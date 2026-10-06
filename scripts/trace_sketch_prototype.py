"""Prototype sketch-map tracer.

Takes an image of a hand-drawn sketch map and writes a GeoJSON file with:
  - streets as LineString features
  - buildings as Polygon features

No text / labels are extracted. Nothing is sent to any server.

Usage
-----
    python scripts/trace_sketch_prototype.py INPUT_IMAGE
    python scripts/trace_sketch_prototype.py INPUT_IMAGE --output out.geojson --debug

With --debug it also writes intermediate .png files next to the output
(binary mask, building mask, skeleton) so you can see what's going on
and tune thresholds.

Install
-------
    pip install opencv-python numpy scikit-image shapely

Coordinate system
-----------------
GeoJSON coordinates are in IMAGE pixel space, with the origin at the
image's top-left corner (x grows right, y grows DOWN). That is NOT what
the editor's Leaflet CRS.Simple uses -- the editor expects y to grow
UP within a 600 x 850 canvas. The mapping will be sorted out when we
wire this into the app; for now, output is kept pixel-honest so you can
overlay the result on the input image for debugging.

Known limitations (prototype)
-----------------------------
- Dense parallel streets can get merged by the skeletoniser.
- Letters that touch a street will leak into the skeleton as noise.
- Building polygons are polygon approximations of contours and may be
  slightly off from the hand-drawn outline.
- No tuning per-image -- single global threshold set is used.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from typing import List, Tuple

import cv2
import numpy as np
from skimage.morphology import skeletonize
from shapely.geometry import LineString, MultiLineString, Polygon, shape as shape_from_geojson
from shapely.ops import linemerge, unary_union, snap as shp_snap


# App's Simple-CRS canvas size, used to put tracer output and hand-drawn
# ground-truth GeoJSON in the same frame for comparison.
APP_CANVAS_WIDTH  = 850.0
APP_CANVAS_HEIGHT = 600.0

# Matching thresholds for the compare step.
MATCH_IOU_BUILDING          = 0.30   # polygon IoU to count as a match
MATCH_LINE_BUFFER_FRAC      = 0.015  # buffer width = frac * canvas-width
MATCH_LINE_IOU_IN_BUFFER    = 0.30   # buffered-line IoU threshold


# ---------------------------------------------------------------------------
# Tunables. These are the knobs we'll iterate on when we look at results.
# ---------------------------------------------------------------------------
MIN_BUILDING_AREA_PX     = 400     # smaller contours are discarded as noise
MAX_BUILDING_AREA_FRAC   = 0.25    # anything bigger than this fraction of
                                   # the full image is almost certainly the
                                   # outer page border, not a building
MIN_BUILDING_CIRCULARITY = 0.08    # 4*pi*A / P^2 ; buildings tend to be
                                   # compact-ish, lines are very non-compact
BUILDING_POLY_EPS_FRAC   = 0.015   # fraction of perimeter used as the
                                   # Douglas-Peucker epsilon

MIN_STREET_LENGTH_PX     = 40      # throw away tiny polylines
STREET_SIMPLIFY_TOL_PX   = 2.0     # Douglas-Peucker tolerance for lines


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------
def preprocess(bgr: np.ndarray) -> np.ndarray:
    """Return a binary mask where strokes = 255, paper = 0."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # Light blur reduces paper-texture noise without eating thin strokes.
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    # Adaptive threshold handles uneven lighting / scan shadows better than
    # a global Otsu does on photographed sketches.
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,  # strokes become 255 (foreground)
        blockSize=25,
        C=15,
    )
    # Small closing joins tiny gaps in strokes without merging neighbours.
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return binary


def remove_small_blobs(binary: np.ndarray, min_area: int) -> np.ndarray:
    """Erase connected components smaller than min_area -- the main cheap
    way of killing text and specks before we skeletonise streets."""
    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = np.zeros_like(binary)
    for i in range(1, nlabels):   # label 0 is background
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[labels == i] = 255
    return out


