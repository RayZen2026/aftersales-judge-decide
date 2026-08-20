# 售后判责系统优化方案

## 当前状态（v0.16.3）

### 测试结果
- **物流责任识别准确率**: 20/20 = 100% ✓
- **责任比例分布**: 
  - 15:85（75%）、20:80（10%）、15:55（5%）
  - 3方责任：20:60:20, 10:60:30
- **主要问题**: 
  - 责任比例集中在15:85（虽然比之前的10:90有改善）
  - 调整因子应用透明度不足
  - 缺少运行时校验
  - prompt过长（超过1000行）

---

## 优化方案

### 优化1: 运行时校验（高优先级）

**目标**: 在代码层增加防御性校验，确保输出符合约束

**实施位置**: `scripts/agent_single.py`

**校验逻辑**:
```python
def validate_and_fix_responsibility(result: dict, task_data: dict) -> dict:
    """
    校验并修正责任比例输出
    
    校验规则：
    1. is_logistics_issue=0 时强制 logistics=0
    2. is_agent_issue=0 时强制 agent=0
    3. 责任比例和必须=100%
    4. 所有比例必须是10的倍数
    5. 平台比例范围10-50%，物流≤30%，代理人≤20%
    """
    resp = result.get("responsibility", {})
    
    # 规则1-2: 强制字段约束
    if task_data.get("是否物流问题") == 0:
        if resp.get("logistics", 0) != 0:
            logger.warning(f"字段校验失败: is_logistics_issue=0 但输出logistics={resp['logistics']}，强制修正为0")
            resp["logistics"] = 0
    
    if task_data.get("是否代理人问题") == 0:
        if resp.get("agent", 0) != 0:
            logger.warning(f"字段校验失败: is_agent_issue=0 但输出agent={resp['agent']}，强制修正为0")
            resp["agent"] = 0
    
    # 规则3: 和=100%
    total = sum(resp.values())
    if total != 100:
        logger.warning(f"责任比例和={total}% ≠ 100%，重新归一化")
        # 重新调用normalize_responsibility
        from state_machine import allocate_correction
        resp = allocate_correction(resp)
    
    # 规则4: 10的倍数
    for party, value in resp.items():
        if value % 10 != 0:
            logger.warning(f"{party}={value}%不是10的倍数，需重新归一化")
            from state_machine import allocate_correction
            resp = allocate_correction(resp)
            break
    
    # 规则5: 范围约束
    if not (10 <= resp.get("platform", 0) <= 50):
        logger.warning(f"平台比例{resp['platform']}%超出10-50%范围")
    if resp.get("logistics", 0) > 30:
        logger.warning(f"物流比例{resp['logistics']}%超出≤30%约束")
    if resp.get("agent", 0) > 20:
        logger.warning(f"代理人比例{resp['agent']}%超出≤20%约束")
    
    result["responsibility"] = resp
    return result
```

**集成点**: 在 `agent_single_chain()` 函数返回前调用
```python
# 在解析LLM输出后
result = json.loads(llm_final_output)

# 新增：运行时校验
result = validate_and_fix_responsibility(result, task_data)

return result
```

**预期效果**:
- 即使LLM输出错误，代码层也能自动修正
- 减少对prompt的依赖，提高系统鲁棒性
- 所有校验错误都会记录日志，便于后续prompt优化

---

### 优化2: 输入数据明确显示字段值（高优先级）

**目标**: 在prompt输入部分就明确标注责任方字段，让LLM一开始就建立正确认知

**实施位置**: `assets/agent_single_prompt_template.j2`

**修改内容**:

在 `### 责任方标识（售后单字段）` 部分增强显示：

```jinja2
### 责任方标识（售后单字段）

**重要：这些字段决定责任方识别，必须严格遵守**

```json
{
  "是否商家问题": {{ dimension_data.task.是否商家问题 | default(0) }},  # 1是0否
  "是否平台问题": {{ dimension_data.task.是否平台问题 | default(0) }},
  "是否物流问题": {{ dimension_data.task.是否物流问题 | default(0) }},  # ⚠️ 0时logistics必须=0
  "是否代理人问题": {{ dimension_data.task.是否代理人问题 | default(0) }},  # ⚠️ 0时agent必须=0
  "是否门店问题": {{ dimension_data.task.是否门店问题 | default(0) }},
  "是否商家承诺": {{ dimension_data.task.是否商家承诺 | default(0) }},
  "是否全品类商家": {{ dimension_data.task.是否全品类商家 | default(0) }}
}
```

**责任场景判定（根据字段自动确定）**:
{% if dimension_data.task.是否物流问题 == 0 and dimension_data.task.是否代理人问题 == 0 %}
- ✅ **2方责任场景**: platform + merchant = 100
- ❌ logistics = 0, agent = 0（不得传入非零值）
- 跳过§一.4.3和§一.4.4计算
{% elif dimension_data.task.是否物流问题 == 1 %}
- ✅ **3方责任场景（含物流）**: platform + merchant + logistics = 100
- ❌ agent = 0
- 计算§一.4.3物流基准比例
{% elif dimension_data.task.是否代理人问题 == 1 %}
- ✅ **3方责任场景（含代理人）**: platform + merchant + agent = 100
- ❌ logistics = 0
- 计算§一.4.4代理人基准比例
{% endif %}
```

