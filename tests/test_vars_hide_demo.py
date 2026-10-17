import json
import os
import re
import subprocess
import sys

import pytest

from conftest import FakeDS
from netdisplay import cli, config, model
from netdisplay.demo import DemoDatasource

ROOT = os.path.join(os.path.dirname(__file__), "..")


def write(tmp_path, text, name="c.yaml"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


# ------------------------------------------------------------------ vars
def test_vars_are_substituted_everywhere(tmp_path):
    cfg = config.load(write(tmp_path, """
vars: {router: gw, dev: eth0, thr: 80}
alerts:
  rules: [{expr: 'up{instance="${router}"} == 0', message: '${router} down'}]
pages:
  - title: P
    rows:
      - {type: stat, label: 'WAN ${dev}', query: 'rate(x{instance="${router}",device="${dev}"}[1m])', thresholds: {warn: 70}}
      - {type: list, query: 'q', rename: [['^${router}-', '']]}
"""))
    w = cfg["pages"][0]["rows"][0][0]
    assert w["label"] == "WAN eth0" and w["query"] == 'rate(x{instance="gw",device="eth0"}[1m])'
    assert cfg["alerts"]["rules"][0] == {"expr": 'up{instance="gw"} == 0', "message": "gw down"}
    assert cfg["pages"][0]["rows"][1][0]["rename"] == [["^gw-", ""]]


def test_undefined_variable_is_an_error_that_names_it(tmp_path):
    with pytest.raises(config.ConfigError) as e:
        config.load(write(tmp_path, "pages:\n  - title: P\n    rows:\n      - {type: stat, query: 'x{i=\"${nope}\"}'}\n"))
    assert "${nope}" in str(e.value) and "vars" in str(e.value)


def test_vars_must_be_a_map(tmp_path):
    with pytest.raises(config.ConfigError):
        config.load(write(tmp_path, "vars: [a, b]\npages:\n  - title: P\n    rows: [[{type: text, text: x}]]\n"))


def test_single_brace_templates_are_untouched_by_vars(tmp_path):
    cfg = config.load(write(tmp_path, "vars: {a: 1}\npages:\n  - title: P\n    rows:\n      - {type: stat, query: q, label: 'x {v:pct} ${a}'}\n"))
    assert cfg["pages"][0]["rows"][0][0]["label"] == "x {v:pct} 1"


def test_unknown_top_level_and_page_keys_warn(tmp_path):
    cfg = config.load(write(tmp_path, "titel: oops\npages:\n  - {title: P, hide_if_emtpy: true, rows: [[{type: text, text: x}]]}\n"))
    joined = "\n".join(cfg["_warnings"])
    assert "unknown top-level key 'titel'" in joined and "unknown page key 'hide_if_emtpy'" in joined


# ------------------------------------------------------------------ hide_if_empty
def _cfg(pages):
    cfg = {"title": "t", "alerts": {"ignore": [], "rules": []}, "pages": pages}
    config.normalize(cfg)
    return cfg


DATA_PAGE = {"id": "data", "rows": [[{"type": "stat", "query": "a"}]]}
EMPTY_PAGE = {"id": "gone", "hide_if_empty": True, "rows": [[{"type": "stat", "query": "nothing"}, {"type": "text", "text": "x"}]]}


def test_page_with_no_data_is_hidden_only_when_asked():
    ds = FakeDS({"a": [({}, 1.0)]})
    shown = model.collect(_cfg([DATA_PAGE, EMPTY_PAGE]), ds)
    assert [p["id"] for p in shown["pages"]] == ["data"]
    keep = dict(EMPTY_PAGE, hide_if_empty=False)
    both = model.collect(_cfg([DATA_PAGE, keep]), ds)
    assert [p["id"] for p in both["pages"]] == ["data", "gone"] and both["pages"][1]["empty"] is True


def test_hidden_page_is_still_available_by_id_or_flag():
    ds, cfg = FakeDS({"a": [({}, 1.0)]}), _cfg([DATA_PAGE, EMPTY_PAGE])
    assert [p["id"] for p in model.collect(cfg, ds, only=["gone"])["pages"]] == ["gone"]
    assert [p["id"] for p in model.collect(cfg, ds, include_hidden=True)["pages"]] == ["data", "gone"]


def test_a_page_with_some_data_or_only_text_is_not_empty():
    ds = FakeDS({"a": [({}, 1.0)]})
    mixed = {"id": "m", "hide_if_empty": True, "rows": [[{"type": "stat", "query": "a"}, {"type": "stat", "query": "nothing"}]]}
    text_only = {"id": "t", "hide_if_empty": True, "rows": [[{"type": "text", "text": "hello"}]]}
    pages = model.collect(_cfg([mixed, text_only]), ds)["pages"]
    assert [p["id"] for p in pages] == ["m", "t"] and not any(p["empty"] for p in pages)


# ------------------------------------------------------------------ demo datasource
def test_demo_first_match_wins_and_tracks_unmatched(tmp_path):
    ds = DemoDatasource(write(tmp_path, """
rules:
  - {match: 'bad == 0$', series: []}
  - {match: 'node_load1', series: [{labels: {instance: a}, value: 0.5}]}
  - {match: 'node', series: [{value: 9}]}
""", "demo.yaml"))
    assert ds.instant('node_load1{x="y"}') == [({"instance": "a"}, 0.5)]
    assert ds.first("node_other") == 9.0
    assert ds.instant("bad == 0") == [] and ds.first("zzz") is None
    assert ds.unmatched == {"zzz"} and "bad == 0" in ds.empty and ds.alive()


def test_demo_range_is_deterministic_and_shaped(tmp_path):
    ds = DemoDatasource(write(tmp_path, "rules:\n  - {match: 'x', series: [{value: 100}], range: {base: 50, amp: 0.2, noise: 0}}\n", "d.yaml"))
    a, b = ds.range("x", points=30), ds.range("x", points=30)
    assert a == b and len(a) == 30 and 39 < min(a) and max(a) < 61


# ------------------------------------------------------------------ examples and snippets
def test_all_examples_and_snippets_load():
    for rel in ("examples/basic.yaml", "examples/homelab.yaml", "examples/snippets/technitium-dns.yaml", "examples/snippets/authentik-ha.yaml"):
        cfg = config.load(os.path.join(ROOT, rel))
        assert not [w for w in cfg["_warnings"] if w.startswith("error")], rel
        assert "${" not in json.dumps(cfg["pages"]) and "${" not in json.dumps(cfg["alerts"]), rel


def test_demo_data_covers_every_homelab_query():
    """If you add a query to homelab.yaml, add a rule to demo-data.yaml (the screenshots depend on it)."""
    cfg = config.load(os.path.join(ROOT, "examples/homelab.yaml"))
    ds = DemoDatasource(os.path.join(ROOT, "examples/demo-data.yaml"))
    m = model.collect(cfg, ds)
    assert ds.unmatched == set()
    assert [p["id"] for p in m["pages"]] == ["internet", "router", "hosts", "nas", "downloads", "services"]
    assert m["alerts"] == []


def test_cli_show_json_and_validate_with_demo(monkeypatch, capsys):
    base = ["netdisplay", "--demo", os.path.join(ROOT, "examples/demo-data.yaml"), "-c", os.path.join(ROOT, "examples/homelab.yaml")]
    monkeypatch.setattr(sys, "argv", base + ["show", "internet", "--json"])
    cli.main()
    out = json.loads(capsys.readouterr().out)
    assert [p["id"] for p in out["pages"]] == ["internet"] and out["pages"][0]["values"]["wan_down"] == 22.6e6
    monkeypatch.setattr(sys, "argv", base + ["validate"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0


# ------------------------------------------------------------------ repository hygiene
@pytest.mark.skipif(subprocess.call(["which", "bash"], stdout=subprocess.DEVNULL) != 0, reason="no bash")
def test_contrib_script_is_valid_bash():
    assert subprocess.call(["bash", "-n", os.path.join(ROOT, "contrib/authentik_metrics.sh")]) == 0


def test_no_personal_details_in_public_files():
    """Keep site-specific strings out of everything but LICENSE and this directory (tests use their own fixtures)."""
    deny = re.compile("|".join(["shu" + "pe", "milli" + "ways", r"192\.168\." + "27", "rod" + "ney"]), re.I)
    repo_url = "github.com/" + "rodney" + "shupe/netdisplay"      # the project's own public URL is fine (badge, clone URL)
    hits = []
    for top in ("README.md", "install.sh", "pyproject.toml", "examples", "contrib", "netdisplay", "systemd"):
        path = os.path.join(ROOT, top)
        files = [path] if os.path.isfile(path) else [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs]
        for f in files:
            if f.endswith((".png", ".pyc")):
                continue
            with open(f, errors="ignore") as fh:
                for n, line in enumerate(fh, 1):
                    if deny.search(line.replace(repo_url, "")):
                        hits.append("%s:%d: %s" % (os.path.relpath(f, ROOT), n, line.strip()[:80]))
    assert not hits, "personal details found:\n" + "\n".join(hits)
