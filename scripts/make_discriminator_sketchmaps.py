#!/usr/bin/env python3
"""
Discriminator sketch maps for Qualitative Accuracy vs. GMDA.

Produces 12 sketch maps split into two groups of 6:

  Group A  SketchMapia wins   (categorical / topological error, GMDA blind)
    A1  Linear-ordering flip  along the route L1 -> L3 -> L2
    A2  Side-of-route flip    L2 drawn north of route instead of south
    A3  Street connectedness  s_T1 drawn with a 10 unit gap at s_M
    A4  RCC containment flip  L4 drawn just outside the park
    A5  DE9IM landmark-street L5 drawn with a 10 unit gap from s_W
    A6  OPRA street relation  s_T1 redrawn as a diagonal T into s_T2

  Group B  GMDA wins          (metric error, QA relations preserved)
    B1  Rigid rotation        20 degrees about the map centre
    B2  Uniform scale         0.7x about the map centre
    B3  Anisotropic scale     sx=0.7, sy=1.0 about the map centre
    B4  Pairwise distance     landmarks jittered within their cells
    B5  Horizontal shear      x += 0.3 * (y - 300)
    B6  Translate + rotate    +40 east, 8 degrees about the centre

Everything is in the SketchMapia editor coordinate space:
  x in [0, 850], y in [0, 600], y pointing up
  (the editor stretches every uploaded image onto [[0,0],[600,850]]).

Run:   python3 make_discriminator_sketchmaps.py [output_dir]
Needs: numpy, matplotlib, shapely.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from copy import deepcopy

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "discriminator_set")

W, H  = 850, 600            # SketchMapia editor space
PX    = 2                   # pixels per map unit -> 1700 x 1200 px
DPI   = 200
U2PT  = 72.0 * PX / DPI     # map units -> points (line widths, font sizes)
CENTRE = (425.0, 300.0)     # rotation / scale pivot for Group B
FONTS_DIR = os.path.join(HERE, "fonts")
FONT_FILES = ["PatrickHand-Regular.ttf", "Kalam-Regular.ttf",
              "ShadowsIntoLight.ttf", "ArchitectsDaughter-Regular.ttf",
              "IndieFlower-Regular.ttf", "ComingSoon-Regular.ttf",
              "GochiHand-Regular.ttf"]
FONT_SCALE = {"Kalam-Regular.ttf": 0.92, "ArchitectsDaughter-Regular.ttf": 0.86,
              "IndieFlower-Regular.ttf": 0.95, "ComingSoon-Regular.ttf": 0.86,
              "ShadowsIntoLight.ttf": 1.0, "PatrickHand-Regular.ttf": 1.0,
              "GochiHand-Regular.ttf": 0.98}
INKS = ["#1b1b1b", "#20233a", "#2a2a2a", "#1c2b4a", "#262220"]

# ---------------------------------------------------------------------------
# BASE MAP
# ---------------------------------------------------------------------------
BASE_STREETS = {
    "s_S":  [(100.0, 100.0), (700.0, 100.0)],
    "s_M":  [(100.0, 300.0), (700.0, 300.0)],     # the defined route
    "s_N":  [(100.0, 500.0), (700.0, 500.0)],
    "s_W":  [(100.0, 100.0), (100.0, 500.0)],
    "s_T1": [(300.0, 300.0), (300.0, 500.0)],
    "s_T2": [(500.0, 300.0), (500.0, 500.0)],
}
ROUTE_KEYS = {"s_M"}

BASE_LANDMARKS = {
    "L1": [(170.0, 240.0), (230.0, 240.0), (230.0, 280.0), (170.0, 280.0)],
    "L2": [(370.0, 240.0), (430.0, 240.0), (430.0, 280.0), (370.0, 280.0)],
    "L3": [(570.0, 240.0), (630.0, 240.0), (630.0, 280.0), (570.0, 280.0)],
    "L4": [(600.0, 400.0), (680.0, 400.0), (680.0, 460.0), (600.0, 460.0)],
    "L5": [(100.0, 200.0), (140.0, 200.0), (140.0, 240.0), (100.0, 240.0)],
}

PARK = [(550.0, 350.0), (700.0, 350.0), (700.0, 500.0), (550.0, 500.0)]

# Stable base-feature ids: streets first, then park, then landmarks.
BASE_ORDER = list(BASE_STREETS) + ["park"] + list(BASE_LANDMARKS)
BASE_ID = {k: i + 1 for i, k in enumerate(BASE_ORDER)}


# ---------------------------------------------------------------------------
# GEOMETRY HELPERS
# ---------------------------------------------------------------------------
def rotate_about(pts, deg, cx=CENTRE[0], cy=CENTRE[1]):
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    out = []
    for x, y in pts:
        x1, y1 = x - cx, y - cy
        out.append((round(cx + c * x1 - s * y1, 2),
                    round(cy + s * x1 + c * y1, 2)))
    return out


def scale_about(pts, sx, sy, cx=CENTRE[0], cy=CENTRE[1]):
    return [(round(cx + (x - cx) * sx, 2), round(cy + (y - cy) * sy, 2))
            for x, y in pts]


def shear_x(pts, k, y0=CENTRE[1]):
    return [(round(x + k * (y - y0), 2), round(y, 2)) for x, y in pts]


def translate(pts, dx, dy):
    return [(round(x + dx, 2), round(y + dy, 2)) for x, y in pts]


def transform_all(apply_fn):
    """Apply a function (pts -> pts) to every street, park and landmark;
    return the new mutable copies."""
    streets = {k: apply_fn(v) for k, v in BASE_STREETS.items()}
    landmarks = {k: apply_fn(v) for k, v in BASE_LANDMARKS.items()}
    park = apply_fn(PARK)
    return streets, landmarks, park


# ---------------------------------------------------------------------------
# PER-SKETCH DEFINITIONS
# ---------------------------------------------------------------------------
def sketch_A1():
    """Route redrawn as a dipping polyline that visits the landmarks in the
    along-route order L1 -> L3 -> L2.  Landmarks stay at their base positions
    so every GMDA aspect is unchanged.  The route is still ONE feature with
    the same base-id as s_M; it just has extra vertices."""
    streets = deepcopy(BASE_STREETS)
    streets["s_M"] = [
        (100.0, 300.0), (650.0, 300.0),
        (650.0, 240.0), (350.0, 240.0),
        (350.0, 300.0), (700.0, 300.0),
    ]
    return dict(streets=streets, landmarks=deepcopy(BASE_LANDMARKS),
                park=deepcopy(PARK), route_order=["L1", "L3", "L2"],
                expected=mark(qa_lo=False))


def sketch_A2():
    landmarks = deepcopy(BASE_LANDMARKS)
    landmarks["L2"] = [(370.0, 320.0), (430.0, 320.0),
                       (430.0, 360.0), (370.0, 360.0)]
    return dict(streets=deepcopy(BASE_STREETS), landmarks=landmarks,
                park=deepcopy(PARK), route_order=["L1", "L2", "L3"],
                expected=mark(qa_lr=False))


def sketch_A3():
    streets = deepcopy(BASE_STREETS)
    streets["s_T1"] = [(300.0, 310.0), (300.0, 500.0)]   # 10 unit gap at s_M
    return dict(streets=streets, landmarks=deepcopy(BASE_LANDMARKS),
                park=deepcopy(PARK), route_order=["L1", "L2", "L3"],
                expected=mark(qa_sc=False))


def sketch_A4():
    landmarks = deepcopy(BASE_LANDMARKS)
    landmarks["L4"] = [(715.0, 400.0), (795.0, 400.0),
                       (795.0, 460.0), (715.0, 460.0)]   # east of the park
    return dict(streets=deepcopy(BASE_STREETS), landmarks=landmarks,
                park=deepcopy(PARK), route_order=["L1", "L2", "L3"],
                expected=mark(qa_rcc=False))


def sketch_A5():
    landmarks = deepcopy(BASE_LANDMARKS)
    landmarks["L5"] = [(112.0, 200.0), (152.0, 200.0),
                       (152.0, 240.0), (112.0, 240.0)]   # 12 unit gap from s_W
    return dict(streets=deepcopy(BASE_STREETS), landmarks=landmarks,
                park=deepcopy(PARK), route_order=["L1", "L2", "L3"],
                expected=mark(qa_de9im=False))


def sketch_A6():
    streets = deepcopy(BASE_STREETS)
    streets["s_T1"] = [(300.0, 300.0), (500.0, 400.0)]   # diagonal T into s_T2
    return dict(streets=streets, landmarks=deepcopy(BASE_LANDMARKS),
                park=deepcopy(PARK), route_order=["L1", "L2", "L3"],
                expected=mark(qa_opra=False))


def _group_B(apply_fn, expected):
    streets, landmarks, park = transform_all(apply_fn)
    return dict(streets=streets, landmarks=landmarks, park=park,
                route_order=["L1", "L2", "L3"], expected=expected)


def sketch_B1():
    return _group_B(lambda p: rotate_about(p, 20),
                    mark(g_canorg=False, g_canacc=False, g_rotbias=False,
                         g_angacc=False))


def sketch_B2():
    return _group_B(lambda p: scale_about(p, 0.7, 0.7),
                    mark(g_scabias=False, g_canacc=False, g_distacc=False))


def sketch_B3():
    return _group_B(lambda p: scale_about(p, 0.7, 1.0),
                    mark(g_scabias=False, g_canacc=False,
                         g_angacc=False, g_distacc=False))


def sketch_B4():
    landmarks = deepcopy(BASE_LANDMARKS)
    offsets = {"L1": (-10, 10), "L2": (15, -10), "L3": (-15, 15),
               "L4": (10, -10), "L5": (15, 10)}
    for k, (dx, dy) in offsets.items():
        landmarks[k] = translate(landmarks[k], dx, dy)
    return dict(streets=deepcopy(BASE_STREETS), landmarks=landmarks,
                park=deepcopy(PARK), route_order=["L1", "L2", "L3"],
                expected=mark(g_distacc=False, g_canacc=False))


def sketch_B5():
    return _group_B(lambda p: shear_x(p, 0.3),
                    mark(g_angacc=False, g_canacc=False))


def sketch_B6():
    def apply(p):
        return translate(rotate_about(p, 8), 40, 0)
    return _group_B(apply, mark(g_rotbias=False, g_canacc=False,
                                g_canorg=False))


SKETCH_FUNCS = [
    ("A1_linear_ordering",   "A", sketch_A1),
    ("A2_side_of_route",     "A", sketch_A2),
    ("A3_connectedness",     "A", sketch_A3),
    ("A4_rcc_containment",   "A", sketch_A4),
    ("A5_de9im_touching",    "A", sketch_A5),
    ("A6_opra_orientation",  "A", sketch_A6),
    ("B1_rotation",          "B", sketch_B1),
    ("B2_scale_uniform",     "B", sketch_B2),
    ("B3_scale_anisotropic", "B", sketch_B3),
    ("B4_distance_jitter",   "B", sketch_B4),
    ("B5_shear",             "B", sketch_B5),
    ("B6_translate_rotate",  "B", sketch_B6),
]


# ---------------------------------------------------------------------------
# EXPECTED-OUTCOME HELPERS
# ---------------------------------------------------------------------------
QA_KEYS = ["qa_rcc", "qa_de9im", "qa_opra", "qa_sc", "qa_lr", "qa_lo"]
GMDA_KEYS = ["g_canorg", "g_canacc", "g_scabias", "g_distacc",
             "g_rotbias", "g_angacc"]

QA_NAMES = {
    "qa_rcc":    "QA_BuildingTopology_RCC",
    "qa_de9im":  "QA_StreetBuildingTopology_DE9IM",
    "qa_opra":   "QA_StreetsOrientation_OPRA",
    "qa_sc":     "QA_StreetsConnectedness",
    "qa_lr":     "QA_BuildingRoute_LeftRight",
    "qa_lo":     "QA_BuildingRoute_LinearOrdering",
}
GMDA_NAMES = {
    "g_canorg":  "GMDA_CanOrg",
    "g_canacc":  "GMDA_CanAcc",
    "g_scabias": "GMDA_ScaBias",
    "g_distacc": "GMDA_DistAcc",
    "g_rotbias": "GMDA_RotBias",
    "g_angacc":  "GMDA_AngAcc",
}


def mark(**overrides):
    """Default = all qualifiers and GMDA aspects pass; overrides set the ones
    this sketch is designed to fail."""
    exp = {k: True for k in QA_KEYS + GMDA_KEYS}
    exp.update(overrides)
    return exp


# ---------------------------------------------------------------------------
# GEOJSON OUTPUT (SketchMapia editor conventions)
# ---------------------------------------------------------------------------
def base_feature_collection():
    feats = []
    # streets
    for k, coords in BASE_STREETS.items():
        feats.append({
            "type": "Feature",
            "properties": {
                "id": BASE_ID[k],
                "RouteSeqOrder": None,
                "isRoute": "Yes" if k in ROUTE_KEYS else None,
                "feat_type": None,
                "selected": False,
                "aligned": False,
                "otype": "Line",
            },
            "geometry": {"type": "LineString",
                         "coordinates": [list(p) for p in coords]},
        })
    # park
    feats.append({
        "type": "Feature",
        "properties": {
            "id": BASE_ID["park"],
            "RouteSeqOrder": None,
            "isRoute": None,
            "feat_type": "park",
            "selected": False,
            "aligned": False,
            "otype": "Polygon",
        },
        "geometry": {"type": "Polygon",
                     "coordinates": [[list(p) for p in PARK] + [list(PARK[0])]]},
    })
    # landmarks
    for k, ring in BASE_LANDMARKS.items():
        feats.append({
            "type": "Feature",
            "properties": {
                "id": BASE_ID[k],
                "RouteSeqOrder": None,
                "isRoute": None,
                "feat_type": None,
                "selected": False,
                "aligned": False,
                "otype": "Polygon",
            },
            "geometry": {"type": "Polygon",
                         "coordinates": [[list(p) for p in ring] + [list(ring[0])]]},
        })
    return {"type": "FeatureCollection", "features": feats}


def sketch_feature_collection(cell):
    """A sketch feature collection; sids are S0..Sn. Streets first, then park
    (if drawn), then landmarks. 1:1 alignment to the same base keys."""
    feats = []
    order = []            # list of (sid, base_key, otype)
    sid = 0

    def add(base_key, geom_type, coords, is_route=False, route_seq=None):
        nonlocal sid
        props = {
            "id": sid,
            "sid": f"S{sid}",
            "SketchRouteSeqOrder": route_seq,
            "isRoute": "Yes" if is_route else None,
            "selected": False,
            "aligned": True,
            "feat_type": "park" if base_key == "park" else None,
            "otype": "Line" if geom_type == "LineString" else "Polygon",
        }
        if geom_type == "LineString":
            geom = {"type": "LineString",
                    "coordinates": [list(p) for p in coords]}
        else:
            geom = {"type": "Polygon",
                    "coordinates": [[list(p) for p in coords] + [list(coords[0])]]}
        feats.append({"type": "Feature", "properties": props, "geometry": geom})
        order.append((f"S{sid}", base_key, props["otype"]))
        sid += 1

    for k, coords in cell["streets"].items():
        add(k, "LineString", coords, is_route=(k in ROUTE_KEYS),
            route_seq=(0 if k in ROUTE_KEYS else None))
    add("park", "Polygon", cell["park"])
    for k, ring in cell["landmarks"].items():
        add(k, "Polygon", ring)

    return {"type": "FeatureCollection", "features": feats}, order


def alignment_block(order):
    """Produce the SketchMapia alignment dict entries (1-based keys) for a
    single sketch: each sketch feature is a 1:1 'No generalization' alignment
    to its matching base feature."""
    out = {}
    for i, (sid, base_key, _) in enumerate(order, start=1):
        out[str(i)] = {
            "BaseAlign": {"0": [BASE_ID[base_key]]},
            "SketchAlign": {"0": [sid]},
            "genType": "No generalization",
            "degreeOfGeneralization": 0.0,
        }
    out["checkAlignnum"] = len(order)
    return out


# ---------------------------------------------------------------------------
# HAND-DRAWN RENDERING
# ---------------------------------------------------------------------------
def new_axes(bg="white"):
    fig = plt.figure(figsize=(W * PX / DPI, H * PX / DPI), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    fig.patch.set_facecolor(bg)
    return fig, ax


def densify(pts, step=5.0, closed=False):
    pts = [tuple(p) for p in pts]
    if closed:
        pts = pts + [pts[0]]
    out = [np.array(pts[0], float)]
    for a, b in zip(pts[:-1], pts[1:]):
        a, b = np.array(a, float), np.array(b, float)
        n = max(1, int(math.ceil(np.linalg.norm(b - a) / step)))
        for k in range(1, n + 1):
            out.append(a + (b - a) * k / n)
    return np.array(out)


def wobble(pts, rng, amp, closed=False):
    """Hand tremor: smooth sideways displacement. Open lines keep their end
    points so strokes still meet at junctions."""
    p = np.asarray(pts, float)
    if amp <= 0 or len(p) < 3:
        return p
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    L = max(s[-1], 1e-9)
    t = np.gradient(p, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-t[:, 1], t[:, 0]])
    off = np.zeros(len(p))
    if closed:
        for k in (1, 2, 3):
            off += rng.uniform(0.3, 0.6) * np.sin(
                2 * math.pi * k * s / L + rng.uniform(0, 6.28))
    else:
        for lam in (rng.uniform(45, 80), rng.uniform(90, 170)):
            off += rng.uniform(0.4, 0.7) * np.sin(
                2 * math.pi * s / lam + rng.uniform(0, 6.28))
        off *= np.clip(np.minimum(s, L - s) / 14.0, 0, 1)
    return p + nrm * (amp * off)[:, None]


def end_dirs(line):
    k = min(3, len(line) - 1)
    d0 = line[0] - line[k]
    d1 = line[-1] - line[-1 - k]
    return d0 / max(np.linalg.norm(d0), 1e-9), d1 / max(np.linalg.norm(d1), 1e-9)


def draw_roads(ax, lines, dead_ends, road_w, edge_w, edge_col, fill_col,
               z=2, bg="white"):
    """Roads as two parallel edge lines: a wide dark stroke with a narrower
    light stroke on top. Dead ends are left open."""
    for l in lines:
        ax.plot(l[:, 0], l[:, 1], color=edge_col, lw=road_w * U2PT,
                solid_capstyle="round", solid_joinstyle="round", zorder=z)
    for p, d in dead_ends:
        a, b = p + d * 0.2, p + d * (road_w / 2 + 2)
        ax.plot([a[0], b[0]], [a[1], b[1]], color=bg,
                lw=(road_w + 3) * U2PT, solid_capstyle="butt", zorder=z + 0.1)
    for l in lines:
        ax.plot(l[:, 0], l[:, 1], color=fill_col,
                lw=(road_w - 2 * edge_w) * U2PT, solid_capstyle="round",
                solid_joinstyle="round", zorder=z + 0.2)
    for p, d in dead_ends:
        a, b = p + d * 0.2, p + d * (road_w / 2 + 2)
        ax.plot([a[0], b[0]], [a[1], b[1]], color=bg,
                lw=(road_w - 2 * edge_w - 0.4) * U2PT,
                solid_capstyle="butt", zorder=z + 0.3)


def _mid_and_angle(line):
    seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    i = int(np.searchsorted(s, s[-1] / 2))
    i = min(max(i, 2), len(line) - 3)
    d = line[i + 2] - line[i - 2]
    ang = math.degrees(math.atan2(d[1], d[0]))
    if ang > 90:
        ang -= 180
    if ang <= -90:
        ang += 180
    return line[i], ang


def _node_degrees(streets):
    deg = {}
    for coords in streets.values():
        for n in (tuple(coords[0]), tuple(coords[-1])):
            deg[n] = deg.get(n, 0) + 1
    return deg


def render_map(streets, landmarks, park, path, route_keys=ROUTE_KEYS,
               labels=True, title=None, seed=0, bg="white"):
    """Hand-drawn rendering: densified strokes, wobble on every line and
    polygon ring, handwritten font for labels. No Warp - every transform is
    kept clean so GMDA measures what we designed."""
    rng = np.random.default_rng(seed)
    fname = FONT_FILES[int(rng.integers(len(FONT_FILES)))]
    fp = fm.FontProperties(fname=os.path.join(FONTS_DIR, fname))
    fscale = FONT_SCALE[fname]
    ink = INKS[int(rng.integers(len(INKS)))]
    pen = float(rng.uniform(1.25, 1.7))
    road_w = float(rng.uniform(15.5, 17.5))
    amp = float(rng.uniform(1.4, 2.3))

    fig, ax = new_axes(bg=bg)
    ax.add_patch(plt.Rectangle((0, 0), W, H, facecolor=bg, zorder=0))

    # Park: wobbly green polygon.
    park_line = wobble(densify(park, closed=True), rng, amp * 0.8, closed=True)
    ax.fill(park_line[:, 0], park_line[:, 1], facecolor="#d7e4c7",
            edgecolor="#4e7030", lw=pen * U2PT, joinstyle="round", zorder=1)
    if labels:
        cx = sum(p[0] for p in park) / len(park)
        cy = sum(p[1] for p in park) / len(park)
        ax.text(cx, cy + 20, "Park", fontproperties=fp,
                fontsize=10 * fscale, rotation=float(rng.uniform(-3, 3)),
                ha="center", va="center", color="#355722", zorder=6)

    # Streets.
    deg = _node_degrees(streets)
    lines, dead, line_by_key = [], [], {}
    for k, coords in streets.items():
        base_line = densify(coords)
        line = wobble(base_line, rng, amp)
        lines.append(line)
        d0, d1 = end_dirs(line)
        if deg[tuple(coords[0])] == 1:
            dead.append((line[0], d0))
        if deg[tuple(coords[-1])] == 1:
            dead.append((line[-1], d1))
        line_by_key[k] = (line, coords)
    draw_roads(ax, lines, dead, road_w, pen, ink, "white", bg=bg)

    # Street name on the midpoint of each drawn street.
    if labels:
        STREET_NAMES = {"s_S": "South St", "s_M": "Main St", "s_N": "North St",
                        "s_W": "West Ave", "s_T1": "First Ln", "s_T2": "Second Ln"}
        for k, (line, _coords) in line_by_key.items():
            name = STREET_NAMES.get(k, k)
            p, ang = _mid_and_angle(line)
            ax.text(p[0], p[1], name, fontproperties=fp,
                    fontsize=(road_w - 2 * pen) * U2PT * 0.78 * fscale,
                    rotation=ang + float(rng.uniform(-1.5, 1.5)),
                    rotation_mode="anchor", ha="center", va="center",
                    color=ink, zorder=4)

    # Landmarks.
    for k, ring in landmarks.items():
        wobbled = wobble(densify(ring, closed=True), rng, amp * 0.8,
                         closed=True)
        ax.fill(wobbled[:, 0], wobbled[:, 1], facecolor="white",
                edgecolor=ink, lw=pen * U2PT, joinstyle="round", zorder=5)
        if labels:
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            ax.text(cx, cy, k, fontproperties=fp,
                    fontsize=10 * fscale,
                    rotation=float(rng.uniform(-4, 4)),
                    ha="center", va="center", color=ink, zorder=6)

    if title:
        ax.text(W / 2, H - 10, title, fontproperties=fp,
                fontsize=9 * fscale, ha="center", va="top",
                color="#333", zorder=10)

    fig.savefig(path, dpi=DPI, facecolor=bg)
    plt.close(fig)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def _bool(val):
    return "pass" if val else "fail"


def main():
    os.makedirs(OUT, exist_ok=True)

    # Base map (PNG + GeoJSON).
    render_map(BASE_STREETS, BASE_LANDMARKS, PARK,
               os.path.join(OUT, "basemap.png"), title="Base map", seed=1)
    with open(os.path.join(OUT, "basemap.png.geojson"), "w",
              encoding="utf-8") as fh:
        json.dump(base_feature_collection(), fh, indent=2)

    alignment_all = {}
    answer_rows = []

    for i, (name, group, fn) in enumerate(SKETCH_FUNCS, start=1):
        cell = fn()
        png_path = os.path.join(OUT, f"{name}.png")
        geo_path = os.path.join(OUT, f"{name}.png.geojson")

        render_map(cell["streets"], cell["landmarks"], cell["park"],
                   png_path, title=f"{name}  (group {group})",
                   seed=100 + i)

        fc, order = sketch_feature_collection(cell)
        with open(geo_path, "w", encoding="utf-8") as fh:
            json.dump(fc, fh, indent=2)

        alignment_all[f"{name}.png"] = alignment_block(order)

        row = {"sketch": name, "group": group,
               "winner": "SketchMapia" if group == "A" else "GMDA"}
        for k in QA_KEYS:
            row[QA_NAMES[k]] = _bool(cell["expected"][k])
        for k in GMDA_KEYS:
            row[GMDA_NAMES[k]] = _bool(cell["expected"][k])
        answer_rows.append(row)

    with open(os.path.join(OUT, "alignment.json"), "w",
              encoding="utf-8") as fh:
        json.dump(alignment_all, fh, indent=2)

    fieldnames = (["sketch", "group", "winner"]
                  + [QA_NAMES[k] for k in QA_KEYS]
                  + [GMDA_NAMES[k] for k in GMDA_KEYS])
    with open(os.path.join(OUT, "answer_key.csv"), "w", encoding="utf-8",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for row in answer_rows:
            w.writerow(row)

    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as fh:
        fh.write(README)

    print(f"wrote {len(SKETCH_FUNCS)} sketches + base map to {OUT}")


README = """# Discriminator sketch maps: Qualitative Accuracy vs. GMDA

