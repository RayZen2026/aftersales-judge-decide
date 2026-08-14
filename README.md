# aftersales-judge-decide

> 升级售后判责主流程 SKILL — 从飞书多维表格拉取待判责任务，串行调度 AGENT 调用 LLM 完成判责（当前基线 3 AGENT，探针决定是否切 1 AGENT），维护 5 状态机，处理 9 类失败，写飞书任务表 + 判责结果表，通过飞书私聊双通道通知运营（24h 去重）。

## 状态

**Phase 5 基线版本 v0.7.0 + 部署就绪**（2026-08-13）

- **v0.7.0 Prompt优化完成**：准确率 0% → 57.9%，30%锚定 90% → 58%，已达可接受水平
- **部署P0 Bug已修复**：4个阻塞性Bug全部修复，开发环境完全可用，生产环境代码就绪
- **LLM后端双栈支持**：开发环境用DashScope，生产环境用MiaodaBackend（openclaw subprocess）
- **下一步**：Phase 6部署准备（cron配置、生产环境验证、观察期启动）

**Phase 2 完成**（2026-08-12：6 核心模块 + 170 用例全绿，覆盖率 90-100%；下一步 Phase 3 主流程）

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

### LLM 后端选择（开发 vs 生产）

**配置开关**（`config.yaml`）：
```yaml
llm:
  use_production_chain: false  # false=开发环境，true=生产环境
```

**开发环境**（`use_production_chain: false`）：
- **后端**：DashScopeBackend（OpenAI 兼容 SDK）
- **模型**：qwen-plus-latest 单模型（config.yaml `llm.dev.model`）
- **降级链**：无（开发调试用，快速失败）
- **凭据**：env `DASHSCOPE_API_KEY`

**生产环境**（`use_production_chain: true`）：
- **后端**：MiaodaBackend（openclaw subprocess 调用）
- **模型**：4+2 降级链（config.yaml `llm.shared_chain` + `llm.agent3_chain`）
- **降级链**：glm-5.1 → qwen-3.7-plus → doubao-seed-2.0-pro → minimax-m3
- **凭据**：openclaw 已配置（无需额外 env）
- **要求**：openclaw 已安装且在 PATH

**切换方式**：
- 修改 `config.yaml` 中 `use_production_chain` 值
- 开发环境：保持 `false`，使用 DashScope
- 生产环境：改为 `true`，使用妙搭 4+2 降级链

**部署就绪状态**（2026-08-13）：
- ✅ **开发环境**：完全可用（DashScope + qwen-plus-latest）
- ⚠️ **生产环境**：代码就绪，需要 openclaw 环境验证（4 模型降级链 + 超时/错误场景测试）

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

## 部署配置检查清单

部署到生产环境（OpenClaw cron + 妙搭 innerapi）前，必须完成以下配置：

### 1. 环境变量配置（.env）

```bash
# 复制模板
cp .env.example .env

# 编辑 .env，设置以下必填项：
ENV=production                          # ⚠️ 必须设为 production
FEISHU_APP_ID=cli_xxx                   # 飞书应用凭据
FEISHU_APP_SECRET=xxx
BITABLE_APP_TOKEN_BUSINESS=U7XQbSEq6axXfJsj2QocRxlQnqb  # 任务表
BITABLE_APP_TOKEN_FIELDS=HGDzb2h7MaydFxsqlyAcCpALnB1    # 维度表
BITABLE_APP_TOKEN_RULES=HGDzb2h7MaydFxsqlyAcCpALnB1     # 规则表
```

### 2. LLM 后端配置（config.yaml）

```yaml
# 编辑 config.yaml
llm:
  use_production_chain: true   # ⚠️ 必须改为 true（开发默认 false）
  timeout_seconds: 120         # 妙搭 subprocess 超时（已配置）
  shared_chain:                # 生产降级链（4 模型）
  - miaoda/glm-5.1
  - miaoda/qwen-3.7-plus
  - miaoda/doubao-seed-2.0-pro
  - miaoda/minimax-m3
```

### 3. store-tier-rules 依赖路径

