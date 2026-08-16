#!/usr/bin/env python3
"""
生成完整的GT vs LLM对比CSV（v3.1标准）
包含：基础输入数据 + GT数据 + LLM输出 + 推理过程 + 差值计算
"""
import json
import csv
import re
from pathlib import Path
from datetime import datetime


def load_gt_data(gt_file):
    """加载GT数据"""
    gt_data = {}
    with open(gt_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sample_id = row['升级售后单号']
            judgment = row['判责结果']

            # 解析责任比例
            resp = parse_gt_responsibility(judgment)
            # 解析金额
            amount = parse_gt_amount(judgment)

            gt_data[sample_id] = {
                'judgment': judgment,
                'responsibility': resp,
                'amount': amount,
                'expectation': row['满足期望类型']
            }
    return gt_data


def parse_gt_responsibility(text):
    """解析GT判责结果中的责任比例"""
    resp = {'platform': 0, 'merchant': 0, 'logistics': 0, 'agent': 0}

    # 平台承担 / 商家承担
    if '平台承担' in text and '商家承担' not in text:
        resp['platform'] = 100
        return resp
    if '商家承担' in text and '平台承担' not in text:
        resp['merchant'] = 100
        return resp

    # 平台商家X:Y
    match = re.search(r'平台商家(\d+):(\d+)', text)
    if match:
        p, m = int(match.group(1)), int(match.group(2))
        total = p + m
        resp['platform'] = int(p / total * 100)
        resp['merchant'] = int(m / total * 100)
        return resp

    # 平台商家物流X:Y:Z
    match = re.search(r'平台商家物流(\d+):(\d+):(\d+)', text)
    if match:
        p, m, l = int(match.group(1)), int(match.group(2)), int(match.group(3))
        total = p + m + l
        resp['platform'] = int(p / total * 100)
        resp['merchant'] = int(m / total * 100)
        resp['logistics'] = int(l / total * 100)
        return resp

    return resp


def parse_gt_amount(text):
    """解析GT判责结果中的赔付金额"""
    match = re.search(r'赔付([\d.]+)', text)
    if match:
        return float(match.group(1))
    return 0.0


def load_probe_report(probe_file):
    """加载探针报告"""
    with open(probe_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_sample_input(raw_file):
    """从raw_*.json加载样本输入数据"""
    with open(raw_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # raw文件是数组格式，取第一个元素
    if isinstance(data, list) and len(data) > 0:
        first_run = data[0]

        # 从prompt中解析输入数据（简化版，只取关键字段）
        prompt = first_run.get('prompt', '')

        # 解析基础字段
        appeal_type = ''
        appeal_amount = 0
        paid_amount = 0
        aftersales_type = ''
        aftersales_interval = 0

        for line in prompt.split('\n'):
            if '- 诉求类型:' in line:
                appeal_type = line.split('`')[1] if '`' in line else ''
            elif '- 诉求赔付金额:' in line:
                appeal_amount = float(line.split('`')[1].strip()) if '`' in line else 0
            elif '- 商品实付金额:' in line:
                paid_amount = float(line.split('`')[1].strip()) if '`' in line else 0
            elif '- 升级售后类型:' in line:
                aftersales_type = line.split('`')[1] if '`' in line else ''
            elif '- 升级售后提交间隔天数:' in line:
                try:
                    aftersales_interval = int(line.split('`')[1].strip()) if '`' in line and line.split('`')[1].strip() else 0
                except:
                    aftersales_interval = 0

        # 从output中获取dimension_data（简化，直接用output）
        output = first_run.get('output', {})

        return {
            'appeal_type': appeal_type,
            'appeal_amount': appeal_amount,
            'paid_amount': paid_amount,
            'aftersales_type': aftersales_type,
            'aftersales_interval': aftersales_interval,
            'output': output,
            'prompt': prompt  # 保留prompt用于后续解析
        }

    return {}


def main():
    # 1. 读取GT数据
    gt_file = Path("assets/eval/ground_truth_v1.csv")
    gt_data = load_gt_data(gt_file)
    print(f"✓ 加载GT数据: {len(gt_data)} 条")

    # 2. 读取探针报告
    probe_file = Path("probes/probe_report_1agent_20260815_225119.json")
    probe_data = load_probe_report(probe_file)
    print(f"✓ 加载探针报告: {len(probe_data['details'])} 条")

    # 3. 读取样本输入数据
    probes_dir = Path("probes")
    sample_inputs = {}
    for detail in probe_data['details']:
        sample_id = detail['sample_id']
        raw_file = probes_dir / f"raw_1agent_{sample_id}.json"
        if raw_file.exists():
            sample_inputs[sample_id] = load_sample_input(raw_file)
    print(f"✓ 加载样本输入数据: {len(sample_inputs)} 条")

    # 4. 整合数据
    rows = []
    for detail in probe_data['details']:
        sample_id = detail['sample_id']

        # 跳过不在GT中的样本
        if sample_id not in gt_data:
            continue

        gt = gt_data[sample_id]
        llm_output = detail['actual']['single']['output']
        sample_input = sample_inputs.get(sample_id, {})

        # 从prompt解析维度数据
        prompt = sample_input.get('prompt', '')

        # 解析商品等级、门店等级等字段
        product_level = ''
        is_severe_quality = 0
        batch_signal = ''
        is_merchant_issue = 0
        is_all_category = 0
        store_tier = ''
        store_gmv_30d = 0
        refund_rate_14d = 0
        last_order_days = 999
        merchant_deviation = 0
        product_deviation = 0
        supplier_count = 0
        evidence_count = 0

        # 从prompt中提取维度数据（简化解析）
        in_product_section = False
        in_merchant_section = False
        in_store_section = False
        in_task_section = False

        for line in prompt.split('\n'):
            line = line.strip()

            # 商品品质维度
            if '### 商品品质维度' in line:
                in_product_section = True
                in_merchant_section = False
                in_store_section = False
                in_task_section = False
            elif '### 商品批次追溯' in line:
                in_product_section = False
            elif '### 商家品质追溯' in line:
                in_merchant_section = True
                in_product_section = False
                in_store_section = False
                in_task_section = False
            elif '### 门店价值与行为' in line:
                in_store_section = True
                in_merchant_section = False
                in_product_section = False
                in_task_section = False
            elif '### 责任方标识' in line:
                in_task_section = True
                in_store_section = False
                in_merchant_section = False
                in_product_section = False

            # 解析字段
            if in_product_section:
                if '"商品等级":' in line:
                    product_level = line.split('"')[3] if len(line.split('"')) > 3 else ''
                elif '"是否严重品质问题":' in line:
                    is_severe_quality = int(line.split(':')[1].split(',')[0].strip())
                elif '"举证图片数量":' in line:
                    evidence_count = int(line.split(':')[1].split(',')[0].strip())
                elif '"举证视频数量":' in line:
                    evidence_count += int(line.split(':')[1].strip())

            elif in_merchant_section:
                if '"商家偏离倍数":' in line:
                    merchant_deviation = float(line.split(':')[1].split(',')[0].strip())
                elif '"商品偏离倍数":' in line:
                    product_deviation = float(line.split(':')[1].split(',')[0].strip())
                elif '"同品类供货商家数量":' in line:
                    supplier_count = int(line.split(':')[1].strip())
                elif '"批次问题信号":' in line:
                    batch_signal = line.split('"')[3] if len(line.split('"')) > 3 else ''

            elif in_store_section:
                if '"门店等级":' in line:
                    store_tier = line.split('"')[3] if len(line.split('"')) > 3 else ''
                elif '"近30天下单金额":' in line:
                    store_gmv_30d = float(line.split(':')[1].split(',')[0].strip())
                elif '"14日售后赔付率":' in line:
                    refund_rate_14d = float(line.split(':')[1].split(',')[0].strip())
                elif '"最近下单间隔天数":' in line:
                    last_order_days = int(line.split(':')[1].strip())

            elif in_task_section:
                if '"是否商家问题":' in line:
                    is_merchant_issue = int(line.split(':')[1].split(',')[0].strip())
                elif '"是否全品类商家":' in line:
                    is_all_category = int(line.split(':')[1].strip().split('#')[0].strip())

        row = {
            # 分组1: 样本标识
            '升级售后单号': sample_id,

            # 分组2: 基础输入数据
            '诉求类型': sample_input.get('appeal_type', ''),
            '诉求赔付金额': sample_input.get('appeal_amount', 0),
            '商品实付金额': sample_input.get('paid_amount', 0),
            '升级售后类型': sample_input.get('aftersales_type', ''),
            '升级售后提交间隔天数': sample_input.get('aftersales_interval', 0),

            '商品等级': product_level,
            '是否严重品质问题': is_severe_quality,
            '批次问题信号': batch_signal,
            '是否商家问题': is_merchant_issue,
            '是否全品类商家': is_all_category,

            '门店等级': store_tier,
            '近30天下单金额': store_gmv_30d,
            '14日售后赔付率': refund_rate_14d,
            '最近下单间隔天数': last_order_days,

            '商家偏离倍数': merchant_deviation,
            '商品偏离倍数': product_deviation,
            '同品类供货商家数': supplier_count,

            '举证数量': evidence_count,

            # 分组3: GT数据
            'GT判责结果': gt['judgment'],
            'GT平台%': gt['responsibility']['platform'],
            'GT商家%': gt['responsibility']['merchant'],
            'GT物流%': gt['responsibility']['logistics'],
            'GT代理人%': gt['responsibility']['agent'],
            'GT金额': f"{gt['amount']:.2f}",
            'GT满足期望': gt['expectation'],

            # 分组4: LLM输出数据
            'LLM判责摘要': llm_output.get('judgment_summary', ''),
            'LLM平台%': llm_output['responsibility']['platform'],
            'LLM商家%': llm_output['responsibility']['merchant'],
            'LLM物流%': llm_output['responsibility']['logistics'],
            'LLM代理人%': llm_output['responsibility']['agent'],
            'LLM金额': f"{llm_output['amount']:.2f}",
            'LLM金额调整比例': llm_output.get('amount_adjust_ratio', 1.0),
            'LLM满足期望': llm_output.get('expectation_satisfaction_type', ''),

            # 分组5: 赔付金额推断
            'LLM赔付金额推理': llm_output.get('judgment_basis', {}).get('amount_adjustment', ''),

            # 分组6: 责任比例推断
            'LLM责任推理': llm_output.get('judgment_basis', {}).get('responsibility_reasoning', ''),

            # 分组7: 差值计算
            '平台%差值': llm_output['responsibility']['platform'] - gt['responsibility']['platform'],
            '商家%差值': llm_output['responsibility']['merchant'] - gt['responsibility']['merchant'],
            '物流%差值': llm_output['responsibility']['logistics'] - gt['responsibility']['logistics'],
            '代理人%差值': llm_output['responsibility']['agent'] - gt['responsibility']['agent'],
            '金额差值': f"{llm_output['amount'] - gt['amount']:.2f}",
            '金额差值%': f"{(llm_output['amount'] - gt['amount']) / gt['amount'] * 100:.1f}%" if gt['amount'] > 0 else "N/A",

            # 分组8: LLM完整输出
            'LLM建议动作': llm_output.get('recommended_action', ''),
            'LLM处理动作': llm_output.get('action', ''),
            'LLM推理说明': llm_output.get('reasoning', ''),
            'LLM门店profile': llm_output.get('judgment_basis', {}).get('store_profile', ''),
            'LLM商品质量判断': llm_output.get('judgment_basis', {}).get('product_quality', ''),
            'LLM商家追溯判断': llm_output.get('judgment_basis', {}).get('merchant_traceability', ''),
            'LLM事实发现': llm_output.get('judgment_basis', {}).get('fact_finding', ''),
            'LLM规则参考': llm_output.get('judgment_basis', {}).get('rule_reference', ''),
            'LLM决策对比': llm_output.get('judgment_basis', {}).get('decision_comparison', '')
        }

        rows.append(row)

    # 5. 写入CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(f"probes/gt_vs_llm_v0.13.0_{timestamp}.csv")
    fieldnames = list(rows[0].keys())

    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ 生成完整对比CSV: {output_file}")
    print(f"  - GT样本数: {len(rows)}")
    print(f"  - 字段数: {len(fieldnames)}")
    print(f"  - 包含: 基础输入数据(18字段) + GT(7字段) + LLM输出(8字段) + 推理(2字段) + 差值(6字段) + 详情(9字段)")


if __name__ == '__main__':
    main()
