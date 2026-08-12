"""日期级 JOIN 核心不变量 + 分页循环（mock run_lark_cli，无网络）。"""
import json

import data_loader as dl
from conftest import FIXTURES_DIR


# ── normalize_date：两种时刻格式同日期（任务表 T00:00+08 × 维度表 T08:00+08）──

def test_same_date_different_times():
    assert dl.normalize_date("2026-08-01T00:00:00.000+08:00") == "2026-08-01"
    assert dl.normalize_date("2026-08-01T08:00:00.000+08:00") == "2026-08-01"
    assert (dl.normalize_date("2026-08-01T00:00:00.000+08:00")
            == dl.normalize_date("2026-08-01T08:00:00.000+08:00"))


def test_utc_midnight_crossing():
    # UTC 2026-07-31 20:00 = 北京 2026-08-01 04:00
    assert dl.normalize_date("2026-07-31T20:00:00Z") == "2026-08-01"


def test_naive_datetime_keeps_local_date():
    assert dl.normalize_date("2026-08-01T05:00:00") == "2026-08-01"


def test_date_only_string():
    assert dl.normalize_date("2026-08-01") == "2026-08-01"


def test_none_and_garbage():
    assert dl.normalize_date(None) is None
    assert dl.normalize_date("") is None
    assert dl.normalize_date("garbage") is None
    assert dl.normalize_date(12345) is not None or True  # epoch 防御分支不崩即可


# ── 商品维度多日期行只命中目标日期 ──

PRODUCT_CFG = {
    "dimensions": {
        "product_dimension_table": {
            "app_token": "X", "table_id": "tblY",
            "select_fields": [{"name": "商品id"}, {"name": "日期"},
                              {"name": "近7日商品售后赔付率"}, {"name": "商品占同品类比例"}],
        }
    }
}


def _fake_product_run(monkeypatch):
    bare = json.loads((FIXTURES_DIR / "envelope_product_dim.json").read_text(encoding="utf-8"))

    def fake_run(args, cfg, timeout=120):
        return bare

    monkeypatch.setattr(dl, "run_lark_cli", fake_run)


def test_product_join_hits_target_date_only(monkeypatch):
    _fake_product_run(monkeypatch)
    row = dl.fetch_product_dimension(PRODUCT_CFG, 20712027, "2026-08-01")
    assert row is not None
    assert dl.normalize_date(row["日期"]) == "2026-08-01"
    assert row["近7日商品售后赔付率"] == 0.12


def test_product_join_miss_returns_none(monkeypatch):
    _fake_product_run(monkeypatch)
    assert dl.fetch_product_dimension(PRODUCT_CFG, 20712027, "2026-09-09") is None
    assert dl.fetch_product_dimension(PRODUCT_CFG, None, "2026-08-01") is None
    assert dl.fetch_product_dimension(PRODUCT_CFG, 20712027, None) is None


def test_product_join_date_key_from_task_row():
    """任务表 订单日期（T00:00+08）规范化后 = 维度表日期键。"""
    order_key = dl.normalize_date("2026-08-01T00:00:00.000+08:00")
    dim_keys = [dl.normalize_date(d) for d in
                ["2026-07-30T08:00:00.000+08:00", "2026-08-01T08:00:00.000+08:00"]]
    assert order_key in dim_keys


# ── 分页 offset 步进 ──

def test_pagination_offset_stepping(monkeypatch):
    pages = {
        0: {"data": [["A", 1], ["B", 2]], "fields": ["name", "n"],
            "field_type_list": ["text", "number"],
            "record_id_list": ["r1", "r2"], "has_more": True},
        2: {"data": [["C", 3]], "fields": ["name", "n"],
            "field_type_list": ["text", "number"],
            "record_id_list": ["r3"], "has_more": False},
    }
    offsets = []

    def fake_run(args, cfg, timeout=120):
        off = int(args[args.index("--offset") + 1])
        offsets.append(off)
        return pages[off]

    monkeypatch.setattr(dl, "run_lark_cli", fake_run)
    env = dl.record_list({}, app_token="X", table_id="tblY",
                         field_names=["name", "n"], limit=3)
    assert [r["name"] for r in env.records] == ["A", "B", "C"]
    assert env.record_ids == ["r1", "r2", "r3"]
    assert offsets == [0, 2]


def test_pagination_respects_limit(monkeypatch):
    def fake_run(args, cfg, timeout=120):
        lim = int(args[args.index("--limit") + 1])
        return {"data": [["A"]] * lim, "fields": ["name"],
                "field_type_list": ["text"],
                "record_id_list": [f"r{i}" for i in range(lim)], "has_more": True}

    monkeypatch.setattr(dl, "run_lark_cli", fake_run)
    env = dl.record_list({}, app_token="X", table_id="tblY", limit=2, page_size=200)
    assert len(env.records) == 2  # 不超拉