12 sketch maps derived from one small synthetic base map
(6 streets, 1 park, 5 landmarks). Each sketch is designed to isolate a
single discriminator between SketchMapia's qualitative-accuracy
qualifiers and the GMDA metric measures.

## Group A — SketchMapia wins (categorical error, GMDA blind)

| Sketch                 | Error                                                       | Qualifier that fails              |
|------------------------|-------------------------------------------------------------|-----------------------------------|
| A1_linear_ordering     | Route visits L1 -> L3 -> L2                                 | BuildingRoute_LinearOrdering      |
| A2_side_of_route       | L2 drawn north of the route instead of south                | BuildingRoute_LeftRight           |
| A3_connectedness       | s_T1 drawn with a 10 unit gap at its join with s_M          | StreetsConnectedness              |
| A4_rcc_containment     | L4 drawn just outside the park outline                      | BuildingTopology (RCC)            |
| A5_de9im_touching      | L5 drawn with a 12 unit gap from s_W                        | StreetBuildingTopology (DE9IM)    |
| A6_opra_orientation    | s_T1 drawn diagonally, dead-ending into s_T2                | StreetsOrientation (OPRA)         |

## Group B — GMDA wins (metric error, QA relations preserved)

| Sketch                 | Transformation                                              | GMDA aspect that fails            |
|------------------------|-------------------------------------------------------------|-----------------------------------|
| B1_rotation            | Rigid 20 degree rotation about the centre                   | RotBias, AngAcc, CanOrg, CanAcc   |
| B2_scale_uniform       | Uniform 0.7x scale about the centre                         | ScaBias, DistAcc, CanAcc          |
| B3_scale_anisotropic   | sx=0.7, sy=1.0 about the centre                             | ScaBias, AngAcc, DistAcc, CanAcc  |
| B4_distance_jitter     | Landmarks jittered inside their cells (streets unchanged)   | DistAcc, CanAcc                   |
| B5_shear               | Horizontal shear x += 0.3 * (y - 300)                       | AngAcc, CanAcc                    |
| B6_translate_rotate    | +40 east, 8 degree rotation                                 | RotBias, CanAcc, CanOrg           |

## Files

* `basemap.png`, `basemap.png.geojson`                 - the shared base map
* `A*.png`, `A*.png.geojson`, `B*.png`, `B*.png.geojson`
                                                        - 12 sketch maps
* `alignment.json`                                     - 1:1 base-to-sketch alignment per sketch
* `answer_key.csv`                                     - expected pass/fail per QA qualifier and GMDA aspect

Coordinates are in the SketchMapia editor space: x in [0, 850],
y in [0, 600], y pointing up (the editor stretches every uploaded image
onto [[0,0],[600,850]]).
"""


if __name__ == "__main__":
    main()
