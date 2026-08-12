#!/usr/bin/env python3
"""
probe_llm.py — 应用层探针框架（Phase 1 T1.4 实质实现）

边界（D-20260807-003 / README 探针先行原则）:
  - 不 import llm.py（Phase 2 产物）；DashScope 客户端、重试、JSON 提取自带
  - 与 main.py 唯一耦合 = allocate_correction（纯数学，DRY 防探针/生产漂移）
  - 数据来自 data_loader.py 的统一 SampleSet（live/CSV 同契约）

探针模式:
  1agent  — T1.5 单 AGENT 完整流程（agent_single 融合模板，1 次调用）
  3agent  — T1.6 3 AGENT 串行（agent1 → agent2+判责规则 → 分配校正 → agent3）
  both    — 两者都跑（Round 1 默认；T1.7 决策门 Round 2 加准确率后再判）

报告格式对齐 assets/eval/eval_standard.md §8（Round 1 accuracy/match = null）。

CLI（经 main.py probe 委托，也可直跑）:
  python scripts/probe_llm.py --probe-mode both --samples-file probes/samples_live_X.json --runs 3
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import jinja2

logger = logging.getLogger("probe_llm")

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import (  # noqa: E402
    load_config, resolve_probe_output_dir, build_samples_live,
)
from main import allocate_correction  # noqa: E402  # 纯数学，无副作用（argparse 在 main() 内）

CST_OFFSET = "+08:00"

AGENT_TEMPLATES = {
    "agent1": "agent1_prompt_template.j2",
    "agent2": "agent2_prompt_template.j2",
    "agent3": "agent3_prompt_template.j2",
    "single": "agent_single_prompt_template.j2",
}

# 自由文本字段——一致性 core 口径排除（strict 仍含）
FREE_TEXT_FIELDS = {"reasoning", "judgment_summary", "key_factors", "tags", "judgment_basis"}


class ProbeFormatError(ValueError):
    """LLM 输出非 JSON / JSON 解析失败"""


# ============================================================
# LLM 客户端（DashScope OpenAI 兼容端点，qwen-plus-latest 占位全链）
# ============================================================

@dataclass
class LLMResult:
    content: str
    latency_ms: int
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    attempts: int = 1
    error: Optional[str] = None


def make_client(cfg: dict):
    from openai import OpenAI  # 延迟 import：无 key 时也允许跑 --help
    llm = cfg["probe"]["llm"]
    api_key = os.environ.get(llm["api_key_env"])
    if not api_key:
        raise RuntimeError(
            f"env {llm['api_key_env']} 缺失 — 先 `set -a && source .env && set +a`")
    return OpenAI(api_key=api_key, base_url=llm["base_url"])


def _is_retryable(e: Exception) -> bool:
    try:
        from openai import APIStatusError, APITimeoutError, APIConnectionError
        if isinstance(e, (APITimeoutError, APIConnectionError)):
            return True
        if isinstance(e, APIStatusError):
            return e.status_code == 429 or e.status_code >= 500
        return False
    except ImportError:
        return False


def call_llm(client, prompt: str, cfg: dict) -> LLMResult:
    llm = cfg["probe"]["llm"]
    retry = llm.get("retry") or {}
    backoffs = retry.get("backoff_seconds", [0.5, 1, 2])
    max_attempts = retry.get("max", 3) + 1
    for attempt in range(max_attempts):
        t0 = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=llm["model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=llm["max_tokens"],
                temperature=llm["temperature"],
                timeout=llm["timeout_seconds"],
            )
            latency = int((time.perf_counter() - t0) * 1000)
            usage = getattr(resp, "usage", None)
            return LLMResult(
                content=(resp.choices[0].message.content or ""),
                latency_ms=latency, model=llm["model"],
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                attempts=attempt + 1)
        except Exception as e:  # noqa: BLE001 — 统一收敛为 LLMResult.error
            latency = int((time.perf_counter() - t0) * 1000)
            if not _is_retryable(e) or attempt + 1 >= max_attempts:
                return LLMResult(content="", latency_ms=latency, model=llm["model"],
                                 attempts=attempt + 1,
                                 error=f"{type(e).__name__}: {e}")
            time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
    raise AssertionError("unreachable")


# ============================================================
# 渲染层
# ============================================================

def make_jinja_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(ASSETS_DIR)),
        keep_trailing_newline=True)
    # 内置 tojson ensure_ascii=True（中文转 \uXXXX）→ 自定义保证 prompt 中文可读
    def tojson_cn(v, indent=None):
        return json.dumps(v, ensure_ascii=False, indent=indent, default=str)
    env.filters["tojson"] = tojson_cn
    return env


def build_render_context(cfg: dict, sample: dict, agent: str,
                         judgment_rules: list, upstream: Optional[dict] = None) -> dict:
    """任务字段 → 模板变量（映射表 cfg.probe.task_field_mapping，显式可审计）。"""
    mapping = cfg["probe"]["task_field_mapping"]
    task = sample["task"]
    parts = []
    for fname in mapping["appeal_content_fields"]:
        v = task.get(fname)
        if v not in (None, ""):
            parts.append(f"{fname}：{v}")
    ctx: dict[str, Any] = {
        "item_id": task.get("升级售后单号") or sample.get("item_id"),
        "appeal_content": "\n".join(parts) or "（无申诉内容）",
        "appeal_type": task.get(mapping["appeal_type"]),
        "appeal_amount": task.get(mapping["appeal_amount"]),
        "aftersales_type": task.get(mapping["aftersales_type"]),
        "dimension_data": sample.get("dimension_data") or {},
        "judgment_rules": judgment_rules or [],
    }
    if agent in ("agent2", "agent3"):
        ctx["agent1_output"] = (upstream or {}).get("agent1")
    if agent == "agent3":
        ctx["agent2_output"] = (upstream or {}).get("agent2")
        ctx["responsibility_corrected"] = (upstream or {}).get("responsibility_corrected")
    return ctx


def render_prompt(env: jinja2.Environment, agent: str, ctx: dict) -> str:
    tpl = env.get_template(AGENT_TEMPLATES[agent])
    return tpl.render(**ctx)


# ============================================================
# JSON 提取 + schema 校验（eval_standard §4 四项）
# ============================================================

def extract_json(text: str) -> dict:
    if not text or not text.strip():
        raise ProbeFormatError("空响应")
    candidate = None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        candidate = m.group(1)
    else:
        start = text.find("{")
        if start < 0:
            raise ProbeFormatError("非 JSON: 无 { 起点")
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        break
        if candidate is None:
            raise ProbeFormatError("非 JSON: 括号不平衡")
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ProbeFormatError(f"JSON 解析失败: {e}") from e
    if not isinstance(obj, dict):
        raise ProbeFormatError("非 JSON 对象")
    return obj


# 字段规格: "number" / "string" / "list" / ("enum", [...]) / ("responsibility", dict)
AGENT_OUTPUT_SCHEMAS: dict[str, Any] = {
    "agent1": {
        "store_expected": ("enum", ["应退货", "应赔付", "应退货或赔付", "需人工"]),
        "store_expected_amount": "number",
        "reasoning": "string",
        "confidence": "number",
    },
    "agent2": {
        "responsibility": "responsibility",
        "reasoning": "string",
        "confidence": "number",
        "key_factors": "list",
    },
    "agent3": {
        "judgment_summary": "string",
        "action": ("enum", ["退款", "退货", "赔付", "无需处理", "需人工"]),
        "amount": "number",
        "responsibility_summary": "string",
        "confidence": "number",
        "tags": "list?",
    },
    # 1-AGENT 输出 schema v2（2026-08-12 确认拍板切 1 AGENT 后定稿）
    # 依据: 判责结果表写字段 + ground truth 样例 + business_context §4.3 推理链
    "single": {
        "store_expected": ("enum", ["应退货", "应赔付", "应退货或赔付", "需人工"]),
        "store_expected_amount": "number",
        "action": ("enum", ["赔付", "退货", "退款", "无需处理", "需人工"]),
        "amount": "number",
        "responsibility": "responsibility",
        "price_uplift_result_type": ("enum", ["同意", "拒绝", "需人工"]),
        "expectation_satisfaction_type": ("enum", ["完全满足", "部分满足", "不满足", "需人工"]),
        "judgment_summary": "string",
        "judgment_basis": "judgment_basis",
        "reasoning": "string",
        "confidence": "number",
        "key_factors": "list",
        "tags": "list?",
    },
}

JUDGMENT_BASIS_PARTS = ["store_profile", "fact_finding", "responsibility_reasoning",
                        "rule_reference", "decision_comparison"]


def _check_field(name: str, value: Any, spec: Any) -> Optional[str]:
    optional = isinstance(spec, str) and spec.endswith("?")
    base = spec[:-1] if optional else spec
    if value is None:
        return None if optional else f"必填缺失: {name}"
    if isinstance(base, tuple) and base[0] == "enum":
        if value not in base[1]:
            return f"enum 非法: {name}={value!r}"
        return None
    if base == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"类型错: {name} 应为 number, 实为 {type(value).__name__}"
        return None
    if base == "string":
        if not isinstance(value, str):
            return f"类型错: {name} 应为 string, 实为 {type(value).__name__}"
        return None
    if base == "list":
        if not isinstance(value, list):
            return f"类型错: {name} 应为 list, 实为 {type(value).__name__}"
        return None
    if base == "responsibility":
        if not isinstance(value, dict):
            return f"类型错: {name} 应为 dict, 实为 {type(value).__name__}"
        errs = []
        for k in ("platform", "merchant"):
            v = value.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                errs.append(f"类型错: {name}.{k} 应为 number")
        return "; ".join(errs) if errs else None
    if base == "judgment_basis":
        if not isinstance(value, dict):
            return f"类型错: {name} 应为 dict, 实为 {type(value).__name__}"
        errs = []
        for part in JUDGMENT_BASIS_PARTS:
            v = value.get(part)
            if not isinstance(v, str) or not v.strip():
                errs.append(f"必填缺失: {name}.{part}")
        return "; ".join(errs) if errs else None
    return None


def validate_output(agent: str, obj: dict) -> list[str]:
    schema = AGENT_OUTPUT_SCHEMAS[agent]
    errors = []
    for name, spec in schema.items():
        err = _check_field(name, obj.get(name), spec)
        if err:
            errors.append(err)
    return errors


# ============================================================
# 探针执行单元
# ============================================================

@dataclass
class ProbeRunResult:
    agent: str
    sample_id: str
    run_index: int
    ok: bool = False
    output: Optional[dict] = None
    format_errors: list = field(default_factory=list)
    latency_ms: int = 0
    prompt_chars: int = 0
    completion_tokens: Optional[int] = None
    error: Optional[str] = None
    skipped: bool = False
    # raw artifact（不进报告 JSON）
    prompt: str = ""
    raw_content: str = ""


def _exec_agent(cfg, env, client, agent, sample, judgment_rules,
                run_index, upstream=None) -> ProbeRunResult:
    sample_id = sample.get("item_id") or "?"
    res = ProbeRunResult(agent=agent, sample_id=sample_id, run_index=run_index)
    ctx = build_render_context(cfg, sample, agent, judgment_rules, upstream)
    res.prompt = render_prompt(env, agent, ctx)
    res.prompt_chars = len(res.prompt)
    llm_res = call_llm(client, res.prompt, cfg)
    res.latency_ms = llm_res.latency_ms
    res.completion_tokens = llm_res.completion_tokens
    res.raw_content = llm_res.content
    if llm_res.error:
        res.error = llm_res.error
        return res
    try:
        obj = extract_json(llm_res.content)
    except ProbeFormatError as e:
        res.format_errors.append(str(e))
        return res
    errs = validate_output(agent, obj)
    res.output = obj
    res.format_errors = errs
    res.ok = not errs
    return res


def probe_single_flow(cfg, env, client, sample, judgment_rules, run_index=0):
    """T1.5：1-AGENT 完整流程（融合模板单次调用）。返回 [ProbeRunResult]。"""
    res = _exec_agent(cfg, env, client, "single", sample, judgment_rules, run_index)
    if res.output and isinstance(res.output.get("responsibility"), dict):
        corrected = allocate_correction(res.output["responsibility"])
        res.output["responsibility_corrected"] = corrected
        if corrected == {"platform": 0, "merchant": 0}:
            # 模板契约：规则无匹配/必填缺失 → 0/0 + confidence=0 = 需人工信号（合法输出，非格式错误）
            res.output["manual_review_signal"] = True
    return [res]


def probe_three_agent_chain(cfg, env, client, sample, judgment_rules, run_index=0):
    """T1.6：3 AGENT 串行（真实上游输出，不造假输入）。返回 [a1, a2, a3]。"""
    sid = sample.get("item_id") or "?"
    a1 = _exec_agent(cfg, env, client, "agent1", sample, judgment_rules, run_index)
    results = [a1]
    if not a1.ok:
        for agent in ("agent2", "agent3"):
            results.append(ProbeRunResult(agent=agent, sample_id=sid, run_index=run_index,
                                          skipped=True,
                                          error=f"上游 agent1 未通过（ok={a1.ok}），跳过"))
        return results
    a2 = _exec_agent(cfg, env, client, "agent2", sample, judgment_rules, run_index,
                     upstream={"agent1": a1.output})
    results.append(a2)
    corrected = None
    if a2.ok and isinstance(a2.output.get("responsibility"), dict):
        corrected = allocate_correction(a2.output["responsibility"])
        if corrected == {"platform": 0, "merchant": 0}:
            # 模板契约：规则无匹配/必填缺失 → 0/0 + confidence=0 = 需人工信号（合法输出，非格式错误）
            # 链路继续：9 类失败处理仅在最终 AGENT 后执行（architecture.md §3）
            a2.output["manual_review_signal"] = True
    if not a2.ok:
        results.append(ProbeRunResult(agent="agent3", sample_id=sid, run_index=run_index,
                                      skipped=True, error="上游 agent2 未通过，跳过"))
        return results
    a3 = _exec_agent(cfg, env, client, "agent3", sample, judgment_rules, run_index,
                     upstream={"agent1": a1.output, "agent2": a2.output,
                               "responsibility_corrected": corrected})
    results.append(a3)
    return results


# ============================================================
# 一致性（eval_standard §2：同输入 N 次）
# ============================================================

def _consistency_unit(outputs: list[Optional[dict]]) -> dict:
    valid = [o for o in outputs if isinstance(o, dict)]
    if len(valid) < 2:
        return {"strict": None, "core": None}
    keys = set()
    for o in valid:
        keys.update(o.keys())
    keys -= {"responsibility_corrected", "manual_review_signal"}  # 派生值，不算独立输出
    strict_diff = core_diff = 0
    core_total = 0
    for k in sorted(keys):
        vals = {json.dumps(o.get(k), ensure_ascii=False, sort_keys=True) for o in valid}
        differs = len(vals) > 1
        if differs:
            strict_diff += 1
        if k not in FREE_TEXT_FIELDS:
            core_total += 1
            if differs:
                core_diff += 1
    return {
        "strict": round(strict_diff / len(keys), 4) if keys else None,
        "core": round(core_diff / core_total, 4) if core_total else None,
    }


def measure_consistency(all_runs: dict[str, list[list[ProbeRunResult]]]) -> dict:
    """all_runs: sample_id → [run0 链, run1 链, ...]；按 AGENT 切片聚合。"""
    units: dict[str, list] = {}  # "sample#agent" → [output_per_run]
    for sid, runs in all_runs.items():
        agents_in_run = sorted({r.agent for run in runs for r in run})
        for agent in agents_in_run:
            outs = []
            for run in runs:
                hit = [r for r in run if r.agent == agent]
                outs.append(hit[0].output if hit else None)
            units[f"{sid}#{agent}"] = outs
    strict_vals, core_vals = [], []
    per_unit = {}
    for key, outs in units.items():
        u = _consistency_unit(outs)
        per_unit[key] = u
        if u["strict"] is not None:
            strict_vals.append(u["strict"])
        if u["core"] is not None:
            core_vals.append(u["core"])
    return {
        "strict": round(sum(strict_vals) / len(strict_vals), 4) if strict_vals else None,
        "core": round(sum(core_vals) / len(core_vals), 4) if core_vals else None,
        "units": len(units),
        "detail": per_unit,
    }


# ============================================================
# 报告（eval_standard §8 对齐）+ raw artifact
# ============================================================

def _p95(values: list[int]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    idx = max(0, math.ceil(0.95 * len(s)) - 1)
    return round(s[idx] / 1000, 3)  # ms → s


def _write_raw_artifacts(out_dir: Path, probe_type: str, sample_id: str,
                         runs: list[list[ProbeRunResult]]) -> None:
    payload = []
    for run_index, run in enumerate(runs):
        for r in run:
            payload.append({
                "agent": r.agent, "run_index": run_index, "sample_id": sample_id,
                "ok": r.ok, "skipped": r.skipped, "error": r.error,
                "format_errors": r.format_errors, "latency_ms": r.latency_ms,
                "prompt_chars": r.prompt_chars, "prompt": r.prompt,
                "raw_content": r.raw_content, "output": r.output,
            })
    safe_id = re.sub(r"[^\w\-]", "_", str(sample_id))
    path = out_dir / f"raw_{probe_type}_{safe_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_report(probe_type: str, cfg: dict,
                 all_runs: dict[str, list[list[ProbeRunResult]]]) -> dict:
    flat = [r for runs in all_runs.values() for run in runs for r in run if not r.skipped]
    total = len(flat)
    ok_count = sum(1 for r in flat if r.ok)
    latencies = [r.latency_ms for r in flat if r.latency_ms > 0]
    per_agent_latency: dict[str, list[int]] = {}
    for r in flat:
        per_agent_latency.setdefault(r.agent, []).append(r.latency_ms)
    consistency = measure_consistency(all_runs)
    manual_review_signals = sum(
        1 for r in flat if r.output and r.output.get("manual_review_signal"))
    details = []
    for sid, runs in all_runs.items():
        first = runs[0] if runs else []
        actual = {}
        for r in first:
            actual[r.agent] = {
                "output": r.output, "ok": r.ok, "skipped": r.skipped,
                "error": r.error, "format_errors": r.format_errors,
                "latency_ms": r.latency_ms,
            }
        details.append({
            "sample_id": sid,
            "expected": None,          # Round 2 人工标注填充
            "actual": actual,
            "match": None,             # Round 2 准确率对比
            "latency_ms": sum(r.latency_ms for r in first),
            "runs": len(runs),
        })
    llm = cfg["probe"]["llm"]
    return {
        "probe_type": probe_type,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": llm["model"],
        "samples_count": len(all_runs),
        "runs_per_sample": cfg["probe"].get("consistency_runs", 3),
        "accuracy": None,              # Round 1 无标注；键保留（§8 对齐）
        "consistency": {k: v for k, v in consistency.items() if k != "detail"},
        "consistency_detail": consistency["detail"],
        "latency_p95": _p95(latencies),
        "latency_by_agent_p95": {a: _p95(v) for a, v in sorted(per_agent_latency.items())},
        "format_check_rate": round(ok_count / total, 4) if total else None,
        "manual_review_signals": manual_review_signals,
        "total_llm_calls": total,
        "error_runs": [
            {"sample_id": r.sample_id, "agent": r.agent, "run_index": r.run_index,
             "error": r.error, "format_errors": r.format_errors}
            for r in flat if not r.ok
        ],
        "details": details,
    }


def write_report(cfg: dict, report: dict, out_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"probe_report_{report['probe_type']}_{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ============================================================
# 编排入口
# ============================================================

def _run_mode(mode: str, cfg, env, client, samples, judgment_rules, runs,
              out_dir: Path) -> dict:
    probe_type = {"1agent": "1agent", "3agent": "3agent_single"}[mode]
    flow = probe_single_flow if mode == "1agent" else probe_three_agent_chain
    all_runs: dict[str, list[list[ProbeRunResult]]] = {}
    for i, sample in enumerate(samples):
        sid = sample.get("item_id") or f"sample_{i}"
        logger.info("[%s] sample %d/%d: %s (%d runs)", mode, i + 1, len(samples), sid, runs)
        sample_runs = []
        for run_index in range(runs):
            chain = flow(cfg, env, client, sample, judgment_rules, run_index)
            sample_runs.append(chain)
            for r in chain:
                status = "ok" if r.ok else ("skip" if r.skipped else "FAIL")
                logger.info("    %s run%d: %s (%dms)%s", r.agent, run_index, status,
                            r.latency_ms, f" {r.format_errors or r.error}" if not r.ok and not r.skipped else "")
        all_runs[sid] = sample_runs
        _write_raw_artifacts(out_dir, probe_type, sid, sample_runs)
    report = build_report(probe_type, cfg, all_runs)
    path = write_report(cfg, report, out_dir)
    logger.info("[%s] 报告: %s (format_check_rate=%s, latency_p95=%ss)",
                mode, path, report["format_check_rate"], report["latency_p95"])
    return {"probe_type": probe_type, "report": str(path),
            "format_check_rate": report["format_check_rate"],
            "latency_p95": report["latency_p95"],
            "consistency": report["consistency"],
            "samples_count": report["samples_count"],
            "total_llm_calls": report["total_llm_calls"],
            "accuracy": None}


def run_probe(args, cfg, logger_=None) -> dict:
    """main.py cmd_probe 委托入口。"""
    out_dir = resolve_probe_output_dir(cfg)
    if getattr(args, "samples_file", None):
        sampleset = json.loads(Path(args.samples_file).read_text(encoding="utf-8"))
    else:
        limit = getattr(args, "samples", None) or cfg["probe"]["task_fetch"]["limit_default"]
        sampleset = build_samples_live(cfg, limit=limit)
    samples = sampleset.get("samples") or []
    if not samples:
        raise RuntimeError("samples 为空，无法跑探针")
    limit = getattr(args, "samples", None)
    if limit:
        samples = samples[:limit]
    judgment_rules = (sampleset.get("run_context") or {}).get("judgment_rules") or []
    runs = getattr(args, "runs", None) or cfg["probe"].get("consistency_runs", 3)
    mode = getattr(args, "probe_mode", "both")

    env = make_jinja_env()
    client = make_client(cfg)
    results = []
    if mode in ("1agent", "both"):
        results.append(_run_mode("1agent", cfg, env, client, samples, judgment_rules, runs, out_dir))
    if mode in ("3agent", "both"):
        results.append(_run_mode("3agent", cfg, env, client, samples, judgment_rules, runs, out_dir))
    return {"mode": mode, "runs": runs, "results": results}


# ============================================================
# Phase 0 兼容签名（内部转调新实现）
# ============================================================

def probe_agent(prompt: str = None, agent_name: str = "agent1", **kwargs) -> dict[str, Any]:
    """单 AGENT 探针（Phase 0 签名保留；新实现走 run_probe / _exec_agent）。"""
    raise NotImplementedError(
        "Phase 1 新实现请走 main.py probe（--probe-mode）或 run_probe()；"
        "Phase 0 的裸 prompt 签名不再支持")


def probe_agents_compare(agent_names: list[str] = None, samples: int = 5, **kwargs) -> dict[str, Any]:
    """1 vs 3 对比（T1.7 决策门 Round 2：加准确率后判定，见 architecture.md §3.5）。"""
    raise NotImplementedError(
        "Round 1 只跑通不判定；Round 2 标注就绪后实现 1 vs 3 决策门")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="probe_llm", description="应用层探针框架")
    parser.add_argument("--probe-mode", choices=["1agent", "3agent", "both"], default="both")
    parser.add_argument("--samples-file", default=None)
    parser.add_argument("--samples", type=int, default=None, help="样本数（缺省用样本文件全量）")
    parser.add_argument("--runs", type=int, default=None, help="一致性次数（默认 config consistency_runs）")
    args = parser.parse_args()
    cfg = load_config()
    result = run_probe(args, cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
