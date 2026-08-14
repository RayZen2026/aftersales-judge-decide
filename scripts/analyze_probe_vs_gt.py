#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
探针结果与GT对比分析脚本

用法:
    python scripts/analyze_probe_vs_gt.py <probe_report.json> [ground_truth.csv]

示例:
    python scripts/analyze_probe_vs_gt.py probes/probe_report_1agent_20260814_151821.json
"""

import sys
import json
import csv
from pathlib import Path
from typing import Dict, List, Tuple

def load_probe_report(probe_path: str) -> Dict:
    """加载探针测试报告"""
    with open(probe_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_ground_truth(gt_path: str) -> Dict[str, Dict]:
    """加载GT数据，返回 {升级售后单号: {字段: 值}} 字典"""
    gt_data = {}
    with open(gt_path, 'r', encoding='utf-8-sig') as f:  # utf-8-sig处理BOM
        reader = csv.DictReader(f)
        for row in reader:
            sample_id = row.get('升级售后单号', '').strip()
            if sample_id:
                gt_data[sample_id] = row
    return gt_data

def parse_responsibility(result_str: str) -> Tuple[int, int]:
    """
    解析判责结果字符串，提取平台和商家比例

    示例:
        "同意赔付24.36，平台商家1:9" -> (10, 90)
        "同意赔付145.52元，商家承担70%、平台30%" -> (30, 70)
    """
    import re

    # 模式1: "平台商家1:9" 或 "平台:商家=1:9"
    pattern1 = r'平台[商家]*[:：]?[商家]*[=]?\s*(\d+)\s*[:：]\s*(\d+)'
    match1 = re.search(pattern1, result_str)
    if match1:
        platform_ratio = int(match1.group(1))
        merchant_ratio = int(match1.group(2))
        total = platform_ratio + merchant_ratio
        return (platform_ratio * 100 // total, merchant_ratio * 100 // total)

    # 模式2: "商家承担70%、平台30%" 或 "平台30% 商家70%"
    pattern2_platform = r'平台[承担]*\s*(\d+)\s*%'
    pattern2_merchant = r'商家[承担]*\s*(\d+)\s*%'

    match_platform = re.search(pattern2_platform, result_str)
    match_merchant = re.search(pattern2_merchant, result_str)

    if match_platform and match_merchant:
        return (int(match_platform.group(1)), int(match_merchant.group(1)))

    # 无法解析
    return (None, None)

def compare_results(probe_sample: Dict, gt_sample: Dict) -> Dict:
    """对比单个样本的探针结果与GT"""
    comparison = {
        'sample_id': probe_sample['sample_id'],
        'probe_responsibility': probe_sample['actual']['single']['output']['responsibility'],
        'gt_result': gt_sample.get('判责结果', ''),
        'match': False,
        'details': {}
    }

    # 解析GT责任比例
    gt_platform, gt_merchant = parse_responsibility(comparison['gt_result'])
    comparison['gt_responsibility'] = {
        'platform': gt_platform,
        'merchant': gt_merchant
    }

    # 对比责任比例
    probe_platform = comparison['probe_responsibility']['platform']
    probe_merchant = comparison['probe_responsibility']['merchant']

    if gt_platform is not None and gt_merchant is not None:
        # 允许±5%的误差
        platform_match = abs(probe_platform - gt_platform) <= 5
        merchant_match = abs(probe_merchant - gt_merchant) <= 5
        comparison['match'] = platform_match and merchant_match
        comparison['details']['platform_diff'] = probe_platform - gt_platform
        comparison['details']['merchant_diff'] = probe_merchant - gt_merchant

    return comparison

def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/analyze_probe_vs_gt.py <probe_report.json> [ground_truth.csv]")
        sys.exit(1)

    probe_path = sys.argv[1]
    gt_path = sys.argv[2] if len(sys.argv) > 2 else 'assets/eval/ground_truth_v1.csv'

    print("=" * 70)
    print("探针结果 vs GT对比分析")
    print("=" * 70)
    print()

    # 加载数据
    print(f"加载探针报告: {probe_path}")
    probe_report = load_probe_report(probe_path)

    print(f"加载GT数据: {gt_path}")
    gt_data = load_ground_truth(gt_path)

    print(f"  探针样本数: {probe_report['samples_count']}")
    print(f"  GT样本数: {len(gt_data)}")
    print()

    # INNER JOIN: 按升级售后单号匹配
    print("=" * 70)
    print("INNER JOIN 结果")
    print("=" * 70)
    print()

    probe_samples = {detail['sample_id']: detail for detail in probe_report['details']}

    matched_samples = []
    unmatched_probe = []
    unmatched_gt = []

    # 找出匹配的样本
    for sample_id in probe_samples:
        if sample_id in gt_data:
            matched_samples.append(sample_id)
        else:
            unmatched_probe.append(sample_id)

    # 找出GT中没有被探针测试的样本
    for sample_id in gt_data:
        if sample_id not in probe_samples:
            unmatched_gt.append(sample_id)

    print(f"✓ 匹配成功: {len(matched_samples)} 条")
    print(f"✗ 探针有但GT无: {len(unmatched_probe)} 条")
    print(f"✗ GT有但探针无: {len(unmatched_gt)} 条")
    print()

    if unmatched_gt:
        print("【警告】以下GT样本未被探针测试:")
        for sample_id in unmatched_gt[:10]:  # 最多显示10个
            print(f"  - {sample_id}")
        if len(unmatched_gt) > 10:
            print(f"  ... (还有 {len(unmatched_gt) - 10} 个)")
        print()

    # 对比责任比例
    print("=" * 70)
    print("责任比例对比分析")
    print("=" * 70)
    print()

    comparisons = []
    exact_matches = 0
    tolerance_matches = 0  # ±5%容差

    for sample_id in matched_samples:
        probe_sample = probe_samples[sample_id]
        gt_sample = gt_data[sample_id]

        comparison = compare_results(probe_sample, gt_sample)
        comparisons.append(comparison)

        if comparison['match']:
            tolerance_matches += 1

            # 检查是否精确匹配
            if (comparison['details'].get('platform_diff') == 0 and
                comparison['details'].get('merchant_diff') == 0):
                exact_matches += 1

    print(f"精确匹配 (±0%): {exact_matches}/{len(matched_samples)} ({exact_matches/len(matched_samples)*100:.1f}%)")
    print(f"容差匹配 (±5%): {tolerance_matches}/{len(matched_samples)} ({tolerance_matches/len(matched_samples)*100:.1f}%)")
    print()

    # 显示不匹配的样本
    mismatches = [c for c in comparisons if not c['match']]
    if mismatches:
        print(f"【不匹配样本】共 {len(mismatches)} 条:")
        print()
        for c in mismatches[:10]:  # 最多显示10个
            print(f"  样本: {c['sample_id']}")
            print(f"    GT:    平台{c['gt_responsibility']['platform']}% 商家{c['gt_responsibility']['merchant']}%")
            print(f"    Probe: 平台{c['probe_responsibility']['platform']}% 商家{c['probe_responsibility']['merchant']}%")
            if 'platform_diff' in c['details']:
                print(f"    差异:  平台{c['details']['platform_diff']:+d}% 商家{c['details']['merchant_diff']:+d}%")
            print()

        if len(mismatches) > 10:
            print(f"  ... (还有 {len(mismatches) - 10} 个不匹配)")
        print()

    # 责任比例分布对比
    print("=" * 70)
    print("责任比例分布对比")
    print("=" * 70)
    print()

    gt_distribution = {}
    probe_distribution = {}

    for c in comparisons:
        if c['gt_responsibility']['platform'] is not None:
            gt_key = f"平台{c['gt_responsibility']['platform']}% 商家{c['gt_responsibility']['merchant']}%"
            gt_distribution[gt_key] = gt_distribution.get(gt_key, 0) + 1

        probe_key = f"平台{c['probe_responsibility']['platform']}% 商家{c['probe_responsibility']['merchant']}%"
        probe_distribution[probe_key] = probe_distribution.get(probe_key, 0) + 1

    print("GT分布:")
    for ratio, count in sorted(gt_distribution.items(), key=lambda x: x[1], reverse=True):
        print(f"  {ratio}: {count}次 ({count/len(comparisons)*100:.1f}%)")
    print()

    print("Probe分布:")
    for ratio, count in sorted(probe_distribution.items(), key=lambda x: x[1], reverse=True):
        print(f"  {ratio}: {count}次 ({count/len(comparisons)*100:.1f}%)")
    print()

    # 生成详细报告文件
    output_path = Path(probe_path).parent / f"comparison_{Path(probe_path).stem}.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': {
                'probe_samples': probe_report['samples_count'],
                'gt_samples': len(gt_data),
                'matched_samples': len(matched_samples),
                'unmatched_probe': len(unmatched_probe),
                'unmatched_gt': len(unmatched_gt),
                'exact_match_rate': exact_matches / len(matched_samples) if matched_samples else 0,
                'tolerance_match_rate': tolerance_matches / len(matched_samples) if matched_samples else 0,
            },
            'comparisons': comparisons,
            'unmatched_gt_list': unmatched_gt,
            'unmatched_probe_list': unmatched_probe
        }, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print(f"✓ 详细对比报告已保存: {output_path}")
    print("=" * 70)

if __name__ == '__main__':
    main()
