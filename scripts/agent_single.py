#!/usr/bin/env python3
"""
agent_single.py — 1-AGENT 完整流程判责（Phase 3）

契约来源：
  - D-20260812-007: 切 1 AGENT（agent_single 融合模板），3 AGENT 方案暂停
  - D-20260807-003: 不 import probe_llm（探针/生产独立；JSON 提取/校验本模块自带）
  - schema v3（agent_single_prompt_template.j2 v0.3.0 output 节，Phase 5）：
    结论层(action/amount/amount_adjust_ratio/responsibility{platform,merchant,logistics,agent}/提价结果类型/满足期望类型)
    + 期望层 + 依据层(judgment_summary/judgment_basis{8维}) + 元数据层
  - 9 类失败映射（failure_handler 9 类 + state_machine 状态）

流程：
  1. build_context: 任务行 + 维度数据 → 模板变量（config task_field_mapping）
  2. render_prompt: jinja2 渲染 agent_single_prompt_template.j2
  3. call_with_fallback: llm.DashScopeBackend（开发）/ MiaodaBackend（生产）
  4. extract_json + validate_schema: JSON 提取 + schema v3 校验
  5. allocate_correction: 4方比例校正（DRY from main.py）
  6. map_failure: LLM 错误 / schema 错误 → 9 类失败类型

不做：状态机推进、飞书写表、通知——均由 main.py 主流程执行。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import jinja2

from llm import LLMResponse, ChainExhaustedError, call_with_fallback, select_chain, dev_chain
from main import allocate_correction

BASE_ASSETS = None  # 延迟初始化（避免顶层 import Path 耦合）


def _assets_dir():
    from pathlib import Path
    global BASE_ASSETS
    if BASE_ASSETS is None:
        BASE_ASSETS = Path(__file__).resolve().parent.parent / "assets"
    return BASE_ASSETS


# ============================================================
# Jinja2 渲染
# ============================================================

_jinja_env: Optional[jinja2.Environment] = None


def _get_jinja_env() -> jinja2.Environment:
    global _jinja_env
    if _jinja_env is None:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_assets_dir())),
            keep_trailing_newline=True)

        def tojson_cn(v, indent=None):
            return json.dumps(v, ensure_ascii=False, indent=indent, default=str)

        env.filters["tojson"] = tojson_cn
        _jinja_env = env
    return _jinja_env


def build_context(cfg: dict, task_row: dict, dimension_data: dict,
                  judgment_rules: list) -> dict:
    """任务行 + 维度数据 + 规则 → agent_single 模板变量（config task_field_mapping）。

    Phase 5: dimension_data 扩展为语义化分组（task/product/store/store_tier）。
    """
    mapping = cfg["probe"]["task_field_mapping"]
    parts = []
    for fname in mapping["appeal_content_fields"]:
        v = task_row.get(fname)
        if v not in (None, "", "-1", -1):
            parts.append(f"{fname}：{v}")

    # 扩展 dimension_data 包含任务表字段（商品品质/责任方标识）
    dimension_with_task = {
        "task": task_row,  # 包含商品名称/商品等级/是否严重品质问题/举证/责任方标识
        "product": dimension_data.get("product"),
        "store": dimension_data.get("store"),
        "store_tier": dimension_data.get("store_tier"),
    }

    return {
        "item_id": task_row.get("升级售后单号"),
        "appeal_content": "\n".join(parts) or "（无申诉内容）",
        "appeal_type": task_row.get(mapping["appeal_type"]),
        "appeal_amount": task_row.get(mapping["appeal_amount"]),
        "paid_amount": task_row.get("商品实付金额"),  # Phase 5 新增
        "aftersales_type": task_row.get(mapping["aftersales_type"]),
        "dimension_data": dimension_with_task,  # Phase 5 结构调整
        "judgment_rules": judgment_rules,
    }


def render_prompt(ctx: dict) -> str:
    return _get_jinja_env().get_template("agent_single_prompt_template.j2").render(**ctx)


# ============================================================
# JSON 提取 + schema v2 校验
# ============================================================

class AgentFormatError(ValueError):
    """LLM 输出不符合 schema v2（9 类失败候选：llm_ability_exceeded 或 appeal_info_insufficient）。"""


REQUIRED_FIELDS = {
    "store_expected": "string",  # Schema v4: 透传输入，不再枚举验证
    "store_expected_amount": "number",
    "recommended_action": ("enum", ["倾向于退货", "赔付金额", "拒绝赔付"]),  # Schema v4: 新增
    "action": ("enum", ["赔付金额", "退货", "需人工", "拒绝赔付"]),  # Schema v4: 枚举调整
    "amount": "number",
    "amount_adjust_ratio": "number?",  # Phase 5 新增，可选（默认1.0）
    "responsibility": "responsibility",
    "price_uplift_result_type": ("enum", ["同意", "拒绝", "需人工"]),
    "expectation_satisfaction_type": ("enum", ["完全满足", "部分满足", "不满足", "需人工"]),
    "judgment_summary": "string",
    "judgment_basis": "judgment_basis",
    "reasoning": "string",
    "confidence": "number",
    "key_factors": "list",
}

JUDGMENT_BASIS_PARTS = [
    "store_profile", "product_quality", "merchant_traceability",  # Phase 5 新增后2个
    "fact_finding", "responsibility_reasoning", "amount_adjustment",  # Phase 5 新增 amount_adjustment
    "rule_reference", "decision_comparison",
]


def extract_json(text: str) -> dict:
    """JSON 围栏 → 平衡括号扫描兜底。"""
    if not text or not text.strip():
        raise AgentFormatError("空响应")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        candidate = m.group(1)
    else:
        start = text.find("{")
        if start < 0:
            raise AgentFormatError("非 JSON: 无 { 起点")
        depth = in_str = esc = 0
        candidate = None
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = 0
                elif ch == "\\":
                    esc = 1
                elif ch == '"':
                    in_str = 0
            else:
                if ch == '"':
                    in_str = 1
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        break
        if candidate is None:
            raise AgentFormatError("非 JSON: 括号不平衡")
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise AgentFormatError(f"JSON 解析失败: {e}") from e
    if not isinstance(obj, dict):
        raise AgentFormatError("非 JSON 对象")
    return obj


def _check_field(name: str, value: Any, spec: Any) -> Optional[str]:
    optional = isinstance(spec, str) and spec.endswith("?")
    base = spec[:-1] if optional else spec
    if value is None:
        return None if optional else f"必填缺失: {name}"
    if isinstance(base, tuple) and base[0] == "enum":
        return f"enum 非法: {name}={value!r}" if value not in base[1] else None
    if base == "number":
        return (f"类型错: {name} 应为 number" if isinstance(value, bool)
                or not isinstance(value, (int, float)) else None)
    if base == "string":
        return f"类型错: {name} 应为 string" if not isinstance(value, str) else None
    if base == "list":
        return f"类型错: {name} 应为 list" if not isinstance(value, list) else None
    if base == "responsibility":
        if not isinstance(value, dict):
            return f"类型错: {name} 应为 dict"
        # Phase 5: 4方责任（platform/merchant/logistics/agent）
        errs = [f"类型错: {name}.{k} 应为 number"
                for k in ("platform", "merchant", "logistics", "agent")
                if k in value and (isinstance(value.get(k), bool) or
                   not isinstance(value.get(k), (int, float)))]
        return "; ".join(errs) if errs else None
    if base == "judgment_basis":
        if not isinstance(value, dict):
            return f"类型错: {name} 应为 dict"
        errs = [f"必填缺失: {name}.{p}"
                for p in JUDGMENT_BASIS_PARTS
                if not isinstance(value.get(p), str) or not value[p].strip()]
        return "; ".join(errs) if errs else None
    return None


def validate_schema(obj: dict) -> list[str]:
    """返回错误列表；空 = 通过。"""
    return [e for name, spec in REQUIRED_FIELDS.items()
            if (e := _check_field(name, obj.get(name), spec)) is not None]


# ============================================================
# 失败类型映射
# ============================================================

def map_failure_type(llm_res: Optional[LLMResponse],
                     format_errors: list[str]) -> str:
    """LLM 错误 / schema 错误 → 9 类失败类型（failure_handler 名单）。"""
    if llm_res and llm_res.error_kind:
        # LLM 调用层失败（ChainExhaustedError 包含 error_kind）
        kind = llm_res.error_kind
        if kind in ("llm_rate_limit",):
            return "llm_rate_limit"
        if kind in ("llm_5xx", "llm_timeout"):
            return "llm_5xx"
        return "llm_ability_exceeded"   # 4xx / unknown → 模型能力问题
    if format_errors:
        # schema 校验失败
        if any("必填缺失" in e or "enum 非法" in e for e in format_errors):
            return "appeal_info_insufficient"   # 输入不足或模型判为需人工
        return "llm_ability_exceeded"           # 类型/结构错误
    return "llm_ability_exceeded"


# ============================================================
# 调用入口
# ============================================================

@dataclass
class AgentResult:
    ok: bool
    output: Optional[dict] = None              # schema v2 合法输出（含 responsibility_corrected）
    format_errors: list = field(default_factory=list)
    failure_type: Optional[str] = None         # 失败时 → failure_handler.decide() 的 key
    llm_response: Optional[LLMResponse] = None
    prompt: str = ""
    manual_review_signal: bool = False          # 规则无匹配 / 信息不足 → 需人工（合法输出）


def run(cfg: dict, backend, task_row: dict, dimension_data: dict,
        judgment_rules: list) -> AgentResult:
    """1-AGENT 完整判责调用。

    backend: DashScopeBackend（开发）或 MiaodaBackend（生产，Phase 4）。
    返回 AgentResult；异常全部收敛到 AgentResult.failure_type，不上抛。
    """
    from llm import select_chain, dev_chain  # noqa: PLC0415

    ctx = build_context(cfg, task_row, dimension_data, judgment_rules)
    prompt = render_prompt(ctx)

    # 根据环境选择chain：生产用降级链，开发用单模型
    use_prod = cfg.get("llm", {}).get("use_production_chain", False)
    chain = select_chain(cfg, "single") if use_prod else dev_chain(cfg)

    params = cfg["llm"]["params"]
    retry_cfg = cfg["llm"]["retry"]

    # LLM 调用
    try:
        llm_res = call_with_fallback(backend, prompt, chain, params, retry_cfg)
    except ChainExhaustedError as e:
        return AgentResult(ok=False, failure_type=e.error_kind or "llm_5xx",
                           prompt=prompt)
    if llm_res.error:
        return AgentResult(ok=False,
                           failure_type=map_failure_type(llm_res, []),
                           llm_response=llm_res, prompt=prompt)

    # JSON 提取
    try:
        obj = extract_json(llm_res.content)
    except AgentFormatError as e:
        return AgentResult(ok=False,
                           failure_type="llm_ability_exceeded",
                           format_errors=[str(e)],
                           llm_response=llm_res, prompt=prompt)

    # schema v2 校验
    errors = validate_schema(obj)
    if errors:
        return AgentResult(ok=False,
                           failure_type=map_failure_type(None, errors),
                           format_errors=errors,
                           llm_response=llm_res, prompt=prompt)

    # 分配校正（DRY from main.py）
    corrected = allocate_correction(obj.get("responsibility") or {})
    obj["responsibility_corrected"] = corrected

    # 需人工信号检测（规则无匹配 / 信息不足）
    manual = (obj.get("action") == "需人工" or
              corrected.get("platform", 0) + corrected.get("merchant", 0) +
              corrected.get("logistics", 0) + corrected.get("agent", 0) == 0)

    return AgentResult(ok=True, output=obj, llm_response=llm_res,
                       prompt=prompt, manual_review_signal=manual)
