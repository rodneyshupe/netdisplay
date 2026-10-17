from conftest import FakeDS
from netdisplay import model


def test_stat_basic_and_thresholds():
    ds = FakeDS({"q": [({}, 93.0)]})
    wd = model.resolve_stat(ds, {"query": "q", "format": "pct", "label": "CPU", "thresholds": {"warn": 70, "bad": 90}})
    assert (wd["text"], wd["color"], wd["label"], wd["raw"]) == ("93%", "bad", "CPU", 93.0)


def test_stat_no_data():
    wd = model.resolve_stat(FakeDS(), {"query": "q", "empty_text": "NONE", "empty_color": "bad"})
    assert (wd["text"], wd["color"], wd["raw"]) == ("NONE", "bad", None)


def test_stat_templates_and_color_query():
    ds = FakeDS({"d": [({}, 296e6)], "u": [({}, 66e6)], "age": [({}, 540.0)], "vs": [({}, 50.0)]})
    wd = model.resolve_stat(ds, {"queries": {"d": "d", "u": "u", "age": "age", "vs": "vs"}, "label": "RUN {age:dur} ago",
                                 "value": "↓{d:mbps} ↑{u:mbps}", "sub": "age {age:dur}",
                                 "color_query": "vs", "thresholds": {"warn_below": 60}})
    assert (wd["label"], wd["text"], wd["sub"], wd["color"]) == ("RUN 9m ago", "↓296 ↑66", "age 9m", "warn")


def test_stat_value_label_rename_and_map():
    ds = FakeDS({"vip": [({"instance": "docker-network-3"}, 1.0)], "h": [({}, 0.0)]})
    wd = model.resolve_stat(ds, {"query": "vip", "value_label": "instance", "rename": [["^docker-", ""]], "color": "good"})
    assert (wd["text"], wd["color"]) == ("network-3", "good")
    wd = model.resolve_stat(ds, {"query": "h", "map": {1: {"text": "healthy", "color": "good"}, 0: {"text": "ISSUES", "color": "bad"}}})
    assert (wd["text"], wd["color"]) == ("ISSUES", "bad")
    wd = model.resolve_stat(ds, {"query": "h", "map": {1: {"text": "ok"}, "default": {"text": "weird", "color": "warn"}}})
    assert (wd["text"], wd["color"]) == ("weird", "warn")      # 0 is not mapped -> the "default" entry


def test_bar_and_spark():
    ds = FakeDS({"m": [({}, 0.5)]}, {"s": [1.0, 4.0, 2.0]})
    bar = model.resolve_bar(ds, {"query": "m", "scale": 100, "thresholds": {"warn": 40, "bad": 90}})
    assert (bar["pct"], bar["text"], bar["color"]) == (50.0, "50%", "warn")
    sp = model.resolve_spark(ds, {"query": "s", "format": "bps"})
    assert (sp["values"], sp["peak_text"], sp["now_text"], sp["raw"]) == ([1.0, 4.0, 2.0], "4 b/s", "2 b/s", 2.0)


def test_list_sorting_filter_and_empty():
    ds = FakeDS({"up": [({"n": "b"}, 1.0), ({"n": "a"}, 0.0), ({"n": "skip-me"}, 1.0), ({"n": "c"}, 1.0)]})
    wd = model.resolve_list(ds, {"query": "up", "name": "{n}", "exclude": "^skip"})
    assert [(i["name"], i["ok"]) for i in wd["items"]] == [("a", False), ("b", True), ("c", True)]
    wd = model.resolve_list(FakeDS(), {"query": "up", "empty_text": "all good", "empty_color": "good"})
    assert wd["items"] == [] and wd["empty_text"] == "all good"


def test_list_static_items_and_ok_if():
    ds = FakeDS({"x": [({}, 0.0)]})
    wd = model.resolve_list(ds, {"items": [{"name": "RAID", "query": "x"}, {"name": "missing", "query": "y"}], "ok_if": "zero", "sort": "none"})
    assert [(i["name"], i["ok"]) for i in wd["items"]] == [("RAID", True), ("missing", None)]


def test_table_join_by_label_and_kinds():
    ds = FakeDS({"up": [({"id": "node/pve-1"}, 1.0), ({"id": "node/pve-2"}, 0.0)],
                 "cpu": [({"id": "node/pve-1"}, 0.42)]})
    wd = model.resolve_table(ds, {"key": "id", "rename": [["^node/", ""]], "columns": [
        {"header": "up", "kind": "dot", "query": "up"},
        {"header": "cpu", "kind": "bar", "scale": 100, "thresholds": {"warn": 70}, "query": "cpu"}]})
    assert [r["name"] for r in wd["rows"]] == ["pve-1", "pve-2"]
    assert wd["rows"][0]["cells"][0]["ok"] is True and wd["rows"][1]["cells"][0]["ok"] is False
    assert wd["rows"][0]["cells"][1]["pct"] == 42.0 and wd["rows"][1]["cells"][1]["pct"] is None


def test_widget_error_is_contained():
    class Boom(FakeDS):
        def instant(self, expr):
            raise RuntimeError("boom")
    wd = model.resolve_widget(Boom(), {"type": "stat", "query": "q", "id": "x"})
    assert wd["type"] == "text" and "boom" in wd["text"] and wd["id"] == "x"


def test_alerts_dedupe_ignore_and_template():
    ds = FakeDS({"r1": [({"instance": "a"}, 0.0), ({"instance": "a"}, 0.0), ({"instance": "Kodi Server"}, 0.0)],
                 "r2": [({"instance": "n1"}, 0.95)]})
    cfg = {"alerts": {"ignore": ["^Kodi"], "rules": [
        {"expr": "r1", "message": "{instance} down"},
        {"expr": "r2", "message": "{instance} disk {value:ratio}"}]}}
    assert model.collect_alerts(cfg, ds) == ["a down", "n1 disk 95%"]


def test_resolve_page_values_and_widths():
    from concurrent.futures import ThreadPoolExecutor
    ds = FakeDS({"a": [({}, 1.0)], "b": [({}, 2.0)]})
    page = {"id": "p", "title": "P", "rows": [[{"type": "stat", "id": "a", "query": "a"}, {"type": "stat", "query": "b", "w": 8}]]}
    with ThreadPoolExecutor(2) as pool:
        out = model.resolve_page(ds, page, pool)
    assert out["values"] == {"a": 1.0}
    assert [w["w"] for w in out["rows"][0]] == [6.0, 8]
