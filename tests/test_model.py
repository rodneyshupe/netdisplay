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


def test_episodes_status_window_and_sort():
    import time as _t
    now = _t.time()
    class S:
        def episodes(self, start, end):
            assert abs((end - start) - 24 * 3600) < 5
            return [{"id": 1, "show": "A", "season": 1, "episode": 2, "aired": now - 3600, "has_file": True},
                    {"id": 2, "show": "B", "season": 10, "episode": 11, "aired": now - 7200, "has_file": False},
                    {"id": 3, "show": "C", "season": 1, "episode": 1, "aired": now - 9000, "has_file": False},
                    {"id": 4, "show": "D", "season": 1, "episode": 1, "aired": now + 1800, "has_file": False}]
        def queued_ids(self):
            return {2}
    ds = FakeDS()
    ds.sonarr = S()
    wd = model.resolve_episodes(ds, {})
    assert [(r["name"], r["cells"][0]["text"], r["cells"][2]["text"]) for r in wd["rows"]] == [
        ("C", "S01E01", "missing"), ("B", "S10E11", "active"), ("A", "S01E02", "downloaded"), ("D", "S01E01", "upcoming")]
    assert wd["rows"][3]["cells"][1]["text"].startswith("in ") and wd["rows"][0]["cells"][1]["text"].endswith(" ago")
    by_status = model.resolve_episodes(ds, {"sort": "status", "limit": 2})
    assert [r["cells"][2]["text"] for r in by_status["rows"]] == ["active", "missing"]


def test_episodes_without_sonarr_is_contained():
    out = model.resolve_widget(FakeDS(), {"type": "episodes"})
    assert out["type"] == "text" and "sonarr" in out["text"]


def test_episodes_group_by_show_and_status_and_noon_window():
    import time as _t
    now = _t.time()
    seen = {}
    class S:
        def episodes(self, start, end):
            seen["w"] = (start, end)
            e = lambda i, show, n, ago, f: {"id": i, "show": show, "season": 2, "episode": n, "aired": now - ago * 3600, "has_file": f}
            return [e(1, "A", 1, 30, True), e(2, "A", 2, 29, True), e(3, "A", 3, 28, True), e(4, "A", 5, 27, True),
                    e(5, "A", 6, 5, False), e(6, "B", 1, 4, False)]
        def queued_ids(self):
            return {5}
    ds = FakeDS()
    ds.sonarr = S()
    wd = model.resolve_episodes(ds, {"from": "-1 12:00", "to": "+1 12:00", "sort": "status"})
    assert [(r["name"], r["cells"][0]["text"], r["cells"][2]["text"]) for r in wd["rows"]] == [
        ("A", "S02E06", "active"), ("B", "S02E01", "missing"), ("A", "S02E01-E03, E05", "downloaded")]
    start, end = seen["w"]
    assert 47 * 3600 <= end - start <= 49 * 3600 and start < now < end
    assert model._ep_range([(1, 5), (2, 1)]) == "S01E05, S02E01"


def test_movies_status_month_window_and_validation():
    import time as _t
    now = _t.time()
    seen = {}
    class R:
        def movies(self, start, end):
            seen["w"] = (start, end)
            m = lambda i, t, d, f, a: {"id": i, "title": t, "year": 2026, "released": now + d * 86400, "has_file": f, "available": a}
            return [m(1, "Got", -10, True, True), m(2, "Loading", -5, False, True), m(3, "Gone", -2, False, True), m(4, "Soon", 9, False, False)]
        def queued_ids(self):
            return {2}
    ds = FakeDS()
    ds.radarr = R()
    wd = model.resolve_movies(ds, {"sort": "status"})
    assert [(r["name"], r["cells"][1]["text"]) for r in wd["rows"]] == [
        ("Loading (2026)", "active"), ("Gone (2026)", "missing"), ("Soon (2026)", "upcoming"), ("Got (2026)", "downloaded")]
    start, end = seen["w"]
    assert 59 * 86400 <= end - start <= 94 * 86400 and start < now < end
    assert model.resolve_widget(FakeDS(), {"type": "movies"})["type"] == "text"


def test_movies_last_and_next():
    import time as _t
    now = _t.time()
    class R:
        def movies(self, start, end):
            assert end - start > 3 * 365 * 86400
            m = lambda i, t, d, f: {"id": i, "title": t, "year": 2026, "released": now + d * 86400, "has_file": f, "available": d <= 0}
            return [m(1, "Old", -400, True), m(2, "Recent", -30, True), m(3, "Soon", 20, False), m(4, "Far", 800, False)]
        def queued_ids(self):
            return set()
    ds = FakeDS()
    ds.radarr = R()
    wd = model.resolve_movies(ds, {"last": 1, "next": 1})
    assert [(r["name"], r["cells"][1]["text"]) for r in wd["rows"]] == [("Recent (2026)", "downloaded"), ("Soon (2026)", "upcoming")]
    assert len(model.resolve_movies(ds, {"next": 2})["rows"]) == 2
