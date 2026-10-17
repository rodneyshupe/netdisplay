"""CLI output: pretty text, JSON and YAML views of the resolved model."""
import json

import yaml

MARK_OK, MARK_BAD, MARK_NONE = "✔", "✘", "·"


def jsonable(model, history=False):
    """Flat, layout-free view: pages[].widgets[] plus pages[].values{<widget id>: raw value}."""
    pages = []
    for p in model["pages"]:
        widgets = []
        for row in p["rows"]:
            for wd in row:
                wd = {k: v for k, v in wd.items() if k not in ("w", "h")}
                if wd["type"] == "spark" and not history:
                    wd.pop("values", None)
                widgets.append(wd)
        pages.append({"id": p["id"], "title": p["title"], "empty": p.get("empty", False), "values": p["values"], "widgets": widgets})
    return {"generated": model["generated"], "title": model["title"], "alerts": model["alerts"], "pages": pages}


def to_json(model, history=False):
    return json.dumps(jsonable(model, history), indent=2, ensure_ascii=False)


def to_yaml(model, history=False):
    return yaml.safe_dump(jsonable(model, history), sort_keys=False, allow_unicode=True, default_flow_style=False)


def _mark(ok, color):
    s = MARK_NONE if ok is None else MARK_OK if ok else MARK_BAD
    if not color:
        return s
    return "\033[%sm%s\033[0m" % ("90" if ok is None else "32" if ok else "31", s)


def pretty(model, color=False):
    bold = (lambda s: "\033[1m%s\033[0m" % s) if color else (lambda s: s)
    red = (lambda s: "\033[31m%s\033[0m" % s) if color else (lambda s: s)
    lines = [bold(model["title"]) + "  " + model["generated"][:16].replace("T", " ")]
    lines.append(red("ALERTS: " + "; ".join(model["alerts"])) if model["alerts"] else "No alerts.")
    for p in model["pages"]:
        lines += ["", bold("== %s ==" % p["title"])]
        for row in p["rows"]:
            for wd in row:
                lines += _widget(wd, color)
    return "\n".join(lines)


def _widget(wd, color):
    t = wd["type"]
    if t == "stat":
        extra = "  (%s)" % wd["sub"] if wd["sub"] else ""
        return ["%-34s %s%s" % (wd["label"], wd["text"], extra)]
    if t == "spark":
        vals = wd["values"]
        return ["%-34s now %s%s" % (wd["label"] or "trend", wd["now_text"],
                                    "  peak %s" % wd["peak_text"] if wd["peak_text"] else "")]
    if t == "bar":
        return ["%-34s %s" % (wd["label"], wd["text"])]
    if t == "text":
        return [wd["text"]]
    if t == "list":
        out = [wd["title"] + ":"] if wd["title"] else []
        if not wd["items"]:
            return out + ["  " + wd["empty_text"]]
        return out + ["  %s %s%s" % (_mark(i["ok"], color), i["name"], "  " + i["text"] if i["text"] else "") for i in wd["items"]]
    if t == "table":
        out = [wd["title"] + ":"] if wd["title"] else []
        if not wd["rows"]:
            return out + ["  " + wd["empty_text"]]
        heads = ["name"] + [c["header"] for c in wd["columns"]]
        raw = [[r["name"]] + [("x" if c["kind"] == "dot" else c["text"]) for c in r["cells"]] for r in wd["rows"]]
        shown = [[r["name"]] + [_mark(c["ok"], color) if c["kind"] == "dot" else c["text"] for c in r["cells"]] for r in wd["rows"]]
        w = [max(len(h), *(len(r[i]) for r in raw)) for i, h in enumerate(heads)]
        out.append("  " + "  ".join(h.ljust(w[i]) for i, h in enumerate(heads)))
        for sr, rr in zip(shown, raw):
            out.append("  " + "  ".join(sr[i] + " " * (w[i] - len(rr[i])) for i in range(len(heads))))
        return out
    return []

