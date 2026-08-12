"""state_machine.py — 5 状态机转移 / 表值映射 / 拉取矩阵语义。"""
import pytest

import state_machine as sm


# ── 合法/非法转移 ──

@pytest.mark.parametrize("src,dst", [
    ("pending", "processing"),        # 首次抢锁
    ("failed", "processing"),         # 重试重抢
    ("processing", "completed"),
    ("processing", "failed"),
    ("processing", "manual_review"),
    ("processing", "pending"),        # 字段匹配失败释放回原状态
])
def test_legal_transitions(src, dst):
    assert sm.can_transition(src, dst)


@pytest.mark.parametrize("src,dst", [
    ("pending", "completed"),         # 未经处理不得成功
    ("pending", "failed"),
    ("completed", "processing"),      # 终态不可逆
    ("failed", "completed"),          # 失败必须经处理
    ("manual_review", "completed"),   # 需人工由运营改写，不走状态机
    ("processing", "processing"),
])
def test_illegal_transitions(src, dst):
    assert not sm.can_transition(src, dst)
    with pytest.raises(sm.InvalidTransition):
        sm.assert_transition(src, dst)


# ── 表值映射 ──

def test_table_value_roundtrip():
    for state in sm.STATES:
        assert sm.from_table_value(sm.to_table_value(state)) == state


def test_pending_alias():
    # 表现行值"未处理"与拍板名"待处理"都映射 pending（阻塞项 #7 统一期兼容）
    assert sm.from_table_value("未处理") == "pending"
    assert sm.from_table_value("待处理") == "pending"


def test_unknown_table_value_raises():
    with pytest.raises(ValueError, match="未知处理状态值"):
        sm.from_table_value("不存在的状态")


def test_to_table_value_unknown_raises():
    with pytest.raises(ValueError, match="未知状态"):
        sm.to_table_value("bogus")


# ── 拉取矩阵语义（architecture.md §2）──

def test_fetchable():
    assert sm.is_fetchable("pending")
    assert sm.is_fetchable("failed")          # cron 兜底重试
    assert not sm.is_fetchable("processing")  # 不重复拉（stale 兜底另行）
    assert not sm.is_fetchable("completed")
    assert not sm.is_fetchable("manual_review")


def test_fetch_final():
    assert sm.is_fetch_final("completed")
    assert sm.is_fetch_final("failed")
    assert sm.is_fetch_final("manual_review")  # 等运营，不再拉取
    assert not sm.is_fetch_final("pending")
    assert not sm.is_fetch_final("processing")


def test_terminal_excludes_manual_review():
    # config terminal = completed/failed；manual_review 是拉取最终态但非 config terminal
    assert sm.is_terminal("completed") and sm.is_terminal("failed")
    assert not sm.is_terminal("manual_review")


# ── config 契约一致性 ──

def test_matches_config_yaml():
    cfg_sm = sm.load_states_from_config()
    assert sm.validate_against_config(cfg_sm) == []
