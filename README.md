# aftersales-judge-decide

> 升级售后判责主流程 SKILL — 编排 + 执行升级售后判责流程,从飞书多维表格拉取待判责任务,串行调度 N 个 AGENT 调用 LLM 完成判责,维护 5 状态机,处理 9 类失败,写飞书任务表 + 判责结果表,通过飞书私聊双通道通知运营(24h 去重)。

## 状态

**Phase 0 PROPOSAL 阶段结束 (v7 → v8 → v9 applied)**

- skill_workshop 实物 v9: `aftersales-judge-decide-20260809-2b41940fbe` status=**applied** (13:57:04)
- skill_workshop 历史 v7: `aftersales-judge-decide-20260808-41793072a7` status=**applied** (13:35:46)
- 实物 SKILL.md: 154 行 / 5769 字节 / sha256 `f7f8f553...`
- Phase 0 实施日期: 2026-08-08 (v1-v7) → 2026-08-09 (v8-v9 按 v2 §10.4 反模式「把 README 塞进 body」优化)

## 关联

| 资源 | 链接 |
|---|---|
| 飞书设计方案 doc | v1.5 doc (workspace 外) + v1.6 doc (Phase 1.5 探针后升版, 拍板项 11) |
| 解析层 SKILL | `aftersales-rules-parse` (只读判责规则表) |
| 探针工具 | `scripts/probe_llm.py` (Phase 0 stub, Phase 1.4 实质) |

## Phase 0 文档

- PROPOSAL v9 实物: `skill-workshop/proposals/aftersales-judge-decide-20260809-2b41940fbe/PROPOSAL.md` (v2 模板, status=applied, **不在 SKILL 仓库内**)
- PROPOSAL v7 备份: `skill-workshop/proposals/aftersales-judge-decide-20260808-41793072a7/PROPOSAL.md` (v7 applied 13:35)
- [`references/architecture.md`](references/architecture.md) — 架构附录(流程图 / 抢锁矩阵 / 决策表)
- [`references/implementation_plan.md`](references/implementation_plan.md) — 6 Phase 开发节奏

## 决策历史 (audit trail)

| ID | 类型 | 决策内容 | 拍板人 / 时间 |
|---|---|---|---|
| **D-20260806-001** | 决策 | 9 类失败 → 3 大类 (retry / 不重试 / 业务问题) | 任锐 04:53 UTC |
| **D-20260806-006** | 决策 | 5 状态机 (待处理 / 已处理-处理中 / 已处理-成功 / 已处理-失败 / 已处理-需人工) | 解析层复用 |
| **D-20260806-011** | 决策 | 飞书通知双通道 (私聊任锐 + memory/YYYY-MM-DD.md) + 24h 去重 | 拍板 |
| **LRN-20260802-013** | 教训 | kimi-k2.6 已移出降级链 (17-22s 慢得不合理, 比 qwen 慢 80%) | 探针验证 |
| **LRN-20260807-001** | 教训 | 探针先行原则 (强规则, AGENT 切分/prompt 模板/降级链**必须在拍板前**跑过探针) | 实战经验 |
| **LCE-20260808-006** | 教训 | 6 维度表 → 3 维度表合并 (商家四级类目表 + 四级类目表 + 商家维度统计表 + 商品维度统计表 4 张合并到商品维度统计表, 门店表保留) | 实施期发现 |

## 拍板项 (任锐 14:11-14:16 拍板 6 Phase 框架 + Phase 5 观察期 1 周)

- 4+2 LLM 降级链: 共享链 (AGENT 1/2) glm-5.1 → qwen-3.7-plus → doubao-seed-2.0-pro → minimax-m3 + AGENT 3 独立链 doubao-seed-2.0-pro → minimax-m3
- 9 类失败 → 3 大类 (retry-able 4 类 / 不重试 3 类 / 业务问题 2 类)
- 5 状态机 (待处理 / 已处理-处理中 / 已处理-成功 / 已处理-失败 / 已处理-需人工)
- 8 magic number (实物 SKILL.md 8 Magic Number 段)
- 探针 3 轮调优上限: 1 轮 = 跑 1 次单 AGENT 探针 (5-10 样本 × 3 AGENT) + 评估 + 调 1 次切分; 3 轮不收敛 → 强制定版当前最佳切分 + 风险标到生产观察期 1 周
- 探针样本量分层: Phase 1.5-1.7 基础测试 5-10 样本 / Phase 3 回归 10-20 样本 / Phase 4.1 端到端 1→3→10→30 单
- Phase 5 观察期 1 周 (7 天 × 14 次/天 = 98 次 cron 触发)
- 维度表 6 → 3 合并 (任务表 + 判责结果表 + 商品维度统计表 + 门店表)
- **拍板项 11 v1.6 触发时机**: Phase 1.5 探针收口后, 触发 v1.6 doc 升版

