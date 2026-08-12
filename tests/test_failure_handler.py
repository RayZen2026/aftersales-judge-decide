"""failure_handler.py — 9 类失败分类 / 处理决策 / 通知与写表策略。"""
import pytest

import failure_handler as fh


# ── 9 类分类 ──

@pytest.mark.parametrize("failure_type", [
    "llm_rate_limit", "llm_5xx", "bitable_temp_unavailable"])
def test_retry_class(failure_type):
    assert fh.classify(failure_type) == "retry"


@pytest.mark.parametrize("failure_type", [
    "appeal_info_insufficient", "rule_conflict", "llm_ability_exceeded"])
def test_manual_review_class(failure_type):
    assert fh.classify(failure_type) == "manual_review"


@pytest.mark.parametrize("failure_type", [
    "credential_invalid", "rule_not_found", "data_corrupted"])
def test_terminal_class(failure_type):
    assert fh.classify(failure_type) == "terminal"


def test_unknown_failure_type_raises():
    # 9 类已锁，未知 = 实现 bug，fail fast
    with pytest.raises(ValueError, match="未知失败类型"):
        fh.classify("something_new")


# ── 处理决策 ──

def test_retry_decision():
    d = fh.decide("llm_rate_limit")
    assert d.retryable is True
    assert d.target_state == "failed"          # 重试耗尽 → cron 兜底重试
    assert d.notify is False                   # 原则 9：retry 类不通知
    assert d.write_result_table is False


def test_manual_review_decision():
    d = fh.decide("rule_conflict")
    assert d.retryable is False
    assert d.target_state == "manual_review"
    assert d.notify is True
    assert d.write_result_table is True        # D-20260806-006：需人工写两表


def test_terminal_decision():
    d = fh.decide("credential_invalid")
    assert d.retryable is False
    assert d.target_state == "failed"
    assert d.notify is True
    assert d.write_result_table is False       # 终态失败只写任务表


def test_all_nine_types_have_decision():
    for ft in fh.FAILURE_CATEGORIES:
        d = fh.decide(ft)
        assert d.target_state in ("failed", "manual_review")


# ── 重试预算 ──

def test_retry_budget_from_config():
    assert fh.retry_budget({"magic_numbers": {"retry_max": 3}}) == 3
    assert fh.retry_budget({}) == 3            # 缺省回退


# ── config 契约一致性 ──

def test_matches_config_yaml():
    cfg_failure = fh.load_failure_config()
    assert fh.validate_against_config(cfg_failure) == []
