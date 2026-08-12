"""agent_single.py — 渲染 / JSON 提取 / schema v2 校验 / 失败映射 / 调用入口。"""
import json

import pytest

import agent_single as ag

CFG = {
    "llm": {
        "dev": {"model": "qwen-plus-latest"},
        "params": {"max_tokens": 30000, "temperature": 0.1},
        "retry": {"max": 1, "backoff_seconds": [0.1]},
    },
    "probe": {"task_field_mapping": {
        "appeal_content_fields": ["问题描述", "客户诉求", "已处理意见（客服组长处理意见）"],
        "appeal_type": "诉求类型",
        "appeal_amount": "诉求赔付金额",
        "aftersales_type": "升级售后类型",
    }},
}

TASK_ROW = {
    "升级售后单号": "UAS1",
    "问题描述": "黄桃坏了",
    "客户诉求": "退货",
    "已处理意见（客服组长处理意见）": None,   # None 段跳过
    "诉求类型": "退货",
    "诉求赔付金额": 77.43,
    "升级售后类型": "处理中升级售后单",
    "商品id": 1001,
    "店铺ID": 2001,
}

DIM = {"product": None, "store": None, "store_tier": "B"}
RULES = [{"优先级": 10, "触发条件AST": "{...}"}]

VALID_OUTPUT = {
    "store_expected": "应赔付",
    "store_expected_amount": 77.43,
    "action": "赔付",
    "amount": 77.43,
    "responsibility": {"platform": 10, "merchant": 90},
    "price_uplift_result_type": "同意",
    "expectation_satisfaction_type": "完全满足",
    "judgment_summary": "综合意见" * 30,
    "judgment_basis": {
        "store_profile": "B 级门店",
        "fact_finding": "商品有质量问题",
        "responsibility_reasoning": "商家全责",
        "rule_reference": "无匹配规则，按兜底原则",
        "decision_comparison": "赔付成本低于退货",
    },
    "reasoning": "判定理由" * 20,
    "confidence": 0.9,
    "key_factors": ["品质问题", "商家责任"],
}


# ── build_context ──

def test_build_context_appeal_content_joins():
    ctx = ag.build_context(CFG, TASK_ROW, DIM, RULES)
    assert "问题描述：黄桃坏了" in ctx["appeal_content"]
    assert "客户诉求：退货" in ctx["appeal_content"]
    assert "已处理意见" not in ctx["appeal_content"]  # None 段跳过
    assert ctx["item_id"] == "UAS1"
    assert ctx["appeal_type"] == "退货"
    assert ctx["judgment_rules"] is RULES


# ── extract_json ──

def test_extract_fenced():
    text = '```json\n{"a": 1}\n```'
    assert ag.extract_json(text) == {"a": 1}


def test_extract_bare():
    text = '好的 {"store_expected": "应赔付", "confidence": 0.9} 完毕'
    assert ag.extract_json(text) == {"store_expected": "应赔付", "confidence": 0.9}


def test_extract_nested():
    obj = {"responsibility": {"platform": 10, "merchant": 90}}
    assert ag.extract_json(json.dumps(obj, ensure_ascii=False)) == obj


def test_extract_invalid():
    with pytest.raises(ag.AgentFormatError):
        ag.extract_json("")
    with pytest.raises(ag.AgentFormatError):
        ag.extract_json("no json here")
    with pytest.raises(ag.AgentFormatError):
        ag.extract_json("{bad json")


# ── validate_schema ──

def test_validate_valid():
    assert ag.validate_schema(VALID_OUTPUT) == []


def test_validate_missing_required():
    incomplete = {k: v for k, v in VALID_OUTPUT.items() if k != "judgment_summary"}
    errs = ag.validate_schema(incomplete)
    assert any("judgment_summary" in e for e in errs)


def test_validate_action_enum():
    bad = {**VALID_OUTPUT, "action": "退货或者赔付"}
    errs = ag.validate_schema(bad)
    assert any("action" in e for e in errs)


def test_validate_responsibility_platform_key():
    bad = {**VALID_OUTPUT, "responsibility": {"platform": "30", "merchant": 70}}
    errs = ag.validate_schema(bad)
    assert any("responsibility.platform" in e for e in errs)


def test_validate_judgment_basis_missing_part():
    bad_basis = {k: v for k, v in VALID_OUTPUT["judgment_basis"].items()
                 if k != "decision_comparison"}
    bad = {**VALID_OUTPUT, "judgment_basis": bad_basis}
    errs = ag.validate_schema(bad)
    assert any("decision_comparison" in e for e in errs)


# ── map_failure_type ──

def test_map_rate_limit():
    from llm import LLMResponse
    res = LLMResponse("", 0, "m", error="429", error_kind="llm_rate_limit")
    assert ag.map_failure_type(res, []) == "llm_rate_limit"


def test_map_5xx():
    from llm import LLMResponse
    res = LLMResponse("", 0, "m", error="503", error_kind="llm_5xx")
    assert ag.map_failure_type(res, []) == "llm_5xx"


def test_map_format_error_appeal_insufficient():
    assert ag.map_failure_type(None, ["必填缺失: action"]) == "appeal_info_insufficient"


def test_map_format_error_type():
    assert ag.map_failure_type(None, ["类型错: reasoning"]) == "llm_ability_exceeded"


# ── run (FakeBackend) ──

class FakeBackend:
    def __init__(self, content="", error_kind=None):
        from llm import LLMResponse
        self.res = LLMResponse(
            content=content, latency_ms=100, model="qwen",
            error=("err" if error_kind else None), error_kind=error_kind)

    def call(self, model, prompt, params):
        return self.res


def test_run_success():
    content = "```json\n" + json.dumps(VALID_OUTPUT, ensure_ascii=False) + "\n```"
    result = ag.run(CFG, FakeBackend(content), TASK_ROW, DIM, RULES)
    assert result.ok
    assert result.output["responsibility_corrected"] == {"platform": 10, "merchant": 90}
    assert result.manual_review_signal is False


def test_run_llm_error():
    result = ag.run(CFG, FakeBackend(error_kind="llm_5xx"), TASK_ROW, DIM, RULES)
    assert not result.ok
    assert result.failure_type == "llm_5xx"


def test_run_json_parse_error():
    result = ag.run(CFG, FakeBackend("not json at all"), TASK_ROW, DIM, RULES)
    assert not result.ok
    assert result.failure_type == "llm_ability_exceeded"


def test_run_schema_error():
    bad = {**VALID_OUTPUT, "action": "违法枚举"}
    content = json.dumps(bad, ensure_ascii=False)
    result = ag.run(CFG, FakeBackend(content), TASK_ROW, DIM, RULES)
    assert not result.ok


def test_run_manual_review_signal_action():
    manual_out = {**VALID_OUTPUT, "action": "需人工"}
    content = json.dumps(manual_out, ensure_ascii=False)
    result = ag.run(CFG, FakeBackend(content), TASK_ROW, DIM, RULES)
    assert result.ok
    assert result.manual_review_signal is True


def test_run_corrects_responsibility():
    # 1:2 → 33:67
    out = {**VALID_OUTPUT, "responsibility": {"platform": 1, "merchant": 2}}
    content = json.dumps(out, ensure_ascii=False)
    result = ag.run(CFG, FakeBackend(content), TASK_ROW, DIM, RULES)
    assert result.ok
    corrected = result.output["responsibility_corrected"]
    assert corrected["platform"] + corrected["merchant"] == 100
