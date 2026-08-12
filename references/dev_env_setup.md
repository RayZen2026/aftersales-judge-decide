# 本地开发环境安装指南（project-local，零全局污染）

> **本文件范围**：`aftersales-judge-decide` 在开发机（Linux / mac）上的开发环境**安装 + 验证**步骤。
> **上游依据**：确认 2026-08-11 拍板「本地 CLI-only」。生产部署栈（OpenClaw cron + openclaw subprocess 调妙搭）**不**在本文件范围。
> **基线**：2026-08-11 开发机实物核对（pyenv 3.10.20 / 3.12.13 / 3.14.4，nvm v24.14.1，git 2.43，OpenSSH 9.6p1，make 4.3）。

---

## 0. 三条核心原则

1. **project-local 管理**
   - Python：`python -m venv` 建项目内 `.venv/`（即需求里说的 pyvenv）；解释器版本经 **pyenv** 选定（开发机已有，不新装）
   - Node.js：**nvm** + 项目内 `.nvmrc` 锁版本；`lark-cli` 走 **npm 本地安装**（`node_modules/.bin/`），**禁止** `npm install -g`
   - 凭据：项目内 `.env`（已 gitignore），**不写** `~/.zshrc` / `~/.bashrc`
   - 探针输出：`PROBE_OUTPUT_DIR=./probes`（项目内，已 gitignore），**不用** `~/.openclaw/tmp/`
2. **零全局污染**：不装全局包、不改 shell rc、不动系统 python / node。
3. **CLI-only**：**不**装 openclaw CLI / OpenClaw Gateway / OpenClaw cron / crontab / systemd timer（确认 2026-08-11 拍板，本地手跑 + pytest）。

---

## 1. 开发机现状 vs 需求（实物核对结论）

| 项 | 需求 | 开发机实物 | 结论 / 动作 |
|---|---|---|---|
| python3 | ≥ 3.9，推荐 3.11+ | pyenv：3.10.20 / **3.12.13** / 3.14.4（默认） | 🟡 用 **3.12.13** 建 `.venv`（**不**用 3.14，原因见 §3.1）|
| Node.js | ≥ 16（lark-cli engines），推荐 22 LTS | nvm 仅 v24.14.1 | 🟡 `nvm install 22` + `.nvmrc` |
| npm | ≥ 8 | 11.11.0 | ✅ |
| git | ≥ 2.25 | 2.43.0 | ✅ 系统级，无需动作 |
| ssh | ≥ 7 | OpenSSH 9.6p1 | ✅ 系统级，无需动作 |
| make（可选）| ≥ 3.8 | 4.3 | ✅ |
| **lark-cli** | ≥ 1.0.79，推荐 1.0.85+ | ❌ **未安装** | 🔴 npm **本地**安装（§2.3）|
| pip | ≥ 21 | venv 自带（26.x） | ✅ |
| DASHSCOPE_API_KEY | 必需（本地 LLM 通路） | ❌ 未配置 | 🔴 项目内 `.env`（§4）|

---

## 2. Node.js：nvm + npm 本地安装

### 2.1 安装 Node 22 LTS（nvm 管理）

```bash
cd aftersales-judge-decide
echo "22" > .nvmrc          # 项目级版本锁（nvm 标准做法）
nvm install 22              # 装进 ~/.nvm/versions/node/v22.x，不碰系统
nvm use                     # 读 .nvmrc，切到 22
node --version              # 期望 v22.x
```

> 开发机的 node 本来就由 nvm 管理（`.bashrc` 里是 `NVM_DIR` hook），此步只是**增装** 22 并按项目锁定，不影响其他项目（其他项目没有 `.nvmrc` 时仍走默认版本）。

### 2.2 package.json（锁 lark-cli 版本）

```bash
npm init -y                 # 若已有 package.json 跳过
npm install --save-dev @larksuite/cli
npx lark-cli --version      # 期望 ≥ 1.0.85
```

### 2.3 使用方式（替代全局命令）

```bash
npx lark-cli base +view-list ...          # 方式 1：npx（推荐）
./node_modules/.bin/lark-cli ...          # 方式 2：直接路径
```

> **⚠️ 配套动作**：现有 `.gitignore` **缺** `node_modules/` 一行，npm 本地安装后必须补上（否则 git status 污染）。

---

