"""CSV 路径：表头名映射 + 类型 coerce + BOM + 未知列保守推断。"""
import csv

import data_loader as dl
from conftest import FIXTURES_DIR


def _cfg(aliases=None):
    return {"probe": {"csv_header_aliases": aliases or {}}}


def _write_task_csv(tmp_path, header, rows, bom=False):
    p = tmp_path / "tasks.csv"
    with open(p, "w", newline="", encoding="utf-8-sig" if bom else "utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def test_csv_header_mapping_and_coerce(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "load_field_types",
                        lambda path=None: {"task_table": {
                            "升级售后单号": "text", "诉求类型": "text",
                            "诉求赔付金额": "number", "订单日期": "datetime",
                            "是否商家问题": "number"}})
    p = _write_task_csv(
        tmp_path,
        ["升级售后单号", "诉求类型", "诉求赔付金额", "订单日期", "是否商家问题"],
        [["UAS900000000000000001", "退货", "77.43", "2026-08-01T00:00:00.000+08:00", "1"]])
    rows = dl.load_tasks_csv(p, _cfg())
    assert len(rows) == 1
    r = rows[0]
    assert r["升级售后单号"] == "UAS900000000000000001"
    assert r["诉求赔付金额"] == 77.43          # number coerce
    assert r["是否商家问题"] == 1              # number int
    assert r["订单日期"] == "2026-08-01T00:00:00.000+08:00"  # datetime 原样


def test_csv_bom_stripped(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "load_field_types",
                        lambda path=None: {"task_table": {"升级售后单号": "text"}})
    p = _write_task_csv(tmp_path, ["升级售后单号"], [["UAS_X"]], bom=True)
    rows = dl.load_tasks_csv(p, _cfg())
    assert rows[0]["升级售后单号"] == "UAS_X"   # BOM 不污染首列表头


def test_csv_alias_remapping(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "load_field_types",
                        lambda path=None: {"task_table": {"升级售后单号": "text"}})
    p = _write_task_csv(tmp_path, ["售后单号"], [["UAS_ALIAS"]])
    rows = dl.load_tasks_csv(p, _cfg(aliases={"售后单号": "升级售后单号"}))
    assert rows[0]["升级售后单号"] == "UAS_ALIAS"


def test_csv_unknown_column_guess(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(dl, "load_field_types", lambda path=None: {"task_table": {}})
    p = _write_task_csv(tmp_path, ["某未知列", "某未知文本"], [["123", "abc"]])
    import logging
    with caplog.at_level(logging.WARNING):
        rows = dl.load_tasks_csv(p, _cfg())
    assert rows[0]["某未知列"] == 123           # 保守推断为 int
    assert rows[0]["某未知文本"] == "abc"
    assert any("不在 field_types 快照" in m for m in caplog.messages)


def test_csv_empty_cell_to_none(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "load_field_types",
                        lambda path=None: {"task_table": {"诉求赔付金额": "number"}})
    p = _write_task_csv(tmp_path, ["诉求赔付金额"], [[""]])
    rows = dl.load_tasks_csv(p, _cfg())
    assert rows[0]["诉求赔付金额"] is None


def test_load_annotations_csv(tmp_path):
    p = tmp_path / "labels.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["升级售后单号", "agent1_store_expected", "备注"])
        w.writerow(["UAS900000000000000001", "应赔付", "人工标注"])
        w.writerow(["", "应退货", "无单号行应被丢弃"])
    ann = dl.load_annotations_csv(p)
    assert "UAS900000000000000001" in ann
    assert ann["UAS900000000000000001"]["agent1_store_expected"] == "应赔付"
    assert len(ann) == 1
