# 升级售后判责主流程 - 6 Phase 开发节奏

> 本文件是 SKILL 的实施路线附录,与 SKILL.md 分离,Phase 0 起草,Phase 1 review 收口阻塞项后定稿。

## 0. 总览

| Phase | 名称 | 工期 | 关键交付物 | 阻塞项 |
|---|---|---|---|---|
| Phase 0 | PROPOSAL + 框架初始化 | 2-3 天 | PROPOSAL.md pending + SKILL 目录 | 无 |
| Phase 1 | PROPOSAL 收口 + 探针基础测试 | 5-7 天 | 阻塞项 4 类收口 + probe_llm.py 跑通 | 4 类阻塞数据(任锐 review) |
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
- 4 类 PROPOSAL 阻塞数据 = review 阶段由任锐提供,不阻塞 Phase 0

### 不做的事
- ❌ 直接写 SKILL.md(v2.0 §4 铁律,必须等 skill_workshop apply)
- ❌ 实现代码(Phase 2 才写)
- ❌ push 到 GitHub(等任锐明确指示)

## 2. Phase 1: PROPOSAL 收口 + 探针基础测试(5-7 天)

### 任务清单
- [ ] 任锐 review PROPOSAL → 提供 4 类阻塞数据
- [ ] 维度表 metadata 收口(商品维度统计表 + 门店表 app_token / table_id / 字段映射)
- [ ] 真实样本数据 10-20 条准备
- [ ] 评估标准定稿(准确率 / 一致性 / latency 阈值)
- [ ] probe_llm.py 框架(复用解析层骨架,subprocess wrapper DRY)
- [ ] 探针基础测试(1 AGENT 完整流程 + 3 AGENT 单 AGENT)

### 探针参数
- 样本量: 5-10(快速验证,vs Phase 3 回归用 10-20)
- 模型: 4+2 链占位测
- prompt: 业务 prompt 模板占位版(`templates/agent{1,2,3}_prompt_template.j2`)

### 阻塞项
- 4 类阻塞数据(任锐 review 时一次性提供)

## 3. Phase 1.5: 探针迭代 + AGENT 切分拍板(3-5 天)

### 3 轮调优上限
- 1 轮 = 跑 1 次单 AGENT 探针(5-10 样本 × 3 AGENT)+ 评估切分质量 + 调 1 次切分
- **3 轮上限**:最多 3 轮,任锐 14:16 拍板
- **3 轮不收敛** → 强制定版当前最佳切分 + 风险标到生产观察期处理

### 探针失败边界

| 阶段 | 探针失败 → 改什么 | 探针失败 → 不改什么 |
|---|---|---|
| Phase 1.5 | AGENT 切分(合并/拆分/重定边界)、占位 prompt 措辞、模型选择、参数 | v1.5 doc 已拍板项 |
| Phase 3 | 代码实现(prompt 拼接、上下文组装、JSON 解析) | AGENT 切分(已锁) |
| Phase 4 | 集成顺序、超时配置 | AGENT 切分(已锁) |

### AGENT 切分占位猜测(待探针定稿)
- AGENT 1: 提取判责信息(从工单 + 维度数据)
- AGENT 2: 应用规则 + 决策(从解析层规则表)
- AGENT 3: 生成结构化结果(综合判责意见)

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

### 调优边界(任锐 14:14 拍板)
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

## 10. 阻塞项完整清单(任锐 review 时一次性提供)

| # | 阻塞项 | 阻塞哪个 Task | 状态 |
|---|---|---|---|
| 1 | 商品维度统计表 metadata | Phase 1.1 维度数据 JOIN | ⏳ 待任锐 |
| 2 | 门店表 metadata | Phase 1.1 维度数据 JOIN | ⏳ 待任锐 |
| 3 | 真实样本 10-20 条 | Phase 1.2 探针基础测试 | ⏳ 待任锐 |
| 4 | 评估标准定稿 | Phase 1.2 探针基础测试 | ⏳ 待任锐 |
| 5 | AGENT 1-3 切分定稿 | Phase 1.8 v1.6 doc 升版 | ⏳ Phase 1.5 探针后 |

## 11. 工期估算修正

| 阶段 | v1 估算 | v2 修正 | 差异原因 |
|---|---|---|---|
| Phase 0 | 1 天 | 2-3 天 | 加 PROPOSAL review 收口 + 阻塞项确认 |
| Phase 1 | 3 天 | 5-7 天 | 加 4 类阻塞数据提供时间 + probe_llm 框架 |
| Phase 1.5 | — | 3-5 天 | **新增**(v1 没考虑探针迭代上限) |
| Phase 1.8 | — | 1-2 天 | **新增**(v1 没考虑 v1.6 doc 升版) |
| Phase 2 | 5 天 | 7-10 天 | 加 5 个模块单测 + 集成测试 |
| Phase 3 | 5 天 | 5-7 天 | 加 10-20 样本正式回归 |
| Phase 4 | 3 天 | 5-7 天 | 加端到端探针 + 失败场景演练 + 监控告警 |
| Phase 5 | 2 周 | 1 周 | 任锐 14:14 拍板 |
| **总计** | **18-19 天** | **28-41 天** | +10-22 天(探针 + 严格化) |
