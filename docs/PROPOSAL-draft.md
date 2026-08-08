---
name: aftersales-judge-decide
description: |
  升级售后判责主流程 SKILL — OpenClaw cron 触发,从飞书多维表格拉取待判责任务,
  串行调度 N 个 AGENT 调用 LLM 完成判责(AGENT 1 门店期望判定 → AGENT 2 承担方比例判责
  → 分配校正 → AGENT 3 综合判责意见),维护 5 状态机(待处理 / 已处理-处理中 /
  已处理-成功 / 已处理-失败 / 已处理-需人工),处理 9 类失败(4 retry / 3 不重试 / 2 业务问题),
  写飞书任务表 + 判责结果表,通过飞书私聊双通道通知任锐(24h 去重)。

  严格不生成/修改判责规则(解析层 SKILL 负责)、不做人工审核、不做规则匹配。
  探针先行原则:AGENT 切分、prompt 模板、降级链在拍板前必须跑过探针。

  Trigger: 升级售后判责 / 判责主流程 / 4.2.3 / aftersales judge decide.

license: Proprietary (internal use only)
compatibility: |
  Requires lark-cli ≥ 1.0.79, Python 3.9+ with pyyaml, bitable access (3 bases:
  业务 base + 字段说明 base + 判责规则表 base from aftersales-rules-parse),
  妙搭 innerapi (4+2 LLM 降级链), OpenClaw cron.

metadata:
  openclaw:
    emoji: ⚖️
    id: aftersales-judge-decide
    version: 0.1.0
    primaryEnv: BITABLE_APP_TOKEN_BUSINESS
    requires:
      bins: [lark-cli, python3]
      env:
        - BITABLE_APP_TOKEN_BUSINESS
        - BITABLE_APP_TOKEN_FIELDS
        - BITABLE_APP_TOKEN_RULES
        - PROBE_OUTPUT_DIR
      config: [config.yaml]
    install:
      - "pip install pyyaml"
    user-invocable: true
    disable-model-invocation: false
    trigger:
      schedule: "0 10-23 * * *"
      timezone: Asia/Shanghai
      intent:
        - 升级售后判责
        - 判责主流程
        - 4.2.3
        - aftersales judge decide
---

# 升级售后判责主流程 SKILL

> **定位**: 编排 + 执行升级售后判责主流程,从飞书任务表拉取工单 → N 个 AGENT 串行调 LLM → 写任务表 + 判责结果表。
> **依赖**: 只读解析层 SKILL `aftersales-rules-parse` 的判责规则表产物。
> **不**生成/修改判责规则、**不**做人工审核、**不**做规则匹配。

## When to use

- "跑一下今天的判责"(`auto` 模式,cron hourly 10-23 自动触发)
- "判责这条工单"(`manual` 模式,单条处理)
- "先跑探针看 N AGENT 切分"(`probe` 模式,Phase 1 必做)
- "测一下端到端流程"(`test` 模式,独立 test_main_table 验证)

**不适用**:
- 解析申诉记录生成规则(→ `aftersales-rules-parse`)
- 改 / 删任务表(→ 独立表管理)
- 运营审核 / 申诉处理(→ 独立工单 SKILL)

## Workflow

```
auto/manual:  S1 触发 → S2 拉取任务 → S3 数据准备 → S4 抢锁+字段匹配 → S5 N AGENT 串行 → S6 状态机推进 → S7 写表 → S8 通知
probe:        1 vs 3 AGENT 切分对比 + 1 AGENT 完整流程,跑通即出报告
test:         独立 test_main_table,端到端单条验证
```

8 步细节 / 状态机 / 失败分类 → `references/architecture.md`(按需加载)。

## Commands

```bash
# 自动模式(cron hourly 10-23)
python3 {baseDir}/scripts/main.py auto [--batch-size 30]

# 手动模式(单条处理)
python3 {baseDir}/scripts/main.py manual --item-id <审批ID>

# 探针模式(Phase 1 必做,1 vs 3 AGENT 切分对比)
python3 {baseDir}/scripts/probe_llm.py --probe-agents 1,3 --samples 5

# 端到端测试模式(独立 test_main_table)
python3 {baseDir}/scripts/main.py test --table-id <test_main_table>
```

## Operations

### 5 状态机(D-20260806-006)

| 状态 | 含义 | 写表 |
|---|---|---|
| 待处理 | 初始态,等拉取 | 任务表 |
| 已处理-处理中 | 抢锁后,AGENT 跑中 | 任务表(含 任务处理时间) |
| 已处理-成功 | AGENT N 成功 + 状态机判定 | 任务表 + 判责结果表 |
| 已处理-失败 | 终态失败(重试 1+2 后仍失败) | 任务表(等 cron 兜底重试) |
| 已处理-需人工 | 业务问题(规则无匹配) | 任务表 + 判责结果表 |

### 9 类失败 → 3 大类(D-20260806-001)

| 大类 | 包含 | 处理 |
|---|---|---|
| **retry-able(4 类)** | 语义错 / 超时 / 429 / 未知 | retry 1+2 次(独立 AGENT 计数) |
| **不重试(3 类)** | 非 JSON / 必填缺失 / 字段类型错 | 终态失败(已处理-失败) |
| **业务问题(2 类)** | 规则无匹配 | 业务问题(已处理-需人工) |