## 探针先行原则 (强规则, LRN-20260807-001)

- AGENT 切分、prompt 模板、降级链**必须在拍板前**跑过探针
- 探针支撑 (业务 prompt 模板占位版 + 真实申诉数据样本 + 评估标准) 未就绪前, **不能跑业务探针**
- 3 轮调优上限 (任锐 14:16 拍板): 1 轮 = 跑 1 次单 AGENT 探针 (5-10 样本 × 3 AGENT) + 评估 + 调 1 次切分
  - 3 轮不收敛 → 强制定版当前最佳切分 + 风险标到生产观察期 1 周
- 探针**不 import** `llm.py`, 避免循环依赖 + 概念独立
- 探针**不假设**当前 SKILL 的 AGENT 数量, 测试场景比应用层更广

## 开发模式 (内部, 不对用户暴露)

SKILL 上线后**只暴露** `auto` / `manual` 2 个用户使用模式。`probe` / `test` 是 SKILL 作者/助手的开发工具, **不进 SKILL.md body**。

| 模式 | 实现 | 启动阶段 | 目的 | 引用 |
|---|---|---|---|---|
| `probe` | `scripts/main.py probe` (Phase 1.5 内部 subcommand) + 复用 `scripts/probe_llm.py` 辅助库 (Phase 0 stub, Phase 1.4 实质) | Phase 1.4-1.7 (T1.4 框架 / T1.5 1 AGENT 探针 / T1.6 3 AGENT 单 AGENT 探针 / T1.7 切分迭代 3 轮) + Phase 3 (T3.1-T3.3 单 AGENT 探针回归) | 1 vs 3 AGENT 切分对比 + 切分迭代 3 轮 + 实现回归 | `references/implementation_plan.md` §Phase 1.4-1.7 + §Phase 3 |
| `test` | `scripts/main.py test` | Phase 4.1 (T4.1 端到端探针 1→3→10→30 完整单) | 部署前完整链路验证 | `references/implementation_plan.md` §Phase 4.1 |

样本量分层 (任锐 14:16 拍板): Phase 1.5-1.7 基础测试 5-10 样本, Phase 3 回归 10-20 样本, Phase 4.1 端到端 1→3→10→30 单。

## v2 规范引用 (SKILL 撰写规范, 不进 SKILL.md body)

| 规范 | 用途 | 章节 |
|---|---|---|
| **流程图节点 ≤ 10 字** | mermaid 流程图节点文字硬限, 防止解析报错 | v2.0 §10.6 |
| **L4 替换走严格模式** | 防软替换陷阱 (SKILL 替换时严格匹配, 不模糊) | v2.0 §10.8 |
| **妙搭三件套不进 LLM 降级链** | Auto/Flash/Multimodal 不用作业务降级; prompt 硬限 ≤ 30k 字符 | v2.0 §7.5 / TOOLS.md LRN-20260802-013 |
| **preflight §7.6 模板** | 4-5 项 env 准备检查 (env / bitable / LLM / 资源 / cron 冲突) | v2.0 §7.6 |
| **SKILL.md ≤ 500 行 / 5000 token** | body 操作手册, 决策/拍板/changelog 全部移 README | v2.0 §10.4 |
| **changelog → 仓库 CHANGELOG.md** | 部署/决策历史 → README.md (本文) | v2.0 §10.4 |

## 阻塞项 (任锐 review 时一次性提供)

**v1.6 触发时机 (拍板项 11)**: Phase 1.5 探针收口后, 触发 v1.6 doc 升版

| # | 阻塞项 | 阻塞哪个 Task |
|---|---|---|
| 1 | 商品维度统计表 metadata (app_token / table_id / 字段映射) | Phase 1.1 维度数据 JOIN |
| 2 | 门店表 metadata (同上) | Phase 1.1 维度数据 JOIN |
| 3 | 真实样本数据 10-20 条 | Phase 1.2 探针基础测试 |
| 4 | 评估标准定稿 (准确率 / 一致性 / latency 阈值) | Phase 1.2 探针基础测试 |
| 5 | AGENT 1-3 切分定稿 (Phase 1.5 探针后) | Phase 1.8 v1.6 doc 升版 |

## 仓库

- GitHub: https://github.com/RayZen2026/aftersales-judge-decide
- License: Proprietary (internal use only)
- Author: ZenRay <jake2011ren@gmail.com>

---

_Phase 0 由 OpenClaw skill_workshop 起草。v9 apply 13:57 (走法 A 完整: v7 → v8 → v9, 按 v2 §10.4 反模式「把 README 塞进 body」优化)。_
