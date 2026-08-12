"""envelope 双形态解包 + 类型 coerce（data_loader 纯函数层，无网络）。"""
import json

import pytest
from conftest import FIXTURES_DIR

import data_loader as dl


# ── envelope 解包（两种形态 + ok=false）──

def test_unwrap_outer_envelope():
    obj = json.loads((FIXTURES_DIR / "envelope_task.json").read_text(encoding="utf-8"))
    env = dl.unwrap_envelope(obj)
    assert env["fields"][0] == "升级售后单号"
    assert len(env["data"]) == 2


def test_unwrap_bare_envelope():
    obj = json.loads((FIXTURES_DIR / "envelope_product_dim.json").read_text(encoding="utf-8"))
    assert dl.unwrap_envelope(obj) is obj  # 裸 envelope 原样返回


def test_unwrap_ok_false_raises():
    with pytest.raises(dl.LarkCliError, match="not_found"):
        dl.unwrap_envelope({"ok": False, "error": {"message": "not_found"}})


def test_records_zip_and_record_ids(monkeypatch):
    """fields × data 行 zip 成 dict；record_id 对齐；formula 保 str。"""
    def fake_run(args, cfg, timeout=120):
        return json.loads((FIXTURES_DIR / "envelope_task.json").read_text(encoding="utf-8"))["data"]

    monkeypatch.setattr(dl, "run_lark_cli", fake_run)
    env = dl.record_list({}, app_token="X", table_id="tblY",
                         field_names=["升级售后单号"], limit=10)
    assert len(env.records) == 2
    assert env.records[0]["升级售后单号"] == "UAS900000000000000001"
    assert env.records[0]["升级售后提交间隔天数"] == "-1"  # formula 保 str
    assert env.record_ids == ["recSYNTH000000001", "recSYNTH000000002"]
    assert env.field_types["订单日期"] == "datetime"


# ── coerce（CSV 无 field_type_list 的类型处理）──

def test_coerce_number_int():
    assert dl.coerce_value("42", "number") == 42
    assert isinstance(dl.coerce_value("42", "number"), int)


def test_coerce_number_float():
    assert dl.coerce_value("77.43", "number") == 77.43


def test_coerce_number_invalid_kept():
    assert dl.coerce_value("abc", "number") == "abc"


def test_coerce_formula_kept_str():
    # 飞书 formula 字段返回字符串数字，不当数值用
    assert dl.coerce_value("0", "formula") == "0"
    assert dl.coerce_value("-1", "formula") == "-1"


def test_coerce_datetime_kept():
    v = "2026-08-01T00:00:00.000+08:00"
    assert dl.coerce_value(v, "datetime") == v


def test_coerce_empty_to_none():
    assert dl.coerce_value("", "text") is None
    assert dl.coerce_value("   ", "number") is None
    assert dl.coerce_value(None, "number") is None


def test_coerce_non_str_passthrough():
    assert dl.coerce_value(5, "number") == 5
    assert dl.coerce_value(1.5, "number") == 1.5


def test_to_number_formula_string():
    # apply_tier 需数值：30日售后赔付率 formula 字符串 → float
    assert dl._to_number("0.073312351") == 0.073312351
    assert dl._to_number("25") == 25
    assert dl._to_number(3.5) == 3.5
    assert dl._to_number("abc") == "abc"
