# 环境依赖清单

> **本文件范围**：升级售后判责 SKILL（`aftersales-judge-decide`）运行 + 开发所需的**开发工具 + Python package** 依赖清单。
> **不含**：飞书凭据 / 飞书 scope 申请 / 数据源 app_token / 阻塞数据 / 6 Phase 任务清单 / preflight 检查 —— 这些见 SKILL.md + config.yaml + 升级售后主流程 SKILL 开发规划.md。
>
> **基线日期**：2026-08-11 11:30 UTC（按任锐拍板：本地 CLI-only 开发期栈 + 生产部署栈分离记录）
> **核对依据**：v1.5 doc compatibility 段（lark-cli ≥ 1.0.79, Python 3.9+ with pyyaml）+ frontmatter `requires.bins`/`requires.env`/`install` 段 + 沙箱实物核对 + 2026-08-11 11:30 UTC 任锐拍板"本地 CLI-only，Qwen 替代妙搭"。

---

## A. 开发期栈（CLI-only，本地开发用）

> **2026-08-11 11:30 UTC 任锐拍板**：本地开发**不**用 OpenClaw 运行时 / openclaw CLI / OpenClaw cron / OpenClaw Gateway——全部 CLI-only。LLM 用 Qwen DashScope API 替代（跟生产 qwen-3.7-plus 同源，输出最接近）。
>
> **理由**：本地只用于 SKILL 业务逻辑 + 探针 + 单元测试，**不**部署生产 cron 调度。LLM 直调 Qwen DashScope OpenAI 兼容端点，**不**走妙搭 innerapi（妙搭直调 3 种端点全失败，TOOLS.md LRN-20260802-013 探针锁死）。
>
> **！** 跟生产共用：lark-cli（飞书调用）+ python3 + 7 必备包（业务逻辑）。**不**共用：LLM 调用（本地 Qwen / 生产 openclaw 调妙搭）+ cron 调度（本地手跑 / 生产 OpenClaw cron）。

### A.1 CLI 工具（8 项）

| # | CLI 工具 | 用途 | 最低版本 | 推荐版本 | 实物版本 | 前置要求 | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | **lark-cli** | 飞书 openapi 调用（base / im / docx / sheets / drive 等）| 1.0.79 | 1.0.85+ | **1.0.85** | **Node.js ≥ 16**（npm `@larksuite/cli`）| ✅ |
| 2 | **python3** | SKILL 脚本 + 探针 + 数据处理 | 3.9 | 3.11+ | **3.10.12** | — | ✅ |
| 3 | **pip** | Python 包管理 | 21+ | 25+ | **26.0.1** | Python 3.9+ | ✅ |
| 4 | **git** | 仓库管理 + push | 2.25+ | 最新 | **2.34.1** | SSH 客户端 or credential helper | ✅ |
| 5 | **ssh** (OpenSSH) | git push 走 SSH（bitable-meta-sync 远端）| 7+ | 8+ | **8.9p1** | — | ✅ |
| 6 | **make** (可选) | build | 3.8+ | 4+ | **4.3** | — | ✅ |
| 7 | **Node.js** | lark-cli 运行时 + npm | 16 (lark-cli 最低) | 22 LTS | **22.22.1** | — | ✅ |
| 8 | **npm** | lark-cli 安装 | 8+ | 10+ | **10.9.4** | Node.js | ✅ |

**🔴 本地开发栈明确**：
- **不**列 **openclaw CLI**（任锐拍板本地用 Qwen DashScope 替代）
- **不**列 **OpenClaw Gateway**（任锐拍板本地 CLI-only）
- **不**列 **OpenClaw cron**（任锐拍板本地手跑 + pytest）
- **不**列 **crontab / systemd timer / launchd**（开发期不需要调度，手跑 + pytest 足够）

### A.2 Python 包（8 必备 + 3 可选）

