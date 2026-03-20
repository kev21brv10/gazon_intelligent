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

    def test_register_product_persists_application_fields(self) -> None:
        brain = GazonBrain()
        record = brain.register_product(
            "bio-1",
            "Bio Boost",
            "Biostimulant",
            dose_conseillee="3.0 ml / L",
            reapplication_after_days=14,
            delai_avant_tonte_jours=0,
            phase_compatible="Sursemis, Reprise",
            application_type="sol",
            application_requires_watering_after=True,
            application_post_watering_mm=1.2,
            application_irrigation_block_hours=0.0,
            application_irrigation_delay_minutes=30.0,
            application_irrigation_mode="auto",
            application_label_notes="Arrosage léger après application",
            note="Produit test",
        )

        self.assertEqual(record["application_type"], "sol")
        self.assertTrue(record["application_requires_watering_after"])
        self.assertEqual(record["application_post_watering_mm"], 1.2)
        self.assertEqual(record["application_irrigation_block_hours"], 0.0)
        self.assertEqual(record["application_irrigation_delay_minutes"], 30.0)
        self.assertEqual(record["application_irrigation_mode"], "auto")
        self.assertEqual(record["application_label_notes"], "Arrosage léger après application")

    def test_declare_intervention_persists_application_fields(self) -> None:
        brain = GazonBrain()
        item = brain.declare_intervention(
            "Traitement",
            date_action=date(2026, 3, 18),
            produit_id="fungi-x",
            produit="Fongicide X",
            dose="12 ml",
            zone="zone_1",
            reapplication_after_days=21,
            application_type="foliaire",
            application_requires_watering_after=False,
            application_post_watering_mm=0.0,
            application_irrigation_block_hours=24.0,
            application_irrigation_delay_minutes=0.0,
            application_irrigation_mode="suggestion",
            application_label_notes="Ne pas arroser pendant 24h",
            note="Application test",
        )

        self.assertEqual(item["application_type"], "foliaire")
        self.assertFalse(item["application_requires_watering_after"])
        self.assertEqual(item["application_post_watering_mm"], 0.0)
        self.assertEqual(item["application_irrigation_block_hours"], 24.0)
        self.assertEqual(item["application_irrigation_delay_minutes"], 0.0)
        self.assertEqual(item["application_irrigation_mode"], "suggestion")
        self.assertEqual(item["application_label_notes"], "Ne pas arroser pendant 24h")
        self.assertIn("declared_at", item)
        self.assertIsNotNone(item["declared_at"])

    def test_record_user_action_is_persisted(self) -> None:
        brain = GazonBrain()
        summary = brain.record_user_action(
            action="Lancer le plan maintenant",
            state="ok",
            reason="Plan lancé immédiatement.",
            plan_type="multi_zone",
            zone_count=2,
            passages=1,
        )

        self.assertEqual(summary["state"], "ok")
        self.assertEqual(brain.memory["derniere_action_utilisateur"]["action"], "Lancer le plan maintenant")
        self.assertEqual(brain.memory["derniere_action_utilisateur"]["plan_type"], "multi_zone")

        reloaded = GazonBrain()
        reloaded.load_state(brain.dump_state())
        self.assertEqual(reloaded.memory["derniere_action_utilisateur"]["state"], "ok")
        self.assertEqual(reloaded.memory["derniere_action_utilisateur"]["zone_count"], 2)

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
            pluie_demain_source="meteo_forecast",
            weather_profile={},
        )
        reloaded = GazonBrain()
        reloaded.load_state(brain.dump_state())

        self.assertGreater(snapshot["bilan_hydrique_mm"], 12.0)
        self.assertEqual(snapshot["soil_balance"]["reserve_mm"], reloaded.soil_balance["reserve_mm"])
        self.assertEqual(reloaded.soil_balance["reserve_mm"], brain.soil_balance["reserve_mm"])
        self.assertIsNotNone(brain.last_result)
        self.assertEqual(brain.last_result.phase_active, snapshot["phase_active"])
        self.assertEqual(brain.last_result.extra["configuration"]["type_sol"], "limoneux")
        self.assertEqual(brain.last_result.extra["pluie_demain_source"], "meteo_forecast")
