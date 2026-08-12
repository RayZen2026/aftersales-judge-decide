#!/usr/bin/env python3
"""
data_loader.py — 数据层探针版（Phase 1 T1.4a）

职责：live lark-cli / CSV 两来源 → 统一 SampleSet JSON（探针数据契约）。
只读，不写飞书。Phase 2 feishu_bitable.py 复用同一批 fetch/JOIN/coerce 函数签名，
只换生产实现（加锁/写表另起），数据契约不变。

统一 SampleSet schema（schema_version 1.0）:
{
  "schema_version": "1.0",
  "source": "live" | "csv",
  "fetched_at": "...+08:00",
  "samples": [{
    "item_id", "record_id",
    "task": {任务表字段, 表头原名},           # 订单日期 规范化 YYYY-MM-DD + 订单日期_raw 留原值
    "dimension_data": {"product": {...}|null, "store": {...}|null, "store_tier": "A"|"B"|"C"|"D"|"其他"|null},
    "join_meta": {"product_matched", "product_date_key", "store_matched",
                   "tier_degraded", "tier_degrade_reason"},
    "expected": null | {...}                  # 人工标注（Round 2 填充）
  }],
  "run_context": {"judgment_rules": [...], "judgment_rules_count": N,
                   "store_tier_rules_meta": {"date","version"}|null}
}

CLI:
  python scripts/data_loader.py fetch            --limit 5 [--out PATH]
  python scripts/data_loader.py from-csv         --task-csv PATH [--annotation-csv PATH] [--no-live-join] [--out PATH]
  python scripts/data_loader.py dump-field-types [--out PATH]
  python scripts/data_loader.py fetch-rules      --kind judgment|store-tier

依赖约定（store-tier-rules 集成）:
  只 import apply_tier（纯函数）。禁调 load_latest_rules——它走 lark-cli --as user
  + 沙箱 config，本地必挂；规则 JSON 由本脚本 bot lark-cli 自拉后作参数传入。
"""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger("data_loader")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
CST = timezone(timedelta(hours=8))  # Asia/Shanghai 无夏令时，固定 +08:00

SCHEMA_VERSION = "1.0"

# apply_tier 所需 6 核心统计字段（store-tier-rules references/output-schema.md）
TIER_STAT_FIELDS = [
    "近90天下单天数",
    "近30天下单金额",
    "近7天平台抽佣金额",
    "30日售后赔付率",
    "近7天下单天数",
    "m13到m7下单天数",
]


class LarkCliError(RuntimeError):
    """lark-cli 调用失败（非零退出 / ok=false / 输出非 JSON）"""


# ============================================================
# 配置
# ============================================================

