#!/usr/bin/env python3
"""探针辅助库 (Phase 0 占位, Phase 1.4 实质实现)

跟解析层 SKILL `aftersales-rules-parse/scripts/probe_llm.py` 共享设计 (DRY):
- 同样函数签名 (probe_agent / probe_agents_compare)
- 同样 LLM 降级链调用接口
- Phase 1.4 复用解析层骨架, 填充判责业务逻辑
"""
from typing import Any


def probe_agent(prompt: str, agent_name: str = "agent1", **kwargs) -> dict[str, Any]:
    """单 AGENT 探针 (Phase 0 占位)

    TODO Phase 1.4: 复用解析层 probe_llm.py 骨架, 实现判责业务探针
    """
    raise NotImplementedError(
        "probe_agent: Phase 0 stub, Phase 1.4 实现 (参考解析层 probe_llm.py)"
    )


def probe_agents_compare(agent_names: list[str], samples: int = 5, **kwargs) -> dict[str, Any]:
    """1 vs 3 AGENT 切分对比探针 (Phase 0 占位)

    TODO Phase 1.5: 跑 1 AGENT 完整流程 + 3 AGENT 串行, 对比准确率 / latency
    """
    raise NotImplementedError(
        "probe_agents_compare: Phase 0 stub, Phase 1.5 实现"
    )