# ---------------------------------------------------------------------------
# Text removal (classical, no OCR)
# ---------------------------------------------------------------------------
# Character-sized connected components are flagged by shape stats and erased
# before street / building extraction. Keeps streets (very low extent in
# their bbox) and buildings (large area) by design.
TEXT_MIN_AREA        = 30
TEXT_MAX_AREA        = 1500
TEXT_MIN_BBOX_H      = 12
TEXT_MAX_BBOX_H      = 70
TEXT_MIN_BBOX_W      = 5
TEXT_MAX_BBOX_W      = 140
TEXT_MIN_ASPECT      = 0.15
TEXT_MAX_ASPECT      = 3.00
TEXT_MIN_EXTENT      = 0.15
TEXT_MAX_EXTENT      = 0.90


def mask_text_components(binary: np.ndarray):
    """Return (binary_without_text, text_mask).

    Flags small compact components with character-like proportions, dilates
    the mask slightly to catch touching parts of the same letter, and
    subtracts it from the input binary.
    """
    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    text_mask = np.zeros_like(binary)
    for i in range(1, nlabels):
        x, y, w, h, area = (stats[i, cv2.CC_STAT_LEFT],
                             stats[i, cv2.CC_STAT_TOP],
                             stats[i, cv2.CC_STAT_WIDTH],
                             stats[i, cv2.CC_STAT_HEIGHT],
                             stats[i, cv2.CC_STAT_AREA])
        if area < TEXT_MIN_AREA or area > TEXT_MAX_AREA:
            continue
        if h < TEXT_MIN_BBOX_H or h > TEXT_MAX_BBOX_H:
            continue
        if w < TEXT_MIN_BBOX_W or w > TEXT_MAX_BBOX_W:
            continue
        aspect = w / max(h, 1)
        if not (TEXT_MIN_ASPECT < aspect < TEXT_MAX_ASPECT):
            continue
        extent = area / float(w * h)
        if not (TEXT_MIN_EXTENT < extent < TEXT_MAX_EXTENT):
            continue
        text_mask[labels == i] = 255

    # Expand slightly so adjacent parts of broken letters go with the mask.
    text_mask = cv2.dilate(text_mask,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
                           iterations=1)
    cleaned = cv2.bitwise_and(binary, cv2.bitwise_not(text_mask))
    return cleaned, text_mask


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------
def extract_buildings(binary: np.ndarray) -> Tuple[List[np.ndarray], np.ndarray]:
    """Find building-like contours.

    Returns (list of (N,2) int arrays in image coords, building_mask uint8)."""
    h, w = binary.shape
    img_area = h * w

    # The input is a stroke mask. Dilate slightly so almost-closed outlines
    # become closed and findContours can enclose them.
    dilated = cv2.dilate(binary,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
                         iterations=1)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    buildings: List[np.ndarray] = []
    mask = np.zeros_like(binary)

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < MIN_BUILDING_AREA_PX:
            continue
        if area > MAX_BUILDING_AREA_FRAC * img_area:
            continue
        peri = cv2.arcLength(cnt, closed=True)
        if peri <= 0:
            continue
        circ = 4 * np.pi * area / (peri * peri)
        if circ < MIN_BUILDING_CIRCULARITY:
            continue   # elongated -- probably a street
        eps = BUILDING_POLY_EPS_FRAC * peri
        poly = cv2.approxPolyDP(cnt, eps, closed=True).reshape(-1, 2)
        if len(poly) < 3:
            continue
        buildings.append(poly)
        cv2.drawContours(mask, [cnt], -1, 255, thickness=cv2.FILLED)

    return buildings, mask


