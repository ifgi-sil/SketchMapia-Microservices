# accuracy — a SKETCHMAPIA Microservice
# Qualitative Spatial Relations

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Django](https://img.shields.io/badge/Django-microservice-green)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED)
![Port](https://img.shields.io/badge/qualitativerelations-:8003-orange)

A Django microservice that measures sketch map accuracy **qualitatively** — by comparing the *spatial relations* between features rather than their metric coordinates.

> **Naming note:** the folder is `accuracy/`, the Docker Compose service is `qualitativerelations`, and the URL prefix is `/accuracy/`. All three refer to this service.

## Background

A sketch map is rarely metrically correct — but it can still be *qualitatively* correct: the church is still inside the square, the shop is still on the left of the road, the streets still cross in the same order. This service formalizes that intuition. It converts each map into a **Qualitative Constraint Network (QCN)** — a set of relations between feature pairs — and then compares the sketch map's QCN against the base map's QCN, relation by relation.

This is the SketchMapia approach described in Schwering et al. (2014), *SketchMapia: Qualitative Representations for the Alignment of Sketch and Metric Maps*.

## Qualitative calculi used

Both maps are qualified with the same set of qualifiers (`qualifier/qualifier_collection.py`):

| Calculus | Module | Captures |
| :--- | :--- | :--- |
| **RCC8 / RCC11** | `qualify_RCC8.py`, `qualify_RCC11.py` | Region connection — containment, overlap, disjointness between regions |
| **DE-9IM (line/polygon)** | `qualify_DE9IM_linepolygon.py` | Topological relations between streets and regions |
| **Left–Right** | `qualify_LeftRight.py` | Which side of a street a landmark lies on |
| **OPRA** | `qualify_OPRA.py` | Oriented point relative directions between streets |
| **Street topology** | `qualify_street_topology.py` | Connectivity between street segments (DE-9IM based) |
| **Linear ordering** | `qualify_linearOrdering.py` | Order of landmarks/streets along a defined route |

Additional qualifiers exist in the folder but are currently commented out of the active list: `qualify_RegionStarVars.py` (star-vars relative directions), `qualify_relativeDist.py` (relative distance), `qualify_Adjacency.py` (street–landmark adjacency).

## What it does

For each calculus, the service computes five counts and one score:

- **total (mm)** — relations present in the metric (base) map
- **total (sm)** — relations present in the sketch map
- **matched** — sketch relations that agree with the base map
- **wrong matched** — sketch relations that contradict the base map
- **missing** — `total(mm) − (matched + wrong matched)`
- **correctness accuracy** — `matched / total(sm) × 100`

It then aggregates across all calculi:

$$\text{precision} = \frac{\sum \text{matched}}{\sum \text{total}_{sm}} \qquad
\text{recall} = \frac{\sum \text{matched}}{\sum \text{total}_{mm}}$$

*(`f_score` is present in the response but currently returned as `"nil"`.)*

## How it works in the app

- In the **Analyse** modal, checking **Accuracy** sends both maps as GeoJSON via **POST** to `/accuracy/analyzeQualitative/`.
- The backend qualifies each map independently via `qualify_map.main_loader(fileName, geojson, "geojson", map_type)`, producing a QCN per map.
- The two QCNs are compared per calculus by `microservice/qualitativeAnalyser.py`.
- The response carries both the scores and the raw QCNs (`smqcn`, `mmqcn`), which the frontend exports into `QADetailedOutput.csv` and the per-map files under the `QualitativeRelations/` folder of the results zip.

## Endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/accuracy/analyzeQualitative/` | **POST** | Full qualitative comparison of sketch vs. metric map |
| `/accuracy/mmReceiver/` | **POST** | Qualify a metric map only; writes the QCN to `QualitativeRelationsOutput/` |
| `/accuracy/smReceiver/` | **POST** | Qualify a sketch map only; writes the QCN to `QualitativeRelationsOutput/` |
| `/accuracy/clearFiles/` | **POST** | Delete everything under `QualitativeRelationsOutput/` |

### Request format (`analyzeQualitative`)

```text
POST /accuracy/analyzeQualitative/
Content-Type: application/x-www-form-urlencoded

sketchFileName=[string]&metricFileName=[string]&sketchdata=[GeoJSON string]&metricdata=[GeoJSON string]
```

### Response format (abridged)

```json
{
  "qualitative_results": {
    "sketchMapID": "Sketch_1.png",
    "totalRCC11Relations_mm": 91,
    "totalRCC11Relations": 10,
    "correctRCC11Relations": 8,
    "wrongMatchedRCC11rels": 2,
    "missingRCC11rels": 81,
    "correctnessAccuracy_rcc11": 80.0,
    "total_LO_rels_sm": 12,
    "matched_LO_rels": 9,
    "correctnessAccuracy_LO": 75.0,
    "correctnessAccuracy_LR": 66.67,
    "correctnessAccuracy_DE9IM": 71.43,
    "correctnessAccuracy_streetTop": 84.21,
    "correctnessAccuracy_opra": 58.33,
    "precision": 0.73,
    "recall": 0.19,
    "f_score": "nil"
  },
  "smqcn": { "...": "sketch map QCN" },
  "mmqcn": { "...": "metric map QCN" }
}
```

Every calculus contributes the same five-count block (`total_*_mm`, `total_*_sm`, `matched_*`, `wrong_matched_*`, `missing_*`, `correctnessAccuracy_*`) — the example above is trimmed for readability.

## Side effects on disk

`mmReceiver` and `smReceiver` write one JSON file per map into the repo-level `QualitativeRelationsOutput/` directory (named after the uploaded file). `clearFiles` empties that directory. `analyzeQualitative` does *not* write to disk — it qualifies in memory and returns the QCNs in the response.

## Running standalone

```bash
cd accuracy
pip install -r requirements.txt
python manage.py makemigrations && python manage.py migrate
python manage.py runserver 0.0.0.0:8003
```

Or, as part of the full stack:

```bash
docker-compose up --build
```

The service is exposed on port `8003`.

> `requirements.txt` for this service is UTF-16 encoded. If `pip install -r` fails with an encoding error, convert it first: `iconv -f UTF-16 -t UTF-8 requirements.txt -o requirements.utf8.txt`.

## Project structure

```text
accuracy/
├── Dockerfile                       # runs on port 8003
├── requirements.txt                 # Django, shapely, geopandas, networkx, ...
├── manage.py
├── accuracy/
│   ├── settings.py
│   ├── urls.py                      # routes /accuracy/ to microservice/urls.py
│   ├── wsgi.py
│   └── asgi.py
├── microservice/
│   ├── urls.py                      # maps the four endpoints to views
│   ├── views.py                     # request handling + score aggregation
│   ├── qualitativeAnalyser.py       # per-calculus matching/counting logic
│   └── inverses.py                  # relation inverse lookup tables
└── qualifier/                       # the qualitative calculi themselves
    ├── qualify_map.py               # main_loader() — entry point, builds a QCN
    ├── qualifier_collection.py      # which qualifiers are active
    ├── qualifier_interface.py
    ├── geojsonLoader.py / svgLoader.py
    ├── qualify_RCC8.py / qualify_RCC11.py
    ├── qualify_DE9IM_linepolygon.py
    ├── qualify_LeftRight.py
    ├── qualify_OPRA.py
    ├── qualify_street_topology.py
    ├── qualify_linearOrdering.py
    ├── qualify_RegionStarVars.py    # inactive
    ├── qualify_relativeDist.py      # inactive
    └── qualify_Adjacency.py         # inactive
```

To activate or deactivate a calculus, edit the append list in `qualifier/qualifier_collection.py`.

## References

- Schwering, A.; Wang, J.; Chipofya, M.; Jan, S.; Li, R.; Broelemann, K. (2014). *SketchMapia: Qualitative Representations for the Alignment of Sketch and Metric Maps.* Spatial Cognition & Computation. [Link](https://www.tandfonline.com/doi/full/10.1080/13875868.2014.917378)

## Related

- [Main README](../README.md) — architecture, quick start, deployment.
- [`completeness/README.md`](../completeness/README.md) — recall-side analysis.
- [`gmda/README.md`](../gmda/README.md) · [`bdr/README.md`](../bdr/README.md) — quantitative accuracy metrics.