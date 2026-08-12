"""feishu_notify.py — 24h 去重 / 双通道 / 发送门。"""
from datetime import datetime, timedelta, timezone

import pytest

import feishu_notify as fn

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 12, 16, 0, 0, tzinfo=CST)

CFG = {
    "notify": {
        "channels": [
            {"type": "feishu_dm", "target": "ou_TEST"},
            {"type": "memory_file", "path": "memory/notify_<date>.md"},
        ],
        "dedup": {"window_hours": 24, "key": "upgrade_order_id"},
    }
}


# ── 24h 去重 ──

def test_dedup_first_time_notifies(tmp_path):
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    assert d.should_notify("UAS1", "llm_5xx", NOW) is True


def test_dedup_within_window_skips(tmp_path):
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    assert d.should_notify("UAS1", "llm_5xx", NOW) is True
    assert d.should_notify("UAS1", "llm_5xx", NOW + timedelta(hours=23)) is False


def test_dedup_after_window_notifies(tmp_path):
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    assert d.should_notify("UAS1", "llm_5xx", NOW) is True
    assert d.should_notify("UAS1", "llm_5xx", NOW + timedelta(hours=25)) is True


def test_dedup_different_exc_type_independent(tmp_path):
    # 同单号不同异常类型 = 独立去重键
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    assert d.should_notify("UAS1", "llm_5xx", NOW) is True
    assert d.should_notify("UAS1", "rule_conflict", NOW) is True


def test_dedup_state_persists(tmp_path):
    d1 = fn.NotifyDedup(tmp_path, window_hours=24)
    assert d1.should_notify("UAS1", "llm_5xx", NOW) is True
    # 新实例加载同一状态文件
    d2 = fn.NotifyDedup(tmp_path, window_hours=24)
    assert d2.should_notify("UAS1", "llm_5xx", NOW + timedelta(hours=1)) is False


def test_dedup_corrupt_state_resets(tmp_path):
    (tmp_path / fn.DEDUP_STATE_FILE).write_text("{corrupt", encoding="utf-8")
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    assert d.should_notify("UAS1", "llm_5xx", NOW) is True


def test_dedup_cleanup(tmp_path):
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    d.should_notify("UAS1", "a", NOW - timedelta(hours=30))  # 超窗
    d.should_notify("UAS2", "b", NOW)                        # 窗口内
    assert d.cleanup(NOW) == 1
    assert len(d.state) == 1


# ── 消息构造 ──

def test_render_message():
    msg = fn.render_message("UAS1", "llm_5xx", "降级链全失败", NOW)
    assert "UAS1" in msg and "llm_5xx" in msg and "降级链全失败" in msg
    assert "2026-08-12" in msg


# ── 发送门 ──

def test_send_gate_closed_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("FEISHU_NOTIFY_ENABLED", raising=False)
    result = fn.send_feishu_dm(CFG, "test")
    assert result == {"skipped": True}


def test_send_gate_open_requires_target(monkeypatch):
    monkeypatch.setenv("FEISHU_NOTIFY_ENABLED", "1")
    with pytest.raises(ValueError, match="feishu_dm target"):
        fn.send_feishu_dm({"notify": {"channels": []}}, "test")


# ── memory 通道 ──

def test_append_memory_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fn, "BASE_DIR", tmp_path)
    path = fn.append_memory_file(CFG, "一条记录", NOW)
    assert path == tmp_path / "memory" / "notify_2026-08-12.md"
    assert "一条记录" in path.read_text(encoding="utf-8")
    # 追加不覆盖
    fn.append_memory_file(CFG, "第二条", NOW)
    assert "第二条" in path.read_text(encoding="utf-8")


# ── notify 编排 ──

def test_notify_dedup_skip(tmp_path):
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    d.should_notify("UAS1", "llm_5xx", NOW)
    r = fn.notify(CFG, d, "UAS1", "llm_5xx", "x", NOW + timedelta(minutes=1))
    assert r["notified"] is False and "去重" in r["reason"]


def test_notify_dual_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(fn, "BASE_DIR", tmp_path)
    monkeypatch.delenv("FEISHU_NOTIFY_ENABLED", raising=False)  # dm 跳过，memory 仍写
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    r = fn.notify(CFG, d, "UAS1", "rule_conflict", "规则冲突", NOW)
    assert r["notified"] is True
    assert r["dm"] == {"skipped": True}
    assert (tmp_path / "memory" / "notify_2026-08-12.md").exists()


def test_notify_dm_failure_degrades_to_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(fn, "BASE_DIR", tmp_path)
    monkeypatch.setenv("FEISHU_NOTIFY_ENABLED", "1")

    def boom(cfg, text, idempotency_key=None):
        raise RuntimeError("飞书 API 挂了")

    monkeypatch.setattr(fn, "send_feishu_dm", boom)
    d = fn.NotifyDedup(tmp_path, window_hours=24)
    r = fn.notify(CFG, d, "UAS1", "llm_5xx", "x", NOW)
    # 飞书失败不阻断 memory 通道
    assert r["notified"] is True
    assert "error" in r["dm"]
    assert (tmp_path / "memory" / "notify_2026-08-12.md").exists()


def test_dedup_default_state_dir_is_state_not_memory(tmp_path, monkeypatch):
    # 去重状态在 state/，不进 memory 通道（防污染 OpenClaw memory 记录）
    monkeypatch.setattr(fn, "BASE_DIR", tmp_path)
    d = fn.NotifyDedup()
    assert d.state_path == tmp_path / "state" / fn.DEDUP_STATE_FILE
