"""Value formatting and the tiny {name:format} template language used throughout the config."""
import re

FORMATS = ("num", "int", "bps", "Bps", "mbps", "bytes", "pct", "ratio", "dur", "ms", "celsius", "updown", "text")


def _scaled(v, units):
    for unit, div in units:
        if abs(v) >= div:
            return "%.1f %s" % (v / div, unit)
    return None


def fmt_value(v, fmt="num"):
    """Format a raw number (or a label string) for display. `fmt` may carry digits: 'num:2'."""
    if v is None:
        return "n/a"
    name, _, arg = (fmt or "num").partition(":")
    if name == "text" or isinstance(v, str):
        return str(v)
    if name in ("num", "int"):
        digits = int(arg) if arg else 0
        if name == "num" and not arg and not float(v).is_integer():
            digits = 2
        return ("{:,.%df}" % digits).format(v)
    if name == "bps":
        return _scaled(v, (("Gb/s", 1e9), ("Mb/s", 1e6), ("kb/s", 1e3))) or "%d b/s" % v
    if name == "Bps":
        return fmt_value(v, "bytes") + "/s"
    if name == "mbps":
        return "%d" % round(v / 1e6)
    if name == "bytes":
        return _scaled(v, (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("kB", 1e3))) or "%d B" % v
    if name == "pct":
        return "%.*f%%" % (int(arg) if arg else 0, v)
    if name == "ratio":
        return "%.*f%%" % (int(arg) if arg else 0, v * 100)
    if name == "dur":
        s = int(v)
        if s >= 86400:
            return "%dd %dh" % (s // 86400, s % 86400 // 3600)
        if s >= 3600:
            return "%dh %dm" % (s // 3600, s % 3600 // 60)
        return "%dm" % (s // 60) if s >= 60 else "%ds" % s
    if name == "ms":
        return "%.*f ms" % (int(arg) if arg else 0, v)
    if name == "celsius":
        return "%.*f°C" % (int(arg) if arg else 0, v)
    if name == "updown":
        return "up" if v >= 1 else "DOWN"
    raise ValueError("unknown format %r (choose from: %s)" % (fmt, ", ".join(FORMATS)))


_TEMPLATE = re.compile(r"\{(\w+)(?::([^{}]+))?\}")


def render(template, values, default_fmt="num"):
    """Fill {name} / {name:format} from `values` (floats, strings or None). Unknown names render as ''."""
    def sub(m):
        name, fmt = m.group(1), m.group(2)
        if name not in values:
            return ""
        return fmt_value(values[name], fmt or default_fmt)
    return _TEMPLATE.sub(sub, template)


def level(v, thresholds):
    """Colour name for a value. thresholds: {warn, bad} (higher is worse) or {warn_below, bad_below}."""
    if v is None or not thresholds:
        return "dim" if v is None else None
    if "bad_below" in thresholds or "warn_below" in thresholds:
        if "bad_below" in thresholds and v < thresholds["bad_below"]:
            return "bad"
        if "warn_below" in thresholds and v < thresholds["warn_below"]:
            return "warn"
        return "good"
    if "bad" in thresholds and v >= thresholds["bad"]:
        return "bad"
    if "warn" in thresholds and v >= thresholds["warn"]:
        return "warn"
    return "good"