| # | 包 | 最低版本 | 推荐版本 | 实物版本 | 用途 | 前置依赖 | 状态 |
|---|---|---|---|---|---|---|---|
| 1 | **pyyaml** | 5.1 | 6.0+ | **6.0.3** | config.yaml 加载（v1.5 doc frontmatter `install:` 段明列）| — | ✅ |
| 2 | **jinja2** | 3.0 | 最新 | **3.1.6** | .j2 业务 prompt 模板渲染（AGENT 1/2/3）| — | ✅ |
| 3 | **pandas** | 1.3 | 2.0+ | **2.3.3** | 维度数据 JOIN（任务表 × 6 张维度表）| numpy ≥ 1.20 | ✅ |
| 4 | **numpy** | 1.20 | 最新 | **2.2.6** | 分位数计算（store-tier-rules SKILL 复用）| — | ✅ |
| 5 | **pytest** | 7.0 | 最新 | **9.0.2** | 单元测试（tests/ 框架，v1.5 doc §11.1）| pyyaml | ✅ |
| 6 | **pytest-timeout** | 2.0 | 最新 | **2.4.0** | 探针超时控制（probe_llm.py 长 prompt 跑时）| pytest | ✅ |
| 7 | **requests** | 2.25 | 最新 | **2.32.5** | HTTP 客户端 | — | ✅ |
| 8 | **openai** ⭐ | 1.0 | 最新 | **待装** | **OpenAI 兼容 SDK 调 Qwen DashScope 端点**（本地 LLM 替代妙搭）| — | 🟡 |
| 9 | **pytest-cov** (可选) | 4.0 | 最新 | 待装 | 测试覆盖率 | pytest | 🟡 |
| 10 | **pytest-mock** (可选) | 3.10 | 最新 | 待装 | mock 框架（feishu_bitable / llm 测试）| pytest | 🟡 |
| 11 | **lark-oapi** (可选) | 1.2 | 最新 | 待装 | 飞书 SDK 替代 lark-cli（**不**走 lark-cli 时用）| — | 🟡 |

**⭐ openai 包的用途**（按任锐 2026-08-11 11:22 UTC 拍板 + 11:27 UTC 确认"Qwen 模型"）：
- 走 Qwen DashScope **OpenAI 兼容端点**：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- 比 `dashscope` 原生 SDK 简单（OpenAI 协议对齐生产 openclaw JSON 协议）
- 调 `qwen-plus` 模型（默认，跟生产 `miaoda/qwen-3.7-plus` **同源**）
- mac 本地：凭据 `DASHSCOPE_API_KEY` env（**不**在沙箱——任锐 mac 上 `~/.zshrc`）

### A.3 CLI 前置要求（实物核对）

| CLI | 前置 | 实物核对结果 |
|---|---|---|
| **lark-cli** | Node.js ≥ 16（engines 声明 `@larksuite/cli@1.0.85`）| ✅ Node 22.22.1 |
| **lark-cli profile** | 飞书 app `cli_aa9177c08e619cb3` OAuth 凭据 | ✅ 已配 |
| **lark-cli bot 调** | 飞书 app scopes | ✅ 6/7 scope（**`base:view:read` 缺**——见下方 🔴）|
| **git push SSH** | ed25519 密钥对（`~/.ssh/id_ed25519` mode 600）| ✅ 2026-08-11 就位 |
| **git push HTTPS** | 一次性 PAT（沙箱不缓存，OpenClaw 拒 env var 注入）| ✅ 任锐手提供 |
| **Qwen DashScope** | `DASHSCOPE_API_KEY` env | ❌ 沙箱**没**有（任锐 mac 上 `~/.zshrc` 才有）|
| **Qwen DashScope 端点** | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | 阿里云百炼官方 OpenAI 兼容端点 |

### A.4 飞书 app scope 实物

**6/7 scope 已就位**：
- `base:bitable:read` ✅
- `base:bitable:write` ✅
- `base:field:read` ✅
- `docx:doc` ✅
- `im:message` ✅
- `contact:user.id` ✅

**1 scope 缺**（🔴 不可缺）：
- `base:view:read` ❌——`lark-cli base +view-list` 实物测试返回 `99991672 access denied`
- **修复**：开发者后台申请 `https://open.feishu.cn/page/scope-apply?clientID=cli_aa9177c08e619cb3&scopes=base%3Aview%3Aread`

---

## B. 生产部署栈（技术事实记录，**不**是"罗列"为开发期依赖）

> **2026-08-11 11:30 UTC 任锐拍板**："生产部署**仍**用 OpenClaw cron + openclaw subprocess 调妙搭"——这是**生产**技术决策，**不**是"开发期"环境依赖。**记录**这段是**为了避免**未来生产部署时**再**发现"妙搭 innerapi 直调不可行"的重复工作。
>
> **！** 本地开发栈（A 段）**不**列 openclaw；**生产**部署栈（B 段）**必须**列 openclaw——**两栈分离**是技术**事实**。

### B.1 OpenClaw cron 调度

| 项 | 值 | 拍板 |
|---|---|---|
| **schedule** | `0 10-23 * * *`（hourly 10-23 整点 = 14 次/天）| v1.5 doc §1.2 |
| **timezone** | `Asia/Shanghai` | v1.5 doc §1.2 |
| **trigger.intent** | `["升级售后判责", "判责主流程", "aftersales judge decide"]` | v2.0 §10.4 |

**！** 沙箱**不**需要 systemd / crontab（OpenClaw 是内部调度）——生产部署**仍**用 OpenClaw cron（**不**用 crontab）。

