"""Draw the resolved model onto a small LCD: Pillow image -> RGB565 -> Linux framebuffer."""
import math
import os
import time
from array import array

GAP = 8
MARGIN = 10
HEADER_H = 30
BANNER_H = 26

PALETTE = {
    "bg": (14, 17, 22), "panel": (28, 33, 41), "fg": (232, 236, 241), "dim": (130, 140, 152),
    "good": (74, 201, 120), "warn": (240, 180, 50), "bad": (240, 84, 84),
    "accent": (80, 170, 255), "accent2": (190, 130, 255),
}

DEFAULT_H = {"stat": 62, "spark": 60, "bar": 34, "text": 18}
ROW_H, TITLE_H, HEAD_H = 22, 16, 14


# ---------------------------------------------------------------- layout (pure, no Pillow)

def widget_height(wd):
    t = wd["type"]
    if "h" in wd:
        return wd["h"]
    if t in DEFAULT_H:
        return DEFAULT_H[t]
    title = TITLE_H if wd.get("title") else 0
    if t == "list":
        n = len(wd["items"])
        return title + (max(1, math.ceil(n / max(1, wd["cols"]))) * ROW_H if n else 18)
    if t == "table":
        n = len(wd["rows"])
        return title + (HEAD_H + n * (ROW_H + 2) if n else 18)
    return 18


def layout(page, width, height):
    """-> (placed [(x, y, w, h, widget)], overflow bool). Rows stack top to bottom on a 12-column grid."""
    unit = (width - 2 * MARGIN + GAP) / 12.0
    bottom = height - BANNER_H - 4
    y, placed, overflow = HEADER_H + 8, [], False
    for row in page["rows"]:
        row = [wd for wd in row if wd.get("only") != "web"]   # web-only widgets take no LCD space
        if not row:
            continue
        rh = max(widget_height(wd) for wd in row)
        x_units = 0.0
        for wd in row:
            wpx = int(wd["w"] * unit - GAP)
            placed.append((int(MARGIN + x_units * unit), y, wpx, widget_height(wd), wd))
            x_units += wd["w"]
        if y + rh > bottom:
            overflow = True
        y += rh + GAP
    return placed, overflow


# ---------------------------------------------------------------- drawing

def _imports():
    global Image, ImageDraw, ImageFont
    from PIL import Image, ImageDraw, ImageFont


def rrect(d, box, radius, fill):
    """ImageDraw.rounded_rectangle needs Pillow >= 8.2; Raspberry Pi OS Bullseye ships 8.1."""
    if hasattr(d, "rounded_rectangle"):
        return d.rounded_rectangle(box, radius=radius, fill=fill)
    x0, y0, x1, y1 = box
    r = max(0, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    d.rectangle((x0 + r, y0, x1 - r, y1), fill=fill)
    d.rectangle((x0, y0 + r, x1, y1 - r), fill=fill)
    for cx, cy in ((x0, y0), (x1 - 2 * r, y0), (x0, y1 - 2 * r), (x1 - 2 * r, y1 - 2 * r)):
        d.ellipse((cx, cy, cx + 2 * r, cy + 2 * r), fill=fill)


class Canvas:
    def __init__(self, width, height, font_dir):
        self.w, self.h = width, height
        self.img = Image.new("RGB", (width, height), PALETTE["bg"])
        self.d = ImageDraw.Draw(self.img)
        def font(size, bold=False):
            try:
                return ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)
            except OSError:
                return ImageFont.load_default()
        self.f = {"title": font(16, True), "mid": font(18, True), "sm": font(13), "xs": font(11)}

    def text(self, xy, s, f="sm", color="fg", anchor="la"):
        self.d.text(xy, s, font=self.f[f], fill=PALETTE[color], anchor=anchor)

    def fit(self, xy, s, maxw, f="sm", color="fg", anchor="la"):
        """Draw text, trimming with an ellipsis so it never overruns maxw pixels."""
        font = self.f[f]
        s = str(s)
        while len(s) > 1 and font.getlength(s) > maxw:
            s = s[:-2].rstrip() + "…" if not s.endswith("…") else s[:-2] + "…"
        self.d.text(xy, s, font=font, fill=PALETTE[color], anchor=anchor)

    def panel(self, x, y, w, h):
        rrect(self.d, (x, y, x + w, y + h), 6, PALETTE["panel"])

    def bar(self, x, y, w, h, pct, color):
        rrect(self.d, (x, y, x + w, y + h), 3, PALETTE["bg"])
        if pct:
            rrect(self.d, (x, y, x + max(4, int(w * min(pct, 100) / 100)), y + h), 3, PALETTE[color])

    def dot(self, x, y, ok, r=5):
        c = PALETTE["dim"] if ok is None else PALETTE["good"] if ok else PALETTE["bad"]
        self.d.ellipse((x - r, y - r, x + r, y + r), fill=c)


def draw_stat(c, x, y, w, h, wd):
    c.panel(x, y, w, h)
    c.fit((x + 8, y + 5), wd["label"], w - 16, "xs", "dim")
    f = "mid" if c.f["mid"].getlength(wd["text"]) <= w - 16 else "sm"
    c.fit((x + 8, y + 20 if h >= 50 else y + 18), wd["text"], w - 16, f, wd["color"])
    if wd["sub"] and h >= 52:
        c.fit((x + 8, y + h - 16), wd["sub"], w - 16, "xs", "dim")


