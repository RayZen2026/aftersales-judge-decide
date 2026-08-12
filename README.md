# aftersales-judge-decide

> 升级售后判责主流程 SKILL — 从飞书多维表格拉取待判责任务，串行调度 AGENT 调用 LLM 完成判责（当前基线 3 AGENT，探针决定是否切 1 AGENT），维护 5 状态机，处理 9 类失败，写飞书任务表 + 判责结果表，通过飞书私聊双通道通知运营（24h 去重）。

## 状态

**Phase 1 进行中 — Round 1 探针端到端跑通**（SKILL.md 探针拍板后再建）

- **Round 1 / Round 2 拍板**（2026-08-12 确认）：输出 schema 未定稿，Round 1 目标 = 探针**端到端跑通**（格式校验/一致性/latency）；准确率评估 + T1.7 1 vs 3 决策门推迟 Round 2（人工标注就绪后）。探针 LLM = DashScope `qwen-plus-latest` 单模型占位全链（本地无妙搭）。CSV 通道只覆盖任务表样本 + 人工标注表，维度数据走 lark-cli live JOIN。
- **数据层补遗**（2026-08-12）：原 Phase 1 计划遗漏数据拉取模块，补 `scripts/data_loader.py`（T1.4a）——live/CSV 双来源 → 统一 SampleSet schema；Phase 2 feishu_bitable.py 复用契约只换 fetch 实现。
- **维度 metadata 收口**（2026-08-12 实查）：6 表全部可读；门店分层规则 table_id 笔误修复（`tbllJ5aMajBhYRjIs` → `tbllJ5aMjBhYRjIs`）。

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

## store-tier-rules 依赖（开发/部署路径分离，⚠️ 部署时必改）

门店分层 AST 求值 import `store-tier-rules` SKILL 的 `apply_tier`（CLAUDE.md 原则 2，不写自己的 `store_tier.py`）。**开发环境与部署环境路径不同**：

| 环境 | 路径 | 注入方式 |
|---|---|---|
| 开发（本机） | `submodules/store-tier-rules/scripts/`（普通目录拷贝 v1.3.0，非 git submodule，已 gitignore） | `config.yaml probe.store_tier.scripts_dir_default` |
| 部署（OpenClaw workspace） | workspace 内 skills 目录（如 `/home/gem/workspace/agent/skills/store-tier-rules/scripts`） | env `STORE_TIER_RULES_DIR` 覆盖（优先级高于 config） |

**注意**：
- 两边 SKILL 版本需**人工对齐**（当前开发拷贝 = v1.3.0），升级 store-tier-rules 后部署侧同步更新。
- **只 import `apply_tier` 纯函数**，禁调其 `load_latest_rules`（走 lark-cli `--as user` + 沙箱 config，本地/生产 bot 通路不适用）；门店分层规则 JSON 由本项目 `data_loader.py` 自己拉取后作参数传入。
- 分层失败降级：`store_tier=null` + `join_meta.tier_degrade_reason` 记录，不中断主流程（`probe.store_tier.degrade_on_failure`）。

## Phase 1 Round 1 探针结果（2026-08-12）

**DoD 8 项全部通过**（跑通 = 格式/链路/报告，准确率阈值判定在 Round 2）：

| 项 | 1agent（T1.5） | 3agent（T1.6） |
|---|---|---|
| LLM 调用 | 15（5 样本 × 3 runs） | 45（5 样本 × 3 runs × 3 AGENT） |
| 格式校验率 | **1.0** | **1.0** |
| latency P95 | 13.3s（融合模板单调用） | 8.9s（agent1 7.8 / agent2 9.2 / agent3 9.0） |
| 一致性 strict/core | 0.58 / 0.34 | 0.72 / 0.61 |
| 需人工信号 | 0（1agent 自行判比例） | 7/45（规则无匹配 → 0/0） |

样本构建：5 样本 live 拉取，商品/门店 JOIN 命中率均 5/5，门店分层 C:3/B:2，零降级。pytest 59 用例全绿。

