import os
import sys
import json
from django.shortcuts import render
from django.http import HttpResponse

# Weighted-measurement-scheme helpers. Both the loader and the flag
# annotator live in /app/shared (mounted via docker-compose). Make sure
# /app is on sys.path so ``from shared.<x> import ...`` resolves even
# when Django's runserver has a different sys.path than ``python -c``.
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

# Weights (pure-Python, no shapely) are mandatory for weighted scoring.
try:
    from shared.measurement_weights import (
        get_weights,
        landmark_completeness_weight,
        street_completeness_weight,
    )
    print("completeness: measurement_weights imported OK")
except Exception as exc:
    import traceback
    print("completeness: measurement_weights import FAILED:", exc)
    traceback.print_exc()
    get_weights = None
    landmark_completeness_weight = None
    street_completeness_weight = None

# feature_flags needs shapely, which isn't in the completeness image.
# Keep this import optional: if it fails, we just skip the inline
# restamp and trust the generalizations service to have stamped the
# flags on its own (which it does since Step B).
try:
    from shared.feature_flags import annotate_route_flags
    print("completeness: feature_flags imported OK (restamp available)")
except Exception as exc:
    print("completeness: feature_flags unavailable, restamp disabled:", exc)
    annotate_route_flags = None


def get_landmarkCompleteness(totalSketchedLandmarks, total_mm_landmark):
    if totalSketchedLandmarks != 0 or total_mm_landmark != 0:
        landmarkCompleteness = (totalSketchedLandmarks / total_mm_landmark) * 100
    else:
        landmarkCompleteness = 0.00
    return landmarkCompleteness


# get stree_completness
def get_streetCompleteness(totalSketchedStreets, toal_mm_streets):
    if totalSketchedStreets != 0 or toal_mm_streets != 0:
        streetCompleteness = (totalSketchedStreets / toal_mm_streets) * 100
    else:
        streetCompleteness = 0.00
    return streetCompleteness


# get cityblock_completeness
def get_cityblockCompleteness(totalSketchedCityblocks, total_mm_cityblocks):
    if totalSketchedCityblocks != 0 or total_mm_cityblocks != 0:
        cityblockCompleteness = (totalSketchedCityblocks / total_mm_cityblocks) * 100
    else:
        cityblockCompleteness = 0.00
    return cityblockCompleteness


# get overall accuracy
def get_overall_completness(landmarkCompleteness, streetCompleteness):
    overAllCompleteness = 0.00
    overAllCompleteness = (landmarkCompleteness + streetCompleteness) / 2

    return overAllCompleteness





def get_streets_mm(mmqcns):
    st_count = 0

    for feature in mmqcns['features']:
        if feature['geometry']['type'] == "LineString":
            st_count += 1
    return st_count


def get_landmarks_mm(mmqcns):
    lm_count = 0
    for feature in mmqcns['features']:
        print (feature, "check check")
        if feature['properties']['feat_type'] == "Landmark":
            lm_count += 1
    return lm_count


"""
    - get total number of drawn street segments
"""


def get_streets_sm(smqcns):
    st_count = 0

    for feature in smqcns['features']:
        if feature['geometry']['type'] == "LineString":
            st_count += 1
    return st_count


"""
    - get total number of drawn landmarks
"""


def get_landmarks_sm(smqcns):
    lm_count = 0

    for feature in smqcns['features']:
        if feature['properties']['feat_type'] == "Landmark":
            lm_count += 1

    return lm_count


def _feature_is_sketched(feat):
    """A base-map feature counts as "sketched" iff it carries a SketchAlign.

    SketchAlign may be a single sid or a list of sids depending on the
    generalization type (OmissionMerge / Amalgamation / No generalization).
    Any non-empty value means the sketcher captured this feature.
    """
    sa = (feat.get("properties") or {}).get("SketchAlign")
    if sa is None:
        return False
    if isinstance(sa, (list, tuple, set)):
        return len(sa) > 0
    return bool(sa)


def _ensure_route_flags(metricMap):
    """Re-stamp on_route / street_position if the generalized basemap
    arrived without them (older project, bypassed generalization, etc.)."""
    features = metricMap.get("features", [])
    if not features:
        return False
    has_flags = any(
        "on_route" in (f.get("properties") or {}) for f in features
    )
    if has_flags or annotate_route_flags is None:
        return has_flags
    print("completeness: metricMap missing on_route flags — restamping inline")
    annotate_route_flags(metricMap)
    return True


