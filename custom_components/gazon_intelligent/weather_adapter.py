from __future__ import annotations

"""Adaptateur météo minimal pour préparer des providers multiples."""

from collections.abc import Mapping
from datetime import date
from typing import Any

from .weather_sources import extract_weather_forecast_summary, extract_weather_profile


class WeatherAdapter:
    """Normalise les données météo utilisées par le coordinateur."""

    @staticmethod
    def profile_from_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
        return extract_weather_profile(attributes)

    @staticmethod
    def forecast_summary(forecasts: list[Mapping[str, Any]] | None) -> dict[str, Any]:
        return extract_weather_forecast_summary(forecasts)

    @staticmethod
    def build_day_context(
        weather_profile: dict[str, Any] | None,
        forecast_summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        weather_profile = weather_profile or {}
        forecast_summary = forecast_summary or {}
        return {
            "today": {
                "date": forecast_summary.get("forecast_date_today") or date.today().isoformat(),
                "temperature": forecast_summary.get("forecast_temperature_today"),
                "pluie_24h": forecast_summary.get("forecast_pluie_24h"),
                "condition": forecast_summary.get("forecast_condition_today"),
                "profile": weather_profile,
            },
            "tomorrow": {
                "date": forecast_summary.get("forecast_date_tomorrow"),
                "pluie_demain": forecast_summary.get("forecast_pluie_demain"),
            },
        }

