# CLAUDE.md — 升级售后判责 SKILL 项目宪法

> 本文件是项目"宪法"，开发者（含 LLM 助手）开发前必读。
> 只写导航、持久原则、易忘点、拍板摘要：流程与决策记录进 `README.md`，操作手册进 `SKILL.md`，架构细节进 `references/architecture.md`。

---

## 0. 强规则

开发升级售后判责 SKILL（`aftersales-judge-decide`）前必须先读本文件。本文件只增不删、不轻易改，改动需确认拍板。

---

## 1. 项目目的

升级售后判责主流程 SKILL：从飞书任务表拉取待判责工单，串行调度 AGENT 调 LLM 完成判责，维护 5 状态机，写任务表 + 判责结果表。当前基线为 3 AGENT 串行，是否切 1 AGENT 由探针拍板（§7 原则 11）。

**不做**：规则解析生成、规则匹配、人工审核、申诉处理、miaoda 启动失败检测。

---

## 2. SKILL 依赖与工具栈

| 依赖 SKILL | 关系 | 调用方式 |
|---|---|---|
| `aftersales-rules-parse` | 解析层（只读）| 读判责规则表产物 |
| `store-tier-rules` | 门店分层 AST 求值 | import 其 scripts，不新写 `store_tier.py` |
| `bitable-meta-sync` | 飞书表元数据同步 | extract 模式 1（目标 base 内建新表）|

**生产栈**：lark-cli + Python 3.9+ + 妙搭 innerapi（4+2 LLM 降级链）+ OpenClaw cron。

**开发栈**（本地 CLI-only，不装 openclaw）：
- **Python环境**：项目本地venv（`.venv/`），不使用系统Python；pip安装到本地venv
- **Node环境**：项目本地node_modules（nvm管理版本），lark-cli本地安装
- **LLM**：Qwen DashScope OpenAI兼容端点（openai SDK，模型名一律 `qwen-plus-latest`）
- **原则**：全部 project-local、零全局污染（所有依赖装在项目目录内）
- 详见 `references/dev_env_setup.md`。

---

## 3. 目录结构（实物）

```plaintext
aftersales-judge-decide/
├── SKILL.md                # 有意删除：待 Phase 1.8 探针（1 vs 3）拍板后重建，勿从 git 恢复 v9
├── CLAUDE.md               # 本文件
├── README.md               # 过程记录（决策/阻塞项/Phase 状态）
├── config.yaml             # 业务参数（${VAR} 严格替换 env）
├── .nvmrc / .python-version / requirements.txt / package.json / .env.example
├── assets/
│   ├── agent{1,2,3}_prompt_template.j2    # 实物在 assets/ 根，不建 templates/ 子目录
│   ├── agent_single_prompt_template.j2    # 1-AGENT 融合模板（T1.5 探针用）
│   ├── field_types.json                   # 字段类型快照（data_loader dump，CSV coerce 基线）
│   └── eval/eval_standard.md
├── references/
│   ├── architecture.md         # 流程图/抢锁矩阵/9 类失败/1 vs 3 决策规则
│   ├── implementation_plan.md  # 6 Phase 节奏与探针决策门
│   ├── business_context.md     # 业务背景 → SKILL 映射
│   └── dev_env_setup.md        # 本地环境安装指南
├── scripts/
│   ├── main.py                 # 主流程 + cron 入口（auto/manual/probe/test）
│   ├── probe_llm.py            # 应用层探针（DashScope qwen-plus-latest 占位全链）
│   └── data_loader.py          # 数据层探针版（live lark-cli/CSV → 统一 SampleSet）
├── submodules/             # 依赖 SKILL 开发拷贝（gitignore；部署路径经 STORE_TIER_RULES_DIR 注入，见 README）
│   └── store-tier-rules/   # 门店分层（只 import apply_tier 纯函数）
├── tests/                  # pytest 首批（envelope/coerce/JOIN/correction/CSV/tier 降级）
└── trash/                  # 归档（gitignore）：源文档 PDF/规划 + env_requirements.md
```

子目录按需创建：根据实际需要建，不需要即不创建（不预建空目录）。

---

## 4. 应用层 = AST 消费方（核心架构）

应用层**不生成**业务规则，只读 + 应用：

| AST 来源 | table_id | 消费方式 | 阶段 | 调 LLM |
|---|---|---|---|---|
| 门店分层规则 | `tbllJ5aMjBhYRjIs` | 纯 AST 求值得门店等级 A/B/C/D | 阶段 2 batch | ❌ |
| 升级售后判责规则 | `tblty9QJT2g7caeg` | 按优先级遍历，注入 AGENT 2 prompt | 阶段 3 per-item | ⚠️ 仅参考 |