# ---------------------------------------------------------------------------
# Streets (skeleton -> polylines)
# ---------------------------------------------------------------------------
def _neighbors(y: int, x: int, skel: np.ndarray) -> List[Tuple[int, int]]:
    """8-connected neighbours of (y,x) that are also skeleton pixels."""
    h, w = skel.shape
    out = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and skel[ny, nx]:
                out.append((ny, nx))
    return out


def extract_streets(binary_no_buildings: np.ndarray) -> List[List[Tuple[int, int]]]:
    """Skeletonise the street mask and traverse the skeleton to produce
    polylines (one per segment between endpoints / junctions).

    Returns list of polylines as [(x, y), ...] in image coords.
    """
    # skimage.morphology.skeletonize expects a boolean image
    skel = skeletonize(binary_no_buildings > 0).astype(np.uint8)
    h, w = skel.shape

    # Count skeleton neighbours per pixel -- 1 = endpoint, 3+ = junction.
    # cv2.filter2D needs matching uint8/float32 src+dst; use float32.
    kernel = np.array([[1, 1, 1],
                       [1, 10, 1],
                       [1, 1, 1]], dtype=np.float32)
    neigh = cv2.filter2D(skel.astype(np.float32), -1, kernel).astype(np.int32)
    # Pixels where the centre is skeletal: neigh - 10 gives neighbour count.
    on_skel = skel > 0
    count = np.where(on_skel, neigh - 10, 0)

    endpoints = set(zip(*np.where(count == 1)))
    junctions = set(zip(*np.where(count >= 3)))
    terminals = endpoints | junctions

    visited = set()
    polylines: List[List[Tuple[int, int]]] = []

    def walk(start_yx, first_step_yx):
        """Walk along a 2-neighbour chain, stopping at a terminal."""
        path = [start_yx, first_step_yx]
        prev, cur = start_yx, first_step_yx
        while True:
            if cur in terminals:
                return path
            nxt = None
            for n in _neighbors(cur[0], cur[1], skel):
                if n != prev:
                    nxt = n
                    break
            if nxt is None:
                return path
            path.append(nxt)
            prev, cur = cur, nxt
            if cur in visited and cur not in terminals:
                return path

    # Start walks from every terminal, following each unvisited outgoing
    # neighbour exactly once.
    for term in terminals:
        for nb in _neighbors(term[0], term[1], skel):
            edge_key = frozenset((term, nb))
            if edge_key in visited:
                continue
            path = walk(term, nb)
            for i in range(len(path) - 1):
                visited.add(frozenset((path[i], path[i + 1])))
            polylines.append(path)

    # Convert (y, x) -> (x, y)
    polylines_xy = [[(x, y) for (y, x) in p] for p in polylines]
    return polylines_xy


# ---------------------------------------------------------------------------
# Postprocessing to GeoJSON
# ---------------------------------------------------------------------------

# Snap tolerance for merging polyline endpoints that are "nearly touching"
# -- in pixels. Set generously enough that stroke jitter at a junction
# doesn't prevent two skeleton walks from being treated as one line.
STREET_SNAP_TOL_PX = 4.0


def merge_street_polylines(polylines_px):
    """Collapse touching / near-touching skeleton polylines into longer lines.

    1. Build shapely LineStrings from each walk.
    2. Snap endpoints to a shared network to close near-touching gaps.
    3. unary_union + linemerge collapses runs of segments that share
       endpoints at a 2-degree junction into one line. Real junctions
       (3+ incident lines) stay split, as they should.
    """
    if not polylines_px:
        return []
    lines = []
    for p in polylines_px:
        if len(p) < 2:
            continue
        try:
            ln = LineString(p)
            if ln.length > 0:
                lines.append(ln)
        except Exception:
            pass
    if not lines:
        return []

    network = unary_union(lines)
    # snap() needs a non-empty reference -- snap network to itself with the
    # chosen tolerance. This pulls endpoints that are a few px apart onto
    # one shared point so linemerge can then fuse them.
    try:
        network = shp_snap(network, network, STREET_SNAP_TOL_PX)
    except Exception:
        pass

    merged = linemerge(network)
    if merged.geom_type == 'MultiLineString':
        out = list(merged.geoms)
    elif merged.geom_type == 'LineString':
        out = [merged]
    else:
        out = []
    return out


