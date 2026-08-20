#!/usr/bin/env python3
"""
test_runtime_validation.py — 运行时校验单元测试（优化1）

测试场景：
1. is_logistics_issue=0 但输出logistics>0 → 强制修正为0
2. is_agent_issue=0 但输出agent>0 → 强制修正为0
3. 责任比例和≠100% → 重新归一化
4. 比例不是10的倍数 → 重新归一化
5. 正常场景 → 不修正
"""
import logging
import sys
from pathlib import Path

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from agent_single import validate_and_fix_responsibility


def test_logistics_constraint():
    """测试场景1: is_logistics_issue=0 但输出logistics=30"""
    logger = logging.getLogger("test")
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

    result = {
        "responsibility": {"platform": 10, "merchant": 60, "logistics": 30, "agent": 0}
    }
    task_data = {"是否物流问题": 0, "是否代理人问题": 0}

    fixed = validate_and_fix_responsibility(result, task_data, logger)

    assert fixed["responsibility"]["logistics"] == 0, "物流比例应修正为0"
    print("✓ 测试1通过: 物流约束校验生效")


def test_agent_constraint():
    """测试场景2: is_agent_issue=0 但输出agent=20"""
    logger = logging.getLogger("test")
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

    result = {
        "responsibility": {"platform": 10, "merchant": 70, "logistics": 0, "agent": 20}
    }
    task_data = {"是否物流问题": 0, "是否代理人问题": 0}

    fixed = validate_and_fix_responsibility(result, task_data, logger)

    assert fixed["responsibility"]["agent"] == 0, "代理人比例应修正为0"
    print("✓ 测试2通过: 代理人约束校验生效")


def test_sum_not_100():
    """测试场景3: 责任比例和≠100%"""
    logger = logging.getLogger("test")
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

    result = {
        "responsibility": {"platform": 15, "merchant": 95, "logistics": 0, "agent": 0}
    }
    task_data = {"是否物流问题": 0, "是否代理人问题": 0}

    fixed = validate_and_fix_responsibility(result, task_data, logger)

    total = sum(fixed["responsibility"].values())
    assert total == 100, f"责任比例和应为100%，实际{total}%"
    print("✓ 测试3通过: 归一化校验生效")


def test_not_multiple_of_10():
    """测试场景4: 比例不是10的倍数"""
    logger = logging.getLogger("test")
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

    result = {
        "responsibility": {"platform": 15, "merchant": 85, "logistics": 0, "agent": 0}
    }
    task_data = {"是否物流问题": 0, "是否代理人问题": 0}

    fixed = validate_and_fix_responsibility(result, task_data, logger)

    for party, value in fixed["responsibility"].items():
        assert value % 10 == 0, f"{party}={value}%应为10的倍数"
    print("✓ 测试4通过: 10的倍数校验生效")


def test_normal_case():
    """测试场景5: 正常输出，不应修正"""
    logger = logging.getLogger("test")
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

    result = {
        "responsibility": {"platform": 20, "merchant": 80, "logistics": 0, "agent": 0}
    }
    task_data = {"是否物流问题": 0, "是否代理人问题": 0}

    original = result["responsibility"].copy()
    fixed = validate_and_fix_responsibility(result, task_data, logger)

    assert fixed["responsibility"] == original, "正常输出不应被修正"
    print("✓ 测试5通过: 正常场景不修正")


def test_3_party_logistics():
    """测试场景6: 3方责任（含物流），正常输出"""
    logger = logging.getLogger("test")
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

    result = {
        "responsibility": {"platform": 10, "merchant": 60, "logistics": 30, "agent": 0}
    }
    task_data = {"是否物流问题": 1, "是否代理人问题": 0}

    original = result["responsibility"].copy()
    fixed = validate_and_fix_responsibility(result, task_data, logger)

    assert fixed["responsibility"] == original, "3方责任（含物流）正常输出不应被修正"
    print("✓ 测试6通过: 3方责任（含物流）正常场景")


if __name__ == "__main__":
    print("运行时校验单元测试\n" + "="*50)

    try:
        test_logistics_constraint()
        test_agent_constraint()
        test_sum_not_100()
        test_not_multiple_of_10()
        test_normal_case()
        test_3_party_logistics()

        print("\n" + "="*50)
        print("✅ 所有测试通过！运行时校验逻辑正确")
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 运行错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
