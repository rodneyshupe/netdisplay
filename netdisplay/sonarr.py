"""Sonarr API client: episodes airing in a time window, and which of them are downloading.

Prometheus has no per-episode data (exportarr only gives counts), so the `episodes` widget reads Sonarr directly.
"""
import calendar
import json
import time
import urllib.parse
import urllib.request


class Sonarr:
    def __init__(self, url, api_key, timeout=6):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _get(self, path, params):
        req = urllib.request.Request("%s/api/v3%s?%s" % (self.url, path, urllib.parse.urlencode(params)),
                                     headers={"X-Api-Key": self.api_key})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def episodes(self, start, end):
        """Monitored episodes with an air date between start and end (epoch seconds).
        -> list of dicts: show, season, episode, aired (epoch), has_file, id."""
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        out = []
        for e in self._get("/calendar", {"start": iso(start), "end": iso(end), "includeSeries": "true"}):
            if not e.get("airDateUtc"):
                continue
            aired = calendar.timegm(time.strptime(e["airDateUtc"], "%Y-%m-%dT%H:%M:%SZ"))
            out.append({"id": e["id"], "show": (e.get("series") or {}).get("title", "?"), "season": e["seasonNumber"],
                        "episode": e["episodeNumber"], "aired": aired, "has_file": bool(e.get("hasFile"))})
        return out

    def queued_ids(self):
        """Episode ids currently in the download queue."""
        data = self._get("/queue", {"page": 1, "pageSize": 500})
        return {r["episodeId"] for r in data.get("records", []) if r.get("episodeId") is not None}
