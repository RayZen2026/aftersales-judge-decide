"""compute_store_tier 降级路径（apply_tier 本身不测——store-tier-rules SKILL 的职责）。"""
import data_loader as dl


# LRN-20260817-004 修法后：scripts_dir_default 指向独立 skill 路径，不依赖 submodules/
CFG = {"probe": {"store_tier": {"scripts_dir_default": "/home/gem/workspace/agent/skills/store-tier-rules/scripts"}}}


def test_store_row_none_degrades():
    tier, reason = dl.compute_store_tier(CFG, None, {"config_snapshot": {}})
    assert tier is None
    assert "JOIN miss" in reason


def test_rules_none_degrades():
    tier, reason = dl.compute_store_tier(CFG, {"店铺id": 1}, None)
    assert tier is None
    assert "未加载" in reason


def test_scripts_dir_missing_degrades(monkeypatch):
    monkeypatch.setenv("STORE_TIER_RULES_DIR", "/nonexistent/store-tier-scripts")
    tier, reason = dl.compute_store_tier(CFG, {"店铺id": 1}, {"config_snapshot": {}})
    assert tier is None
    assert "不存在" in reason


def test_resolve_scripts_dir_env_override(monkeypatch):
    monkeypatch.setenv("STORE_TIER_RULES_DIR", "/custom/deploy/path")
    assert str(dl.resolve_store_tier_scripts_dir(CFG)) == "/custom/deploy/path"


def test_resolve_scripts_dir_default():
    # LRN-20260817-004: 默认值已修为独立 skill 真实路径（不再依赖 submodules/）
    monkeypatch_none = dl.resolve_store_tier_scripts_dir(CFG)
    assert str(monkeypatch_none).endswith("/home/gem/workspace/agent/skills/store-tier-rules/scripts")
