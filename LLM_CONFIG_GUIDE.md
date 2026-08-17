# LLM后端配置指南

> 更新日期: 2026-08-17  
> 版本: v1.0

---

## 一、快速开始

### 1.1 配置方式（推荐）

通过环境变量 `LLM_PROVIDER` 控制后端选择：

```bash
# 开发/测试环境（使用DashScope）
export LLM_PROVIDER=dashscope
python scripts/main.py auto --limit 5

# 生产环境（使用妙搭）
export LLM_PROVIDER=miaoda
python scripts/main.py auto --limit 5
```

### 1.2 .env配置

在 `.env` 文件中添加：

```bash
# 开发/测试
LLM_PROVIDER=dashscope
DASHSCOPE_API_KEY=sk-xxx

# 生产
LLM_PROVIDER=miaoda
```

---

## 二、后端对比

### 2.1 DashScope后端

| 属性 | 值 |
|------|-----|
| **使用场景** | 开发、测试、本地验证 |
| **模型** | qwen-plus-latest（单模型） |
| **优点** | 配置简单、响应快、成本低 |
| **缺点** | 无降级链、单点故障 |
| **必需配置** | `DASHSCOPE_API_KEY` |

**适用场景**：
- ✅ 本地开发调试
- ✅ Prompt优化迭代
- ✅ GT测试验证
- ✅ 小规模数据测试（<100条）

### 2.2 Miaoda后端

| 属性 | 值 |
|------|-----|
| **使用场景** | 生产环境 |
| **模型** | 4模型降级链（glm-5.1/qwen-3.7-plus/doubao-seed-2.0-pro/minimax-m3） |
| **优点** | 高可用、自动降级、支持reasoning |
| **缺点** | 需OpenClaw环境、配置复杂 |
| **必需配置** | OpenClaw环境 + 妙搭innerapi权限 |

**适用场景**：
- ✅ 生产环境自动判责
- ✅ 大规模数据处理（>1000条/天）
- ✅ 高可用要求
- ✅ 自动降级容错

---

## 三、配置详解

### 3.1 环境变量优先级

配置加载顺序（高→低）：

1. **环境变量 `LLM_PROVIDER`**（最高优先级）
2. **config.yaml 中的 `llm.provider`**
3. **config.yaml 中的 `use_production_chain`**（向后兼容）

### 3.2 config.yaml配置

```yaml
llm:
  provider: ${LLM_PROVIDER:dashscope}  # 从env注入，默认dashscope
  use_production_chain: true           # 向后兼容（provider未设置时生效）
  
  # DashScope配置（provider=dashscope时使用）
  dev:
    provider: dashscope
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    model: qwen-plus-latest
    api_key_env: DASHSCOPE_API_KEY
    max_tokens: 8192
    timeout_seconds: 60
  
  # Miaoda配置（provider=miaoda时使用）
  shared_chain:
  - miaoda/glm-5.1
  - miaoda/qwen-3.7-plus
  - miaoda/doubao-seed-2.0-pro
  - miaoda/minimax-m3
  timeout_seconds: 120
```

### 3.3 代码逻辑

`scripts/main.py:_make_backend()` 选择后端：

```python
def _make_backend(cfg: dict):
    provider = cfg.get("llm", {}).get("provider", "").lower()
    
    if provider == "miaoda":
        return MiaodaBackend(cfg)
    elif provider == "dashscope":
        return DashScopeBackend(cfg)
    
    # 降级到use_production_chain（向后兼容）
    use_prod = cfg.get("llm", {}).get("use_production_chain", False)
    return MiaodaBackend(cfg) if use_prod else DashScopeBackend(cfg)
```

---

## 四、使用场景示例

### 4.1 本地开发调试

```bash
# 1. 配置.env
echo "LLM_PROVIDER=dashscope" >> .env
echo "DASHSCOPE_API_KEY=sk-xxx" >> .env

# 2. 运行测试
python scripts/main.py auto --limit 5
```

### 4.2 Prompt优化（GT测试）

```bash
# 使用DashScope快速迭代
LLM_PROVIDER=dashscope ./run_probe_gt_optimized.sh 1

# 分析结果
python scripts/analyze_probe_vs_gt.py probes/probe_gt_samples_*.json
```

### 4.3 生产部署前验证

```bash
# Step 1: DashScope验证（5条样本）
LLM_PROVIDER=dashscope python scripts/main.py auto --limit 5

# Step 2: Miaoda验证（需OpenClaw环境）
LLM_PROVIDER=miaoda python scripts/main.py auto --limit 1

# Step 3: 确认无误后部署
./deploy.sh
```

### 4.4 混合部署策略

```bash
# 方案1: 白天用Miaoda（高峰期），夜间用DashScope（省成本）
# cron: 10:00-18:00用miaoda，19:00-23:00用dashscope

# 方案2: A/B测试
# 50%流量用miaoda，50%用dashscope，对比质量

# 方案3: 降级备份
# 主用miaoda，检测到异常时自动切dashscope
```

