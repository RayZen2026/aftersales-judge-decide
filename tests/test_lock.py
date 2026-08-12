"""lock.py — 抢锁判定 / stale 兜底 / 写入载荷。"""
from datetime import datetime, timedelta, timezone

import pytest

import lock

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 12, 16, 0, 0, tzinfo=CST)
STALE_MIN = 5


# ── parse_dt ──

def test_parse_iso_cst():
    dt = lock.parse_dt("2026-08-12T15:00:00.000+08:00")
    assert dt == datetime(2026, 8, 12, 15, 0, tzinfo=CST)


def test_parse_utc_z():
    dt = lock.parse_dt("2026-08-12T07:00:00Z")
    assert dt == datetime(2026, 8, 12, 15, 0, tzinfo=CST)


def test_parse_epoch_ms():
    ts = int(datetime(2026, 8, 12, 15, 0, tzinfo=CST).timestamp() * 1000)
    assert lock.parse_dt(ts) == datetime(2026, 8, 12, 15, 0, tzinfo=CST)


def test_parse_invalid():
    assert lock.parse_dt(None) is None
    assert lock.parse_dt("") is None
    assert lock.parse_dt("garbage") is None


# ── is_stale ──

def test_is_stale_boundary():
    fresh = (NOW - timedelta(minutes=4)).isoformat()
    stale = (NOW - timedelta(minutes=6)).isoformat()
    assert lock.is_stale(fresh, NOW, STALE_MIN) is False
    assert lock.is_stale(stale, NOW, STALE_MIN) is True


def test_is_stale_unparseable_defaults_stale():
    # 宁可重抢，不可漏放
    assert lock.is_stale(None, NOW, STALE_MIN) is True
    assert lock.is_stale("garbage", NOW, STALE_MIN) is True


# ── check_lockable 矩阵 ──

def test_pending_and_failed_acquirable():
    for state in ("pending", "failed"):
        c = lock.check_lockable(state, None, NOW, STALE_MIN)
        assert c.acquirable and not c.stale_reclaim


def test_processing_fresh_not_acquirable():
    fresh = (NOW - timedelta(minutes=1)).isoformat()
    c = lock.check_lockable("processing", fresh, NOW, STALE_MIN)
    assert not c.acquirable and not c.stale_reclaim


def test_processing_stale_reclaim():
    stale = (NOW - timedelta(minutes=10)).isoformat()
    c = lock.check_lockable("processing", stale, NOW, STALE_MIN)
    assert c.acquirable and c.stale_reclaim


@pytest.mark.parametrize("state", ["completed", "manual_review"])
def test_final_states_not_acquirable(state):
    c = lock.check_lockable(state, None, NOW, STALE_MIN)
    assert not c.acquirable


# ── 写入载荷 ──

def test_acquire_fields():
    assert lock.acquire_fields() == {"处理状态": "已处理-处理中"}


@pytest.mark.parametrize("state,value", [
    ("completed", "已处理-成功"),
    ("failed", "已处理-失败"),
    ("manual_review", "已处理-需人工"),
])
def test_release_fields(state, value):
    assert lock.release_fields(state) == {"处理状态": value}


def test_release_fields_illegal_state():
    with pytest.raises(ValueError, match="释放目标状态非法"):
        lock.release_fields("pending")


def test_stale_filter_threshold():
    assert lock.stale_filter_threshold(NOW, STALE_MIN) == NOW - timedelta(minutes=5)
