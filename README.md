# aftersales-judge-decide

> 升级售后判责主流程 SKILL — 编排 + 执行升级售后判责流程,从飞书多维表格拉取待判责任务,串行调度 N 个 AGENT 调用 LLM 完成判责,维护 5 状态机,处理 9 类失败,写飞书任务表 + 判责结果表,通过飞书私聊双通道通知运营(24h 去重)。

## 状态

**Phase 0 PROPOSAL pending 等 review**

- skill_workshop proposal_id: `aftersales-judge-decide-20260808-41793072a7`
- 状态: `pending` (scanner: clean)
- 目标: SKILL.md → `workspace/skills/aftersales-judge-decide/SKILL.md` (apply 后写入)
- Phase 0 实施日期: 2026-08-08

## 关联

| 资源 | 链接 |
|---|---|
| 飞书设计方案 doc | (待任锐补,见 v1.5 doc 完整版) |
| 解析层 SKILL | `aftersales-rules-parse` (只读判责规则表) |
| 探针工具 | `scripts/probe_llm.py` (沿用解析层骨架,DRY 共享 subprocess wrapper) |

## Phase 0 文档

- [`docs/PROPOSAL-draft.md`](docs/PROPOSAL-draft.md) — Phase 0 PROPOSAL 草稿(skill_workshop pending)
- [`docs/architecture.md`](docs/architecture.md) — 架构附录(流程图 / 抢锁矩阵 / 决策表)
- [`docs/implementation-plan.md`](docs/implementation-plan.md) — 6 Phase 开发节奏

## 拍板项 (来自 v1.5 doc + 14:11-14:16 任锐反馈)

- 4+2 LLM 降级链(共享 + AGENT 3 独立)
- 9 类失败 → 3 大类(retry / 不重试 / 业务问题)
- 5 状态机(待处理 / 已处理-处理中 / 已处理-成功 / 已处理-失败 / 已处理-需人工)
- 9 magic number(stale_timeout=5min / payment_threshold=200 / batch_size=30 / max_tokens=30000 / temperature=0.1 / retry_max=3 / dedup_window=24h / cron="0 10-23 * * *" / manual_review_threshold=待定)
- 探针 3 轮调优上限(任锐 14:16 拍板)
- 探针样本量分层(1.5 阶段 5-10 / Phase 3 回归 10-20)
- Phase 5 观察期 1 周(7 天 × 14 次/天 = 98 次 cron 触发)
- 维度表 6 → 3 合并(任务表 + 判责结果表 + 商品维度统计表 + 门店表)

## 阻塞项 (任锐 review 时一次性提供)

| # | 阻塞项 | 阻塞阶段 |
|---|---|---|
| 1 | 商品维度统计表 metadata (app_token / table_id / 字段映射) | Phase 1.1 |
| 2 | 门店表 metadata (同上) | Phase 1.1 |
| 3 | 真实样本 10-20 条 | Phase 1.2 |
| 4 | 评估标准 (准确率 / 一致性 / latency 阈值) | Phase 1.2 |
| 5 | AGENT 1-3 切分定稿 (Phase 1.5 探针后) | Phase 1.8 |

## 仓库

- GitHub: https://github.com/RayZen2026/aftersales-judge-decide
- License: Proprietary (internal use only)
- Author: ZenRay <jake2011ren@gmail.com>

---

_Phase 0 由 OpenClaw skill_workshop 起草。SKILL.md 待 apply 后入库。_
