# validation — SKETCHMAPIA Validation Microservice

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Django](https://img.shields.io/badge/Django-microservice-green)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED)
![Port](https://img.shields.io/badge/validation-:8004-orange)

A Django microservice that **cleans up hand-drawn and imported map geometry** before analysis — snapping near-miss endpoints, merging pass-through segments, and correcting route ordering.


## Background

Hand-drawn streets almost never meet exactly. Two lines that a human reads as "crossing" may be 3 pixels apart; a single street may be drawn as four separate strokes. Every downstream service — junction detection in [`gmda`](../gmda/README.md), street topology in [`accuracy`](../accuracy/README.md), street counts in [`completeness`](../completeness/README.md) — depends on topology being right. Feed them raw strokes and the junction count is wrong before any metric is computed.

This service fixes that, and does so **with the researcher in the loop**: it never silently rewrites data.

## The preview / apply model

Validation runs in two phases, controlled by the `action` parameter:

| Phase | `action` | Behaviour |
| :--- | :--- | :--- |
| **Preview** | `preview` (default) | Detect proposed snaps and merges, return them as an **audit** object. Nothing is modified. |
| **Apply** | `apply` | Take the subset of proposals the user approved, apply only those, return the corrected map. |

This is the key design decision of the service: automatic geometry cleanup is a research-integrity risk, so the proposals are surfaced in the UI and committed only on explicit approval.

## What it does

### 1. Endpoint snapping

`snap_line_endpoints(lines_gdf, bounds=[[0,0],[600,850]])` finds line endpoints that fall within tolerance of each other and snaps them together. `find_snapped_groups()` then reports which original line IDs were affected, so each proposed snap can be approved individually.

### 2. Simple intersection merging

`merge_simple_intersections(linegdf)` builds a node set from all line endpoints, uses a spatial index (`sindex`) to find which lines touch each node, and keeps only nodes with exactly **two** incident lines — a pass-through point, not a real junction. A NetworkX graph then groups the segments joined by those nodes, and `merge_lines_ordered()` stitches each group into a single `LineString`, walking coordinates end-to-end and reversing segments where needed.

### 3. Route correction

`validateRoute(line_gdf, route_ids)` re-checks the participant's route against the merged geometry. `get_max_route_order()` resolves the `sketchrouteorder` property across merged segments, and `remap_alignment_ids()` / `convert_mapping_to_sketch_ids()` keep alignment IDs consistent after merges change the ID space.

### 4. Reassembly

Corrected line features are recombined with the untouched polygon and point features into a single `FeatureCollection`.

## Endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/validation/validate/` | **POST** | Preview or apply geometry validation |

### Request format — preview

```text
POST /validation/validate/
Content-Type: application/x-www-form-urlencoded

type=metric&action=preview&metricdata=[GeoJSON string]&route=[JSON array of ids]
```

`type` is either `metric` or `sketch`.

### Response — preview

```json
{
  "audit": {
    "snap": [[3, 7], [11, 12]],
    "merge": [
      { "merged_from": [4, 5, 6], "merged_into": 4 }
    ]
  }
}
```

### Request format — apply

```text
POST /validation/validate/
Content-Type: application/x-www-form-urlencoded

type=metric&action=apply&metricdata=[GeoJSON string]&route=[JSON array]
&snap=[JSON array of approved snap pairs]&merge=[JSON array of approved merge groups]
```

Only the snap pairs and merge groups passed back in `snap` / `merge` are applied — approving nothing is a valid, no-op run.

### Response — apply

```json
{
  "modifiedStreets": {
    "type": "FeatureCollection",
    "features": [ "..." ]
  }
}
```

## Key functions

| Function | Role |
| :--- | :--- |
| `snap_line_endpoints` | Snap near-coincident endpoints within bounds |
| `find_snapped_groups` | Report which line IDs a snap affected |
| `endpoint_intersection_pairs` | Find endpoint-level intersections between lines |
| `merge_simple_intersections` | Detect and merge pass-through (degree-2) nodes |
| `merge_lines_ordered` | Stitch a group of segments into one ordered `LineString` |
| `apply_approved_snaps` | Commit only the user-approved snaps |
| `apply_approved_merges` | Commit only the user-approved merges |
| `validateRoute` | Re-derive route ordering after merges |
| `get_max_route_order` | Resolve `sketchrouteorder` across merged segments |
| `combine_by_alignment` / `remap_alignment_ids` / `convert_mapping_to_sketch_ids` | Keep alignment IDs valid after the ID space changes |
| `to_builtin_types` | Convert numpy/geopandas types to JSON-serializable Python types |

`to_builtin_types` is not cosmetic — numpy integer IDs from geopandas are not JSON-serializable, so audit payloads must pass through it.

## Running standalone

```bash
cd validation
pip install -r requirements.txt
python manage.py makemigrations && python manage.py migrate
python manage.py runserver 0.0.0.0:8004
```

Or, as part of the full stack:

```bash
docker-compose up --build
```

The service is exposed on port `8004`.

> `requirements.txt` for this service is UTF-16 encoded. If `pip install -r` fails with an encoding error, convert it first: `iconv -f UTF-16 -t UTF-8 requirements.txt -o requirements.utf8.txt`.

## Deployment note

In `docker-compose.yml` (local) the service is named `validation`; in `docker-compose.server.yml` (production) the container is named `sketchmap_validation` while still pulling `ghcr.io/ifgi-sil/validation:latest`. The URL prefix is `/validation/` in both.

## Project structure

```text
validation/
├── Dockerfile                  # runs on port 8004
├── requirements.txt            # Django, shapely, geopandas, networkx, numpy, pandas
├── manage.py
├── validation/
│   ├── settings.py
│   ├── urls.py                 # routes /validation/ to microservice/urls.py
│   ├── wsgi.py
│   └── asgi.py
└── microservice/
    ├── urls.py                 # maps validate/ to the view
    └── views.py                # snapping, merging, route correction
```

## Related

- [Main README](../README.md) — architecture, quick start, deployment.
- [`generalizations/README.md`](../generalizations/README.md) — the next step in the chain.
- [`gmda/README.md`](../gmda/README.md) — junction detection, which depends on clean topology.