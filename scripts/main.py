#!/usr/bin/env python3
"""
aftersales-judge-decide main.py skeleton
v0.1.0 Phase 0 占位版

完整 Workflow(待 Phase 2-3 实现):
  Stage 1: 触发 + 拉取(batch)
  Stage 2: 数据准备(batch)
  Stage 3: 单条处理循环(per-item, 串行)
    抢锁 → 字段匹配 → N AGENT 串行 → 9 类失败处理 → 5 状态机推进 → 写表 → 通知

路径 A argparse(v2.0 §5.1):
  auto   - cron hourly 10-23 触发(默认)
  manual - 单条处理(指定 item_id)
  test   - 端到端测试(独立 test_main_table)
  probe  - 探针基础测试(Phase 1.5-1.7, 3 轮调优上限)

⚠️ 占位版 = 函数签名 + 文档,逻辑待 Phase 2-3 填充
"""

import argparse
import sys
import os
import json
import logging
from pathlib import Path
from typing import Optional

# 路径常量
BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
ASSETS_DIR = BASE_DIR / "assets"
TEMPLATES_DIR = ASSETS_DIR / "agent_prompt_templates"
LOGS_DIR = BASE_DIR / "logs"
PROBES_DIR = BASE_DIR / "probes"

# 配置加载(占位,Phase 2.1 真实实现)
def load_config():
    """Load config.yaml (Phase 2.1 实现 L4 严格替换)"""
    # TODO Phase 2.1: 严格替换策略(v2.0 §10.8)
    if CONFIG_PATH.exists():
        import yaml
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


