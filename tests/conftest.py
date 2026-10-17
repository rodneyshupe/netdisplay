import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class FakeDS:
    """Stands in for metrics.Datasource: maps an exact query string to canned series."""

    def __init__(self, data=None, ranges=None):
        self.data, self.ranges = data or {}, ranges or {}
        self.empty, self.errors = set(), {}

    def instant(self, expr):
        res = self.data.get(expr, [])
        if not res:
            self.empty.add(expr)
        return res

    def first(self, expr):
        r = self.instant(expr)
        return r[0][1] if r else None

    def range(self, expr, minutes=30, points=60):
        return self.ranges.get(expr, [])

    def alive(self):
        return True
