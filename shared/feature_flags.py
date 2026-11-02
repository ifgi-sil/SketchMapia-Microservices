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