## 3. Python：pyenv 选版本 + venv 项目隔离

### 3.1 为什么用 3.12.13 而不是默认的 3.14.4

- 此前锁定的实物版本 **pandas 2.3.3 / numpy 2.2.6** 官方 wheel 只到 **cp313**；Python 3.14 上 pip 会退回源码编译，大概率失败。
- 3.12.13 满足 v1.5 doc「Python 3.9+，推荐 3.11+」，且开发机 pyenv **已有**，零新装。
- （可选）项目根放 `.python-version`（内容 `3.12.13`），pyenv 进目录自动切换，避免误用 3.14。

### 3.2 建 venv + 装包

```bash
cd aftersales-judge-decide
PYENV_VERSION=3.12.13 python -m venv .venv     # 项目内 .venv/（已 gitignore）
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3.3 requirements.txt（8 必备，版本下限 = 此前实物版本）

```text
pyyaml>=5.1,<7          # 实物 6.0.3 — config.yaml 加载
jinja2>=3.0             # 实物 3.1.6 — agent{1,2,3}_prompt_template.j2 渲染
pandas>=1.3,<3          # 实物 2.3.3 — 任务表 × 6 维度表 JOIN
numpy>=1.20             # 实物 2.2.6 — 分位数（store-tier-rules 复用）
pytest>=7.0             # 实物 9.0.2 — tests/ 单元测试
pytest-timeout>=2.0     # 实物 2.4.0 — probe_llm.py 超时控制
requests>=2.25          # 实物 2.32.5 — HTTP 客户端
openai>=1.0             # 待装 — Qwen DashScope OpenAI 兼容端点（本地 LLM 通路）
```

可选（按需，不进 requirements.txt）：

```bash
pip install pytest-cov pytest-mock    # 覆盖率 / mock
pip install lark-oapi                 # 不走 lark-cli 时的飞书 SDK（本期不需要）
```

---

## 4. 凭据 / 环境变量：项目内 `.env`（不写 shell rc）

### 4.1 `.env.example` 模板 → 复制后填值

```bash
cp .env.example .env      # .env 已在 .gitignore，绝不入库
```

`.env.example` 内容：

```dotenv
# ── LLM：Qwen DashScope OpenAI 兼容端点（本地替代妙搭）──
# 申请: https://dashscope.console.aliyun.com/apiKey
DASHSCOPE_API_KEY=sk-xxx

# ── 飞书 Bitable app_token ──
BITABLE_APP_TOKEN_BUSINESS=HGDzb2h7MaydFxsqlyAcCpALnB1
BITABLE_APP_TOKEN_FIELDS=XMKUbBzycaNNN4sb3GMcu3aBnfe
BITABLE_APP_TOKEN_RULES=HGDzb2h7MaydFxsqlyAcCpALnB1

# ── 探针输出（project-local；不用生产默认的 ~/.openclaw/tmp/probe-results）──
PROBE_OUTPUT_DIR=./probes
```

### 4.2 加载方式（每次开新终端）

```bash
cd aftersales-judge-decide
source .venv/bin/activate
set -a && source .env && set +a     # 导出 .env 全部变量
```

> 不引入 direnv / python-dotenv 等新依赖（不在批准的依赖清单内）；`set -a` 是纯 shell 方案。config.yaml 走 `${VAR}` 严格替换（CLAUDE.md §6.4），env 缺失启动即失败，正好兜底。

---

## 5. 飞书 lark-cli 授权（一次性，用户级例外项）

OAuth profile 按 lark-cli 自身设计存放在**用户级**目录，无法收进项目目录——这是本方案**仅有的两个**用户级例外之一（另一个是 `~/.ssh/` 密钥）。

**2026-08-11 实物核对：开发机 lark-cli 未初始化**（`npx lark-cli auth status` → `not configured`）。首次配置流程（需确认浏览器配合）：

```bash
# 1) 初始化 + device flow 授权（阻塞并输出验证 URL，浏览器打开完成）
npx lark-cli config init --new

# 2) 授权后核对状态 / scope
npx lark-cli auth status
npx lark-cli auth check          # 检查 token 是否有所需 scope

