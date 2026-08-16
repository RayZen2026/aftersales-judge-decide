"""llm.py — 错误分类 / 链选择 / 降级链编排（FakeBackend，无网络）。"""
import pytest
import openai

import llm

CFG = {
    "llm": {
        "shared_chain": ["m1", "m2", "m3", "m4"],
        "agent3_chain": ["m5", "m6"],
        "dev": {"provider": "dashscope",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen-plus-latest",
                "api_key_env": "DASHSCOPE_API_KEY",
                "max_tokens": 8192,
                "temperature": 0.1,
                "timeout_seconds": 60},
        "retry": {"max": 2, "backoff_seconds": [0.1, 0.2], "honor_retry_after": True},
    },
    "probe": {"llm": {"model": "qwen-plus-latest"}},  # probe_llm 自用，llm.py 不读
}


# ── select_chain / dev_chain ──

@pytest.mark.parametrize("agent", ["agent1", "agent2", "single"])
def test_select_chain_shared(agent):
    assert llm.select_chain(CFG, agent) == ["m1", "m2", "m3", "m4"]


def test_select_chain_agent3_independent():
    assert llm.select_chain(CFG, "agent3") == ["m5", "m6"]


def test_dev_chain_single_model():
    assert llm.dev_chain(CFG) == ["qwen-plus-latest"]


# ── classify_error ──

def _status_error(code, headers=None):
    exc = openai.APIStatusError.__new__(openai.APIStatusError)
    exc.status_code = code

    class _Resp:
        def __init__(self, h):
            self.headers = h or {}

    exc.response = _Resp(headers)
    return exc


def test_classify_429_with_retry_after():
    kind, ra = llm.classify_error(_status_error(429, {"retry-after": "2.5"}))
    assert kind == "llm_rate_limit" and ra == 2.5


def test_classify_429_without_retry_after():
    kind, ra = llm.classify_error(_status_error(429))
    assert kind == "llm_rate_limit" and ra is None


def test_classify_5xx():
    kind, _ = llm.classify_error(_status_error(503))
    assert kind == "llm_5xx"


def test_classify_4xx_not_retryable():
    kind, _ = llm.classify_error(_status_error(400))
    assert kind == "llm_unknown"


def test_classify_timeout():
    exc = openai.APITimeoutError.__new__(openai.APITimeoutError)
    kind, _ = llm.classify_error(exc)
    assert kind == "llm_timeout"


def test_classify_generic_exception():
    kind, _ = llm.classify_error(RuntimeError("boom"))
    assert kind == "llm_unknown"


# ── call_with_fallback ──

class FakeBackend:
    """按脚本返回 LLMResponse 序列。"""

    def __init__(self, script):
        self.script = list(script)  # [(model, error_kind, retry_after) | (model, None)]
        self.calls = []

    def call(self, model, prompt, params):
        self.calls.append(model)
        item = self.script.pop(0)
        m, kind = item[0], item[1]
        assert m == model
        if kind is None:
            return llm.LLMResponse(content="ok", latency_ms=10, model=model)
        ra = item[2] if len(item) > 2 else None
        return llm.LLMResponse(content="", latency_ms=10, model=model,
                               error=f"fake {kind}", error_kind=kind, retry_after=ra)


def test_first_model_success():
    b = FakeBackend([("m1", None)])
    res = llm.call_with_fallback(b, "p", ["m1", "m2"], {}, CFG["llm"]["retry"],
                                 sleep_fn=lambda s: None)
    assert res.content == "ok" and res.model == "m1"
    assert b.calls == ["m1"]


def test_retry_then_success_backoff():
    sleeps = []
    b = FakeBackend([("m1", "llm_rate_limit"), ("m1", None)])
    res = llm.call_with_fallback(b, "p", ["m1"], {}, CFG["llm"]["retry"],
                                 sleep_fn=sleeps.append)
    assert res.content == "ok" and b.calls == ["m1", "m1"]
    assert sleeps == [0.1]  # backoff_seconds[0]


def test_honor_retry_after():
    sleeps = []
    b = FakeBackend([("m1", "llm_rate_limit", 7.0), ("m1", None)])
    llm.call_with_fallback(b, "p", ["m1"], {}, CFG["llm"]["retry"],
                           sleep_fn=sleeps.append)
    assert sleeps == [7.0]


def test_fallback_to_second_model():
    script = [("m1", "llm_5xx"), ("m1", "llm_5xx"), ("m1", "llm_5xx"),  # m1 重试耗尽(max=2)
              ("m2", None)]
    b = FakeBackend(script)
    res = llm.call_with_fallback(b, "p", ["m1", "m2"], {}, CFG["llm"]["retry"],
                                 sleep_fn=lambda s: None)
    assert res.model == "m2" and res.content == "ok"


def test_non_retryable_skips_retry_falls_through():
    # 4xx 不重试，直接降级下一模型
    b = FakeBackend([("m1", "llm_unknown"), ("m2", None)])
    res = llm.call_with_fallback(b, "p", ["m1", "m2"], {}, CFG["llm"]["retry"],
                                 sleep_fn=lambda s: None)
    assert res.model == "m2"
    assert b.calls == ["m1", "m2"]