### B.2 openclaw subprocess 调妙搭 innerapi（**唯一** LLM 通路）

**！** 按 TOOLS.md LRN-20260802-013 探针**实物**锁死（2026-08-02 19:09-19:25，5 模型 × 3 次 × 30k/40k 字符）：

| 调 LLM 通路 | 实物结果 |
|---|---|
| `innerapi.aiforce.cloud/sgw/model/proxy/chat/completions` | ❌ 500 "get lark userID failed" |
| `innerapi.aiforce.run/innerapi/api/v1/studio/innerapi/integration_apis/call` | ❌ 200 但 ai.chat 404 |
| miaoda 插件 8 个 apiName（image_understanding / web_search / doc_parse 等）| ❌ 无 ai.chat |
| miaoda-studio-cli 7 个命令 | ❌ 无 chat |
| **`openclaw capability model run`** | ✅ **5/5 模型 100% 成功** |

**生产 LLM 调用**（**唯一**通路）：

```python
import subprocess, json
result = subprocess.run(
    ['openclaw', 'capability', 'model', 'run',
     '--model', 'miaoda/glm-5.1',  # 4+2 降级链 #1
     '--prompt', prompt,
     '--json'],
    capture_output=True, text=True, timeout=120
)
data = json.loads(result.stdout)
text = data['outputs'][0]['text']
```

**生产 4+2 降级链**（v1.5 doc 决策 11，kimi 移出）：
- shared_chain: `miaoda/glm-5.1` → `miaoda/qwen-3.7-plus` → `miaoda/doubao-seed-2.0-pro` → `miaoda/minimax-m3`
- agent3_chain: `miaoda/doubao-seed-2.0-pro` → `miaoda/minimax-m3`

### B.3 飞书 4 env 凭据（生产）

| env 变量 | 值 | 用途 |
|---|---|---|
| `BITABLE_APP_TOKEN_BUSINESS` | `HGDzb2h7MaydFxsqlyAcCpALnB1` | 业务 base（product/store/result/ast_rules）|
| `BITABLE_APP_TOKEN_FIELDS` | `XMKUbBzycaNNN4sb3GMcu3aBnfe` | 字段说明 base |
| `BITABLE_APP_TOKEN_RULES` | `HGDzb2h7MaydFxsqlyAcCpALnB1`（= 业务 base）| 判责规则表 base |
| `PROBE_OUTPUT_DIR` | `~/.openclaw/tmp/probe-results`（默认）| 探针输出 |

---

## 总结

### 🟢 开发期栈已就位（沙箱 8 CLI + 7 必备包 = 15 项 + 1 待装 = 16 项）

**沙箱**已装齐所有 CLI + Python 包（**除** `openai` 待装），**不需要**再装。

v1.5 doc frontmatter `install: pip install pyyaml` 是**声明**，实物 `PyYAML 6.0.3` 已装（**实物**已**满足** v1.5 doc 要求）。

### 🟡 可选安装（按需）

```bash
pip install openai              # Qwen DashScope OpenAI 兼容 SDK（开发期 LLM 替代）
pip install pytest-cov          # 测试覆盖率
pip install pytest-mock         # mock 框架
pip install lark-oapi           # 飞书 SDK（不通过 lark-cli 时用）
```

### 🔴 不可缺（任锐手动）

- **飞书 app `base:view:read` scope 申请**——`lark-cli base +view-list` 实物测试 99991672 失败
  - 开发者后台：`https://open.feishu.cn/page/scope-apply?clientID=cli_aa9177c08e619cb3&scopes=base%3Aview%3Aread`
  - 申请后 lark-cli 需重新 OAuth 授权（`lark-cli auth login --profile cli_aa9177c08e619cb3`）
- **DASHSCOPE_API_KEY**（任锐 mac 上）—— 申请：`https://dashscope.console.aliyun.com/apiKey`
  - mac 上 `~/.zshrc` 加 `export DASHSCOPE_API_KEY=sk-xxx` + `source ~/.zshrc`

### 🟡 后续 Phase 1.10 任务（v1.6 doc 4 项硬约束之一）

- **frontmatter `install:` 段补全**——从 `pip install pyyaml`（1 项）升级为 8 必备包（pyyaml + jinja2 + pandas + numpy + pytest + pytest-timeout + requests + openai）
- **frontmatter `requires.bins` 段**——实物只有 `[lark-cli, python3]`，**应该**补 Node.js（lark-cli 运行时）—— **不**补 openclaw（任锐拍板本地不跑）

---

## 一键安装命令（任锐 mac 上跑）

