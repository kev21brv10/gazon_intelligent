from __future__ import annotations

import unittest
from importlib import util
from pathlib import Path
import sys


def _load_weather_sources_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "gazon_intelligent"
        / "weather_sources.py"
    )
    spec = util.spec_from_file_location("gazon_intelligent_weather_sources", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {module_path}")
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


weather_sources = _load_weather_sources_module()


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
        forecasts = [
            {
                "temperature": "19.4",
                "apparent_temperature": "18.0",
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
        self.assertEqual(summary["forecast_condition_today"], "cloudy")