def linestrings_to_geojson_features(linestrings, start_id: int) -> tuple:
    feats = []
    nid = start_id
    for line in linestrings:
        if line.is_empty:
            continue
        line = line.simplify(STREET_SIMPLIFY_TOL_PX, preserve_topology=False)
        if line.is_empty or line.length < MIN_STREET_LENGTH_PX \
                or len(line.coords) < 2:
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "id": nid,
                "otype": "Line",
                "feat_type": None,
                "isRoute": None,
                "aligned": False,
                "selected": False,
                "proposed": True,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[float(x), float(y)] for (x, y) in line.coords],
            },
        })
        nid += 1
    return feats, nid


def polylines_to_geojson_features(polylines, start_id: int, image_h: int) -> tuple:
    """Backwards-compat wrapper: skeleton polylines -> merged -> features."""
    merged = merge_street_polylines(polylines)
    return linestrings_to_geojson_features(merged, start_id)


def polygons_to_geojson_features(polys, start_id: int, image_h: int) -> list:
    feats = []
    nid = start_id
    for pts in polys:
        if len(pts) < 3:
            continue
        try:
            poly = Polygon([(float(x), float(y)) for (x, y) in pts])
            if not poly.is_valid or poly.area < MIN_BUILDING_AREA_PX:
                continue
        except Exception:
            continue
        ring = list(poly.exterior.coords)
        feats.append({
            "type": "Feature",
            "properties": {
                "id": nid,
                "otype": "Polygon",
                "feat_type": "Landmark",
                "isRoute": None,
                "aligned": False,
                "selected": False,
                "proposed": True,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[float(x), float(y)] for (x, y) in ring]],
            },
        })
        nid += 1
    return feats, nid


# ---------------------------------------------------------------------------
# Coordinate conversion for comparison with hand-annotated ground truth
# ---------------------------------------------------------------------------
def image_px_to_app_canvas(coords_px, image_w: int, image_h: int):
    """Convert (x_px, y_px) from image-pixel space (origin top-left, y-down)
    to the app's Leaflet Simple-CRS frame (origin bottom-left, y-up, canvas
    APP_CANVAS_WIDTH x APP_CANVAS_HEIGHT). Used so tracer output can be
    compared with hand-drawn GeoJSON exported from the editor.
    """
    sx = APP_CANVAS_WIDTH  / float(image_w)
    sy = APP_CANVAS_HEIGHT / float(image_h)
    out = []
    for x, y in coords_px:
        out.append((x * sx, APP_CANVAS_HEIGHT - y * sy))
    return out


# ---------------------------------------------------------------------------
# Compare vs hand-annotated GeoJSON
# ---------------------------------------------------------------------------
def _load_ground_truth(path: str):
    """Return (hand_lines, hand_polys) as Shapely geoms, filtering by otype."""
    with open(path, "r", encoding="utf-8") as f:
        gj = json.load(f)
    lines, polys = [], []
    for feat in gj.get("features", []):
        geom_type = (feat.get("geometry") or {}).get("type")
        props = feat.get("properties") or {}
        otype = props.get("otype")
        try:
            geom = shape_from_geojson(feat["geometry"])
        except Exception:
            continue
        if not geom.is_valid or geom.is_empty:
            continue
        if geom_type == "LineString" or otype == "Line":
            lines.append(geom)
        elif geom_type == "Polygon" or otype == "Polygon":
            polys.append(geom)
    return lines, polys


def _poly_iou(a: Polygon, b: Polygon) -> float:
    try:
        inter = a.intersection(b).area
        union = a.union(b).area
        return (inter / union) if union > 0 else 0.0
    except Exception:
        return 0.0


