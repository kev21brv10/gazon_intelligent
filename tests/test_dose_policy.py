from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
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


def _install_homeassistant_dt_stub() -> None:
    homeassistant = sys.modules.get("homeassistant")
    if homeassistant is None:
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []  # type: ignore[attr-defined]
        sys.modules["homeassistant"] = homeassistant
    util = sys.modules.get("homeassistant.util")
    if util is None:
        util = types.ModuleType("homeassistant.util")
        util.__path__ = []  # type: ignore[attr-defined]
        sys.modules["homeassistant.util"] = util
    dt_module = types.ModuleType("homeassistant.util.dt")
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=ZoneInfo("Europe/Paris"))  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_dt_stub()

guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
decision = importlib.import_module("custom_components.gazon_intelligent.decision")
decision_watering = importlib.import_module("custom_components.gazon_intelligent.decision_watering")
watering_policy = importlib.import_module("custom_components.gazon_intelligent.watering_policy")


def _make_context(**overrides):
    payload = {
        "today": date(2026, 5, 15),
        "temperature": 20.0,
        "forecast_temperature_today": 21.0,
        "vent": 3.0,
        "humidite_sol": 45.0,
        "type_sol": "limoneux",
        "pluie_probabilite_max_3j": 10.0,
        "pluie_24h": 0.0,
        "pluie_demain": 0.0,
        "pluie_j2": 0.0,
        "pluie_3j": 0.0,
        "soil_balance": {"reserve_mm": 16.7, "delta_mm": -1.1},
        "weather_profile": {},
        "runtime_context": {},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class TestDosePolicy(unittest.TestCase):
    def test_resolve_dose_policy_disabled_preserves_legacy_objective(self) -> None:
        policy = watering_policy.resolve_dose_policy(
            {
                "phase_dominante": "Normal",
                "sous_phase": "Normal",
                "month": 5,
                "temperature": 20.0,
                "et0_mm": 2.0,
                "legacy_objective_mm": 1.2,
            },
            dynamic_enabled=False,
        )
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["dose_band"], "baseline")
        self.assertEqual(policy["dose_mm_effective"], 1.2)
        self.assertEqual(policy["candidate_band"], "spring")
        self.assertEqual(policy["candidate_mm"], 6.0)

    def test_resolve_dose_policy_spring_band(self) -> None:
        policy = watering_policy.resolve_dose_policy(
            {
                "phase_dominante": "Normal",
                "sous_phase": "Normal",
                "month": 4,
                "temperature": 19.0,
                "et0_mm": 2.0,
                "legacy_objective_mm": 1.0,
            },
            dynamic_enabled=True,
        )
        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["dose_band"], "spring")
        self.assertEqual(policy["dose_mm_effective"], 6.0)

    def test_resolve_dose_policy_summer_band(self) -> None:
        policy = watering_policy.resolve_dose_policy(
            {
                "phase_dominante": "Normal",
                "sous_phase": "Normal",
                "month": 7,
                "temperature": 30.0,
                "et0_mm": 3.3,
                "legacy_objective_mm": 1.0,
            },
            dynamic_enabled=True,
        )
        self.assertEqual(policy["dose_band"], "summer")
        self.assertEqual(policy["dose_mm_effective"], 8.0)

    def test_resolve_dose_policy_heatwave_band(self) -> None:
        policy = watering_policy.resolve_dose_policy(
            {
                "phase_dominante": "Normal",
                "sous_phase": "Normal",
                "month": 7,
                "temperature": 35.0,
                "et0_mm": 5.2,
                "heat_stress_level": "canicule",
                "legacy_objective_mm": 1.0,
            },
            dynamic_enabled=True,
        )
        self.assertEqual(policy["dose_band"], "heatwave")
        self.assertEqual(policy["dose_mm_effective"], 10.0)

    def test_resolve_dose_policy_autumn_band(self) -> None:
        policy = watering_policy.resolve_dose_policy(
            {
                "phase_dominante": "Normal",
                "sous_phase": "Normal",
                "month": 10,
                "temperature": 22.0,
                "et0_mm": 2.0,
                "legacy_objective_mm": 1.0,
            },
            dynamic_enabled=True,
        )
        self.assertEqual(policy["dose_band"], "autumn")
        self.assertEqual(policy["dose_mm_effective"], 5.5)

    def test_resolve_dose_policy_sursemis_band(self) -> None:
        policy = watering_policy.resolve_dose_policy(
            {
                "phase_dominante": "Sursemis",
                "sous_phase": "Reprise",
                "month": 5,
                "temperature": 21.0,
                "et0_mm": 2.0,
                "legacy_objective_mm": 1.0,
            },
            dynamic_enabled=True,
        )
        self.assertEqual(policy["dose_band"], "sursemis")
        self.assertEqual(policy["dose_mm_effective"], 2.5)

    def test_build_decision_snapshot_exposes_watering_objective(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 5, 15),
            hour_of_day=8,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=45.0,
            type_sol="limoneux",
            etp_capteur=2.0,
        )
        self.assertIn("objectif_mm", snapshot)
        self.assertIn("mm_final", snapshot)
        self.assertIn("use_depletion_logic", snapshot)
        self.assertFalse(snapshot["use_depletion_logic"])
        self.assertEqual(snapshot["objectif_mm"], snapshot["mm_final"])


if __name__ == "__main__":
    unittest.main()
