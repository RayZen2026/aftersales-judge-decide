"""feishu_bitable.py — 写保护门 / update 幂等 / 结果表 upsert / 锁封装。"""
import json

import pytest

import feishu_bitable as fb
from data_loader import Envelope

CFG = {
    "task_table": {"app_token": "APP_T", "table_id": "tblTASK"},
    "dimensions": {"result_table": {"app_token": "APP_R", "table_id": "tblRESULT"}},
}


@pytest.fixture
def write_enabled(monkeypatch):
    monkeypatch.setenv("BITABLE_WRITE_ENABLED", "1")


@pytest.fixture
def capture_calls(monkeypatch):
    calls = []

    def fake_run(args, cfg, timeout=120):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(fb, "run_lark_cli", fake_run)
    return calls


# ── 写保护门 ──

def test_write_guard_blocks_without_env(monkeypatch):
    monkeypatch.delenv("BITABLE_WRITE_ENABLED", raising=False)
    with pytest.raises(fb.WriteGuardError, match="BITABLE_WRITE_ENABLED"):
        fb.update_task_record(CFG, "recX", {"处理状态": "已处理-处理中"})


def test_write_guard_blocks_wrong_value(monkeypatch):
    monkeypatch.setenv("BITABLE_WRITE_ENABLED", "yes")  # 只认 "1"
    with pytest.raises(fb.WriteGuardError):
        fb.update_task_record(CFG, "recX", {"处理状态": "已处理-处理中"})


# ── 任务表 update ──

def test_update_task_record_payload(write_enabled, capture_calls):
    fb.update_task_record(CFG, "recA", {"处理状态": "已处理-处理中"})
    args = capture_calls[0]
    assert "+record-batch-update" in args
    assert args[args.index("--base-token") + 1] == "APP_T"
    assert args[args.index("--table-id") + 1] == "tblTASK"
    payload = json.loads(args[args.index("--json") + 1])
    assert payload == {"update_records": {"recA": {"处理状态": "已处理-处理中"}}}


def test_update_task_record_requires_args(write_enabled):
    with pytest.raises(ValueError):
        fb.update_task_record(CFG, "", {"处理状态": "x"})
    with pytest.raises(ValueError):
        fb.update_task_record(CFG, "recA", {})


# ── 结果表 upsert（1 单 1 行幂等）──

def test_upsert_creates_when_absent(write_enabled, capture_calls, monkeypatch):
    monkeypatch.setattr(fb, "find_result_record_id", lambda cfg, oid: None)
    fb.upsert_result_record(CFG, {"升级售后单号": "UAS1", "判责理由": "x"})
    args = capture_calls[0]
    assert "+record-batch-create" in args
    payload = json.loads(args[args.index("--json") + 1])
    assert payload == {"create_records": [{"升级售后单号": "UAS1", "判责理由": "x"}]}


def test_upsert_updates_when_exists(write_enabled, capture_calls, monkeypatch):
    monkeypatch.setattr(fb, "find_result_record_id", lambda cfg, oid: "recEXIST")
    fb.upsert_result_record(CFG, {"升级售后单号": "UAS1", "判责理由": "x"})
    args = capture_calls[0]
    assert "+record-batch-update" in args
    payload = json.loads(args[args.index("--json") + 1])
    assert payload == {"update_records": {"recEXIST": {"升级售后单号": "UAS1", "判责理由": "x"}}}


def test_upsert_requires_order_id(write_enabled):
    with pytest.raises(ValueError, match="升级售后单号"):
        fb.upsert_result_record(CFG, {"判责理由": "x"})


def test_find_result_record_id(monkeypatch):
    def fake_record_list(cfg, **kw):
        assert kw["filter_json"] is not None
        assert "升级售后单号" in kw["filter_json"]
        return Envelope(records=[{"升级售后单号": "UAS1"}], record_ids=["recFOUND"])

    monkeypatch.setattr(fb, "record_list", fake_record_list)
    assert fb.find_result_record_id(CFG, "UAS1") == "recFOUND"


def test_find_result_record_id_absent(monkeypatch):
    monkeypatch.setattr(fb, "record_list", lambda cfg, **kw: Envelope())
    assert fb.find_result_record_id(CFG, "UAS_X") is None


# ── 锁封装 ──

def test_acquire_lock_writes_processing(write_enabled, capture_calls):
    fb.acquire_lock(CFG, "recA")
    payload = json.loads(capture_calls[0][capture_calls[0].index("--json") + 1])
    assert payload["update_records"]["recA"] == {"处理状态": "已处理-处理中"}


@pytest.mark.parametrize("state,value", [
    ("completed", "已处理-成功"),
    ("failed", "已处理-失败"),
    ("manual_review", "已处理-需人工"),
])
def test_release_lock_writes_terminal(write_enabled, capture_calls, state, value):
    fb.release_lock(CFG, "recA", state)
    payload = json.loads(capture_calls[0][capture_calls[0].index("--json") + 1])
    assert payload["update_records"]["recA"] == {"处理状态": value}


def test_release_lock_illegal_state(write_enabled):
    with pytest.raises(ValueError):
        fb.release_lock(CFG, "recA", "pending")


# ── 结果字段映射 ──

def test_build_result_fields():
    out = {"judgment_summary": "结论段", "price_uplift_result_type": "同意"}
    fields = fb.build_result_fields("UAS1", out)
    assert fields == {"升级售后单号": "UAS1", "判责理由": "结论段", "提价结果类型": "同意"}


def test_build_result_fields_defaults():
    fields = fb.build_result_fields("UAS1", {})
    assert fields["判责理由"] == ""
    assert fields["提价结果类型"] == "需人工"
