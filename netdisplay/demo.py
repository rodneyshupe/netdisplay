"""Canned-data datasource for trying netdisplay without Prometheus, and for reproducible screenshots.

    netdisplay --demo examples/demo-data.yaml serve

The fixture file is a list of rules; the first rule whose `match` regex is found in a query wins:

    rules:
      - match: 'node_load1'
        series:
          - {labels: {instance: router}, value: 0.12}
        range: {base: 0.12, amp: 0.4, noise: 0.1}      # optional: shape of sparklines for this query
"""
import math
import random
import re

import yaml


class DemoDatasource:
    def __init__(self, path):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        self.rules = [(re.compile(r["match"]), r) for r in data.get("rules", [])]
        self.empty, self.errors, self.unmatched = set(), {}, set()

    def _rule(self, expr):
        for rx, rule in self.rules:
            if rx.search(expr):
                return rule
        self.unmatched.add(expr)
        return None

    def instant(self, expr):
        rule = self._rule(expr)
        out = [(dict(s.get("labels") or {}), float(s["value"])) for s in (rule or {}).get("series", [])]
        if not out:
            self.empty.add(expr)
        return out

    def first(self, expr):
        res = self.instant(expr)
        return res[0][1] if res else None

    def range(self, expr, minutes=30, points=60):
        rule = self._rule(expr)
        if not rule:
            self.empty.add(expr)
            return []
        shape = rule.get("range") or {}
        series = rule.get("series") or [{"value": 1.0}]
        base = float(shape.get("base", series[0]["value"]))
        amp, noise = float(shape.get("amp", 0.25)), float(shape.get("noise", 0.08))
        rng = random.Random(expr)               # deterministic per query, so screenshots are repeatable
        return [max(0.0, base * (1 + amp * math.sin(i / 7.0 + 1) + noise * (rng.random() - 0.5) * 2)) for i in range(points)]

    def alive(self):
        return True
