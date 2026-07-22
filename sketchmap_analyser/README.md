# sketchmap_analyser — Main Web Application

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Django](https://img.shields.io/badge/Django-3.2-092E20)
![Leaflet](https://img.shields.io/badge/Leaflet-map%20editor-199900)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED)
![Port](https://img.shields.io/badge/sketchmap__analyser-:8000-orange)

The **orchestrator and user interface** of SketchMapia: the sketch map editor, the alignment tool, the Analyse workflow, the results table, and the CSV export. Every analysis microservice is called from *this* application's frontend.

## Role in the architecture

This service holds no analysis logic of its own. It:

1. Serves the landing page, the map editor, and the results view.
2. Lets the researcher load a base map and sketch maps, draw/import features, and **align** sketch features to base features.
3. On **Analyse**, sequences calls to the analysis services and collects their JSON responses.
4. Renders everything into one results table and exports it as a zip of CSVs.

The calls are made **from the browser**, not server-to-server — which is why the port map and the Apache reverse proxy both matter.

<p align="center">
  <img src="../docs/images/architecture.png" alt="Architecture" width="750"/>
</p>

## Service routing — how the frontend finds the services

`static/js/project.js` contains `getServiceUrl(serviceName)`, the single place where routing is decided:

```js
function getServiceUrl(serviceName) {
    const hostName = window.location.hostname;
    const protocol = window.location.protocol;

    // Local dev: direct Docker ports
    if (hostName === 'localhost' || hostName === '127.0.0.1') {
        const portMap = {
            generalizations: 8001,
            completeness: 8002,
            qualitativerelations: 8003,
            validation: 8004,
            gmda: 8005,
            bdr: 8006
        };
        return `${protocol}//${hostName}:${portMap[serviceName]}`;
    }

    // Production: Apache reverse-proxy paths on the same origin
    return `${protocol}//${hostName}`;
}
```

| Environment | How services are reached |
| :--- | :--- |
| **Local** (`localhost` / `127.0.0.1`) | Direct Docker ports, `8001`–`8006` |
| **Production** (any other hostname) | Same origin; Apache proxies each `/service/` path to its localhost port |

**Adding a service means adding it to this port map** — see [`docs/adding-a-new-service.md`](../docs/adding-a-new-service.md) for the full six-step checklist.

## The Analyse workflow

<p align="center">
  <img src="../docs/images/dataflow.png" alt="Data Flow" width="700"/>
</p>

1. Load a project and click **Analyse**.
2. The `#analyseModal` opens (`openAnalyseModal()` in `static/js/sketchmapeditor.js`) with four checkboxes:
   - **Completeness** — locked on, always runs
   - **Accuracy** — qualitative spatial relations
   - **Buildings GMDA** — landmark-based GMDA
   - **Junctions GMDA** — junction-based GMDA
3. `runAnalysis()` runs the generalization step first, then sequences the selected metrics:
   **Completeness → Accuracy → Buildings GMDA → Junctions GMDA**
4. The generalized base map is cached per sketch map in `allGenBaseMap[sketchMaptitle]` and reused by every metric — it is computed once, not per-metric.
5. Results are written into `genResultArray` and rendered by `populateGMDAResults()` into the main results table (`#OrderingofMaps` in `templates/results.html`).
6. Columns for unselected metrics are hidden via the `hide-accuracy` / `hide-buildings` / `hide-junctions` classes toggled on the table — the columns exist in the DOM but are collapsed by CSS in `static/css/main.css`.

<details>
<summary><b>Request lifecycle diagram</b></summary>
<p align="center">
  <img src="../docs/images/request_lifecycle.png" alt="Request Lifecycle" width="700"/>
</p>
</details>

## Results table

One table, grouped column sets, a 2-row `<thead>` and a sticky header. Grouped sets:

| Group | Source service |
| :--- | :--- |
| Completeness | [`completeness`](../completeness/README.md) |
| Accuracy (qualitative relations) | [`accuracy`](../accuracy/README.md) |
| Buildings GMDA | [`gmda`](../gmda/README.md) |
| Junctions GMDA | [`gmda`](../gmda/README.md) |
| Landmarks BDR / Junctions BDR | [`bdr`](../bdr/README.md) |

Junction-side GMDA fields are stored with a `Junc_` prefix in `genResultArray` to keep them distinct from the landmark-side fields.

## CSV export

**Download Results** builds a zip in the browser with JSZip (`static/js/jszip.min.js`), assembled in `static/js/project.js`:

| File | Contents |
| :--- | :--- |
| `ResultSummary.csv` | The full results table, one row per sketch map |
| `CompletenessDetailedOutput.csv` | Landmark/street counts and completeness percentages |
| `GeneralizationDetailedOutput.csv` | Generalization groups and types |
| `QADetailedOutput.csv` | Per-calculus qualitative relation counts *(only if Accuracy ran)* |
| `GMDADetailedOutput.csv` | `nTL`/`nDL` and all six metrics, for both Buildings and Junctions |
| `BDRDetailedOutput.csv` | `r`, `DI`, `phi`, `theta`, `alpha1`, `alpha2` for both variants |
| `QualitativeRelations/<sketchmap>.csv` | Sketch map QCN *(only if Accuracy ran)* |
| `QualitativeRelations/BaseMapFor<sketchmap>.csv` | Base map QCN *(only if Accuracy ran)* |

## URLs

| Path | View | Purpose |
| :--- | :--- | :--- |
| `/` | `TemplateView` → `home.html` | Landing page |
| `/documentation/` | `TemplateView` → `documentation.html` | In-app documentation page |
| `/generalizingmaps/` | `generalizingmaps.views.map` | The map editor |
| `/generalizingmaps/compare/` | `generalizingmaps.views.compare` | Comparison view |
| `/generalizingmaps/compare/compareResults/` | `generalizingmaps.views.compareResults` | Comparison results |
| `/accounts/signup/` | `accounts.views.SignUp` | User registration |
| `/useraccount/...` | `django.contrib.auth.urls` | Login/logout/password reset |
| `/admin/` | Django admin | Admin |

> `home.html` extends `base.html`, and `base.html` carries the landing page content directly — there is no `{% block content %}`. Landing page edits go in `base.html`.

## Running standalone

```bash
cd sketchmap_analyser
pip install -r requirements.txt
python manage.py makemigrations && python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Running standalone gives you the UI, but **Analyse will fail** — the analysis services on 8001–8006 won't be up. For a working app, use the full stack:

```bash
docker-compose up --build
```

Then open **http://localhost:8000/generalizingmaps/**.

## Project structure

```text
sketchmap_analyser/
├── Dockerfile                       # runs on port 8000
├── requirements.txt
├── manage.py
├── sketchmap_analyser/
│   ├── settings.py
│   ├── urls.py                      # root URL conf
│   ├── wsgi.py
│   └── asgi.py
├── accounts/                        # signup
├── generalizingmaps/                # editor + compare views
├── templates/
│   ├── base.html                    # landing page (content lives here)
│   ├── home.html                    # extends base.html
│   ├── documentation.html           # in-app documentation page
│   ├── generalizingmaps.html        # editor + #analyseModal
│   ├── results.html                 # #OrderingofMaps results table
│   ├── compare.html
│   ├── signup.html
│   └── registration/login.html
└── static/
    ├── js/
    │   ├── project.js               # getServiceUrl(), service calls, CSV/zip export
    │   ├── sketchmapeditor.js       # openAnalyseModal(), runAnalysis(), column toggles
    │   ├── map.js, sketchMap_sma_script.js, compare.js, js-utils.js
    │   └── leaflet.*, jszip.min.js, ... (vendor)
    ├── css/main.css                 # modal styling, .hide-* column rules, sticky header
    ├── img/, images/, videos/, font/
    ├── geojson_files/               # sample OSM data (buildings, streets, regions)
    └── leaflet/, vendor/
```

## Where to make common changes

| Task | File |
| :--- | :--- |
| Add a service to the frontend | `static/js/project.js` → `getServiceUrl()` port map |
| Add a checkbox to the Analyse modal | `templates/generalizingmaps.html` (`#analyseModal`) |
| Change the analysis sequence | `static/js/sketchmapeditor.js` → `runAnalysis()` |
| Add a results column | `templates/results.html` + `populateGMDAResults()` in `project.js` |
| Show/hide columns per metric | `.hide-*` classes in `static/css/main.css` |
| Add a CSV to the export zip | `static/js/project.js` (~line 1520, the `zip.file(...)` block) |
| Edit the landing page | `templates/base.html` |
| Edit the documentation page | `templates/documentation.html` |

## Related

- [Main README](../README.md) — architecture, quick start, deployment.
- [`docs/adding-a-new-service.md`](../docs/adding-a-new-service.md) — the six-step checklist for a new microservice.
- [`docs/gmda-integration-notes.md`](../docs/gmda-integration-notes.md) — what changed in this app when GMDA was integrated.