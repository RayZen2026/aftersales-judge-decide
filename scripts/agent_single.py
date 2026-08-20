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

# ============================================================
# Function Calling 工具定义
# ============================================================

NORMALIZE_RESPONSIBILITY_TOOL = {
    "type": "function",
    "function": {
        "name": "normalize_responsibility",
        "description": "归一化责任比例到100%并标准化到10的倍数。输入4方初始权重，返回标准化后的比例（平台+商家+物流+代理人=100%，且都是10的倍数）。",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "number",
                    "description": "平台初始权重"
                },
                "merchant": {
                    "type": "number",
                    "description": "商家初始权重"
                },
                "logistics": {
                    "type": "number",
                    "description": "物流初始权重（默认0）"
                },
                "agent": {
                    "type": "number",
                    "description": "代理人初始权重（默认0）"
                }
            },
            "required": ["platform", "merchant"]
        }
    }
}


def execute_normalize_responsibility(args: dict) -> dict:
    """执行归一化工具函数。

    args: {"platform": 30, "merchant": 70, "logistics": 0, "agent": 0}
    返回: {"platform": 30, "merchant": 70, "logistics": 0, "agent": 0}
    """
    return allocate_correction(args)


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
# 运行时校验（优化1：防御性校验）
# ============================================================

def validate_and_fix_responsibility(result: dict, task_data: dict, logger) -> dict:
    """
    校验并修正责任比例输出（优化1：运行时校验）

    校验规则：
    1. is_logistics_issue=0 时强制 logistics=0
    2. is_agent_issue=0 时强制 agent=0
    3. 责任比例和必须=100%
    4. 所有比例必须是10的倍数
    5. 平台比例范围10-50%，物流≤30%，代理人≤20%

    Args:
        result: LLM输出的完整结果（含responsibility字段）
        task_data: 任务数据（含是否物流问题/是否代理人问题字段）
        logger: 日志对象

    Returns:
        修正后的result（修改responsibility字段）
    """
    resp = result.get("responsibility", {}).copy()
    modified = False

    # 规则1: is_logistics_issue=0 时强制 logistics=0
    is_logistics = task_data.get("是否物流问题", 0)
    if is_logistics == 0 and resp.get("logistics", 0) != 0:
        logger.warning(f"[运行时校验] 字段约束失败: is_logistics_issue=0 但输出logistics={resp['logistics']}%，强制修正为0")
        resp["logistics"] = 0
        modified = True

    # 规则2: is_agent_issue=0 时强制 agent=0
    is_agent = task_data.get("是否代理人问题", 0)
    if is_agent == 0 and resp.get("agent", 0) != 0:
        logger.warning(f"[运行时校验] 字段约束失败: is_agent_issue=0 但输出agent={resp['agent']}%，强制修正为0")
        resp["agent"] = 0
        modified = True

    # 规则3: 和=100%
    total = sum(resp.values())
    if total != 100:
        logger.warning(f"[运行时校验] 责任比例和={total}% ≠ 100%，重新归一化")
        resp = allocate_correction(resp)
        modified = True

    # 规则4: 10的倍数
    for party, value in resp.items():
        if value % 10 != 0:
            logger.warning(f"[运行时校验] {party}={value}%不是10的倍数，需重新归一化")
            resp = allocate_correction(resp)
            modified = True
            break

    # 规则5: 范围约束（仅警告，不强制修正）
    platform = resp.get("platform", 0)
    logistics = resp.get("logistics", 0)
    agent = resp.get("agent", 0)

    if not (10 <= platform <= 50):
        logger.warning(f"[运行时校验] 平台比例{platform}%超出10-50%范围")
    if logistics > 30:
        logger.warning(f"[运行时校验] 物流比例{logistics}%超出≤30%约束")
    if agent > 20:
        logger.warning(f"[运行时校验] 代理人比例{agent}%超出≤20%约束")

    if modified:
        result["responsibility"] = resp
        logger.info(f"[运行时校验] 修正后责任比例: {json.dumps(resp, ensure_ascii=False)}")

    return result


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

    支持 function calling：LLM 可调用 normalize_responsibility 工具进行归一化计算。
    """
    from llm import select_chain, dev_chain  # noqa: PLC0415

    ctx = build_context(cfg, task_row, dimension_data, judgment_rules)
    prompt = render_prompt(ctx)

    # 根据backend类型选择chain：DashScope用开发单模型，Miaoda用生产降级链
    from llm import DashScopeBackend, MiaodaBackend  # noqa: PLC0415
    if isinstance(backend, DashScopeBackend):
        chain = dev_chain(cfg)  # 开发环境：qwen-plus-latest单模型
    elif isinstance(backend, MiaodaBackend):
        chain = select_chain(cfg, "single")  # 生产环境：4+2降级链
    else:
        # 兜底：按配置决定
        use_prod = cfg.get("llm", {}).get("use_production_chain", False)
        chain = select_chain(cfg, "single") if use_prod else dev_chain(cfg)

    params = cfg["llm"]["params"]
    retry_cfg = cfg["llm"]["retry"]

    # 准备工具定义
    tools = [NORMALIZE_RESPONSIBILITY_TOOL]

    # Tool calling 循环（最多5轮：initial call + 4轮tool调用）
    max_tool_rounds = 5
    messages = [{"role": "user", "content": prompt}]
    tool_calls_count = 0  # 统计工具调用次数

    for round_idx in range(max_tool_rounds):
        # LLM 调用
        try:
            llm_res = call_with_fallback(backend, prompt, chain, params, retry_cfg,
                                         tools=tools, messages=messages)
        except ChainExhaustedError as e:
            return AgentResult(ok=False, failure_type=e.error_kind or "llm_5xx",
                               prompt=prompt)
        if llm_res.error:
            # 添加详细错误日志
            import logging
            logger = logging.getLogger("aftersales-judge-decide")
            logger.error(f"LLM调用失败 round={round_idx}: error={llm_res.error}, "
                        f"error_kind={llm_res.error_kind}")
            return AgentResult(ok=False,
                               failure_type=map_failure_type(llm_res, []),
                               llm_response=llm_res, prompt=prompt)

        # 检查是否有tool_calls
        if llm_res.tool_calls:
            tool_calls_count += len(llm_res.tool_calls)
            # 添加日志
            import logging
            logger = logging.getLogger("aftersales-judge-decide")
            logger.info(f"[Function Calling] Round {round_idx + 1}: "
                       f"LLM调用了{len(llm_res.tool_calls)}个工具")

            # 执行工具调用
            tool_results = []
            for tc in llm_res.tool_calls:
                if tc["function"]["name"] == "normalize_responsibility":
                    try:
                        args = json.loads(tc["function"]["arguments"])
                        logger.info(f"[Function Calling] 执行normalize_responsibility: "
                                   f"输入={json.dumps(args, ensure_ascii=False)}")
                        result = execute_normalize_responsibility(args)
                        logger.info(f"[Function Calling] 归一化结果: "
                                   f"{json.dumps(result, ensure_ascii=False)}")
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result, ensure_ascii=False)
                        })
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"[Function Calling] 工具执行失败: {e}")
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": f"Error: {e}"
                        })

            # 构建下一轮messages（assistant message with tool_calls + tool results）
            messages.append({
                "role": "assistant",
                "content": llm_res.content or "",
                "tool_calls": llm_res.tool_calls
            })
            messages.extend(tool_results)
            continue  # 继续下一轮LLM调用

        # 没有tool_calls，说明LLM已给出最终答案
        if tool_calls_count > 0:
            import logging
            logger = logging.getLogger("aftersales-judge-decide")
            logger.info(f"[Function Calling] 总共调用了{tool_calls_count}次工具，"
                       f"经过{round_idx + 1}轮对话后得到最终答案")
        break

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

    # 运行时校验（优化1：防御性校验）
    import logging
    logger = logging.getLogger("aftersales-judge-decide")
    obj = validate_and_fix_responsibility(obj, ctx["dimension_data"]["task"], logger)

    # 分配校正（DRY from main.py）
    corrected = allocate_correction(obj.get("responsibility") or {})
    obj["responsibility_corrected"] = corrected

    # 需人工信号检测（规则无匹配 / 信息不足）
    manual = (obj.get("action") == "需人工" or
              corrected.get("platform", 0) + corrected.get("merchant", 0) +
              corrected.get("logistics", 0) + corrected.get("agent", 0) == 0)

    return AgentResult(ok=True, output=obj, llm_response=llm_res,
                       prompt=prompt, manual_review_signal=manual)