def _line_iou_buffered(a: LineString, b: LineString, buf: float) -> float:
    try:
        ab = a.buffer(buf)
        bb = b.buffer(buf)
        inter = ab.intersection(bb).area
        union = ab.union(bb).area
        return (inter / union) if union > 0 else 0.0
    except Exception:
        return 0.0


def _greedy_match(hand, auto, score_fn, threshold):
    """Greedy maximum-score matching. Returns match count."""
    pairs = []
    for i, hg in enumerate(hand):
        for j, ag in enumerate(auto):
            s = score_fn(hg, ag)
            if s >= threshold:
                pairs.append((s, i, j))
    pairs.sort(key=lambda t: -t[0])
    used_h, used_a = set(), set()
    matched = 0
    for s, i, j in pairs:
        if i in used_h or j in used_a:
            continue
        used_h.add(i); used_a.add(j); matched += 1
    return matched


def compare_with_ground_truth(auto_street_feats, auto_building_feats,
                              image_w, image_h, gt_path):
    """Compare tracer output against the hand-annotated GeoJSON.

    Returns a dict with per-category counts and precision/recall/F1.
    """
    hand_lines, hand_polys = _load_ground_truth(gt_path)

    # Transform tracer output (image pixels) into the same frame the hand
    # ground truth lives in (app canvas).
    auto_lines = []
    for ft in auto_street_feats:
        coords = ft["geometry"]["coordinates"]
        auto_lines.append(LineString(image_px_to_app_canvas(coords, image_w, image_h)))
    auto_polys = []
    for ft in auto_building_feats:
        ring = ft["geometry"]["coordinates"][0]
        try:
            auto_polys.append(Polygon(image_px_to_app_canvas(ring, image_w, image_h)))
        except Exception:
            pass

    buf = APP_CANVAS_WIDTH * MATCH_LINE_BUFFER_FRAC

    matched_lines = _greedy_match(
        hand_lines, auto_lines,
        lambda a, b: _line_iou_buffered(a, b, buf),
        MATCH_LINE_IOU_IN_BUFFER,
    )
    matched_polys = _greedy_match(
        hand_polys, auto_polys,
        _poly_iou,
        MATCH_IOU_BUILDING,
    )

    def _prf(matched, auto_n, hand_n):
        p = matched / auto_n if auto_n else 0.0
        r = matched / hand_n if hand_n else 0.0
        f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
        return round(p, 3), round(r, 3), round(f1, 3)

    s_p, s_r, s_f = _prf(matched_lines, len(auto_lines), len(hand_lines))
    b_p, b_r, b_f = _prf(matched_polys, len(auto_polys), len(hand_polys))

    return {
        "hand_streets": len(hand_lines),
        "auto_streets": len(auto_lines),
        "matched_streets": matched_lines,
        "streets_precision": s_p,
        "streets_recall": s_r,
        "streets_f1": s_f,
        "hand_buildings": len(hand_polys),
        "auto_buildings": len(auto_polys),
        "matched_buildings": matched_polys,
        "buildings_precision": b_p,
        "buildings_recall": b_r,
        "buildings_f1": b_f,
    }