def draw_spark(c, x, y, w, h, wd):
    c.panel(x, y, w, h)
    vals = wd["values"]
    if len(vals) < 2:
        c.text((x + w // 2, y + h // 2), "no data", "xs", "dim", "mm")
        return
    hi = max(vals) or 1
    pts = [(x + 4 + i * (w - 8) / (len(vals) - 1), y + h - 4 - v / hi * (h - 20)) for i, v in enumerate(vals)]
    col = PALETTE[wd["color"]]
    c.d.polygon(pts + [(pts[-1][0], y + h - 4), (pts[0][0], y + h - 4)],
                fill=tuple(v // 4 + PALETTE["panel"][i] * 3 // 4 for i, v in enumerate(col)))
    c.d.line(pts, fill=col, width=2)
    c.fit((x + 6, y + 3), ("%s  peak %s" % (wd["label"], wd["peak_text"])).strip(), w - 12, "xs", "dim")


def draw_bar(c, x, y, w, h, wd):
    c.fit((x, y), wd["label"], w - 60, "xs", "dim")
    c.text((x + w, y - 2), wd["text"], "sm", "fg", "ra")
    c.bar(x, y + 16, w, 12, wd["pct"], wd["color"])


def draw_text(c, x, y, w, h, wd):
    c.fit((x, y), wd["text"], w, "xs", wd["color"])


def draw_list(c, x, y, w, h, wd):
    if wd["title"]:
        c.fit((x, y), wd["title"], w, "xs", "dim")
        y += TITLE_H
    if not wd["items"]:
        c.fit((x, y), wd["empty_text"], w, "sm", wd["empty_color"])
        return
    cols = max(1, wd["cols"])
    colw = w / float(cols)
    rows = math.ceil(len(wd["items"]) / cols)
    for i, it in enumerate(wd["items"]):
        col, row = divmod(i, rows)
        ix, iy = x + col * colw, y + row * ROW_H
        c.dot(ix + 6, iy + 8, it["ok"])
        textw = c.f["xs"].getlength(it["text"]) + 6 if it["text"] else 0
        c.fit((ix + 18, iy), it["name"], colw - 24 - textw, "sm", "bad" if it["ok"] is False else "fg")
        if it["text"]:
            c.text((ix + colw - 6, iy + 2), it["text"], "xs", "dim", "ra")


def draw_table(c, x, y, w, h, wd):
    if wd["title"]:
        c.fit((x, y), wd["title"], w, "xs", "dim")
        y += TITLE_H
    if not wd["rows"]:
        c.fit((x, y), wd["empty_text"], w, "sm", wd["empty_color"] if "empty_color" in wd else "dim")
        return
    widths = [c_["width"] or {"dot": 26, "bar": 120}.get(c_["kind"], 74) for c_ in wd["columns"]]
    name_w = max(40, w - sum(widths))
    xs = [x + name_w]
    for cw in widths[:-1]:
        xs.append(xs[-1] + cw)
    for col, cx, cw in zip(wd["columns"], xs, widths):
        if col["header"]:
            c.fit((cx + (cw // 2 if col["kind"] == "dot" else 0 if col["kind"] == "bar" else 6), y), col["header"], cw - 2,
                  "xs", "dim", "ma" if col["kind"] == "dot" else "la")
    y += HEAD_H
    for r in wd["rows"]:
        c.fit((x + 2, y + 2), r["name"], name_w - 6, "sm")
        for cell, cx, cw in zip(r["cells"], xs, widths):
            if cell["kind"] == "dot":
                c.dot(cx + cw // 2, y + 9, cell["ok"])
            elif cell["kind"] == "bar":
                bw = max(20, cw - 50)
                c.bar(cx, y + 3, bw, 12, cell["pct"], cell["color"])
                c.text((cx + cw - 8, y + 2), cell["text"], "xs", "dim", "ra")
            else:
                c.fit((cx + 6, y + 2), cell["text"], cw - 10, "sm", cell["color"])
        y += ROW_H + 2


DRAW = {"stat": draw_stat, "spark": draw_spark, "bar": draw_bar, "text": draw_text, "list": draw_list, "table": draw_table}


def render_page(page, idx, total, alerts, cfg):
    _imports()
    d = cfg["display"]
    c = Canvas(d["width"], d["height"], d["font_dir"])
    placed, overflow = layout(page, d["width"], d["height"])
    for x, y, w, h, wd in placed:
        if y + h <= d["height"] - BANNER_H:
            DRAW[wd["type"]](c, x, y, w, h, wd)
    c.d.rectangle((0, 0, d["width"], HEADER_H), fill=PALETTE["panel"])
    c.text((10, 15), page["title"], "title", "fg", "lm")
    for i in range(total):
        x0 = d["width"] // 2 - total * 7 + i * 14
        c.d.ellipse((x0, 11, x0 + 7, 18), fill=PALETTE["accent"] if i == idx else (60, 68, 80))
    c.text((d["width"] - 10, 15), time.strftime("%H:%M"), "title", "dim", "rm")
    if alerts:
        c.d.rectangle((0, d["height"] - BANNER_H, d["width"], d["height"]), fill=PALETTE["bad"])
        msg = "! " + " · ".join(alerts[:3]) + (" +%d" % (len(alerts) - 3) if len(alerts) > 3 else "")
        c.fit((8, d["height"] - 13), msg, d["width"] - 16, "sm", "fg", "lm")
    return c.img


def to_rgb565(img):
    data = img.tobytes()
    return array("H", [((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                       for r, g, b in zip(data[0::3], data[1::3], data[2::3])]).tobytes()


def blit(img, path):
    with open(path, "wb") as fb:
        fb.write(to_rgb565(img))
