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


def _result_table(cfg: dict, test_mode: bool = False) -> dict:
    """test_mode=True 时用 test_result_table（Phase 4 端到端隔离）。"""
    if test_mode and "test_result_table" in cfg.get("dimensions", {}):
        return cfg["dimensions"]["test_result_table"]
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


def find_result_record_id(cfg: dict, order_id: str,
                          test_mode: bool = False) -> Optional[str]:
    """判责结果表按 升级售后单号 查已有行（1 单 1 行幂等检查）。"""
    rt = _result_table(cfg, test_mode)
    filter_json = json.dumps(
        {"logic": "and", "conditions": [["升级售后单号", "==", order_id]]},
        ensure_ascii=False)
    env = record_list(cfg, app_token=rt["app_token"], table_id=rt["table_id"],
                      field_names=["升级售后单号"], filter_json=filter_json, limit=1)
    return env.record_ids[0] if env.records else None


def upsert_result_record(cfg: dict, fields: dict,
                         test_mode: bool = False) -> dict:
    """判责结果表 1 单 1 行幂等写：已有行 → update，无 → create。

    调用方保证只在 成功/需人工 终态调用（已处理-失败不写结果表）。
    test_mode=True 时写 test_result_table（Phase 4 端到端隔离）。
    """
    _require_write_guard()
    order_id = fields.get("升级售后单号")
    if not order_id:
        raise ValueError("upsert_result_record: fields 必须含 升级售后单号")
    rt = _result_table(cfg, test_mode)
    existing = find_result_record_id(cfg, order_id, test_mode)
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

def _format_judgment_report(output: dict) -> str:
    """judgment_summary + judgment_basis → 判责报告（业务人员可读详情）。"""
    parts = []
    summary = output.get("judgment_summary") or ""
    if summary:
        parts.append(f"【判责结论】\n{summary}")
    basis = output.get("judgment_basis") or {}
    if isinstance(basis, dict):
        labels = {
            "store_profile": "【门店画像】",
            "fact_finding": "【事实认定】",
            "responsibility_reasoning": "【责任判定】",
            "rule_reference": "【规则引用】",
            "decision_comparison": "【决策对比】",
        }
        for k, label in labels.items():
            v = basis.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(f"{label}\n{v}")
    return "\n\n".join(parts)


def _format_judgment_result(output: dict) -> str:
    """格式化简短判责结论（写入「判责结果」字段，如"同意赔付77.43，平台商家1:9"）。"""
    action = output.get("action") or "需人工"
    amount = output.get("amount") or 0
    resp = output.get("responsibility_corrected") or output.get("responsibility") or {}
    platform = resp.get("platform", 0)
    merchant = resp.get("merchant", 0)
    if action == "赔付" and amount:
        result = f"同意赔付{amount}，平台商家{platform}:{merchant}"
    elif action == "退货":
        result = f"同意退货，平台商家{platform}:{merchant}"
    elif action == "退款":
        result = f"同意退款，平台商家{platform}:{merchant}"
    elif action == "无需处理":
        result = "无需处理"
    else:
        result = f"需人工审核，平台商家{platform}:{merchant}"
    return result


def build_result_fields(order_id: str, output: dict) -> dict:
    """1-AGENT 输出 schema v2 → 判责结果表写入字段（5 字段，2026-08-12 实查对齐）。

    字段映射：
      升级售后单号  ← order_id
      判责结果      ← 简短格式化结论（如"同意赔付77.43，平台商家1:9"）
      提交结果类型  ← price_uplift_result_type（同意/拒绝/需人工）
      满足期望类型  ← expectation_satisfaction_type（完全满足/部分满足/不满足/需人工）
      判责报告      ← judgment_summary + judgment_basis 格式化（业务人员查阅）
    """
    return {
        "升级售后单号": order_id,
        "判责结果": _format_judgment_result(output),
        "提交结果类型": output.get("price_uplift_result_type") or "需人工",
        "满足期望类型": output.get("expectation_satisfaction_type") or "需人工",
        "判责报告": _format_judgment_report(output),
    }
