"""
Annotate a GeoJSON feature collection with the per-feature flags that
the weighted measurement scheme (see shared/measurement_weights.py)
needs for scoring:

    properties.on_route         -> bool (every street + landmark)
    properties.street_position  -> "end" | "middle"  (streets only)

The generalizations service calls ``annotate_route_flags`` once, just
before writing ``generalizedoutputMap.json``.  Completeness scoring and
generalization scoring then read these flags straight off feature
properties, no re-computation needed downstream.

Rules (per supervisor + Charu, 2026-10):

* ``on_route`` for a street  = ``properties.isRoute == "Yes"`` (flag only).
* ``on_route`` for a landmark = polygon adjacent to the merged defined
  route under the same ``computeAdjacency`` test Linear Ordering uses.
* ``street_position`` for every street (on-route or off-route):
    - both endpoints touch another street's endpoint  -> "middle"
    - 0 or 1 touching endpoints                       -> "end"
  Endpoint equality is checked with a small ``EPS`` tolerance to
  tolerate float-precision noise after linemerge / amalgamation.
"""

from shapely.geometry import LineString, Point, Polygon, shape
from shapely import ops

from shared.measurement_weights import generalization_weight

EPS = 1e-6
ADJACENCY_BUFFER_PADDING = 5  # mirrors computeMinMaxDist's +5 in utils_i4l


# ------------------------------------------------------------------
# Helpers reused from the accuracy qualifier (replicated to keep this
# module self-contained; the generalizations container does not import
# from accuracy).
# ------------------------------------------------------------------

def _merged_route(route_lines):
    if not route_lines:
        return None
    merged = ops.linemerge(route_lines) if len(route_lines) > 1 else route_lines[0]
    if merged.geom_type == "LineString":
        return merged
    if merged.geom_type == "MultiLineString":
        coords = []
        for g in merged.geoms:
            coords.extend(list(g.coords))
        return LineString(coords) if len(coords) >= 2 else None
    return merged


def _max_min_dist(polygons, streets):
    """Same tolerance Left/Right + Linear Ordering use: max over polygons
    of the min distance to any non-touching street, plus a small pad."""
    if not polygons or not streets:
        return 0
    min_dists = []
    for poly in polygons:
        dists = [
            poly.distance(s) for s in streets
            if not (poly.touches(s) or poly.intersects(s))
        ]
        if dists:
            min_dists.append(min(dists))
    if not min_dists:
        return 0
    return max(min_dists) + ADJACENCY_BUFFER_PADDING


def _is_adjacent(poly, route, max_dist):
    buf = route.buffer(max_dist)
    return (
        buf.intersects(poly)
        or buf.touches(poly)
        or buf.overlaps(poly)
        or buf.covers(poly)
        or buf.contains(poly)
        or buf.within(poly)
        or buf.crosses(poly)
    )


# ------------------------------------------------------------------
# Street endpoint connectivity
# ------------------------------------------------------------------

def _endpoints(line):
    coords = list(line.coords)
    return Point(coords[0]), Point(coords[-1])


def _endpoint_touches(ep, other_endpoints):
    for other in other_endpoints:
        if abs(ep.x - other.x) < EPS and abs(ep.y - other.y) < EPS:
            return True
    return False


def _position_for_street(line, all_street_endpoints_except_self):
    """Return "middle" iff BOTH endpoints touch some other street's endpoint."""
    start, end = _endpoints(line)
    other = [ep for ep in all_street_endpoints_except_self]
    connected = 0
    if _endpoint_touches(start, other):
        connected += 1
    if _endpoint_touches(end, other):
        connected += 1
    return "middle" if connected == 2 else "end"


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def annotate_route_flags(feature_collection):
    """Mutates and returns ``feature_collection``.

    ``feature_collection`` is a plain dict in GeoJSON shape:
        {"type": "FeatureCollection", "features": [ {geometry, properties}, ... ]}
    """
    features = feature_collection.get("features", [])

    # Build shapely geometries once; keep index parallel to features list.
    geoms = []
    for feat in features:
        try:
            geoms.append(shape(feat["geometry"]))
        except Exception:
            geoms.append(None)

    polygons = [(i, g) for i, g in enumerate(geoms)
                if g is not None and g.geom_type == "Polygon"]
    streets = [(i, g) for i, g in enumerate(geoms)
               if g is not None and g.geom_type == "LineString"]

    # --- defined route (for landmark on_route) ---
    route_lines = [g for i, g in streets
                   if (features[i].get("properties") or {}).get("isRoute") == "Yes"]
    defined_route = _merged_route(route_lines)

    max_dist = _max_min_dist(
        [g for _, g in polygons],
        [g for _, g in streets]
    )

    # --- street endpoints, grouped per-street for the "except self" view ---
    street_endpoints_by_idx = {i: _endpoints(g) for i, g in streets}

    # --- stamp flags ---
    for i, g in polygons:
        props = features[i].setdefault("properties", {}) or {}
        features[i]["properties"] = props
        if defined_route is not None and max_dist > 0:
            props["on_route"] = bool(_is_adjacent(g, defined_route, max_dist))
        else:
            props["on_route"] = False

    for i, g in streets:
        props = features[i].setdefault("properties", {}) or {}
        features[i]["properties"] = props
        props["on_route"] = (props.get("isRoute") == "Yes")

        # Endpoints from every OTHER street (any street, on- or off-route).
        others = []
        for j, (ep1, ep2) in street_endpoints_by_idx.items():
            if j == i:
                continue
            others.append(ep1)
            others.append(ep2)
        props["street_position"] = _position_for_street(g, others)

    return feature_collection


