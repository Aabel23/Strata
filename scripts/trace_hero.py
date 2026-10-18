"""Centerline-trace the Overview hero line art from a mockup PNG into an inline SVG.

Usage (Python 3.12 venv with pillow numpy scikit-image skan):
  python scripts/trace_hero.py IN.png X0,Y0,X1,Y1 OUT.svg [--erase x0,y0,x1,y1 ...] [--scale 5] [--thresh 90]
Erase boxes are in crop coordinates (UI drawn over the art).
Output: thin stroked paths (class l1/l2/l3 by source brightness, class r for ridge outlines),
opaque mountain bodies (class b) behind them, and 4-point stars (class s). Colours come from CSS.
"""
import argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from skimage.morphology import skeletonize, remove_small_objects
from skimage.measure import label, regionprops
from skan import Skeleton

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("box"); ap.add_argument("out")
ap.add_argument("--erase", action="append", default=[])
ap.add_argument("--scale", type=int, default=5)
ap.add_argument("--thresh", type=int, default=90)
ap.add_argument("--ridge", type=float, default=170, help="raw brightness for the bright outline class")
ap.add_argument("--gap", type=int, default=10, help="max vertical ink gap (1x px) still inside a mountain body")
ap.add_argument("--waves", action="store_true", help="also write OUT-waves.svg: ground waves joined, smoothed and extended to any width")
ap.add_argument("--minlen", type=float, default=4.0, help="drop paths shorter than this (1x px)")
a = ap.parse_args()
S = a.scale

img = Image.open(a.src).convert("RGB").crop(tuple(int(v) for v in a.box.split(",")))
W, H = img.size
lum = img.convert("L")
d = ImageDraw.Draw(lum)
for e in a.erase:
    d.rectangle(tuple(int(v) for v in e.split(",")), fill=0)
lum = lum.point(lambda v: max(0, min(255, (v - 38) * 3)))
big = np.asarray(lum.resize((W * S, H * S), Image.LANCZOS).filter(ImageFilter.GaussianBlur(S * .25)), dtype=float)
ink = remove_small_objects(big > a.thresh, max_size=6 * S * S)

# stars: small compact blobs in the 1x image, away from other ink
small = np.asarray(lum) > 120
stars = []
for rp in regionprops(label(small)):
    y0, x0, y1, x1 = rp.bbox
    if 3 <= rp.area <= 40 and max(y1 - y0, x1 - x0) <= 9 and abs((y1 - y0) - (x1 - x0)) <= 2:
        pad = np.asarray(lum)[max(0, y0 - 5):y1 + 5, max(0, x0 - 5):x1 + 5] > 60
        if pad.sum() <= rp.area * 1.6:
            cy, cx = rp.centroid
            stars.append((cx, cy, max(y1 - y0, x1 - x0) / 2 + .5, min(1, np.asarray(lum)[y0:y1, x0:x1].max() / 255 + .15)))
            ink[y0 * S - 2 * S:y1 * S + 2 * S, x0 * S - 2 * S:x1 * S + 2 * S] = False

# mountain bodies: per column, from the top ink pixel down while ink gaps stay small (hatching), then stop
inks = np.asarray(Image.fromarray(ink.astype(np.uint8) * 255).resize((W, H), Image.BOX)) > 40
top = np.full(W, H, float); bot = np.full(W, H, float)
for x in range(W):
    ys = np.flatnonzero(inks[:, x])
    if len(ys):
        top[x] = ys[0]; b = ys[0]
        for y in ys[1:]:
            if y - b > a.gap: break
            b = y
        bot[x] = b if b - ys[0] > 6 else ys[0]  # isolated lines (waves) get no body
k = np.ones(9) / 9
from scipy.ndimage import maximum_filter1d, minimum_filter1d
has = bot - top > 6
has = minimum_filter1d(maximum_filter1d(has.astype(int), 15), 15) > 0  # close narrow gaps between bodies
from scipy.ndimage import median_filter
top = median_filter(top, 9)  # drop one-column spikes
bot = np.where(has, maximum_filter1d(np.where(has, bot, 0), 41), bot)  # hatch gaps: body reaches the lowest nearby run
bot = minimum_filter1d(maximum_filter1d(bot, 9), 9)
top_s = np.convolve(np.pad(top, 4, mode="edge"), k, "valid"); bot_s = np.convolve(np.pad(bot, 4, mode="edge"), k, "valid")
body, run = [], []
for x in range(W + 1):
    if x < W and bot_s[x] - top_s[x] > 4:
        run.append(x)
    elif len(run) > 15:
        pts = [(x_, top_s[x_] + .8) for x_ in run] + [(x_, bot_s[x_] - .5) for x_ in reversed(run)]
        body.append("M" + " L".join(f"{p:.1f} {q:.1f}" for p, q in pts) + "Z"); run = []
    else:
        run = []

# centerlines
sk = Skeleton(skeletonize(ink))
src = np.asarray(img.convert("L"), dtype=float)  # raw brightness drives the stroke class
topmask = np.zeros((H, W), bool)
for x in range(W):
    if top[x] < H: topmask[int(top[x]), x] = True