# 3) scope 补全后如需重新授权
npx lark-cli auth login --profile cli_aa9177c08e619cb3
```

### 🔴 前置：`base:view:read` scope 尚缺（确认手动）

- 实物测试 `lark-cli base +view-list` 返回 `99991672 access denied`
- 浏览器申请：`https://open.feishu.cn/page/scope-apply?clientID=cli_aa9177c08e619cb3&scopes=base%3Aview%3Aread`
- 审批通过后**重新**执行上面的 `auth login`

---

## 6. 验证清单（全部通过 = 环境就绪）

```bash
source .venv/bin/activate && set -a && source .env && set +a

nvm current                 # 期望 v22.x
node --version              # 期望 v22.x
npx lark-cli --version      # 期望 ≥ 1.0.85
python --version            # 期望 3.12.13（venv 内）
python -c "import yaml, jinja2, pandas, numpy, pytest, requests, openai; print('OK')"
pytest --version            # 期望 ≥ 7.0

# DashScope 连通性（LLM 通路）
python - <<'EOF'
import os
from openai import OpenAI
client = OpenAI(
    api_key=os.environ['DASHSCOPE_API_KEY'],
    base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
)
resp = client.chat.completions.create(
    model='qwen-plus-latest',    # 本账号只有 latest 别名权限（稳定版 qwen-plus 403）
    messages=[{'role': 'user', 'content': 'ping'}],
    max_tokens=100,
)
print('DashScope OK:', resp.choices[0].message.content)
EOF

# 飞书连通性（base:view:read scope 批准 + 重新授权后）
npx lark-cli base +view-list ...    # 不再返回 99991672 即通过
```

---

## 7. 明确不装

| 项 | 不装原因 |
|---|---|
| openclaw CLI / OpenClaw Gateway / OpenClaw cron | 确认 2026-08-11 拍板：本地 CLI-only，生产才用 |
| crontab / systemd timer / launchd | 开发期手跑 + pytest，不需要调度 |
| dashscope 原生 SDK | 用 `openai` SDK 走 OpenAI 兼容端点即可（对齐生产 JSON 协议）|
| miaoda-studio-cli / 妙搭 innerapi 直调 | LRN-20260802-013 探针锁死：3 种直调端点全失败 |

---

## 8. 配套文件清单（本指南落地需要新增/修改）

| 文件 | 动作 | 内容 |
|---|---|---|
| `.nvmrc` | 新增 | `22` |
| `package.json` | 新增 | devDependency `@larksuite/cli` ≥ 1.0.85 |
| `requirements.txt` | 新增 | §3.3 的 8 必备包 |
| `.env.example` | 新增 | §4.1 模板（无真凭据，可入库）|
| `.python-version`（可选）| 新增 | `3.12.13` |
| `.gitignore` | **修改** | 补 `node_modules/` 一行 |
| `.env` | 本地生成 | **不入库**（已 gitignore）|

---

## 9. 遗留问题（需确认拍板）

1. ~~本目录当前不是 git 仓库~~ **已解决**（2026-08-11）：远端 `git@github.com:RayZen2026/aftersales-judge-decide.git`，本地 Phase 0 交付已 push（含远端 Phase 0 历史合并）。**注意**：本机 github.com:22 被干扰，git SSH 走项目级 `core.sshCommand`（`ssh.github.com:443` + `~/.ssh/id_ed25519_github`，RayZen2026 账号公钥 weersknape@gmail.com）。
2. ~~`DASHSCOPE_API_KEY`~~ **已闭环**（2026-08-11）：真 key + `qwen-plus-latest` 实测 ping 通过。注意：本账号对稳定版 `qwen-plus` / turbo / flash / max 均 403 `Model.AccessDenied`，只有 **latest 别名**可用——开发期 LLM 模型名一律用 `qwen-plus-latest`（scripts/llm.py 本地后端按此配置）。
3. 飞书两项手工前置：① 开发机 lark-cli **未初始化**（`config init --new` device flow 授权，§5）；② `base:view:read` scope 审批（§5 🔴）。

---

## 相关文档

- `trash/env_requirements.md` —— 依赖清单初版（开发栈/生产栈/版本核对），已归档不维护，git 历史可恢复
- `references/architecture.md` —— 5 状态机 / 9 类失败 / 抢锁机制
- `references/implementation_plan.md` —— 6 Phase 开发节奏
- `CLAUDE.md` —— 项目宪法（§6.3 push 流程 / §6.4 config.yaml 严格替换）