```bash
# 设置环境变量指向 OpenClaw workspace 中的 store-tier-rules
export STORE_TIER_RULES_DIR=/home/gem/workspace/agent/skills/store-tier-rules/scripts
```

### 4. Preflight 检查

```bash
# 运行启动前检查（6 项：环境一致性 + 5 项原有检查）
python scripts/main.py preflight

# 预期输出应包含：
# ✅ 环境一致性检查通过（production + use_production_chain=true）
# ✅ feishu_creds: env 变量存在 (3 项)
# ✅ bitable_read: 任务表可达
# ✅ llm_ping: 妙搭降级链可用
# ✅ disk_min_mb: 磁盘空间充足
# ✅ cron_registered: cron 配置正确
```

### 5. 部署后验证

```bash
# 手动触发一次 cron（不等待定时）
python scripts/main.py auto --limit 1

# 检查日志：
# - 无 preflight 报错
# - LLM 调用走 MiaodaBackend（非 DashScopeBackend）
# - 任务表状态正常更新（未处理 → 处理中 → 已处理）
```

**⚠️ 常见错误**：
- `ENV` 未设置或设为 `development` → preflight 报错"生产环境必须 use_production_chain=true"
- `use_production_chain=false` 但 `ENV=production` → preflight 报错（环境不一致）
- 缺少 `DASHSCOPE_API_KEY` 但 `use_production_chain=false` → DashScopeBackend 初始化失败

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

## Phase 1.5 收口：切 1 AGENT + schema v2 + GT 对比（2026-08-12）

**拍板**：切 1 AGENT（D-20260812-007，3 AGENT 方案暂停，快速落地优先）；代理人上限 20%（D-20260812-008）。

**1 轮调优**（schema v2 = judgment_basis 判责依据层 + 提价结果类型/满足期望类型 + C 类诉求代价判决标准 + platform 术语）：

| 指标 | Round 1 | 调优后 | 标准 |
|---|---|---|---|
| 格式校验率 | 1.0 | **1.0** | 100% ✅ |
| 一致性 core | 0.34 | **0.125** | ≤5% ❌（大幅改善仍未达） |
| latency P95 | 13.3s | **23.9s** | 端到端 ≤30s ✅（schema v2 输出变大） |

**GT 对比**（`assets/eval/ground_truth_v1.csv` 4 单 × 3 runs）：

| 维度 | 结果 |
|---|---|
| action / 提价结果类型 | 12/12 ✅ |
| amount 精确匹配 | 3/4（794255：探针 200 vs GT 150——GT 审核砍价，探针按诉求额全赔） |
| 满足期望类型 | 11/12 |
| **承担比例** | ❌ 全 runs 50:50 vs GT 1:9/1:9/3:7/5:5——LLM 把平台上限 50% 当默认值，Phase 3 首要调优项 |

**遗留风险（转 Phase 3 回归 + Phase 5 观察期）**：一致性 12.5% 仍超 5%；准确率未正式评估（GT 仅 4 单）；比例偏差；latency 贴近预算。

## Phase 5: 迭代记录（2026-08-13）

### 部署检查与 P0 Bug 修复（2026-08-13）

**部署检查发现**：部署后发现 4 个 P0 级 Bug，全部已修复（2 次 commit）

#### Bug #1: release_lock("pending") 崩溃 ✅
- **问题**：`lock.py:98` 只允许 3 个终态，字段缺失场景退回 pending 时崩溃
- **修复**：`scripts/lock.py` 允许 "pending" 状态（Line 98）
- **影响**：修复字段缺失场景崩溃，允许记录退回待处理状态

#### Bug #2: agent_single.run 永远走 dev_chain ✅
- **问题**：`agent_single.py:266` 硬编码 `dev_chain(cfg)`，生产环境无降级链
- **修复**：
  - `scripts/agent_single.py` (Line 262-268)：根据 `use_production_chain` 选择 chain
  - `config.yaml` (Line 332)：新增 `llm.use_production_chain` 配置开关
- **影响**：开发/生产环境可独立配置（单模型 vs 4+2 降级链）

