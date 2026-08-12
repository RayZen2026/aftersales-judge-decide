# 升级售后判责主流程 - 6 Phase 开发节奏

> 本文件是 SKILL 的实施路线附录,与 SKILL.md 分离,Phase 0 起草,Phase 1 review 收口阻塞项后定稿。

> **⚠️ 开发前必读 [CLAUDE.md](../CLAUDE.md)** —— 项目宪法（依赖 SKILL / 实物路径 / AST 消费方定位 / 持久原则）。改动需确认明确拍板。

## 0. 总览

| Phase | 名称 | 工期 | 关键交付物 | 阻塞项 |
|---|---|---|---|---|
| Phase 0 | PROPOSAL + 框架初始化 | 2-3 天 | PROPOSAL.md pending + SKILL 目录 | 无 |
| Phase 1 | PROPOSAL 收口 + 探针基础测试 | 5-7 天 | 阻塞项 4 类收口 + probe_llm.py 跑通 | ✅ 2026-08-12 阶段型收口 |
| Phase 1.5 | 探针迭代 + AGENT 切分拍板 | 3-5 天 | 3 轮调优 + AGENT 1-3 切分定稿 | ✅ 2026-08-12 收口:切 1 AGENT |
| Phase 1.8 | 部署准备(v1.6 内容 + 一次性 apply) | 1-2 天 | SKILL.md 重建草稿 + 4 项硬约束 | ✅ 触发满足;Phase 3 后执行(D-20260812-010) |
| Phase 2 | 核心模块 + 数据访问 | 7-10 天 | state_machine.py / failure_handler.py / llm.py / feishu_bitable.py | ✅ 2026-08-12 完成(6 模块 + 170 用例) |
| Phase 3 | 主流程 + 单 AGENT 探针回归 | 5-7 天 | agent_single.py + main.py + 单测 + 10-20 样本回归 | ✅ 切分已锁(1 AGENT) |
| Phase 4 | 端到端 + 生产部署 | 5-7 天 | test_main_table 端到端 + cron 配置 + 监控告警 + 全量切流 | Phase 3 探针通过 |
| Phase 5 | 观察期 + 优化 | 1 周(7 天 × 14 次/天 = 98 次 cron)| 调优 prompt/参数/状态机实现细节 | Phase 4 部署完成 |

**总工期**: 28-41 天(实施) + 7 天(观察期) = 35-48 天

## 1. Phase 0: PROPOSAL + 框架初始化(2-3 天)