topmask = np.asarray(Image.fromarray(topmask.astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0


def rdp(p, eps):
    if len(p) < 3: return p
    a_, b_ = p[0], p[-1]; ab = b_ - a_; n = np.hypot(*ab) or 1
    v = p - a_; dist = np.abs(ab[0] * v[:, 1] - ab[1] * v[:, 0]) / n
    i = int(dist.argmax())
    return np.vstack([rdp(p[:i + 1], eps)[:-1], rdp(p[i:], eps)]) if dist[i] > eps else np.array([a_, b_])


def bez(p):  # Catmull-Rom through points -> cubic Bezier path data
    f = lambda v: f"{v:.1f}".rstrip("0").rstrip(".")
    out = f"M{f(p[0][0])} {f(p[0][1])}"
    if len(p) == 2: return out + f"L{f(p[1][0])} {f(p[1][1])}"
    q = np.vstack([p[0], p, p[-1]])
    for i in range(1, len(q) - 2):
        c1 = q[i] + (q[i + 1] - q[i - 1]) / 6; c2 = q[i + 1] - (q[i + 2] - q[i]) / 6
        out += f"C{f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(q[i + 1][0])} {f(q[i + 1][1])}"
    return out


# polylines from skeleton branches, then join branches that continue each other (same direction at a shared end)
lines = []
for i in range(sk.n_paths):
    p = sk.path_coordinates(i)[:, ::-1] / S
    if len(p) >= 2: lines.append(p)


def tang(p, end):  # unit direction leaving the polyline at that end
    q = p if end else p[::-1]
    v = q[-1] - q[max(0, len(q) - 6)]
    return v / (np.hypot(*v) or 1)


joined = True
while joined:
    joined = False
    ends = [(i, e, (l[-1] if e else l[0])) for i, l in enumerate(lines) for e in (0, 1)]
    used = set()
    for i, e, pt in ends:
        if i in used: continue
        best = None
        for j, f, qt in ends:
            if j == i or j in used or np.hypot(*(pt - qt)) > 1.2: continue
            c = -float(tang(lines[i], e) @ tang(lines[j], f))  # 1 = straight continuation
            if c > .8 and (best is None or c > best[0]): best = (c, j, f)
        if best:
            _, j, f = best
            A = lines[i] if e else lines[i][::-1]; B = lines[j][::-1] if f else lines[j]
            lines[i] = np.vstack([A, B]); lines[j] = None; used |= {i, j}; joined = True
    lines = [l for l in lines if l is not None]

has_s = bot_s - top_s > 4
groups = {"r": [], "l1": [], "l2": [], "l3": []}
for p in lines:
    if np.hypot(*np.diff(p, axis=0).T).sum() < a.minlen: continue
    xi = np.clip(p[:, 0].astype(int), 0, W - 1); yi = np.clip(p[:, 1].astype(int), 0, H - 1)
    inside = has_s[xi] & (p[:, 1] >= top_s[xi] - 2) & (p[:, 1] <= bot_s[xi] + 1.5)
    if inside.mean() < .5:  # ground waves / strays: drawn from the fitted wave layer instead
        continue
    br = src[yi, xi].mean()
    cls = "r" if br > a.ridge or (topmask[yi, xi].mean() > .6 and br > a.ridge - 40) else "l1" if br > a.ridge - 55 else "l2" if br > a.ridge - 95 else "l3"
    groups[cls].append(bez(rdp(p, .35)))

svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMaxYMax meet">',
       f'<path class="b" d="{"".join(body)}"/>']
for c, ps in groups.items():
    if ps: svg.append(f'<path class="{c}" d="{"".join(ps)}"/>')
star = lambda x, y, r: (f"M{x:.1f} {y - r * 2:.1f}Q{x:.1f} {y:.1f} {x + r * 2:.1f} {y:.1f}Q{x:.1f} {y:.1f} {x:.1f} {y + r * 2:.1f}"
                         f"Q{x:.1f} {y:.1f} {x - r * 2:.1f} {y:.1f}Q{x:.1f} {y:.1f} {x:.1f} {y - r * 2:.1f}Z")
for x, y, r, o in stars:
    svg.append(f'<path class="s" opacity="{o:.2f}" d="{star(x, y, r * .65)}"/>')
svg.append("</svg>\n")
res = "".join(svg)
open(a.out, "w").write(res)
print(f"{a.out}: {len(res)} bytes, " + ", ".join(f"{c}={len(v)}" for c, v in groups.items()) + f", bodies={len(body)}, stars={len(stars)}")

if a.waves:
    import json, os
    # waves are hand-measured from the mockup (the 1024px source is too faint/broken to fit them reliably)
    spec = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hero_waves.json")))
    bx = [int(v) for v in a.box.split(",")]; byc = {}
    for w in spec["waves"]:
        P = np.array(w["p"], float) - bx[:2]
        x0, x1 = P[0, 0], P[-1, 0]; s0 = (P[1, 1] - P[0, 1]) / (P[1, 0] - x0); s1 = (P[-1, 1] - P[-2, 1]) / (x1 - P[-2, 0]); L = 120.0
        left = np.arange(-2400, x0 - 20, 40.0); right = np.arange(x1 + 30, W + 60, 30.0)
        yl = P[0, 1] + s0 * L * (1 - np.exp((left - x0) / L)); yr = P[-1, 1] + s1 * L * (1 - np.exp(-(right - x1) / L))
        Q = np.vstack([np.column_stack([left, yl]), P, np.column_stack([right, yr])])
        byc.setdefault(w["c"], []).append(bez(Q))
    wout = a.out.replace(".svg", "-waves.svg")
    # wide viewBox, right-aligned with the mountains (same height, xMax + slice): waves reach any container width
    res = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2400 0 {W + 2400} {H}" preserveAspectRatio="xMaxYMax slice">'
           + "".join(f'<path class="{c}" d="{"".join(v)}"/>' for c, v in byc.items()) + "</svg>\n")
    open(wout, "w").write(res)
    print(f"{wout}: {len(res)} bytes, waves={sum(map(len, byc.values()))}")
