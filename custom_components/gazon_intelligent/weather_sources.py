from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def get_float_from_attributes(attributes: Mapping[str, Any] | None, *keys: str) -> float | None:
    """Retourne le premier attribut numérique disponible parmi plusieurs clés."""
    if not attributes:
        return None
    for key in keys:
        value = attributes.get(key)
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def extract_weather_profile(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extrait un maximum d'informations standard depuis une entité météo."""
    if not attributes:
        return {}

    return {
        "weather_temperature": get_float_from_attributes(attributes, "temperature", "native_temperature"),
        "weather_apparent_temperature": get_float_from_attributes(
            attributes,
            "apparent_temperature",
            "native_apparent_temperature",
        ),
        "weather_humidity": get_float_from_attributes(attributes, "humidity", "native_humidity"),
        "weather_wind_speed": get_float_from_attributes(attributes, "wind_speed", "native_wind_speed"),
        "weather_pressure": get_float_from_attributes(attributes, "pressure", "native_pressure"),
        "weather_cloud_coverage": get_float_from_attributes(
            attributes,
            "cloud_coverage",
            "native_cloud_coverage",
        ),
        "weather_dew_point": get_float_from_attributes(attributes, "dew_point", "native_dew_point"),
        "weather_uv_index": get_float_from_attributes(attributes, "uv_index", "native_uv_index"),
        "weather_precipitation_probability": get_float_from_attributes(
            attributes,
            "precipitation_probability",
            "native_precipitation_probability",
        ),
        "weather_condition": attributes.get("condition"),
    }