**预期效果**:
- LLM在看到输入数据时就知道是2方还是3方场景
- 减少对后续推理的依赖
- 通过Jinja2模板动态生成场景提示，避免LLM自己判断

---

### 优化3: 增加计算透明度（中优先级）

**目标**: 要求LLM详细记录计算过程，便于验证和调试

**实施位置**: `assets/agent_single_prompt_template.j2`

**修改1: 输出schema增加字段**

```json
{
  ...
  "responsibility": {
    "platform": 0,
    "merchant": 0,
    "logistics": 0,
    "agent": 0
  },
  "responsibility_calculation": {
    "base": {"platform": 0, "merchant": 0, "logistics": 0, "agent": 0},
    "adjustments": [
      {"factor": "批次问题", "merchant_delta": "+15%", "reason": "批次问题信号=是"},
      {"factor": "商品偏离", "merchant_delta": "+10%", "reason": "商品偏离1.62>1.5"},
      {"factor": "商家偏离", "merchant_delta": "+5%", "reason": "商家偏离1.12在0.8-1.5"}
    ],
    "after_adjustments": {"platform": 25, "merchant": 95, "logistics": 0, "agent": 0},
    "normalized": {"platform": 20, "merchant": 80, "logistics": 0, "agent": 0}
  },
  ...
}
```

**修改2: 在judgment_basis.responsibility_reasoning中要求详细列出**

```
"responsibility_reasoning": "责任判定: 必须包含完整计算链
  - 基准: 商家XX%（A级+非严重品质）, 平台YY%（商家一般+门店A级）
  - 调整: 批次问题+15%, 商品偏离+10%, 商家偏离+5%, 全品类约束转移-10%
  - 累加: 商家75%+30%-10%=95%, 平台15%+10%=25%
  - 归一化: total=120% → 商家向上取整80%, 平台反算20%
  - 最终: 平台20%商家80% (logistics=0, agent=0)"
```

**预期效果**:
- 可以验证LLM是否真的应用了所有调整因子
- 便于发现计算错误
- 为后续优化提供数据支持

---

### 优化4: prompt精简（中优先级）

**目标**: 减少prompt长度，提升性能和准确率

**实施策略**:

#### 4.1 合并重复示例
- 删除示例1（40:60）或示例2.1（20:80），两者都是2方责任，保留一个即可
- 将示例2（30:70 A级严重品质）和示例2.5（20:80 全品类约束）合并为一个示例

#### 4.2 精简规则说明
将冗长的文字说明改为表格：

**当前**:
```
- 商品偏离倍数 > 2.0（严重品质问题）→ 商家 **+20%**
- 商品偏离倍数 > 1.5（品质波动）→ 商家 **+10%**
- 商品偏离倍数 < 0.8（优质商品）→ 商家 **-10%**
- 其他（0.8-1.5）→ 商家 **+0%**
```

**优化后**:
```
| 商品偏离倍数 | 商家调整 |
|-------------|---------|
| > 2.0       | +20%    |
| 1.5-2.0     | +10%    |
| 0.8-1.5     | +0%     |
| < 0.8       | -10%    |
```

#### 4.3 移除冗余说明
- 删除历史版本记录（行12-21），移到单独的CHANGELOG.md
- 删除重复的"关键原则"段落
- 简化P0规则的触发条件说明

**预期效果**:
- prompt从1000+行压缩到700-800行
- LLM更容易抓住关键指令
- 降低推理成本和延迟

---

### 优化5: 责任比例多样性（需进一步分析）

**现状**: 15:85占75%，集中度仍然较高

**可能原因分析**:
1. **数据本身集中**: 大部分样本确实都是A级商品+商家一般偏离的情况
2. **基准值设置**: A级非严重品质基准75%，加上一般的调整（+10%左右），确实容易落在85%附近
3. **LLM倾向**: 可能还是受到示例的锚定效应

