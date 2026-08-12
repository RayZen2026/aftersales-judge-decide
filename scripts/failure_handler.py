#!/usr/bin/env python3
"""
failure_handler.py — 9 类失败 → 3 大类处理（Phase 2）

契约来源：
  - D-20260806-001: 9 类失败 → 3 大类（retry / 不重试-需人工 / 不重试-终态）
  - config.yaml failure 块（9 类名单已锁，不可轻改）
  - CLAUDE.md 原则 6: 失败重试独立计数（AGENT 间互不影响）
  - CLAUDE.md 原则 9: retry 类不飞书通知（避免 LLM 失败清单风暴）
  - architecture.md §3: 9 类失败处理仅在最终 AGENT 后执行
  - D-20260806-006: 需人工写任务表 + 判责结果表；终态失败只写任务表

3 大类处理策略：
  retry(3)          → 本次运行内重试 retry_max 次（独立计数）；耗尽 → 状态=已处理-失败
                      （cron 兜底重试）；不飞书通知
  manual_review(3)  → 状态=已处理-需人工（写任务表 + 写判责结果表）；飞书通知
  terminal(3)       → 状态=已处理-失败（终态，只写任务表）；飞书通知

纯逻辑模块：分类 + 决策；实际重试执行在 llm.py / 主流程，通知在 feishu_notify.py。
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── 9 类失败 → 3 大类（config.yaml failure 块对齐）──
CATEGORY_RETRY = "retry"
CATEGORY_MANUAL_REVIEW = "manual_review"
CATEGORY_TERMINAL = "terminal"

FAILURE_CATEGORIES = {
    # retry：本次运行内重试，耗尽转 failed（cron 兜底）
    "llm_rate_limit": CATEGORY_RETRY,
    "llm_5xx": CATEGORY_RETRY,
    "bitable_temp_unavailable": CATEGORY_RETRY,
    # manual_review：业务问题类，转需人工
    "appeal_info_insufficient": CATEGORY_MANUAL_REVIEW,
    "rule_conflict": CATEGORY_MANUAL_REVIEW,
    "llm_ability_exceeded": CATEGORY_MANUAL_REVIEW,
    # terminal：终态失败
    "credential_invalid": CATEGORY_TERMINAL,
    "rule_not_found": CATEGORY_TERMINAL,
    "data_corrupted": CATEGORY_TERMINAL,
}

# 分类 → 目标任务表状态（retry 类 = 重试耗尽后的落点）
CATEGORY_TARGET_STATE = {
    CATEGORY_RETRY: "failed",
    CATEGORY_MANUAL_REVIEW: "manual_review",
    CATEGORY_TERMINAL: "failed",
}


@dataclass(frozen=True)
class FailureDecision:
    """单个失败类型的完整处理决策。"""
    failure_type: str
    category: str               # retry / manual_review / terminal
    target_state: str           # 任务表目标状态（内部键）
    retryable: bool             # 本次运行内是否重试
    notify: bool                # 是否飞书通知（retry 类 False，原则 9）
    write_result_table: bool    # 是否写判责结果表（仅 manual_review 终态）


def classify(failure_type: str) -> str:
    """9 类失败分类。未知类型抛错（9 类已锁，未知 = 实现 bug，fail fast）。"""
    category = FAILURE_CATEGORIES.get(failure_type)
    if category is None:
        raise ValueError(f"未知失败类型: {failure_type!r}（9 类失败已锁，见 config.yaml failure 块）")
    return category


def decide(failure_type: str) -> FailureDecision:
    """失败类型 → 完整处理决策。"""
    category = classify(failure_type)
    return FailureDecision(
        failure_type=failure_type,
        category=category,
        target_state=CATEGORY_TARGET_STATE[category],
        retryable=category == CATEGORY_RETRY,
        notify=category != CATEGORY_RETRY,          # 原则 9：retry 类不通知
        write_result_table=category == CATEGORY_MANUAL_REVIEW,  # D-20260806-006
    )


def retry_budget(cfg: dict, agent: str | None = None) -> int:
    """重试次数上限（原则 6：各 AGENT 独立计数，预算相同）。"""
    return int(cfg.get("magic_numbers", {}).get("retry_max", 3))


def load_failure_config(path: Path | None = None) -> dict:
    p = Path(path) if path else BASE_DIR / "config.yaml"
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["failure"]


def validate_against_config(cfg_failure: dict) -> list[str]:
    """本模块 9 类名单 vs config.yaml 一致性校验，返回不一致清单（空 = 一致）。"""
    issues = []
    for category, key in ((CATEGORY_RETRY, "retry"),
                          (CATEGORY_MANUAL_REVIEW, "manual_review"),
                          (CATEGORY_TERMINAL, "terminal")):
        cfg_types = set(cfg_failure.get(key) or [])
        mod_types = {t for t, c in FAILURE_CATEGORIES.items() if c == category}
        if cfg_types != mod_types:
            issues.append(f"{category} 类不一致: config={sorted(cfg_types)} vs module={sorted(mod_types)}")
    return issues
