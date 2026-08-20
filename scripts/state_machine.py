#!/usr/bin/env python3
"""
state_machine.py — 5 状态机（Phase 2）

契约来源（拍板项，不可轻改）：
  - D-20260806-006: 5 状态写库分表（任务表 update 幂等 5 状态都更新；
    判责结果表 insert 1 单 1 行，仅成功/需人工终态）
  - D-20260813 拉取矩阵（architecture.md §2）：
    拉取 = 待处理 + 已处理-失败(重试)；处理中不重复拉（stale 5min 兜底重抢）；
    成功/需人工 = 最终态不拉
  - config.yaml state_machine: states / terminal

状态内部键(英) ↔ 任务表字段值(中)：
  pending ↔ 未处理（表现行值；拍板名"待处理"，阻塞项 #7 统一前沿用）
  processing ↔ 已处理-处理中
  completed ↔ 已处理-成功
  failed ↔ 已处理-失败
  manual_review ↔ 已处理-需人工

纯逻辑模块：不碰飞书 / 不碰 LLM。写表由 feishu_bitable.py 执行。
"""
from __future__ import annotations

import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── 状态定义（config.yaml state_machine 对齐）──
STATES = ["pending", "processing", "manual_review", "completed", "failed"]
TERMINAL_STATES = frozenset({"completed", "failed"})        # config terminal
FETCH_FINAL_STATES = TERMINAL_STATES | {"manual_review"}     # 拉取最终态（需人工等运营，不再拉取）

# ── 任务表字段值映射 ──
STATE_TABLE_VALUES = {
    "pending": "未处理",          # 表现行值（拍板名"待处理"，阻塞项 #7 待统一）
    "processing": "已处理-处理中",
    "completed": "已处理-成功",
    "failed": "已处理-失败",
    "manual_review": "已处理-需人工",
}

# 表值 → 内部键（含别名：未来表选项改为"待处理"时兼容）
TABLE_VALUE_ALIASES = {
    "未处理": "pending",
    "待处理": "pending",
    "已处理-处理中": "processing",
    "已处理-成功": "completed",
    "已处理-失败": "failed",
    "已处理-需人工": "manual_review",
}

# ── 合法转移（architecture.md §1/§2 主流程 + 抢锁矩阵）──
TRANSITIONS = frozenset({
    ("pending", "processing"),        # 首次抢锁
    ("failed", "processing"),         # cron 兜底重试重抢
    ("processing", "completed"),      # 成功终态
    ("processing", "failed"),         # 终态失败 / retry 耗尽
    ("processing", "manual_review"),  # 业务问题类（规则无匹配等）
    ("processing", "pending"),        # 字段匹配检验失败 → 抢锁释放回原状态
})


class InvalidTransition(ValueError):
    """非法状态转移"""


def can_transition(src: str, dst: str) -> bool:
    return (src, dst) in TRANSITIONS


def assert_transition(src: str, dst: str) -> None:
    if not can_transition(src, dst):
        raise InvalidTransition(f"非法状态转移: {src} → {dst}")


def to_table_value(state: str) -> str:
    """内部键 → 任务表字段值。"""
    if state not in STATE_TABLE_VALUES:
        raise ValueError(f"未知状态: {state}")
    return STATE_TABLE_VALUES[state]


def from_table_value(value: str | list) -> str:
    """任务表字段值 → 内部键（容错别名；未知值抛错 = 数据污染 fail fast）。

    飞书字段可能返回字符串（单选）或列表（多选），这里统一处理。
    """
    # 处理列表情况（多选字段）
    if isinstance(value, list):
        if not value:
            value = ""
        else:
            value = value[0]  # 取第一个值

    state = TABLE_VALUE_ALIASES.get((value or "").strip())
    if state is None:
        raise ValueError(f"未知处理状态值: {value!r}（data_corrupted 候选）")
    return state


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def is_fetch_final(state: str) -> bool:
    """拉取最终态：不再进入 cron 拉取范围（成功/失败终态 + 需人工等运营）。"""
    return state in FETCH_FINAL_STATES


def is_fetchable(state: str) -> bool:
    """可拉取：待处理 + 已处理-失败（重试），见拉取矩阵。"""
    return state in {"pending", "failed"}


def load_states_from_config(path: Path | None = None) -> dict:
    """读 config.yaml state_machine 块（运行时一致性校验用）。"""
    p = Path(path) if path else BASE_DIR / "config.yaml"
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["state_machine"]


def validate_against_config(cfg_state_machine: dict) -> list[str]:
    """本模块状态/终态定义 vs config.yaml 一致性校验，返回不一致清单（空 = 一致）。"""
    issues = []
    cfg_states = set(cfg_state_machine.get("states") or [])
    if cfg_states != set(STATES):
        issues.append(f"states 不一致: config={sorted(cfg_states)} vs module={sorted(STATES)}")
    cfg_terminal = set(cfg_state_machine.get("terminal") or [])
    if cfg_terminal != set(TERMINAL_STATES):
        issues.append(f"terminal 不一致: config={sorted(cfg_terminal)} vs module={sorted(TERMINAL_STATES)}")
    return issues
