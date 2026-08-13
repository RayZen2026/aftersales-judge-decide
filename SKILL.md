---
name: "aftersales-judge-decide"
description: "升级售后判责主流程 SKILL：cron 触发 → 1 AGENT 判责 → 5 状态机 → 写飞书任务表 + 判责结果表。"
license: Proprietary (internal use only)
compatibility: |
  Requires lark-cli ≥ 1.0.79, Python 3.9+ (pyyaml / jinja2 / openai),
  飞书多维表格访问权限（业务 base + 维度 base + 规则 base），
  妙搭 innerapi（4+2 LLM 降级链，生产），OpenClaw cron。

metadata:
  openclaw:
    emoji: ⚖️
    id: aftersales-judge-decide
    version: 1.0.0
    primaryEnv: BITABLE_APP_TOKEN_BUSINESS
    requires:
      bins: [lark-cli, python3]
      env:
        - BITABLE_APP_TOKEN_BUSINESS
        - BITABLE_APP_TOKEN_FIELDS
        - BITABLE_APP_TOKEN_RULES
        - DASHSCOPE_API_KEY
      config: [config.yaml]
    install:
      - "pip install -r requirements.txt"
      - "npm install"
    user-invocable: true
    disable-model-invocation: false
    trigger:
      schedule: "0 10-23 * * *"
      timezone: Asia/Shanghai
      intent:
        - 升级售后判责
        - 判责主流程
        - aftersales judge decide
---

# 升级售后判责主流程 SKILL

> **定位**：从飞书任务表拉取待判责工单，调用 1-AGENT LLM 完成判责，维护 5 状态机，写任务表 + 判责结果表。
> **依赖**：只读 `aftersales-rules-parse` SKILL 的判责规则表产物（AST）；门店分层由 `store-tier-rules` SKILL 的 `apply_tier` 函数批量计算（不调 LLM）。
> **不做**：生成/修改判责规则、人工审核、申诉处理、规则匹配。

## When to use

- "跑一下今天的判责" → `auto` 模式（cron hourly 10-23 自动触发）
- "判责这条工单 UAS1234..." → `manual` 模式（单条处理）

**不适用**：
- 生成判责规则 → `aftersales-rules-parse`
- 修改任务表数据 → 独立表管理
- 运营审核 / 申诉处理 → 独立工单 SKILL

## Workflow

```
auto / manual：
  S1 preflight（5 项启动检查）
  S2 视图「近两天数据」拉取（未处理 + 已处理-失败）
  S3 数据准备 batch（维度 JOIN + 门店分层 AST + 判责规则拉取）
  S4 per-item 串行
      → 抢锁（处理状态 → 已处理-处理中）
      → 字段匹配检验
      → 1-AGENT 判责（agent_single_prompt_template.j2）
      → 9 类失败处理
      → 写判责结果表（成功/需人工终态）
      → 写回任务表状态
      → 释放锁

probe / test 是开发内部模式，不对用户暴露。
```

细节 → `references/architecture.md`（按需加载）。

## Commands

```bash
# 自动模式（cron hourly 10-23 Asia/Shanghai）
python3 {baseDir}/scripts/main.py auto

# 手动模式（指定单号单条处理）
python3 {baseDir}/scripts/main.py manual --item-id <升级售后单号>

# 测试模式（写测试表，可重复运行，开发/测试期）
python3 {baseDir}/scripts/main.py manual --item-id <升级售后单号> --test-mode
```

## Preflight

启动时自动运行，任一 abort 级失败则阻断：

| 检查项 | 类型 | 失败行为 |
|---|---|---|
| `feishu_creds` | env 变量存在（4 个 token） | abort |
| `bitable_access` | lark-cli 可读 4 张表 | abort |
| `llm_chain` | LLM 链 ping 通 | warn_only |
| `cron_config` | cron 无重叠（本地跳过） | warn_only |
| `disk_space` | 可用磁盘 ≥ 500MB | warn_only |

abort 失败时输出具体失败项，检查 env 或 lark-cli 授权后重跑。

## Config

`config.yaml` 关键配置项（`${VAR}` 引用 env，缺失启动即 abort）：

| 键 | 说明 | 调优 |
|---|---|---|
| `task_table.fetch_view` | 拉取视图（近两天数据，vewdVsAfk9）| 按飞书表实查更新 |
| `probe.task_fetch.status_in` | 拉取状态范围（未处理 / 已处理-失败）| 一般不改 |
| `llm.shared_chain` | 4 模型降级链（生产） | 需妙搭环境 |
| `llm.dev.model` | 开发期单模型（qwen-plus-latest） | 按账号权限 |
| `magic_numbers` | 8 个运行参数（见下）| Phase 5 观察期调优 |
| `notify.channels[*].target` | 飞书私聊接收人 open_id | 换人时改 |
| `cron.schedule` | `0 10-23 * * *` Asia/Shanghai | 按需调 |

必需 env：
```
BITABLE_APP_TOKEN_BUSINESS   # 升级售后商家审核任务表所在 base
BITABLE_APP_TOKEN_FIELDS     # 字段说明 base（维度表）
BITABLE_APP_TOKEN_RULES      # 判责规则 base
DASHSCOPE_API_KEY            # 开发期 Qwen DashScope（生产用妙搭 innerapi）
BITABLE_WRITE_ENABLED=1      # 开启真实飞书写入（开发期不设则只读）
FEISHU_NOTIFY_ENABLED=1      # 开启飞书私聊通知（开发期不设则只记 memory）
```

