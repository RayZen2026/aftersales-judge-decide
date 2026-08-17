"""data_loader.lark_cli_bin — 路径解析优先级（LRN-20260817-002 修法）。

修法后优先级：
  1. LARK_CLI_BIN env（部署覆盖 / CI 特殊路径）
  2. shutil.which('lark-cli')（沙箱 npm-global / 系统包）
  3. <BASE>/node_modules/.bin/lark-cli（项目自带依赖，向后兼容）

测试要点：
  - 每个分支在干净 env 下独立验证
  - 优先级严格：高优先级一定胜出，不受低优先级存在性影响
  - fallback 在前两者都没有时返回 SKILL 本地路径
"""
import os
import sys
from pathlib import Path
from unittest import mock

# conftest 已注入 scripts/ 到 sys.path
import data_loader


# ── 1. LARK_CLI_BIN env 优先级最高 ──

def test_env_bin_wins_over_which(monkeypatch, tmp_path):
    """LARK_CLI_BIN env 存在时直接返回，不查 which / 本地路径。"""
    monkeypatch.setenv("LARK_CLI_BIN", "/custom/path/to/lark-cli")
    # which 命中一个不同路径，应当被 env 盖掉
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/lark-cli")
    # 即使本地 node_modules 存在也应被盖掉
    fake_local = tmp_path / "node_modules" / ".bin" / "lark-cli"
    fake_local.parent.mkdir(parents=True)
    fake_local.touch()
    monkeypatch.setattr(data_loader, "BASE_DIR", tmp_path)

    assert data_loader.lark_cli_bin({}) == "/custom/path/to/lark-cli"


def test_env_bin_wins_over_no_which(monkeypatch, tmp_path):
    """LARK_CLI_BIN 存在 + which 找不到 → 还是 env 赢。"""
    monkeypatch.setenv("LARK_CLI_BIN", "/opt/lark-cli")
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(data_loader, "BASE_DIR", tmp_path)

    assert data_loader.lark_cli_bin({}) == "/opt/lark-cli"


# ── 2. which 命中时返回 PATH 路径（沙箱 npm-global 场景）──

def test_which_wins_over_local(monkeypatch, tmp_path):
    """LARK_CLI_BIN 没设 + which 命中 + 本地 node_modules 也存在 → which 赢。"""
    monkeypatch.delenv("LARK_CLI_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda x: "/home/gem/.npm-global/bin/lark-cli")
    fake_local = tmp_path / "node_modules" / ".bin" / "lark-cli"
    fake_local.parent.mkdir(parents=True)
    fake_local.touch()
    monkeypatch.setattr(data_loader, "BASE_DIR", tmp_path)

    assert data_loader.lark_cli_bin({}) == "/home/gem/.npm-global/bin/lark-cli"


def test_which_returns_none_falls_back_to_local(monkeypatch, tmp_path):
    """which 找不到 → 返回 BASE/node_modules/.bin/lark-cli。"""
    monkeypatch.delenv("LARK_CLI_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(data_loader, "BASE_DIR", tmp_path)

    expected = str(tmp_path / "node_modules" / ".bin" / "lark-cli")
    assert data_loader.lark_cli_bin({}) == expected


# ── 3. fallback（项目自带）保持向后兼容 ──

def test_fallback_returns_skill_local_path(monkeypatch, tmp_path):
    """env + which 都无 → 返回 SKILL 本地 node_modules 路径。"""
    monkeypatch.delenv("LARK_CLI_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(data_loader, "BASE_DIR", tmp_path)

    result = data_loader.lark_cli_bin({})
    assert result == str(tmp_path / "node_modules" / ".bin" / "lark-cli")


# ── 4. cfg 入参不影响路径解析（保留兼容，未来可能基于 cfg 切换）──

def test_cfg_arg_accepted_but_ignored(monkeypatch, tmp_path):
    """当前实现 cfg 不参与解析，但接口保留（未来可能用 cfg 切 profile）。"""
    monkeypatch.delenv("LARK_CLI_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr(data_loader, "BASE_DIR", tmp_path)

    # cfg 是空 dict / None / 任意值都不应抛错
    assert data_loader.lark_cli_bin({}) is not None
    assert data_loader.lark_cli_bin(None) is not None
    assert data_loader.lark_cli_bin({"some_key": "value"}) is not None


# ── 5. 沙箱实物（integration 风格）──

def test_real_sandbox_resolves_to_npm_global(monkeypatch):
    """当前沙箱全局 lark-cli 在 npm-global：未设 env 时应解析到该路径。

    跳过条件：沙箱没装 lark-cli（不常见，LRN-20260817-002 记录的沙箱环境）。
    """
    monkeypatch.delenv("LARK_CLI_BIN", raising=False)
    # 真实 which（不 mock）
    import shutil as real_shutil
    real_path = real_shutil.which("lark-cli")
    if not real_path:
        pytest.skip("沙箱无全局 lark-cli，跳过实物测试")
    # 沙箱实物：应解析到 which 命中的真实路径
    assert data_loader.lark_cli_bin({}) == real_path
    # 应包含 'lark-cli' 文件名
    assert Path(data_loader.lark_cli_bin({})).name == "lark-cli"
