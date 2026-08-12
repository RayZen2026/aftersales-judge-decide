"""allocate_correction 等比缩放不变量（main.py 纯数学，探针/生产共用）。"""
import random

from main import allocate_correction


def test_already_100():
    assert allocate_correction({"platform": 70, "merchant": 30}) == {"platform": 70, "merchant": 30}


def test_scaling_99_1():
    assert allocate_correction({"platform": 99, "merchant": 1}) == {"platform": 99, "merchant": 1}


def test_scaling_1_2():
    # 1:2 → 33/67（等比缩放后和=100）
    assert allocate_correction({"platform": 1, "merchant": 2}) == {"platform": 33, "merchant": 67}


def test_zero_total_returns_zero_pair():
    # 已知边界：total=0 → {0,0}，破坏和=100 不变量；探针报告视为格式异常（见 probe_llm）
    assert allocate_correction({"platform": 0, "merchant": 0}) == {"platform": 0, "merchant": 0}


def test_missing_keys_default_zero():
    assert allocate_correction({}) == {"platform": 0, "merchant": 0}


def test_random_sum_100_invariant():
    random.seed(42)
    for _ in range(100):
        m = random.randint(0, 100)
        s = random.randint(0, 100)
        if m + s == 0:
            continue
        r = allocate_correction({"platform": m, "merchant": s})
        assert r["platform"] + r["merchant"] == 100, (m, s, r)
        assert 0 <= r["platform"] <= 100 and 0 <= r["merchant"] <= 100
