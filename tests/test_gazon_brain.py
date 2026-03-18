from __future__ import annotations

import unittest
from datetime import date
from importlib import util
from pathlib import Path
import sys
import types


MODULE_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "gazon_intelligent"
)


def _ensure_package(name: str) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(MODULE_DIR if name.endswith("gazon_intelligent") else MODULE_DIR.parent)]  # type: ignore[attr-defined]
    sys.modules[name] = module


def _load_module(fullname: str, filename: str):
    spec = util.spec_from_file_location(fullname, MODULE_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {filename}")
    module = util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


_ensure_package("custom_components")
_ensure_package("custom_components.gazon_intelligent")
_load_module("custom_components.gazon_intelligent.const", "const.py")
_load_module("custom_components.gazon_intelligent.water", "water.py")
_load_module("custom_components.gazon_intelligent.memory", "memory.py")
_load_module("custom_components.gazon_intelligent.soil_balance", "soil_balance.py")
_load_module("custom_components.gazon_intelligent.decision", "decision.py")
GazonBrain = _load_module(
    "custom_components.gazon_intelligent.gazon_brain",
    "gazon_brain.py",
).GazonBrain


class GazonBrainTests(unittest.TestCase):
    def test_load_state_sanitizes_legacy_payload(self) -> None:
        brain = GazonBrain()
        brain.load_state(
            {
                "mode": "Sursemis",
                "date_action": "2026-03-18",
                "history": [
                    {
                        "type": "arrosage",
                        "date": "2026-03-18",
                        "total_mm": 3.6,
                        "zones": [
                            {"zone": "zone_1", "mm": 1.2},
                            {"zone": "zone_2", "mm": 1.1},
                            {"zone": "zone_3", "mm": 1.3},
                        ],
                    }
                ],
                "products": {
                    "humuslight": {
                        "id": "humuslight",
                        "nom": "Humuslight",
                        "sol_compatible": "limoneux",
                    }
                },
                "soil_balance": {
                    "date": "2026-03-18",
                    "reserve_mm": "14.6",
                    "ledger": [],
                },
                "memory": {
                    "historique_total": 0,
                    "catalogue_produits": 0,
                },
            }
        )

        self.assertEqual(brain.mode, "Sursemis")
        self.assertEqual(brain.date_action, date(2026, 3, 18))
        self.assertEqual(brain.memory["historique_total"], 1)
        self.assertEqual(brain.memory["catalogue_produits"], 1)
        self.assertNotIn("sol_compatible", brain.products["humuslight"])

    def test_record_watering_keeps_session_summary(self) -> None:
        brain = GazonBrain()
        payload = brain.record_watering(
            date_action=date(2026, 3, 18),
            zones=[
                {"zone": "zone_1", "rate_mm_h": 2.4, "duration_min": 30.0, "mm": 1.2},
                {"zone": "zone_2", "rate_mm_h": 1.1, "duration_min": 60.0, "mm": 1.1},
                {"zone": "zone_3", "rate_mm_h": 1.3, "duration_min": 60.0, "mm": 1.3},
            ],
            source="auto_irrigation",
        )

        self.assertEqual(payload["total_mm"], 3.6)
        self.assertEqual(payload["session_total_mm"], 3.6)
        self.assertEqual(len(payload["zones"]), 3)
        self.assertEqual(brain.history[-1]["total_mm"], 3.6)

    def test_compute_snapshot_updates_and_persists_soil_balance(self) -> None:
        brain = GazonBrain()
        brain.record_watering(
            date_action=date(2026, 3, 18),
            total_mm=3.6,
            zones=[
                {"zone": "zone_1", "rate_mm_h": 2.4, "duration_min": 30.0, "mm": 1.2},
                {"zone": "zone_2", "rate_mm_h": 1.1, "duration_min": 60.0, "mm": 1.1},
                {"zone": "zone_3", "rate_mm_h": 1.3, "duration_min": 60.0, "mm": 1.3},
            ],
            source="auto_irrigation",
        )
        snapshot = brain.compute_snapshot(
            today=date(2026, 3, 18),
            temperature=20.0,
            pluie_24h=1.0,
            pluie_demain=0.0,
            humidite=60.0,
            type_sol="limoneux",
            etp_capteur=2.0,
            humidite_sol=None,
            vent=None,
            rosee=None,
            hauteur_gazon=None,
            retour_arrosage=None,
            pluie_source="capteur_pluie_24h",
            weather_profile={},
        )
        reloaded = GazonBrain()
        reloaded.load_state(brain.dump_state())

        self.assertGreater(snapshot["bilan_hydrique_mm"], 12.0)
        self.assertEqual(snapshot["soil_balance"]["reserve_mm"], reloaded.soil_balance["reserve_mm"])
        self.assertEqual(reloaded.soil_balance["reserve_mm"], brain.soil_balance["reserve_mm"])