# 日志初始化(占位)
def init_logging():
    """Init logging (Phase 2 实现)"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return logging.getLogger("aftersales-judge-decide")


# ============================================================
# AGENT 占位函数(Phase 3 真实实现,3 轮探针调优后定稿)
# ============================================================

def agent1(input_data: dict) -> dict:
    """
    AGENT 1: 门店期望判定
    LLM 共享链: glm-5.1 → qwen-3.7-plus → doubao-seed-2.0-pro → minimax-m3

    输入: input_data = {
        "item_id": str,
        "appeal_content": str,
        "appeal_type": str,  # 退货/赔付金额/退货或者赔付金额
        "appeal_amount": int,  # 元
        "aftersales_type": str,  # 处理中/超时
        "dimension_data": {"product": dict, "store": dict}
    }

    输出: {
        "store_expected": "应退货"|"应赔付"|"应退货或赔付"|"需人工",
        "store_expected_amount": int,
        "reasoning": str,
        "confidence": float
    }
    """
    # TODO Phase 3.1: 渲染 agent1_prompt_template.j2 + 调 LLM 共享链 + 解析 JSON
    return {
        "store_expected": "需人工",
        "store_expected_amount": 0,
        "reasoning": "AGENT 1 占位实现,待 Phase 3.1 真实实现",
        "confidence": 0.0,
    }


def agent2(input_data: dict, agent1_output: dict) -> dict:
    """
    AGENT 2: 承担方比例判责
    LLM 共享链: 同 AGENT 1

    输入: input_data + agent1_output

    输出: {
        "responsibility": {"meituan": int, "merchant": int},  # 0-100, 之和=100
        "reasoning": str,
        "confidence": float,
        "key_factors": list
    }
    """
    # TODO Phase 3.2: 渲染 agent2_prompt_template.j2 + 调 LLM 共享链 + 解析 JSON
    return {
        "responsibility": {"meituan": 0, "merchant": 0},
        "reasoning": "AGENT 2 占位实现,待 Phase 3.2 真实实现",
        "confidence": 0.0,
        "key_factors": [],
    }


def allocate_correction(responsibility: dict) -> dict:
    """
    分配校正(纯数学,不调 LLM,D-20260806-008)
    确保 meituan + merchant = 100(等比缩放)

    输入: responsibility = {"meituan": int, "merchant": int}
    输出: responsibility(校正后)
    """
    # TODO Phase 3.4: 等比缩放实现
    m = responsibility.get("meituan", 0)
    s = responsibility.get("merchant", 0)
    total = m + s
    if total == 0:
        return {"meituan": 0, "merchant": 0}
    return {
        "meituan": round(m * 100 / total),
        "merchant": round(s * 100 / total),
    }


def agent3(input_data: dict, agent1_output: dict, agent2_output: dict, responsibility_corrected: dict) -> dict:
    """
    AGENT 3: 综合判责意见
    LLM 独立链: doubao-seed-2.0-pro → minimax-m3(综合任务不需 reasoning 强模型)

    输入: input_data + agent1_output + agent2_output + responsibility_corrected

    输出: {
        "judgment_summary": str,  # 200-800 字
        "action": "退款"|"退货"|"赔付"|"无需处理"|"需人工",
        "amount": int,
        "responsibility_summary": str,  # "美团 X% / 商家 Y%"
        "confidence": float,
        "tags": list
    }
    """
    # TODO Phase 3.3: 渲染 agent3_prompt_template.j2 + 调 LLM 独立链 + 解析 JSON
    return {
        "judgment_summary": "AGENT 3 占位实现,待 Phase 3.3 真实实现",
        "action": "需人工",
        "amount": 0,
        "responsibility_summary": "美团 0% / 商家 0%",
        "confidence": 0.0,
        "tags": [],
    }


# ============================================================
# Workflow 占位(Phase 3.4 真实实现)
# ============================================================

def stage1_fetch(logger) -> list:
    """
    Stage 1: 触发 + 拉取(batch)
    - cron 触发检查(单 JOB 单 Task, stale 5min 兜底)
    - 拉取任务: WHERE 处理状态 IN ('待处理', '已处理-失败') AND 审批时间窗口
    """
    # TODO Phase 3.4: 调 lark-cli 拉取
    logger.info("Stage 1: fetch (占位, 待 Phase 3.4 真实实现)")
    return []


def stage2_prepare(items: list, logger) -> list:
    """
    Stage 2: 数据准备(batch)
    - 维度数据 JOIN(2 张维度表: 商品维度统计表 + 门店表)
    - 解析门店等级(AST 规则 + 数据, 不调 LLM)
    - 读 config.yaml 业务参数
    """
    # TODO Phase 3.4: 维度表 JOIN + 读 config
    logger.info(f"Stage 2: prepare {len(items)} items (占位, 待 Phase 3.4 真实实现)")
    return items


def stage3_process_per_item(item: dict, logger) -> dict:
    """
    Stage 3: 单条处理(per-item, 串行)
    - 抢单条锁(per-item, 处理状态=已处理-处理中)
    - 字段匹配检验(per-item, 失败 → 飞书通知 + 抢锁释放 + 跳过)
    - 3 AGENT 串行(agent1 → agent2 → agent3)
    - 9 类失败处理 + 5 状态机推进
    - 写判责结果表(成功/需人工)
    - 写回任务表状态
    - 抢锁释放
    """
    # TODO Phase 3.4: 完整流程实现
    logger.info(f"Stage 3: process {item.get('item_id')} (占位, 待 Phase 3.4 真实实现)")

    # 占位 Workflow: 3 AGENT 串行
    a1 = agent1(item)
    a2 = agent2(item, a1)
    corrected = allocate_correction(a2.get("responsibility", {}))
    a3 = agent3(item, a1, a2, corrected)

    return {
        "item_id": item.get("item_id"),
        "agent1": a1,
        "agent2": a2,
        "responsibility_corrected": corrected,
        "agent3": a3,
    }


# ============================================================
# 4 个 subcommand 入口(v2.0 §5.1 路径 A)
# ============================================================

def cmd_auto(args, logger):
    """auto 模式: cron hourly 10-23 触发(默认)"""
    logger.info("auto mode (占位, 待 Phase 3.4 真实实现)")
    items = stage1_fetch(logger)
    items = stage2_prepare(items, logger)
    results = [stage3_process_per_item(item, logger) for item in items]
    logger.info(f"auto mode done, processed {len(results)} items")
    return {"mode": "auto", "processed": len(results)}


def cmd_manual(args, logger):
    """manual 模式: 单条处理(指定 item_id)"""
    logger.info(f"manual mode item_id={args.item_id} (占位, 待 Phase 3.4 真实实现)")
    # TODO Phase 3.4: 拉取单条 + 3 AGENT 串行 + 写表
    return {"mode": "manual", "item_id": args.item_id, "status": "占位"}


def cmd_test(args, logger):
    """test 模式: 端到端测试(独立 test_main_table)"""
    logger.info(f"test mode table_id={args.table_id} (占位, 待 Phase 4.1 真实实现)")
    # TODO Phase 4.1: 端到端 1 → 3 → 10 → 30 完整单
    return {"mode": "test", "table_id": args.table_id, "status": "占位"}


def cmd_probe(args, logger):
    """probe 模式: 探针基础测试(Phase 1.5-1.7)

    Round 1 = 端到端跑通(格式/一致性/latency);准确率 + 1 vs 3 决策门 Round 2。
    委托 probe_llm.run_probe(延迟 import 避免循环依赖: probe_llm 顶层 from main import allocate_correction)。
    """
    import probe_llm  # noqa: PLC0415
    logger.info(f"probe mode={args.probe_mode} runs={args.runs} samples_file={args.samples_file}")
    return probe_llm.run_probe(args, load_config(), logger)


# ============================================================
# 入口
# ============================================================

def main():
    """CLI 入口: argparse 4 subcommand"""
    parser = argparse.ArgumentParser(
        prog="aftersales-judge-decide",
        description="升级售后判责主流程 SKILL - 编排 + 执行"
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # auto (cron hourly 10-23, 默认)
    p_auto = subparsers.add_parser("auto", help="cron 自动模式")
    p_auto.add_argument("--batch-size", type=int, default=30, help="单次 Task 拉取上限")

    # manual
    p_manual = subparsers.add_parser("manual", help="手动处理单条")
    p_manual.add_argument("--item-id", required=True, help="升级售后单号")

    # test (端到端)
    p_test = subparsers.add_parser("test", help="端到端测试")
    p_test.add_argument("--table-id", required=True, help="test_main_table ID")

    # probe (Phase 1.5 探针)
    p_probe = subparsers.add_parser("probe", help="探针基础测试")
    p_probe.add_argument("--probe-mode", choices=["1agent", "3agent", "both"],
                         default="both", help="1agent=T1.5 完整流程 / 3agent=T1.6 串行链")
    p_probe.add_argument("--samples-file", default=None,
                         help="data_loader 产物 SampleSet JSON；缺省现场 live 拉取")
    p_probe.add_argument("--samples", type=int, default=None, help="样本数上限")
    p_probe.add_argument("--runs", type=int, default=None,
                         help="一致性次数（默认 config probe.consistency_runs）")

    args = parser.parse_args()
    logger = init_logging()
    config = load_config()

    # 派发
    dispatch = {
        "auto": cmd_auto,
        "manual": cmd_manual,
        "test": cmd_test,
        "probe": cmd_probe,
    }
    result = dispatch[args.mode](args, logger)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
