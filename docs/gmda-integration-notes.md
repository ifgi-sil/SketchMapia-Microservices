# GMDA Feature — Integration Notes

Implementation notes preserved from the GMDA feature integration (PR #11).
For the method itself and metric formulas, see the main [README](../README.md).

## How the two calculators work

### Landmark-based GMDA

- In the **Analyse** modal, checking "Buildings GMDA" (alongside Completeness, and optionally Accuracy) triggers `runAnalysis()`, which runs the base analysis first, then sends both maps as GeoJSON via **POST** to `/gmda/calculateGMDA/`.
- The backend extracts all polygon features from both maps, builds 8-point MBRs for each, resolves alignment using the **SketchAlign** property, and classifies pairs into 1:1, Many:1, and Many:Many groups using Union-Find.
- The six metrics are computed over all valid landmark pairs and returned as JSON, then written into the **Buildings GMDA** columns of the results table.

### Junction-based GMDA

- Checking "Junctions GMDA" sends both maps to `/gmda/calculateJunctionGMDA/` after the base analysis completes.
- The backend detects junctions by finding road endpoints that share the same coordinate (rounded to 3 decimal places) across two or more line segments.
- For the basemap, all junctions count toward **nTL**; for the sketchmap, only junctions formed by road IDs shared with the base map are used.
- Junctions are matched between maps using a **topological subset check**: a sketch junction matches a base junction if all road IDs at the sketch junction are a subset of the road IDs at the base junction.
- Matched pairs are classified with the same Union-Find grouping as landmarks; results go into the **Junctions GMDA** columns.

## Service layout

```text
gmda/
├── Dockerfile                  # runs on port 8005
├── requirements.txt            # Django, numpy, shapely
├── manage.py
├── gmda/
│   ├── settings.py
│   ├── urls.py                 # routes /gmda/ to microservice/urls.py
│   ├── wsgi.py
│   └── asgi.py
└── microservice/
    ├── urls.py                 # maps endpoints to views
    └── views.py                # all GMDA logic lives here
```

## Changes to existing files (at integration time)

| File | Change |
| :--- | :--- |
| `docker-compose.yml` | Added `gmda` service on port 8005. |
| `sketchmap_analyser/static/js/project.js` | Added `gmda: 8005` to port map; added `computeGMDAFromAllGenBaseMap()` and `computeJunctionGMDAFromAllGenBaseMap()`; results are written into `genResultArray` (including `nTL`/`nDL`, and `Junc_`-prefixed fields for junctions) and rendered via `populateGMDAResults()` into the main results table; `ResultSummary.csv` export extended with 12 GMDA columns; added a new `GMDADetailedOutput.csv` export containing nTL/nDL and all six metrics for both Buildings and Junctions. |
| `sketchmap_analyser/templates/generalizingmaps.html` | Replaced the standalone GMDA Calculator dropdown with an **Analyse** modal (`#analyseModal`) containing checkboxes: Completeness (locked on), Accuracy, Buildings GMDA, Junctions GMDA. |
| `sketchmap_analyser/templates/results.html` | Merged GMDA metrics into the main results table (`#OrderingofMaps`) as two grouped column sets ("Buildings GMDA", "Junctions GMDA") with a 2-row `<thead>`, replacing the separate GMDA Summary panel. Result window enlarged and given a sticky header. |
| `sketchmap_analyser/static/js/sketchmapeditor.js` | Added `openAnalyseModal()`, `closeAnalyseModal()`, and `runAnalysis()`, which sequences Completeness → Accuracy → Buildings GMDA → Junctions GMDA based on the modal's checkboxes, and toggles `hide-accuracy`/`hide-buildings`/`hide-junctions` classes on the results table to show only the selected columns. |
| `sketchmap_analyser/static/css/main.css` | Added modal styling (matching the existing menu button theme) and column show/hide rules (`.hide-accuracy`, `.hide-buildings`, `.hide-junctions`) plus sticky header rules for the results table. |
| `generalizations/generalizations/settings.py` | Fixed CORS configuration. |
