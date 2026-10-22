"""
Shared loader + weight-lookup helpers for the SketchMapia weighted
measurement scheme.

Each microservice that needs scoring weights (completeness,
generalizations, possibly accuracy later) copies this file in via its
Dockerfile and the top-level ``measurement_config.json``, then calls
``get_weights()`` once per request.

Config shape (see repo-root measurement_config.json):

    weights.route.{off_route, on_route}         -> int
    weights.street_position.{end, middle}       -> int
    weights.generalization.<GenType>            -> int

Runtime formulas:

    landmark_completeness_weight(on_route)
        = route[on_route|off_route]

    street_completeness_weight(position, on_route)
        = street_position[end|middle] * route[on_route|off_route]

    generalization_weight(gen_type, on_route)
        = generalization[gen_type] * route[on_route|off_route]

``No generalization`` instances are excluded by the caller, not here;
this module only returns weights for types explicitly present in the
config.
"""

import json
import os

DEFAULT_CONFIG_FILENAME = "measurement_config.json"


def _candidate_paths():
    """Where to look for the repo-root config file.

    - ``$MEASUREMENT_CONFIG_PATH`` (explicit override, used by tests)
    - ``/app/measurement_config.json`` (container convention: each service
      mounts the repo-root file here via docker-compose)
    - ``<cwd>/measurement_config.json`` (local dev when CWD is repo root)
    - two directories up from this module (local dev when imported from
      source without a mount; keeps the file at the repo root on disk)
    """
    env = os.environ.get("MEASUREMENT_CONFIG_PATH")
    if env:
        yield env
    yield os.path.join("/app", DEFAULT_CONFIG_FILENAME)
    yield os.path.join(os.getcwd(), DEFAULT_CONFIG_FILENAME)
    yield os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        DEFAULT_CONFIG_FILENAME,
    )


def load_config(path=None):
    """Load the shared config. ``path`` lets tests point at a fixture."""
    if path is not None:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    for candidate in _candidate_paths():
        if candidate and os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as fh:
                return json.load(fh)
    raise FileNotFoundError(
        f"{DEFAULT_CONFIG_FILENAME} not found; expected at the repo root "
        f"(set MEASUREMENT_CONFIG_PATH to override)."
    )


def _route_weight(weights, on_route):
    return weights["route"]["on_route" if on_route else "off_route"]


def landmark_completeness_weight(weights, on_route):
    return _route_weight(weights, on_route)


def street_completeness_weight(weights, position, on_route):
    """``position`` is ``"end"`` or ``"middle"``."""
    pos = weights["street_position"][position]
    return pos * _route_weight(weights, on_route)


def generalization_weight(weights, gen_type, on_route):
    """Return 0 for types absent from the config (e.g. ``No generalization``)."""
    base = weights["generalization"].get(gen_type, 0)
    if base == 0:
        return 0
    return base * _route_weight(weights, on_route)


def get_weights(path=None):
    """Convenience: return the ``weights`` sub-dict used by the helpers above."""
    return load_config(path)["weights"]
