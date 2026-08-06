from __future__ import annotations

"""Adaptateur météo minimal pour préparer des providers multiples."""

from collections.abc import Mapping
from typing import Any

from .weather_sources import extract_weather_forecast_summary, extract_weather_profile


class WeatherAdapter:
    """Normalise les données météo utilisées par le coordinateur."""

    @staticmethod
    def profile_from_attributes(
        attributes: Mapping[str, Any] | None,
        *,
        condition: str | None = None,
    ) -> dict[str, Any]:
        """`condition` est l'ÉTAT de l'entité météo — voir `extract_weather_profile`."""
        return extract_weather_profile(attributes, condition=condition)

    @staticmethod
    def forecast_summary(forecasts: list[Mapping[str, Any]] | None) -> dict[str, Any]:
        return extract_weather_forecast_summary(forecasts)
