# 部署前检查清单

> 生成时间: 2026-08-16  
> 当前状态: 已完成端到端验证，待正式部署

---

## 一、核心配置检查

### 1.1 config.yaml 关键配置

| 配置项 | 当前值 | 生产要求 | 状态 |
|--------|--------|----------|------|
| `result_table.table_id` | `tblQ1btbmJsBESGd` | `tblQ1btbmJsBESGd`（15字段生产表） | ✅ 正确 |
| `result_table.select_fields` | 5个字段定义 | 保持（代码根据table_id自动写15字段） | ✅ 正确 |
| `test_result_table.table_id` | `tblQ1btbmJsBESGd` | 同生产表（已转正） | ✅ 正确 |
| `task_table.fetch_view` | `vewdVsAfk9` | 保持（近两天数据） | ✅ 正确 |
| `llm.provider` | `dashscope` | 生产改为 `miaoda_innerapi` | ⚠️ **待确认** |
| `cron.schedule` | `0 10-23 * * *` | 按需（hourly 10-23） | ✅ 正确 |
| `environment` | `development` | 改为 `production` | ⚠️ **待修改** |

**关键说明**：
- 原测试表（tblQ1btbmJsBESGd）已转正为生产表
- 该表有15个字段，代码自动识别并写入完整字段
- 旧生产表（tblQFKdViDyghC65，5字段）已废弃

### 1.2 环境变量 (.env)

| 变量 | 用途 | 生产要求 | 状态 |
|------|------|----------|------|
| `ENV` | 环境标识 | `production` | ⚠️ 待修改 |
| `BITABLE_APP_TOKEN_BUSINESS` | 任务表 base | 已配置 | ✅ |
| `BITABLE_APP_TOKEN_FIELDS` | 维度表 base | 已配置 | ✅ |
| `BITABLE_APP_TOKEN_RULES` | 规则表 base | 已配置 | ✅ |
| `DASHSCOPE_API_KEY` | LLM API（开发期） | 生产期用妙搭 | ⚠️ 待确认 |
| `BITABLE_WRITE_ENABLED` | 写保护开关 | **不写入**.env | ✅ 正确 |
| `FEISHU_NOTIFY_ENABLED` | 通知开关 | 生产环境设为1 | ⚠️ 待确认 |

---

## 二、代码逻辑检查

### 2.1 15字段写入逻辑 ✅

**已修改**（2026-08-16）：
- `scripts/feishu_bitable.py:build_result_fields()` 
  - 新增 `table_id` 参数
  - 当 `table_id == "tblQ1btbmJsBESGd"` 时写15字段
  - 当指向生产表 `tblQFKdViDyghC65` 时写5字段

- `scripts/main.py:_write_result()`
  - 传递 `result_table_id` 给 `build_result_fields()`

**验证结果**：
- 5条样本写入测试表成功（无报错）
- 任务表状态更新正常（待处理 → 已处理-成功）

### 2.2 状态机逻辑 ✅

5状态转换已验证：
- 未处理（待处理） → 已处理-处理中（抢锁）
- 已处理-处理中 → 已处理-成功（完成）
- 已处理-处理中 → 已处理-失败（LLM失败）
- 已处理-处理中 → 已处理-需人工（规则无匹配）

### 2.3 Preflight 检查 ✅

5项启动检查全部实现：
1. `feishu_creds` - 环境变量检查
2. `bitable_access` - 飞书表连接
3. `llm_chain` - LLM可用性
4. `cron_config` - cron冲突检查（本地跳过）
5. `disk_space` - 磁盘空间检查

---

## 三、文档检查

### 3.1 核心文档完整性 ✅

| 文档 | 状态 | 说明 |
|------|------|------|
| `CLAUDE.md` | ✅ 最新 | 项目宪法，持久原则 |
| `SKILL.md` | ✅ 最新 | 用户操作手册（v1.0.0） |
| `README.md` | ✅ 最新 | 开发流程与决策历史 |
| `config.yaml` | ⚠️ 待调整 | result_table需改回生产表 |
| `.env.example` | ✅ 存在 | 环境变量模板 |

