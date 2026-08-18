"""测试 function calling 功能（normalize_responsibility 工具调用）。"""
import json
import pytest

from llm import LLMResponse
import agent_single as ag


class FakeBackendWithToolCalls:
    """模拟支持 tool calling 的 Backend。"""

    def __init__(self, scenario="direct"):
        """
        scenario:
          - "direct": LLM 直接返回最终答案（不调用工具）
          - "tool_then_answer": LLM 先调用工具，然后返回最终答案
        """
        self.scenario = scenario
        self.call_count = 0

    def call(self, model, prompt, params, tools=None, messages=None):
        self.call_count += 1

        if self.scenario == "direct":
            # 第一轮：直接返回最终答案
            content = json.dumps({
                "store_expected": "赔付金额",
                "store_expected_amount": 50,
                "action": "赔付金额",
                "amount": 50,
                "amount_adjust_ratio": 1.0,
                "recommended_action": "赔付金额",
                "price_uplift_result_type": "同意",
                "responsibility": {"platform": 30, "merchant": 70, "logistics": 0, "agent": 0},
                "judgment_summary": "测试",
                "reasoning": "测试推理过程",
                "confidence": 0.9,
                "judgment_basis": {
                    "store_profile": "A级",
                    "product_quality": "正常",
                    "merchant_traceability": "正常",
                    "fact_finding": "正常",
                    "responsibility_reasoning": "测试",
                    "amount_adjustment": "测试",
                    "rule_reference": "无",
                    "decision_comparison": "测试"
                },
                "expectation_satisfaction_type": "完全满足",
                "key_factors": ["测试"]
            }, ensure_ascii=False)
            return LLMResponse(content=content, latency_ms=100, model=model)

        elif self.scenario == "tool_then_answer":
            if self.call_count == 1:
                # 第一轮：LLM 决定调用工具
                return LLMResponse(
                    content="我需要归一化责任比例",
                    latency_ms=100,
                    model=model,
                    tool_calls=[{
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "normalize_responsibility",
                            "arguments": json.dumps({"platform": 30, "merchant": 65, "logistics": 0, "agent": 0})
                        }
                    }]
                )
            else:
                # 第二轮：收到工具结果后返回最终答案
                content = json.dumps({
                    "store_expected": "赔付金额",
                    "store_expected_amount": 50,
                    "action": "赔付金额",
                    "amount": 50,
                    "amount_adjust_ratio": 1.0,
                    "recommended_action": "赔付金额",
                    "price_uplift_result_type": "同意",
                    "responsibility": {"platform": 32, "merchant": 68, "logistics": 0, "agent": 0},
                    "judgment_summary": "测试",
                    "reasoning": "测试推理过程",
                    "confidence": 0.9,
                    "judgment_basis": {
                        "store_profile": "A级",
                        "product_quality": "正常",
                        "merchant_traceability": "正常",
                        "fact_finding": "正常",
                        "responsibility_reasoning": "测试",
                        "amount_adjustment": "测试",
                        "rule_reference": "无",
                        "decision_comparison": "测试"
                    },
                    "expectation_satisfaction_type": "完全满足",
                    "key_factors": ["测试"]
                }, ensure_ascii=False)
                return LLMResponse(content=content, latency_ms=100, model=model)


def test_normalize_responsibility_tool_definition():
    """验证工具定义结构。"""
    tool = ag.NORMALIZE_RESPONSIBILITY_TOOL
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "normalize_responsibility"
    assert "platform" in tool["function"]["parameters"]["properties"]
    assert "merchant" in tool["function"]["parameters"]["properties"]


def test_execute_normalize_responsibility():
    """验证工具执行函数。"""
    result = ag.execute_normalize_responsibility({"platform": 30, "merchant": 65, "logistics": 0, "agent": 0})
    # 归一化+标准化：30+65=95 → scale to 100 → 31.6:68.4 → ceiling → 40:60（merchant ceiling到70，platform=100-70=30）
    assert result["platform"] + result["merchant"] + result["logistics"] + result["agent"] == 100
    assert result["merchant"] % 10 == 0  # 标准化到10的倍数


def test_run_without_tool_calling():
    """测试不使用工具的正常流程。"""
    cfg = {
        "probe": {
            "task_field_mapping": {
                "appeal_content_fields": ["申诉原因"],
                "appeal_type": "诉求类型",
                "appeal_amount": "诉求金额",
                "aftersales_type": "售后类型"
            }
        },
        "llm": {
            "use_production_chain": False,
            "dev": {"model": "qwen-plus-latest"},
            "params": {"max_tokens": 30000, "temperature": 0.1},
            "retry": {"max": 1, "backoff_seconds": [0.1]}
        }
    }
    task_row = {
        "升级售后单号": "UAS001",
        "诉求类型": "赔付金额",
        "诉求金额": 100,
        "商品实付金额": 200,
        "申诉原因": "测试"
    }
    dim = {"task": task_row, "product": None, "store": None, "store_tier": None}

    backend = FakeBackendWithToolCalls(scenario="direct")
    result = ag.run(cfg, backend, task_row, dim, [])

    assert result.ok
    assert backend.call_count == 1  # 只调用一次
    assert result.output["responsibility_corrected"]["platform"] == 30


def test_run_with_tool_calling():
    """测试使用工具调用的流程。"""
    cfg = {
        "probe": {
            "task_field_mapping": {
                "appeal_content_fields": ["申诉原因"],
                "appeal_type": "诉求类型",
                "appeal_amount": "诉求金额",
                "aftersales_type": "售后类型"
            }
        },
        "llm": {
            "use_production_chain": False,
            "dev": {"model": "qwen-plus-latest"},
            "params": {"max_tokens": 30000, "temperature": 0.1},
            "retry": {"max": 1, "backoff_seconds": [0.1]}
        }
    }
    task_row = {
        "升级售后单号": "UAS001",
        "诉求类型": "赔付金额",
        "诉求金额": 100,
        "商品实付金额": 200,
        "申诉原因": "测试"
    }
    dim = {"task": task_row, "product": None, "store": None, "store_tier": None}

    backend = FakeBackendWithToolCalls(scenario="tool_then_answer")
    result = ag.run(cfg, backend, task_row, dim, [])

    assert result.ok
    assert backend.call_count == 2  # 第一轮调用工具，第二轮返回答案
    assert result.output["responsibility_corrected"]["platform"] + \
           result.output["responsibility_corrected"]["merchant"] == 100
