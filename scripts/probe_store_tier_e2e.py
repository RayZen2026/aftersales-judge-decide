"""门店等级解析端到端 probe（飞书端零副作用）。

LRN-20260817-004 修法验证 + 持续 smoke test：
- 拉飞书《门店分层规则表》最新 1 行 rules JSON
- 拉飞书《门店维度统计表》多条样本
- 调 apply_tier 真函数
- 验输出 A/B/C/D/其他，**不是** None

不写飞书结果表，不改任务表状态，**仅诊断**。
"""
import argparse
import json
import sys
from pathlib import Path

# scripts/ 加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import load_config  # noqa: E402
from data_loader import (  # noqa: E402
    TIER_STAT_FIELDS, compute_store_tier, fetch_store_dimension,
    fetch_store_tier_rules, record_list,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.format(__doc__=__doc__))
    p.add_argument("--shop-ids", type=str, default="303260,35585,1024",
                   help="逗号分隔店铺 id 列表（默认 3 条样本）")
    p.add_argument("--auto-pick", type=int, default=0,
                   help="从门店维度表自动挑 N 条样本（按近30天下单金额排序，覆盖高分位/低分位）")
    args = p.parse_args()

    cfg = load_config()
    print("=" * 60)
    print("e2e probe — store_tier 解析验证")
    print("=" * 60)

    # 1. 拉 rules
    print("\n[1/3] fetch_store_tier_rules...")
    try:
        rules = fetch_store_tier_rules(cfg)
    except Exception as e:
        print(f"  ❌ FAIL: {type(e).__name__}: {str(e)[:200]}")
        return 2
    cs = rules.get("config_snapshot", {})
    print(f"  ✅ version={cs.get('version')} | source_date={cs.get('config_source_date')} | total_count={cs.get('total_count')}")
    print(f"  tiers: {sorted((cs.get('tiers') or {}).keys())}")

    # 2. 准备样本
    samples: list[tuple[str, dict | None]] = []  # (shop_id, store_row)
    if args.auto_pick > 0:
        # 从门店维度表拉 N 条，按近30天下单金额 desc（覆盖高分位 + 低分位）
        dim = cfg["dimensions"]["store_table"]
        env = record_list(
            cfg, app_token=dim["app_token"], table_id=dim["table_id"],
            sort_json=json.dumps(
                [{"field": "近30天下单金额", "desc": True}], ensure_ascii=False
            ),
            limit=args.auto_pick,
        )
        for rec in env.records:
            sid = rec.get("店铺id") or rec.get("店铺ID")
            samples.append((str(sid), rec))
        print(f"\n[2/3] auto_pick {args.auto_pick} 样本 from 门店维度统计表 (sort 金额 desc)")

    # 用户指定店铺 id
    for sid in args.shop_ids.split(","):
        sid = sid.strip()
        if not sid:
            continue
        store_row = fetch_store_dimension(cfg, sid)
        samples.append((sid, store_row))

    if not samples:
        print("  ❌ 没样本")
        return 2

    # 3. compute_store_tier for each
    print(f"\n[3/3] compute_store_tier for {len(samples)} 样本")
    print("-" * 80)
    ok_count = 0
    fail_count = 0
    for sid, store_row in samples:
        tier, reason = compute_store_tier(cfg, store_row, rules)
        if tier in {"A", "B", "C", "D", "其他"}:
            ok_count += 1
            sym = "✅"
        else:
            fail_count += 1
            sym = "❌"
        # 关键统计字段
        stats = {
            f: store_row.get(f) for f in TIER_STAT_FIELDS if store_row
        } if store_row else {}
        print(f"  {sym} shop_id={sid:>10} | tier={tier!r:>8} | reason={reason!r}")
        if stats:
            # 紧凑展示 6 维
            s = " | ".join(f"{k}={v}" for k, v in list(stats.items())[:3])
            print(f"            {s}")

    print("-" * 80)
    print(f"  总样本={len(samples)} | 解析成功={ok_count} | 失败={fail_count}")
    if fail_count == 0:
        print("  ✅ 修法生效 — 全部样本能解析出 A/B/C/D/其他")
        return 0
    print(f"  ❌ {fail_count} 条未解析 — store_tier 修法未生效或部分降级")
    return 1


if __name__ == "__main__":
    sys.exit(main())