### 任务清单
- [x] 写 PROPOSAL.md(本文件 PROPOSAL.md,AGENT 1-3 用占位猜测)
- [x] 写 references/architecture.md(架构附录)
- [x] 写 references/implementation_plan.md(本文件,6 Phase 路线)
- [x] 调 `openclaw skills workshop propose-create --proposal-dir ./aftersales-judge-decide-proposal/`
- [x] GitHub 仓库初始化(clone https://github.com/RayZen2026/aftersales-judge-decide.git)
- [x] git config user.name ZenRay + user.email jake2011ren@gmail.com(local)

### 阻塞项(Phase 0 不阻塞)
- 4 类 PROPOSAL 阻塞数据 = review 阶段由确认提供,不阻塞 Phase 0

### 不做的事
- ❌ 直接写 SKILL.md(v2.0 §4 铁律,必须等 skill_workshop apply)
- ❌ 实现代码(Phase 2 才写)
- ❌ push 到 GitHub(等确认明确指示)

## 2. Phase 1: PROPOSAL 收口 + 探针基础测试(5-7 天)

> **收口状态(2026-08-12,✅ 阶段型收口)**:T1.4a 数据层 / T1.4 探针框架 / T1.5 / T1.6 完成,T1.7 由切分拍板解决(D-20260812-007 切 1 AGENT)。残留 3 项转 Phase 3 回归:标注扩充(GT 现 4 条 → 10-20 条)、准确率口径定稿(自由文本/比例对比方法)、PROPOSAL review 形式项。

### 任务清单
- [x] 确认 review PROPOSAL → 提供 4 类阻塞数据（metadata 收口 ✅ / 样本 live + GT 4 条 ✅ / 评估标准部分 ✅——准确率口径残留转 Phase 3）
- [x] 维度表 metadata 收口(商品维度统计表 + 门店表 app_token / table_id / 字段映射) —— 2026-08-12 实查收口：6 表全部可读，config.yaml 验证；门店分层规则 table_id 笔误修复（tbllJ5aMajBhYRjIs → tbllJ5aMjBhYRjIs）
- [x] **T1.4a 数据层探针版（补遗，原计划遗漏）**：`scripts/data_loader.py` —— live lark-cli + CSV 双来源 → 统一 SampleSet schema；维度 JOIN（商品按商品id+订单日期 日期级匹配 / 门店快照按店铺id）+ apply_tier 集成（submodules/store-tier-rules import）；**拉取范围 = 视图「近两天数据」**（D-20260812-006；filter-json 覆盖视图过滤 → 状态过滤客户端，范围 = 未处理 + 已处理-失败）；Phase 2 feishu_bitable.py 复用同一数据契约，只换 fetch 实现
- [ ] 真实样本数据 10-20 条准备（live 拉取已通；GT 标注 4 条已入库 `assets/eval/ground_truth_v1.csv`；**扩充至 10-20 条转 Phase 3 回归**）
- [ ] 评估标准定稿(准确率 / 一致性 / latency 阈值)（Round 1 只跑格式/一致性/latency；准确率口径 Round 2，2026-08-12 确认拍板）
- [x] probe_llm.py 框架(Phase 1 实质实现: DashScope qwen-plus-latest 占位全链 + jinja2 渲染 + JSON 提取/schema 校验 + 报告对齐 eval_standard §8) + config.yaml 补 `probe` 块(output_dir / test_scenarios / evaluation_rubric / llm / task_fetch / task_field_mapping / store_tier)
- [x] **T1.5 1 AGENT 完整流程探针**(5-10 样本)——**1 vs 3 决策基线**(设计方案 §0.1:探针通过 → 改 1 AGENT)；**Round 1 跑通完成**（2026-08-12：5 样本 × 3 runs，格式 1.0 / latency P95 13.3s / 一致性 core 0.34）；准确率判定待 Round 2
- [x] **T1.6 3 AGENT 单 AGENT 探针**(5-10 样本/AGENT,3 AGENT 是当前基线)；**Round 1 跑通完成**（2026-08-12：5 样本 × 3 runs × 3 AGENT，格式 1.0 / latency P95 8.9s / 需人工信号 7/45）；准确率判定待 Round 2
- [x] **T1.7 1 vs 3 决策门**:1 AGENT 全部达标 → 切 1 AGENT;任一不达标 → 保持 3 AGENT(判定标准 `assets/eval/eval_standard.md`,决策规则 `references/architecture.md` §3.5)——**已解决(D-20260812-007 确认拍板 = 切 1 AGENT**;eval_standard 一致性/准确率未全达,确认知悉风险,转 Phase 3 回归 + Phase 5 观察期)

### 探针参数
- 样本量: 5-10(快速验证,vs Phase 3 回归用 10-20)
- 模型: DashScope qwen-plus-latest 单模型占位全链(2026-08-12 确认拍板;本地无妙搭,4+2 降级链生产才测)
- prompt: 业务 prompt 模板占位版(`assets/agent{1,2,3}_prompt_template.j2` + `agent_single_prompt_template.j2` 融合模板)

### 阻塞项
- 4 类阻塞数据(确认 review 时一次性提供)

## 3. Phase 1.5: 探针迭代 + AGENT 切分拍板(3-5 天)

### 收口状态(2026-08-12,✅ 已收口)

- **决策 = 切 1 AGENT**(D-20260812-007,确认拍板):Round 1 探针 1-AGENT 端到端跑通(格式校验 100%),快速落地优先;3 AGENT 方案暂停
- **完成 1 轮调优**(输出 schema v2 + C 类诉求代价判决标准 + judgment_basis 判责依据层):一致性 core **0.34 → 0.125**,格式校验 1.0,单调用 P95 23.9s(schema v2 输出变大)
- **GT 对比**(`assets/eval/ground_truth_v1.csv` 4 单 × 3 runs):action/提价结果类型 12/12 ✅;amount 精确 3/4(794255 探针 200 vs GT 150,门店诉求 200 被 GT 审核砍价);满足期望类型 11/12;**承担比例全 50:50 vs GT 1:9/1:9/3:7/5:5 ❌——LLM 把平台上限 50% 当默认值,系统性偏差,Phase 3 prompt 调优首要项**
- **遗留风险转 Phase 3 回归 + Phase 5 观察期**:一致性 core 12.5% 仍超 5% 阈值;准确率未正式评估(GT 仅 4 单);比例偏差;latency 23.9s 贴近 30s 端到端预算

### 3 轮调优上限
- 1 轮 = 跑 1 次单 AGENT 探针(5-10 样本 × 3 AGENT)+ 评估切分质量 + 调 1 次切分
- **3 轮上限**:最多 3 轮(确认拍板)
- **3 轮不收敛** → 强制定版当前最佳切分 + 风险标到生产观察期处理

### 探针失败边界

| 阶段 | 探针失败 → 改什么 | 探针失败 → 不改什么 |
|---|---|---|
| Phase 1.5 | AGENT 切分(合并/拆分/重定边界)、占位 prompt 措辞、模型选择、参数 | v1.5 doc 已拍板项 |
| Phase 3 | 代码实现(prompt 拼接、上下文组装、JSON 解析) | AGENT 切分(已锁) |
| Phase 4 | 集成顺序、超时配置 | AGENT 切分(已锁) |

### AGENT 角色(v1.5 doc §5 已拍板基线,非占位猜测)
- AGENT 1: 门店期望判定(门店期望的判责结果 + 金额,共享链)
- AGENT 2: 承担方比例判责(判责规则 AST 仅 prompt 引用,按优先级遍历;分配校正纯数学兜底,共享链)
- AGENT 3: 综合判责意见(推理链,独立链 doubao-seed-2.0-pro → minimax-m3)
- 探针调优范围:prompt 措辞 / 切分边界(3 轮上限);**1 vs 3 决策** 见 `references/architecture.md` §3.5
- 业务规则覆盖要求(责任方 / 诉求类型 A/B/C / 平台 50% 上限等)见 `references/business_context.md` §4

## 4. Phase 1.8: 部署准备（v1.6 内容 + 一次性 apply）(1-2 天)

> **定位调整（2026-08-12，D-20260812-010 确认拍板）**：开发期不走 skill_workshop 治理流程——git 已覆盖审计/review/回滚，本仓是 staging（SKILL.md 有意删除，无活跃 SKILL 文件，不触 v2 §4.1 适用域）。本阶段 = 部署准备，**执行时机推迟到 Phase 3 后**（实现内容稳定再定稿，避免返工）；部署时一次性 propose-update apply（目标 workspace 若执行 v2 §4.1）。

### 4 项硬约束 + 内容清单
- [ ] **SKILL.md 重建草稿**（按 1 AGENT 定稿架构：操作手册 body ≤500 行；probe/test 开发模式不进 body，只暴露 auto/manual）
- [ ] **frontmatter requires.bins**: `["lark-cli", "python3"]`(v2.0 §10.14 L3 契约)
- [ ] **frontmatter requires.config**: `["config.yaml"]`(v2.0 §10.14 L3 契约)
- [ ] **preflight 5 项**: feishu 凭据 / bitable 可达 / LLM 链 / cron 冲突 / 磁盘空间(v2.0 §7.6)
- [ ] **L4 严格替换策略**: `${VAR}` 缺失即启动失败,防软替换陷阱(v2.0 §10.8)
- [ ] **§11.1 SKILL.md 加 "Skill Workshop" 段**: v2.0 §4 流程描述
- [ ] 飞书 doc v1.5 → v1.6（部署前同步）

### 触发条件
- ~~AGENT 切分拍板(决策 4)~~ ✅ 已满足（2026-08-12，D-20260812-007）；**执行时机 = Phase 3 内容稳定后**

## 5. Phase 2: 核心模块 + 数据访问(7-10 天)

> **状态（2026-08-12，✅ 完成）**：6 模块全部落地，170 用例全绿，覆盖率 ≥90%（计划要求 ≥80%）。
> 两个安全门：写飞书表需 env `BITABLE_WRITE_ENABLED=1`；飞书私聊需 `FEISHU_NOTIFY_ENABLED=1`（防开发误写生产/打扰确认人）。

### 任务清单
- [x] `state_machine.py`(5 状态机 + 合法转移表 + 表值双向映射（含 未处理/待处理 别名）+ 拉取矩阵语义) 96%
- [x] `failure_handler.py`(9 类失败分类 + 3 大类处理决策（重试/需人工/终态 + 通知/写表策略）+ config 契约校验) 98%
- [x] `llm.py`(4+2 降级链编排 + 模型内重试/backoff/honor_retry_after + DashScope 开发后端 + Miaoda 生产后端 Phase 4 占位 + 错误分类映射 9 类失败) 94%
- [x] `feishu_bitable.py`(任务表 update 幂等 + 判责结果表 upsert 1 单 1 行 + 锁封装 + 读侧复用 data_loader 契约 + 写保护门) 100%
- [x] `feishu_notify.py`(飞书私聊 + memory_file 双通道 + 24h 同单号同异常类型去重持久化 + 飞书失败降级 memory + 发送门) 90%
- [x] `lock.py`(per-item 抢锁判定 + stale 5min 兜底；实物适配：任务表无"任务处理时间"字段，用系统字段 更新时间(fldCQOdVZI) 作 stale 基准) 93%
- [x] 每个模块单测(pytest,覆盖率 ≥ 80%——实际 90-100%)

## 6. Phase 3: 主流程 + 单 AGENT 探针回归(5-7 天)

> AGENT 切分已锁 = 1 AGENT(D-20260812-007);实现按 agent_single 融合模板,agent{1,2,3} 模板保留为参考。

### 任务清单
- [ ] `agent_single.py`(1-AGENT 完整流程判责,schema v2 输出)+ 探针回归(5-10 样本)
- [ ] **承担比例偏差修复**(GT 对比发现:全 50:50 默认化;需 prompt 明确比例反映证据强度、上限≠默认值)
- [ ] `main.py` Workflow 编排(阶段 1/2/3)
- [ ] `分配校正` 纯数学模块(Phase 1 已提前实现 allocate_correction,platform/merchant 术语)
- [ ] 集成测试(状态机推进 + 写表)
- [ ] 10-20 样本正式回归(评估标准验收,含 GT 扩充集准确率)

## 7. Phase 4: 端到端 + 生产部署(5-7 天)

### 任务清单
- [ ] 端到端探针(1 → 3 → 10 → 30 完整单,使用 test_main_table 独立表)
- [ ] 准确率 / 一致性 / latency 评估
- [ ] 失败场景演练(9 类失败全跑)
- [ ] OpenClaw cron 配置(hourly 10-23 Asia/Shanghai)
- [ ] 监控 + 告警(飞书私聊 + memory_file)
- [ ] memory_file 通知通道路径对齐 OpenClaw workspace memory 目录（开发期为 SKILL 目录 memory/ 下的文件近似，config `notify.channels[memory_file].path` 可调；去重状态独立在 state/，不入 memory 通道）
- [ ] 第一次跑(小流量验证)+ 全量切流

## 8. Phase 5: 观察期 + 优化(1 周)

### 时间
- 1 周 = 7 天 × 14 次/天 = 98 次 cron 触发

### 调优边界(确认拍板)
- ✅ 可改: prompt 措辞、参数、状态机实现细节
- ❌ 不可改: AGENT 切分(已锁)、降级链(已锁)、9 类失败分类(已锁)、5 状态机结构(已锁)

### 任务清单
- [ ] 第 1 周观察(每天 1 次 cron 触发 → 后扩到每小时 1 次)
- [ ] 收集真实数据:准确率 / 一致性 / latency / 失败率
- [ ] 调优 prompt / 参数(在调优边界内)
- [ ] 第 1 周末 review + 决定是否扩量

## 9. 关键风险点

| 风险 | 阶段 | 缓解 |
|---|---|---|
| AGENT 切分探针 3 轮不收敛 | Phase 1.5 | 强制定版当前最佳切分 + 风险标到生产观察期 |
| 真实样本 10-20 条不够代表性 | Phase 1 | 覆盖典型 case(退货 / 赔付金额 / 退货或赔付) |
| LLM 降级链全失败 | Phase 4 | 兜底 = 任务表状态=已处理-失败 + cron 兜底重试 |
| miaoda 启动失败 | Phase 4 | D-20260806-007 暂不实施,SKILL 不写启动 ping 检查 |
| cron 任务重叠 | Phase 4 | stale 5min 兜底 + 单 JOB 单 Task |
| 飞书通知轰炸 | Phase 4 | 24h 同单号同异常类型去重 |

## 10. 阻塞项完整清单(确认 review 时一次性提供)

> 2026-08-12 状态更新：#1/#2 已实查收口，#3/#4 部分就绪（Round 1 跑通不依赖，Round 2 需要）。

| # | 阻塞项 | 阻塞哪个 Task | 状态 |
|---|---|---|---|
| 1 | 商品维度统计表 metadata | Phase 1.1 维度数据 JOIN | ✅ 2026-08-12 实查收口 |
| 2 | 门店表 metadata | Phase 1.1 维度数据 JOIN | ✅ 2026-08-12 实查收口 |
| 3 | 真实样本 10-20 条 | Phase 1.2 探针基础测试 | 🟡 部分就绪(live 拉取已通;人工标注 CSV Round 2) |
| 4 | 评估标准定稿 | Phase 1.2 探针基础测试 | 🟡 部分就绪(Round 1 只跑格式/一致性/latency;准确率口径 Round 2) |
| 5 | AGENT 切分定稿(1 vs 3 决策 + 边界调优,Phase 1.5 探针后)| Phase 1.8 v1.6 doc 升版 | ✅ 2026-08-12 拍板 = 切 1 AGENT(D-20260812-007) |