**需要进一步分析**:
- 查看这15个15:85样本的原始数据，看是否有共同特征
- 检查它们的调整因子是否真的相同
- 如果数据本身就集中，那这不是问题；如果数据多样但输出集中，才需要优化

**优化方向**（待确认）:
1. **调整基准值**: 降低A级非严重品质的基准（75%→70%），拉开差距
2. **增加调整因子权重**: 让偏离倍数的影响更大（如商品偏离>1.5 从+10%改为+15%）
3. **增加更多示例**: 覆盖30:70, 25:75, 35:65等不同比例
4. **在prompt中明确要求**: "不要固定在某个比例，要根据实际数据计算"

**建议**: 先完成前4个优化，收集更多数据后再决定是否需要调整

---

## 实施计划

### 第一阶段（立即实施）✅ 已完成
1. ✅ **优化1**: 增加运行时校验（已完成 v0.17.0）
   - ✅ 编写 `validate_and_fix_responsibility` 函数（agent_single.py L263-333）
   - ✅ 集成到 `agent_single.py` run函数（L422调用）
   - ✅ 单元测试：tests/test_runtime_validation.py 6个场景全部通过
   - ✅ 端到端测试：v0.17.0测试1个样本，未触发校验（说明LLM输出正确）

2. ✅ **优化2**: 输入数据明确显示（已完成 v0.17.0）
   - ✅ 修改 prompt 模板增强字段显示（L110-143，责任方标识添加⚠️警告）
   - ✅ 增加Jinja2动态场景提示（2方/3方物流/3方代理人自动判定）
   - ✅ 明确列出强制约束和计算范围
   - ✅ 端到端测试：v0.17.0测试1个样本，输出正确（10:90:0:0）

### 第二阶段（短期优化）
3. ✅ **优化3**: 增加计算透明度（已完成 v0.16.4）
   - ✅ 修改输出schema（responsibility_calculation字段）
   - ✅ 更新config.yaml和feishu_bitable.py
   - ✅ 更新示例2.5展示完整计算过程
   - ✅ 测试并验证计算过程记录（v0.16.4+v0.17.0测试通过）

4. ⏳ **优化4**: prompt精简（待实施，约60分钟）
   - 合并示例
   - 表格化规则
   - 移除冗余
   - 全量测试20个样本

### 第三阶段（数据分析）
5. ⏳ **优化5**: 责任比例多样性分析（需确认）
   - 收集100+样本数据
   - 分析15:85样本的原始数据特征
   - 根据分析结果决定是否调整基准值或权重

---

## 预期效果

### 立即效果（第一阶段）
- **可靠性**: 即使LLM输出错误，代码层也能自动修正 → 物流责任识别准确率100%保持
- **准确性**: 输入数据明确显示场景类型 → 减少LLM推理错误

### 短期效果（第二阶段）
- **可维护性**: 计算过程透明化 → 便于问题排查和prompt优化
- **性能**: prompt精简 → 降低推理成本和延迟（预计减少20-30%）

### 长期效果（第三阶段）
- **多样性**: 根据数据分析调整基准值/权重 → 责任比例分布更合理

---

## 风险评估

### 风险1: 运行时校验可能过度修正
- **风险**: 如果校验逻辑有bug，可能错误修正正确的输出
- **缓解**: 
  - 所有修正都记录详细日志
  - 先在小批量测试，观察修正率
  - 如果修正率>5%，说明prompt仍有问题，需要继续优化

### 风险2: prompt精简可能丢失重要信息
- **风险**: 删除某些说明后，LLM可能遗漏规则
- **缓解**:
  - 分步精简，每次精简后测试
  - 保留核心规则，只删除冗余重复
  - 在删除前备份当前版本

### 风险3: 多样性优化可能破坏准确性
- **风险**: 调整基准值/权重后，可能导致某些场景下的比例不合理
- **缓解**:
  - 先做数据分析，确认有优化空间
  - 小幅调整（如75%→70%），而不是大幅改动
  - A/B测试新旧版本

---

## 成功指标

1. **物流责任识别准确率**: 保持100%（100+样本验证）
2. **运行时修正率**: <5%（说明prompt质量高）
3. **责任比例多样性**: 最高占比<50%（不再集中在某一比例）
4. **计算过程完整性**: 100%输出包含完整计算链
5. **推理延迟**: 降低20-30%（通过prompt精简）

---

## 备注

- 优化1和2是防御性措施，建议立即实施
- 优化3和4可以并行进行
- 优化5需要先收集数据分析，不要盲目调整
- 每次优化后都要全量测试20+样本，确保没有回退
