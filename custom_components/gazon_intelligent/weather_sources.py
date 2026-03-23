from __future__ import annotations

from datetime import date, timedelta
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
    """Extrait un horizon météo court et générique à partir des prévisions journalières."""
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

    def _forecast_date(forecast: Mapping[str, Any]) -> date | None:
        raw = forecast.get("datetime") or forecast.get("date") or forecast.get("time")
        if raw is None:
            return None
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    def _forecast_precipitation_mm(forecast: Mapping[str, Any] | None) -> float | None:
        if not forecast:
            return None
        return _read_float(forecast, "precipitation")

    def _forecast_precipitation_signal(forecast: Mapping[str, Any] | None) -> float | None:
        if not forecast:
            return None
        return _read_float(forecast, "precipitation", "precipitation_probability")

    def _forecast_probability(forecast: Mapping[str, Any] | None) -> float | None:
        if not forecast:
            return None
        return _read_float(forecast, "precipitation_probability")

    def _daily_summary(forecast: Mapping[str, Any] | None, forecast_date: date | None) -> dict[str, Any]:
        return {
            "date": forecast_date.isoformat() if forecast_date else None,
            "temperature": _read_float(forecast, "temperature", "apparent_temperature"),
            "apparent_temperature": _read_float(forecast, "apparent_temperature"),
            "precipitation_mm": _forecast_precipitation_mm(forecast),
            "precipitation_signal": _forecast_precipitation_signal(forecast),
            "precipitation_probability": _forecast_probability(forecast),
            "condition": forecast.get("condition") if forecast else None,
        }

    by_date: dict[date, Mapping[str, Any]] = {}
    for forecast in forecasts:
        if not isinstance(forecast, Mapping):
            continue
        forecast_date = _forecast_date(forecast)
        if forecast_date is None:
            continue
        by_date.setdefault(forecast_date, forecast)

    today_date = date.today()
    horizon_dates = [today_date + timedelta(days=offset) for offset in range(3)]
    horizon_forecasts: list[Mapping[str, Any] | None] = [by_date.get(forecast_date) for forecast_date in horizon_dates]
    if horizon_forecasts[0] is None:
        horizon_forecasts[0] = forecasts[0] if len(forecasts) > 0 and isinstance(forecasts[0], Mapping) else None
    if horizon_forecasts[1] is None:
        horizon_forecasts[1] = forecasts[1] if len(forecasts) > 1 and isinstance(forecasts[1], Mapping) else None
    if horizon_forecasts[2] is None:
        horizon_forecasts[2] = forecasts[2] if len(forecasts) > 2 and isinstance(forecasts[2], Mapping) else None

    daily_summaries = []
    for forecast, forecast_date in zip(horizon_forecasts, horizon_dates):
        daily_summaries.append(_daily_summary(forecast, forecast_date))

    precipitation_mm_values = [item["precipitation_mm"] for item in daily_summaries]
    precipitation_probability_values = [
        item["precipitation_probability"] for item in daily_summaries if item["precipitation_probability"] is not None
    ]
    if all(value is not None for value in precipitation_mm_values):
        forecast_pluie_3j = round(sum(float(value) for value in precipitation_mm_values if value is not None), 1)
    else:
        forecast_pluie_3j = None
    forecast_probabilite_max_3j = (
        round(max(float(value) for value in precipitation_probability_values), 1)
        if precipitation_probability_values
        else None
    )

    return {
        "forecast_pluie_24h": daily_summaries[0]["precipitation_signal"],
        "forecast_pluie_demain": daily_summaries[1]["precipitation_signal"],
        "forecast_pluie_j2": daily_summaries[2]["precipitation_signal"],
        "forecast_pluie_3j": forecast_pluie_3j,
        "forecast_probabilite_max_3j": forecast_probabilite_max_3j,
        "forecast_temperature_today": daily_summaries[0]["temperature"],
        "forecast_temperature_tomorrow": daily_summaries[1]["temperature"],
        "forecast_temperature_j2": daily_summaries[2]["temperature"],
        "forecast_condition_today": daily_summaries[0]["condition"],
        "forecast_condition_tomorrow": daily_summaries[1]["condition"],
        "forecast_condition_j2": daily_summaries[2]["condition"],
        "forecast_date_today": daily_summaries[0]["date"],
        "forecast_date_tomorrow": daily_summaries[1]["date"],
        "forecast_date_j2": daily_summaries[2]["date"],
        "forecast_days": daily_summaries,
    }