def load_config(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else CONFIG_PATH
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if "probe" not in cfg:
        raise KeyError("config.yaml 缺 probe 块（Phase 1 T1.4a 要求）")
    return cfg


def resolve_probe_output_dir(cfg: dict) -> Path:
    raw = os.environ.get("PROBE_OUTPUT_DIR") or cfg["probe"].get("output_dir") or "probes"
    d = Path(raw)
    if not d.is_absolute():
        d = BASE_DIR / d
    d.mkdir(parents=True, exist_ok=True)
    return d


# ============================================================
# lark-cli subprocess 封装
# ============================================================

def lark_cli_bin(cfg: dict) -> str:
    env_bin = os.environ.get("LARK_CLI_BIN")
    if env_bin:
        return env_bin
    return str(BASE_DIR / "node_modules" / ".bin" / "lark-cli")


def run_lark_cli(args: list[str], cfg: dict, timeout: int = 120) -> dict:
    """跑 lark-cli 并解包 envelope。

    防御两种形态：
    - 外层信封 {"ok": true, "identity": "bot", "data": {<envelope>}}（lark-cli --json 原始输出）
    - 裸 envelope {data, fields, field_id_list, ...}（如 probes/raw_task_10.json 存档形态）
    """
    cmd = [lark_cli_bin(cfg)] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LarkCliError(f"lark-cli 执行失败: {e}") from e
    if r.returncode != 0:
        raise LarkCliError(f"lark-cli rc={r.returncode}: {(r.stderr or r.stdout)[:500]}")
    out = (r.stdout or "").strip()
    if not out:
        raise LarkCliError("lark-cli stdout 为空")
    try:
        obj = json.loads(out)
    except json.JSONDecodeError as e:
        raise LarkCliError(f"lark-cli stdout 非 JSON: {e}; head={out[:200]}") from e
    return unwrap_envelope(obj)


def unwrap_envelope(obj: Any) -> dict:
    """外层 {ok,...} 信封解包；ok=false 抛错；裸 envelope 原样返回。"""
    if isinstance(obj, dict) and "ok" in obj:
        if not obj.get("ok"):
            err = obj.get("error") or {}
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise LarkCliError(f"lark-cli api error: {msg}")
        return obj.get("data") or {}
    return obj


@dataclass
class Envelope:
    records: list[dict] = field(default_factory=list)   # 字段名 → 值
    field_types: dict[str, str] = field(default_factory=dict)  # 字段名 → text/number/datetime/formula
    record_ids: list[Optional[str]] = field(default_factory=list)
    has_more: bool = False


def record_list(cfg: dict, *, app_token: str, table_id: str,
                field_names: Optional[list[str]] = None,
                view_id: Optional[str] = None,
                filter_json: Optional[str] = None,
                sort_json: Optional[str] = None,
                limit: Optional[int] = None,
                page_size: int = 200, max_pages: int = 20) -> Envelope:
    """base +record-list 分页拉取。field_names 必须显式投影（不投影返回列数不可控）。

    ⚠️ view_id 与 filter_json 互斥使用：实测 --filter-json 会**完全覆盖**视图过滤
    （视图时间窗丢失）。按视图拉时额外条件走客户端过滤。
    """
    env = Envelope()
    offset = 0
    last_has_more = False
    for _ in range(max_pages):
        page_limit = page_size if limit is None else min(page_size, limit - len(env.records))
        if page_limit <= 0:
            break
        args = ["base", "+record-list",
                "--base-token", app_token, "--table-id", table_id]
        if view_id:
            args += ["--view-id", view_id]
        for name in field_names or []:
            args += ["--field-id", name]
        if filter_json:
            args += ["--filter-json", filter_json]
        if sort_json:
            args += ["--sort-json", sort_json]
        args += ["--offset", str(offset), "--limit", str(page_limit), "--json"]
        data = run_lark_cli(args, cfg)
        rows = data.get("data") or []
        names = data.get("fields") or []
        types = data.get("field_type_list") or []
        rids = data.get("record_id_list") or []
        if names and types:
            env.field_types = dict(zip(names, types))
        for i, row in enumerate(rows):
            env.records.append(dict(zip(names, row)))
            env.record_ids.append(rids[i] if i < len(rids) else None)
        last_has_more = bool(data.get("has_more"))
        if not last_has_more or not rows:
            break
        offset += len(rows)
    env.has_more = last_has_more and (limit is None or len(env.records) < limit)
    return env


# ============================================================
# 类型处理
# ============================================================

def normalize_date(value: Any) -> Optional[str]:
    """任意 ISO8601 → +08:00 当地 YYYY-MM-DD。

    任务表 订单日期=2026-08-01T00:00+08 × 维度表 日期=2026-08-01T08:00+08 → 同日期（JOIN 键）。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):  # 防御：epoch ms
        try:
            return datetime.fromtimestamp(value / 1000, tz=CST).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
        return m.group(1) if m else None
    if dt.tzinfo is None:
        return dt.date().isoformat()
    return dt.astimezone(CST).date().isoformat()


def coerce_value(value: Any, ftype: Optional[str]) -> Any:
    """CSV 字符串 → number/datetime/text。live JSON 已带类型，原样返回。

    formula 一律保 str（飞书 formula 字段返回字符串数字 "0"/"1"/"-1"，不当数值用）。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    s = value.strip()
    if s == "":
        return None
    if (ftype or "").lower() == "number":
        try:
            f = float(s)
        except ValueError:
            logger.warning("number 字段值无法解析, 保留原字符串: %r", value)
            return s
        return int(f) if "." not in s and f.is_integer() else f
    return s  # text / datetime / formula / 未知类型


def _guess_coerce(value: Optional[str]) -> Any:
    """field_types.json 无条目时的保守推断（CSV 未映射列），附 warning。"""
    if value is None:
        return None
    s = value.strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def load_field_types(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else BASE_DIR / "assets" / "field_types.json"
    if not p.exists():
        logger.warning("field_types.json 不存在(%s), CSV coerce 退化为保守推断 (先跑 dump-field-types)", p)
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_field_types(cfg: dict, out_path: Optional[str] = None) -> Path:
    """live 拉 1 页生成 {表别名: {字段名: 类型}} 快照——CSV coerce 基线 + 字段漂移回归校验。"""
    ast_j = cfg["ast_rules"]["aftersales_judgment"]["fetch"]
    tables = {
        "task_table": (cfg["task_table"]["app_token"], cfg["task_table"]["table_id"]),
        "product_dimension_table": (cfg["dimensions"]["product_dimension_table"]["app_token"],
                                    cfg["dimensions"]["product_dimension_table"]["table_id"]),
        "store_table": (cfg["dimensions"]["store_table"]["app_token"],
                        cfg["dimensions"]["store_table"]["table_id"]),
        "judgment_rules_table": (ast_j["app_token"], ast_j["table_id"]),
    }
    snapshot: dict[str, dict] = {}
    for key, (app_token, table_id) in tables.items():
        env = record_list(cfg, app_token=app_token, table_id=table_id, limit=1)
        snapshot[key] = env.field_types
        logger.info("field_types[%s]: %d 字段", key, len(env.field_types))
    out = Path(out_path) if out_path else BASE_DIR / "assets" / "field_types.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ============================================================
# live fetch
# ============================================================

def _filter_eq(field_name: str, value: Any) -> str:
    return json.dumps({"logic": "and", "conditions": [[field_name, "==", value]]},
                      ensure_ascii=False)


def _sort_json(spec_sort: list[dict]) -> Optional[str]:
    if not spec_sort:
        return None
    return json.dumps([{"field": s["field"], "desc": s.get("direction", "asc") == "desc"}
                       for s in spec_sort], ensure_ascii=False)


def fetch_tasks_live(cfg: dict, limit: int) -> Envelope:
    """按视图「近两天数据」拉取（不拉全量，确认 2026-08-12 拍板），客户端过滤处理状态。

    视图过滤 = 审批创建时间 > Yesterday（相对滚动窗口，无法用 filter-json 表达）；
    且 --filter-json 与 --view-id 同传会覆盖视图过滤（实测），故状态过滤走客户端；
    拉取范围 = 未处理 + 已处理-失败（architecture.md §2 拉取矩阵：失败单 cron 兜底重试）；
    limit 在过滤后应用。
    """
    tt = cfg["task_table"]
    view = tt.get("fetch_view") or {}
    view_id = view.get("id") or view.get("name")
    if not view_id:
        raise KeyError("config.yaml task_table.fetch_view 缺失（拉取范围必须按视图，禁止全量）")
    names = cfg["probe"]["task_fetch"]["field_names"]
    env = record_list(cfg, app_token=tt["app_token"], table_id=tt["table_id"],
                      field_names=names, view_id=view_id)
    total = len(env.records)
    status_in = set(cfg["probe"]["task_fetch"].get("status_in") or ["未处理", "已处理-失败"])
    kept = [(r, rid) for r, rid in zip(env.records, env.record_ids)
            if r.get("处理状态") in status_in][:limit]
    env.records = [r for r, _ in kept]
    env.record_ids = [rid for _, rid in kept]
    logger.info("任务表拉取: 视图 %s 共 %d 条 → 处理状态∈%s 保留 %d 条 (limit %d)",
                view.get("name", view_id), total, sorted(status_in), len(env.records), limit)
    return env


def fetch_product_dimension(cfg: dict, product_id: Any, order_date_key: Optional[str]) -> Optional[dict]:
    """商品维度 = (商品id × 日期) 历史表：服务端按 商品id 过滤，客户端日期级匹配。

    不用 lark-cli ExactDate 日期过滤（语法语义未实测）；命中多行取 日期 desc 首行。
    """
    if product_id is None or not order_date_key:
        return None
    dim = cfg["dimensions"]["product_dimension_table"]
    names = [f["name"] for f in dim["select_fields"]]
    env = record_list(cfg, app_token=dim["app_token"], table_id=dim["table_id"],
                      field_names=names, filter_json=_filter_eq("商品id", product_id),
                      limit=200)
    candidates = [r for r in env.records if normalize_date(r.get("日期")) == order_date_key]
    if not candidates:
        return None
    candidates.sort(key=lambda r: str(r.get("日期") or ""), reverse=True)
    return candidates[0]


def fetch_store_dimension(cfg: dict, store_id: Any) -> Optional[dict]:
    """门店维度 = 快照表（每店 1 行），按 店铺id 过滤取首行。"""
    if store_id is None:
        return None
    dim = cfg["dimensions"]["store_table"]
    names = [f["name"] for f in dim["select_fields"]]
    env = record_list(cfg, app_token=dim["app_token"], table_id=dim["table_id"],
                      field_names=names, filter_json=_filter_eq("店铺id", store_id),
                      limit=1)
    return env.records[0] if env.records else None


def fetch_store_tier_rules(cfg: dict) -> dict:
    """门店分层规则表最新一行（sort 日期 desc limit 1）→ 解析 rules JSON。

    字段值可能是 str 或 [{text:...}] 段列表（对齐 store-tier-rules load_latest_rules 归一逻辑）。
    """
    spec = cfg["ast_rules"]["store_tier"]["fetch"]
    fetch_fields = [f["name"] for f in spec.get("fetch_fields", [])] or None
    env = record_list(cfg, app_token=spec["app_token"], table_id=spec["table_id"],
                      field_names=fetch_fields, sort_json=_sort_json(spec.get("sort") or []),
                      limit=spec.get("limit", 1))
    if not env.records:
        raise LarkCliError("门店分层规则表为空")
    raw = env.records[0].get("门店分层规则")
    if isinstance(raw, list):
        raw = "".join(seg.get("text", "") for seg in raw if isinstance(seg, dict))
    if not raw:
        raise LarkCliError("门店分层规则字段为空")
    return json.loads(raw)


def fetch_judgment_rules(cfg: dict, limit: int = 100) -> list[dict]:
    """判责规则 AST（filter 是否生效=是，sort 优先级 desc，5 字段）——AGENT 2 / single 模板注入用。"""
    spec = cfg["ast_rules"]["aftersales_judgment"]["fetch"]
    fetch_fields = [f["name"] for f in spec.get("fetch_fields", [])] or None
    filter_json = None
    conds = []
    for c in spec.get("filter") or []:
        op = "==" if c.get("op") == "eq" else c.get("op")
        conds.append([c["field"], op, c["value"]])
    if conds:
        filter_json = json.dumps({"logic": "and", "conditions": conds}, ensure_ascii=False)
    env = record_list(cfg, app_token=spec["app_token"], table_id=spec["table_id"],
                      field_names=fetch_fields, filter_json=filter_json,
                      sort_json=_sort_json(spec.get("sort") or []), limit=limit)
    logger.info("判责规则 AST: %d 条 (生效)", len(env.records))
    return env.records


# ============================================================
# store-tier-rules 集成（只 import apply_tier 纯函数）
# ============================================================

def resolve_store_tier_scripts_dir(cfg: dict) -> Path:
    env_dir = os.environ.get("STORE_TIER_RULES_DIR")
    if env_dir:
        return Path(env_dir)
    rel = cfg["probe"].get("store_tier", {}).get(
        "scripts_dir_default", "submodules/store-tier-rules/scripts")
    return BASE_DIR / rel


def _to_number(v: Any) -> Any:
    """formula 字段返回字符串数字（如 30日售后赔付率='0.073...'），apply_tier 需数值。"""
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return v
    return v


def compute_store_tier(cfg: dict, store_row: Optional[dict],
                       tier_rules: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """apply_tier(shop_id, rules, store_stats) → A/B/C/D/其他。

    失败一律降级 (None, reason)，不中断探针（degrade_on_failure）。
    """
    if store_row is None:
        return None, "store dimension JOIN miss"
    if not tier_rules:
        return None, "store tier rules 未加载"
    scripts_dir = resolve_store_tier_scripts_dir(cfg)
    if not scripts_dir.is_dir():
        return None, f"store-tier-rules scripts 目录不存在: {scripts_dir}"
    try:
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        mod = importlib.import_module("apply_tier_rules")
        stats = {k: _to_number(store_row.get(k)) for k in TIER_STAT_FIELDS}
        tier = mod.apply_tier(store_row.get("店铺id"), tier_rules, stats)
        return tier, None
    except Exception as e:  # noqa: BLE001 — 降级可配，探针不中断
        return None, f"apply_tier 失败: {e}"


# ============================================================
# SampleSet 组装
# ============================================================

def _normalize_task_row(task_row: dict) -> dict:
    out = dict(task_row)
    if "订单日期" in out:
        out["订单日期_raw"] = out["订单日期"]
        out["订单日期"] = normalize_date(out["订单日期"])
    return out


def build_sample(cfg: dict, task_row: dict, record_id: Optional[str],
                 tier_rules: Optional[dict]) -> dict:
    task_out = _normalize_task_row(task_row)
    order_date_key = task_out.get("订单日期")
    product_row = fetch_product_dimension(cfg, task_row.get("商品id"), order_date_key)
    store_row = fetch_store_dimension(cfg, task_row.get("店铺ID"))
    tier, tier_reason = compute_store_tier(cfg, store_row, tier_rules)
    join_meta = {
        "product_matched": product_row is not None,
        "product_date_key": order_date_key,
        "store_matched": store_row is not None,
        "tier_degraded": tier is None,
        "tier_degrade_reason": tier_reason,
    }
    return {
        "item_id": task_row.get("升级售后单号"),
        "record_id": record_id,
        "task": task_out,
        "dimension_data": {"product": product_row, "store": store_row, "store_tier": tier},
        "join_meta": join_meta,
        "expected": None,
    }


def _sampleset(source: str, samples: list[dict], judgment_rules: list[dict],
               tier_rules: Optional[dict]) -> dict:
    tier_meta = None
    if tier_rules:
        tier_meta = {"date": tier_rules.get("date"),
                     "version": (tier_rules.get("config_snapshot") or {}).get("version")}
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "fetched_at": datetime.now(CST).isoformat(timespec="seconds"),
        "samples": samples,
        "run_context": {
            "judgment_rules": judgment_rules,
            "judgment_rules_count": len(judgment_rules),
            "store_tier_rules_meta": tier_meta,
        },
    }


def build_samples_live(cfg: dict, limit: Optional[int] = None) -> dict:
    tf = cfg["probe"]["task_fetch"]
    limit = min(limit or tf["limit_default"], tf["limit_max"])
    env = fetch_tasks_live(cfg, limit)
    try:
        tier_rules = fetch_store_tier_rules(cfg)
    except (LarkCliError, json.JSONDecodeError) as e:
        logger.warning("门店分层规则拉取失败, 全部降级: %s", e)
        tier_rules = None
    judgment_rules = fetch_judgment_rules(cfg)
    samples = [build_sample(cfg, row, rid, tier_rules)
               for row, rid in zip(env.records, env.record_ids)]
    return _sampleset("live", samples, judgment_rules, tier_rules)


# ============================================================
# CSV 路径（任务表样本 + 人工标注表；维度数据走 live JOIN）
# ============================================================

def load_tasks_csv(path: Path, cfg: dict) -> list[dict]:
    types = load_field_types().get("task_table", {})
    aliases = cfg["probe"].get("csv_header_aliases") or {}
    warned: set[str] = set()
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row: dict[str, Any] = {}
            for header, val in raw.items():
                if header is None:
                    continue
                name = aliases.get(header, header)
                ftype = types.get(name)
                if ftype is None:
                    if name not in warned:
                        warned.add(name)
                        logger.warning("CSV 列 %r 不在 field_types 快照, 保守推断类型", header)
                    row[name] = _guess_coerce(val)
                else:
                    row[name] = coerce_value(val, ftype)
            rows.append(row)
    logger.info("任务 CSV: %d 行 (%s)", len(rows), path)
    return rows


def load_annotations_csv(path: Path) -> dict[str, dict]:
    """人工标注表 → {升级售后单号: 行 dict}。schema Round 2 定稿，本轮仅透传。"""
    out: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            item_id = (raw.get("升级售后单号") or "").strip()
            if item_id:
                out[item_id] = {k: v for k, v in raw.items() if k != "升级售后单号"}
    logger.info("标注 CSV: %d 条 (%s)", len(out), path)
    return out


def build_samples_from_csv(cfg: dict, task_csv: Path,
                           annotation_csv: Optional[Path] = None,
                           live_join: bool = True) -> dict:
    tasks = load_tasks_csv(Path(task_csv), cfg)
    annotations = load_annotations_csv(Path(annotation_csv)) if annotation_csv else {}
    tier_rules = None
    judgment_rules: list[dict] = []
    if live_join:
        try:
            tier_rules = fetch_store_tier_rules(cfg)
        except (LarkCliError, json.JSONDecodeError) as e:
            logger.warning("门店分层规则拉取失败, 全部降级: %s", e)
        judgment_rules = fetch_judgment_rules(cfg)
    samples = []
    for row in tasks:
        if live_join:
            s = build_sample(cfg, row, None, tier_rules)
        else:
            task_out = _normalize_task_row(row)
            s = {
                "item_id": row.get("升级售后单号"),
                "record_id": None,
                "task": task_out,
                "dimension_data": {"product": None, "store": None, "store_tier": None},
                "join_meta": {"product_matched": False,
                              "product_date_key": task_out.get("订单日期"),
                              "store_matched": False,
                              "tier_degraded": True,
                              "tier_degrade_reason": "live JOIN disabled"},
                "expected": None,
            }
        if s["item_id"] in annotations:
            s["expected"] = annotations[s["item_id"]]
        samples.append(s)
    return _sampleset("csv", samples, judgment_rules, tier_rules)


# ============================================================
# 摘要输出
# ============================================================

def summarize(sampleset: dict) -> dict:
    samples = sampleset["samples"]
    n = len(samples)
    product_hit = sum(1 for s in samples if s["join_meta"]["product_matched"])
    store_hit = sum(1 for s in samples if s["join_meta"]["store_matched"])
    tiers: dict[str, int] = {}
    for s in samples:
        t = s["dimension_data"]["store_tier"] or "null"
        tiers[t] = tiers.get(t, 0) + 1
    return {
        "samples": n,
        "product_join_hit": f"{product_hit}/{n}",
        "store_join_hit": f"{store_hit}/{n}",
        "store_tier_dist": tiers,
        "judgment_rules_count": sampleset["run_context"]["judgment_rules_count"],
        "store_tier_rules_meta": sampleset["run_context"]["store_tier_rules_meta"],
    }


def _default_out_path(cfg: dict, source: str) -> Path:
    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    return resolve_probe_output_dir(cfg) / f"samples_{source}_{ts}.json"


def _write_sampleset(cfg: dict, sampleset: dict, out: Optional[str], source: str) -> Path:
    out_path = Path(out) if out else _default_out_path(cfg, source)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(sampleset, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ============================================================
# CLI
# ============================================================

def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="data_loader",
                                     description="数据层探针版: live/CSV → 统一 SampleSet")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="live 拉取任务样本 + 维度 JOIN")
    p_fetch.add_argument("--limit", type=int, default=None)
    p_fetch.add_argument("--out", default=None)

    p_csv = sub.add_parser("from-csv", help="任务 CSV(+标注 CSV) → SampleSet")
    p_csv.add_argument("--task-csv", required=True)
    p_csv.add_argument("--annotation-csv", default=None)
    p_csv.add_argument("--no-live-join", action="store_true",
                       help="维度不做 live JOIN(全 null, 离线冒烟用)")
    p_csv.add_argument("--out", default=None)

    p_dump = sub.add_parser("dump-field-types", help="生成字段类型快照 assets/field_types.json")
    p_dump.add_argument("--out", default=None)

    p_rules = sub.add_parser("fetch-rules", help="调试: 拉规则表")
    p_rules.add_argument("--kind", choices=["judgment", "store-tier"], required=True)

    args = parser.parse_args()
    cfg = load_config()

    if args.cmd == "fetch":
        ss = build_samples_live(cfg, limit=args.limit)
        out = _write_sampleset(cfg, ss, args.out, "live")
    elif args.cmd == "from-csv":
        ss = build_samples_from_csv(cfg, Path(args.task_csv),
                                    Path(args.annotation_csv) if args.annotation_csv else None,
                                    live_join=not args.no_live_join)
        out = _write_sampleset(cfg, ss, args.out, "csv")
    elif args.cmd == "dump-field-types":
        out = dump_field_types(cfg, args.out)
        print(json.dumps({"field_types": str(out)}, ensure_ascii=False, indent=2))
        return
    elif args.cmd == "fetch-rules":
        if args.kind == "judgment":
            data = fetch_judgment_rules(cfg)
        else:
            data = fetch_store_tier_rules(cfg)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    print(json.dumps({"out": str(out), "summary": summarize(ss)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
