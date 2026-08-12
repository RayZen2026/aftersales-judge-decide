#!/usr/bin/env python3
"""
feishu_bitable.py — 4 表数据访问层（Phase 2 生产实现）

契约来源：
  - D-20260806-006: 任务表 update 幂等（5 状态都经此写）；判责结果表
    insert 1 单 1 行（仅成功/需人工终态，不写已处理-失败）
  - D-20260812-006: 拉取 = 视图「近两天数据」+ 客户端状态过滤（读侧复用
    data_loader 的 SampleSet 契约，本模块不重复实现）
  - 写保护门（开发安全）：一切写操作要求 env BITABLE_WRITE_ENABLED=1，
    防止开发迭代误写生产表（Phase 4 端到端用 test_main_table + 开门）

读侧复用 data_loader（同一数据契约）：
  fetch_tasks_live / fetch_product_dimension / fetch_store_dimension /
  fetch_judgment_rules / fetch_store_tier_rules
"""
from __future__ import annotations

import json
import os
from typing import Optional

from data_loader import LarkCliError, record_list, run_lark_cli


class WriteGuardError(RuntimeError):
    """写保护门：未设 BITABLE_WRITE_ENABLED=1 时拒绝一切写操作。"""


def _require_write_guard() -> None:
    if os.environ.get("BITABLE_WRITE_ENABLED") != "1":
        raise WriteGuardError(
            "写保护门：设 env BITABLE_WRITE_ENABLED=1 才允许写飞书表"
            "（开发期默认禁写，防误写生产表）")


def _task_table(cfg: dict) -> dict:
    return cfg["task_table"]


def _result_table(cfg: dict) -> dict:
    return cfg["dimensions"]["result_table"]


# ============================================================
# 写侧
# ============================================================

def update_task_record(cfg: dict, record_id: str, fields: dict) -> dict:
    """任务表 update（幂等：同字段重复写安全；5 状态写库都经此）。"""
    _require_write_guard()
    if not record_id or not fields:
        raise ValueError("update_task_record: record_id 与 fields 必填")
    tt = _task_table(cfg)
    payload = json.dumps({"update_records": {record_id: fields}}, ensure_ascii=False)
    args = ["base", "+record-batch-update",
            "--base-token", tt["app_token"], "--table-id", tt["table_id"],
            "--json", payload]
    return run_lark_cli(args, cfg)


def find_result_record_id(cfg: dict, order_id: str) -> Optional[str]:
    """判责结果表按 升级售后单号 查已有行（1 单 1 行幂等检查）。"""
    rt = _result_table(cfg)
    filter_json = json.dumps(
        {"logic": "and", "conditions": [["升级售后单号", "==", order_id]]},
        ensure_ascii=False)
    env = record_list(cfg, app_token=rt["app_token"], table_id=rt["table_id"],
                      field_names=["升级售后单号"], filter_json=filter_json, limit=1)
    return env.record_ids[0] if env.records else None


def upsert_result_record(cfg: dict, fields: dict) -> dict:
    """判责结果表 1 单 1 行幂等写：已有行 → update，无 → create。

    调用方保证只在 成功/需人工 终态调用（已处理-失败不写结果表）。
    """
    _require_write_guard()
    order_id = fields.get("升级售后单号")
    if not order_id:
        raise ValueError("upsert_result_record: fields 必须含 升级售后单号")
    rt = _result_table(cfg)
    existing = find_result_record_id(cfg, order_id)
    if existing:
        payload = json.dumps({"update_records": {existing: fields}}, ensure_ascii=False)
        args = ["base", "+record-batch-update",
                "--base-token", rt["app_token"], "--table-id", rt["table_id"],
                "--json", payload]
    else:
        payload = json.dumps({"create_records": [fields]}, ensure_ascii=False)
        args = ["base", "+record-batch-create",
                "--base-token", rt["app_token"], "--table-id", rt["table_id"],
                "--json", payload]
    return run_lark_cli(args, cfg)


# ============================================================
# 锁便捷封装（载荷生成在 lock.py，写入经 update_task_record）
# ============================================================

def acquire_lock(cfg: dict, record_id: str) -> dict:
    """抢锁：处理状态 → 已处理-处理中（更新时间系统自动刷新）。"""
    from lock import acquire_fields  # noqa: PLC0415
    return update_task_record(cfg, record_id, acquire_fields())


def release_lock(cfg: dict, record_id: str, target_state: str) -> dict:
    """释放锁：处理状态 → 终态值（completed/failed/manual_review）。"""
    from lock import release_fields  # noqa: PLC0415
    return update_task_record(cfg, record_id, release_fields(target_state))


# ============================================================
# 判责结果写入（业务字段映射）
# ============================================================

def build_result_fields(order_id: str, output: dict) -> dict:
    """1-AGENT 输出 schema v2 → 判责结果表字段（config dimensions.result_table）。

    - 判责理由 ← judgment_summary（结论段）
    - 提价结果类型 ← price_uplift_result_type（同意/拒绝/需人工）
    """
    return {
        "升级售后单号": order_id,
        "判责理由": output.get("judgment_summary") or "",
        "提价结果类型": output.get("price_uplift_result_type") or "需人工",
    }