### 4+2 LLM 降级链

**共享链(AGENT 1/2)**: glm-5.1 → qwen-3.7-plus → doubao-seed-2.0-pro → minimax-m3
**AGENT 3 独立链**: doubao-seed-2.0-pro → minimax-m3

> kimi-k2.6 已移出降级链(17-22s 慢得不合理,LRN-20260802-013)。

### 9 Magic Number

| 参数 | 值 | 用途 |
|---|---|---|
| `stale_timeout` | 5 min | 抢锁 stale 兜底 |
| `payment_threshold` | 200 元 | 触发赔付判责的金额阈值 |
| `batch_size` | 30 单/次 | 单次 Task 拉取上限 |
| `max_tokens` | 30000 | LLM 单次输出上限 |
| `temperature` | 0.1 | LLM 采样温度 |
| `retry_max` | 3 次 | 单 AGENT 失败重试上限(1+2) |
| `dedup_window` | 24 h | 飞书通知去重窗口 |
| `cron` | `"0 10-23 * * *"` | Asia/Shanghai hourly |
| `manual_review_threshold` | 待定 | 运营加新规则触发人工审核(暂不配) |

### 4 张表(任务表 + 判责结果表 + 2 维度表)

| 表 | 类型 | 用途 |
|---|---|---|
| 任务表(升级售后商家审核任务表) | 业务表 | 5 状态机主表,幂等更新 |
| 判责结果表 | 业务表 | 成功/需人工 2 终态写入,1 单 1 行 |
| 商品维度统计表 | 维度表 | 商品维度(原 5 维度表合并) |
| 门店表 | 维度表 | 门店维度 |

> **6 维度表 → 3 维度表合并**:
> 商家四级类目表/四级类目表/商家维度统计表/商品维度统计表 4 张合并到 1 张「商品维度统计表」
> 门店表保留 1 张独立
> (LCE-20260808-006)

### 探针先行原则(强规则,LRN-20260807-001)

- AGENT 切分、prompt 模板、降级链**必须在拍板前**跑过探针
- 探针支撑(业务 prompt 模板占位版 + 真实申诉数据样本 + 评估标准)未就绪前,**不能跑业务探针**
- **3 轮调优上限**:1 轮 = 跑 1 次单 AGENT 探针(5-10 样本 × 3 AGENT)+ 评估 + 调 1 次切分
  3 轮不收敛 → 强制定版当前最佳切分 + 风险标到生产观察期处理
- 探针**不 import** `llm.py`,避免循环依赖 + 概念独立
- 探针**不假设**当前 SKILL 的 AGENT 数量,测试场景比应用层更广

### 飞书通知双通道(D-20260806-011)

- **通道 1**: 飞书私聊任锐(写死 `ou_8f870f9b1670d27d033d91fda17ade4e`)
- **通道 2**: `memory/YYYY-MM-DD.md`(agent 跑出错时自动写)
- **去重**: 同单号 + 同异常类型 24h 内最多通知 1 次
- **触发场景**: 字段匹配失败 / 维度数据缺失 / 已处理-需人工 终态 / 整体批次异常 / 探针批次异常

### preflight(§7.6 v2.0 模板,4-5 项)

- [ ] feishu 凭据(BITABLE_APP_TOKEN_BUSINESS 等 3 个 env)
- [ ] bitable 可达(任务表 / 判责结果表 / 2 维度表)
- [ ] LLM 链(4+2 降级链 ping 通)
- [ ] 资源(磁盘 / 端口 / 沙箱凭证)
- [ ] cron 冲突(无重叠 schedule)

## Don't do

- **不**生成/修改判责规则(→ 解析层 SKILL)
- **不**做人工审核 / 申诉处理(→ 独立工单 SKILL)
- **不**做规则匹配(规则引擎在解析层产物中固化)
- **不**绑死 AGENT 数量(N=3 占位,探针回填,Phase 1.5 拍板)
- **不**在 SKILL.md body 放实现细节(→ `references/architecture.md` / `scripts/`)
- 妙搭三件套(Auto/Flash/Multimodal)**不**进 LLM 降级链;prompt 硬限 ≤ 30k 字符
- 流程图节点 ≤ 10 字,只描述 WHAT/ORDER,不描述 HOW/数字/决策编号
- L4 替换走严格模式(防软替换陷阱,§10.8 v2.0 模板)

## 阻塞项(Phase 1 review 阶段由任锐提供)

| # | 阻塞项 | 阻塞哪个 Task |
|---|---|---|
| 1 | 商品维度统计表 metadata(app_token / table_id / 字段映射) | Phase 1.1 维度数据 JOIN |
| 2 | 门店表 metadata(同上) | Phase 1.1 维度数据 JOIN |
| 3 | 真实样本数据 10-20 条 | Phase 1.2 探针基础测试 |
| 4 | 评估标准定稿(准确率 / 一致性 / latency 阈值) | Phase 1.2 探针基础测试 |
| 5 | AGENT 1-3 切分定稿(Phase 1.5 探针后) | Phase 1.8 v1.6 doc 升版 |
