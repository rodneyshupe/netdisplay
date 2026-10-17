"""Radarr API client: movies released in a time window, and which of them are downloading."""
import calendar
import time

from .sonarr import Sonarr


def _epoch(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) if s else None


class Radarr(Sonarr):
    def movies(self, start, end):
        """Monitored movies whose release date falls between start and end (epoch seconds).
        The release date is the earliest digital/physical release (when it can be downloaded), else the cinema date.
        -> list of dicts: id, title, year, released (epoch), has_file, available (Radarr says it can be grabbed now)."""
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        out = []
        for m in self._get("/calendar", {"start": iso(start), "end": iso(end)}):
            dates = [d for d in (_epoch(m.get("digitalRelease")), _epoch(m.get("physicalRelease"))) if d] \
                or [d for d in (_epoch(m.get("inCinemas")),) if d]
            if not dates or not start <= min(dates) < end:
                continue
            out.append({"id": m["id"], "title": m.get("title", "?"), "year": m.get("year"), "released": min(dates),
                        "has_file": bool(m.get("hasFile")), "available": bool(m.get("isAvailable"))})
        return out

    def queued_ids(self):
        data = self._get("/queue", {"page": 1, "pageSize": 500})
        return {r["movieId"] for r in data.get("records", []) if r.get("movieId") is not None}
