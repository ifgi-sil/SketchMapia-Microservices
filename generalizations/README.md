# generalizations — SKETCHMAPIA Generalization Microservice

![Python](https://img.shields.io/badge/Python-3.8.20-blue)
![Django](https://img.shields.io/badge/Django-microservice-green)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED)
![Port](https://img.shields.io/badge/generalizations-:8001-orange)

A Django microservice that applies the **generalizations a participant made** back onto the base map, producing the *generalized base map* that the accuracy service downstream compares against.

This is the first service in the analysis chain: without it, comparing a sketch map against a raw OSM base map would penalize the participant for abstractions that are cognitively correct.

## Background

People do not draw what is there — they draw a simplified version of it. Three buildings become one block; a curved street becomes straight; a roundabout becomes a crossing. Manivannan, Krukar & Schwering (2022, 2024) classify these transformations systematically and show they can be detected from sketch map alignment.

This service takes that classification and *applies* it: given the base map, the sketch map, and an alignment describing which base features the participant merged, omitted, or abstracted, it rebuilds the base map at the participant's level of generalization. The result is a fair reference — the accuracy services then measure only genuine spatial error, not abstraction.

## What it does

Given three payloads — base map, sketch map, and alignment — the service:

1. Persists all three inputs to `generalizedMap/` (`inputbaseMap.json`, `inputsketchMap.json`, `alignment.json`).
2. Walks the alignment, sorting base features by generalization type (`genType`): amalgamation, collapse, omission, area-to-line, etc.
3. Applies the corresponding geometric transformation with Shapely (`unary_union`, `polygonize`, `concave_hull`, `snap`, `substring`, …).
4. Assigns each generalization group a **deterministic `gen_id`** via `make_gen_id(base_align)` — the same set of base IDs always yields the same ID (`g.12.17.23`), regardless of order or participant.
5. Stamps `gen_id` onto sketch-side features through their `sid`, so both maps carry a shared grouping key.
6. Writes `generalizedMap/generalizedoutputMap.json` and returns the combined feature collection as the response body.

## Key concepts

| Concept | Meaning |
| :--- | :--- |
| **`genType`** | The generalization class recorded in the alignment for a group of base features |
| **`SketchAlign`** | Property on base features listing the sketch IDs they align to |
| **`sid`** | Sketch-side feature ID, used in pass 2 to propagate `gen_id` |
| **`gen_id`** | Deterministic group ID (`g.<sorted base ids joined by dots>`) shared by base- and sketch-side members of one generalization group |
| **`groupID` / `group`** | Frontend-facing flags used for hover/highlight of generalized groups |

`gen_id` determinism matters: it is what makes the generalized output stable across runs and comparable across participants.

## How it works in the app

- The user aligns sketch features to base features in the editor, then clicks **Analyse**.
- The frontend **POST**s the base map, sketch map, alignment and sketch map name to `/generalizations/requestFME/`.
- The returned generalized base map is cached per sketch map (`allGenBaseMap[sketchMaptitle]`) and reused by every subsequent metric — **completeness, accuracy, GMDA, BDR** .
- Generalization details are exported to `GeneralizationDetailedOutput.csv` in the results zip.

The view is decorated with `@ensure_csrf_cookie`.

> **Historical note:** the endpoint name `requestFME` dates from an earlier implementation that delegated to Safe Software's FME. The processing is now pure Python/Shapely; the name is kept for API compatibility.

## Endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/generalizations/requestFME/` | **POST** | Apply the alignment's generalizations to the base map |

### Request format

```text
POST /generalizations/requestFME/
Content-Type: application/x-www-form-urlencoded

basedata=[GeoJSON string]&sketchdata=[GeoJSON string]&aligndata=[JSON string]&sketchmapName=[string]
```

### Response format

A GeoJSON `FeatureCollection` combining generalized base features and sketch features, each carrying `gen_id` where applicable:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": { "id": 12, "SketchAlign": [3], "gen_id": "g.12" },
      "geometry": { "type": "Polygon", "coordinates": [ ["..."] ] }
    }
  ]
}
```

## Side effects on disk

All I/O happens in the service-local `generalizedMap/` directory:

| File | Contents |
| :--- | :--- |
| `inputbaseMap.json` | Last base map received |
| `inputsketchMap.json` | Last sketch map received |
| `alignment.json` | Last alignment received |
| `generalizedoutputMap.json` | Last generalized output produced |

These are overwritten on every request — they exist for debugging, not as a store. Because the container is single-writer and stateless otherwise, concurrent requests to this service will clobber each other's temp files.

## Running standalone

```bash
cd generalizations
pip install -r requirements.txt
python manage.py makemigrations && python manage.py migrate
python manage.py runserver 0.0.0.0:8001
```

Or, as part of the full stack:

```bash
docker-compose up --build
```

The service is exposed on port `8001`.

> `requirements.txt` for this service is UTF-16 encoded. If `pip install -r` fails with an encoding error, convert it first: `iconv -f UTF-16 -t UTF-8 requirements.txt -o requirements.utf8.txt`.

## Project structure

```text
generalizations/
├── Dockerfile                  # runs on port 8001
├── requirements.txt            # Django, shapely, geopandas, geojson, pandas, ...
├── manage.py
├── generalizedMap/             # scratch dir for inputs + generalized output
├── generalizations/
│   ├── settings.py             # CORS config
│   ├── urls.py                 # routes /generalizations/ to microservice/urls.py
│   ├── wsgi.py
│   └── asgi.py
└── microservice/
    ├── urls.py                 # maps requestFME/ to the view
    └── views.py                # make_gen_id(), requestFME(), spatial_transformation()
```

## References

- Manivannan, C.; Krukar, J.; Schwering, A. (2024). *An algorithmic approach to detect generalization in sketch maps from sketch map alignment.* [doi:10.1371/journal.pone.0304696](https://doi.org/10.1371/journal.pone.0304696)
- Manivannan, C.; Krukar, J.; Schwering, A. (2022). *Spatial generalization in sketch maps: A systematic classification.* Journal of Environmental Psychology. [doi:10.1016/j.jenvp.2022.101851](https://doi.org/10.1016/j.jenvp.2022.101851)

## Related

- [Main README](../README.md) — architecture, quick start, deployment.
- [`validation/README.md`](../validation/README.md) — geometry cleanup that runs before generalization.