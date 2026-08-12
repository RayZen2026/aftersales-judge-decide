# 评估标准(草稿)

> **范围**: AGENT 1/2/3 单 AGENT 探针回归 + 端到端评估
> **状态**: Phase 0 草稿(确认 + 助手 Phase 1.3 联合定稿)
> **来源**: 解析层 SKILL 评估经验 + v1.5 doc §6.1 + v2 规划 T0.3

---

## 1. 准确率(每 AGENT 单独跑)

| 阈值 | 标准 | 评估方式 |
|---|---|---|
| **≥ 85%** | 通过 | 探针结果 vs 期望结果(人工标)对比,正确率 ≥ 85% |
| 70-85% | 警告(可继续,但需调优) | 同上 |
| < 70% | 不通过(回退或强制定版) | 同上 |

**样本分布要求**:
- 成功 case ≥ 5 条
- manual_review case ≥ 3 条
- 终态失败 case ≥ 2 条
- 总数 10-20 条(确认拍板样本量分层)

## 2. 一致性(相同输入跑 3 次)

| 阈值 | 标准 |
|---|---|
| **不一致率 ≤ 5%** | 通过 |
| 5-15% | 警告 |
| > 15% | 不通过(降低 temperature 或调 prompt) |

**测量方法**: 相同输入跑 3 次,对比输出,字段级别不一致数 / 总字段数 ≤ 5%

**优化方向**:
- temperature=0.1(已拍板,看是否需要降到 0.0)
- 加 few-shot examples(Phase 1.5 探针评估)

## 3. latency

| 阶段 | P95 阈值 | 备注 |
|---|---|---|
| 单 AGENT 探针 | **≤ 8s** | AGENT 1/2/3 各自 ≤ 8s |
| 3 AGENT 串行 | **≤ 24s** | 3 × 8s = 24s(无并发,理论上限) |
| 端到端(含锁/写表/通知) | **≤ 30s** | 24s + 6s 系统开销 |
| cron 触发开销 | **≤ 10s** | OpenClaw cron 调度延迟 |

**性能预算**:
- LLM 调用(P95)≤ 8s × 3 = 24s
- 飞书 bitable 读写 ≤ 3s × 4 = 12s
- 飞书通知 ≤ 2s
- 锁/状态机 ≤ 1s
- **总计 ≤ 39s**(理论上限),实际期望 ≤ 30s

## 4. 格式校验

| 项 | 标准 |
|---|---|
| JSON 解析成功率 | **100%** |
| 必填字段完整率 | **100%** |
| 字段类型匹配率 | **100%** |
| enum 值合法率 | **100%** |

**任一项不达标** → 9 类失败之一"非 JSON"/"必填缺失"/"字段类型错",转 manual_review 或 终态失败

## 5. 资源

| 资源 | 阈值 |
|---|---|
| CPU 峰值 | < 80% |
| 内存 | < 2GB |
| 磁盘(探针输出 + 日志) | < 1GB |
| 飞书 API 调用频率 | < 10 req/s(避免 429) |

## 6. 人工 review 流程(占位,Phase 1.3 确认定稿)

### 6.1 触发条件

- AGENT 输出 `store_expected="需人工"` 或 `action="需人工"`
- 9 类失败分类中的"业务问题"类
- confidence < 0.5(占位,Phase 1.3 拍板阈值)

### 6.2 通知渠道(已拍板,决策 16)

- 飞书私聊确认(`ou_8f870f9b1670d27d033d91fda17ade4e`)
- memory_file 双通道备份
- 24h 同单号同异常类型去重(D-20260806-011)

### 6.3 运营处理流程(待定稿)

- [ ] 运营收到通知,登录飞书任务表查看详情
- [ ] 人工补全数据 / 改判责 / 接受默认
- [ ] 状态机推进: 已处理-需人工 → 已处理-成功(改写) / 已处理-失败(放弃)
- [ ] 改写后不重跑 AGENT(避免循环)

## 7. 评估脚本(Phase 1.3 定稿后写)

```python
# scripts/evaluate.py (占位)
# 输入: probe_results.json (探针结果) + samples_v1.json (期望结果)
# 输出: 评估报告(准确率 / 一致性 / latency / 格式校验)

def evaluate(probe_results, samples):
    accuracy = compute_accuracy(probe_results, samples)
    consistency = compute_consistency(probe_results)
    latency = compute_latency_p95(probe_results)
    format_check = compute_format_check(probe_results)
    return {
        "accuracy": accuracy,
        "consistency": consistency,
        "latency_p95": latency,
        "format_check": format_check,
    }
```

## 8. 探针报告格式(占位)

```json
{
  "probe_type": "1agent" | "3agent_single" | "3agent_full" | "e2e",
  "timestamp": "2026-08-08T...",
  "samples_count": 10,
  "accuracy": 0.87,
  "consistency": 0.03,
  "latency_p95": 7.2,
  "format_check_rate": 1.0,
  "details": [
    {
      "sample_id": "...",
      "expected": {...},
      "actual": {...},
      "match": true,
      "latency_ms": 7234
    }
  ]
}
```

## 9. 阈值表(汇总)

| 维度 | 通过 | 警告 | 不通过 |
|---|---|---|---|
| 准确率 | ≥ 85% | 70-85% | < 70% |
| 一致性(不一致率) | ≤ 5% | 5-15% | > 15% |
| 单 AGENT latency P95 | ≤ 8s | 8-12s | > 12s |
| 3 AGENT 串行 P95 | ≤ 24s | 24-36s | > 36s |
| 端到端 P95 | ≤ 30s | 30-45s | > 45s |
| JSON 解析成功率 | 100% | — | < 100% |
| 资源占用 | < 80% | — | > 80% |