# ------------------------------------------------------------------
# Weighted generalization (Step D)
# ------------------------------------------------------------------

def _base_align_ids(base_align):
    """Normalize BaseAlign (int, list, nested list, or dict-shaped) to a flat
    list of int ids. Returns [] when nothing usable is present."""
    if base_align is None:
        return []
    if isinstance(base_align, dict):
        base_align = list(base_align.values())
    if isinstance(base_align, (list, tuple, set)):
        out = []
        for x in base_align:
            if isinstance(x, (list, tuple, set)):
                for y in x:
                    try:
                        out.append(int(y))
                    except (TypeError, ValueError):
                        continue
            else:
                try:
                    out.append(int(x))
                except (TypeError, ValueError):
                    continue
        return out
    try:
        return [int(base_align)]
    except (TypeError, ValueError):
        return []


def _aggregate_on_route(props, base_on_route):
    """True iff any BaseAlign member is on-route in ``base_on_route``.

    Falls back to the feature's own ``on_route`` flag when ``base_on_route``
    is not provided or the feature has no usable BaseAlign.
    """
    if base_on_route:
        bids = _base_align_ids(props.get("BaseAlign"))
        if bids:
            return any(bool(base_on_route.get(bid)) for bid in bids)
    return bool(props.get("on_route"))


def annotate_generalization_weights(feature_collection, weights,
                                    base_on_route=None):
    """Stamp ``properties.gen_weight`` on every feature of ``feature_collection``.

    See docs/weighted-measurement scheme Step D. Rules:
      - ``No generalization`` or ``missing: true`` -> 0
      - JunctionMerge aggregates (genType2): count * base * route_mul,
        on-route resolved by any member in ``BaseAlign`` being on-route
      - Roundabout aggregates (genType1 == "Roundaboutcollapse"): same shape
      - Multi-MultiOmissionMerge (genType3), base side only: base * route_mul
      - Amalgamation / OmissionMerge / Collapse (polygon) / AbstractionToExistence
        buildings / AbstractionToExistence streets: base * route_mul
      - Anything else (sketch-only, street stubs, unknown) -> 0
    """
    features = feature_collection.get("features", [])
    for feat in features:
        props = feat.setdefault("properties", {}) or {}
        feat["properties"] = props

        gen_type  = props.get("genType")
        gen_type1 = props.get("genType1")
        gen_type2 = props.get("genType2")
        gen_type3 = props.get("genType3")

        if gen_type == "No generalization" or props.get("missing"):
            props["gen_weight"] = 0
            continue

        # JunctionMerge / Roundabout: count * base * route_mul,
        # aggregate on-route resolved via BaseAlign members.
        if gen_type2 == "JunctionMerge":
            count = int(props.get("JunctionMergeCount") or 0)
            on_route = _aggregate_on_route(props, base_on_route)
            per = generalization_weight(weights, "JunctionMerge", on_route)
            props["gen_weight"] = count * per
            continue

        if gen_type1 and "Roundabout" in gen_type1:
            count = int(props.get("RoundAboutCount") or 0)
            on_route = _aggregate_on_route(props, base_on_route)
            per = generalization_weight(weights, "RoundaboutCollapse", on_route)
            props["gen_weight"] = count * per
            continue

        # Multi-MultiOmissionMerge: base-side only (sketch-side duplicates
        # the aggregate for display and must not be counted again).
        if (gen_type3 and "Multi-MultiOmissionMerge" in gen_type3
                and props.get("mapType") != "Sketch"):
            on_route = bool(props.get("on_route"))
            props["gen_weight"] = generalization_weight(
                weights, "Multi-MultiOmissionMerge", on_route
            )
            continue

        # Standard single-type aggregates.
        gen_key = None
        if gen_type == "Amalgamation":
            gen_key = "Amalgamation"
        elif gen_type == "OmissionMerge":
            gen_key = "OmissionMerge"
        elif gen_type == "Collapse":
            gen_key = "Collapse_landmark"
        elif gen_type == "Abstraction to show existence buildings":
            gen_key = "AbstractionToExistence_landmark"
        elif gen_type == "Abstraction to show existence streets":
            gen_key = "AbstractionToExistence_street"

        if gen_key is None:
            props["gen_weight"] = 0
            continue

        on_route = bool(props.get("on_route"))
        props["gen_weight"] = generalization_weight(weights, gen_key, on_route)

    return feature_collection