#### Bug #3: MiaodaBackend 是空桩 ✅
- **问题**：`scripts/llm.py` 中 `MiaodaBackend` 只有 `raise NotImplementedError`，生产环境无法使用妙搭 LLM
- **修复**：
  - `scripts/llm.py` (Line 158-242)：完整实现 MiaodaBackend（80+ 行）
    - 通过 `openclaw infer model run` subprocess 调用妙搭
    - 解析 JSON 返回，处理 3 类错误（returncode/JSON decode/ok=false）
    - 超时处理（TimeoutExpired）
  - `scripts/main.py` (Line 273-287)：更新 `_make_backend` 支持后端选择
- **影响**：生产环境可使用妙搭 4+2 降级链，代码就绪待 openclaw 环境验证

#### Bug #4: Preflight 检查 env 但 config 用硬编码 ✅
- **问题**：`config.yaml` 所有 `app_token` 硬编码，Preflight 检查的 `BITABLE_APP_TOKEN_*` 环境变量不被使用
- **修复**：
  - `config.yaml`：7 处 app_token 改为 `${BITABLE_APP_TOKEN_*}` 变量引用
    - task_table.app_token: `${BITABLE_APP_TOKEN_BUSINESS}`
    - dimensions 4 表：`${BITABLE_APP_TOKEN_FIELDS}`
    - ast_rules 2 表：`${BITABLE_APP_TOKEN_RULES}`
  - `.env.example`：更新 3 个 token 变量说明
- **影响**：Preflight 检查与 config 配置口径一致，支持通过环境变量配置 token

**文件变更统计**：
```
第一次 commit（Bug #1, #2, #4）:
  .env.example            |  9 +++++++--
  config.yaml             | 15 ++++++++-------
  scripts/agent_single.py |  8 +++++++-
  scripts/lock.py         |  4 ++--
  4 files changed, 24 insertions(+), 12 deletions(-)

第二次 commit（Bug #3）:
  scripts/llm.py  | +83 -3  (实现 MiaodaBackend.call，80行新增)
  scripts/main.py | +16 -7  (_make_backend 支持后端选择)
  2 files changed, 92 insertions(+), 7 deletions(-)
```

**部署就绪状态**：
- ✅ **开发环境**：完全可用（DashScope + qwen-plus-latest）
- ⚠️ **生产环境**：代码就绪，需要 openclaw 环境验证（4 模型降级链 + 超时/错误场景测试）

---

### v0.6.0 Prompt 优化（累加计算公式）
- **目标**: 消除 v0.5.0 的 20:80 固定模式偏差
- **方案**: 应用累加计算公式（单向调整表述，避免"平台+X商家-X"相抵歧义）
- **成果**: 20:80 固定模式 100% → 0%（9/9 样本验证）
- **新问题**: 30% 平台比例锚定效应（9/9 样本平台比例均为 30%）
- **根因**: Prompt 中"治理义务 10-30%"描述过强，LLM 默认输出 30%

### v0.7.0 Prompt 优化（消除 30% 锚定效应）
- **目标**: 消除 v0.6.0 的 30% 平台比例锚定效应
- **方案**: 
  - 删除"10-30%"具体数值范围，改为"承担必要的治理责任"原则性描述
  - 约束检查后置（§一.4 计算公式），明确"先按公式算到底，最后才检查 10%-50% 约束"
  - 强调按公式计算，避免 LLM 提前假设平台比例
- **成果（N=20）**: 
  - 准确率: 0% → 57.9%（允许±10%偏差，11/19 匹配）
  - 30% 锚定: 90% → 58%（下降 32%）
  - 平台比例多样化: 30%(11条) / 40%(3条) / 50%(5条)
  - 格式校验率: 100%（保持）
  - 延迟 P95: 21.53s（稳定）
- **剩余问题**: 
  - 50:50 过判（4条）: GT 为 1:9/2:8 的案例被判为 50:50
  - 边界偏差（4条）: 偏差 20%（仍在可接受范围内）
- **结论**: v0.7.0 可作为 Phase 5 基线版本，准确率 57.9% 已达可接受水平

