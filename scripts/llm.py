#!/usr/bin/env python3
"""
llm.py — LLM 调用层生产实现（Phase 2）

契约来源：
  - config.yaml llm 块：shared_chain（4 模型）/ agent3_chain（2 模型）/
    params（max_tokens/temperature）/ retry（backoff + honor_retry_after）
  - D-20260807-003：probe_llm.py 不 import 本模块（探针自带客户端）；
    本模块是生产实现，Phase 3 主流程消费
  - D-20260812-007 切 1 AGENT：single 调用走共享链；agent3_chain 仅
    3 AGENT 暂停轨道保留引用（select_chain 兼容）
  - 开发栈（CLAUDE.md §2）：本地 = DashScope qwen-plus-latest 单模型占位
    全链（dev_chain）；生产 = 妙搭 innerapi（MiaodaBackend，Phase 4 实现）

降级链编排（call_with_fallback）：
  按链顺序试模型；retryable 错误（llm_rate_limit/llm_5xx/llm_timeout）
  先按 retry.backoff_seconds 重试当前模型（honor_retry_after 优先），
  retry_max 耗尽 → 降级下一模型；全链失败 → ChainExhaustedError
  （error_kind 供 failure_handler 分类）。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

# ── 9 类失败中的 LLM 相关类型（failure_handler 名单对齐）──
ERR_RATE_LIMIT = "llm_rate_limit"
ERR_5XX = "llm_5xx"
ERR_TIMEOUT = "llm_timeout"      # 编排内部细分，failure_handler 归类时映射到 retry 类
ERR_UNKNOWN = "llm_unknown"      # 非 retryable（4xx 非 429 / 其他异常）

RETRYABLE_KINDS = frozenset({ERR_RATE_LIMIT, ERR_5XX, ERR_TIMEOUT})


@dataclass
class LLMResponse:
    content: str
    latency_ms: int
    model: str
    attempts: int = 1
    error: Optional[str] = None
    error_kind: Optional[str] = None
    retry_after: Optional[float] = None
    completion_tokens: Optional[int] = None


class ChainExhaustedError(RuntimeError):
    """4+2 降级链全失败（9 类失败映射入口：error_kind 保留最后一次错误类型）。"""

    def __init__(self, error_kind: str, message: str):
        super().__init__(message)
        self.error_kind = error_kind


class Backend(Protocol):
    def call(self, model: str, prompt: str, params: dict) -> LLMResponse: ...


# ============================================================
# 错误分类
# ============================================================

def classify_error(exc: Exception) -> tuple[str, Optional[float]]:
    """异常 → (error_kind, retry_after)。openai SDK 感知但不硬依赖。"""
    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError
    except ImportError:
        return ERR_UNKNOWN, None
    if isinstance(exc, APITimeoutError):
        return ERR_TIMEOUT, None
    if isinstance(exc, APIConnectionError):
        return ERR_5XX, None  # 连接类按 infra 错误重试
    if isinstance(exc, APIStatusError):
        code = getattr(exc, "status_code", None)
        if code == 429:
            retry_after = None
            resp = getattr(exc, "response", None)
            raw = getattr(getattr(resp, "headers", None), "get", lambda *_: None)("retry-after")
            if raw:
                try:
                    retry_after = float(raw)
                except (TypeError, ValueError):
                    retry_after = None
            return ERR_RATE_LIMIT, retry_after
        if isinstance(code, int) and code >= 500:
            return ERR_5XX, None
        return ERR_UNKNOWN, None  # 4xx 非 429 = 不重试
    return ERR_UNKNOWN, None


# ============================================================
# 链选择
# ============================================================

def select_chain(cfg: dict, agent: str) -> list[str]:
    """agent → 模型链。single/agent1/agent2 = 共享链；agent3 = 独立链（暂停轨道）。"""
    llm_cfg = cfg["llm"]
    if agent == "agent3":
        return list(llm_cfg.get("agent3_chain") or llm_cfg["shared_chain"])
    return list(llm_cfg["shared_chain"])


def dev_chain(cfg: dict) -> list[str]:
    """开发环境链：qwen-plus-latest 单模型占位全链（config llm.dev 块）。"""
    return [cfg["llm"]["dev"]["model"]]


# ============================================================
# 后端
# ============================================================

class DashScopeBackend:
    """开发后端：DashScope OpenAI 兼容端点（openai SDK，config llm.dev 块）。

    max_tokens 后端内封顶：调用方可传生产 params（30000），本后端按
    llm.dev.max_tokens（8192）封顶——后端知道自己的限制，调用方无感。
    """

    def __init__(self, cfg: dict):
        from openai import OpenAI  # noqa: PLC0415
        p = cfg["llm"]["dev"]
        api_key = os.environ.get(p["api_key_env"])
        if not api_key:
            raise RuntimeError(f"env {p['api_key_env']} 缺失 — 先 source .env")
        self.client = OpenAI(api_key=api_key, base_url=p["base_url"])
        self.timeout = p.get("timeout_seconds", 60)
        self.max_tokens_cap = p.get("max_tokens", 8192)
        self.temperature_default = p.get("temperature", 0.1)

    def call(self, model: str, prompt: str, params: dict) -> LLMResponse:
        t0 = time.perf_counter()
        max_tokens = params.get("max_tokens")
        max_tokens = min(max_tokens, self.max_tokens_cap) if max_tokens else self.max_tokens_cap
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=params.get("temperature", self.temperature_default),
                timeout=self.timeout,
            )
            latency = int((time.perf_counter() - t0) * 1000)
            usage = getattr(resp, "usage", None)
            return LLMResponse(
                content=(resp.choices[0].message.content or ""),
                latency_ms=latency, model=model,
                completion_tokens=getattr(usage, "completion_tokens", None))
        except Exception as e:  # noqa: BLE001 — 统一收敛为 LLMResponse
            latency = int((time.perf_counter() - t0) * 1000)
            kind, retry_after = classify_error(e)
            return LLMResponse(content="", latency_ms=latency, model=model,
                               error=f"{type(e).__name__}: {e}",
                               error_kind=kind, retry_after=retry_after)


class MiaodaBackend:
    """生产后端：妙搭 innerapi（openclaw subprocess 调用）。

    model 入参格式：miaoda/glm-5.1（chain 已带前缀，直接传给 openclaw）。
    调用方式：openclaw infer model run --model <model> --prompt <prompt> --json
    """

    def __init__(self, cfg: dict):
        llm_cfg = cfg.get("llm", {})
        self.timeout = llm_cfg.get("timeout_seconds", 120)
        self.max_tokens_cap = llm_cfg.get("params", {}).get("max_tokens", 30000)

    def call(self, model: str, prompt: str, params: dict) -> LLMResponse:
        """通过 openclaw subprocess 调用妙搭 LLM。

        返回 LLMResponse；所有异常收敛到 error_kind，不上抛。
        """
        import json
        import subprocess

        t0 = time.perf_counter()
        max_tokens = params.get("max_tokens")
        max_tokens = min(max_tokens, self.max_tokens_cap) if max_tokens else self.max_tokens_cap

        try:
            result = subprocess.run(
                ["openclaw", "infer", "model", "run",
                 "--model", model,          # model 已是 "miaoda/glm-5.1" 完整格式
                 "--prompt", prompt,
                 "--json"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            latency = int((time.perf_counter() - t0) * 1000)

            # 检查进程退出码
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()[:200]
                return LLMResponse(
                    content="", latency_ms=latency, model=model,
                    error=f"openclaw exit {result.returncode}: {stderr}",
                    error_kind=ERR_5XX)

            # 解析 JSON
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                return LLMResponse(
                    content="", latency_ms=latency, model=model,
                    error=f"JSON decode failed: {e}",
                    error_kind=ERR_5XX)

            # 检查业务状态
            if not data.get("ok"):
                return LLMResponse(
                    content="", latency_ms=latency, model=model,
                    error=f"openclaw ok=false: {data}",
                    error_kind=ERR_UNKNOWN)  # 业务失败不重试

            # 提取输出文本
            outputs = data.get("outputs") or []
            text = outputs[0].get("text", "") if outputs else ""

            return LLMResponse(
                content=text,
                latency_ms=latency,
                model=model,
                completion_tokens=None)  # openclaw 输出不含 token 统计

        except subprocess.TimeoutExpired:
            latency = int((time.perf_counter() - t0) * 1000)
            return LLMResponse(
                content="", latency_ms=latency, model=model,
                error=f"openclaw timeout after {self.timeout}s",
                error_kind=ERR_TIMEOUT)

        except Exception as e:  # noqa: BLE001 — 统一收敛为 LLMResponse
            latency = int((time.perf_counter() - t0) * 1000)
            kind, retry_after = classify_error(e)
            return LLMResponse(
                content="", latency_ms=latency, model=model,
                error=f"{type(e).__name__}: {e}",
                error_kind=kind, retry_after=retry_after)


# ============================================================
# 降级链编排
# ============================================================

def call_with_fallback(backend: Backend, prompt: str, chain: list[str],
                       params: dict, retry_cfg: dict,
                       sleep_fn: Callable[[float], None] = time.sleep) -> LLMResponse:
    """按链顺序调用 + 模型内重试 + 降级。全部失败抛 ChainExhaustedError。

    sleep_fn 注入便于测试（无真实等待）。
    """
    if not chain:
        raise ValueError("chain 为空")
    max_retry = int(retry_cfg.get("max", 3))
    backoffs = retry_cfg.get("backoff_seconds") or [0.5, 1, 2]
    honor_ra = bool(retry_cfg.get("honor_retry_after", True))
    last: Optional[LLMResponse] = None
    for model in chain:
        for attempt in range(max_retry + 1):
            res = backend.call(model, prompt, params)
            res.attempts = attempt + 1
            if res.error is None:
                return res
            last = res
            if res.error_kind not in RETRYABLE_KINDS or attempt >= max_retry:
                break  # 非 retryable 或本模型重试耗尽 → 降级下一模型
            if honor_ra and res.retry_after:
                delay = res.retry_after
            else:
                delay = backoffs[min(attempt, len(backoffs) - 1)]
            sleep_fn(delay)
    raise ChainExhaustedError(
        last.error_kind if last else ERR_UNKNOWN,
        f"降级链全失败: {chain}; last={last.error if last else None}")
