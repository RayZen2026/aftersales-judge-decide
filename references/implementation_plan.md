# 升级售后判责主流程 - 6 Phase 开发节奏

> 本文件是 SKILL 的实施路线附录,与 SKILL.md 分离,Phase 0 起草,Phase 1 review 收口阻塞项后定稿。

> **⚠️ 开发前必读 [CLAUDE.md](../CLAUDE.md)** —— 项目宪法（依赖 SKILL / 实物路径 / AST 消费方定位 / 持久原则）。改动需确认明确拍板。

## 0. 总览

| Phase | 名称 | 工期 | 关键交付物 | 阻塞项 |
|---|---|---|---|---|
| Phase 0 | PROPOSAL + 框架初始化 | 2-3 天 | PROPOSAL.md pending + SKILL 目录 | 无 |
| Phase 1 | PROPOSAL 收口 + 探针基础测试 | 5-7 天 | 阻塞项 4 类收口 + probe_llm.py 跑通 | 4 类阻塞数据(确认 review) |
| Phase 1.5 | 探针迭代 + AGENT 切分拍板 | 3-5 天 | 3 轮调优 + AGENT 1-3 切分定稿 | Phase 1 数据集 |
| Phase 1.8 | v1.6 doc 升版(4 项硬约束) | 1-2 天 | 飞书 doc 升 v1.6,frontmatter/preflight/L4/§11.1 | AGENT 切分拍板 |
| Phase 2 | 核心模块 + 数据访问 | 7-10 天 | state_machine.py / failure_handler.py / llm.py / feishu_bitable.py | 无 |
| Phase 3 | 主流程 + 单 AGENT 探针回归 | 5-7 天 | agent1/2/3.py + main.py + 单测 + 10-20 样本回归 | Phase 1.5 切分定稿 |
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

### 任务清单
- [ ] 确认 review PROPOSAL → 提供 4 类阻塞数据（进行中：metadata 已收口，样本 live 就绪，人工标注未就绪）
- [x] 维度表 metadata 收口(商品维度统计表 + 门店表 app_token / table_id / 字段映射) —— 2026-08-12 实查收口：6 表全部可读，config.yaml 验证；门店分层规则 table_id 笔误修复（tbllJ5aMajBhYRjIs → tbllJ5aMjBhYRjIs）
- [x] **T1.4a 数据层探针版（补遗，原计划遗漏）**：`scripts/data_loader.py` —— live lark-cli + CSV 双来源 → 统一 SampleSet schema；维度 JOIN（商品按商品id+订单日期 日期级匹配 / 门店快照按店铺id）+ apply_tier 集成（submodules/store-tier-rules import）；Phase 2 feishu_bitable.py 复用同一数据契约，只换 fetch 实现
- [ ] 真实样本数据 10-20 条准备（Round 1：live 拉取已通；Round 2：人工标注 CSV → expected 填充）
- [ ] 评估标准定稿(准确率 / 一致性 / latency 阈值)（Round 1 只跑格式/一致性/latency；准确率口径 Round 2，2026-08-12 确认拍板）
- [x] probe_llm.py 框架(Phase 1 实质实现: DashScope qwen-plus-latest 占位全链 + jinja2 渲染 + JSON 提取/schema 校验 + 报告对齐 eval_standard §8) + config.yaml 补 `probe` 块(output_dir / test_scenarios / evaluation_rubric / llm / task_fetch / task_field_mapping / store_tier)
- [ ] **T1.5 1 AGENT 完整流程探针**(5-10 样本)——**1 vs 3 决策基线**(设计方案 §0.1:探针通过 → 改 1 AGENT)；Round 1 = 端到端跑通(格式/一致性/latency)
- [ ] **T1.6 3 AGENT 单 AGENT 探针**(5-10 样本/AGENT,3 AGENT 是当前基线)；Round 1 = 端到端跑通
- [ ] **T1.7 1 vs 3 决策门**:1 AGENT 全部达标 → 切 1 AGENT;任一不达标 → 保持 3 AGENT(判定标准 `assets/eval/eval_standard.md`,决策规则 `references/architecture.md` §3.5)——推迟 Round 2(需人工标注准确率)

### 探针参数
- 样本量: 5-10(快速验证,vs Phase 3 回归用 10-20)
- 模型: DashScope qwen-plus-latest 单模型占位全链(2026-08-12 确认拍板;本地无妙搭,4+2 降级链生产才测)
- prompt: 业务 prompt 模板占位版(`assets/agent{1,2,3}_prompt_template.j2` + `agent_single_prompt_template.j2` 融合模板)

### 阻塞项
- 4 类阻塞数据(确认 review 时一次性提供)

## 3. Phase 1.5: 探针迭代 + AGENT 切分拍板(3-5 天)

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

## 4. Phase 1.8: v1.6 doc 升版(1-2 天)

### 4 项硬约束(决策 4 触发)
- [ ] **frontmatter requires.bins**: `["lark-cli", "python3"]`(v2.0 §10.14 L3 契约)
- [ ] **frontmatter requires.config**: `["config.yaml"]`(v2.0 §10.14 L3 契约)
- [ ] **preflight 4-5 项**: feishu 凭据 / bitable 可达 / LLM 链 / 资源 / cron 冲突(v2.0 §7.6)
- [ ] **L4 严格替换策略**: 防软替换陷阱(v2.0 §10.8)
- [ ] **§11.1 SKILL.md 加 "Skill Workshop" 段**: v2.0 §4 流程描述

### 触发条件
- AGENT 切分拍板(决策 4)

## 5. Phase 2: 核心模块 + 数据访问(7-10 天)

### 任务清单
- [ ] `state_machine.py`(5 状态机 + 9 类失败映射)
- [ ] `failure_handler.py`(9 类失败分类 + 3 大类处理)
- [ ] `llm.py`(4+2 降级链 + 限流退避 + 共享链/独立链)
- [ ] `feishu_bitable.py`(4 张表 CRUD + 锁机制)
- [ ] `feishu_notify.py`(飞书私聊 + memory_file 双通道 + 24h 去重)
- [ ] `lock.py`(per-item 抢锁 + stale 5min 兜底)
- [ ] 每个模块单测(pytest,覆盖率 ≥ 80%)

## 6. Phase 3: 主流程 + 单 AGENT 探针回归(5-7 天)

### 任务清单
- [ ] `agent1.py`(门店期望判定)+ 单 AGENT 探针回归(5-10 样本)
- [ ] `agent2.py`(承担方比例判责)+ 单 AGENT 探针回归
- [ ] `agent3.py`(综合判责意见)+ 单 AGENT 探针回归
- [ ] `main.py` Workflow 编排(阶段 1/2/3)
- [ ] `分配校正` 纯数学模块
- [ ] 集成测试(全 AGENT 串行 + 状态机推进 + 写表)
- [ ] 10-20 样本正式回归(评估标准验收)

## 7. Phase 4: 端到端 + 生产部署(5-7 天)

### 任务清单
- [ ] 端到端探针(1 → 3 → 10 → 30 完整单,使用 test_main_table 独立表)
- [ ] 准确率 / 一致性 / latency 评估
- [ ] 失败场景演练(9 类失败全跑)
- [ ] OpenClaw cron 配置(hourly 10-23 Asia/Shanghai)
- [ ] 监控 + 告警(飞书私聊 + memory_file)
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
| 5 | AGENT 切分定稿(1 vs 3 决策 + 边界调优,Phase 1.5 探针后)| Phase 1.8 v1.6 doc 升版 | ⏳ Phase 1.5 探针后 |
