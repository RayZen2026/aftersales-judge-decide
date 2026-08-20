# 结果表字段映射与修复方案

## 一、问题描述

飞书结果表（tblQ1btbmJsBESGd）有27个字段，但当前代码只映射了16个字段，**缺失11个输入数据字段**。

这11个字段来自任务表，需要在写入结果表时从`task_row`或`dimension_data.task`中透传。

---

## 二、字段分类

### 2.1 已映射字段（16个）

#### 基础字段（5个，所有表都写）
1. ✅ 升级售后单号
2. ✅ 判责结果
3. ✅ 提交结果类型
4. ✅ 满足期望类型
5. ✅ 判责报告

#### 扩展字段（11个，仅测试表写）
6. ✅ 建议动作（LLM输出）
7. ✅ 门店画像（LLM输出）
8. ✅ 商品品质（LLM输出）
9. ✅ 商家追溯（LLM输出）
10. ✅ 事实认定（LLM输出）
11. ✅ 责任判定（LLM输出）
12. ✅ 金额调整（LLM输出）
13. ✅ 规则引用（LLM输出）
14. ✅ 决策对比（LLM输出）
15. ✅ 关键因素（LLM输出）
16. ✅ 责任计算过程（LLM输出）

### 2.2 缺失字段（11个，需要补充）

| # | 字段名 | 字段ID | 类型 | 数据来源 |
|---|--------|--------|------|----------|
| 17 | ❌ 升级售后提交间隔天数 | fldExihGiD | number | task_row["升级售后提交间隔天数"] |
| 18 | ❌ 是否商家问题 | fldl34KFYO | number | task_row["是否商家问题"] |
| 19 | ❌ 是否代理人问题 | fldRXQd7yd | number | task_row["是否代理人问题"] |
| 20 | ❌ 是否物流问题 | fldAKR03I7 | number | task_row["是否物流问题"] |
| 21 | ❌ 是否全品类商家 | fld9AVEAf9 | number | task_row["是否全品类商家"] |
| 22 | ❌ 诉求赔付金额 | fld4wUOmPp | number | task_row["诉求赔付金额"] |
| 23 | ❌ 诉求类型 | fldJBnFTLE | text | task_row["诉求类型"] |
| 24 | ❌ 是否严重品质问题 | fld3aG9zAY | number | task_row["是否严重品质问题"] |
| 25 | ❌ 是否平台问题 | fld7uLDSZH | number | task_row["是否平台问题"] |
| 26 | ❌ 门店等级 | fld4BkiOVk | text | task_row["门店等级"] |
| 27 | ❌ 升级售后类型 | fldHDvFwx6 | text | task_row["升级售后类型"] |

---

## 三、修改方案

### 3.1 修改文件：`scripts/feishu_bitable.py`

**位置**：`build_result_fields()` 函数

**修改内容**：

#### 步骤1：修改函数签名，接收task_row参数

```python
def build_result_fields(order_id: str, output: dict, task_row: dict = None, test_mode: bool = False, table_id: str = None) -> dict:
    """1-AGENT 输出 schema v4 → 判责结果表写入字段。
    
    Args:
        order_id: 升级售后单号
        output: LLM输出的完整结果
        task_row: 任务表原始数据（用于透传输入字段）
        test_mode: 是否测试模式
        table_id: 目标表ID
    """
```

#### 步骤2：在扩展字段中添加11个输入数据字段

```python
# 测试表扩展字段（22个）：test_mode=True 或 指向测试表
if test_mode or table_id == "tblQ1btbmJsBESGd":
    # ... 现有代码 ...
    
    # 新增：11个输入数据字段（从task_row透传）
    if task_row:
        fields.update({
            # 数值型字段
            "升级售后提交间隔天数": task_row.get("升级售后提交间隔天数", 0),
            "是否商家问题": task_row.get("是否商家问题", 0),
            "是否代理人问题": task_row.get("是否代理人问题", 0),
            "是否物流问题": task_row.get("是否物流问题", 0),
            "是否全品类商家": task_row.get("是否全品类商家", 0),
            "诉求赔付金额": task_row.get("诉求赔付金额", 0),
            "是否严重品质问题": task_row.get("是否严重品质问题", 0),
            "是否平台问题": task_row.get("是否平台问题", 0),
            
            # 文本型字段
            "诉求类型": task_row.get("诉求类型", ""),
            "门店等级": task_row.get("门店等级", ""),
            "升级售后类型": task_row.get("升级售后类型", ""),
        })

return fields
```

