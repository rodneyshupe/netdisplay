"""Prometheus-compatible HTTP API client (Prometheus, VictoriaMetrics, Mimir, Thanos...)."""
import json
import threading
import time
import urllib.parse
import urllib.request


class Datasource:
    def __init__(self, url, timeout=4, headers=None):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {}
        self.empty = set()          # queries that returned nothing (for `netdisplay validate`)
        self.errors = {}            # query -> error text
        self._lock = threading.Lock()

    def _get(self, path, params):
        req = urllib.request.Request("%s%s?%s" % (self.url, path, urllib.parse.urlencode(params)), headers=self.headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            body = json.load(r)
        if body.get("status") != "success":
            raise RuntimeError(body.get("error", "query failed"))
        return body["data"]["result"]

    def instant(self, expr):
        """-> list of (labels dict, float). Empty list on error or no data."""
        try:
            res = [(r["metric"], float(r["value"][1])) for r in self._get("/api/v1/query", {"query": expr})]
        except Exception as e:
            with self._lock:
                self.errors[expr] = str(e)
            return []
        if not res:
            with self._lock:
                self.empty.add(expr)
        return res

    def first(self, expr):
        r = self.instant(expr)
        return r[0][1] if r else None

    def range(self, expr, minutes=30, points=60):
        """-> list of floats from the first series."""
        end = time.time()
        try:
            res = self._get("/api/v1/query_range", {"query": expr, "start": end - minutes * 60, "end": end,
                                                    "step": max(15, int(minutes * 60 / points))})
        except Exception as e:
            with self._lock:
                self.errors[expr] = str(e)
            return []
        if not res:
            with self._lock:
                self.empty.add(expr)
            return []
        return [float(v) for _, v in res[0]["values"]]

    def alive(self):
        return self.first("vector(1)") is not None
