#!/usr/bin/env python3
"""
aftersales-judge-decide main.py — Phase 3 主流程实现

架构（architecture.md §1 + §2 + §3）：
  Stage 1: 触发 + 拉取（batch）
    - cron 空跑检测（cron 空跑不通知，原则 10）
    - stale 5min 兜底重抢（原则 8）
    - 视图「近两天数据」拉取（D-20260812-006）+ 客户端状态过滤
  Stage 2: 数据准备（batch）
    - 维度 JOIN（商品 + 门店）
    - 门店分层 AST 求值（apply_tier，不调 LLM，原则 2）
    - 判责规则 AST 拉取（AGENT prompt 注入用）
  Stage 3: per-item 串行
    - 抢锁（lock.check_lockable → feishu_bitable.acquire_lock）
    - 字段匹配检验（必填字段缺失 → 通知 + 释放 + 跳过）
    - agent_single.run（1-AGENT 完整判责，D-20260812-007）
    - failure_handler.decide → 状态机 + 写表 + 通知（9 类失败 → 3 大类）
    - 释放锁

CLI 模式（v2.0 §5.1）：
  auto   - cron 自动（默认，对外暴露）
  manual - 手动单条（对外暴露）
  probe  - 探针（开发内部，不进 SKILL.md body）
  test   - 端到端（开发内部，Phase 4 实现）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
CST = timezone(timedelta(hours=8))

logger = logging.getLogger("aftersales-judge-decide")


# ============================================================
# 配置与初始化
# ============================================================

def load_config(path: Optional[Path] = None) -> dict:
    """YAML 加载 + L4 严格替换（${VAR} 引用 env，缺失即 abort）。

    支持 ${VAR:default} 默认值语法（v0.0 2026-08-17）：VAR 缺失时用 default，
    缺省仍按 L4 严格模式 abort。
    只替换 YAML 值部分的 ${VAR}；注释行（# 开头）不处理，
    防止注释中的示例文字被误匹配（如 config 头部说明注释）。
    """
    p = Path(path) if path else CONFIG_PATH
    with open(p, "r", encoding="utf-8") as f:
        lines = f.readlines()
    import re as _re
    errors: list[str] = []
    processed = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # 注释行：原样保留，不做替换
            processed.append(line)
            continue
        def _replace(m, _errors=errors):
            var = m.group(1)
            default = m.group(2)  # None if no :default
            val = os.environ.get(var)
            if val is None:
                if default is not None:
                    return default
                _errors.append(var)
                return m.group(0)
            return val
        processed.append(_re.sub(r"\$\{([A-Z][A-Z0-9_]*)(?::([^}]*))?\}", _replace, line))
    if errors:
        raise RuntimeError(
            f"config.yaml L4 严格替换失败：env 变量缺失 {errors}。"
            "先 `set -a && source .env && set +a` 或配置生产 env。")
    return yaml.safe_load("".join(processed))


# ============================================================
# Preflight（v2.0 §7.6 + config.yaml preflight 块）
# ============================================================

class PreflightError(RuntimeError):
    """preflight abort 级失败，阻断启动。"""


def _pf_env_present(check: dict) -> tuple[bool, str]:
    missing = [t for t in (check.get("targets") or []) if not os.environ.get(t)]
    if missing:
        return False, f"env 变量缺失: {missing}"
    return True, "ok"


def _pf_lark_read(check: dict, cfg: dict) -> tuple[bool, str]:
    """lark-cli bot 可读指定表（fetch 1 条验证）。"""
    from data_loader import record_list, LarkCliError  # noqa: PLC0415
    table_keys = check.get("targets") or []
    table_map = {
        "task_table": cfg.get("task_table", {}),
        "result_table": cfg.get("dimensions", {}).get("result_table", {}),
        "product_dimension_table": cfg.get("dimensions", {}).get("product_dimension_table", {}),
        "store_table": cfg.get("dimensions", {}).get("store_table", {}),
    }
    failed = []
    for key in table_keys:
        tbl = table_map.get(key, {})
        app_token = tbl.get("app_token")
        table_id = tbl.get("table_id")
        if not app_token or not table_id:
            failed.append(f"{key}(config 缺 app_token/table_id)")
            continue
        try:
            record_list(cfg, app_token=app_token, table_id=table_id, limit=1)
        except LarkCliError as e:
            failed.append(f"{key}: {e}")
    if failed:
        return False, f"bitable 不可达: {failed}"
    return True, "ok"


def _pf_llm_ping(check: dict, cfg: dict) -> tuple[bool, str]:
    """LLM 链第一个模型 ping（开发环境 DashScope；生产 Miaoda 暂跳过）。"""
    if os.environ.get("BITABLE_WRITE_ENABLED") != "1":
        # 开发期不强制 ping 生产 LLM（妙搭未接入）
        return True, "跳过(开发环境)"
    try:
        backend = _make_backend(cfg)
        chain = ["qwen-plus-latest"]  # 开发占位；生产改为 config llm.shared_chain[0]
        from llm import call_with_fallback  # noqa: PLC0415
        res = call_with_fallback(backend, "ping", chain,
                                 {"max_tokens": 5, "temperature": 0},
                                 cfg["llm"]["retry"])
        if res.error:
            return False, f"LLM ping 失败: {res.error}"
        return True, "ok"
    except Exception as e:  # noqa: BLE001
        return False, f"LLM ping 异常: {e}"


def _pf_disk_space(check: dict) -> tuple[bool, str]:
    import shutil  # noqa: PLC0415
    threshold_mb = check.get("threshold_mb", 500)
    free_mb = shutil.disk_usage(BASE_DIR).free // (1024 * 1024)
    if free_mb < threshold_mb:
        return False, f"磁盘空间不足: {free_mb}MB < {threshold_mb}MB"
    return True, f"{free_mb}MB 可用"


def _pf_cron_registered(check: dict, cfg: dict) -> tuple[bool, str]:
    """cron 冲突检测（本地 CLI-only 环境跳过，OpenClaw 部署时实测）。"""
    return True, "跳过(本地 CLI-only;OpenClaw 部署时检验)"


def _pf_store_tier_resolvable(check: dict, cfg: dict) -> tuple[bool, str]:
    """LRN-20260817-004：preflight 强约束验 store-tier-rules scripts 可导入。

    避免 store_tier 静默降级为 null 导致 A/B/C/D 保护没生效。
    """
    from data_loader import resolve_store_tier_scripts_dir
    targets = check.get("targets") or ["apply_tier_rules"]
    scripts_dir = resolve_store_tier_scripts_dir(cfg)
    if not scripts_dir.is_dir():
        return False, f"scripts 目录不存在: {scripts_dir} (设 STORE_TIER_RULES_DIR env 或修 config.yaml scripts_dir_default)"
    missing = [t for t in targets if not (scripts_dir / f"{t}.py").is_file()]
    if missing:
        return False, f"scripts 目录缺文件: {missing} (在 {scripts_dir})"
    # 真实 import 验 (apply_tier_rules 依赖 _config)
    import importlib
    sys.path_mod = [str(scripts_dir)]
    saved = [p for p in sys.path if p]
    try:
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        mod = importlib.import_module("apply_tier_rules")
        if not hasattr(mod, "apply_tier") or not callable(mod.apply_tier):
            return False, "apply_tier_rules.py 缺 apply_tier 函数"
    except Exception as e:  # noqa: BLE001
        return False, f"import apply_tier_rules 失败: {type(e).__name__}: {e}"
    finally:
        sys.path[:] = saved
    return True, f"ok ({scripts_dir})"


def run_preflight(cfg: dict) -> list[dict]:
    """运行 config.yaml preflight 块的 5 项检查 + 环境一致性检查。

    返回 [{name, ok, message}]；abort 级失败抛 PreflightError。
    开发期 load_config 未做 ${VAR} 替换时部分检查会因 env 缺失而 warn。
    """
    results = []

    # 【新增】环境一致性检查（优先执行，在所有其他检查之前）
    env = cfg.get("environment", "").lower()
    use_prod_chain = cfg.get("llm", {}).get("use_production_chain", False)

    if env == "production":
        # 生产必须用生产链
        if not use_prod_chain:
            results.append({
                "name": "environment_consistency",
                "ok": False,
                "level": "abort",
                "message": "生产环境必须 use_production_chain=true；当前 ENV=production 但 llm.use_production_chain=false"
            })
            summary = "\n".join(f"  [{r['level'].upper()}] {r['name']}: {r['message']}"
                                for r in results)
            raise PreflightError(f"preflight 检查失败（abort），启动中止：\n{summary}")
        results.append({
            "name": "environment_consistency",
            "ok": True,
            "level": "ok",
            "message": "环境一致性检查通过（production + use_production_chain=true）"
        })
        logger.info("✅ 环境一致性检查通过（production + use_production_chain=true）")

    elif env == "development":
        # 开发环境警告（允许但提醒）
        # provider 显式设置时（如 dashscope），use_production_chain 不生效，无需告警
        provider_explicit = cfg.get("llm", {}).get("provider", "").lower()
        if use_prod_chain and not provider_explicit:
            results.append({
                "name": "environment_consistency",
                "ok": True,
                "level": "warn",
                "message": "开发环境检测到 use_production_chain=true（非典型配置）"
            })
            logger.warning("⚠️ 开发环境检测到 use_production_chain=true（非典型配置）")
        else:
            results.append({
                "name": "environment_consistency",
                "ok": True,
                "level": "ok",
                "message": "环境一致性检查通过（development）"
            })
            logger.info("✅ 环境一致性检查通过（development）")

    elif env == "staging":
        # staging 允许两种配置（灵活）
        results.append({
            "name": "environment_consistency",
            "ok": True,
            "level": "ok",
            "message": f"环境一致性检查通过（staging, use_production_chain={use_prod_chain}）"
        })
        logger.info(f"✅ 环境一致性检查通过（staging, use_production_chain={use_prod_chain}）")

    else:
        # ENV 缺失或非法
        results.append({
            "name": "environment_consistency",
            "ok": False,
            "level": "abort",
            "message": f"ENV 环境变量非法或缺失: '{env}'；必须设置为 development | production | staging"
        })
        summary = "\n".join(f"  [{r['level'].upper()}] {r['name']}: {r['message']}"
                            for r in results)
        raise PreflightError(f"preflight 检查失败（abort），启动中止：\n{summary}")

    # 原有 5 项检查
    for check in cfg.get("preflight") or []:
        name = check.get("name", "?")
        kind = check.get("check", "")
        fail_action = check.get("fail_action", "abort")
        try:
            if kind == "env_present":
                ok, msg = _pf_env_present(check)
            elif kind == "lark_read":
                ok, msg = _pf_lark_read(check, cfg)
            elif kind == "llm_ping":
                ok, msg = _pf_llm_ping(check, cfg)
            elif kind == "disk_min_mb":
                ok, msg = _pf_disk_space(check)
            elif kind == "cron_registered":
                ok, msg = _pf_cron_registered(check, cfg)
            elif kind == "store_tier_resolvable":
                ok, msg = _pf_store_tier_resolvable(check, cfg)
            else:
                ok, msg = True, f"未知检查类型 {kind}（跳过）"
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"检查异常: {e}"
        level = "ok" if ok else ("warn" if fail_action == "warn_only" else "abort")
        results.append({"name": name, "ok": ok, "level": level, "message": msg})
        if not ok and fail_action == "abort":
            summary = "\n".join(f"  [{r['level'].upper()}] {r['name']}: {r['message']}"
                                for r in results)
            raise PreflightError(
                f"preflight 检查失败（abort），启动中止：\n{summary}")
        logger.log(
            logging.INFO if ok else logging.WARNING,
            "preflight [%s] %s: %s", level.upper(), name, msg)
    return results


def init_logging(level: str = "INFO") -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return logging.getLogger("aftersales-judge-decide")


def allocate_correction(responsibility: dict) -> dict:
    """4方责任分配校正（Phase 5，纯数学）——供 agent_single.py import。

    物流/代理人互斥：只有一方>0，另一方=0。
    platform + merchant + (logistics | agent) = 100
    物流≤30%、代理人≤20%（下游校正会截断）。
    total=0 → {0,0,0,0}（破坏"和=100"不变量，报告视其为格式异常）。

    标准化逻辑（2026-08-18）：
    1. 归一化到100%
    2. 非平台方向上取整到10的倍数
    3. 平台 = 100% - 其他各方之和（确保平台也是10的倍数）
    """
    import math

    p = responsibility.get("platform", 0) or 0
    m = responsibility.get("merchant", 0) or 0
    l = responsibility.get("logistics", 0) or 0
    a = responsibility.get("agent", 0) or 0

    # 互斥约束：物流/代理人二选一，若同时>0则优先物流
    if l > 0 and a > 0:
        a = 0  # 物流优先，代理人归零

    total = p + m + l + a

    if total == 0:
        return {"platform": 0, "merchant": 0, "logistics": 0, "agent": 0}

    # 步骤1: 等比缩放到100
    scale = 100.0 / total
    m_scaled = m * scale
    l_scaled = l * scale
    a_scaled = a * scale

    # 步骤2: 上限截断（物流≤30%、代理人≤20%）
    if l_scaled > 30:
        l_scaled = 30
    if a_scaled > 20:
        a_scaled = 20

    # 步骤3: 非平台方向上取整到10的倍数
    m_std = math.ceil(m_scaled / 10) * 10
    l_std = math.ceil(l_scaled / 10) * 10 if l_scaled > 0 else 0
    a_std = math.ceil(a_scaled / 10) * 10 if a_scaled > 0 else 0

    # 步骤4: 平台反算（确保总和=100且平台是10的倍数）
    p_std = 100 - m_std - l_std - a_std

    # 步骤5: 安全检查（平台不能为负）
    if p_std < 0:
        # 向上取整导致总和>100，需要调整商家（向下取整）
        overflow = -p_std
        m_std = m_std - math.ceil(overflow / 10) * 10
        # 如果商家调整后仍无法满足，则调整物流/代理人
        if m_std < 0:
            if l_std > 0:
                l_std = max(10, l_std + m_std)  # 从物流中扣除
                m_std = 10
            elif a_std > 0:
                a_std = max(10, a_std + m_std)  # 从代理人中扣除
                m_std = 10
        p_std = 100 - m_std - l_std - a_std

    return {
        "platform": p_std,
        "merchant": m_std,
        "logistics": l_std,
        "agent": a_std,
    }


def _make_backend(cfg: dict):
    """根据配置选择 LLM 后端。

    选择逻辑（2026-08-17优化）：
    1. 优先使用 cfg.llm.provider（从env LLM_PROVIDER注入）
       - "dashscope": DashScopeBackend（开发/测试，Qwen DashScope）
       - "miaoda": MiaodaBackend（生产，openclaw subprocess）
    2. 降级到 cfg.llm.use_production_chain（向后兼容）
       - false: DashScopeBackend
       - true: MiaodaBackend
    """
    llm_cfg = cfg.get("llm", {})
    provider = llm_cfg.get("provider", "").lower()

    # 优先使用provider配置
    if provider == "miaoda":
        from llm import MiaodaBackend  # noqa: PLC0415
        return MiaodaBackend(cfg)
    elif provider == "dashscope":
        from llm import DashScopeBackend  # noqa: PLC0415
        return DashScopeBackend(cfg)

    # 降级到use_production_chain（向后兼容）
    use_prod = llm_cfg.get("use_production_chain", False)
    if use_prod:
        from llm import MiaodaBackend  # noqa: PLC0415
        return MiaodaBackend(cfg)
    else:
        from llm import DashScopeBackend  # noqa: PLC0415
        return DashScopeBackend(cfg)


# ============================================================
# Stage 1: 触发 + 拉取
# ============================================================

def check_stale_and_reclaim(cfg: dict, fb) -> int:
    """stale 5min 兜底重抢：扫处理中记录，超时的重置为 failed 供下次 cron 重试。

    fb: feishu_bitable 模块（注入便于测试）。返回重抢数量。
    """
    from data_loader import record_list, normalize_date, LarkCliError  # noqa: PLC0415
    from lock import check_lockable, is_stale            # noqa: PLC0415
    from state_machine import STATE_TABLE_VALUES         # noqa: PLC0415

    stale_min = cfg["lock"]["stale_minutes"]
    now = datetime.now(CST)
    tt = cfg["task_table"]

    try:
        env = record_list(cfg, app_token=tt["app_token"], table_id=tt["table_id"],
                          field_names=["升级售后单号", "处理状态", "更新时间"],
                          filter_json=json.dumps({"logic": "and", "conditions": [
                              ["处理状态", "==", STATE_TABLE_VALUES["processing"]]
                          ]}, ensure_ascii=False), limit=200)
    except LarkCliError as e:
        # 如果filter失败（可能是选项不存在），跳过stale检查
        logger.warning("stale检查跳过: filter失败（可能是'已处理-处理中'选项不存在）: %s", str(e)[:200])
        return 0
    reclaimed = 0
    for row, rid in zip(env.records, env.record_ids):
        if rid and is_stale(row.get("更新时间"), now, stale_min):
            logger.warning("stale 重抢: %s (%s)", row.get("升级售后单号"), rid)
            fb.release_lock(cfg, rid, "failed")
            reclaimed += 1
    return reclaimed


def stage1_fetch(cfg: dict) -> tuple[list[dict], list[str]]:
    """视图拉取 + 客户端状态过滤（D-20260812-006）。返回 (rows, record_ids)。"""
    from data_loader import fetch_tasks_live  # noqa: PLC0415
    limit = cfg["magic_numbers"]["batch_size"]
    env = fetch_tasks_live(cfg, limit=limit)
    return env.records, env.record_ids


# ============================================================
# Stage 2: 数据准备
# ============================================================

def stage2_prepare(cfg: dict, tasks: list[dict]) -> tuple[list[dict], list[dict]]:
    """维度 JOIN + 分层（batch）+ 判责规则拉取。

    返回 (enriched_samples, judgment_rules)。
    enriched_samples[i] = {task, dimension_data, join_meta, item_id, record_id}
    """
    from data_loader import (  # noqa: PLC0415
        fetch_product_dimension, fetch_store_dimension,
        fetch_store_tier_rules, fetch_judgment_rules,
        compute_store_tier, normalize_date,
    )
    # 批量拉取规则（每次 cron 拉一次，batch 内复用）
    try:
        tier_rules = fetch_store_tier_rules(cfg)
    except Exception as e:  # noqa: BLE001
        logger.warning("门店分层规则拉取失败, 全部降级: %s", e)
        tier_rules = None
    judgment_rules = fetch_judgment_rules(cfg)
    samples = []
    for row in tasks:
        order_date = normalize_date(row.get("订单日期"))
        product = fetch_product_dimension(cfg, row.get("商品id"), order_date)
        store = fetch_store_dimension(cfg, row.get("店铺ID"))
        tier, tier_reason = compute_store_tier(cfg, store, tier_rules)
        samples.append({
            "item_id": row.get("升级售后单号"),
            "task": row,
            "dimension_data": {"product": product, "store": store, "store_tier": tier},
            "join_meta": {"product_matched": product is not None,
                          "store_matched": store is not None,
                          "tier_degraded": tier is None,
                          "tier_degrade_reason": tier_reason},
        })
    return samples, judgment_rules


# ============================================================
# Stage 3: per-item 串行
# ============================================================

REQUIRED_TASK_FIELDS = [
    "升级售后单号", "诉求类型", "升级售后类型",
    "商品id", "店铺ID", "订单日期",
]


def _check_required_fields(task_row: dict) -> list[str]:
    return [f for f in REQUIRED_TASK_FIELDS
            if task_row.get(f) in (None, "", -1, "-1")]


def process_item(cfg: dict, sample: dict, record_id: str,
                 judgment_rules: list, backend, fb, notify_dedup, test_mode: bool = False) -> str:
    """单条处理（抢锁→判责→写表→释放）。返回最终状态内部键。

    test_mode=True: 写测试表（test_result_table），跳过抢锁/释放锁
    test_mode=False: 写生产表（result_table），正常抢锁/释放锁
    """
    import agent_single                            # noqa: PLC0415
    from failure_handler import decide             # noqa: PLC0415
    from feishu_notify import notify               # noqa: PLC0415
    from lock import check_lockable, acquire_fields  # noqa: PLC0415
    from state_machine import (                    # noqa: PLC0415
        from_table_value, to_table_value, assert_transition,
    )

    task_row = sample["task"]
    dimension_data = sample.get("dimension_data", {})
    item_id = sample["item_id"] or "?"
    now = datetime.now(CST)
    stale_min = cfg["lock"]["stale_minutes"]

    # test_mode: 跳过抢锁逻辑（测试表独立，可重复运行）
    if not test_mode:
        # 抢锁（防御性）
        state = from_table_value(task_row.get("处理状态") or "未处理")
        lock_check = check_lockable(state, task_row.get("更新时间"), now, stale_min)
        if not lock_check.acquirable:
            logger.info("跳过 %s: %s", item_id, lock_check.reason)
            return state
        fb.acquire_lock(cfg, record_id)
        logger.info("已抢锁 %s (%s)", item_id, lock_check.reason)
    else:
        logger.info("test_mode: 跳过抢锁，直接处理 %s", item_id)

    # 字段匹配检验
    missing = _check_required_fields(task_row)
    if missing:
        logger.warning("%s 必填字段缺失 %s, 释放锁跳过", item_id, missing)
        notify(cfg, notify_dedup, item_id, "appeal_info_insufficient",
               f"必填字段缺失: {missing}", now)
        fb.release_lock(cfg, record_id, "pending")  # 退回待处理
        return "pending"

    # 1-AGENT 判责
    result = agent_single.run(cfg, backend, task_row,
                              sample["dimension_data"], judgment_rules)

    # 9 类失败处理
    if not result.ok:
        decision = decide(result.failure_type or "llm_ability_exceeded")
        target = decision.target_state
        if not test_mode:
            fb.release_lock(cfg, record_id, target)
        if decision.notify:
            notify(cfg, notify_dedup, item_id, result.failure_type or "llm_ability_exceeded",
                   "; ".join(result.format_errors or [result.failure_type or ""]), now)
        if decision.write_result_table and result.output:
            _write_result(cfg, fb, item_id, result.output, task_row=task_row, dimension_data=dimension_data, test_mode=test_mode)
        logger.info("%s 失败 %s → %s", item_id, result.failure_type, target)
        return target

    # 成功或需人工（manual_review_signal）
    if result.manual_review_signal:
        target = "manual_review"
        if not test_mode:
            fb.release_lock(cfg, record_id, target)
        notify(cfg, notify_dedup, item_id, "rule_conflict",
               "规则无匹配或模型判定需人工", now)
        if result.output:
            _write_result(cfg, fb, item_id, result.output, task_row=task_row, dimension_data=dimension_data, test_mode=test_mode)
        logger.info("%s 需人工", item_id)
        return target

    # 成功终态
    if not test_mode:
        fb.release_lock(cfg, record_id, "completed")
    _write_result(cfg, fb, item_id, result.output, task_row=task_row, dimension_data=dimension_data, test_mode=test_mode)
    logger.info("%s 完成: action=%s amount=%s",
                item_id,
                result.output.get("action"),
                result.output.get("amount"))
    return "completed"


def _write_result(cfg: dict, fb, item_id: str, output: dict, task_row: dict = None, dimension_data: dict = None, test_mode: bool = False) -> None:
    """写判责结果表（生产表或测试表）。

    Args:
        cfg: 配置字典
        fb: feishu_bitable模块
        item_id: 升级售后单号
        output: LLM输出结果
        task_row: 任务表原始数据（用于透传输入字段到结果表）
        dimension_data: 维度数据（用于获取门店等级等计算字段）
        test_mode: True=写测试表（22字段），False=写生产表（5字段）
    """
    # 获取目标表ID，判断是否为测试表
    result_table_id = cfg['dimensions']['result_table']['table_id']
    fields = fb.build_result_fields(item_id, output, task_row=task_row, dimension_data=dimension_data, test_mode=test_mode, table_id=result_table_id)
    try:
        fb.upsert_result_record(cfg, fields, test_mode=test_mode)
    except Exception as e:  # noqa: BLE001
        logger.error("写判责结果表失败 %s: %s", item_id, e)


# ============================================================
# cmd_auto / cmd_manual / cmd_probe / cmd_test
# ============================================================

def _run_workflow(cfg: dict, limit: int = None, test_mode: bool = False) -> dict:
    """auto/manual 共用的完整 Workflow。

    Args:
        cfg: 配置字典
        limit: 最多处理多少条记录（None=使用配置中的batch_size）
        test_mode: True=写入测试表，False=写入生产表
    """
    import feishu_bitable as fb                    # noqa: PLC0415
    from feishu_notify import NotifyDedup          # noqa: PLC0415

    notify_dedup = NotifyDedup(window_hours=cfg["notify"]["dedup"]["window_hours"])
    backend = _make_backend(cfg)

    # 如果指定了limit，临时覆盖batch_size
    original_batch_size = cfg["magic_numbers"]["batch_size"]
    if limit and limit > 0:
        cfg["magic_numbers"]["batch_size"] = limit
        logger.info(f"临时设置 batch_size={limit}")

    try:
        # Stage 1
        tasks, record_ids = stage1_fetch(cfg)
        if not tasks:
            logger.info("无待处理任务, 本次 cron 空跑 (原则 10 不通知)")
            empty_stats = {s: 0 for s in ("completed", "failed", "manual_review", "pending", "processing")}
            return {"processed": 0, "skipped": 0, "results": {}, "stats": empty_stats, "test_mode": test_mode}

        # stale 兜底（在 Stage1 拉出列表后，Stage3 遍历前）
        check_stale_and_reclaim(cfg, fb)

        # Stage 2
        samples, judgment_rules = stage2_prepare(cfg, tasks)

        # Stage 3
        results: dict[str, str] = {}
        for sample, rid in zip(samples, record_ids):
            if not rid:
                logger.warning("record_id 缺失, 跳过 %s", sample.get("item_id"))
                continue
            final_state = process_item(cfg, sample, rid, judgment_rules, backend, fb, notify_dedup, test_mode=test_mode)
            results[sample["item_id"]] = final_state

        stats = {s: sum(1 for v in results.values() if v == s)
                 for s in ("completed", "failed", "manual_review", "pending", "processing")}
        return {"processed": len(results), "results": results, "stats": stats, "test_mode": test_mode}
    finally:
        # 恢复原始batch_size
        cfg["magic_numbers"]["batch_size"] = original_batch_size


def cmd_auto(args, logger_) -> dict:
    cfg = load_config()
    run_preflight(cfg)
    limit = getattr(args, 'limit', None)
    test_mode = getattr(args, 'test_mode', False)
    result = _run_workflow(cfg, limit=limit, test_mode=test_mode)
    logger_.info("auto 完成: %s", result["stats"])
    return {"mode": "auto", **result}


def cmd_manual(args, logger_) -> dict:
    """手动处理单条（manual 模式，直接跳 Stage1 拉取视图只取指定单号）。"""
    import feishu_bitable as fb                    # noqa: PLC0415
    from feishu_notify import NotifyDedup          # noqa: PLC0415
    from data_loader import record_list            # noqa: PLC0415

    cfg = load_config()
    run_preflight(cfg)
    tt = cfg["task_table"]
    field_names = cfg["probe"]["task_fetch"]["field_names"]
    env = record_list(cfg, app_token=tt["app_token"], table_id=tt["table_id"],
                      field_names=field_names,
                      filter_json=json.dumps({"logic": "and", "conditions": [
                          ["升级售后单号", "==", args.item_id]
                      ]}, ensure_ascii=False), limit=1)
    if not env.records:
        return {"mode": "manual", "error": f"单号不存在: {args.item_id}"}

    samples, judgment_rules = stage2_prepare(cfg, env.records)
    notify_dedup = NotifyDedup(window_hours=cfg["notify"]["dedup"]["window_hours"])
    backend = _make_backend(cfg)
    test_mode = getattr(args, 'test_mode', False)  # 支持--test-mode标志
    final = process_item(cfg, samples[0], env.record_ids[0],
                         judgment_rules, backend, fb, notify_dedup, test_mode=test_mode)
    return {"mode": "manual", "item_id": args.item_id, "final_state": final, "test_mode": test_mode}


def cmd_probe(args, logger_) -> dict:
    """probe 模式：委托 probe_llm.run_probe（开发内部）。"""
    import probe_llm                               # noqa: PLC0415
    cfg = load_config()
    logger_.info("probe mode=%s runs=%s", args.probe_mode, args.runs)
    return probe_llm.run_probe(args, cfg, logger_)


def cmd_test(args, logger_) -> dict:
    """test 模式：Phase 4 端到端（占位）。"""
    return {"mode": "test", "status": "Phase 4 实现（test_main_table）"}


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        prog="aftersales-judge-decide",
        description="升级售后判责主流程 SKILL")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # 对外暴露（SKILL.md body 只写这两个）
    p_auto = subparsers.add_parser("auto", help="cron 自动模式")
    p_auto.add_argument("--limit", type=int, default=None, help="限制处理条数（测试用）")
    p_auto.add_argument("--test-mode", action="store_true", help="写测试表而非生产表")

    p_manual = subparsers.add_parser("manual", help="手动处理单条")
    p_manual.add_argument("--item-id", required=True)
    p_manual.add_argument("--test-mode", action="store_true", help="写测试表（15字段）而非生产表（5字段）")

    # 开发内部（不进 SKILL.md body，CLAUDE.md §"开发模式"）
    p_probe = subparsers.add_parser("probe", help="探针（开发内部）")
    p_probe.add_argument("--probe-mode", choices=["1agent", "3agent", "both"], default="both")
    p_probe.add_argument("--samples-file", default=None)
    p_probe.add_argument("--samples", type=int, default=None)
    p_probe.add_argument("--runs", type=int, default=None)

    p_test = subparsers.add_parser("test", help="端到端（开发内部，Phase 4）")
    p_test.add_argument("--table-id", required=True)

    args = parser.parse_args()
    log = init_logging()
    dispatch = {
        "auto": cmd_auto, "manual": cmd_manual,
        "probe": cmd_probe, "test": cmd_test,
    }
    result = dispatch[args.mode](args, log)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
