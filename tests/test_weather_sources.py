from __future__ import annotations

import unittest
from datetime import date, timedelta
import importlib
from pathlib import Path
import sys
import types



ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)

weather_sources = importlib.import_module("custom_components.gazon_intelligent.weather_sources")


class WeatherSourcesTests(unittest.TestCase):
    def test_get_float_from_attributes_prefers_first_numeric_value(self) -> None:
        attributes = {
            "temperature": "18.7",
            "native_temperature": 21,
            "humidity": "44,2",
        }

        value = weather_sources.get_float_from_attributes(attributes, "temperature", "native_temperature")

        self.assertEqual(value, 18.7)

    def test_get_float_from_attributes_skips_missing_and_invalid_values(self) -> None:
        attributes = {
            "temperature": "unknown",
            "humidity": None,
            "wind_speed": "13.5",
        }

        value = weather_sources.get_float_from_attributes(attributes, "temperature", "humidity", "wind_speed")

        self.assertEqual(value, 13.5)

    def test_get_float_from_attributes_returns_none_when_no_numeric_value(self) -> None:
        attributes = {
            "temperature": "unknown",
            "humidity": None,
        }

        value = weather_sources.get_float_from_attributes(attributes, "temperature", "humidity")

        self.assertIsNone(value)

    def test_extract_weather_profile_collects_standard_fields(self) -> None:
        attributes = {
            "temperature": "18.2",
            "apparent_temperature": "17.4",
            "humidity": "44",
            "wind_speed": "13.5",
            "pressure": "1012.8",
            "cloud_coverage": "63",
            "dew_point": "11.1",
            "uv_index": "4",
            "precipitation_probability": "35",
            "condition": "sunny",
        }

        profile = weather_sources.extract_weather_profile(attributes)

        self.assertEqual(profile["weather_temperature"], 18.2)
        self.assertEqual(profile["weather_apparent_temperature"], 17.4)
        self.assertEqual(profile["weather_humidity"], 44.0)
        self.assertEqual(profile["weather_wind_speed"], 13.5)
        self.assertEqual(profile["weather_pressure"], 1012.8)
        self.assertEqual(profile["weather_cloud_coverage"], 63.0)
        self.assertEqual(profile["weather_dew_point"], 11.1)
        self.assertEqual(profile["weather_uv_index"], 4.0)
        self.assertEqual(profile["weather_precipitation_probability"], 35.0)
        self.assertEqual(profile["weather_condition"], "sunny")

    def test_extract_weather_forecast_summary_collects_day_values(self) -> None:
        today = date.today()
        forecasts = [
            {
                "datetime": (today + timedelta(days=1)).isoformat(),
                "temperature": "16.2",
                "precipitation": "3.1",
            },
            {
                "datetime": today.isoformat(),
                "temperature": "19.4",
                "apparent_temperature": "18.0",
                "precipitation": "0.8",
                "condition": "cloudy",
            },
        ]

        summary = weather_sources.extract_weather_forecast_summary(forecasts)

        self.assertEqual(summary["forecast_temperature_today"], 19.4)
        self.assertEqual(summary["forecast_pluie_24h"], 0.8)
        self.assertEqual(summary["forecast_pluie_demain"], 3.1)
        self.assertEqual(summary["forecast_condition_today"], "cloudy")
        self.assertEqual(summary["forecast_date_today"], today.isoformat())
        self.assertEqual(summary["forecast_date_tomorrow"], (today + timedelta(days=1)).isoformat())

    def test_extract_weather_forecast_summary_falls_back_when_dates_missing(self) -> None:
        forecasts = [
            {
                "temperature": "19.4",
                "precipitation": "0.8",
                "condition": "cloudy",
            },
            {
                "temperature": "16.2",
                "precipitation": "3.1",
            },
        ]

        summary = weather_sources.extract_weather_forecast_summary(forecasts)

        self.assertEqual(summary["forecast_temperature_today"], 19.4)
        self.assertEqual(summary["forecast_pluie_24h"], 0.8)
        self.assertEqual(summary["forecast_pluie_demain"], 3.1)
