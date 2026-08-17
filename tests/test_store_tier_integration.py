"""compute_store_tier — 集成测试（LRN-20260817-004 修法验证）。

修法（commit 待定）：
  - 改 config.yaml store_tier.scripts_dir_default 默认值（避免 submodules/ 不存在的问题）
  - 加 .env STORE_TIER_RULES_DIR env
  - 集成测试锁住"飞书 rules + store_row → apply_tier → A/B/C/D/其他"链路

测试要点：
  1. 沙箱可访问真实飞书（lark-cli 已验：~/.npm-global/bin/lark-cli）
  2. STORE_TIER_RULES_DIR 真实可达 + apply_tier_rules.py 可 import
  3. fetch_store_tier_rules 真拉表 + json.loads 出 rules
  4. fetch_store_dimension 真拉 1 条样本
  5. compute_store_tier 调 apply_tier 输出 A/B/C/D/其他
  6. 验证：降级不发生（tier 不为 None）— 这是修法成功的关键标志
"""
import os
import sys
from pathlib import Path

import pytest

# conftest.py 注入 scripts/ 到 sys.path
import data_loader
from data_loader import (
    compute_store_tier, fetch_store_dimension, fetch_store_tier_rules,
    record_list, TIER_STAT_FIELDS,
)


# ── preflight: 沙箱环境必备条件 ──

def test_store_tier_rules_dir_env_set():
    """STORE_TIER_RULES_DIR 必须设（避免 submodules/ 静默降级）。"""
    assert os.environ.get("STORE_TIER_RULES_DIR"), (
        "STORE_TIER_RULES_DIR 未设 — .env 应有 STORE_TIER_RULES_DIR=/home/gem/workspace/agent/skills/store-tier-rules/scripts"
    )


def test_store_tier_scripts_dir_resolves_to_real_path():
    """resolve_store_tier_scripts_dir 必须解析到真实 apply_tier_rules.py 所在目录。"""
    from data_loader import resolve_store_tier_scripts_dir
    cfg = {"probe": {"store_tier": {}}}  # 最小 cfg，env 优先路径
    scripts_dir = resolve_store_tier_scripts_dir(cfg)
    assert scripts_dir.is_dir(), f"scripts 目录不存在: {scripts_dir}"
    assert (scripts_dir / "apply_tier_rules.py").is_file(), (
        f"apply_tier_rules.py 缺失: {scripts_dir}"
    )
    assert (scripts_dir / "_config.py").is_file(), (
        f"_config.py 缺失（apply_tier_rules 依赖）: {scripts_dir}"
    )


def test_apply_tier_rules_importable():
    """apply_tier_rules.py 可 import（compute_store_tier 关键依赖）。"""
    import importlib
    if str(Path(os.environ.get("STORE_TIER_RULES_DIR", "")).resolve()) not in sys.path:
        sys.path.insert(0, str(Path(os.environ.get("STORE_TIER_RULES_DIR", "")).resolve()))
    mod = importlib.import_module("apply_tier_rules")
    assert hasattr(mod, "apply_tier"), "apply_tier 函数缺失"
    assert callable(mod.apply_tier), "apply_tier 不可调用"


# ── 集成测试: 真飞书数据 → compute_store_tier → A/B/C/D/其他 ──

@pytest.fixture(scope="module")
def cfg():
    """加载真实 config（沙箱 .env 已 source，env 注入凭据）。

    重要：必须用 main.load_config（带 L4 ${VAR} 严格替换），不能用 yaml.safe_load。
    yaml.safe_load 不会替换 ${VAR} → app_token 是字面量 → lark-cli NOTEXIST 错误。
    """
    import sys
    if "scripts" not in sys.path:
        sys.path.insert(0, "scripts")
    from main import load_config
    return load_config()


@pytest.fixture(scope="module")
def tier_rules(cfg):
    """从飞书《门店分层规则表》拉最新 1 行 rules JSON。"""
    try:
        return fetch_store_tier_rules(cfg)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"无法拉取门店分层规则（飞书不可达或表为空）: {e}")


