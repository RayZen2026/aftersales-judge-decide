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
    monkeypatch.setattr(fb, "find_result_record_id", lambda cfg, oid, test_mode=False: None)
    fb.upsert_result_record(CFG, {"升级售后单号": "UAS1", "判责理由": "x"})
    args = capture_calls[0]
    assert "+record-batch-create" in args
    payload = json.loads(args[args.index("--json") + 1])
    assert payload == {"create_records": [{"升级售后单号": "UAS1", "判责理由": "x"}]}


def test_upsert_updates_when_exists(write_enabled, capture_calls, monkeypatch):
    monkeypatch.setattr(fb, "find_result_record_id", lambda cfg, oid, test_mode=False: "recEXIST")
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
        fb.release_lock(CFG, "recA", "garbage")  # 改为非法 state


# ── 结果字段映射 ──

def test_build_result_fields():
    resp = {"platform": 10, "merchant": 90, "logistics": 0, "agent": 0}
    out = {
        "action": "赔付金额", "amount": 77.43,  # Schema v4: 赔付→赔付金额
        "recommended_action": "赔付金额",  # Schema v4: 新增字段
        "price_uplift_result_type": "同意",     # LLM 输出不再透传，从 action 推导
        "expectation_satisfaction_type": "完全满足",
        "judgment_summary": "综合意见",
        "judgment_basis": {"store_profile": "B级", "product_quality": "A级商品",
                           "merchant_traceability": "商家偏离3倍",
                           "fact_finding": "品质问题",
                           "responsibility_reasoning": "商家责任",
                           "amount_adjustment": "完全满足诉求",
                           "rule_reference": "无匹配", "decision_comparison": "赔付优先"},
        "responsibility": resp,
        "responsibility_corrected": resp,
        "key_factors": ["品质问题", "商家责任"],
    }
    fields = fb.build_result_fields("UAS1", out)
    assert fields["升级售后单号"] == "UAS1"
    assert "77.43" in fields["判责结果"]
    assert "平台商家10:90" in fields["判责结果"]
    assert fields["提交结果类型"] == "同意"         # action=赔付 → 同意
    assert fields["满足期望类型"] == "完全满足"
    assert "【判责结论】" in fields["判责报告"]
    assert "【门店画像】" in fields["判责报告"]
    assert "【商品品质】" in fields["判责报告"]    # Phase 5 新增
    assert "【商家追溯】" in fields["判责报告"]    # Phase 5 新增


def test_build_result_fields_test_mode():
    """测试表模式：输出15字段（生产表5字段 + 扩展10字段）"""
    resp = {"platform": 10, "merchant": 90, "logistics": 0, "agent": 0}
    out = {
        "action": "赔付金额", "amount": 77.43,
        "recommended_action": "赔付金额",
        "expectation_satisfaction_type": "完全满足",
        "judgment_summary": "综合意见",
        "judgment_basis": {
            "store_profile": "B级门店",
            "product_quality": "A级商品",
            "merchant_traceability": "商家偏离3倍",
            "fact_finding": "品质问题明确",
            "responsibility_reasoning": "商家全责",
            "amount_adjustment": "完全满足诉求",
            "rule_reference": "无匹配规则",
            "decision_comparison": "赔付优先",
        },
        "responsibility_corrected": resp,
        "key_factors": ["品质问题", "商家责任"],
    }
    fields = fb.build_result_fields("UAS1", out, test_mode=True)

    # 生产表基础字段（5个）
    assert fields["升级售后单号"] == "UAS1"
    assert fields["判责结果"] == "同意赔付77.43元，平台商家10:90"
    assert fields["提交结果类型"] == "同意"
    assert fields["满足期望类型"] == "完全满足"
    assert "【判责结论】" in fields["判责报告"]

    # 测试表扩展字段（10个）
    assert fields["建议动作"] == "赔付金额"
    assert fields["门店画像"] == "B级门店"
    assert fields["商品品质"] == "A级商品"
    assert fields["商家追溯"] == "商家偏离3倍"
    assert fields["事实认定"] == "品质问题明确"
    assert fields["责任判定"] == "商家全责"
    assert fields["金额调整"] == "完全满足诉求"
    assert fields["规则引用"] == "无匹配规则"
    assert fields["决策对比"] == "赔付优先"
    assert fields["关键因素"] == "品质问题, 商家责任"



