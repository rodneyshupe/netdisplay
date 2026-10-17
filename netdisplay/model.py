"""Turn config + live metrics into a resolved model: pages -> rows -> widgets with ready-to-draw values.

Every renderer (LCD, web page, CLI text/JSON/YAML) works from this model, so they always agree.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor

from .fmt import fmt_value, level, render

MAX_WORKERS = 8


def _rename(s, rules):
    for pat, rep in rules or []:
        s = re.sub(pat, rep, s)
    return s


def _allowed(name, w):
    if w.get("include") and not re.search(w["include"], name):
        return False
    return not (w.get("exclude") and re.search(w["exclude"], name))


def _mapping(m):
    return {(k if k == "default" else int(k)): v for k, v in (m or {}).items()}


def _mapped(mapping, v):
    if not mapping or not isinstance(v, (int, float)):
        return None
    return mapping.get(int(round(v)), mapping.get("default"))


def resolve_stat(ds, w):
    queries = w.get("queries") or {"v": w["query"]}
    main = "v" if "v" in queries else next(iter(queries))
    vals = {}
    for name, expr in queries.items():
        res = ds.instant(expr)
        if name == main and w.get("value_label") and res:
            vals[name] = _rename(res[0][0].get(w["value_label"], ""), w.get("rename"))
        else:
            vals[name] = res[0][1] if res else None
    v, fmt = vals[main], w.get("format", "num")
    if v is None:
        text, color = w.get("empty_text", "n/a"), w.get("empty_color", "dim")
    else:
        m = _mapped(_mapping(w.get("map")), v)
        text = m["text"] if m and "text" in m else render(w.get("value", "{%s}" % main), vals, fmt)
        cv = vals.get(w["color_query"]) if w.get("color_query") else v
        color = w.get("color") or (m or {}).get("color") or (level(cv, w.get("thresholds")) if not isinstance(cv, str) else None) or "fg"
    return {"type": "stat", "label": render(w.get("label", ""), vals, fmt), "text": text, "color": color,
            "sub": render(w["sub"], vals, fmt) if w.get("sub") else "", "raw": v}


def resolve_spark(ds, w):
    vals = ds.range(w["query"], w.get("minutes", 30), w.get("points", 60))
    peak = max(vals) if vals else None
    return {"type": "spark", "label": w.get("label", ""), "values": vals, "color": w.get("color", "accent"),
            "peak_text": "" if peak is None else fmt_value(peak, w.get("format", "num")),
            "now_text": "n/a" if not vals else fmt_value(vals[-1], w.get("format", "num")),
            "raw": vals[-1] if vals else None}


def resolve_bar(ds, w):
    v = ds.first(w["query"])
    pct = None if v is None else v * w.get("scale", 1)
    return {"type": "bar", "label": w.get("label", ""), "pct": pct,
            "text": render(w.get("text", "{v:pct}"), {"v": pct}, "pct"),
            "color": w.get("color") or level(pct, w.get("thresholds")) or "good", "raw": pct}


def _ok(v, ok_if):
    if v is None:
        return None
    return v == 0 if ok_if == "zero" else v != 0 if ok_if == "nonzero" else v >= 1


def resolve_list(ds, w):
    fmt, items = w.get("format", "num"), []
    if "query" in w:
        for labels, v in ds.instant(w["query"]):
            vals = dict(labels)
            vals["value"] = v
            name = _rename(render(w.get("name", "{instance}"), vals, fmt), w.get("rename"))
            if _allowed(name, w):
                items.append({"name": name, "ok": _ok(v, w.get("ok_if")),
                              "text": render(w["text"], vals, fmt) if w.get("text") else ""})
    for it in w.get("items", []):
        v = ds.first(it["query"])
        items.append({"name": it["name"], "ok": _ok(v, w.get("ok_if")), "text": ""})
    sort = w.get("sort", "failing_first")
    if sort == "failing_first":
        items.sort(key=lambda i: (i["ok"] is not False, i["name"].lower()))
    elif sort == "name":
        items.sort(key=lambda i: i["name"].lower())
    if w.get("limit"):
        items = items[:w["limit"]]
    return {"type": "list", "title": w.get("title", ""), "items": items, "cols": w.get("cols", 2),
            "empty_text": w.get("empty_text", "none"), "empty_color": w.get("empty_color", "dim")}


def _cell(col, v):
    kind = col.get("kind", "text")
    if kind == "dot":
        return {"kind": "dot", "ok": None if v is None else v >= 1, "text": "", "raw": v}
    if kind == "bar":
        pct = None if v is None else v * col.get("scale", 1)
        return {"kind": "bar", "pct": pct, "text": fmt_value(pct, col.get("format", "pct")),
                "color": col.get("color") or level(pct, col.get("thresholds")) or "good", "raw": pct}
    m = _mapped(_mapping(col.get("map")), v)
    text = m["text"] if m and "text" in m else fmt_value(v, col.get("format", "num"))
    color = col.get("color") or (m or {}).get("color") or level(v, col.get("thresholds")) or "fg"
    return {"kind": "text", "text": text, "color": color, "raw": v}


def resolve_table(ds, w):
    key = w.get("key", "instance")
    cols = w["columns"]
    per_col, labels_of, order = [], {}, []
    for col in cols:
        got = {}
        for labels, v in ds.instant(col["query"]):
            k = labels.get(key, "")
            got.setdefault(k, v)
            labels_of.setdefault(k, labels)
            if k not in order:
                order.append(k)
        per_col.append(got)
    rows = []
    for k in order:
        name = _rename(render(w.get("name", "{%s}" % key), labels_of[k]), w.get("rename"))
        if _allowed(name, w):
            rows.append({"name": name, "cells": [_cell(c, got.get(k)) for c, got in zip(cols, per_col)]})
    if w.get("sort", "name") == "name":
        rows.sort(key=lambda r: r["name"].lower())
    if w.get("limit"):
        rows = rows[:w["limit"]]
    return {"type": "table", "title": w.get("title", ""), "rows": rows, "empty_text": w.get("empty_text", "no data"),
            "columns": [{"header": c.get("header", ""), "kind": c.get("kind", "text"), "width": c.get("width")} for c in cols]}


def resolve_text(ds, w):
    return {"type": "text", "text": w["text"], "color": w.get("color", "dim")}


RESOLVERS = {"stat": resolve_stat, "spark": resolve_spark, "bar": resolve_bar, "list": resolve_list,
             "table": resolve_table, "text": resolve_text}


def resolve_widget(ds, w):
    try:
        out = RESOLVERS[w["type"]](ds, w)
    except Exception as e:  # one bad widget must not blank the page
        out = {"type": "text", "text": "%s widget error: %s" % (w.get("type"), e), "color": "bad"}
    if w.get("id"):
        out["id"] = w["id"]
    if "h" in w:
        out["h"] = w["h"]
    if w.get("only"):
        out["only"] = w["only"]
    return out


def _value_of(wd):
    """Raw value exposed under page.values.<widget id>."""
    t = wd["type"]
    if t in ("stat", "spark", "bar"):
        return wd["raw"]
    if t == "list":
        return wd["items"]
    if t == "table":
        heads = [c["header"] or "col%d" % i for i, c in enumerate(wd["columns"])]
        return [dict([("name", r["name"])] + [(h, c.get("raw")) for h, c in zip(heads, r["cells"])]) for r in wd["rows"]]
    return None


def _has_data(wd):
    """True/False for widgets that query data, None for ones that don't (text)."""
    t = wd["type"]
    if t == "stat":
        return wd["raw"] is not None
    if t == "spark":
        return bool(wd["values"])
    if t == "bar":
        return wd["pct"] is not None
    if t == "list":
        return any(i["ok"] is not None for i in wd["items"])
    if t == "table":
        return bool(wd["rows"])
    return None