---

## 五、故障排查

### 5.1 DashScope常见问题

**问题1: ModuleNotFoundError: No module named 'openai'**

```bash
# 解决：安装openai SDK
pip install openai
```

**问题2: DASHSCOPE_API_KEY未设置**

```bash
# 检查环境变量
echo $DASHSCOPE_API_KEY

# 重新加载.env
set -a && source .env && set +a
```

**问题3: 429 Rate Limit错误**

```bash
# 原因：超出API限流
# 解决：降低batch_size或切换到miaoda
```

### 5.2 Miaoda常见问题

**问题1: openclaw命令未找到**

```bash
# 原因：不在OpenClaw环境中
# 解决：确保在OpenClaw容器/服务器内运行
which openclaw
```

**问题2: 模型调用超时**

```bash
# 检查timeout配置
# config.yaml: llm.timeout_seconds
# 生产默认120秒，可根据实际调整
```

**问题3: subprocess返回ok=false**

```bash
# 检查openclaw日志
openclaw logs --tail 100

# 检查模型权限
openclaw infer model list
```

---

## 六、性能对比

### 6.1 响应时间

| 后端 | 平均响应时间 | P95响应时间 |
|------|-------------|------------|
| DashScope | ~15s | ~25s |
| Miaoda | ~20s | ~35s |

### 6.2 成本对比

| 后端 | 单条成本 | 1000条/天成本 |
|------|---------|--------------|
| DashScope | ¥0.02 | ¥20 |
| Miaoda | ¥0.03 | ¥30 |

*成本基于qwen-plus-latest，实际以账单为准*

### 6.3 可用性

| 后端 | SLA | 降级能力 |
|------|-----|---------|
| DashScope | 99.5% | 无（单模型） |
| Miaoda | 99.9% | 4模型降级链 |

---

## 七、最佳实践

### 7.1 开发阶段

✅ **推荐配置**：
```bash
LLM_PROVIDER=dashscope
```

**理由**：
- 响应快，迭代效率高
- 成本低，适合高频测试
- 配置简单，本地即可运行

### 7.2 测试阶段

✅ **推荐配置**：
```bash
# 功能测试用dashscope
LLM_PROVIDER=dashscope python scripts/main.py auto --limit 20

# 压力测试用miaoda
LLM_PROVIDER=miaoda python scripts/main.py auto --limit 100
```

**理由**：
- 功能测试关注正确性，不需要降级链
- 压力测试需要验证生产环境能力

### 7.3 生产阶段

✅ **推荐配置**：
```bash
LLM_PROVIDER=miaoda
```

**理由**：
- 高可用，自动降级
- 支持大规模并发
- 企业级SLA保障

---

## 八、迁移指南

### 8.1 从旧配置迁移

**旧配置**（只有use_production_chain）：
```yaml
llm:
  use_production_chain: true
```

**新配置**（推荐）：
```bash
# .env
LLM_PROVIDER=miaoda
```

**向后兼容**：
- 旧配置仍然有效
- 新配置优先级更高
- 逐步迁移，无需一次性修改

### 8.2 迁移步骤

```bash
# Step 1: 添加环境变量
echo "LLM_PROVIDER=dashscope" >> .env

# Step 2: 验证配置生效
python -c "from scripts.data_loader import load_config; print(load_config()['llm']['provider'])"

# Step 3: 运行测试
python scripts/main.py auto --limit 1

# Step 4: 确认无误，删除旧配置
# 注：保留use_production_chain作为降级配置
```

---

## 九、常见问题

**Q1: LLM_PROVIDER和use_production_chain的关系？**

A: `LLM_PROVIDER`优先级更高。如果设置了`LLM_PROVIDER`，则忽略`use_production_chain`；未设置时才使用`use_production_chain`。

**Q2: 可以在运行时切换后端吗？**

A: 可以，但需要重启进程。修改环境变量后重新运行即可。

**Q3: 如何验证当前使用的后端？**

A: 查看日志中的模型名称：
- DashScope: `qwen-plus-latest`
- Miaoda: `miaoda/glm-5.1`等

**Q4: 两个后端的Prompt版本一致吗？**

A: 一致。都使用 `assets/agent_single_prompt_template.j2`，当前版本v0.14.3。

**Q5: 可以同时运行两个后端吗？**

A: 可以。不同进程设置不同的`LLM_PROVIDER`即可，适合A/B测试。

---

## 十、参考文档

- [CLAUDE.md](./CLAUDE.md) - 项目宪法
- [SKILL.md](./SKILL.md) - 用户操作手册
- [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) - 部署检查清单
- [config.yaml](./config.yaml) - 配置文件

---

**更新记录**：
- 2026-08-17: 初版发布，支持LLM_PROVIDER环境变量切换
