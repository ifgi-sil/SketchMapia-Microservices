# completeness — a SKETCHMAPIA Microservice

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Django](https://img.shields.io/badge/Django-microservice-green)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED)
![Port](https://img.shields.io/badge/completeness-:8002-orange)

A Django microservice that measures **how much of the reference environment a participant recalled** — the recall side of sketch map analysis, as opposed to the accuracy services ([`gmda`](../gmda/README.md), [`bdr`](../bdr/README.md), [`accuracy`](../accuracy/README.md)).

Completeness is always included in an analysis run: in the **Analyse** modal it is locked on, and the other metrics are opt-in.

## Background

Before asking *how accurately* someone drew a place, it is worth asking *what they drew at all*. Completeness answers that: of all landmarks and streets present in the base map, what fraction appears in the sketch map? It is deliberately simple — a straight count-based ratio — and it is what the accuracy metrics deliberately factor out (e.g. GMDA's `CanAcc` measures layout accuracy of drawn features only, precisely because recall is measured here).

## What it does

Given two GeoJSON feature collections — the metric (base) map and the sketch map — this service:

1. Counts landmarks in each map (features whose `properties.feat_type` is `"Landmark"`).
2. Counts streets in each map (features whose `geometry.type` is `"LineString"`).
3. Divides sketch counts by base-map counts to produce per-category percentages.
4. Averages landmark and street completeness into an overall score.

## Metrics calculated

| Field | Meaning |
| :--- | :--- |
| `sketchMapID` | Filename of the analysed sketch map |
| `total_mm_landmarks` | Landmarks present in the metric (base) map |
| `toal_mm_streets` | Street segments present in the metric map *(note: name kept as-is for API compatibility)* |
| `totalSketchedLandmarks` | Landmarks drawn in the sketch map |
| `totalSketchedStreets` | Street segments drawn in the sketch map |
| `landmarkCompleteness` | `totalSketchedLandmarks / total_mm_landmarks × 100`, rounded to 2 dp |
| `streetCompleteness` | `totalSketchedStreets / toal_mm_streets × 100`, rounded to 2 dp |
| `overAllCompleteness` | Mean of `landmarkCompleteness` and `streetCompleteness`, rounded to 2 dp |

$$\text{LandmarkCompleteness} = \frac{n_{\text{sketched landmarks}}}{n_{\text{base landmarks}}} \times 100 \qquad
\text{StreetCompleteness} = \frac{n_{\text{sketched streets}}}{n_{\text{base streets}}} \times 100$$

$$\text{OverallCompleteness} = \frac{\text{LandmarkCompleteness} + \text{StreetCompleteness}}{2}$$

City-block completeness (`get_cityblockCompleteness`) exists in the code but is currently not wired into the response.

## How it works in the app

- The user clicks **Analyse** in the sketch map editor.
- Completeness is checked and locked; `runAnalysis()` sends the sketch map and metric map as GeoJSON via **POST** to `/completeness/analyzeCompleteness/`, together with both filenames.
- The response is written into the completeness columns of the main results table.
- On **Download Results**, the values also land in `ResultSummary.csv` and `CompletenessDetailedOutput.csv`.

## Endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/completeness/analyzeCompleteness/` | **POST** | Landmark, street and overall completeness |

### Request format

```text
POST /completeness/analyzeCompleteness/
Content-Type: application/x-www-form-urlencoded

sketchFileName=[string]&metricFileName=[string]&sketchdata=[GeoJSON string]&metricdata=[GeoJSON string]
```

### Response format

```json
{
  "sketchMapID": "Sketch_1.png",
  "total_mm_landmarks": 14,
  "toal_mm_streets": 22,
  "totalSketchedLandmarks": 5,
  "totalSketchedStreets": 9,
  "landmarkCompleteness": 35.71,
  "streetCompleteness": 40.91,
  "overAllCompleteness": 38.31
}
```

## Input expectations

- Landmarks are identified by `properties.feat_type == "Landmark"` — features missing `feat_type` will raise a `KeyError`.
- Streets are identified purely by geometry type (`LineString`).
- Both payloads must be JSON-encoded GeoJSON strings.

## Running standalone

```bash
cd completeness
pip install -r requirements.txt
python manage.py makemigrations && python manage.py migrate
python manage.py runserver 0.0.0.0:8002
```

Or, as part of the full stack:

```bash
docker-compose up --build
```

The service is exposed on port `8002`.

## Project structure

```text
completeness/
├── Dockerfile                  # runs on port 8002
├── requirements.txt
├── manage.py
├── completeness/
│   ├── settings.py
│   ├── urls.py                 # routes /completeness/ to microservice/urls.py
│   ├── wsgi.py
│   └── asgi.py
└── microservice/
    ├── urls.py                 # maps analyzeCompleteness/ to the view
    └── views.py                # counting + ratio logic
```

## Related

- [Main README](../README.md) — architecture, quick start, deployment.
- [`accuracy/README.md`](../accuracy/README.md) — qualitative spatial relations accuracy.
- [`gmda/README.md`](../gmda/README.md) · [`bdr/README.md`](../bdr/README.md) — quantitative accuracy metrics.