生产方不在应用层：门店分层规则由**人手配置**（规则少而稳定）；判责规则由 **`aftersales-rules-parse` 生成**（5 大类 19 动作）。

---

## 5. 表清单（飞书任务 + 维度 + AST）

| 表 | 类型 | app_token | table_id |
|---|---|---|---|
| 升级售后商家审核任务表 | 任务表 | `U7XQbSEq6axXfJsj2QocRxlQnqb` | `tblEMESCIIr4pqz8` |
| 判责结果表 | 业务表 | 待确认 | 待补 |
| 商品维度统计表 | 维度表 | `HGDzb2h7MaydFxsqlyAcCpALnB1` | `tblkP6fdG2OxN8JP` |
| 门店维度统计表 | 维度表 | `HGDzb2h7MaydFxsqlyAcCpALnB1` | `tblHJNJq8IEhlOs3` |
| 门店分层规则（AST）| 只读消费 | `HGDzb2h7MaydFxsqlyAcCpALnB1` | `tbllJ5aMjBhYRjIs` |
| 升级售后判责规则（AST）| 只读消费 | `HGDzb2h7MaydFxsqlyAcCpALnB1` | `tblty9QJT2g7caeg` |

table_id 一律以 `lark-cli` 实查为准。2026-08-12 已修复：`config.yaml` 门店分层规则 table_id 笔误（`tbllJ5aMajBhYRjIs` → `tbllJ5aMjBhYRjIs`，实查验证）。

---

## 6. 易忘点（开发前必查）

- **实物优先于文字预期**：路径/字段/ID 必须 lark-cli 实查；`ls` 看到文件存在 ≠ 文件在预期位置。
- **实物路径 vs doc 拍板路径**：实物为 `assets/agent{1,2,3}_prompt_template.j2`（根）+ `assets/eval/eval_standard.md`；不迁移到 doc §11.1 的 `templates/`/`policies/` 路径，两边都不动。
- **SKILL.md 有意删除**：待探针拍板后重建；git 里的 v9 版含过时表述（N=3 占位），勿恢复。
- **config.yaml 严格替换**：`${VAR}` 引用 env，缺失即启动失败；preflight 启动检查 5 项（feishu 凭据 / bitable 可达 / LLM 链 / cron 冲突 / 磁盘空间）。
- **5 状态写库分表**：任务表 update 幂等（5 状态都更新）；判责结果表 insert 1 单 1 行（仅成功/需人工终态，不写已处理-失败）。
- **沙箱 push 走一次性 PAT**：临时脚本 + url.insteadOf + push + unset + 删脚本；验证清理 5 项（`url.*` / `grep` / `known_hosts` / `memory/` / `/tmp/gh_push_*.sh`）。
- **迭代记录位置**：所有 Phase 5 Prompt 优化的迭代记录放在 `trash/迭代记录/`，包含 INDEX.md（版本对比索引）+ v0.X.0.md（完整迭代报告）。
- **迭代记录结构**：每个 v0.X.0.md 必须预留"## 八、补充建议与思考"章节，供用户 review 后补充业务洞察、优化方向、数据调整建议等内容。

---

## 7. 持久原则（不可轻易改）

| # | 原则 |
|---|---|
| 1 | 应用层只读 AST，不生成 AST（生成是 `aftersales-rules-parse` 的事）|
| 2 | 门店分层用 `store-tier-rules` SKILL import，不写自己的 `store_tier.py` |
| 3 | 探针先行：AGENT 切分 / prompt / 降级链必须先跑探针再拍板 |
| 4 | 实物优先于文字预期：路径 / 字段 / ID 必须 lark-cli 实查 |
| 5 | 单 JOB 单 Task：hourly 10-23 cron 单实例串行 |
| 6 | 失败重试独立计数：AGENT 1 retry 失败不影响 AGENT 2 状态 |
| 7 | 5 状态机不变量：任务表 update 幂等，判责结果表 insert 1 单 1 行 |
| 8 | stale 5min 兜底：bitable 无事务，靠单 JOB 单 Task + stale 重抢兜底 |
| 9 | 4 retry 类不飞书通知（避免 LLM 失败清单风暴）|
| 10 | cron 空跑不通知 |
| 11 | 3 AGENT 是当前基线（不是占位）；探针只决定 1 vs 3 切换——1 AGENT 达标则切 1，不达标保持 3（二选一，非 1/2/3/5）|
| 12 | 设计方案（v1.5 doc）不大调整；AGENT 数量只走原则 11 的探针出口，切 1 AGENT 的影响面锁在 LLM 调用层（5 状态机 / 9 类失败 / 锁 / 写表 / cron / 通知不变）|