```bash
# 1. 安装 Node.js（lark-cli 运行时，engines ≥ 16，推荐 22 LTS）
brew install node

# 2. 安装 lark-cli（npm 一行，engines ≥ 16）
npm install -g @larksuite/cli

# 3. 安装 Python 包（8 必备）
pip install pyyaml jinja2 pandas numpy pytest pytest-timeout requests openai

# 4. Python 包（3 可选，按需）
pip install pytest-cov pytest-mock
pip install lark-oapi

# 5. 设置 DASHSCOPE_API_KEY env（mac 上 ~/.zshrc）
echo 'export DASHSCOPE_API_KEY=sk-xxx' >> ~/.zshrc
source ~/.zshrc

# 6. 飞书 app scope 申请（任锐浏览器手动）
# 浏览器打开: https://open.feishu.cn/page/scope-apply?clientID=cli_aa9177c08e619cb3&scopes=base%3Aview%3Aread
# 申请后重新授权: lark-cli auth login --profile cli_aa9177c08e619cb3

# 7. 验证 CLI + Python 包
lark-cli --version              # 期望: 1.0.85+
python3 --version               # 期望: 3.9+
node --version                  # 期望: 16+ (推荐 22 LTS)
python3 -c "import yaml, jinja2, pandas, numpy, pytest, requests, openai; print('OK')"

# 8. 验证 Qwen DashScope 端点
python3 -c "
import os
from openai import OpenAI
client = OpenAI(
    api_key=os.environ['DASHSCOPE_API_KEY'],
    base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'
)
resp = client.chat.completions.create(
    model='qwen-plus',
    messages=[{'role': 'user', 'content': 'ping'}],
    max_tokens=100,
)
print(resp.choices[0].message.content)
"
```

---

## 关键版本匹配（实物）

- **lark-cli 1.0.85** ≥ 1.0.79 ✅（v1.5 doc 最低要求）
- **python3 3.10.12** ≥ 3.9 ✅（v1.5 doc 最低要求）
- **Node.js 22.22.1** ≥ 16 ✅（lark-cli engines 声明）
- **pyyaml 6.0.3** ≥ 5.1 ✅
- **pandas 2.3.3** ≥ 1.3 ✅
- **openai ≥ 1.0**（实物**未**装，待任锐 mac 装）

---

## 开发期栈 vs 生产部署栈对比

| 能力 | 开发期栈（任锐拍板）| 生产部署栈（技术事实）|
|---|---|---|
| **触发方式** | 手跑 + pytest | OpenClaw cron hourly 10-23 Asia/Shanghai |
| **LLM 调用** | `openai` SDK 调 Qwen DashScope（`qwen-plus`）| `openclaw capability model run` subprocess 调妙搭（4+2 降级链）|
| **LLM 模型** | `qwen-plus`（本地 mac）| `miaoda/glm-5.1` → `miaoda/qwen-3.7-plus` → `miaoda/doubao-seed-2.0-pro` → `miaoda/minimax-m3` |
| **飞书调用** | lark-cli | lark-cli（**同样**）|
| **凭证** | mac `DASHSCOPE_API_KEY` env + 沙箱 4 env | 沙箱 4 env（**同样**）|
| **隔离** | 无（单进程手跑）| OpenClaw isolated session |
| **配置** | config.yaml 直接读 | config.yaml 直接读（**同样**）|
| **数据落盘** | probes/*.json | probes/*.json（**同样**）|
| **.gitignore** | probes/ + .env | probes/ + .env（**同样**）|
| **scripts/llm.py** | QwenDashScopeClient | OpenClawClient（**共用** `LLMClient` 抽象基类）|

**！** 关键：**一份代码 + 双栈 LLM 后端**——`scripts/llm.py` 写 `LLMClient` 抽象基类 + `get_client()` 工厂方法（按 env 自动选本地 Qwen / 生产 openclaw）。

---

## 相关文档

- **SKILL.md**（SKILL 主体）—— frontmatter compatibility / requires.bins / requires.env / install 段
- **config.yaml**（业务参数）—— 11 块顶层 key（task_table / dimensions / ast_rules / magic_numbers / llm / cron / failure / state_machine / notify / lock / preflight）+ 9 magic number
- **references/architecture.md**（架构）—— 5 状态机 / 9 类失败 / 抢锁机制
- **references/implementation_plan.md**（实施计划）—— T2 5 模块 + T3 3 AGENT + T4 端到端
- **TOOLS.md "SKILL 调 LLM 原则"**（探针结论）—— LRN-20260802-013 妙搭 3 种直调端点全失败，openclaw subprocess 是**唯一**通路
- **飞书 v1.5 doc**（完整设计方案）—— `https://bggc.feishu.cn/docx/Z5yqdzqpuowhQCx5bUJcpxIxnac`
- **升级售后主流程 SKILL 开发规划.md**（v2 6 Phase 规划）—— `~/workspace/agent/升级售后处理/`
