# bdr — Bi-Dimensional Regression Microservice

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Django](https://img.shields.io/badge/Django-microservice-green)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED)
![Port](https://img.shields.io/badge/bdr-:8006-orange)

A Django microservice implementing **Bi-Dimensional Regression (BDR)** for SketchMapia — a similarity-transform-based method for measuring how closely a sketch map's spatial configuration matches its reference base map.

This service was developed and integrated as part of the [BDR-Feature](https://github.com/CL-77/BDR-Feature) branch, which was subsequently merged into this repo alongside the existing [GMDA (Gardony Map Drawing Analyzer)](../README.md) feature. It reuses GMDA's 8-point MBR extraction and `SketchAlign`-based 1:1 alignment logic as the shared foundation for this second, independent accuracy metric.

## Background

Bi-Dimensional Regression is a statistical technique for comparing the configural similarity between two 2D point sets — commonly used in cognitive mapping research to assess how well a sketch map's spatial layout matches its corresponding reference/target map. It generalizes ordinary least-squares regression from one dimension to two, fitting a similarity transform (uniform scale, rotation, and translation) that best maps one configuration of points onto the other, then measures how much residual error remains after that transform.

## Key Features

- **Reuses GMDA's Alignment Pipeline**:
Uses the same 8 peripheral MBR points per feature and the same `SketchAlign`/`aligned` property-based matching as GMDA, so both metrics operate on a consistent, strictly 1:1 aligned feature set.
- **Similarity Transform Fitting**:
Estimates a single similarity transform (scale `phi`, rotation `theta`, translation `alpha1`/`alpha2`) that best maps base-map points onto sketch-map points using least-squares, via `skimage.transform.SimilarityTransform`.
- **Dual Feature Support**:
Provided as two independent calculators — one for landmark polygons/points, one for street-junction points — following the same Landmarks/Junctions split as GMDA.
- **Automatic Junction Detection**:
For the junctions calculator, junctions are detected directly from line-segment endpoints that coincide across two or more roads, then matched between base map and sketch map using a topological subset check on shared road IDs.

## What it does

Given two GeoJSON feature collections — a generalized base map and a processed sketch map — this service:

1. Filters both maps down to strictly 1:1 aligned features (via the `aligned` / `SketchAlign` properties).
2. Builds 8-point Minimum Bounding Rectangles (MBRs) for each aligned feature pair.
3. Fits a similarity transform mapping base-map MBR points ($X$) onto sketch-map MBR points ($Y$), using least-squares.
4. Returns the fitted transform parameters plus a goodness-of-fit / distortion score.

## Metrics Calculated

| Metric | Meaning |
| :--- | :--- |
| **r** | Bidimensional correlation — goodness-of-fit of the similarity transform (2D analogue of R²) |
| **DI** | Distortion Index — percentage-scale distortion score derived from `r` |
| **phi** | Fitted uniform scale factor |
| **theta** | Fitted rotation, in degrees |
| **alpha1, alpha2** | Fitted x/y translation offset |

Let $A_i, B_i$ be the sketch-map point coordinates, $\hat{A}_i, \hat{B}_i$ the transform's predicted points (from mapping base-map points through the fitted transform), and $\bar{A}, \bar{B}$ the means of the sketch-map coordinates.

1. **Bidimensional Correlation (r)**:
Measures how well the fitted transform explains the sketch-map point positions. Computed from the residual sum of squares between the transform's predicted points and the actual sketch-map points, relative to the total variance of the sketch-map points.

$$r = 1 - \frac{\sum (A_i - \hat{A}_i)^2 + (B_i - \hat{B}_i)^2}{\sum (A_i - \bar{A})^2 + (B_i - \bar{B})^2}$$

2. **Distortion Index (DI)**:
A percentage-scale measure of how much the sketch map's configuration deviates from a perfect similarity-transformed copy of the base map. Derived directly from `r`.

$$DI = 100\sqrt{1 - r^2}$$

3. **Scale Factor (phi)**:
The uniform scale factor of the fitted similarity transform — how much larger or smaller the sketch map's layout is relative to the base map.

4. **Rotation (theta)**:
The rotation angle (in degrees) of the fitted similarity transform, indicating systematic rotational skew between the sketch map and the base map.

5. **Translation (alpha1, alpha2)**:
The x/y translation offset of the fitted similarity transform.

## New Features Added

1. **BDR Calculator (Landmark Based)**:

Calculates the four BDR measures using polygon/point features (landmarks) from the generalized base map and sketch map.

**How it works?**
- After running **Analyse**, the generalized base map and processed sketchmap are available in the frontend.
- Checking **Calculate BDR for Landmarks** sends both maps as GeoJSON to this service via a **POST** request to **/bdr/calculateLandmarksBDR/**.
- The backend filters both maps down to strictly 1:1 aligned polygon/point features, builds 8-point MBRs for each, and fits a similarity transform mapping base-map MBR points onto sketch-map MBR points.
- The four metrics are computed from the fitted transform and returned as JSON.
- Results are written into the Landmarks BDR columns of the main results table.

2. **Junction Based BDR Calculator**:

Calculates the four BDR measures using street-junction points from both maps.

**How it works?**
- After running **Analyse**, checking **Calculate BDR for Junctions** sends both maps as GeoJSON to **/bdr/calculateJunctionsBDR/**.
- The backend detects junctions on both maps by finding line-segment endpoints shared by two or more roads.
- Junctions are matched between maps using a topological subset check: a sketch-map junction matches a base-map junction if all road IDs at the sketch junction are a subset of the road IDs at the base junction.
- MBR points for matched junction pairs are used to fit the similarity transform, and the four metrics are computed and returned.
- Results are written into the Junctions BDR columns of the main results table.

## Endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/bdr/calculateLandmarksBDR/` | **POST** | Landmark-based BDR |
| `/bdr/calculateJunctionsBDR/` | **POST** | Junction-based BDR |

### Request Format (Both Endpoints)

```text
POST /bdr/calculateLandmarksBDR/
Content-Type: application/x-www-form-urlencoded

basemapdata=[GeoJSON string]&sketchmapdata=[GeoJSON string]
```

### Response Format

```json
{
  "r": 0.9714,
  "DI": 23.7332,
  "phi": 0.8063,
  "theta": 26.6147,
  "alpha1": 243.0352,
  "alpha2": -69.226
}
```

## Running standalone

```bash
cd bdr
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8006
```

Or, as part of the full stack:

```bash
docker-compose up --build
```

The service is exposed on port `8006`.

## Project structure

```text
bdr/
├── Dockerfile
├── requirements.txt        # Django, numpy, geopandas, scikit-image, scikit-learn
├── manage.py
├── bdr/
│   ├── settings.py
│   ├── urls.py              # routes /bdr/ to microservice/urls.py
│   ├── wsgi.py
│   └── asgi.py
└── microservice/
    ├── urls.py               # maps endpoints to views
    └── views.py               # all BDR logic lives here
```

## Related

- [GMDA-Feature (this repo)](../README.md) — full integration docs, including how BDR results are surfaced in the main results table.
- [BDR-Feature](https://github.com/CL-77/BDR-Feature) — the original feature branch this service was developed on.

## Contributors

A massive thank you to everyone who helped build the BDR Calculator!

- Ajay [ajay-sheokand](https://github.com/ajay-sheokand)
- Clement Amirault [CL-77](https://github.com/CL-77)
