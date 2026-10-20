"""Operator-supplied effort labels; validation does not verify client settings."""

SOURCES = ("requested", "client-reported", "inferred", "unknown")
FIELDS = ("reasoning_effort", "reasoning_effort_source", "requested_reasoning_effort")


def validate(metadata):
    """Validate without filling missing historical fields or inferring provenance."""
    effort = metadata.get("reasoning_effort")
    source = metadata.get("reasoning_effort_source")
    requested = metadata.get("requested_reasoning_effort")
    for name, value in (("reasoning_effort", effort), ("requested_reasoning_effort", requested)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(name + " must be a nonempty string or null")
    if source is not None and source not in SOURCES:
        raise ValueError("reasoning_effort_source must be requested, client-reported, inferred, or unknown")
    if source not in (None, "unknown") and effort is None:
        raise ValueError("reasoning_effort_source requires reasoning_effort unless unknown")
    if source == "requested" and requested is not None and effort != requested:
        raise ValueError("requested effort labels disagree; use client-reported or inferred for a differing value")


def labels(reasoning_effort=None, reasoning_effort_source="unknown", requested_reasoning_effort=None):
    result = dict(zip(FIELDS, (reasoning_effort, reasoning_effort_source, requested_reasoning_effort)))
    validate(result)
    return result


def add_arguments(parser):
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--reasoning-effort-source", choices=SOURCES, default="unknown")
    parser.add_argument("--requested-reasoning-effort")
