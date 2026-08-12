"""任务表拉取 = 视图「近两天数据」+ 客户端状态过滤（不拉全量）。

背景（2026-08-12 实测）：--filter-json 与 --view-id 同传时 filter-json 完全覆盖
视图过滤（时间窗丢失）→ 视图拉全量后客户端过滤 处理状态，limit 过滤后应用。
"""
import data_loader as dl


def _cfg(view_id="vewSYNTH", view_name="近两天数据", status_in=None):
    return {
        "task_table": {
            "app_token": "X", "table_id": "tblY",
            "fetch_view": {"id": view_id, "name": view_name},
        },
        "probe": {"task_fetch": {
            "field_names": ["升级售后单号", "处理状态"],
            "status_in": status_in if status_in is not None else ["未处理", "已处理-失败"],
        }},
    }


def _envelope_rows(rows):
    return {"data": rows,
            "fields": ["升级售后单号", "处理状态"],
            "field_type_list": ["text", "text"],
            "record_id_list": [f"rec{i}" for i in range(len(rows))],
            "has_more": False}


def test_record_list_passes_view_id(monkeypatch):
    captured = {}

    def fake_run(args, cfg, timeout=120):
        captured["args"] = args
        return _envelope_rows([["UAS1", "未处理"]])

    monkeypatch.setattr(dl, "run_lark_cli", fake_run)
    dl.record_list({}, app_token="X", table_id="tblY",
                   field_names=["升级售后单号"], view_id="vewSYNTH")
    args = captured["args"]
    assert "--view-id" in args
    assert args[args.index("--view-id") + 1] == "vewSYNTH"


def test_fetch_tasks_live_view_plus_client_status_filter(monkeypatch):
    rows = [["UAS1", "未处理"], ["UAS2", "已处理-成功"], ["UAS3", "未处理"],
            ["UAS4", "已处理-失败"], ["UAS5", "已处理-需人工"]]

    def fake_run(args, cfg, timeout=120):
        # 视图拉取不带 filter-json（防覆盖视图过滤）
        assert "--filter-json" not in args
        assert "--view-id" in args
        return _envelope_rows(rows)

    monkeypatch.setattr(dl, "run_lark_cli", fake_run)
    env = dl.fetch_tasks_live(_cfg(), limit=10)
    # 拉取范围 = 未处理 + 已处理-失败（兜底重试）；成功/需人工终态不拉
    assert [r["升级售后单号"] for r in env.records] == ["UAS1", "UAS3", "UAS4"]
    assert env.record_ids == ["rec0", "rec2", "rec3"]


def test_fetch_tasks_live_limit_after_filter(monkeypatch):
    rows = [["UAS1", "已处理-成功"], ["UAS2", "未处理"], ["UAS3", "已处理-失败"],
            ["UAS4", "未处理"]]

    def fake_run(args, cfg, timeout=120):
        return _envelope_rows(rows)

    monkeypatch.setattr(dl, "run_lark_cli", fake_run)
    env = dl.fetch_tasks_live(_cfg(), limit=2)
    assert [r["升级售后单号"] for r in env.records] == ["UAS2", "UAS3"]


def test_fetch_tasks_live_view_id_falls_back_to_name(monkeypatch):
    captured = {}

    def fake_run(args, cfg, timeout=120):
        captured["args"] = args
        return _envelope_rows([])

    monkeypatch.setattr(dl, "run_lark_cli", fake_run)
    cfg = _cfg(view_id=None)
    dl.fetch_tasks_live(cfg, limit=5)
    args = captured["args"]
    assert args[args.index("--view-id") + 1] == "近两天数据"


def test_fetch_tasks_live_missing_view_raises():
    cfg = {"task_table": {"app_token": "X", "table_id": "tblY"},
           "probe": {"task_fetch": {"field_names": []}}}
    try:
        dl.fetch_tasks_live(cfg, limit=5)
        assert False, "应抛 KeyError"
    except KeyError as e:
        assert "fetch_view" in str(e)