# ---------------------------------------------------------------------------
# Trace a single image. Returns (street_feats, building_feats, w, h,
# building_pts_px, street_polylines_px) so the caller can both write files
# and (optionally) produce debug overlays.
# ---------------------------------------------------------------------------
def trace_one(image_path: str):
    bgr = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"could not read image: {image_path}")
    h, w = bgr.shape[:2]

    binary = preprocess(bgr)
    binary = remove_small_blobs(binary, min_area=40)

    # Flag and erase character-sized components before anything else looks
    # at the mask. Text that touches a street will still leak -- that's a
    # next-step fix (word-grouping / inpaint) -- but isolated labels go away.
    binary_no_text, text_mask = mask_text_components(binary)

    buildings_pts, building_mask = extract_buildings(binary_no_text)

    street_mask = cv2.bitwise_and(binary_no_text, cv2.bitwise_not(building_mask))
    street_mask = remove_small_blobs(street_mask, min_area=80)

    polylines = extract_streets(street_mask)

    street_feats, next_id = polylines_to_geojson_features(polylines, start_id=1, image_h=h)
    building_feats, _ = polygons_to_geojson_features(buildings_pts, start_id=next_id, image_h=h)
    return {
        "bgr": bgr,
        "w": w, "h": h,
        "binary": binary,
        "binary_no_text": binary_no_text,
        "text_mask": text_mask,
        "building_mask": building_mask,
        "street_mask": street_mask,
        "buildings_pts": buildings_pts,
        "polylines": polylines,
        "street_feats": street_feats,
        "building_feats": building_feats,
    }