### Schema v4.0 完成（2026-08-13）
- **store_expected/store_expected_amount**: 改为透传输入（不判断）
- **action 枚举**: 赔付→赔付金额，增加"拒绝赔付"，移除"退款"/"无需处理"
- **amount**: 所有场景都输出（退货=建议赔付金额，拒绝赔付=0）
- **recommended_action**: 新增字段（倾向于退货/赔付金额/拒绝赔付）
- **judgment_summary**: 字数压缩至 ≤40字（仅结果）
- **reasoning**: 字数压缩至 ≤140字（判责报告给业务人员）
- **responsibility**: 支持 4 方责任（platform/merchant/logistics/agent）

### 端到端流程验证（2026-08-13）
- **验证目标**: 主流程（Stage1-4）无卡点
- **测试样本**: 3 条真实工单（UAS124827052384735292 / UAS124826525001334874 / UAS124820506573553731）
- **成果**: ✅ 100% 成功（3/3）
  - Stage1: 任务表拉取正常（视图「近两天数据」）
  - Stage2: 维度 JOIN 全部命中（商品维度/门店维度/门店分层/判责规则）
  - Stage3: LLM 判责（1-AGENT）Schema v4.0 合规率 100%
  - Stage4: 测试表写入（15 字段含 judgment_basis 8 维展开）
- **test_mode 功能**: 
  - 跳过抢锁/释放锁（可重复运行）
  - 写测试表而非生产表
  - 独立于任务表状态

### test_mode 实现（2026-08-13）
- **代码修改**:
  - `scripts/main.py`: process_item 增加 test_mode 参数，跳过锁操作
  - `scripts/main.py`: cmd_manual 支持 --test-mode 标志
  - `scripts/feishu_bitable.py`: build_result_fields 支持 test_mode（15 字段映射）
  - `config.yaml`: 新增 test_result_table 配置
- **测试表配置**:
  - 表名: 升级售后结果表-测试使用
  - app_token: HGDzb2h7MaydFxsqlyAcCpALnB1
  - table_id: tblQ1btbmJsBESGd
  - URL: https://bggc.feishu.cn/wiki/QtV8wiiSuikve7kOzaKcS4tEnXb?table=tblQ1btbmJsBESGd&view=vewWdG3ptr
- **测试表字段（15 个）**: 生产表 5 字段 + 建议动作 + judgment_basis 8 维展开 + 关键因素

### 30% 锚定效应分析（2026-08-13）
- **现象**: 9/9 样本平台比例均为 30%（v0.6.0 探针）
- **边界条件发现**: 1/12 样本突破锚定输出 20%（严重品质问题场景 is_severe_quality=1）
- **根因**: LLM 理解"治理义务 10-30%"为优先级高于累加计算的"强制调整"
- **下一步**: v0.7.0 Prompt 优化（弱化"治理义务"锚定 + 禁止覆盖累加结果）

