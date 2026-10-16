# Python 3.12 upgrade

All seven services use `python:3.12.15-bookworm` and Django 5.2.18 LTS.
The upgrade was checked on 16 October 2026. Python 3.12 receives security
fixes through October 2028; Django 5.2 receives extended support through
April 2028. See the [Python lifecycle](https://devguide.python.org/versions/)
and [Django lifecycle](https://www.djangoproject.com/download/).

## Compatibility findings and changes

The original Python 3.8.20 image is unsupported. Changing its tag alone
cannot work: NumPy 1.21.6 and SciPy 1.7.3 require Python below 3.11, and
Django 3.2 officially supports only Python 3.6–3.10.

Runtime dependencies were traced through the Django views, URL imports and
qualifiers. Each service now has a UTF-8 requirements file containing its
runtime dependencies, with exact versions for direct dependencies. Old
notebook, documentation, linting, Windows installer and unused Flask/OSMnx
packages are no longer installed in the service containers. The optional
legacy Neo4j/Spyder scripts and standalone OpenCV tracing prototype are
outside the deployed Django request paths and need their own environments.
Pandas stays on 2.3.3 to avoid an unnecessary migration to pandas 3.

The dependency changes require these application adjustments:

- Replace the removed `request.is_ajax()` API with the existing AJAX header
  check in the comparison endpoint.
- Replace pandas' removed `error_bad_lines` argument with `on_bad_lines`.
- Read alignment IDs as strings and fill comparison results with scalar
  `.at` assignments. Changes to rows returned by `iterrows()` do not reliably
  update the original DataFrame with the new pandas version. An absent
  alignment returns JSON `null`, preserving a blank cell when a researcher
  has not aligned a base feature.
- Explicitly retain `AutoField` for the UI project's implicit primary keys.
- Remove an unused scikit-learn import from BDR.
- Remove the obsolete `USE_L10N` setting from all seven services.

GeoPandas, Shapely, NumPy, scikit-learn, scikit-image, NetworkX and SVG tools
were updated to releases that install on Python 3.12. Their versions are
listed in each service's `requirements.txt`. Binary wheels are required in
Docker builds, so an unavailable native dependency fails the build instead
of silently attempting an untested source compilation. These wheels supply
the native geospatial libraries; the generalizations image no longer needs
separate GDAL/PROJ development packages. Build exclusions prevent Python bytecode from entering the images.
The existing SQLite files remain in the build context, preserving the
previous image behavior.

## Server CPU compatibility

The production VM does not expose all x86-64-v2 instructions. NumPy 2.4
raised its default x86 CPU baseline to that level, so the original upgrade's
NumPy 2.5.4 wheels failed during import. This stopped Django startup and
caused Apache to return 503. See the
[NumPy 2.4 release notes](https://numpy.org/doc/stable/release/2.4.0-notes.html#modulate-dispatched-x86-cpu-features).

All six services that use NumPy now explicitly pin `numpy==2.3.5`, including
the UI, which previously obtained NumPy indirectly through pandas. Python
remains 3.12.15 and Django remains 5.2.18. Completeness does not use NumPy.
The pin prevents a future image rebuild from silently selecting the
incompatible wheels again.

CI also runs each service's regression tests through QEMU's `qemu64` CPU
model, which lacks the newer instructions. This is separate from the
normal modern-CPU image checks. The emulator is used only for testing and
is not installed in the runtime images.

Preserve the UI database before publishing, following the deployment steps
below: the existing Watchtower setup updates containers automatically.
After CI publishes the corrected images, use the existing Compose file in
the server deployment directory (`~/sketchMapia-2025` in the supplied logs):

```bash
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps -a
sudo docker compose logs --tail=100 sketchmap_analyser
sudo docker compose exec sketchmap_analyser python -c 'import numpy; print(numpy.__version__)'
curl --max-time 10 -i http://127.0.0.1:8000/
```

The server uses its default Compose file; `docker-compose.server.yml` is
only a reference copy in this repository and was absent on the server.
Follow the database preservation steps below before replacing containers.
A longer-term infrastructure option is to expose x86-64-v2 CPU features to
the VM if its host supports them; that would allow future NumPy upgrades
without this compatibility pin.

## Validation

All eighteen current regression tests pass in rebuilt Linux amd64 images
both normally and under QEMU's older `qemu64` CPU model. All seven images
also pass dependency checks, Django system checks, migration generation
checks and migrations. The missing-alignment test covers omissions by each
researcher across ten maps.

The corrected UI also served real HTTP requests for `/` and
`/generalizingmaps/` with status 200 under `qemu64`. NumPy reported an
SSE/SSE2/SSE3 baseline, with SSSE3, SSE4.1, SSE4.2 and AVX unavailable.
This covers the CPU limitation missed by the original modern-CPU checks.

The initial upgrade additionally verified WSGI/ASGI loading, normal
container startup and migration of a separate Django 3.2.22 database to
5.2.18, preserving its original user's password and session login/logout.
Image runs include the repository's SQLite files.

| Service | Regression tests | Normal CPU | Older CPU (`qemu64`) |
| --- | ---: | --- | --- |
| sketchmap_analyser | 4 | Pass | Pass |
| generalizations | 3 | Pass | Pass |
| validation | 4 | Pass | Pass |
| completeness | 1 | Pass | Pass |
| accuracy / qualitativerelations | 1 | Pass | Pass |
| gmda | 3 | Pass | Pass |
| bdr | 2 | Pass | Pass |

The regression tests cover:

- Six UI pages, account creation, login and POST logout.
- Three-researcher CSV comparisons across ten maps, malformed CSV rows,
  numeric alignment IDs and agreement/disagreement values.
- The checked-in generalization example, compared against its existing
  output properties and geometries; amalgamation, buffered collapse and
  omission merge.
- Validation previews and approved street merges, endpoint snapping,
  route orientation and maps containing landmarks without streets.
- Completeness scores and all six qualitative relation groups for identical
  maps, including route-based relations.
- GMDA landmark and junction metrics for identical maps.
- BDR landmark and junction metrics against a known translation.

The GitHub test workflow builds each Linux amd64 image and runs dependency
checks, Django checks, migration checks, migrations and regression tests.
Publishing the images now depends on those jobs passing.

Run the same checks locally for a service:

```bash
docker build --platform linux/amd64 -t sketchmapia-312-test ./gmda
docker run --rm --platform linux/amd64 sketchmapia-312-test bash -ec '
  python -m pip check
  python manage.py check
  python manage.py makemigrations --check --dry-run
  python manage.py migrate --noinput
  python manage.py test --noinput
'
```

Tests use temporary files and Django's test database. No live database or
existing analysis output is needed.

## Deployment and limits

Rebuild and deploy all seven services together using the existing deployment
process. Back up the existing SQLite databases and retain the previous
images before applying migrations; rolling back migrated databases requires
restoring the corresponding backup. The normal container command already
runs `manage.py migrate`.

The reference server Compose file has no persistent database volume. Export
the running UI container's `/app/db.sqlite3` before replacement and arrange
for that database to be restored or mounted in the new container. This
upgrade preserves the existing image build behavior of copying the
repository's SQLite files.

This change does not deploy or publish images. Synthetic examples and the
checked-in sample cannot establish that every research dataset produces
identical results after native geometry and numerical library upgrades.
Before production rollout, compare representative saved projects in staging,
including roundabout collapse, junction merge, street-stub abstractions and
researcher CSV uploads. The UI's existing ten-map comparison assumption is
retained.

An existing validation edge case was observed during testing: a route that
still references a segment removed by an approved merge can raise
`KeyError: None` in `validateRoute`. That function and the merge/route ID
handling are unchanged by this upgrade; this is outside the passing route
orientation test, which uses retained segment IDs.