def resolve_page(ds, page, pool):
    flat = [(ri, w) for ri, row in enumerate(page["rows"]) for w in row]
    results = list(pool.map(lambda t: resolve_widget(ds, t[1]), flat))
    rows = [[] for _ in page["rows"]]
    values = {}
    for (ri, w), res in zip(flat, results):
        res["w"] = w.get("w", 12.0 / len(page["rows"][ri]))
        rows[ri].append(res)
        if res.get("id"):
            values[res["id"]] = _value_of(res)
    flags = [f for row in rows for f in map(_has_data, row) if f is not None]
    empty = bool(flags) and not any(flags)
    return {"id": page["id"], "title": page.get("title", page["id"]), "rows": rows, "values": values,
            "empty": empty, "hidden": bool(page.get("hide_if_empty")) and empty}


def collect_alerts(cfg, ds):
    if not ds.alive():
        return ["metrics server unreachable"]
    msgs = []
    for rule in cfg["alerts"]["rules"]:
        for labels, v in ds.instant(rule["expr"]):
            vals = dict(labels)
            vals["value"] = v
            msgs.append(render(rule.get("message", rule.get("name", "alert")), vals, rule.get("format", "num")))
    ignore = [re.compile(p) for p in cfg["alerts"]["ignore"]]
    seen, out = set(), []
    for m in msgs:
        if m not in seen and not any(p.search(m) for p in ignore):
            seen.add(m)
            out.append(m)
    return out


def collect(cfg, ds, only=None, alerts=True, include_hidden=False):
    """Resolve the whole model (or only the page ids in `only`).

    Pages with `hide_if_empty: true` whose widgets all came back without data are left out,
    unless they were asked for by id or include_hidden is set."""
    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        pages = [resolve_page(ds, p, pool) for p in cfg["pages"] if not only or p["id"] in only]
    if not (only or include_hidden):
        pages = [p for p in pages if not p["hidden"]]
    return {"generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "title": cfg["title"],
            "alerts": collect_alerts(cfg, ds) if alerts else [], "pages": pages}