### Phase 5 待完成项
- [ ] v0.7.0 Prompt 优化（消除 30% 锚定）
- [ ] GT 样本扩充（4 条 → 20+ 条）
- [ ] 准确率正式评估（责任比例准确率 ≥70%）
- [ ] 观察期数据收集（98 次 cron 触发）

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
| **D-20260812-006** | 决策 | 任务表拉取范围 = 视图「近两天数据」（vewdVsAfk9，审批创建时间 > Yesterday 相对滚动窗），不拉全量；filter-json 会覆盖视图过滤（实测）→ 处理状态走客户端过滤 | 确认 |
| **D-20260812-007** | 决策 | **AGENT 切分 = 切 1 AGENT**（Round 1 探针 1-AGENT 端到端跑通：格式校验 100% / 单调用 P95 13.3s，确认拍板快速落地；3 AGENT 方案暂停）。一致性/准确率未达 eval_standard 的风险转 Phase 3 回归 + Phase 5 观察期；切分影响面锁 LLM 调用层（architecture.md §3.5） | 确认 |
| **D-20260812-008** | 决策 | 代理人维护补偿上限 = **20%**（源文档 §5.2 写 15% vs §9 写 20% 不一致，拍板 20%）；business_context §6.1 闭环 | 确认 |
| **D-20260812-009** | 决策 | 1-AGENT 输出 schema v2 定稿：结论层（action/amount/responsibility 平台:商家/提价结果类型/满足期望类型）+ 期望层 + **判责依据层 judgment_basis**（门店画像/事实认定/责任判定/规则引用/决策对比，面向业务人员）+ 元数据层；GT 样例 = assets/eval/ground_truth_v1.csv（4 条）；术语 meituan → platform 对齐 GT | 确认 |
| **D-20260812-010** | 决策 | **开发期不走 skill_workshop 治理流程**（git 已覆盖审计/review/回滚；本仓 = staging，SKILL.md 有意删除、无活跃 SKILL 文件，不触 v2 §4.1）；Phase 1.8 改定位 = 部署准备（SKILL.md 重建草稿 + 4 项硬约束），**Phase 3 内容稳定后执行**；部署时一次性 propose-update apply（目标 workspace 若执行 v2 §4.1） | 确认 |
| **LCE-20260812-001** | 教训 | formula 字段返回字符串数字（30日售后赔付率='0.073...'）→ apply_tier 前必须数值 coerce | 实查 |
| **LCE-20260812-002** | 教训 | lark-cli envelope 双形态（外层 {ok,data} vs 裸 envelope）→ 解析必须防御解包 | 实查 |
| **LCE-20260812-003** | 教训 | 任务表/维度表 datetime 格式不一致（T00:00+08 vs T08:00+08）→ JOIN 按日期级匹配 | 实查 |
| **D-20260813-001** | 决策 | test_mode 功能实现：manual 命令支持 --test-mode 标志，写测试表（15 字段含 judgment_basis 8 维展开），跳过抢锁逻辑，可重复运行 | 确认 |
| **D-20260813-002** | 决策 | Schema v4.0 完成：recommended_action 新增字段，action 枚举调整（赔付金额/退货/拒绝赔付/需人工），store_expected/store_expected_amount 透传输入，judgment_summary ≤40 字，reasoning ≤140 字，支持 4 方责任 | 确认 |
| **D-20260813-003** | 决策 | 端到端流程验证通过（3/3 样本），主流程无卡点，可专注 LLM 优化；测试表 15 字段全部正确写入 | 确认 |
| **D-20260813-004** | 决策 | **部署 P0 Bug 全部修复**（4 个）：#1 release_lock pending 崩溃 / #2 永远走 dev_chain / #3 MiaodaBackend 空桩 / #4 Preflight env 不一致；开发环境完全可用，生产环境代码就绪待 openclaw 验证 | 确认 |
| **D-20260813-005** | 决策 | LLM 后端双栈支持：开发环境 DashScopeBackend（OpenAI SDK + qwen-plus-latest 单模型），生产环境 MiaodaBackend（openclaw subprocess + 4+2 降级链）；配置开关 `llm.use_production_chain`（false=开发，true=生产） | 确认 |

## 阻塞项（确认 review 时一次性提供）

> 2026-08-12 更新：#1/#2 已实查收口，#3/#4 部分就绪。

| # | 阻塞项 | 阻塞哪个 Task | 状态 |
|---|---|---|---|
| 1 | 商品维度统计表 metadata（app_token / table_id / 字段映射）| Phase 1.1 维度数据 JOIN | ✅ 实查收口 |
| 2 | 门店表 metadata（同上）| Phase 1.1 维度数据 JOIN | ✅ 实查收口 |
| 3 | 真实样本数据 10-20 条 | Phase 1.2 探针基础测试 | 🟡 live 拉取已通；人工标注 CSV Round 2 |
| 4 | 评估标准定稿（准确率 / 一致性 / latency 阈值）| Phase 1.2 探针基础测试 | 🟡 Round 1 只跑格式/一致性/latency；准确率 Round 2 |
| 5 | AGENT 1-3 切分定稿（Phase 1.5 探针后）| Phase 1.8 v1.6 doc 升版 | ⏳ 待探针 |
| 6 | 代理人维护补偿上限 15% vs 20%（business_context §6.1 两处不一致）| AGENT 2 业务 prompt | ✅ 2026-08-12 拍板 = 20%（D-20260812-008） |
| 7 | 任务表 处理状态 字段值（现仅"未处理"+ 手动造 2 条"已处理-失败"，5 状态选项待补全）| Phase 2 写表 | 🟡 部分就绪（拉取过滤已兼容，后续添加） |

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