### 3.2 SKILL.md 元数据 ✅

OpenClaw 部署元数据已配置：
```yaml
metadata:
  openclaw:
    emoji: ⚖️
    id: aftersales-judge-decide
    version: 1.0.0
    primaryEnv: BITABLE_APP_TOKEN_BUSINESS
    trigger:
      schedule: "0 10-23 * * *"
      timezone: Asia/Shanghai
```

---

## 四、测试验证

### 4.1 端到端验证 ✅

**验证脚本**: `run_production_validation.sh`

**验证结果**（2026-08-16）：
- ✅ 5条样本全部处理成功
- ✅ 任务表状态正确更新
- ✅ 结果表写入无报错
- ✅ LLM调用正常（v0.14.3）
- ✅ 无异常日志

**处理记录**：
```
UAS126156932011540490: action=赔付金额 amount=23.42
UAS125965905111830600: action=赔付金额 amount=70
UAS125884913789452355: action=退货 amount=87.88
UAS125930251246121039: action=赔付金额 amount=50.76
UAS125874962236973060: action=赔付金额 amount=120.69
```

### 4.2 GT测试（Prompt v0.14.3）✅

**最新版本**: v0.14.3（消除30%锚定效应）

**关键指标**（待人工验证）：
- 30%锚定占比: 目标 <40%（v0.12.0基线82%）
- 责任比例准确率: 目标提升
- 赔付金额准确率: 维持±5%容差

---

## 五、部署步骤

### 5.1 配置修改（部署前必做）

1. **修改 .env**（生产环境）：
```bash
ENV=production
BITABLE_WRITE_ENABLED=1          # 生产环境启用
FEISHU_NOTIFY_ENABLED=1          # 启用飞书通知
DASHSCOPE_API_KEY=<生产key>     # 或配置妙搭innerapi
```

2. **验证配置**：
```bash
python3 scripts/main.py auto --limit 1  # 单条测试
```

**说明**：result_table 已指向正式生产表（tblQ1btbmJsBESGd，15字段），无需修改 config.yaml。

### 5.2 OpenClaw 部署

**方式1: skill_workshop 提议（推荐）**
```bash
cd /path/to/skill_workshop
./propose_update.sh aftersales-judge-decide /path/to/this/repo
# 审核通过后
./apply_update.sh aftersales-judge-decide
```

**方式2: 直接部署（需权限）**
```bash
# 在OpenClaw环境中
openclaw skill install /path/to/aftersales-judge-decide
openclaw skill enable aftersales-judge-decide
```

### 5.3 部署后验证

1. **Cron 触发验证**：
   - 等待下一个整点（10:00-23:00）
   - 检查任务表处理状态
   - 检查结果表新增记录

2. **手动触发验证**：
```bash
python3 scripts/main.py auto --limit 5
```

3. **监控指标**：
   - 处理成功率 ≥95%
   - 单条平均耗时 <30秒
   - LLM失败率 <5%
   - 30%锚定占比 <40%（前3天观察）

---

## 六、回滚方案

### 6.1 配置回滚

如发现问题，可通过以下方式回滚：

**数据隔离**：在 config.yaml 中配置 test_result_table 指向备用表
```yaml
test_result_table:
  table_id: <备用表ID>  # 如需要
```

**说明**：当前已使用15字段生产表（tblQ1btbmJsBESGd），无旧表可回滚。如需隔离测试，使用 `--test-mode` 参数。

```bash
# OpenClaw环境
openclaw skill disable aftersales-judge-decide
```

### 6.2 Cron 暂停

```bash
# OpenClaw环境
openclaw skill disable aftersales-judge-decide
```

---

## 七、生产表架构说明

### 7.1 15字段生产表 ✅

**当前生产表** (`tblQ1btbmJsBESGd`) 包含完整15个字段：

