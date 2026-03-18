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


def extract_weather_forecast_summary(forecasts: list[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Extrait la pluie et la température prévues pour aujourd'hui et demain."""
    if not forecasts:
        return {}

    def _read_float(forecast: Mapping[str, Any] | None, *keys: str) -> float | None:
        if not forecast:
            return None
        for key in keys:
            parsed = _to_float(forecast.get(key))
            if parsed is not None:
                return parsed
        return None

    today = forecasts[0] if len(forecasts) > 0 and isinstance(forecasts[0], Mapping) else None
    tomorrow = forecasts[1] if len(forecasts) > 1 and isinstance(forecasts[1], Mapping) else None

    return {
        "forecast_pluie_24h": _read_float(today, "precipitation"),
        "forecast_pluie_demain": _read_float(tomorrow, "precipitation", "precipitation_probability"),
        "forecast_temperature_today": _read_float(today, "temperature", "apparent_temperature"),
        "forecast_condition_today": today.get("condition") if today else None,
    }
