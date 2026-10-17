"""Command line entry point."""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import __version__, config, model, output
from .metrics import Datasource

DESCRIPTION = "Config-driven dashboard for a small LCD, a web page and the command line, fed by PromQL."


def _datasource(args, cfg):
    if args.demo:
        from .demo import DemoDatasource
        return DemoDatasource(args.demo)
    return Datasource(cfg["datasource"]["url"], cfg["datasource"]["timeout"], cfg["datasource"].get("headers"))


def _load(args):
    try:
        cfg = config.load(args.config)
    except config.ConfigError as e:
        sys.exit("config error: %s" % e)
    return cfg, _datasource(args, cfg)


def cmd_run(args):
    from . import lcd
    cfg, ds = _load(args)
    d = cfg["display"]
    steps = max(1, d["page_seconds"] // d["refresh_seconds"])
    visible, idx, alerts, alerts_at = [], 0, [], 0.0
    while True:
        if time.time() - alerts_at > 30:
            alerts, alerts_at = model.collect_alerts(cfg, ds), time.time()
        if idx == 0 or not visible:
            # once per rotation, find out which pages have data (hide_if_empty pages drop out)
            visible = [p["id"] for p in model.collect(cfg, ds, alerts=False)["pages"]] or [cfg["pages"][0]["id"]]
        pid = visible[idx % len(visible)]
        for _ in range(steps):
            try:
                page = model.collect(cfg, ds, only=[pid], alerts=False)["pages"][0]
                lcd.blit(lcd.render_page(page, idx % len(visible), len(visible), alerts, cfg), d["framebuffer"])
            except OSError as e:
                print("framebuffer write failed: %s" % e, file=sys.stderr)
            time.sleep(d["refresh_seconds"])
        idx = (idx + 1) % len(visible)


def cmd_show(args):
    cfg, ds = _load(args)
    ids = [p["id"] for p in cfg["pages"]]
    bad = [p for p in args.pages if p not in ids]
    if bad:
        sys.exit("unknown page %s (choose from: %s)" % (", ".join(bad), ", ".join(ids)))
    m = model.collect(cfg, ds, only=args.pages or None)
    if args.json:
        print(output.to_json(m, args.history))
    elif args.yaml:
        print(output.to_yaml(m, args.history), end="")
    else:
        print(output.pretty(m, sys.stdout.isatty() and not args.no_color))


def cmd_pages(args):
    cfg, _ = _load(args)
    for p in cfg["pages"]:
        print("%-14s %s" % (p["id"], p.get("title", "")))


def cmd_png(args):
    from . import lcd
    cfg, ds = _load(args)
    os.makedirs(args.dir, exist_ok=True)
    m = model.collect(cfg, ds)
    for i, p in enumerate(m["pages"]):
        lcd.render_page(p, i, len(m["pages"]), m["alerts"], cfg).save("%s/%d_%s.png" % (args.dir, i, p["id"]))
    print("wrote %d images to %s" % (len(m["pages"]), args.dir))


def cmd_serve(args):
    from . import web
    cfg, ds = _load(args)
    web.serve(cfg, ds, args.port)


def cmd_validate(args):
    """Check the config, the datasource, every query, and that each page fits the LCD."""
    from . import lcd
    try:
        cfg = config.load(args.config)
    except config.ConfigError as e:
        sys.exit("config error: %s" % e)
    ds = _datasource(args, cfg)
    bad = False
    for w in cfg["_warnings"]:
        print(w)
    print("config: %s (%d pages)" % (cfg["_path"], len(cfg["pages"])))
    if not ds.alive():
        print("error: datasource %s is not answering" % cfg["datasource"]["url"])
        sys.exit(1)
    print("datasource: %s ok" % ("demo data" if args.demo else cfg["datasource"]["url"]))
    with ThreadPoolExecutor(model.MAX_WORKERS) as pool:
        pages = [model.resolve_page(ds, p, pool) for p in cfg["pages"]]
    for p in pages:
        if p["hidden"]:
            print("note: page %r has hide_if_empty and no data right now, so it is not shown" % p["id"])
        _, overflow = lcd.layout(p, cfg["display"]["width"], cfg["display"]["height"])
        if overflow:
            print("warning: page %r is taller than the %dx%d display; the bottom is cut off on the LCD (the web page is fine)"
                  % (p["id"], cfg["display"]["width"], cfg["display"]["height"]))
    for expr, err in sorted(ds.errors.items()):
        print("error: query failed: %s\n         %s" % (expr, err))
        bad = True
    for expr in sorted(ds.empty - set(ds.errors)):
        print("warning: query returned no data: %s" % expr)
    print("ok" if not bad else "problems found")
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(prog="netdisplay", description=DESCRIPTION)
    ap.add_argument("-c", "--config", help="config file (default: $NETDISPLAY_CONFIG, ./netdisplay.yaml, "
                                           "~/.config/netdisplay/config.yaml, /etc/netdisplay/config.yaml)")
    ap.add_argument("--demo", metavar="FILE", help="read canned data from a demo fixture file instead of the datasource "
                                                   "(try it without Prometheus; see examples/demo-data.yaml)")
    ap.add_argument("--version", action="version", version="netdisplay " + __version__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run", help="run the rotating LCD display (default)")
    sp = sub.add_parser("show", help="print the dashboard data")
    sp.add_argument("pages", nargs="*", help="page ids (default: all)")
    fmt = sp.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="output JSON")
    fmt.add_argument("--yaml", action="store_true", help="output YAML")
    sp.add_argument("--history", action="store_true", help="include sparkline points in --json/--yaml")
    sp.add_argument("--no-color", action="store_true")
    sub.add_parser("pages", help="list page ids")
    sp = sub.add_parser("png", help="render every page to PNG files")
    sp.add_argument("dir")
    sp = sub.add_parser("serve", help="web dashboard + JSON API")
    sp.add_argument("--port", type=int, help="override web.port from the config")
    sub.add_parser("validate", help="check the config, datasource, queries and LCD layout")
    args = ap.parse_args()
    {"show": cmd_show, "pages": cmd_pages, "png": cmd_png, "serve": cmd_serve, "validate": cmd_validate}.get(args.cmd, cmd_run)(args)
