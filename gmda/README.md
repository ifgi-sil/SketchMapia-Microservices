# gmda — a SKETCHMAPIA Microservice
# Gardony Map Drawing Analyzer
![Python](https://img.shields.io/badge/Python-3.x-blue)
![Django](https://img.shields.io/badge/Django-microservice-green)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED)
![Port](https://img.shields.io/badge/gmda-:8005-orange)

A Django microservice implementing the **Gardony Map Drawing Analyzer (GMDA)** for SketchMapia — six quantitative measures of how accurately a sketch map reproduces the spatial configuration of its reference base map.

Based on [Gardony, Taylor & Brunyé (2016)](https://link.springer.com/article/10.3758/s13428-014-0556-x), *Gardony Map Drawing Analyzer: Software for quantitative analysis of sketch maps*, Behavior Research Methods 48, 151–177.

The companion service [`bdr`](../bdr/README.md) reuses this service's MBR extraction and alignment approach for a second, independent accuracy method.

## Background

GMDA compares a drawn (sketch) configuration against a target (base map) configuration by looking at every **pair of points** in each map and asking how the sketched relationship between the pair differs from the true one — in terms of canonical direction (N/S/E/W), normalized distance, and angle. Aggregating those pairwise errors yields six scores that separate *what was recalled* from *how accurately it was laid out*.

This service implements the paper's **Advanced Mode**: instead of collapsing each feature to a single centroid, every feature is represented by **8 peripheral points** along its Minimum Bounding Rectangle, so both position and spatial extent/orientation contribute to the metrics.

## Key features

- **8-point MBR representation (Advanced Mode)** — each polygon/point feature becomes 8 points on its minimum bounding rectangle; point markers get a 1-pixel buffer first (`compute_mbr_points`).
- **Alignment-driven matching** — feature pairs are resolved from the `SketchAlign` property rather than naive ID equality, and normalized through `_normalize_align_value` (which flattens strings, lists, nested lists, and strips `s` prefixes).
- **Strict 1:1 filtering** — a Union-Find structure groups aligned features and classifies them into 1:1, Many:1 and Many:Many; only strict 1:1 pairs feed the metrics.
- **Same-landmark pair exclusion** — point pairs drawn from the *same* landmark's 8 MBR points are excluded from the combinatorics.
- **Two calculators** — Landmark-based (polygons/points) and Junction-based (street junctions), exposed as separate endpoints.
- **Junction layer export** — the junction endpoint also returns the detected junctions as GeoJSON (`basemapJunctions`, `sketchmapJunctions`) so the frontend can draw them as layers.

## What it does

Given two GeoJSON feature collections — a generalized base map and a processed sketch map — the service:

1. Filters both maps to strictly 1:1 aligned features (landmarks) or detects and matches junctions (junctions).
2. Builds 8-point MBRs for each feature in each matched pair.
3. Generates all valid cross-feature point pairs on both maps.
4. Computes the six metrics from the paired distance ratios and angular differences.
5. Returns the metrics plus `nTL` / `nDL` as JSON.

## Metrics calculated

| Metric | Measures | Penalizes omissions? |
| :--- | :--- | :---: |
| **CanOrg** | Canonical organization — overall N/S/E/W topological accuracy | ✅ |
| **CanAcc** | Canonical accuracy — layout accuracy of drawn landmarks only | ❌ |
| **DistAcc** | Distance accuracy — normalized pairwise distance error | ❌ |
| **ScaBias** | Scaling bias — systematic expansion (+) or compression (−) | ❌ |
| **AngAcc** | Angular accuracy — normalized pairwise angular error | ❌ |
| **RotBias** | Rotational bias — systematic clockwise (+) / counterclockwise (−) rotation | ❌ |

`nTL` = number of target (base map) landmarks/junctions; `nDL` = number of drawn (sketch map) landmarks/junctions.

### Combinatorics (Advanced Mode)

With 8 peripheral points per landmark, comparisons between points of the *same* landmark are excluded. For $n_{TL}$ target landmarks and $n_{DL}$ drawn landmarks:

$$N_{TL} = \binom{8n_{TL}}{2} - n_{TL}\binom{8}{2} \qquad N_{DL} = \binom{8n_{DL}}{2} - n_{DL}\binom{8}{2}$$

### Formulas

**Canonical Organization** — uses all target pairs as denominator, so omitted landmarks lower the score:

$$CanOrg = \frac{\sum_{i=1}^{N_{TL}} \text{CanonicalScore}_i}{2N_{TL}}$$

**Canonical Accuracy** — denominator switches to drawn pairs, isolating layout accuracy from recall:

$$CanAcc = \frac{\sum_{i=1}^{N_{DL}} \text{CanonicalScore}_i}{2N_{DL}}$$

**Distance Accuracy** — with $dr_{SM}, dr_{TE}$ the scale-equalized distance ratios of sketch map and target environment:

$$DistAcc = 1 - \frac{\sum_{i=1}^{N_{DL}} |dr_{SM, i} - dr_{TE, i}|}{N_{DL}}$$

**Scaling Bias** — signed version of the same comparison:

$$ScaBias = \frac{\sum_{i=1}^{N_{DL}} (dr_{SM, i} - dr_{TE, i})}{N_{DL}}$$

**Angular Accuracy** — absolute angular deviations scaled against the maximum error of $180^\circ$:

$$AngAcc = 1 - \frac{\sum_{i=1}^{N_{DL}} \left| \frac{180}{\pi} ang_{Diff, i} \right|}{180 \cdot N_{DL}}$$

**Rotational Bias** — circular mean via trigonometric summation (`np.arctan2`), handling the $0^\circ \equiv 360^\circ$ wrap-around:

$$RotBias = \frac{180}{\pi} \text{atan2}\left( \frac{\sum_{i=1}^{N_{DL}} \sin(ang_{Diff, i})}{N_{DL}}, \frac{\sum_{i=1}^{N_{DL}} \cos(ang_{Diff, i})}{N_{DL}} \right)$$

## The two calculators

### 1. Landmark-based GMDA

Uses polygon and point features (e.g. buildings) from both maps.

**How it works**

- After running **Analyse**, the generalized base map and processed sketch map are available in the frontend.
- Checking **Buildings GMDA** in the Analyse modal sends both maps as GeoJSON via **POST** to `/gmda/calculateGMDA/`.
- The backend extracts polygon features from both maps, builds 8-point MBRs, resolves alignment through the `SketchAlign` property, and classifies pairs into 1:1 / Many:1 / Many:Many using Union-Find.
- The six metrics are computed over all valid landmark pairs and returned as JSON.
- Results are written into the **Buildings GMDA** columns of the main results table.

### 2. Junction-based GMDA

Uses street junctions detected from road-segment endpoints.

**How it works**

- Checking **Junctions GMDA** sends both maps to `/gmda/calculateJunctionGMDA/` after the base analysis completes.
- The backend detects junctions by finding road endpoints that share the same coordinate (rounded to 3 decimal places) across two or more line segments (`find_juncs_from_geojson`).
- For the base map, all junctions count toward `nTL`; for the sketch map, only junctions formed by road IDs shared with the base map are used.
- Junctions are matched with a **topological subset check**: a sketch junction matches a base junction if all road IDs at the sketch junction are a subset of the road IDs at the base junction.
- Matched pairs are classified with the same Union-Find grouping as landmarks; results go into the **Junctions GMDA** columns.

<p align="center">
  <img src="../docs/images/junction_matching.png" alt="Junction Matching Logic" width="650"/>
</p>

## Endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/gmda/calculateGMDA/` | **POST** | Landmark-based GMDA |
| `/gmda/calculateJunctionGMDA/` | **POST** | Junction-based GMDA |

Both views are `@csrf_exempt` and return `405` for non-POST requests, `500` with an `error` key (and a traceback for the junction endpoint) on failure.

### Request format (both endpoints)

```text
POST /gmda/calculateGMDA/
Content-Type: application/x-www-form-urlencoded

basemapdata=[GeoJSON string]&sketchmapdata=[GeoJSON string]
```

### Response format

```json
{
  "CanOrg": 0.0962,
  "CanAcc": 0.8917,
  "ScaBias": -0.0001,
  "DistAcc": 0.9358,
  "RotBias": -30.2334,
  "AngAcc": 0.7942,
  "nTL": 14,
  "nDL": 5
}
```

The junction endpoint additionally returns `basemapJunctions` and `sketchmapJunctions` as GeoJSON feature collections.

## Running standalone

```bash
cd gmda
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8005
```

Or, as part of the full stack:

```bash
docker-compose up --build
```

The service is exposed on port `8005`.

## Project structure

```text
gmda/
├── Dockerfile                  # runs on port 8005
├── requirements.txt            # Django, numpy, shapely
├── manage.py
├── test_check.py
├── gmda/
│   ├── settings.py
│   ├── urls.py                 # routes /gmda/ to microservice/urls.py
│   ├── wsgi.py
│   └── asgi.py
└── microservice/
    ├── urls.py                 # maps endpoints to views
    └── views.py                # all GMDA logic lives here
```

Key functions in `microservice/views.py`:

| Function | Role |
| :--- | :--- |
| `_normalize_align_value` | Flattens `SketchAlign` values (string / list / nested) into a clean list of sketch IDs |
| `compute_mbr_points` | Builds the 8 peripheral MBR points for a Polygon/MultiPolygon/Point |
| `landmark_pairs_generator` | Generates all valid cross-landmark point pairs |
| `compute_gmda` | Full landmark pipeline → six metrics |
| `find_juncs_from_geojson` | Detects junctions from coincident road endpoints |
| `compute_JunctionGMDA` | Full junction pipeline → six metrics + junction layers |
| `calculateGMDA` / `calculateJunctionGMDA` | Django views wrapping the two pipelines |

## Related

- [Main README](../README.md) — architecture, quick start, deployment.
- [`docs/gmda-integration-notes.md`](../docs/gmda-integration-notes.md) — integration change log: which frontend files changed and why.
- [`bdr/README.md`](../bdr/README.md) — the BDR service, which reuses this pipeline.

## Contributors

- Ajay — [@ajay-sheokand](https://github.com/ajay-sheokand)
- Clement Amirault — [@CL-77](https://github.com/CL-77)