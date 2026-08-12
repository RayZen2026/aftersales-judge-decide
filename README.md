# aftersales-judge-decide

> 升级售后判责主流程 SKILL — 从飞书多维表格拉取待判责任务，串行调度 AGENT 调用 LLM 完成判责（当前基线 3 AGENT，探针决定是否切 1 AGENT），维护 5 状态机，处理 9 类失败，写飞书任务表 + 判责结果表，通过飞书私聊双通道通知运营（24h 去重）。

## 状态

**Phase 1 准备中**（SKILL.md 探针拍板后再建）

- **SKILL.md 有意删除**（2026-08-11 确认拍板）：v9 版含过时表述（"N=3 占位"，已被纠正为"3 AGENT 是拍板基线，探针只决定 1 vs 3 切换"）。按 v2.0 §4 流程，SKILL.md 是 apply 产物，待 Phase 1.8 AGENT 切分探针拍板后按确定架构重建；v9 保留在 git 历史（commit `b8c04ce`）。
- **设计基线 = v1.5 doc，不再大调整**：3 AGENT 是当前基线（设计源 doc 8.3 拍板），探针只决定是否切 1 AGENT。决策规则见 `references/architecture.md` §3.5，业务背景见 `references/business_context.md` §5。
- **Phase 0 已完成**（2026-08-08 ~ 08-09）：PROPOSAL 经 v7 → v8 → v9 迭代，v9 由 skill_workshop apply 定版（实物 `aftersales-judge-decide-20260809-2b41940fbe`，status=applied）。

## 拍板基线

6 Phase 框架与 Phase 5 观察期 1 周由确认拍板，关键基线值：

- **4+2 LLM 降级链**：共享链（AGENT 1/2）glm-5.1 → qwen-3.7-plus → doubao-seed-2.0-pro → minimax-m3；AGENT 3 独立链 doubao-seed-2.0-pro → minimax-m3
- **9 类失败 → 3 大类**：retry-able 4 类 / 不重试 3 类 / 业务问题 2 类
- **5 状态机**：待处理 / 已处理-处理中 / 已处理-成功 / 已处理-失败 / 已处理-需人工
- **8 magic number**：SKILL.md 重建时保留独立 Magic Number 段
- **维度表 6 → 3 合并**（任务表 + 判责结果表 + 商品维度统计表 + 门店表）
- **Phase 5 观察期 1 周**：7 天 × 14 次/天 = 98 次 cron 触发
- **拍板项 11（v1.6 触发时机）**：Phase 1.5 探针收口后，触发 v1.6 doc 升版

## 探针先行原则（强规则，LRN-20260807-001）

- AGENT 切分、prompt 模板、降级链**必须在拍板前**跑过探针
- **1 vs 3 二选一**（D-20260807-004，确认拍板）：当前基线 = 3 AGENT 串行（**不是占位**，设计源 doc 8.3 拍板）；1 AGENT 完整流程探针达标 → 切 1 AGENT，不达标 → 保持 3。决策规则见 `references/architecture.md` §3.5 + `references/business_context.md` §5
- 探针支撑（业务 prompt 模板占位版 + 真实申诉数据样本 + 评估标准）未就绪前，**不能跑业务探针**
- **3 轮调优上限**：1 轮 = 跑 1 次单 AGENT 探针（5-10 样本 × 3 AGENT）+ 评估 + 调 1 次切分；3 轮不收敛 → 强制定版当前最佳切分 + 风险标到生产观察期 1 周
- 探针**不 import** `llm.py`（避免循环依赖 + 概念独立）
- 探针测试场景比应用层更广（1 vs 3 二选一 + 1 AGENT 完整流程验证）

## 开发模式（内部，不对用户暴露）

SKILL 上线后**只暴露** `auto` / `manual` 2 个用户使用模式。`probe` / `test` 是 SKILL 作者/助手的开发工具，**不进 SKILL.md body**。

| 模式 | 实现 | 启动阶段 | 目的 |
|---|---|---|---|
| `probe` | `scripts/main.py probe` + 复用 `scripts/probe_llm.py` | Phase 1.4-1.7（切分决策）+ Phase 3（回归）| 1 vs 3 AGENT 切分对比 + 切分迭代 + 实现回归 |
| `test` | `scripts/main.py test` | Phase 4.1 端到端探针 | 部署前完整链路验证 |

样本量分层（确认拍板）：Phase 1.5-1.7 基础测试 5-10 样本 / Phase 3 回归 10-20 样本 / Phase 4.1 端到端 1→3→10→30 单。

## v2 规范引用（SKILL 撰写规范，不进 SKILL.md body）