def _weighted_completeness(metricMap, weights):
    """Return (landmark_pct, street_pct, overall_pct,
                total_landmark_weight, total_street_weight)."""
    lm_num = lm_den = 0
    st_num = st_den = 0

    for feat in metricMap.get("features", []):
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        on_route = bool(props.get("on_route", False))
        sketched = _feature_is_sketched(feat)

        if props.get("feat_type") == "Landmark":
            w = landmark_completeness_weight(weights, on_route)
            lm_den += w
            if sketched:
                lm_num += w
        elif geom.get("type") == "LineString":
            position = props.get("street_position", "end")
            w = street_completeness_weight(weights, position, on_route)
            st_den += w
            if sketched:
                st_num += w

    lm_pct = (lm_num / lm_den) * 100 if lm_den else 0.0
    st_pct = (st_num / st_den) * 100 if st_den else 0.0
    # Mirror the legacy overall formula: average of the two sub-scores.
    overall_pct = (lm_pct + st_pct) / 2
    return lm_pct, st_pct, overall_pct, lm_den, st_den


def analyzeCompleteness(request):
    print("completeness view version: weighted v1 | get_weights is None?", get_weights is None)
    sketchFileName = request.POST.get('sketchFileName')
    metricFileName = request.POST.get('metricFileName')
    print("check check", sketchFileName, metricFileName)
    sketchmapdata = request.POST.get('sketchdata')
    metricmapdata = request.POST.get('metricdata')

    metricMap = json.loads(metricmapdata)
    sketchMap = json.loads(sketchmapdata)

    total_mm_landmarks = get_landmarks_mm(metricMap)
    toal_mm_streets = get_streets_mm(metricMap)
    # total_mm_cityblocks = completeness.get_cityblocks_mm(metricMap)

    totalSketchedLandmarks = get_landmarks_sm(sketchMap)
    totalSketchedStreets = get_streets_sm(sketchMap)
    # totalSketchedCityblocks = completeness.get_cityblocks_sm(sketchMap)

    landmarkCompleteness = get_landmarkCompleteness(totalSketchedLandmarks, total_mm_landmarks)
    landmarkCompleteness = round(landmarkCompleteness, 2)
    # session['landmarkCompleteness'] = landmarkCompleteness

    streetCompleteness = get_streetCompleteness(totalSketchedStreets, toal_mm_streets)
    streetCompleteness = round(streetCompleteness, 2)

    overAllCompleteness = get_overall_completness(landmarkCompleteness, streetCompleteness)
    # session['overAllCompleteness'] = overAllCompleteness
    print("Landmarks :", total_mm_landmarks, "Streets:", toal_mm_streets)
    completeness_results = {"sketchMapID": sketchFileName, "total_mm_landmarks": total_mm_landmarks,
              "toal_mm_streets": toal_mm_streets,
              "totalSketchedLandmarks": totalSketchedLandmarks,
              "totalSketchedStreets": totalSketchedStreets,
              "landmarkCompleteness": landmarkCompleteness,
              "streetCompleteness": streetCompleteness,
              "overAllCompleteness": round(overAllCompleteness, 2)
              }

    # Weighted scores (supervisor's scheme). Skipped silently if the
    # shared helpers couldn't be imported — the legacy keys above still
    # populate the response so callers never break.
    if get_weights is not None:
        try:
            _ensure_route_flags(metricMap)
            weights = get_weights()
            lm_w, st_w, overall_w, lm_total, st_total = _weighted_completeness(
                metricMap, weights
            )
            completeness_results["landmarkWeightedCompleteness"] = round(lm_w, 2)
            completeness_results["streetWeightedCompleteness"]   = round(st_w, 2)
            completeness_results["overallWeightedCompleteness"]  = round(overall_w, 2)
            completeness_results["totalLandmarkWeight"] = lm_total
            completeness_results["totalStreetWeight"]   = st_total
        except Exception as exc:
            print("weighted completeness failed:", exc)

    # breakpoint()
    print(completeness_results)
    return HttpResponse(json.dumps(completeness_results), content_type="application/json")
