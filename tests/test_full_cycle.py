from __future__ import annotations

import unittest
from datetime import date
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

GazonBrain = importlib.import_module("custom_components.gazon_intelligent.gazon_brain").GazonBrain


class FullCycleTests(unittest.TestCase):
    def test_brain_survives_restarts_with_persisted_balance_and_products(self) -> None:
        brain = GazonBrain()
        brain.register_product(
            "humuslight",
            "Humuslight",
            "Biostimulant",
            dose_conseillee="1.3 L / 350 m²",
            reapplication_after_days=25,
            delai_avant_tonte_jours=2,
            phase_compatible="Sursemis, Reprise",
            note="Produit test",
        )
        brain.declare_intervention(
            "Biostimulant",
            date_action=date(2026, 3, 18),
            produit_id="humuslight",
            zone="Gazon complet",
            note="Application test",
        )
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

        first_snapshot = brain.compute_snapshot(
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
        second_snapshot = reloaded.compute_snapshot(
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

        self.assertEqual(first_snapshot["bilan_hydrique_mm"], second_snapshot["bilan_hydrique_mm"])
        self.assertEqual(reloaded.memory["catalogue_produits"], 1)
        self.assertEqual(reloaded.memory["derniere_application"]["produit_id"], "humuslight")
        self.assertEqual(reloaded.memory["prochaine_reapplication"], "2026-04-12")