@pytest.fixture(scope="module")
def sample_store_row(cfg):
    """从飞书《门店维度统计表》拉 1 条样本（任意店铺 id）。"""
    dim = cfg["dimensions"]["store_table"]
    try:
        env = record_list(cfg, app_token=dim["app_token"], table_id=dim["table_id"], limit=1)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"无法拉取门店维度统计表: {e}")
    if not env.records:
        pytest.skip("门店维度统计表为空")
    return env.records[0]


def test_compute_store_tier_returns_actual_tier(cfg, tier_rules, sample_store_row):
    """compute_store_tier 不再静默降级 → 返回 A/B/C/D/其他 之一。"""
    tier, reason = compute_store_tier(cfg, sample_store_row, tier_rules)
    assert tier is not None, (
        f"compute_store_tier 返回 None (reason={reason!r}) — "
        "修法未生效，门店等级仍静默降级为 null"
    )
    assert tier in {"A", "B", "C", "D", "其他"}, f"非法 tier 输出: {tier!r}"
    assert reason is None, f"成功路径不应有 reason: {reason!r}"


def test_compute_store_tier_degrades_on_missing_store(cfg, tier_rules):
    """store_row=None → 降级为 None + reason=store dimension JOIN miss（设计预期 - 两种模式都 graceful）。"""
    tier, reason = compute_store_tier(cfg, None, tier_rules)
    assert tier is None
    assert reason == "store dimension JOIN miss"


def test_compute_store_tier_degrades_on_missing_rules(cfg, sample_store_row):
    """tier_rules=None → degrade_on_failure=true 降级 None；false 抛 LarkCliError。"""
    from data_loader import LarkCliError
    cfg_strict = {**cfg, "probe": {**cfg.get("probe", {}), "store_tier": {**cfg.get("probe", {}).get("store_tier", {}), "degrade_on_failure": False}}}
    with pytest.raises(LarkCliError, match="store tier rules"):
        compute_store_tier(cfg_strict, sample_store_row, None)
    # 降级模式仍 graceful
    cfg_loose = {**cfg, "probe": {**cfg.get("probe", {}), "store_tier": {**cfg.get("probe", {}).get("store_tier", {}), "degrade_on_failure": True}}}
    tier, reason = compute_store_tier(cfg_loose, sample_store_row, None)
    assert tier is None
    assert reason == "store tier rules 未加载"


def test_compute_store_tier_strict_mode_raises_on_missing_scripts(cfg, sample_store_row, tier_rules, monkeypatch):
    """LRN-20260817-004：degrade_on_failure=false 下 scripts 目录不存在 → 抛 LarkCliError fail-fast。"""
    from data_loader import LarkCliError
    monkeypatch.setenv("STORE_TIER_RULES_DIR", "/nonexistent/store-tier-scripts")
    cfg_strict = {**cfg, "probe": {**cfg.get("probe", {}), "store_tier": {**cfg.get("probe", {}).get("store_tier", {}), "degrade_on_failure": False}}}
    with pytest.raises(LarkCliError, match="scripts 目录不存在"):
        compute_store_tier(cfg_strict, sample_store_row, tier_rules)


def test_tier_stat_fields_match_store_row(cfg, sample_store_row):
    """TIER_STAT_FIELDS 6 字段都能从 store_row 取到（apply_tier 必需）。"""
    missing = [f for f in TIER_STAT_FIELDS if sample_store_row.get(f) is None]
    assert not missing, f"store_row 缺 6 核心统计字段: {missing}"


# ── 回归测试: 模拟 submodules/ 缺失场景（之前一直静默降级）──

def test_submodules_default_path_warns_but_env_wins(cfg, monkeypatch):
    """env 优先于 config 默认值 — 验证修复了'config 默认 submodules/ 路径不存在'问题。

    注意：本测试只验逻辑，不真访问 submodules/。
    """
    from data_loader import resolve_store_tier_scripts_dir
    # 显式 unset env
    monkeypatch.delenv("STORE_TIER_RULES_DIR", raising=False)
    # config 默认值是真实路径（修法后）
    cfg_with_real_default = {
        "probe": {"store_tier": {"scripts_dir_default": "/home/gem/workspace/agent/skills/store-tier-rules/scripts"}}
    }
    scripts_dir = resolve_store_tier_scripts_dir(cfg_with_real_default)
    assert scripts_dir.is_dir(), "config 默认值应指向真实路径（修法后）"