def write_outputs(trace, image_path, out_geojson, write_debug: bool):
    with open(out_geojson, "w", encoding="utf-8") as f:
        json.dump({
            "type": "FeatureCollection",
            "features": trace["street_feats"] + trace["building_feats"],
            "properties": {
                "source_image": os.path.basename(image_path),
                "image_width_px": trace["w"],
                "image_height_px": trace["h"],
                "coord_system": "image_pixels_top_left",
            },
        }, f, indent=2)

    if write_debug:
        base = os.path.splitext(out_geojson)[0]
        cv2.imwrite(base + ".dbg_binary.png",        trace["binary"])
        cv2.imwrite(base + ".dbg_text_mask.png",     trace["text_mask"])
        cv2.imwrite(base + ".dbg_binary_no_text.png", trace["binary_no_text"])
        cv2.imwrite(base + ".dbg_building_mask.png", trace["building_mask"])
        cv2.imwrite(base + ".dbg_street_mask.png",   trace["street_mask"])
        overlay = trace["bgr"].copy()
        for poly in trace["buildings_pts"]:
            cv2.polylines(overlay, [poly.reshape(-1, 1, 2)], True, (0, 180, 0), 2)
        for px in trace["polylines"]:
            if len(px) < 2:
                continue
            pts = np.array(px, dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(overlay, [pts], False, (0, 0, 220), 2)
        cv2.imwrite(base + ".dbg_overlay.png", overlay)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _resolve_output_path(image_path: str, out_dir: str | None) -> str:
    base = os.path.splitext(os.path.basename(image_path))[0] + ".traced.geojson"
    return os.path.join(out_dir, base) if out_dir else \
           os.path.splitext(image_path)[0] + ".traced.geojson"


def _find_ground_truth(image_path: str) -> str | None:
    """Look for a hand-annotated GeoJSON next to the image.

    The editor exports as "<image_filename>.geojson" (keeping the extension),
    e.g. AS_Sketch_1.jpg -> AS_Sketch_1.jpg.geojson. Also accept the
    stem-only "AS_Sketch_1.geojson" as a fallback.
    """
    cand1 = image_path + ".geojson"
    if os.path.isfile(cand1):
        return cand1
    cand2 = os.path.splitext(image_path)[0] + ".geojson"
    if os.path.isfile(cand2):
        return cand2
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", nargs="?", help="Path to a single sketch-map image.")
    ap.add_argument("--dir", help="Process every image in this folder.")
    ap.add_argument("--out-dir", help="Where to put outputs when using --dir.")
    ap.add_argument("--output", "-o", help="Output GeoJSON path for single-image mode.")
    ap.add_argument("--debug", action="store_true",
                    help="Also write intermediate PNGs for every traced image.")
    ap.add_argument("--compare", action="store_true",
                    help="Compare each traced output against a hand-annotated "
                         "<image>.geojson sitting next to the image.")
    ap.add_argument("--summary", help="CSV summary path. Implies --compare if given.")
    args = ap.parse_args(argv)

    if not args.image and not args.dir:
        ap.error("provide either an image path or --dir FOLDER")

    # Build the list of input images.
    images: list[str] = []
    if args.image:
        if not os.path.isfile(args.image):
            print(f"error: not a file: {args.image}", file=sys.stderr)
            return 2
        images.append(args.image)
    if args.dir:
        if not os.path.isdir(args.dir):
            print(f"error: not a directory: {args.dir}", file=sys.stderr)
            return 2
        exts = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp", "*.tif", "*.tiff")
        for ext in exts:
            images.extend(glob.glob(os.path.join(args.dir, ext)))
            images.extend(glob.glob(os.path.join(args.dir, ext.upper())))
        images = sorted(set(images))
        if not images:
            print(f"error: no images found in {args.dir}", file=sys.stderr)
            return 2
        print(f"[trace] batch mode: {len(images)} images under {args.dir}")

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)

    do_compare = args.compare or bool(args.summary)
    summary_rows: list[dict] = []
    failures: list[tuple[str, str]] = []

    for img in images:
        try:
            trace = trace_one(img)
        except Exception as exc:
            print(f"[trace] {img}: FAILED ({exc})", file=sys.stderr)
            failures.append((img, str(exc)))
            continue

        out_path = args.output if (args.output and args.image and not args.dir) \
                   else _resolve_output_path(img, args.out_dir)
        write_outputs(trace, img, out_path, args.debug)

        n_streets = len(trace["street_feats"])
        n_bldgs   = len(trace["building_feats"])
        print(f"[trace] {os.path.basename(img)}  "
              f"size={trace['w']}x{trace['h']}  "
              f"streets={n_streets} buildings={n_bldgs} -> {out_path}")

        if do_compare:
            gt = _find_ground_truth(img)
            row = {"image": os.path.basename(img),
                   "has_ground_truth": bool(gt)}
            if gt:
                cmp_metrics = compare_with_ground_truth(
                    trace["street_feats"], trace["building_feats"],
                    trace["w"], trace["h"], gt,
                )
                row.update(cmp_metrics)
                print(f"       vs ground truth [{os.path.basename(gt)}]: "
                      f"streets P/R/F1 = {row['streets_precision']}/"
                      f"{row['streets_recall']}/{row['streets_f1']}  "
                      f"buildings P/R/F1 = {row['buildings_precision']}/"
                      f"{row['buildings_recall']}/{row['buildings_f1']}")
            else:
                print("       (no ground truth found next to image)")
            summary_rows.append(row)

    if args.summary and summary_rows:
        cols = ["image", "has_ground_truth",
                "hand_streets", "auto_streets", "matched_streets",
                "streets_precision", "streets_recall", "streets_f1",
                "hand_buildings", "auto_buildings", "matched_buildings",
                "buildings_precision", "buildings_recall", "buildings_f1"]
        with open(args.summary, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            for row in summary_rows:
                writer.writerow(row)
        print(f"[trace] summary: {args.summary}  ({len(summary_rows)} rows)")

        # Also print a brief aggregate so stdout tells the story at a glance.
        with_gt = [r for r in summary_rows if r.get("has_ground_truth")]
        if with_gt:
            def _mean(key): return sum(r.get(key, 0) for r in with_gt) / len(with_gt)
            print(f"[trace] mean over {len(with_gt)} images with ground truth:")
            print(f"        streets    P={_mean('streets_precision'):.2f}  "
                  f"R={_mean('streets_recall'):.2f}  F1={_mean('streets_f1'):.2f}")
            print(f"        buildings  P={_mean('buildings_precision'):.2f}  "
                  f"R={_mean('buildings_recall'):.2f}  F1={_mean('buildings_f1'):.2f}")

    if failures:
        print(f"[trace] {len(failures)} image(s) failed.")
        for p, e in failures:
            print(f"        {p}: {e}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
