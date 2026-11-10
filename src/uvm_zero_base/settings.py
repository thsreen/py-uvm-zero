"""Testbench settings: Python defaults here, then TB_CONFIG "settings", then TB_ENV_CONFIG."""
from numbers import Real

ENV_DEFAULTS = {"max_errors": 1, "timeout": 1, "timeout_unit": "ms", "heartbeat_timeout": 1000,
                "drain_cycles": 10}
SCOREBOARD_DEFAULTS = {"history": 0}
_UNITS = ("fs", "ps", "ns", "us", "ms", "sec", "step")


def _positive_int(value):
    return type(value) is int and value > 0


def _positive_number(value):
    return type(value) is not bool and isinstance(value, Real) and value > 0


# Each setting: (accepts value?, description for the error message).
_RULES = {
    "max_errors": (_positive_int, "a positive integer"),
    "timeout": (lambda value: value is None or _positive_number(value), "a positive number or null"),
    "timeout_unit": (lambda value: value in _UNITS, f"one of {', '.join(_UNITS)}"),
    "heartbeat_timeout": (lambda value: value is None or _positive_int(value), "a positive integer or null"),
    "drain_cycles": (lambda value: type(value) is int and value >= 0, "a non-negative integer"),
    "history": (lambda value: value is None or (type(value) is int and value >= 0), "a non-negative integer or null"),
}


def check(values, defaults, where):
    """Return one problem per unknown or invalid setting."""
    if not isinstance(values, dict):
        return [f"{where} must be a JSON object"]

    problems = []
    for key, value in values.items():
        if key not in defaults:
            problems.append(f"{where}: unknown setting {key!r}")
            continue

        accepts, description = _RULES[key]
        if not accepts(value):
            problems.append(f"{where}.{key} must be {description}, got {value!r}")

    return problems


def resolve(defaults, *layers, where="settings"):
    """Merge layers over the Python defaults, later layers winning; raise on bad values."""
    merged = dict(defaults)
    for layer in layers:
        if layer:
            problems = check(layer, defaults, where)
            if problems:
                raise ValueError("\n".join(problems))

            merged.update(layer)

    return merged
