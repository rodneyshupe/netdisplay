import pytest

from netdisplay.fmt import fmt_value, level, render


@pytest.mark.parametrize("v,fmt,expected", [
    (283e6, "bps", "283.0 Mb/s"), (1.2e9, "bps", "1.2 Gb/s"), (900, "bps", "900 b/s"),
    (1.9e12, "bytes", "1.9 TB"), (1500, "Bps", "1.5 kB/s"), (296e6, "mbps", "296"),
    (46.4, "pct", "46%"), (46.46, "pct:1", "46.5%"), (0.5, "ratio", "50%"),
    (93784, "dur", "1d 2h"), (3700, "dur", "1h 1m"), (125, "dur", "2m"), (9, "dur", "9s"),
    (12.6, "ms", "13 ms"), (71.7, "celsius", "72°C"), (1, "updown", "up"), (0, "updown", "DOWN"),
    (16384, "num", "16,384"), (3.14159, "num:3", "3.142"), (2.5, "num", "2.50"), (7.0, "int", "7"),
])
def test_fmt_value(v, fmt, expected):
    assert fmt_value(v, fmt) == expected


def test_none_and_text():
    assert fmt_value(None, "bps") == "n/a"
    assert fmt_value("docker-network-3", "num") == "docker-network-3"


def test_unknown_format():
    with pytest.raises(ValueError):
        fmt_value(1, "bogus")


def test_render_template():
    out = render("↓{d:mbps} ↑{u:mbps} {age:dur} [{missing}] {v}", {"d": 296e6, "u": 66e6, "age": 540, "v": 3.0}, "num")
    assert out == "↓296 ↑66 9m [] 3"


def test_render_label_values_are_text():
    assert render("{instance}:{n}", {"instance": "dns1", "n": 5.0}) == "dns1:5"


def test_level():
    t = {"warn": 70, "bad": 90}
    assert (level(10, t), level(70, t), level(95, t), level(None, t)) == ("good", "warn", "bad", "dim")
    below = {"warn_below": 60}
    assert (level(50, below), level(80, below)) == ("warn", "good")
    assert level(5, {"bad_below": 100}) == "bad" and level(100, {"bad_below": 100}) == "good"
    assert level(5, None) is None