---

## 8. GT测试与优化文档生成流程

### 8.1 GT测试标准流程

**目的**：验证prompt优化效果，生成多维度对比分析

**步骤**：
1. **运行GT探针测试**：
   ```bash
   ./run_probe_gt_simple.sh 1
   ```
   - 测试任务表中的所有样本（通常30-50条）
   - 自动过滤出GT中的39条样本
   - 生成3个文件：`probe_report_*.json`, `probe_gt_samples_*.json`, `comparison_*.json`

2. **多维度分析**（使用最新的probe结果）：
   ```bash
   source .venv/bin/activate
   python scripts/analyze_probe_vs_gt.py probes/probe_gt_samples_*.json
   ```
   - 输出责任比例对比（精确匹配率、分布对比）
   - 输出详细对比报告JSON

3. **赔付金额分析**（手动Python脚本）：
   ```python
   # 分析赔付金额准确率（±5%容差）
   # 分析系统性偏差（平均值对比）
   # 分析满足期望类型准确率
   ```

### 8.2 优化文档生成规范

**位置**：`trash/迭代记录/vX.X.0.md`（每个版本一个文档）

**文档结构**（必须包含）：
1. **执行摘要**：
   - 核心指标对比表（与上一版本对比）
   - 关键发现（3-5条要点）

2. **优化措施回顾**：
   - 列出本版本的所有改动（P0/P1分类）
   - 目标达成情况表

3. **三个维度分析**（Phase 5 Prompt优化必须包含）：
   - **责任比例分析**：准确率统计、分布对比、精确匹配案例、典型偏差案例
   - **赔付金额分析**：准确率统计、系统性偏差、完全匹配案例、偏差最大案例
   - **满足期望类型分析**：准确率、错误模式

4. **根因分析**：
   - 锚定问题分析（如30:70锚定、10:90锚定）
   - 系统性偏差原因
   - 准确率变化原因

5. **优化效果评估**：
   - 优化措施有效性表
   - 目标达成情况

6. **下一步优化方向**（vX+1.0）：
   - P0改动（必须解决的问题）
   - P1改动（提升准确率）
   - 预期成果表

7. **附录**：
   - 完整测试数据路径
   - 版本演进对比表

**命名规范**：
- 版本号：`vX.X.0`（X递增，保持0结尾）
- 文件名：`vX.X.0.md`（不带后缀如`_full_analysis`）
- 优化摘要：可选，命名为`vX.X.0_optimization_summary.md`

**数据保留**：
- probes目录：只保留最新版本的3个核心文件（probe_report, probe_gt_samples, comparison）
- GT数据：`assets/eval/ground_truth_v1.csv`持续维护，发现错误及时修正

### 8.3 版本迭代原则

**版本号规则**：
- `v0.6.0 → v0.7.0 → v0.8.0 → v0.9.0`（小版本号递增）
- 每次prompt优化算一个版本
- 版本号在文档中明确标注

**版本对比基准**：
- 每个版本文档必须与**上一版本**对比（如v0.8.0对比v0.7.0）
- 版本演进表包含所有历史版本

**优化循环**：
1. 分析当前版本问题（根因分析）
2. 设计优化方案（P0/P1改动）
3. 修改prompt模板
4. 提交commit（feat: vX.X.0 ...）
5. 运行GT测试
6. 生成优化文档
7. 回到步骤1（如未达目标）

---

## 9. 修订原则

本文件只增不删、不轻易改；改动需确认拍板。决策与教训的完整追溯见 `README.md` 决策历史，本文件保留结论不保留流水账。

---

## 10. Commit 规范（通用）

- **用户未明确要求不 commit**：除非用户明确说"提交"/"commit"，否则不主动创建 commit。完成代码修改后等待用户指示。
- **一个逻辑变更一个 commit**：不混入无关改动，也不把完整变更拆得支离破碎。
- **message 格式**：`type: 标题` — 中文标题 ≤ 50 字，写清做了什么；type 取 feat / fix / docs / refactor / test / chore。
- **body 写背景**：需要说明决策背景或取舍时在 body 展开；决策结论记 `README.md` 决策历史，不靠 commit message 承载。
- **绝不提交**：凭据（.env / token / key）；运行时产物与本地依赖由 .gitignore 覆盖（node_modules / probes / trash / .claude 等）。
- **push 需拍板**：push 到 GitHub 必须有明确指示。