def test_build_result_fields_defaults():
    fields = fb.build_result_fields("UAS1", {"action": "需人工"})
    assert fields["提交结果类型"] == "需人工"        # action=需人工 → 需人工
    assert fields["满足期望类型"] == "需人工"


def test_derive_submission_result():
    """Schema v4: 提交结果类型必须从 action 推导，不依赖 LLM 输出。"""
    assert fb._derive_submission_result("赔付金额") == "同意"
    assert fb._derive_submission_result("退货") == "同意"
    assert fb._derive_submission_result("拒绝赔付") == "拒绝"
    assert fb._derive_submission_result("需人工") == "需人工"


def test_build_result_fields_with_4party():
    """Phase 5: 4方责任格式化测试（物流+代理人）。"""
    resp = {"platform": 10, "merchant": 60, "logistics": 20, "agent": 10}
    out = {
        "action": "赔付金额", "amount": 100.0,  # Schema v4: 赔付→赔付金额
        "expectation_satisfaction_type": "完全满足",
        "judgment_summary": "物流代理人共同责任",
        "judgment_basis": {"store_profile": "A级", "product_quality": "A级",
                           "merchant_traceability": "偏离1倍",
                           "fact_finding": "物流损坏", "responsibility_reasoning": "4方分担",
                           "amount_adjustment": "完全满足", "rule_reference": "规则X",
                           "decision_comparison": "赔付"},
        "responsibility_corrected": resp,
    }
    fields = fb.build_result_fields("UAS2", out)
    assert "平台商家10:60" in fields["判责结果"]
    assert "物流20" in fields["判责结果"]
    assert "代理人10" in fields["判责结果"]
    assert fields["提交结果类型"] == "同意"


# ── Schema v4.0 新增测试 ──

def test_format_judgment_result_return_with_amount():
    """Schema v4: 退货场景输出建议赔付金额"""
    resp = {"platform": 20, "merchant": 80, "logistics": 0, "agent": 0}
    out = {"action": "退货", "amount": 66, "responsibility_corrected": resp}
    result = fb._format_judgment_result(out)
    assert "同意退货" in result
    assert "建议赔付66元" in result
    assert "平台商家20:80" in result


def test_format_judgment_result_reject():
    """Schema v4: 拒绝赔付场景"""
    resp = {"platform": 0, "merchant": 0, "logistics": 0, "agent": 0}
    out = {"action": "拒绝赔付", "amount": 0, "responsibility_corrected": resp}
    result = fb._format_judgment_result(out)
    assert "拒绝赔付" in result
    assert "平台商家0:0" in result


def test_build_result_fields_reject():
    """Schema v4: 拒绝赔付完整字段"""
    out = {
        "action": "拒绝赔付",
        "amount": 0,
        "expectation_satisfaction_type": "不满足",
        "judgment_summary": "门店价值低，复购差，拒绝赔付",
        "judgment_basis": {
            "store_profile": "D级", "product_quality": "正常",
            "merchant_traceability": "正常", "fact_finding": "无举证",
            "responsibility_reasoning": "无责任方", "amount_adjustment": "拒绝",
            "rule_reference": "无规则", "decision_comparison": "拒绝"
        },
        "responsibility_corrected": {"platform": 0, "merchant": 0, "logistics": 0, "agent": 0},
    }
    fields = fb.build_result_fields("UAS3", out)
    assert "拒绝赔付" in fields["判责结果"]
    assert fields["提交结果类型"] == "拒绝"
    assert fields["满足期望类型"] == "不满足"

