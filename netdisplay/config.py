"""Config file loading, defaults and validation."""
import copy
import os
import re

try:
    import yaml
except ImportError:  # pragma: no cover
    raise SystemExit("netdisplay needs PyYAML: apt install python3-yaml  (or: pip install pyyaml)")

SEARCH = ("./netdisplay.yaml", "~/.config/netdisplay/config.yaml", "/etc/netdisplay/config.yaml")

TOP_KEYS = {"title", "vars", "datasource", "display", "web", "alerts", "pages"}
PAGE_KEYS = {"id", "title", "rows", "hide_if_empty"}
_VAR = re.compile(r"\$\{(\w+)\}")

DEFAULTS = {
    "title": "Network status",
    "datasource": {"url": "http://localhost:9090", "timeout": 4, "headers": {}},
    "display": {"framebuffer": "/dev/fb1", "width": 480, "height": 320, "page_seconds": 10,
                "refresh_seconds": 5, "font_dir": "/usr/share/fonts/truetype/dejavu"},
    "web": {"port": 80, "cache_seconds": 5},
    "alerts": {"ignore": [], "rules": []},
    "pages": [],
}

_COMMON = {"type", "id", "w", "h", "only"}
WIDGETS = {
    "stat": _COMMON | {"label", "query", "queries", "value", "format", "sub", "thresholds", "color", "color_query",
                       "map", "value_label", "rename", "empty_text", "empty_color"},
    "spark": _COMMON | {"label", "query", "minutes", "points", "format", "color"},
    "bar": _COMMON | {"label", "query", "scale", "text", "thresholds", "color"},
    "list": _COMMON | {"title", "query", "items", "name", "ok_if", "text", "format", "exclude", "include", "sort",
                       "limit", "cols", "empty_text", "empty_color", "rename"},
    "table": _COMMON | {"title", "key", "name", "rename", "columns", "exclude", "include", "sort", "limit",
                        "empty_text", "empty_color"},
    "text": _COMMON | {"text", "color"},
}
COLUMN_KEYS = {"header", "query", "kind", "format", "thresholds", "map", "scale", "width", "color"}
COLORS = ("good", "warn", "bad", "accent", "accent2", "dim", "fg")


class ConfigError(Exception):
    pass


def find_config(path=None):
    cands = [path] if path else [os.environ.get("NETDISPLAY_CONFIG")] + list(SEARCH)
    for c in cands:
        if c and os.path.isfile(os.path.expanduser(c)):
            return os.path.expanduser(c)
    raise ConfigError("no config file found (looked in: %s). Use --config or NETDISPLAY_CONFIG; "
                      "start from examples/basic.yaml" % ", ".join([path] if path else SEARCH))


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def substitute_vars(node, variables, where=""):
    """Replace ${name} in every string of the config with the value from the top-level `vars:` map."""
    if isinstance(node, str):
        def sub(m):
            if m.group(1) not in variables:
                raise ConfigError("undefined variable ${%s} in %s (define it under `vars:`)" % (m.group(1), where or "config"))
            return str(variables[m.group(1)])
        return _VAR.sub(sub, node)
    if isinstance(node, list):
        return [substitute_vars(x, variables, where) for x in node]
    if isinstance(node, dict):
        return {k: substitute_vars(v, variables, "%s.%s" % (where, k) if where else str(k)) for k, v in node.items()}
    return node


def load(path=None):
    path = find_config(path)
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError("%s: invalid YAML: %s" % (path, e))
    variables = raw.get("vars") or {}
    if not isinstance(variables, dict):
        raise ConfigError("%s: `vars` must be a map of name: value" % path)
    raw = substitute_vars({k: v for k, v in raw.items() if k != "vars"}, variables)
    raw["vars"] = variables
    cfg = _merge(DEFAULTS, raw)
    if os.environ.get("NETDISPLAY_FONT_DIR"):
        cfg["display"]["font_dir"] = os.environ["NETDISPLAY_FONT_DIR"]
    cfg["_path"] = path
    problems = validate(cfg)
    errors = [p for p in problems if p.startswith("error")]
    if errors:
        raise ConfigError("%s:\n  %s" % (path, "\n  ".join(errors)))
    cfg["_warnings"] = problems
    normalize(cfg)
    return cfg


def normalize(cfg):
    """rows may hold a bare widget dict; pages get an id from their title."""
    for p in cfg["pages"]:
        p["rows"] = [r if isinstance(r, list) else [r] for r in p["rows"]]
        p.setdefault("id", re.sub(r"\W+", "_", p.get("title", "page")).strip("_").lower())


def validate(cfg):
    out = []
    err = lambda where, msg: out.append("error: %s: %s" % (where, msg))
    warn = lambda where, msg: out.append("warning: %s: %s" % (where, msg))
    if not isinstance(cfg.get("pages"), list) or not cfg["pages"]:
        err("pages", "at least one page is required")
        return out
    for k in cfg:
        if k not in TOP_KEYS and not k.startswith("_"):
            warn("config", "unknown top-level key %r (typo?)" % k)
    seen = set()
    for pi, page in enumerate(cfg["pages"]):
        where = "pages[%d]" % pi
        if not isinstance(page, dict) or not page.get("rows"):
            err(where, "needs a title and a non-empty `rows` list")
            continue
        for k in page:
            if k not in PAGE_KEYS:
                warn(where, "unknown page key %r (typo?)" % k)
        pid = page.get("id") or re.sub(r"\W+", "_", page.get("title", "")).strip("_").lower()
        if pid in seen:
            err(where, "duplicate page id %r" % pid)
        seen.add(pid)
        for ri, row in enumerate(page["rows"]):
            for wi, w in enumerate(row if isinstance(row, list) else [row]):
                ww = "page %r row %d widget %d" % (pid, ri + 1, wi + 1)
                if not isinstance(w, dict) or w.get("type") not in WIDGETS:
                    err(ww, "`type` must be one of: %s" % ", ".join(WIDGETS))
                    continue
                t = w["type"]
                for k in w:
                    if k not in WIDGETS[t]:
                        warn(ww, "unknown key %r for a %s widget (typo?)" % (k, t))
                need = {"stat": ("query", "queries"), "spark": ("query",), "bar": ("query",),
                        "list": ("query", "items"), "table": ("columns",), "text": ("text",)}[t]
                if not any(k in w for k in need):
                    err(ww, "%s widget needs %s" % (t, " or ".join("`%s`" % n for n in need)))
                for c in w.get("columns", []) if t == "table" else []:
                    for k in c:
                        if k not in COLUMN_KEYS:
                            warn(ww, "unknown column key %r" % k)
                    if "query" not in c:
                        err(ww, "every table column needs a `query`")
                if w.get("only") not in (None, "lcd", "web"):
                    err(ww, "only must be `lcd` or `web`")
                for key in ("color", "empty_color"):
                    if w.get(key) not in (None,) + COLORS:
                        err(ww, "%s must be one of: %s" % (key, ", ".join(COLORS)))
    return out