| 规范 | 用途 | 章节 |
|---|---|---|
| 流程图节点 ≤ 10 字 | mermaid 流程图节点文字硬限，防止解析报错 | v2.0 §10.6 |
| L4 替换走严格模式 | 防软替换陷阱（SKILL 替换时严格匹配，不模糊）| v2.0 §10.8 |
| 妙搭三件套不进 LLM 降级链 | Auto/Flash/Multimodal 不用作业务降级；prompt 硬限 ≤ 30k 字符 | v2.0 §7.5 |
| preflight §7.6 模板 | 4-5 项 env 准备检查（env / bitable / LLM / 资源 / cron 冲突）| v2.0 §7.6 |
| SKILL.md ≤ 500 行 / 5000 token | body 操作手册，决策/拍板/changelog 全部移 README | v2.0 §10.4 |
| changelog → 仓库 CHANGELOG.md | 部署/决策历史 → README.md（本文）| v2.0 §10.4 |

## 决策历史（audit trail）

| ID | 类型 | 内容 | 拍板人 / 来源 |
|---|---|---|---|
| **D-20260806-001** | 决策 | 9 类失败 → 3 大类（retry / 不重试 / 业务问题）| 确认 |
| **D-20260806-006** | 决策 | 5 状态机（待处理 / 已处理-处理中 / 已处理-成功 / 已处理-失败 / 已处理-需人工）| 解析层复用 |
| **D-20260806-011** | 决策 | 飞书通知双通道（私聊确认 + memory/YYYY-MM-DD.md）+ 24h 去重 | 确认 |
| **D-20260807-004** | 决策 | 1 vs 3 二选一：探针达标切 1 AGENT，不达标保持 3 | 确认 |
| **LRN-20260802-013** | 教训 | kimi-k2.6 已移出降级链（17-22s 慢得不合理，比 qwen 慢 80%）| 探针验证 |
| **LRN-20260803-026** | 教训 | OpenClaw exec 拒绝 GITHUB_TOKEN env var → 走 here-doc + 临时脚本 | 实战经验 |
| **LRN-20260803-027** | 教训 | here-doc 单引号 `'EOF'` 不展开 `$VAR` → 用裸 EOF 或脚本外传参 | 实战经验 |
| **LRN-20260806-002** | 教训 | 飞书画板 = Mermaid 输入，不走 openapi 后处理 | 实战经验 |
| **LRN-20260806-003** | 教训 | 飞书画板箭头 1px narrow 缩放后不可见 | 实战经验 |
| **LRN-20260806-006** | 教训 | 流程图上传前先 ASCII 走读连接顺序 | 实战经验 |
| **LRN-20260807-001** | 教训 | 探针先行原则（AGENT 切分/prompt/降级链拍板前必须跑探针）| 实战经验 |
| **LCE-20260808-006** | 教训 | 维度表 6 → 3 合并 | 实施期发现 |

## 阻塞项（确认 review 时一次性提供）

| # | 阻塞项 | 阻塞哪个 Task |
|---|---|---|
| 1 | 商品维度统计表 metadata（app_token / table_id / 字段映射）| Phase 1.1 维度数据 JOIN |
| 2 | 门店表 metadata（同上）| Phase 1.1 维度数据 JOIN |
| 3 | 真实样本数据 10-20 条 | Phase 1.2 探针基础测试 |
| 4 | 评估标准定稿（准确率 / 一致性 / latency 阈值）| Phase 1.2 探针基础测试 |
| 5 | AGENT 1-3 切分定稿（Phase 1.5 探针后）| Phase 1.8 v1.6 doc 升版 |

## 文档

| 资源 | 位置 |
|---|---|
| 飞书设计方案 doc | v1.5 doc（workspace 外）；Phase 1.5 探针收口后升 v1.6（拍板项 11）|
| PROPOSAL v9（applied）| `skill-workshop/proposals/aftersales-judge-decide-20260809-2b41940fbe/PROPOSAL.md`（workspace 外）|
| 解析层 SKILL | `aftersales-rules-parse`（只读判责规则表）|
| 架构附录 | [`references/architecture.md`](references/architecture.md) — 流程图 / 抢锁矩阵 / 决策表 / §3.5 1 vs 3 决策规则 |
| 6 Phase 节奏 | [`references/implementation_plan.md`](references/implementation_plan.md) — Phase 1 T1.5-T1.7 探针决策门 |
| 业务背景 | [`references/business_context.md`](references/business_context.md) — 补偿方案 → SKILL 映射 + 业务规则清单 |
| 开发环境 | [`references/dev_env_setup.md`](references/dev_env_setup.md) — 本地 CLI-only 安装指南 |
| 探针工具 | `scripts/probe_llm.py`（Phase 0 stub，Phase 1.4 实质）|
| 源文档归档 | trash/：升级售后主流程SKILL开发规划.md / v1.5 设计方案 PDF / 补偿方案 PDF（gitignore，git 历史可恢复）|

## 仓库

- GitHub: https://github.com/RayZen2026/aftersales-judge-decide
- License: Proprietary (internal use only)
- Author: ZenRay <jake2011ren@gmail.com>