### 3.2 修改文件：`scripts/main.py`

**位置**：调用 `build_result_fields()` 的地方

**查找位置**：

```bash
grep -n "build_result_fields" scripts/main.py
```

**修改内容**：传递task_row参数

**修改前**：
```python
result_fields = build_result_fields(order_id, agent_output, test_mode=test_mode, table_id=result_table_id)
```

**修改后**：
```python
result_fields = build_result_fields(order_id, agent_output, task_row=task_row, test_mode=test_mode, table_id=result_table_id)
```

### 3.3 修改文件：`config.yaml`

**位置**：`dimensions.result_table.fields` 和 `dimensions.test_result_table.fields`

**修改内容**：添加11个字段配置（如果需要显式配置的话）

**注意**：根据当前代码逻辑，字段映射是直接通过字段名匹配的，不需要在config.yaml中显式配置每个字段的field_id。但为了文档完整性，可以在注释中说明。

---

## 四、实施步骤

### 步骤1：修改 feishu_bitable.py

1. 修改 `build_result_fields()` 函数签名，添加 `task_row` 参数
2. 在扩展字段部分添加11个输入数据字段的映射
3. 更新注释：从"11个扩展字段"改为"22个扩展字段"

### 步骤2：修改 main.py

1. 查找所有调用 `build_result_fields()` 的地方
2. 传递 `task_row` 参数

### 步骤3：测试验证

1. 选择一个测试样本
2. 修改其状态为"未处理"
3. 运行测试
4. 检查结果表中11个新字段是否正确填充

### 步骤4：提交

```bash
git add scripts/feishu_bitable.py scripts/main.py
git commit -m "feat: 结果表新增11个输入数据字段透传

- feishu_bitable.py: build_result_fields新增task_row参数
- 透传11个输入字段：升级售后提交间隔天数、是否商家问题、是否代理人问题、
  是否物流问题、是否全品类商家、诉求赔付金额、诉求类型、是否严重品质问题、
  是否平台问题、门店等级、升级售后类型
- 测试表扩展字段：从11个增加到22个
- 目标：结果表可以完整查看输入数据+输出数据，便于分析和调试"
```

---

## 五、数据流图

```
任务表 (task_table)
  ↓ (包含11个输入字段)
task_row
  ↓
main.py: 调用 agent_single.run()
  ↓
LLM输出 (output, 包含11个判责依据字段)
  ↓
main.py: 调用 build_result_fields(order_id, output, task_row)
  ↓
结果表 (result_table)
  - 5个基础字段（所有表）
  - 11个LLM输出字段（测试表）
  - 11个输入数据字段（测试表，新增）
  = 27个字段（完整）
```

---

## 六、预期效果

**修改前**：
- 结果表有27个字段，但11个输入数据字段是空白
- 无法在结果表中直接查看输入条件（需要关联任务表）

**修改后**：
- 结果表27个字段全部填充
- 可以在结果表中同时查看输入数据和输出数据
- 便于分析、调试和数据导出

---

## 七、注意事项

1. **字段名匹配**：飞书表字段名必须与task_row的key完全一致
2. **默认值**：数值型字段默认0，文本型字段默认空字符串
3. **仅测试表**：这11个字段只在测试表（tblQ1btbmJsBESGd）中写入，生产表不写
4. **向后兼容**：task_row参数默认None，现有调用不传也不会报错（只是字段为空）

---

## 八、FAQ

### Q1：为什么这11个字段之前没有映射？

A：可能是因为：
1. 初期只关注LLM输出结果，没有考虑输入数据透传
2. 测试表是后来扩展的，字段逐步增加
3. 结果表主要用于展示判责结果，输入数据可以从任务表关联查询

### Q2：为什么只在测试表写入，生产表不写？

A：
1. 生产表设计时可能只需要5个核心字段（单号、结果、类型、报告）
2. 测试表用于调试和分析，需要更完整的数据
3. 输入数据在任务表已有，生产环境可以通过单号关联查询

### Q3：task_row从哪里来？

A：从 `data_loader.fetch_tasks_live()` 返回的 `Envelope.records` 中获取，是任务表的原始数据行（字典格式）。

### Q4：如果task_row为None会怎样？

A：代码会跳过这11个字段的写入（因为有 `if task_row:` 判断），字段值保持空白，不会报错。