def test_chain_exhausted():
    script = [("m1", "llm_5xx")] * 3 + [("m2", "llm_5xx")] * 3
    b = FakeBackend(script)
    with pytest.raises(llm.ChainExhaustedError) as ei:
        llm.call_with_fallback(b, "p", ["m1", "m2"], {}, CFG["llm"]["retry"],
                               sleep_fn=lambda s: None)
    assert ei.value.error_kind == "llm_5xx"


def test_empty_chain_raises():
    with pytest.raises(ValueError):
        llm.call_with_fallback(FakeBackend([]), "p", [], {}, {})


# ── DashScopeBackend（mock OpenAI client，无网络）──

class _FakeCompletions:
    def __init__(self, raise_exc=None):
        self.raise_exc = raise_exc
        self.last_kwargs = None

    def create(self, **kw):
        self.last_kwargs = kw
        if self.raise_exc:
            raise self.raise_exc
        from types import SimpleNamespace
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="你好"))],
            usage=SimpleNamespace(completion_tokens=7))


class _FakeClient:
    def __init__(self, raise_exc=None, **kw):
        from types import SimpleNamespace
        self.completions = _FakeCompletions(raise_exc)
        self.chat = SimpleNamespace(completions=self.completions)


def _make_backend(monkeypatch, raise_exc=None):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    client = _FakeClient(raise_exc)
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
    return llm.DashScopeBackend(CFG), client


def test_dashscope_backend_success(monkeypatch):
    b, client = _make_backend(monkeypatch)
    res = b.call("qwen-plus-latest", "prompt", {"max_tokens": 10, "temperature": 0.1})
    assert res.content == "你好" and res.error is None
    assert res.completion_tokens == 7 and res.latency_ms >= 0
    assert client.completions.last_kwargs["max_tokens"] == 10  # 未超封顶，原样传


def test_dashscope_backend_max_tokens_capped(monkeypatch):
    # 调用方传生产 params（30000）→ 后端内按 llm.dev.max_tokens=8192 封顶
    b, client = _make_backend(monkeypatch)
    b.call("qwen-plus-latest", "p", {"max_tokens": 30000})
    assert client.completions.last_kwargs["max_tokens"] == 8192


def test_dashscope_backend_max_tokens_default(monkeypatch):
    # 未传 max_tokens → 用封顶值
    b, client = _make_backend(monkeypatch)
    b.call("qwen-plus-latest", "p", {})
    assert client.completions.last_kwargs["max_tokens"] == 8192


def test_dashscope_backend_5xx(monkeypatch):
    b, _ = _make_backend(monkeypatch, raise_exc=_status_error(503))
    res = b.call("qwen-plus-latest", "p", {})
    assert res.error is not None and res.error_kind == "llm_5xx"


def test_dashscope_backend_timeout(monkeypatch):
    exc = openai.APITimeoutError.__new__(openai.APITimeoutError)
    b, _ = _make_backend(monkeypatch, raise_exc=exc)
    res = b.call("qwen-plus-latest", "p", {})
    assert res.error_kind == "llm_timeout"


def test_dashscope_backend_requires_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        llm.DashScopeBackend(CFG)


def test_miaoda_backend_init():
    """测试 MiaodaBackend 初始化读取配置"""
    backend = llm.MiaodaBackend(CFG)
    assert backend.timeout == 120  # 从 CFG["llm"]["timeout_seconds"] 读取（默认120，Issue #22修复）
    assert backend.max_tokens_cap == 30000  # 从 CFG["llm"]["params"]["max_tokens"] 读取


# ── MiaodaBackend --thinking 兼容性（P0-4 修复）──

def test_miaoda_thinking_capable_models():
    """验证 THINKING_CAPABLE 集合包含 reasoning=true 的 3 个模型，不含 minimax-m3"""
    tc = llm.MiaodaBackend.THINKING_CAPABLE
    assert "miaoda/glm-5.1" in tc
    assert "miaoda/qwen-3.7-plus" in tc
    assert "miaoda/doubao-seed-2.0-pro" in tc
    assert "miaoda/minimax-m3" not in tc  # reasoning=false，不能加 --thinking


def test_miaoda_backend_build_args_with_thinking():
    """reasoning=true 模型应注入 --thinking medium"""
    backend = llm.MiaodaBackend(CFG)
    args = backend._build_args("miaoda/glm-5.1", "test prompt")
    assert "--thinking" in args
    idx = args.index("--thinking")
    assert args[idx + 1] == "medium"
    assert "--model" in args and "miaoda/glm-5.1" in args
    assert "--json" in args


def test_miaoda_backend_build_args_without_thinking():
    """minimax-m3 (reasoning=false) 不应注入 --thinking"""
    backend = llm.MiaodaBackend(CFG)
    args = backend._build_args("miaoda/minimax-m3", "test prompt")
    assert "--thinking" not in args
    assert "--model" in args and "miaoda/minimax-m3" in args
    assert "--json" in args
