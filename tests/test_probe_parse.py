"""probe_llm 纯函数层：JSON 提取 + schema 校验 + 一致性口径 + 渲染变量映射（无网络）。"""
import json

import pytest

import probe_llm as pl


# ── extract_json ──

def test_extract_fenced_json():
    text = '前置说明\n```json\n{"a": 1}\n```\n后置'
    assert pl.extract_json(text) == {"a": 1}


def test_extract_bare_braces():
    text = '好的，判定结果如下 {"store_expected": "应赔付", "confidence": 0.9} 完毕'
    assert pl.extract_json(text) == {"store_expected": "应赔付", "confidence": 0.9}


def test_extract_nested_braces():
    obj = {"responsibility": {"platform": 30, "merchant": 70}, "reasoning": "x"}
    text = "输出：" + json.dumps(obj, ensure_ascii=False)
    assert pl.extract_json(text) == obj


def test_extract_braces_in_string():
    # 字符串内含花括号不应打断平衡扫描
    obj = {"reasoning": "规则 {op: and} 匹配"}
    text = json.dumps(obj, ensure_ascii=False)
    assert pl.extract_json(text) == obj


def test_extract_invalid_raises():
    with pytest.raises(pl.ProbeFormatError):
        pl.extract_json("")
    with pytest.raises(pl.ProbeFormatError):
        pl.extract_json("没有 JSON 的纯文本")
    with pytest.raises(pl.ProbeFormatError):
        pl.extract_json("{括号不平衡")
    with pytest.raises(pl.ProbeFormatError):
        pl.extract_json("{not: valid json}")


# ── validate_output（eval_standard §4：必填/类型/enum）──

def test_validate_agent1_ok():
    obj = {"store_expected": "应赔付", "store_expected_amount": 77.43,
           "reasoning": "x" * 100, "confidence": 0.9}
    assert pl.validate_output("agent1", obj) == []


def test_validate_agent1_enum_bad():
    obj = {"store_expected": "退货或者赔付", "store_expected_amount": 0,
           "reasoning": "x", "confidence": 0.5}
    errs = pl.validate_output("agent1", obj)
    assert any("enum 非法" in e for e in errs)


def test_validate_agent1_missing_required():
    errs = pl.validate_output("agent1", {"store_expected": "应赔付"})
    assert any("必填缺失" in e for e in errs)


def test_validate_agent2_responsibility_type():
    obj = {"responsibility": {"platform": "30", "merchant": 70},
           "reasoning": "x", "confidence": 0.5, "key_factors": ["a"]}
    errs = pl.validate_output("agent2", obj)
    assert any("responsibility.platform" in e for e in errs)


def test_validate_agent3_tags_optional():
    obj = {"judgment_summary": "x", "action": "赔付", "amount": 10,
           "responsibility_summary": "美团 0% / 商家 100%", "confidence": 0.8}
    assert pl.validate_output("agent3", obj) == []  # tags 可选


def test_validate_agent3_action_enum():
    obj = {"judgment_summary": "x", "action": "退货或者赔付", "amount": 0,
           "responsibility_summary": "x", "confidence": 0.8}
    errs = pl.validate_output("agent3", obj)
    assert any("enum 非法" in e and "action" in e for e in errs)


def test_validate_bool_not_number():
    obj = {"store_expected": "应赔付", "store_expected_amount": True,
           "reasoning": "x", "confidence": 0.9}
    errs = pl.validate_output("agent1", obj)
    assert any("类型错" in e for e in errs)


# ── 一致性口径 ──

def test_consistency_identical_outputs():
    out = {"action": "赔付", "amount": 10, "reasoning": "同样的理由"}
    u = pl._consistency_unit([out, dict(out), dict(out)])
    assert u["strict"] == 0.0 and u["core"] == 0.0


def test_consistency_free_text_only_diff():
    # reasoning 自由文本差异 → strict > 0，core = 0
    u = pl._consistency_unit([
        {"action": "赔付", "amount": 10, "reasoning": "理由 A"},
        {"action": "赔付", "amount": 10, "reasoning": "理由 B"},
    ])
    assert u["strict"] > 0
    assert u["core"] == 0.0


def test_consistency_core_diff():
    u = pl._consistency_unit([
        {"action": "赔付", "amount": 10},
        {"action": "退货", "amount": 10},
    ])
    assert u["core"] > 0


def test_consistency_insufficient_runs():
    assert pl._consistency_unit([{"a": 1}]) == {"strict": None, "core": None}
    assert pl._consistency_unit([None, None]) == {"strict": None, "core": None}


# ── 渲染变量映射 ──

CFG = {"probe": {"task_field_mapping": {
    "appeal_content_fields": ["问题描述", "客户诉求", "已处理意见（客服组长处理意见）"],
    "appeal_type": "诉求类型",
    "appeal_amount": "诉求赔付金额",
    "aftersales_type": "升级售后类型",
}}}

SAMPLE = {
    "item_id": "UAS_X",
    "task": {"升级售后单号": "UAS_X", "诉求类型": "退货", "诉求赔付金额": 77.43,
             "升级售后类型": "处理中升级售后单", "问题描述": "黄桃坏了",
             "客户诉求": "退货", "已处理意见（客服组长处理意见）": None},
    "dimension_data": {"product": None, "store": None, "store_tier": "C"},
}


def test_render_context_appeal_content_skips_none():
    ctx = pl.build_render_context(CFG, SAMPLE, "agent1", [])
    assert "问题描述：黄桃坏了" in ctx["appeal_content"]
    assert "客户诉求：退货" in ctx["appeal_content"]
    assert "已处理意见" not in ctx["appeal_content"]  # None 段跳过
    assert ctx["item_id"] == "UAS_X"
    assert ctx["appeal_type"] == "退货"


def test_render_agent1_prompt_contains_data():
    env = pl.make_jinja_env()
    ctx = pl.build_render_context(CFG, SAMPLE, "agent1", [])
    prompt = pl.render_prompt(env, "agent1", ctx)
    assert "UAS_X" in prompt
    assert "黄桃坏了" in prompt
    assert "store_expected" in prompt  # 输出 schema 在模板里


def test_render_agent2_prompt_injects_rules_and_upstream():
    env = pl.make_jinja_env()
    rules = [{"优先级": 10, "触发条件AST": "{...}", "责任方": ["商家"]}]
    a1_out = {"store_expected": "应赔付", "store_expected_amount": 77.43,
              "reasoning": "x", "confidence": 0.9}
    ctx = pl.build_render_context(CFG, SAMPLE, "agent2", rules, upstream={"agent1": a1_out})
    prompt = pl.render_prompt(env, "agent2", ctx)
    assert "判责规则 AST" in prompt
    assert "优先级" in prompt          # 规则注入（ensure_ascii=False，中文可读）
    assert "应赔付" in prompt          # 上游 AGENT 1 输出


def test_render_single_prompt():
    env = pl.make_jinja_env()
    ctx = pl.build_render_context(CFG, SAMPLE, "single", [])
    prompt = pl.render_prompt(env, "single", ctx)
    assert "judgment_summary" in prompt and "responsibility" in prompt
