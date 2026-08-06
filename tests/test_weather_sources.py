from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types
from unittest.mock import patch
from zoneinfo import ZoneInfo



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

homeassistant = types.ModuleType("homeassistant")
homeassistant.__path__ = []  # type: ignore[attr-defined]
sys.modules["homeassistant"] = homeassistant
util = types.ModuleType("homeassistant.util")
util.__path__ = []  # type: ignore[attr-defined]
sys.modules["homeassistant.util"] = util
dt_module = types.ModuleType("homeassistant.util.dt")
dt_module.now = lambda: datetime(2026, 4, 17, 12, 0, tzinfo=ZoneInfo("Europe/Paris"))  # type: ignore[attr-defined]
dt_module.utcnow = lambda: dt_module.now().astimezone(timezone.utc)  # type: ignore[attr-defined]
sys.modules["homeassistant.util.dt"] = dt_module
util.dt = dt_module  # type: ignore[attr-defined]

weather_sources = importlib.import_module("custom_components.gazon_intelligent.weather_sources")
weather_sources = importlib.reload(weather_sources)


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
        today = date(2026, 4, 17)
        forecasts = [
            {
                "datetime": (today + timedelta(days=2)).isoformat(),
                "temperature": "15.4",
                "precipitation": "1.2",
                "condition": "rainy",
            },
            {
                "datetime": (today + timedelta(days=1)).isoformat(),
                "temperature": "16.2",
                "precipitation": "3.1",
                "precipitation_probability": "75",
            },
            {
                "datetime": today.isoformat(),
                "temperature": "19.4",
                "apparent_temperature": "18.0",
                "precipitation": "0.8",
                "precipitation_probability": "20",
                "condition": "cloudy",
            },
        ]

        with patch.object(
            weather_sources.dt_util,
            "now",
            return_value=datetime(2026, 4, 17, 12, 0, tzinfo=ZoneInfo("Europe/Paris")),
        ):
            summary = weather_sources.extract_weather_forecast_summary(forecasts)

        self.assertEqual(summary["forecast_temperature_today"], 19.4)
        self.assertEqual(summary["forecast_pluie_24h"], 0.8)
        self.assertEqual(summary["forecast_pluie_demain"], 3.1)
        self.assertEqual(summary["forecast_pluie_j2"], 1.2)
        self.assertEqual(summary["forecast_pluie_3j"], 5.1)
        self.assertEqual(summary["forecast_probabilite_max_3j"], 75.0)
        self.assertEqual(summary["forecast_condition_today"], "cloudy")
        self.assertEqual(summary["forecast_condition_tomorrow"], None)
        self.assertEqual(summary["forecast_condition_j2"], "rainy")
        self.assertEqual(summary["forecast_date_today"], today.isoformat())
        self.assertEqual(summary["forecast_date_tomorrow"], (today + timedelta(days=1)).isoformat())
        self.assertEqual(summary["forecast_date_j2"], (today + timedelta(days=2)).isoformat())
        self.assertEqual(len(summary["forecast_days"]), 3)

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


class LaConditionMeteoVientDeLEtatPasDesAttributsTests(unittest.TestCase):
    """Chez Home Assistant, la condition d'une entité `weather.*` EST son état.

    `extract_weather_profile` lisait `attributes.get("condition")` — toujours `None`. Le garde
    « il pleut en ce moment » n'a donc jamais pu s'armer depuis sa mise en place le 18/03/2026.
    Conséquence mesurée le 30/07/2026 : `weather.forecast_maison` = `rainy` de 06:43 à 09:28,
    pluviomètre de 1,1 à 2,2 mm, et **5,1 mm versés à 07:38 sous la pluie**.
    """

    # Les attributs réels d'une entité météo Home Assistant : aucune clé `condition`.
    ATTRIBUTS_REELS = {
        "temperature": 17.0,
        "humidity": 92,
        "wind_speed": 11.0,
        "pressure": 1004.0,
        "cloud_coverage": 98,
    }

    def test_la_condition_est_lue_depuis_l_etat(self) -> None:
        profil = weather_sources.extract_weather_profile(
            self.ATTRIBUTS_REELS, condition="rainy"
        )
        self.assertEqual(profil["weather_condition"], "rainy")

    def test_sans_l_etat_la_condition_reste_introuvable(self) -> None:
        """La preuve du défaut : avec les seuls attributs, la condition est nulle."""
        profil = weather_sources.extract_weather_profile(self.ATTRIBUTS_REELS)
        self.assertIsNone(profil["weather_condition"])

    def test_les_non_valeurs_de_home_assistant_sont_ecartees(self) -> None:
        for etat in ("unknown", "unavailable", "", "  ", None):
            with self.subTest(etat=etat):
                profil = weather_sources.extract_weather_profile(
                    self.ATTRIBUTS_REELS, condition=etat
                )
                self.assertIsNone(profil["weather_condition"])

    def test_l_attribut_reste_lu_en_repli(self) -> None:
        """Un fournisseur qui publierait quand même l'attribut continue de fonctionner."""
        profil = weather_sources.extract_weather_profile(
            {**self.ATTRIBUTS_REELS, "condition": "pouring"}, condition=None
        )
        self.assertEqual(profil["weather_condition"], "pouring")

    def test_un_profil_purement_etat_reste_exploitable(self) -> None:
        """Attributs vides mais état connu : on ne doit pas retourner un dict vide."""
        profil = weather_sources.extract_weather_profile({}, condition="rainy")
        self.assertEqual(profil["weather_condition"], "rainy")

    def test_le_garde_pluie_s_arme_enfin(self) -> None:
        """Le bout de la chaîne : c'est ce booléen qui bloque arrosage et tonte."""
        guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
        for etat in ("rainy", "pouring", "lightning-rainy", "snowy-rainy"):
            with self.subTest(condition=etat):
                profil = weather_sources.extract_weather_profile(
                    self.ATTRIBUTS_REELS, condition=etat
                )
                self.assertTrue(guidance.is_active_rain_weather(profil))
        # Contrôle négatif, et preuve du défaut d'origine.
        self.assertFalse(
            guidance.is_active_rain_weather(
                weather_sources.extract_weather_profile(self.ATTRIBUTS_REELS)
            )
        )
        self.assertFalse(
            guidance.is_active_rain_weather(
                weather_sources.extract_weather_profile(
                    self.ATTRIBUTS_REELS, condition="sunny"
                )
            )
        )
