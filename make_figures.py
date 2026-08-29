"""Render the calibration figure from figures/calibration.json.

No dependencies, and no data cache required: check_calibration.py dumps the
numbers it printed, this reads them back and draws. Regenerating the figure is
a second's work for anyone who clones the repo; regenerating the *numbers*
means the full pull, which is why the JSON is committed alongside the SVG.

Text placement is checked rather than eyeballed. Every string is registered
with a conservative bounding box and _assert_no_collisions() fails the render
if two boxes overlap or a box lands on a plotted point. The box widths assume a
font wider than any in the stack, because the SVG names a font stack and the
viewer picks: a layout that only works in the author's first choice is a layout
that breaks on someone else's machine.

    python make_figures.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "figures", "calibration.json")
OUT = os.path.join(HERE, "figures", "calibration.svg")

W, H = 780, 496
L, R, T, B = 68, 30, 88, 78          # T fits two subtitle lines, B the axis title
                                     # and the footer
PW, PH = W - L - R, H - T - B

INK = "#1b1f24"
MUTED = "#5a636e"
GRID = "#e3e7ec"
MODEL = "#c1483a"
MARKET = "#2f6f9f"

# Advance width per character, as a multiple of font-size. DejaVu Sans, the
# common Linux fallback when none of the named faces resolve, averages about
# 0.55 for mixed-case text. 0.63 is deliberately past that, so a box that
# clears here clears on a wider face too.
WIDE = 0.63

_boxes = []      # (x0, y0, x1, y1, name) for every string drawn
_points = []     # (x, y, r) for every plotted marker
_segments = []   # ((x0,y0),(x1,y1)) for every drawn curve segment


def _text_box(x, y, size, text, anchor, name):
    w = len(text) * size * WIDE
    x0 = {"start": x, "middle": x - w / 2, "end": x - w}[anchor]
    # baseline y: ascent above, descent below
    _boxes.append((x0, y - size * 0.80, x0 + w, y + size * 0.24, name))


def _seg_hits_box(p0, p1, box):
    """Liang-Barsky clip: does the segment p0-p1 enter the rectangle?"""
    x0, y0 = p0
    dx, dy = p1[0] - x0, p1[1] - y0
    t0, t1 = 0.0, 1.0
    for num, den in ((box[0] - x0, dx), (x0 - box[2], -dx),
                     (box[1] - y0, dy), (y0 - box[3], -dy)):
        if den == 0:
            if num > 0:
                return False
            continue
        t = num / den
        if den > 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _assert_no_collisions():
    def overlap(a, b):
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])

    bad = []
    for a in _boxes:
        if a[0] < 0 or a[2] > W or a[1] < 0 or a[3] > H:
            bad.append(f"text/canvas: {a[4]!r} runs off the {W}x{H} canvas")
    for i, a in enumerate(_boxes):
        for b in _boxes[i + 1:]:
            if overlap(a, b):
                bad.append(f"text/text: {a[4]!r} x {b[4]!r}")
        for px, py, pr in _points:
            if a[0] - pr <= px <= a[2] + pr and a[1] - pr <= py <= a[3] + pr:
                bad.append(f"text/marker: {a[4]!r} sits on a plotted point "
                           f"at ({px:.0f},{py:.0f}) r={pr:.1f}")
                break
        for p0, p1 in _segments:
            if _seg_hits_box(p0, p1, a):
                bad.append(f"text/curve: {a[4]!r} sits on a curve segment")
                break
    if bad:
        raise SystemExit("figure layout collides:\n  " + "\n  ".join(sorted(set(bad))))


def x(p):
    return L + p * PW


def y(p):
    return T + (1 - p) * PH


def radius(n, nmax):
    # area proportional to sqrt(n): keeps the 112k bin from swallowing the plot
    return 2.6 + 6.4 * (n / nmax) ** 0.5


def series(points, colour, nmax):
    d = " ".join(("M" if i == 0 else "L") + f"{x(p['mean_pred']):.1f},{y(p['realised']):.1f}"
                 for i, p in enumerate(points))
    out = [f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="2.1" '
           f'stroke-linejoin="round" stroke-linecap="round"/>']
    for a, b in zip(points, points[1:]):
        _segments.append(((x(a["mean_pred"]), y(a["realised"])),
                          (x(b["mean_pred"]), y(b["realised"]))))
    for p in points:
        r = radius(p["n"], nmax)
        _points.append((x(p["mean_pred"]), y(p["realised"]), r))
        out.append(f'<circle cx="{x(p["mean_pred"]):.1f}" cy="{y(p["realised"]):.1f}" '
                   f'r="{r:.2f}" fill="{colour}" stroke="#ffffff" stroke-width="1.1"/>')
    return "\n".join(out)


def main():
    with open(SRC, encoding="utf-8") as fh:
        d = json.load(fh)
    rel, br = d["reliability"], d["brier"]
    nmax = max(p["n"] for s in rel.values() for p in s)
    top = {s: [p for p in rel[s] if p["lo"] == 0.95][0] for s in ("model", "market")}

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'width="{W}" height="{H}" font-family="-apple-system,BlinkMacSystemFont,'
         f'Segoe UI,Helvetica,Arial,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>']

    for t in (0, .2, .4, .6, .8, 1.0):
        s.append(f'<line x1="{x(t):.1f}" y1="{T}" x2="{x(t):.1f}" y2="{T+PH}" '
                 f'stroke="{GRID}" stroke-width="1"/>')
        s.append(f'<line x1="{L}" y1="{y(t):.1f}" x2="{L+PW}" y2="{y(t):.1f}" '
                 f'stroke="{GRID}" stroke-width="1"/>')
        s.append(f'<text x="{x(t):.1f}" y="{T+PH+20}" font-size="11.5" fill="{MUTED}" '
                 f'text-anchor="middle">{t:.1f}</text>')
        _text_box(x(t), T + PH + 20, 11.5, f"{t:.1f}", "middle", f"xtick {t}")
        s.append(f'<text x="{L-10}" y="{y(t)+4:.1f}" font-size="11.5" fill="{MUTED}" '
                 f'text-anchor="end">{t:.1f}</text>')
        _text_box(L - 10, y(t) + 4, 11.5, f"{t:.1f}", "end", f"ytick {t}")

    # The diagonal carries no rotated caption. The plot is not square, so a
    # label rotated to follow the line needs an angle derived from PW/PH, and
    # its rotated bounding box is then tall enough to land on a marker wherever
    # it goes. The line is named in the subtitle instead, where it costs
    # nothing and cannot collide with anything.
    s.append(f'<line x1="{x(0):.1f}" y1="{y(0):.1f}" x2="{x(1):.1f}" y2="{y(1):.1f}" '
             f'stroke="{MUTED}" stroke-width="1.3" stroke-dasharray="5 4"/>')

    s.append(series(rel["market"], MARKET, nmax))
    s.append(series(rel["model"], MODEL, nmax))

    title = "The market is the better forecaster at every probability"
    s.append(f'<text x="{L}" y="28" font-size="15.5" font-weight="600" fill="{INK}">'
             f'{title}</text>')
    _text_box(L, 28, 15.5, title, "start", "title")

    sub1 = (f"Reliability on each forecaster\u2019s own bins, "
            f"{br['n']:,} bucket-hours, training cities.")
    s.append(f'<text x="{L}" y="50" font-size="12" fill="{MUTED}">{sub1}</text>')
    _text_box(L, 50, 12, sub1, "start", "subtitle 1")

    sub2 = "Dashed line is perfect calibration; marker area \u221d bin count."
    s.append(f'<text x="{L}" y="68" font-size="11.5" fill="{MUTED}">{sub2}</text>')
    _text_box(L, 68, 11.5, sub2, "start", "subtitle 2")

    # Legend in the upper-left quadrant, which both curves leave empty, and
    # carrying the top-bin comparison so no floating annotation is needed.
    lx, ly = L + 16, T + 24
    for i, (key, lab, col) in enumerate((("model", "§6 fair value", MODEL),
                                         ("market", "Kalshi mid-quote", MARKET))):
        p = top[key]
        txt = f'{lab}, says {p["mean_pred"]:.2f}, settles {p["realised"]:.2f}'
        cy = ly + i * 22
        s.append(f'<circle cx="{lx}" cy="{cy-4:.1f}" r="5" fill="{col}"/>')
        s.append(f'<text x="{lx+14}" y="{cy:.1f}" font-size="12.5" fill="{INK}">'
                 f'<tspan fill="{col}" font-weight="600">{lab}</tspan>'
                 f', says {p["mean_pred"]:.2f}, settles {p["realised"]:.2f}</text>')
        _text_box(lx + 14, cy, 12.5, txt, "start", f"legend {key}")

    foot = ("Brier score, lower is better: "
            f"model {br['model']:.4f} \u00b7 market {br['market']:.4f}")
    s.append(f'<text x="{L}" y="{H-18}" font-size="11.5" fill="{MUTED}">'
             f'Brier score, lower is better: '
             f'<tspan fill="{MODEL}" font-weight="600">model {br["model"]:.4f}</tspan>'
             f' \u00b7 <tspan fill="{MARKET}" font-weight="600">'
             f'market {br["market"]:.4f}</tspan></text>')
    _text_box(L, H - 18, 11.5, foot, "start", "footer")

    s.append(f'<text x="{L+PW/2:.0f}" y="{T+PH+42}" font-size="12" fill="{INK}" '
             f'text-anchor="middle">forecast probability</text>')
    _text_box(L + PW / 2, T + PH + 42, 12, "forecast probability", "middle", "x axis title")

    s.append(f'<text x="16" y="{T+PH/2:.0f}" font-size="12" fill="{INK}" '
             f'text-anchor="middle" transform="rotate(-90 16 {T+PH/2:.0f})">'
             f'realised settle rate</text>')
    # rotated -90 about (16, mid): the box is vertical, so swap the extents
    half = len("realised settle rate") * 12 * WIDE / 2
    _boxes.append((16 - 12 * 0.8, T + PH / 2 - half, 16 + 12 * 0.24,
                   T + PH / 2 + half, "y axis title"))

    _assert_no_collisions()

    s.append('</svg>')
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(s) + "\n")
    print(f"wrote {os.path.relpath(OUT, HERE)}  ({len(_boxes)} text boxes checked "
          f"against each other, {len(_points)} markers and {len(_segments)} "
          f"curve segments: no collisions)")


if __name__ == "__main__":
    main()
