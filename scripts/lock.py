#!/usr/bin/env python3
"""
lock.py — per-item 抢锁 + stale 兜底（Phase 2）

契约来源：
  - D-20260806-004/013: 抢锁节点 = 遍历 item 后、AGENT 前；锁 = 处理状态改
    已处理-处理中；拉取 = 待处理 + 失败
  - CLAUDE.md 原则 5/8: 单 JOB 单 Task + stale 5min 兜底——bitable 无事务，
    抢锁原子性靠"单 JOB 单 Task 串行"保证，stale 重抢兜底异常残留
  - config.yaml lock 块: scope=per_item / stale_minutes=5 /
    release_states=[completed, failed, manual_review]

实物适配（2026-08-12 实查）：
  任务表无独立"任务处理时间"字段；用系统字段 更新时间(fldCQOdVZI, updated_at,
  任何写入自动刷新)作 stale 判定基准——抢锁写 处理状态=已处理-处理中 时
  更新时间自动刷新，无需维护额外字段。

纯逻辑模块：锁判定/写入载荷生成；实际读写由 feishu_bitable.py 执行。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

TASK_STATUS_FIELD = "处理状态"          # fldUmAgcBk (text)
TASK_UPDATED_AT_FIELD = "更新时间"      # fldCQOdVZI (updated_at, 系统自动刷新, 只读)


@dataclass(frozen=True)
class LockCheck:
    acquirable: bool
    stale_reclaim: bool      # True = 抢的是 stale 残留锁（处理中但已超时）
    reason: str


def parse_dt(value) -> datetime | None:
    """ISO8601 / epoch ms → aware datetime（+08:00）。不可解析 → None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=CST)
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
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(CST)


def is_stale(updated_at_value, now: datetime, stale_minutes: int) -> bool:
    """更新时间早于 now - stale_minutes → stale。不可解析按 stale 处理（宁可重抢）。"""
    dt = parse_dt(updated_at_value)
    if dt is None:
        return True
    return (now - dt) > timedelta(minutes=stale_minutes)


def check_lockable(state: str, updated_at_value, now: datetime,
                   stale_minutes: int) -> LockCheck:
    """抢锁前判定（防御性，防双抢）。

    state = 内部状态键（pending/processing/completed/failed/manual_review）。
    """
    if state in ("pending", "failed"):
        return LockCheck(True, False, f"{state} 可抢锁")
    if state == "processing":
        if is_stale(updated_at_value, now, stale_minutes):
            return LockCheck(True, True, "stale 残留锁重抢（更新时间超时）")
        return LockCheck(False, False, "正在处理中（未超时），跳过")
    # completed / manual_review：最终态
    return LockCheck(False, False, f"{state} 最终态，不抢锁")


def acquire_fields() -> dict[str, list]:
    """抢锁写入载荷：处理状态 → 已处理-处理中（更新时间由系统自动刷新）。

    飞书单选字段写入时需要列表格式（即使 multiple=false）。
    """
    return {TASK_STATUS_FIELD: ["已处理-处理中"]}


def release_fields(target_state: str) -> dict[str, list]:
    """释放写入载荷：处理状态 → 终态值（更新时间保留历史，不清除）。

    target_state ∈ completed/failed/manual_review/pending（config lock.release_states + 字段缺失回退）。
    飞书单选字段写入时需要列表格式（即使 multiple=false）。
    """
    from state_machine import to_table_value  # 延迟 import 避免顶层耦合
    if target_state not in ("completed", "failed", "manual_review", "pending"):
        raise ValueError(f"释放目标状态非法: {target_state}（release_states 已锁）")
    return {TASK_STATUS_FIELD: [to_table_value(target_state)]}


def stale_filter_threshold(now: datetime, stale_minutes: int) -> datetime:
    """stale 扫描阈值时刻（早于此时刻的处理中记录 = stale 候选）。"""
    return now - timedelta(minutes=stale_minutes)
