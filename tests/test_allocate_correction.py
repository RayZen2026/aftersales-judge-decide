"""allocate_correction 4方责任等比缩放+上限截断+互斥约束（Phase 5，main.py 纯数学）。

物流/代理人互斥：两者不会同时>0，若LLM同时输出则物流优先。
"""
import random

from main import allocate_correction


# ============================================================
# Phase 5: 4方责任（platform/merchant/logistics/agent，物流/代理人互斥）
# ============================================================

def test_4party_already_100():
    # 输入logistics=15, agent=5，互斥后agent归零，总和=95，缩放到100
    result = allocate_correction({"platform": 40, "merchant": 40, "logistics": 15, "agent": 5})
    assert result["agent"] == 0  # 互斥归零
    assert result["platform"] + result["merchant"] + result["logistics"] == 100
    assert result["logistics"] > 0  # 物流保留


def test_4party_scaling():
    # 10:20:15:0（无代理人）→ 缩放但超限 → logistics=30截断
    result = allocate_correction({"platform": 10, "merchant": 20, "logistics": 15, "agent": 0})
    assert result["platform"] + result["merchant"] + result["logistics"] + result["agent"] == 100
    # logistics按比例缩放15→33%超限截断到30，溢出3分配到platform/merchant
    assert result["logistics"] == 30
    assert result["agent"] == 0


def test_4party_scaling_to_100():
    # 1:2:0:0.5（和=3.5，有agent）→ 等比缩放到100 → 约29:57:0:14
    result = allocate_correction({"platform": 1, "merchant": 2, "logistics": 0, "agent": 0.5})
    assert result["platform"] + result["merchant"] + result["logistics"] + result["agent"] == 100
    assert result["logistics"] == 0  # 无物流
    assert result["agent"] > 0  # 有代理人


def test_mutual_exclusion_logistics_priority():
    """物流/代理人互斥：同时>0时物流优先，代理人归零。"""
    result = allocate_correction({"platform": 30, "merchant": 30, "logistics": 20, "agent": 20})
    assert result["logistics"] > 0  # 物流保留
    assert result["agent"] == 0  # 代理人归零
    assert result["platform"] + result["merchant"] + result["logistics"] == 100


def test_logistics_cap_30():
    # 物流超限：platform=20, merchant=20, logistics=60 → logistics截断到30，溢出30分配
    result = allocate_correction({"platform": 20, "merchant": 20, "logistics": 60, "agent": 0})
    assert result["logistics"] == 30  # 截断
    assert result["agent"] == 0
    assert result["platform"] + result["merchant"] == 70
    assert result["platform"] + result["merchant"] + result["logistics"] == 100


def test_agent_cap_20():
    # 代理人超限：platform=30, merchant=30, agent=40 → agent截断到20，溢出20分配
    result = allocate_correction({"platform": 30, "merchant": 30, "logistics": 0, "agent": 40})
    assert result["agent"] == 20  # 截断
    assert result["logistics"] == 0
    assert result["platform"] + result["merchant"] == 80
    assert result["platform"] + result["merchant"] + result["agent"] == 100


def test_zero_total_returns_4zero():
    assert allocate_correction({"platform": 0, "merchant": 0, "logistics": 0, "agent": 0}) == \
           {"platform": 0, "merchant": 0, "logistics": 0, "agent": 0}


def test_missing_keys_default_zero():
    assert allocate_correction({}) == {"platform": 0, "merchant": 0, "logistics": 0, "agent": 0}


def test_only_platform_merchant():
    # 兼容旧2方：只有platform+merchant → logistics/agent=0
    result = allocate_correction({"platform": 30, "merchant": 70})
    assert result == {"platform": 30, "merchant": 70, "logistics": 0, "agent": 0}


def test_random_sum_100_invariant_4party():
    random.seed(42)
    for _ in range(100):
        p = random.randint(0, 100)
        m = random.randint(0, 100)
        # 互斥：只生成一方>0
        if random.random() < 0.5:
            l = random.randint(0, 50)
            a = 0
        else:
            l = 0
            a = random.randint(0, 30)
        if p + m + l + a == 0:
            continue
        r = allocate_correction({"platform": p, "merchant": m, "logistics": l, "agent": a})
        assert r["platform"] + r["merchant"] + r["logistics"] + r["agent"] == 100, (p, m, l, a, r)
        assert 0 <= r["platform"] <= 100 and 0 <= r["merchant"] <= 100
        assert 0 <= r["logistics"] <= 30, f"logistics超限: {r['logistics']}"
        assert 0 <= r["agent"] <= 20, f"agent超限: {r['agent']}"
        # 互斥检查
        assert not (r["logistics"] > 0 and r["agent"] > 0), f"物流/代理人未互斥: {r}"


# ============================================================
# 向后兼容：旧2方测试保留
# ============================================================

def test_already_100():
    assert allocate_correction({"platform": 70, "merchant": 30}) == \
           {"platform": 70, "merchant": 30, "logistics": 0, "agent": 0}


def test_scaling_99_1():
    assert allocate_correction({"platform": 99, "merchant": 1}) == \
           {"platform": 99, "merchant": 1, "logistics": 0, "agent": 0}


def test_scaling_1_2():
    # 1:2 → 33/67（等比缩放后和=100）
    assert allocate_correction({"platform": 1, "merchant": 2}) == \
           {"platform": 33, "merchant": 67, "logistics": 0, "agent": 0}


def test_zero_total_returns_zero_pair():
    assert allocate_correction({"platform": 0, "merchant": 0}) == \
           {"platform": 0, "merchant": 0, "logistics": 0, "agent": 0}

