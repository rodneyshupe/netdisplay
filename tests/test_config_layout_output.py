import json

import pytest
import yaml

from netdisplay import config, lcd, output


def write(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text)
    return str(p)


def test_example_configs_are_valid():
    for name in ("basic", "homelab"):
        cfg = config.load("examples/%s.yaml" % name)
        assert not [w for w in cfg["_warnings"] if w.startswith("error")]
        assert cfg["pages"]


def test_defaults_merged_and_ids_generated(tmp_path):
    cfg = config.load(write(tmp_path, "pages:\n  - title: My Page\n    rows:\n      - {type: text, text: hi}\n"))
    assert cfg["display"]["width"] == 480 and cfg["web"]["port"] == 80
    assert cfg["pages"][0]["id"] == "my_page" and cfg["pages"][0]["rows"] == [[{"type": "text", "text": "hi"}]]


@pytest.mark.parametrize("body,fragment", [
    ("pages: []\n", "at least one page"),
    ("pages:\n  - title: x\n    rows: [[{type: nope}]]\n", "`type` must be one of"),
    ("pages:\n  - title: x\n    rows: [[{type: stat}]]\n", "needs `query`"),
    ("pages:\n  - title: x\n    rows: [[{type: table, columns: [{header: a}]}]]\n", "needs a `query`"),
    ("pages:\n  - title: x\n    rows: [[{type: text, text: a, color: purple}]]\n", "color must be one of"),
    ("pages:\n  - {id: a, title: x, rows: [[{type: text, text: a}]]}\n  - {id: a, title: y, rows: [[{type: text, text: a}]]}\n", "duplicate page id"),
])
def test_config_errors(tmp_path, body, fragment):
    with pytest.raises(config.ConfigError) as e:
        config.load(write(tmp_path, body))
    assert fragment in str(e.value)


def test_unknown_key_is_a_warning_not_an_error(tmp_path):
    cfg = config.load(write(tmp_path, "pages:\n  - title: x\n    rows: [[{type: stat, query: q, lable: typo}]]\n"))
    assert any("unknown key 'lable'" in w for w in cfg["_warnings"])


def test_missing_config_message():
    with pytest.raises(config.ConfigError) as e:
        config.load("/nonexistent/file.yaml")
    assert "no config file found" in str(e.value)


def _wd(t, w, **kw):
    d = {"type": t, "w": w}
    d.update(kw)
    return d


def test_layout_grid_and_heights():
    page = {"rows": [[_wd("stat", 6), _wd("stat", 6)], [_wd("spark", 12)]]}
    placed, overflow = lcd.layout(page, 480, 320)
    assert not overflow
    (x1, y1, w1, h1, _), (x2, y2, w2, _, _), (_, y3, w3, _, _) = placed
    assert x1 == 10 and y1 == y2 == 38 and x2 > x1 + w1 and w3 > w1 * 2 and y3 == 38 + 62 + 8


def test_layout_overflow_and_web_only():
    big = {"rows": [[_wd("stat", 12)]] * 6}
    assert lcd.layout(big, 480, 320)[1] is True
    page = {"rows": [[_wd("stat", 12)], [_wd("table", 12, only="web", title="t", rows=[{}] * 30, columns=[])]]}
    placed, overflow = lcd.layout(page, 480, 320)
    assert len(placed) == 1 and not overflow


def test_heights_for_lists_and_tables():
    assert lcd.widget_height({"type": "list", "title": "T", "items": [1] * 5, "cols": 2}) == 16 + 3 * 22
    assert lcd.widget_height({"type": "list", "title": "", "items": [], "cols": 2}) == 18
    assert lcd.widget_height({"type": "table", "title": "", "rows": [1, 2], "columns": []}) == 14 + 2 * 24
    assert lcd.widget_height({"type": "stat", "h": 40}) == 40


MODEL = {"generated": "2026-10-16T20:00:00-0700", "title": "T", "alerts": ["x down"], "pages": [{
    "id": "p", "title": "P", "values": {"a": 1.0}, "rows": [[
        {"type": "stat", "w": 6, "id": "a", "label": "L", "text": "1", "color": "good", "sub": "", "raw": 1.0},
        {"type": "spark", "w": 6, "label": "S", "values": [1.0, 2.0], "color": "accent", "peak_text": "2", "now_text": "2", "raw": 2.0}],
        [{"type": "list", "w": 12, "title": "T", "items": [{"name": "a", "ok": True, "text": ""}], "cols": 1, "empty_text": "", "empty_color": "dim"}]]}]}


def test_json_and_yaml_outputs_agree_and_hide_history():
    j = json.loads(output.to_json(MODEL))
    assert j["alerts"] == ["x down"] and j["pages"][0]["values"] == {"a": 1.0}
    assert "values" not in j["pages"][0]["widgets"][1] and "w" not in j["pages"][0]["widgets"][0]
    assert yaml.safe_load(output.to_yaml(MODEL)) == j
    assert json.loads(output.to_json(MODEL, history=True))["pages"][0]["widgets"][1]["values"] == [1.0, 2.0]


def test_pretty_text():
    text = output.pretty(MODEL, color=False)
    assert "ALERTS: x down" in text and "== P ==" in text and "✔ a" in text and "now 2" in text