## Formatter

判责结果写入飞书判责结果表，运营通过飞书查阅：

### 生产表（5 字段，正常运行）

| 字段 | 示例 | 说明 |
|---|---|---|
| 升级售后单号 | UAS124632640199344143 | 主键，关联任务表 |
| 判责结果 | 同意赔付24.36元，平台商家10:90 | 简短结论（action + 金额 + 责任比例）<br/>支持4方责任：平台/商家/物流/代理人 |
| 提交结果类型 | 同意 / 拒绝 / 需人工 | 对门店诉求的最终处置 |
| 满足期望类型 | 完全满足 / 部分满足 / 不满足 / 需人工 | 与门店期望的对齐程度 |
| 判责报告 | 【判责结论】...【门店画像】...【责任判定】... | 完整判责依据（8部分），供业务人员解释判责结果 |

**判责结果格式示例**（Schema v4.0）:
- 2方赔付: "同意赔付24.36元，平台商家10:90"
- 3方赔付: "同意赔付42元，平台30%、商家40%、物流30%"
- 退货场景: "同意退货，建议赔付107.43元，平台商家20:80"
- 拒绝场景: "拒绝赔付，平台商家30:70"

**判责报告8部分**:
1. 判责结论 (judgment_summary, ≤40字)
2. 门店画像 (store_profile)
3. 商品品质 (product_quality)
4. 商家追溯 (merchant_traceability)
5. 事实认定 (fact_finding)
6. 责任判定 (responsibility_reasoning)
7. 金额调整 (amount_adjustment)
8. 规则引用 (rule_reference)
9. 决策对比 (decision_comparison)

### 测试表（15 字段，--test-mode 开发/测试期）

测试表包含生产表 5 字段 + 扩展 10 字段:
- **建议动作** (recommended_action): 倾向于退货/赔付金额/拒绝赔付
- **judgment_basis 8维展开**: 将判责报告的 8 个部分拆分为独立字段
- **关键因素** (key_factors): 提炼的决策关键点

**用途**: 开发/测试期查看 LLM 推理过程，便于 prompt 优化和质量分析  
**测试表 URL**: https://bggc.feishu.cn/wiki/QtV8wiiSuikve7kOzaKcS4tEnXb?table=tblQ1btbmJsBESGd&view=vewWdG3ptr

任务表同步更新处理状态：

| 终态 | 含义 | 结果表写入 |
|---|---|---|
| 已处理-成功 | 判责完成 | ✅ |
| 已处理-需人工 | 规则无匹配 / 信息不足 | ✅（含部分结果）|
| 已处理-失败 | LLM 链全失败 | ❌（等下次 cron 兜底重试）|

## Operations

### 8 Magic Number

| 参数（config magic_numbers） | 值 | 用途 |
|---|---|---|
| `stale_timeout_minutes` | 5 min | 处理中记录 stale 兜底重抢阈值 |
| `payment_threshold_yuan` | 200 元 | 诉求赔付金额参考阈值 |
| `batch_size` | 30 单/次 | 单次 cron 拉取上限 |
| `max_tokens` | 30000 | 生产 LLM 单次输出上限（开发期 8192）|
| `temperature` | 0.1 | LLM 采样温度 |
| `retry_max` | 3 次 | 单次运行内 LLM 失败重试上限 |
| `dedup_window_hours` | 24 h | 飞书通知去重窗口（同单号同异常类型）|
| `manual_review_threshold` | null | 需人工置信度阈值（待拍板）|

### 5 状态机

| 状态 | 拉取？| 含义 |
|---|---|---|
| 未处理（待处理）| ✅ | 初始态 |
| 已处理-处理中 | ❌（stale 兜底）| 抢锁中 |
| 已处理-成功 | ❌ | 最终态 |
| 已处理-失败 | ✅（cron 重试）| 失败态，等重试 |
| 已处理-需人工 | ❌ | 业务问题，等运营 |

### 9 类失败 → 3 大类

| 大类 | 失败类型 | 处理 | 通知 |
|---|---|---|---|
| **retry（3 类）** | llm_rate_limit / llm_5xx / bitable_temp_unavailable | 最多 3 次重试，耗尽 → 已处理-失败 | ❌（原则 9）|
| **需人工（3 类）** | appeal_info_insufficient / rule_conflict / llm_ability_exceeded | 已处理-需人工 + 写结果表 | ✅ |
| **终态失败（3 类）** | credential_invalid / rule_not_found / data_corrupted | 已处理-失败（不重试）| ✅ |

### 飞书通知

- **通道 1**：飞书私聊（`notify.channels[feishu_dm].target` open_id）
- **通道 2**：`memory/notify_YYYY-MM-DD.md` 追加记录
- **去重**：同单号 + 同异常类型 24h 内最多 1 次
- **不通知**：retry 类失败（原则 9）、cron 空跑（原则 10）

## Don't do

- 不生成 / 修改判责规则（→ 解析层 SKILL `aftersales-rules-parse`）
- 不做人工审核 / 申诉处理（→ 独立工单 SKILL）
- 不新写门店分层逻辑（→ `store-tier-rules` SKILL import `apply_tier`）
- prompt 硬限 ≤ 30k 字符
- `probe` / `test` 模式不对外暴露（开发内部用，详见 README「开发模式」段）
- 飞书 bitable 写入需显式设 `BITABLE_WRITE_ENABLED=1`（防开发误写生产）
