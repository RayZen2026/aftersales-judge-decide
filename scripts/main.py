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
    """YAML 加载（Phase 4 升级为 L4 严格替换）。"""
    p = Path(path) if path else CONFIG_PATH
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_logging(level: str = "INFO") -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return logging.getLogger("aftersales-judge-decide")


def allocate_correction(responsibility: dict) -> dict:
    """分配校正（纯数学，D-20260806-008）——供 agent_single.py import。"""
    p = responsibility.get("platform", 0) or 0
    s = responsibility.get("merchant", 0) or 0
    total = p + s
    if total == 0:
        return {"platform": 0, "merchant": 0}
    return {"platform": round(p * 100 / total), "merchant": round(s * 100 / total)}


def _make_backend(cfg: dict):
    """开发期 DashScopeBackend；生产 MiaodaBackend（Phase 4 切换）。"""
    from llm import DashScopeBackend  # noqa: PLC0415
    return DashScopeBackend(cfg)


# ============================================================
# Stage 1: 触发 + 拉取
# ============================================================

def check_stale_and_reclaim(cfg: dict, fb) -> int:
    """stale 5min 兜底重抢：扫处理中记录，超时的重置为 failed 供下次 cron 重试。

    fb: feishu_bitable 模块（注入便于测试）。返回重抢数量。
    """
    from data_loader import record_list, normalize_date  # noqa: PLC0415
    from lock import check_lockable, is_stale            # noqa: PLC0415
    from state_machine import STATE_TABLE_VALUES         # noqa: PLC0415

    stale_min = cfg["lock"]["stale_minutes"]
    now = datetime.now(CST)
    tt = cfg["task_table"]
    env = record_list(cfg, app_token=tt["app_token"], table_id=tt["table_id"],
                      field_names=["升级售后单号", "处理状态", "更新时间"],
                      filter_json=json.dumps({"logic": "and", "conditions": [
                          ["处理状态", "==", STATE_TABLE_VALUES["processing"]]
                      ]}, ensure_ascii=False), limit=200)
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
                 judgment_rules: list, backend, fb, notify_dedup) -> str:
    """单条处理（抢锁→判责→写表→释放）。返回最终状态内部键。"""
    import agent_single                            # noqa: PLC0415
    from failure_handler import decide             # noqa: PLC0415
    from feishu_notify import notify               # noqa: PLC0415
    from lock import check_lockable, acquire_fields  # noqa: PLC0415
    from state_machine import (                    # noqa: PLC0415
        from_table_value, to_table_value, assert_transition,
    )

    task_row = sample["task"]
    item_id = sample["item_id"] or "?"
    now = datetime.now(CST)
    stale_min = cfg["lock"]["stale_minutes"]

    # 抢锁（防御性）
    state = from_table_value(task_row.get("处理状态") or "未处理")
    lock_check = check_lockable(state, task_row.get("更新时间"), now, stale_min)
    if not lock_check.acquirable:
        logger.info("跳过 %s: %s", item_id, lock_check.reason)
        return state
    fb.acquire_lock(cfg, record_id)
    logger.info("已抢锁 %s (%s)", item_id, lock_check.reason)

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
        fb.release_lock(cfg, record_id, target)
        if decision.notify:
            notify(cfg, notify_dedup, item_id, result.failure_type or "llm_ability_exceeded",
                   "; ".join(result.format_errors or [result.failure_type or ""]), now)
        if decision.write_result_table and result.output:
            _write_result(cfg, fb, item_id, result.output)
        logger.info("%s 失败 %s → %s", item_id, result.failure_type, target)
        return target

    # 成功或需人工（manual_review_signal）
    if result.manual_review_signal:
        target = "manual_review"
        fb.release_lock(cfg, record_id, target)
        notify(cfg, notify_dedup, item_id, "rule_conflict",
               "规则无匹配或模型判定需人工", now)
        if result.output:
            _write_result(cfg, fb, item_id, result.output)
        logger.info("%s 需人工", item_id)
        return target

    # 成功终态
    fb.release_lock(cfg, record_id, "completed")
    _write_result(cfg, fb, item_id, result.output)
    logger.info("%s 完成: action=%s amount=%s",
                item_id,
                result.output.get("action"),
                result.output.get("amount"))
    return "completed"


def _write_result(cfg: dict, fb, item_id: str, output: dict) -> None:
    fields = fb.build_result_fields(item_id, output)
    try:
        fb.upsert_result_record(cfg, fields)
    except Exception as e:  # noqa: BLE001
        logger.error("写判责结果表失败 %s: %s", item_id, e)


# ============================================================
# cmd_auto / cmd_manual / cmd_probe / cmd_test
# ============================================================

def _run_workflow(cfg: dict) -> dict:
    """auto/manual 共用的完整 Workflow。"""
    import feishu_bitable as fb                    # noqa: PLC0415
    from feishu_notify import NotifyDedup          # noqa: PLC0415

    notify_dedup = NotifyDedup(window_hours=cfg["notify"]["dedup"]["window_hours"])
    backend = _make_backend(cfg)

    # Stage 1
    tasks, record_ids = stage1_fetch(cfg)
    if not tasks:
        logger.info("无待处理任务, 本次 cron 空跑 (原则 10 不通知)")
        return {"processed": 0, "skipped": 0, "results": {}}

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
        final_state = process_item(cfg, sample, rid, judgment_rules, backend, fb, notify_dedup)
        results[sample["item_id"]] = final_state

    stats = {s: sum(1 for v in results.values() if v == s)
             for s in ("completed", "failed", "manual_review", "pending", "processing")}
    return {"processed": len(results), "results": results, "stats": stats}


def cmd_auto(args, logger_) -> dict:
    cfg = load_config()
    result = _run_workflow(cfg)
    logger_.info("auto 完成: %s", result["stats"])
    return {"mode": "auto", **result}


def cmd_manual(args, logger_) -> dict:
    """手动处理单条（manual 模式，直接跳 Stage1 拉取视图只取指定单号）。"""
    import feishu_bitable as fb                    # noqa: PLC0415
    from feishu_notify import NotifyDedup          # noqa: PLC0415
    from data_loader import record_list            # noqa: PLC0415

    cfg = load_config()
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
    final = process_item(cfg, samples[0], env.record_ids[0],
                         judgment_rules, backend, fb, notify_dedup)
    return {"mode": "manual", "item_id": args.item_id, "final_state": final}


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
    subparsers.add_parser("auto", help="cron 自动模式")
    p_manual = subparsers.add_parser("manual", help="手动处理单条")
    p_manual.add_argument("--item-id", required=True)

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