**Round 2 调优输入**（探针发现）：
1. **action 翻转**：诉求="退货或者赔付金额"时，run 间 action 在 退货/赔付 间翻转——占位 prompt 无 C 类诉求代价判决标准（退货物流费 10 元/次、流失代价等，见 business_context §4.2）。
2. **1 vs 3 行为语义差异**：3agent 的 agent2 严格执行"规则无匹配 → 0/0 需人工"模板契约（7/45），1agent 则自行推理出比例——Round 2 决策时需拍板"规则无匹配"的统一口径。
3. **agent2 输入缺 task 字段**：LLM 明示"商品名称未在输入中给出"（agent2 模板只收 item_id + agent1 输出 + 维度数据 + 规则）——Round 2 prompt 调优候选。
4. **生效判责规则仅 1 条**（数据现状：是否生效=是 只 1 行）——大量样本走"规则无匹配"路径，规则覆盖是 Round 2 准确率的前置。
5. **一致性超阈值**：core 口径 0.34-0.61 > 评估标准 15% 上限——Round 2 调优方向：temperature 0.1→0.0 / few-shot / 代价判决标准显式化。

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
| **D-20260812-001** | 决策 | Phase 1 Round 1 = 探针端到端跑通（格式/一致性/latency）；准确率 + T1.7 决策门推迟 Round 2（人工标注就绪后） | 确认 |
| **D-20260812-002** | 决策 | 探针 LLM = DashScope qwen-plus-latest 单模型占位全链（本地无妙搭；4+2 降级链生产才测） | 确认 |
| **D-20260812-003** | 决策 | 数据层补遗（T1.4a data_loader.py）：live/CSV 双来源 → 统一 SampleSet；Phase 2 复用契约只换 fetch | 确认 |
| **D-20260812-004** | 决策 | CSV 范围 = 任务表样本 + 人工标注表；维度数据走 live JOIN | 确认 |
| **D-20260812-005** | 决策 | store-tier-rules 开发路径 submodules/（gitignore），部署经 STORE_TIER_RULES_DIR 注入；只 import apply_tier | 确认 |
| **LCE-20260812-001** | 教训 | formula 字段返回字符串数字（30日售后赔付率='0.073...'）→ apply_tier 前必须数值 coerce | 实查 |
| **LCE-20260812-002** | 教训 | lark-cli envelope 双形态（外层 {ok,data} vs 裸 envelope）→ 解析必须防御解包 | 实查 |
| **LCE-20260812-003** | 教训 | 任务表/维度表 datetime 格式不一致（T00:00+08 vs T08:00+08）→ JOIN 按日期级匹配 | 实查 |

## 阻塞项（确认 review 时一次性提供）

> 2026-08-12 更新：#1/#2 已实查收口，#3/#4 部分就绪。

| # | 阻塞项 | 阻塞哪个 Task | 状态 |
|---|---|---|---|
| 1 | 商品维度统计表 metadata（app_token / table_id / 字段映射）| Phase 1.1 维度数据 JOIN | ✅ 实查收口 |
| 2 | 门店表 metadata（同上）| Phase 1.1 维度数据 JOIN | ✅ 实查收口 |
| 3 | 真实样本数据 10-20 条 | Phase 1.2 探针基础测试 | 🟡 live 拉取已通；人工标注 CSV Round 2 |
| 4 | 评估标准定稿（准确率 / 一致性 / latency 阈值）| Phase 1.2 探针基础测试 | 🟡 Round 1 只跑格式/一致性/latency；准确率 Round 2 |
| 5 | AGENT 1-3 切分定稿（Phase 1.5 探针后）| Phase 1.8 v1.6 doc 升版 | ⏳ 待探针 |
| 6 | 代理人维护补偿上限 15% vs 20%（business_context §6.1 两处不一致）| AGENT 2 业务 prompt | ⏳ 待拍板 |
| 7 | 任务表 处理状态 字段值（现仅"未处理"，5 状态选项待补）| Phase 2 写表 | ⏳ 待确认 |

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
