from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
import importlib
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_module(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module

def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


def _install_homeassistant_stubs() -> None:
    _ensure_module("homeassistant")
    util_mod = _ensure_module("homeassistant.util")
    dt_mod = _ensure_module("homeassistant.util.dt")
    if not hasattr(dt_mod, "now"):
        dt_mod.now = lambda: datetime.now(timezone.utc)
    if not hasattr(dt_mod, "utcnow"):
        dt_mod.utcnow = lambda: datetime.now(timezone.utc)
    if not hasattr(util_mod, "dt"):
        util_mod.dt = dt_mod


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_stubs()

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
            application_type="sol",
            application_requires_watering_after=True,
            application_post_watering_mm=1.0,
            application_irrigation_block_hours=0.0,
            application_irrigation_delay_minutes=0.0,
            application_irrigation_mode="auto",
            application_label_notes="Arrosage léger après application",
            note="Produit test",
        )
        brain.declare_intervention(
            "Biostimulant",
            date_action=date(2026, 3, 18),
            produit_id="humuslight",
            zone="Gazon complet",
            note="Application test",
            application_type="sol",
            application_requires_watering_after=True,
            application_post_watering_mm=1.0,
            application_irrigation_block_hours=0.0,
            application_irrigation_delay_minutes=0.0,
            application_irrigation_mode="auto",
            application_label_notes="Arrosage léger après application",
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
            pluie_demain_source="meteo_forecast",
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
            pluie_demain_source="meteo_forecast",
            weather_profile={},
        )

        self.assertEqual(first_snapshot["bilan_hydrique_mm"], second_snapshot["bilan_hydrique_mm"])
        self.assertEqual(reloaded.memory["catalogue_produits"], 1)
        self.assertEqual(reloaded.memory["derniere_application"]["produit_id"], "humuslight")
        self.assertEqual(reloaded.memory["derniere_application"]["application_type"], "sol")
        self.assertTrue(reloaded.memory["application_requires_watering_after"])
        self.assertEqual(reloaded.memory["application_post_watering_mm"], 1.0)
        self.assertEqual(reloaded.memory["application_irrigation_mode"], "auto")
        self.assertEqual(reloaded.memory["prochaine_reapplication"], "2026-04-12")


class LeCliquetDeTemperatureSurvitAuDisqueTests(unittest.TestCase):
    """0.87.0 — le maximum du jour retenu pour la hauteur de tonte traverse le disque.

    La mémoire est RECONSTRUITE à chaque cycle (`compute_memory`) : une clé qui n'est pas
    réinjectée depuis le snapshot meurt au cycle suivant, et une clé qui n'atteint pas
    `dump_state` meurt au redémarrage — or les redémarrages sont fréquents sur cette installation.
    On suit donc la VALEUR : décision → cerveau → disque → cerveau neuf → décision suivante.
    """

    def _cycle(self, brain, heure: int, prevision: float, mesure: float):
        return brain.compute_snapshot(
            today=date(2026, 4, 15), hour_of_day=heure, temperature=mesure,
            forecast_temperature_today=prevision, pluie_24h=0.0, pluie_demain=0.0,
            humidite=60.0, type_sol="limoneux", etp_capteur=2.0, humidite_sol=None, vent=None,
            rosee=None, hauteur_gazon=None, retour_arrosage=None, pluie_source="capteur_pluie_24h",
            pluie_demain_source="meteo_forecast", weather_profile={},
        )

    def test_le_soir_apres_redemarrage_la_journee_reste_douce(self) -> None:
        brain = GazonBrain()
        midi = self._cycle(brain, heure=14, prevision=14.0, mesure=13.0)
        self.assertEqual(midi["hauteur_tonte_temperature_jour"], {"date": "2026-04-15", "max": 14.0})
        self.assertEqual(brain.memory["hauteur_tonte_temperature_jour"]["max"], 14.0)

        relu = GazonBrain()
        relu.load_state(brain.dump_state())
        self.assertEqual(relu.memory.get("hauteur_tonte_temperature_jour"), {"date": "2026-04-15", "max": 14.0},
                         "le cliquet meurt au redémarrage")
        # 23 h : la prévision « du jour » ne couvre plus que les heures restantes.
        soir = self._cycle(relu, heure=23, prevision=7.5, mesure=7.0)
        self.assertNotIn("froide", soir["hauteur_tonte_motif"])
        self.assertEqual(relu.memory["hauteur_tonte_temperature_jour"]["max"], 14.0)
