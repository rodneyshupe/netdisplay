"""Web dashboard + JSON API (stdlib http.server, no extra dependencies)."""
import io
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import model

INDEX = os.path.join(os.path.dirname(os.path.realpath(__file__)), "web", "index.html")


class Snapshot:
    """Collect at most once per `ttl` seconds however many browsers are open."""

    def __init__(self, cfg, ds):
        self.cfg, self.ds, self.ttl = cfg, ds, cfg["web"]["cache_seconds"]
        self.data, self.t, self.lock = None, 0.0, threading.Lock()

    def get(self):
        with self.lock:
            if self.data is None or time.time() - self.t > self.ttl:
                self.data = model.collect(self.cfg, self.ds)
                self.t = time.time()
            return self.data


def serve(cfg, ds, port=None):
    snap = Snapshot(cfg, ds)
    port = port or cfg["web"]["port"]

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def js(self, obj):
            self.send(200, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            path = url.path.rstrip("/") or "/"
            ids = [p["id"] for p in cfg["pages"]]
            try:
                if path == "/":
                    with open(INDEX, "rb") as f:
                        html = f.read().replace(b"{{TITLE}}", cfg["title"].encode())
                    return self.send(200, html, "text/html; charset=utf-8")
                if path == "/healthz":
                    return self.send(200, b"ok\n", "text/plain")
                if path == "/api/pages":
                    return self.js([{"id": p["id"], "title": p.get("title", p["id"])} for p in cfg["pages"]])
                if path == "/api/all":
                    return self.js(snap.get())
                if path.startswith("/api/") and path[5:] in ids:
                    data = snap.get()
                    page = next(p for p in data["pages"] if p["id"] == path[5:])
                    return self.js({"generated": data["generated"], "alerts": data["alerts"], "page": page})
                if path == "/screen.png":
                    from . import lcd
                    data = snap.get()
                    pid = urllib.parse.parse_qs(url.query).get("page", [ids[0]])[0]
                    pages = data["pages"]
                    idx = next((i for i, p in enumerate(pages) if p["id"] == pid), None)
                    if idx is None:
                        return self.send(404, b"unknown page\n", "text/plain")
                    buf = io.BytesIO()
                    lcd.render_page(pages[idx], idx, len(pages), data["alerts"], cfg).save(buf, "PNG")
                    return self.send(200, buf.getvalue(), "image/png")
                self.send(404, b"not found\n", "text/plain")
            except Exception as e:
                self.send(500, ("error: %s\n" % e).encode(), "text/plain")

        def log_message(self, fmt, *a):
            pass

    print("netdisplay web on http://0.0.0.0:%d" % port, flush=True)
    ThreadingHTTPServer(("", port), Handler).serve_forever()