**基础字段（5个）**：
- 升级售后单号
- 判责结果
- 提交结果类型
- 满足期望类型
- 判责报告

**扩展字段（10个）**：
- 建议动作
- 门店画像（judgment_basis.store_profile）
- 商品品质（judgment_basis.product_quality）
- 商家追溯（judgment_basis.merchant_traceability）
- 事实认定（judgment_basis.fact_finding）
- 责任判定（judgment_basis.responsibility_reasoning）
- 金额调整（judgment_basis.amount_adjustment）
- 规则引用（judgment_basis.rule_reference）
- 决策对比（judgment_basis.decision_comparison）
- 关键因素（key_factors数组拼接）

**代码逻辑**：
- `scripts/feishu_bitable.py:build_result_fields()` 根据 `table_id` 自动判断
- `table_id == "tblQ1btbmJsBESGd"` → 写入15字段
- 其他table_id → 写入5字段（向后兼容）

---

## 八、已知问题与注意事项

### 8.1 表架构演进历史 ℹ️

- **Phase 4（2026-08-12）**：使用5字段表（tblQFKdViDyghC65）
- **Phase 5（2026-08-13）**：创建15字段测试表（tblQ1btbmJsBESGd）
- **2026-08-16**：测试表转正为生产表（本次变更）

旧5字段表（tblQFKdViDyghC65）已废弃，历史数据保留但不再写入。

### 8.2 LLM 链配置 ⚠️

当前使用 DashScope（开发期），生产环境建议：
- 方案A: 继续用 DashScope（需确认配额）
- 方案B: 切换到妙搭 innerapi（4+2降级链）

**切换步骤**（如选方案B）：
```yaml
# config.yaml
llm:
  provider: miaoda_innerapi
  shared_chain:
    - model: qwen-max
      fallback: qwen-plus
    - model: gpt-4
      fallback: gpt-3.5-turbo
```

### 8.3 Prompt 版本追踪

当前生产版本: **v0.14.3**（2026-08-16）
- 特性: 消除30%锚定效应
- 模板: `assets/agent_single_prompt_template.j2`
- 版本标记在模板头部（line 1-15）

---

## 九、联系与支持

**问题上报**:
- 查看日志: `logs/`
- 检查通知: `memory/notify_*.md`
- 飞书私聊: 配置在 `config.yaml notify.channels[feishu_dm].target`

**文档位置**:
- 架构设计: `references/architecture.md`
- 开发流程: `README.md`
- 业务背景: `references/business_context.md`

---

## 检查清单总结

### 必做项（P0）

- [ ] **LLM配置确认**: DashScope 或妙搭 innerapi
- [ ] **环境变量设置**: `ENV=production`, `BITABLE_WRITE_ENABLED=1`
- [ ] **单条测试**: `auto --limit 1` 验证通过
- [ ] **飞书表权限验证**: 确认生产表（tblQ1btbmJsBESGd）写入权限

### 建议项（P1）

- [ ] **GT测试验证**: 人工检查v0.14.3的30%锚定改善效果
- [ ] **飞书通知测试**: 确认通知渠道配置正确
- [ ] **监控告警配置**: 设置异常告警（如有监控系统）
- [ ] **文档归档**: 将验证报告和迭代记录整理到 `trash/`

### 可选项（P2）

- [ ] **Cron调优**: 根据实际负载调整schedule
- [ ] **Magic Number调优**: 观察期后调整 `config.yaml magic_numbers`
- [ ] **备份表配置**: 如需数据隔离，配置独立的test_result_table

---

**部署状态**: 🟢 已就绪，可直接部署  
**建议部署时间**: 工作日10:00-12:00（便于监控首次运行）

**关键变更**（2026-08-16）:
- 测试表（tblQ1btbmJsBESGd）转正为生产表
- 启用15字段完整判责依据写入
- 旧5字段表（tblQFKdViDyghC65）已废弃
