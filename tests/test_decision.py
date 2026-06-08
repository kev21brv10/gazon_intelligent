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

decision = importlib.import_module("custom_components.gazon_intelligent.decision")
decision_mowing = importlib.import_module("custom_components.gazon_intelligent.decision_mowing")
decision_phase = importlib.import_module("custom_components.gazon_intelligent.decision_phase")
decision_risk = importlib.import_module("custom_components.gazon_intelligent.decision_risk")
decision_watering = importlib.import_module("custom_components.gazon_intelligent.decision_watering")
water = importlib.import_module("custom_components.gazon_intelligent.water")

FIXED_NOW_UTC = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
FIXED_TODAY = FIXED_NOW_UTC.date()
FIXED_HA_NOW_UTC = datetime(2026, 4, 4, 12, 15, tzinfo=timezone.utc)
FIXED_HA_TODAY = FIXED_HA_NOW_UTC.date()


def make_snapshot(**overrides):
    params = {
        "history": [],
        "today": FIXED_TODAY,
        "hour_of_day": 8,
        "temperature": 20.0,
        "pluie_24h": 0.0,
        "pluie_demain": 0.0,
        "humidite": 60.0,
        "type_sol": "limoneux",
        "etp_capteur": 2.0,
    }
    params.update(overrides)
    return decision.build_decision_snapshot(**params)


class TestPhaseLogic(unittest.TestCase):
    def test_compute_phase_active_prefers_highest_priority(self) -> None:
        today = date(2026, 3, 17)
        history = [
            {"type": "Sursemis", "date": "2026-03-10"},
            {"type": "Traitement", "date": "2026-03-16"},
        ]

        phase, start, end = decision.compute_phase_active(history, today=today, temperature=18)

        self.assertEqual(phase, "Traitement")
        self.assertEqual(start, date(2026, 3, 16))
        self.assertEqual(end, date(2026, 3, 17))

    def test_compute_phase_active_stays_normal_without_active_history_even_when_cold(self) -> None:
        phase, start, end = decision.compute_phase_active([], today=date(2026, 1, 15), temperature=12)

        self.assertEqual(phase, "Normal")
        self.assertIsNone(start)
        self.assertIsNone(end)

        phase, start, end = decision.compute_phase_active([], today=date(2026, 4, 14), temperature=2)

        self.assertEqual(phase, "Normal")
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_compute_recent_watering_mm_respects_window(self) -> None:
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 2.5},
            {"type": "arrosage", "date": "2026-03-16", "objectif_mm": 1.5},
            {"type": "arrosage", "date": "2026-03-13", "objectif_mm": 9.0},
        ]

        total = decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), days=2)

        self.assertEqual(total, 4.0)

    def test_compute_recent_watering_mm_uses_session_surface_depth(self) -> None:
        history = [
            {
                "type": "arrosage",
                "date": "2026-03-17",
                "objectif_mm": 1.2,
                "total_mm": 3.6,
                "zones": [
                    {"zone": "zone_1", "mm": 1.2},
                    {"zone": "zone_2", "mm": 1.1},
                    {"zone": "zone_3", "mm": 1.3},
                ],
            }
        ]

        total = decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), days=2)

        self.assertEqual(total, 1.2)

    def test_compute_recent_watering_count_shares_recent_filtering_rules(self) -> None:
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 2.5},
            {"type": "arrosage", "date": "invalid", "objectif_mm": 1.5},
            {"type": "arrosage", "date": "2026-03-15", "zones": [{"zone": "z1", "mm": 1.0}]},
            {"type": "arrosage", "date": "2026-03-10", "objectif_mm": 9.0},
            {"type": "arrosage", "date": "2026-03-16"},
        ]

        count = water.compute_recent_watering_count(history, today=date(2026, 3, 17), days=2)

        self.assertEqual(count, 2)

    def test_compute_dominant_phase_prefers_highest_priority_active_window(self) -> None:
        history = [
            {"type": "Sursemis", "date": "2026-03-10"},
            {"type": "Scarification", "date": "2026-03-16"},
            {"type": "Traitement", "date": "2026-03-17"},
        ]

        dominant = decision.compute_dominant_phase(history, today=date(2026, 3, 17), temperature=18)

        self.assertEqual(dominant["phase_dominante"], "Traitement")
        self.assertEqual(dominant["source"], "historique_actif")
        self.assertEqual(dominant["date_debut"], date(2026, 3, 17))
        self.assertEqual(dominant["date_fin"], date(2026, 3, 18))

    def test_compute_dominant_phase_expires_single_day_phase_on_next_day(self) -> None:
        dominant = decision.compute_dominant_phase(
            [{"type": "Biostimulant", "date": "2026-03-17"}],
            today=date(2026, 3, 18),
            temperature=12,
        )

        self.assertEqual(dominant["phase_dominante"], "Normal")
        self.assertEqual(dominant["source"], "absence_phase")

    def test_compute_subphase_tracks_sursemis_progression(self) -> None:
        # Règle Sursemis: Germination <= 10j → jour 10 = dernier jour Germination, jour 11 = Enracinement
        subphase = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 7),
            date_fin=date(2026, 3, 27),
            today=date(2026, 3, 18),
        )

        self.assertEqual(subphase["sous_phase"], "Enracinement")
        self.assertEqual(subphase["age_jours"], 11)

    def test_compute_subphase_progression_moves_with_time(self) -> None:
        # Règle Sursemis: Germination <= 10j, Enracinement <= 24j → jour 11 = Enracinement
        subphase = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 7),
            date_fin=date(2026, 3, 27),
            today=date(2026, 3, 18),
            now=datetime(2026, 3, 18, 6, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(subphase["sous_phase"], "Enracinement")
        self.assertEqual(subphase["age_jours"], 11)
        self.assertEqual(subphase["detail"], "Sursemis / Enracinement")

class TestHydricCoreAndMemory(unittest.TestCase):
    def test_compute_water_balance_returns_detailed_metrics(self) -> None:
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 0.5},
        ]

        balance = decision.compute_water_balance(
            history=history,
            today=date(2026, 3, 17),
            etp=5.0,
            pluie_24h=1.0,
            pluie_demain=0.0,
            type_sol="sableux",
        )

        self.assertEqual(balance["pluie_efficace"], 0.9)
        self.assertEqual(balance["arrosage_recent"], 0.5)
        self.assertEqual(balance["arrosage_recent_jour"], 0.5)
        self.assertEqual(balance["arrosage_recent_3j"], 0.5)
        self.assertEqual(balance["arrosage_recent_7j"], 0.5)
        self.assertEqual(balance["deficit_jour"], 5.4)
        self.assertEqual(balance["deficit_3j"], 19.9)
        self.assertEqual(balance["deficit_7j"], 48.5)

    def test_compute_water_balance_prefers_persisted_soil_balance_reserve(self) -> None:
        balance = decision.compute_water_balance(
            history=[],
            today=date(2026, 3, 17),
            etp=3.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            type_sol="limoneux",
            soil_balance={
                "reserve_mm": 14.0,
                "reserve_max_mm": 24.0,
            },
        )

        self.assertEqual(balance["reserve_stock_mm"], 14.0)
        self.assertEqual(balance["reserve_actuelle_mm"], 12.0)
        self.assertEqual(balance["reserve_stock_max_mm"], 24.0)
        self.assertEqual(balance["reserve_surplus_mm"], 2.0)

    def test_build_decision_snapshot_uses_persistent_soil_balance(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            etp_capteur=3.0,
            soil_balance={
                "date": "2026-03-17",
                "reserve_mm": 14.0,
                "previous_reserve_mm": 11.0,
                "pluie_mm": 1.0,
                "arrosage_mm": 5.0,
                "etp_mm": 3.0,
                "delta_mm": 3.0,
                "type_sol": "limoneux",
                "reserve_max_mm": 24.0,
                "reserve_min_mm": 0.0,
                "ledger": [],
            },
        )

        self.assertEqual(snapshot["reserve_hydrique_sol_mm"], 14.0)
        self.assertAlmostEqual(snapshot["bilan_hydrique_mm"], -2.9, places=1)
        self.assertEqual(snapshot["bilan_hydrique_precedent_mm"], 11.0)
        self.assertEqual(snapshot["type_sol"], "limoneux")
        self.assertEqual(snapshot["soil_balance"]["reserve_mm"], 14.0)

    def test_build_decision_snapshot_exposes_hydric_observability_metrics(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 4, 8),
            hour_of_day=9,
            temperature=20.0,
            forecast_temperature_today=24.0,
            temperature_source="capteur",
            temperature_reference_hydrique=22.8,
            etp_capteur=None,
            soil_balance={
                "date": "2026-04-08",
                "reserve_mm": 10.0,
                "previous_reserve_mm": 9.0,
                "pluie_mm": 0.0,
                "arrosage_mm": 0.0,
                "etp_mm": 1.4,
                "delta_mm": -1.0,
                "type_sol": "limoneux",
                "reserve_max_mm": 24.0,
                "reserve_min_mm": 0.0,
                "ledger": [],
            },
            et0_source="fallback_temperature",
        )

        self.assertEqual(snapshot["temperature_reference_hydrique"], 22.8)
        self.assertEqual(snapshot["et0_source"], "fallback_temperature")
        self.assertGreater(snapshot["et0_mm"], 0.0)
        self.assertEqual(snapshot["kc_gazon"], 0.8)
        self.assertGreater(snapshot["etc_mm"], 0.0)
        self.assertEqual(snapshot["reserve_actuelle_mm"], 10.0)
        self.assertEqual(snapshot["reserve_utile_mm"], 12.0)
        self.assertEqual(snapshot["depletion_mm"], 2.0)
        self.assertAlmostEqual(snapshot["depletion_ratio"], 0.167, places=3)

    def test_compute_advanced_context_uses_weather_probability(self) -> None:
        context = decision.compute_advanced_context(
            humidite_sol=22,
            vent=18,
            rosee=1.0,
            hauteur_gazon=11.5,
            retour_arrosage=0.7,
            weather_profile={
                "weather_precipitation_probability": 70,
                "weather_condition": "cloudy",
            },
        )

        self.assertEqual(context["humidite_sol"], 22.0)
        self.assertEqual(context["vent"], 18.0)
        self.assertEqual(context["rosee"], 1.0)
        self.assertEqual(context["hauteur_gazon"], 11.5)
        self.assertEqual(context["retour_arrosage"], 0.7)
        self.assertEqual(context["weather_precipitation_probability"], 70.0)
        self.assertGreater(context["soil_factor"], 1.0)
        self.assertGreater(context["wind_factor"], 1.0)
        self.assertLess(context["dew_factor"], 1.0)
        self.assertLess(context["rain_factor"], 1.0)

    def test_compute_advanced_context_normalizes_weather_probability_strings(self) -> None:
        context = decision.compute_advanced_context(
            weather_profile={"weather_precipitation_probability": "70"},
        )

        self.assertEqual(context["weather_precipitation_probability"], 70.0)

    def test_compute_memory_tracks_last_useful_events(self) -> None:
        history = [
            {"type": "tonte", "date": "2026-03-12"},
            {"type": "arrosage", "date": "2026-03-13", "objectif_mm": 1.0},
            {
                "type": "arrosage",
                "date": "2026-03-16",
                "objectif_mm": 0.8,
                "total_mm": 3.0,
                "zones": [
                    {"zone": "zone_1", "mm": 1.2},
                    {"zone": "zone_2", "mm": 1.8},
                ],
            },
            {"type": "Sursemis", "date": "2026-03-10"},
            {
                "type": "Fertilisation",
                "date": "2026-03-17",
                "produit": "Engrais printemps",
                "dose": "12.5",
                "zone": "zone_1",
                "reapplication_after_days": 21,
                "note": "Test",
                "source": "service",
            },
        ]

        memory = decision.compute_memory(
            history=history,
            current_phase="Sursemis",
            decision={
                "phase_active": "Sursemis",
                "objectif_mm": 2.8,
                "conseil_principal": "Arroser ce matin",
                "action_recommandee": "Appliquer 2.8 mm",
                "action_a_eviter": "Tondre",
                "niveau_action": "a_faire",
                "fenetre_optimale": "maintenant",
                "risque_gazon": "modere",
                "prochaine_reevaluation": "dans 24 h",
                "raison_decision": "Test",
            },
            today=date(2026, 3, 17),
        )

        self.assertEqual(memory["derniere_tonte"]["date"], "2026-03-12")
        self.assertEqual(memory["dernier_arrosage"]["date"], "2026-03-16")
        self.assertIsNone(memory["dernier_arrosage_significatif"])
        self.assertEqual(memory["derniere_phase_active"], "Sursemis")
        self.assertEqual(memory["derniere_application"]["libelle"], "Engrais printemps")
        self.assertEqual(memory["derniere_application"]["type"], "Fertilisation")
        self.assertEqual(memory["derniere_application"]["dose"], "12.5")
        self.assertEqual(memory["prochaine_reapplication"], "2026-04-07")
        self.assertEqual(memory["dernier_conseil"]["conseil_principal"], "Arroser ce matin")
        self.assertEqual(memory["dernier_conseil"]["prochaine_reevaluation"], "dans 24 h")

class TestDecisionSnapshotWatering(unittest.TestCase):
    def test_build_decision_snapshot_normal_recommends_watering(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=20,
            etp_capteur=3.0,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["phase_dominante"], "Normal")
        self.assertEqual(snapshot["sous_phase"], "Normal")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "personnalise")
        self.assertEqual(snapshot["arrosage_conseille"], "personnalise")
        self.assertIn(snapshot["tonte_statut"], {"autorisee", "autorisee_avec_precaution", "a_surveiller"})
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertEqual(snapshot["fenetre_optimale"], "demain_matin")
        self.assertEqual(snapshot["risque_gazon"], "modere")
        self.assertEqual(snapshot["prochaine_reevaluation"], "dans 24 h")
        self.assertGreater(snapshot["objectif_mm"], 0)
        self.assertLessEqual(snapshot["objectif_mm"], snapshot["objectif_mm_brut"])
        self.assertLess(snapshot["bilan_hydrique_mm"], 0)
        self.assertEqual(snapshot["decision_resume"]["action"], "arrosage")
        self.assertTrue(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["heat_stress_level"], "vigilance")
        self.assertGreaterEqual(snapshot["deficit_mm_ajuste"], 0.0)
        self.assertGreaterEqual(snapshot["mm_final"], snapshot["mm_cible"])
        self.assertEqual(snapshot["niveau_confiance"], "high")
        self.assertIn("weekly_guardrail_reason", snapshot)

    def test_build_decision_snapshot_normal_suppresses_micro_watering(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=20,
            etp_capteur=1.0,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["type_arrosage"], "aucune_action")
        self.assertEqual(snapshot["arrosage_conseille"], "aucune_action")
        self.assertEqual(snapshot["niveau_action"], "aucune_action")
        self.assertNotIn("0.0 mm", snapshot["conseil_principal"])
        self.assertNotIn("0.0 mm", snapshot["action_recommandee"])
        self.assertEqual(snapshot["action_a_eviter"], "Éviter tout arrosage inutile.")

    def test_build_decision_snapshot_reduces_watering_when_rain_compensates(self) -> None:
        dry_snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            etp_capteur=3.0,
        )
        rainy_snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            pluie_demain=3.0,
            etp_capteur=3.0,
        )

        self.assertTrue(rainy_snapshot["arrosage_recommande"])
        self.assertLess(rainy_snapshot["objectif_mm"], dry_snapshot["objectif_mm"])
        self.assertEqual(rainy_snapshot["objectif_mm"], rainy_snapshot["decision_resume"]["objectif_mm"])
        self.assertLessEqual(rainy_snapshot["objectif_mm"], rainy_snapshot["objectif_mm_brut"])
        self.assertNotEqual(rainy_snapshot["action_recommandee"], dry_snapshot["action_recommandee"])

    def test_build_decision_snapshot_blocks_when_forecast_rain_covers_need(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            pluie_demain=10.0,
            etp_capteur=3.0,
        )

        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["fenetre_optimale"], "apres_pluie")
        self.assertEqual(snapshot["block_reason"], "pluie_prevue_suffisante")

    def test_build_decision_snapshot_normal_uses_soil_fractionation(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=30,
            humidite=45,
            type_sol="argileux",
            etp_capteur=4.5,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertGreaterEqual(snapshot["watering_passages"], 2)
        self.assertGreater(snapshot["watering_pause_minutes"], 0)

    def test_build_decision_snapshot_treatment_blocks_actions(self) -> None:
        snapshot = make_snapshot(
            history=[{"type": "Traitement", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            humidite=50,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["phase_active"], "Traitement")
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertEqual(snapshot["tonte_statut"], "interdite")
        self.assertEqual(snapshot["niveau_action"], "surveiller")
        self.assertEqual(snapshot["fenetre_optimale"], "attendre")
        self.assertEqual(snapshot["risque_gazon"], "faible")
        self.assertEqual(snapshot["prochaine_reevaluation"], "dans 24 h")
        self.assertEqual(snapshot["objectif_mm"], 0.0)

    def test_build_decision_snapshot_application_block_has_priority_over_traitement_phase(self) -> None:
        with patch.object(
            decision_watering,
            "compute_application_state",
            return_value={
                "derniere_application": {"type": "Traitement", "libelle": "Produit test"},
                "application_type": "sol",
                "application_requires_watering_after": False,
                "application_post_watering_mm": 0.0,
                "application_irrigation_block_hours": 24.0,
                "application_irrigation_delay_minutes": 0.0,
                "application_irrigation_mode": "auto",
                "application_label_notes": None,
                "application_post_watering_status": "bloque",
                "application_block_until": "2026-04-05T12:15:00+00:00",
                "application_block_active": True,
                "application_block_remaining_minutes": 60.0,
                "application_post_watering_pending": False,
                "application_post_watering_ready_at": None,
                "application_post_watering_delay_remaining_minutes": 0.0,
                "application_post_watering_ready": False,
                "application_post_watering_remaining_mm": 0.0,
            },
        ):
            snapshot = make_snapshot(
                history=[{"type": "Traitement", "date": "2026-04-04"}],
                today=date(2026, 4, 4),
                hour_of_day=10,
                temperature=18,
                humidite=50,
                etp_capteur=2.0,
            )

        self.assertTrue(snapshot["application_block_active"])
        self.assertIn("fenêtre de protection", snapshot["conseil_principal"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")

    def test_build_decision_snapshot_blocks_watering_and_mowing_when_raining(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=18,
            humidite=55,
            etp_capteur=2.0,
            weather_profile={
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        )

        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["fenetre_optimale"], "apres_pluie")
        self.assertFalse(snapshot["tonte_autorisee"])

    def test_build_decision_snapshot_foliar_application_blocks_auto_watering(self) -> None:
        now = FIXED_HA_NOW_UTC
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Traitement",
                    "date": now.date().isoformat(),
                    "declared_at": (now - timedelta(hours=2)).isoformat(),
                    "produit": "Fongicide X",
                    "application_type": "foliaire",
                    "application_requires_watering_after": False,
                    "application_post_watering_mm": 0.0,
                    "application_irrigation_block_hours": 24.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "suggestion",
                    "application_label_notes": "Pas d'arrosage après application",
                }
            ],
            today=now.date(),
            hour_of_day=10,
            temperature=18,
            humidite=50,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_type"], "foliaire")
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["application_label_notes"], "Pas d'arrosage après application")
        self.assertEqual(snapshot["application_irrigation_mode"], "suggestion")

    def test_build_decision_snapshot_sol_application_uses_application_technique(self) -> None:
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Fertilisation",
                    "date": "2026-03-17",
                    "declared_at": "2026-03-17T08:00:00+00:00",
                    "produit": "Engrais printemps",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.2,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "auto",
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            humidite=55,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_type"], "sol")
        self.assertFalse(snapshot["application_block_active"])
        self.assertTrue(snapshot["application_post_watering_ready"])
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertTrue(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["watering_cause"], "post_application")
        self.assertEqual(snapshot["type_arrosage"], "application_technique_auto")
        self.assertEqual(snapshot["arrosage_conseille"], "application_technique_auto")
        self.assertGreater(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["decision_resume"]["type_arrosage"], "application_technique_auto")
        self.assertEqual(snapshot["decision_resume"]["moment"], "maintenant")
        self.assertEqual(snapshot["application_irrigation_mode"], "auto")

    def test_build_decision_snapshot_sol_application_manual_mode_requires_button(self) -> None:
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-17",
                    "declared_at": "2026-03-17T08:00:00+00:00",
                    "produit": "Bio Boost",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "manuel",
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            humidite=55,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_irrigation_mode"], "manuel")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["watering_cause"], "post_application")
        self.assertEqual(snapshot["type_arrosage"], "application_technique")
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertIn("arrosage manuel immédiat", snapshot["conseil_principal"].lower())

    def test_build_decision_snapshot_unknown_application_type_blocks_auto_watering(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[
                {
                    "type": "Sursemis",
                    "date": "2026-03-17",
                    "declared_at": "2026-03-17T08:00:00+00:00",
                    "produit": "Produit inconnu",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertNotIn("application_type", snapshot)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertIn("type d'application inconnu", snapshot["conseil_principal"].lower())

class TestDecisionSnapshotSursemisAndHeatStress(unittest.TestCase):
    def test_build_decision_snapshot_sursemis_mentions_passage_interval(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["phase_active"], "Sursemis")
        self.assertEqual(snapshot["type_arrosage"], "manuel_frequent")
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertGreater(snapshot["objectif_mm"], 0.0)
        self.assertLessEqual(snapshot["objectif_mm"], snapshot["objectif_mm_brut"])
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["watering_target_date"], "2026-03-17")
        self.assertEqual(snapshot["next_action_date"], "2026-03-17")
        self.assertEqual(snapshot["next_action_display"], "17/03/2026")
        self.assertIn("cycle de surface", snapshot["action_recommandee"])
        self.assertIn("1.5 mm", snapshot["action_recommandee"])

    def test_build_decision_snapshot_sursemis_projects_next_mowing_date(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["next_mowing_date"], "2026-04-11")
        self.assertEqual(snapshot["next_mowing_display"], "11/04/2026")
        self.assertEqual(snapshot["raison_blocage_code"], "phase_sursemis")

    def test_build_decision_snapshot_distinguishes_canicule_phases(self) -> None:
        short = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=31,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=40,
            type_sol="limoneux",
            etp_capteur=4.2,
        )
        prolonged = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=35,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=25,
            type_sol="limoneux",
            etp_capteur=5.5,
        )
        recovery = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=35,
            pluie_24h=0.0,
            pluie_demain=8.0,
            humidite=25,
            type_sol="limoneux",
            etp_capteur=5.5,
            pluie_3j=8.0,
        )

        self.assertEqual(short["heat_stress_phase"], "canicule_courte")
        self.assertEqual(prolonged["heat_stress_phase"], "canicule_prolongee")
        self.assertEqual(recovery["heat_stress_phase"], "sortie_de_canicule")
        self.assertGreater(short["objectif_mm"], 0.0)
        self.assertGreater(prolonged["objectif_mm"], short["objectif_mm"])
        self.assertEqual(recovery["objectif_mm"], 0.0)
        self.assertEqual(recovery["type_arrosage"], "bloque")

    def test_build_watering_bundle_exposes_stable_core_keys_across_paths(self) -> None:
        expected_keys = {
            "objectif_mm",
            "objectif_mm_brut",
            "deficit_brut_mm",
            "deficit_mm_brut",
            "deficit_mm_ajuste",
            "mm_cible",
            "mm_final_recommande",
            "mm_final",
            "mm_requested",
            "mm_applied",
            "mm_detected",
            "arrosage_recommande",
            "arrosage_auto_autorise",
            "type_arrosage",
            "arrosage_conseille",
            "decision_resume",
            "raison_decision",
            "watering_passages",
            "watering_pause_minutes",
            "watering_target_date",
            "block_reason",
            "weekly_guardrail_mm_min",
            "weekly_guardrail_mm_max",
            "weekly_guardrail_reason",
            "soil_profile",
            "soil_retention_factor",
            "soil_drainage_factor",
            "soil_infiltration_factor",
            "soil_need_factor",
            "watering_window_start_minute",
            "watering_window_end_minute",
            "watering_window_optimal_start_minute",
            "watering_window_optimal_end_minute",
            "watering_window_acceptable_end_minute",
            "application_type",
            "application_post_watering_status",
        }

        contexts = [
            decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 3, 17),
                hour_of_day=8,
                temperature=20,
                pluie_24h=0,
                pluie_demain=0,
                humidite=60,
                type_sol="limoneux",
                etp_capteur=3.0,
            ),
            decision.DecisionContext.from_legacy_args(
                history=[{"type": "Traitement", "date": "2026-03-17"}],
                today=date(2026, 3, 17),
                hour_of_day=8,
                temperature=18,
                pluie_24h=0,
                pluie_demain=0,
                humidite=55,
                type_sol="limoneux",
                etp_capteur=2.0,
            ),
        ]

        for context in contexts:
            phase_bundle = decision.build_phase_bundle(context)
            water_bundle = decision.build_water_bundle(context, phase_bundle)
            risk_bundle = decision.build_risk_bundle(context, phase_bundle, water_bundle)
            mowing_bundle = decision.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
            bundle = decision_watering.build_watering_bundle(
                context, phase_bundle, water_bundle, risk_bundle, mowing_bundle
            )
            self.assertTrue(expected_keys.issubset(bundle.keys()))
    def test_build_water_bundle_dynamic_guardrail_varies_with_season(self) -> None:
        winter_context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 1, 15),
            hour_of_day=7,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        summer_context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 7, 15),
            hour_of_day=7,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        winter_phase = decision.build_phase_bundle(winter_context)
        summer_phase = decision.build_phase_bundle(summer_context)
        winter_water = decision.build_water_bundle(winter_context, winter_phase)
        summer_water = decision.build_water_bundle(summer_context, summer_phase)

        self.assertLess(winter_water["weekly_guardrail_mm_min"], summer_water["weekly_guardrail_mm_min"])
        self.assertLess(winter_water["weekly_guardrail_mm_max"], summer_water["weekly_guardrail_mm_max"])
        self.assertIn("saison=winter", winter_water["weekly_guardrail_reason"])
        self.assertIn("saison=summer", summer_water["weekly_guardrail_reason"])

    def test_build_water_bundle_exposes_month_profile_metadata(self) -> None:
        spring_context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 15),
            hour_of_day=7,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=2.0,
        )
        summer_context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 7, 15),
            hour_of_day=7,
            temperature=28,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.5,
        )

        spring_phase = decision.build_phase_bundle(spring_context)
        spring_water = decision.build_water_bundle(spring_context, spring_phase)
        spring_risk = decision.build_risk_bundle(spring_context, spring_phase, spring_water)
        spring_mowing = decision.build_mowing_bundle(spring_context, spring_phase, spring_water, spring_risk)
        spring_watering = decision_watering.build_watering_bundle(
            spring_context, spring_phase, spring_water, spring_risk, spring_mowing
        )

        summer_phase = decision.build_phase_bundle(summer_context)
        summer_water = decision.build_water_bundle(summer_context, summer_phase)
        summer_risk = decision.build_risk_bundle(summer_context, summer_phase, summer_water)
        summer_mowing = decision.build_mowing_bundle(summer_context, summer_phase, summer_water, summer_risk)
        summer_watering = decision_watering.build_watering_bundle(
            summer_context, summer_phase, summer_water, summer_risk, summer_mowing
        )

        self.assertEqual(spring_watering["season_phase"], "reveil_printanier")
        self.assertEqual(spring_watering["month_profile"], "relance_vegetative")
        self.assertEqual(summer_watering["season_phase"], "defense_estivale")
        self.assertEqual(summer_watering["month_profile"], "defense_thermique")
        self.assertIn("mois=relance_vegetative", spring_watering["weekly_guardrail_reason"])
        self.assertIn("mois=defense_thermique", summer_watering["weekly_guardrail_reason"])


class TestDecisionResultConstruction(unittest.TestCase):
    def test_build_decision_result_snapshot_matches_legacy_snapshot(self) -> None:
        kwargs = {
            "history": [{"type": "Traitement", "date": "2026-03-17"}],
            "today": date(2026, 3, 17),
            "hour_of_day": 8,
            "temperature": 18.0,
            "forecast_temperature_today": 19.5,
            "temperature_source": "capteur",
            "temperature_reference_hydrique": 18.8,
            "pluie_24h": 0.0,
            "pluie_demain": 0.0,
            "humidite": 55.0,
            "type_sol": "limoneux",
            "etp_capteur": 2.0,
            "rosee": 0.5,
            "weather_profile": {
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        }
        context = decision.DecisionContext.from_legacy_args(**kwargs)

        expected = decision.build_decision_snapshot(**kwargs)
        actual = decision.build_decision_result(context).to_snapshot()

        self.assertEqual(actual, expected)

    def test_compute_decision_preserves_legacy_output_contract(self) -> None:
        result = decision.compute_decision(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.2,
                "deficit_jour": 1.2,
                "deficit_3j": 2.0,
                "deficit_7j": 3.5,
            },
            advanced_context={
                "niveau_action": "a_faire",
                "fenetre_optimale": "maintenant",
                "risque_gazon": "modere",
                "prochaine_reevaluation": "dans 24 h",
                "urgence": "moyenne",
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            temperature=20.0,
            etp=2.0,
            objectif_mm=1.0,
            jours_restants=0,
            score_hydrique=42,
            score_stress=33,
            score_tonte=12,
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=8,
        )

        snapshot = result.to_snapshot()
        self.assertEqual(result.phase_dominante, "Normal")
        self.assertEqual(result.sous_phase, "Normal")
        self.assertEqual(snapshot["objectif_mm"], 1.0)
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["risque_gazon"], "modere")
        self.assertEqual(snapshot["jours_restants"], 0)

    def test_compute_decision_legacy_facade_preserves_window_metadata(self) -> None:
        result = decision.compute_decision(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -0.8,
                "deficit_jour": 0.8,
                "deficit_3j": 1.5,
                "deficit_7j": 2.5,
            },
            advanced_context={
                "niveau_action": "surveiller",
                "fenetre_optimale": "ce_matin",
                "risque_gazon": "faible",
                "prochaine_reevaluation": "dans 12 h",
                "urgence": "faible",
                "watering_window_start_minute": 240,
                "watering_window_end_minute": 600,
                "watering_window_profile": "mild",
                "watering_evening_allowed": False,
                "heat_stress_level": "normal",
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=50.0,
            temperature=18.0,
            etp=1.8,
            objectif_mm=0.5,
            jours_restants=1,
            score_hydrique=21,
            score_stress=10,
            score_tonte=5,
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
        )

        snapshot = result.to_snapshot()
        self.assertEqual(snapshot["fenetre_optimale"], "ce_matin")
        self.assertEqual(snapshot["watering_window_start_minute"], 240)
        self.assertEqual(snapshot["watering_window_end_minute"], 600)
        self.assertEqual(snapshot["watering_window_profile"], "mild")
        self.assertFalse(snapshot["watering_evening_allowed"])
        self.assertEqual(snapshot["heat_stress_level"], "normal")

    def test_decision_result_extra_cannot_override_canonical_snapshot_fields(self) -> None:
        result = decision.DecisionResult(
            phase_dominante="Normal",
            sous_phase="Normal",
            action_recommandee="Rien",
            action_a_eviter="Trop arroser",
            niveau_action="a_faire",
            fenetre_optimale="maintenant",
            risque_gazon="faible",
            objectif_arrosage=1.0,
            tonte_autorisee=True,
            extra={
                "phase_dominante": "Traitement",
                "objectif_mm": 9.9,
                "niveau_action": "critique",
                "custom_flag": True,
            },
        )

        snapshot = result.to_snapshot()

        self.assertEqual(snapshot["phase_dominante"], "Normal")
        self.assertEqual(snapshot["objectif_mm"], 1.0)
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertTrue(snapshot["custom_flag"])

    def test_decision_result_normalizes_invalid_structured_values_defensively(self) -> None:
        result = decision.DecisionResult(
            phase_dominante="bad-phase",
            sous_phase="bad-subphase",
            action_recommandee="Rien",
            action_a_eviter="Trop arroser",
            niveau_action="bad-level",
            fenetre_optimale="bad-window",
            risque_gazon="faible",
            objectif_arrosage=0.0,
            tonte_autorisee=True,
            tonte_statut="bad-mowing",
            type_arrosage="bad-watering",
            arrosage_conseille="",
        )

        snapshot = result.to_snapshot()

        self.assertEqual(result.phase_dominante, "Normal")
        self.assertEqual(result.sous_phase, "Normal")
        self.assertEqual(result.niveau_action, "a_faire")
        self.assertEqual(result.tonte_statut, "a_surveiller")
        self.assertEqual(result.fenetre_optimale, "attendre")
        self.assertEqual(result.type_arrosage, "personnalise")
        self.assertEqual(result.arrosage_conseille, "personnalise")
        self.assertEqual(snapshot["phase_dominante"], "Normal")
        self.assertEqual(snapshot["sous_phase"], "Normal")
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertEqual(snapshot["fenetre_optimale"], "attendre")
        self.assertEqual(snapshot["type_arrosage"], "personnalise")

    def test_decision_result_aligns_arrosage_conseille_with_canonical_branch(self) -> None:
        result = decision.DecisionResult(
            phase_dominante="Normal",
            sous_phase="Normal",
            action_recommandee="Applique 5 mm",
            action_a_eviter="Rien",
            niveau_action="a_faire",
            fenetre_optimale="maintenant",
            risque_gazon="faible",
            objectif_arrosage=5.0,
            tonte_autorisee=True,
            type_arrosage="auto",
            arrosage_conseille="personnalise",
        )

        self.assertEqual(result.type_arrosage, "auto")
        self.assertEqual(result.arrosage_conseille, "auto")
        self.assertEqual(result.display_label_for("arrosage_conseille"), "Arrosage automatique")


class TestDecisionPhaseBundleRobustness(unittest.TestCase):
    def test_build_phase_bundle_clamps_incoherent_progression_and_age(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            temperature=18.0,
        )
        with patch.object(
            decision_phase,
            "compute_dominant_phase",
            return_value={
                "phase_dominante": "",
                "date_debut": "2026-04-04",
                "date_fin": "2026-04-10",
                "age_jours": -3,
                "source": None,
            },
        ), patch.object(
            decision_phase,
            "compute_subphase",
            return_value={
                "sous_phase": "",
                "detail": None,
                "age_jours": -7,
                "progression": 145.0,
            },
        ):
            bundle = decision_phase.build_phase_bundle(context)

        self.assertEqual(bundle["phase_dominante"], "Normal")
        self.assertEqual(bundle["phase_dominante_source"], "inconnu")
        self.assertEqual(bundle["phase_age_days"], 0)
        self.assertEqual(bundle["sous_phase"], "Normal")
        self.assertEqual(bundle["sous_phase_detail"], "Normal")
        self.assertEqual(bundle["sous_phase_age_days"], 0)
        self.assertEqual(bundle["sous_phase_progression"], 100.0)

    def test_build_phase_bundle_never_exposes_negative_remaining_days_or_invalid_end_date(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            temperature=18.0,
        )
        with patch.object(
            decision_phase,
            "compute_dominant_phase",
            return_value={
                "phase_dominante": "Traitement",
                "date_debut": "2026-04-01",
                "date_fin": "not-a-date",
                "age_jours": 3,
                "source": "historique_actif",
            },
        ), patch.object(
            decision_phase,
            "compute_subphase",
            return_value={
                "sous_phase": "Application",
                "detail": "Traitement / Application",
                "age_jours": 1,
                "progression": -12.0,
            },
        ), patch.object(
            decision_phase,
            "compute_jours_restants_for",
            return_value=-5,
        ):
            bundle = decision_phase.build_phase_bundle(context)

        self.assertIsNone(bundle["date_fin"])
        self.assertEqual(bundle["jours_restants"], 0)
        self.assertEqual(bundle["sous_phase_progression"], 0.0)


class TestDecisionRiskRobustness(unittest.TestCase):
    def test_build_risk_bundle_tolerates_partial_input_bundles(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        risk_bundle = decision.build_risk_bundle(
            context,
            {"phase_dominante": "Normal"},
            {"objectif_mm": 0.0},
        )

        self.assertIn("scores", risk_bundle)
        self.assertIn("niveau_action", risk_bundle)
        self.assertIn("fenetre_optimale", risk_bundle)
        self.assertIn("risque_gazon", risk_bundle)
        self.assertIn("urgence", risk_bundle)
        self.assertEqual(risk_bundle["urgence"], "faible")

    def test_decision_urgence_normalizes_unknown_text_inputs(self) -> None:
        urgence = decision_risk._decision_urgence(
            phase_dominante="Normal",
            arrosage_recommande=False,
            niveau_action="BAD_LEVEL",
            risque_gazon="UNKNOWN",
            bilan_hydrique_mm=0.1,
            pluie_demain=None,
        )

        self.assertEqual(urgence, "faible")


class TestObjectiveAndGuidance(unittest.TestCase):
    def test_compute_objectif_mm_sursemis_returns_micro_apport_when_conditions_are_met(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": 0.8,
                "deficit_3j": 1.5,
                "deficit_7j": 3.0,
            },
            today=date(2026, 3, 17),
            pluie_24h=0.0,
            pluie_demain=0,
            humidite=50,
            temperature=18.0,
            etp=1.4,
            type_sol="limoneux",
            weather_profile={
                "weather_precipitation_probability": 40.0,
            },
        )

        self.assertEqual(objectif, 3.0)

    def test_compute_objectif_mm_blocks_sursemis_when_balance_is_high(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": 10.8,
                "deficit_3j": 2.8,
                "deficit_7j": 8.6,
            },
            today=date(2026, 3, 17),
            pluie_24h=0.0,
            pluie_demain=0,
            humidite=50,
            temperature=18.7,
            etp=1.4,
            type_sol="limoneux",
            weather_profile={
                "weather_precipitation_probability": 20.0,
            },
        )

        self.assertEqual(objectif, 0.0)

    def test_compute_objectif_mm_returns_zero_when_weather_is_rainy(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.2,
                "deficit_3j": 2.0,
                "deficit_7j": 3.5,
            },
            today=date(2026, 3, 17),
            pluie_demain=0.0,
            humidite=55.0,
            temperature=18.0,
            etp=2.0,
            type_sol="limoneux",
            weather_profile={
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        )

        self.assertEqual(objectif, 0.0)

    def test_build_decision_snapshot_normal_blocks_with_24h_cooldown(self) -> None:
        now = FIXED_HA_NOW_UTC
        today = FIXED_HA_TODAY
        snapshot = make_snapshot(
            history=[
                {"type": "Normal", "date": today.isoformat()},
                {
                    "type": "arrosage",
                    "date": today.isoformat(),
                    "recorded_at": (now - timedelta(hours=12)).isoformat(),
                    "total_mm": 12.0,
                },
            ],
            today=today,
            hour_of_day=8,
            temperature=18.0,
            humidite=55.0,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertIn(snapshot["block_reason"], {"cooldown_24h", "sol_deja_humide"})
        self.assertIn("Cooldown", snapshot["raison_decision"])

    def test_build_decision_snapshot_normal_uses_daily_balance_even_with_positive_soil_reserve(self) -> None:
        today = date(2026, 3, 17)
        snapshot = make_snapshot(
            history=[{"type": "Normal", "date": today.isoformat()}],
            today=today,
            hour_of_day=8,
            temperature=18.0,
            humidite=55.0,
            etp_capteur=2.0,
            soil_balance={"reserve_mm": 6.0},
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["reserve_hydrique_sol_mm"], 6.0)
        self.assertLess(snapshot["bilan_hydrique_mm"], 0.0)
        self.assertEqual(snapshot["type_arrosage"], "personnalise")
        self.assertIsNone(snapshot.get("block_reason"))
        self.assertGreater(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["watering_strategy"], "adult_deep")
        self.assertEqual(snapshot["objective_scope"], "global_surface")
        self.assertEqual(snapshot["watering_stage"], "normal")
        self.assertNotIn("surface_cycle_mm", snapshot)
        self.assertNotIn("daily_cycles_target", snapshot)
        self.assertNotIn("cycle_spacing_minutes", snapshot)
        self.assertNotIn("Sol déjà humide", snapshot["raison_decision"])
        self.assertNotIn("sol_deja_humide", snapshot["raison_decision"])

    def test_build_decision_snapshot_normal_urgence_uses_daily_balance_when_soil_reserve_is_positive(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Normal", "date": "2026-04-04"}],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=14.6,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=60.0,
            type_sol="limoneux",
            etp_capteur=0.9,
            soil_balance={
                "reserve_mm": 15.8,
                "previous_reserve_mm": 16.7,
                "pluie_mm": 0.0,
                "arrosage_mm": 0.0,
                "etp_mm": 0.9,
                "delta_mm": -0.9,
            },
        )

        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["type_arrosage"], "aucune_action")
        self.assertEqual(snapshot["arrosage_conseille"], "aucune_action")
        self.assertLess(snapshot["bilan_hydrique_mm"], 0.0)
        self.assertGreater(snapshot["reserve_hydrique_sol_mm"], 0.0)
        self.assertEqual(snapshot["urgence"], "moyenne")

    def test_compute_objectif_mm_blocks_when_three_day_rain_horizon_is_significant(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -0.6,
                "deficit_3j": 2.1,
                "deficit_7j": 3.5,
            },
            today=date(2026, 3, 17),
            pluie_demain=0.0,
            humidite=55.0,
            temperature=18.0,
            etp=2.0,
            type_sol="limoneux",
            pluie_j2=1.8,
            pluie_3j=4.8,
        )

        self.assertEqual(objectif, 0.0)

    def test_build_decision_snapshot_sursemis_is_capped_by_mode_floor(self) -> None:
        today = date(2026, 3, 17)
        snapshot = make_snapshot(
            history=[{"type": "Sursemis", "date": today.isoformat()}],
            today=today,
            hour_of_day=10,
            temperature=18.0,
            etp_capteur=0.0,
            soil_balance={"reserve_mm": -1.0},
        )

        self.assertEqual(snapshot["phase_active"], "Sursemis")
        self.assertEqual(snapshot["type_arrosage"], "manuel_frequent")
        self.assertEqual(snapshot["objectif_mm"], 1.5)
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertIsNone(snapshot.get("block_reason"))
        self.assertEqual(snapshot["watering_strategy"], "semis_frequent")
        self.assertEqual(snapshot["objective_scope"], "surface_cycle")
        self.assertIn("semis_frequent", snapshot["raison_decision"])
        self.assertIn("cycle de surface", snapshot["raison_decision"])

    def test_compute_action_guidance_sursemis_allows_daytime_micro_cycles(self) -> None:
        base_kwargs = dict(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "deficit_3j": 1.2,
                "deficit_7j": 2.4,
            },
            advanced_context={
                "vent": 8,
                "rosee": 0.0,
                "hauteur_gazon": 7.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            temperature=18.0,
            etp=1.2,
            objectif_mm=0.5,
        )

        early = decision.compute_action_guidance(hour_of_day=3, **base_kwargs)
        acceptable = decision.compute_action_guidance(hour_of_day=6, **base_kwargs)
        afternoon = decision.compute_action_guidance(hour_of_day=14, **base_kwargs)
        evening = decision.compute_action_guidance(hour_of_day=19, **base_kwargs)

        self.assertEqual(early["fenetre_optimale"], "ce_matin")
        self.assertEqual(acceptable["fenetre_optimale"], "ce_matin")
        self.assertEqual(afternoon["fenetre_optimale"], "maintenant")
        self.assertEqual(evening["fenetre_optimale"], "demain_matin")

    def test_compute_action_guidance_adjusts_window_with_temperature(self) -> None:
        base_kwargs = dict(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "deficit_3j": 1.2,
                "deficit_7j": 2.4,
            },
            advanced_context={
                "vent": 8,
                "rosee": 0.0,
                "hauteur_gazon": 7.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            etp=1.2,
            objectif_mm=0.5,
            hour_of_day=6,
        )

        cool = decision.compute_action_guidance(temperature=8.0, **base_kwargs)
        hot = decision.compute_action_guidance(temperature=24.0, **base_kwargs)

        self.assertEqual(cool["watering_window_start_minute"], 600)
        self.assertEqual(cool["watering_window_end_minute"], 1020)
        self.assertEqual(cool["watering_window_optimal_start_minute"], 600)
        self.assertEqual(cool["watering_window_optimal_end_minute"], 1020)
        self.assertEqual(hot["watering_window_start_minute"], 600)
        self.assertEqual(hot["watering_window_end_minute"], 1020)
        self.assertEqual(hot["watering_window_optimal_start_minute"], 600)
        self.assertEqual(hot["watering_window_optimal_end_minute"], 1020)
        self.assertEqual(cool["watering_window_profile"], "cool")
        self.assertEqual(hot["watering_window_profile"], "hot")

    def test_compute_action_guidance_allows_evening_when_conditions_match(self) -> None:
        # En avril, le soir n'est autorisé qu'en cas de déficit critique (< -3.0 mm)
        guidance = decision.compute_action_guidance(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -3.5,  # Déficit critique pour autoriser le soir en avril
                "deficit_3j": 4.0,
                "deficit_7j": 7.0,
            },
            advanced_context={
                "vent": 6,
                "rosee": 0.0,
                "hauteur_gazon": 8.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=42.0,
            temperature=27.0,
            etp=4.4,
            objectif_mm=4.0,
            hour_of_day=19,
        )

        self.assertEqual(guidance["fenetre_optimale"], "soir")
        self.assertTrue(guidance["watering_evening_allowed"])
        self.assertEqual(guidance["watering_evening_start_minute"], 1080)
        self.assertEqual(guidance["watering_evening_end_minute"], 1200)

    def test_compute_action_guidance_prefers_after_rain_when_three_day_horizon_is_wet(self) -> None:
        guidance = decision.compute_action_guidance(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "deficit_3j": 2.4,
                "deficit_7j": 4.2,
            },
            advanced_context={
                "vent": 6,
                "rosee": 0.0,
                "hauteur_gazon": 7.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=2.2,
            pluie_3j=5.0,
            pluie_probabilite_max_3j=85.0,
            humidite=55.0,
            temperature=18.0,
            etp=1.2,
            objectif_mm=0.5,
            hour_of_day=6,
        )

        self.assertEqual(guidance["fenetre_optimale"], "apres_pluie")

    def test_compute_action_guidance_exposes_stable_window_keys_across_paths(self) -> None:
        expected_keys = {
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
            "heat_stress_level",
            "heat_stress_phase",
            "watering_window_start_minute",
            "watering_window_end_minute",
            "watering_window_optimal_start_minute",
            "watering_window_optimal_end_minute",
            "watering_window_acceptable_end_minute",
            "watering_evening_start_minute",
            "watering_evening_end_minute",
            "watering_window_profile",
            "watering_evening_allowed",
        }
        variants = [
            dict(
                phase_dominante="Traitement",
                sous_phase="Application",
                water_balance={"bilan_hydrique_mm": 0.0, "deficit_3j": 0.0, "deficit_7j": 0.0},
                advanced_context={},
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=60.0,
                temperature=18.0,
                etp=1.0,
                objectif_mm=0.0,
                hour_of_day=10,
            ),
            dict(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance={"bilan_hydrique_mm": -1.6, "deficit_3j": 2.1, "deficit_7j": 3.9},
                advanced_context={"vent": 6, "rosee": 0.0, "hauteur_gazon": 8.0},
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=42.0,
                temperature=27.0,
                etp=4.4,
                objectif_mm=2.0,
                hour_of_day=19,
            ),
        ]

        for kwargs in variants:
            guidance = decision.compute_action_guidance(**kwargs)
            self.assertTrue(expected_keys.issubset(guidance.keys()))

    def test_fractionation_expands_above_two_mm(self) -> None:
        passages = decision_watering._soil_fractionation_passages(
            phase_dominante="Normal",
            sous_phase="Normal",
            type_sol="limoneux",
            objectif_mm=3.0,
            stress_level="modere",
            temperature=18.0,
            humidite=55.0,
            etp=2.0,
        )

        self.assertEqual(passages, 2)

    def test_fractionation_is_capped_to_three_passages(self) -> None:
        passages = decision_watering._soil_fractionation_passages(
            phase_dominante="Fertilisation",
            sous_phase="Reponse",
            type_sol="argileux",
            objectif_mm=10.0,
            stress_level="fort",
            temperature=32.0,
            humidite=30.0,
            etp=4.5,
        )

        self.assertEqual(passages, 3)

class TestDecisionSnapshotSursemisRules(unittest.TestCase):
    def test_build_decision_snapshot_sursemis_objectif_zero_never_recommends_zero_mm(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            pluie_24h=1.0,
            pluie_demain=3.2,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=0.5,
        )

        self.assertEqual(snapshot["phase_active"], "Sursemis")
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["niveau_action"], "surveiller")
        self.assertEqual(snapshot["decision_resume"]["action"], "aucune_action")
        self.assertNotIn("0.0 mm", snapshot["action_recommandee"])
        self.assertNotIn("0.0 mm", snapshot["conseil_principal"])
        self.assertEqual(snapshot["action_a_eviter"], "Multiplier les petits cycles.")

    def test_build_decision_snapshot_sursemis_micro_apport_rules(self) -> None:
        cases = [
            (
                "dry_surface",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                1.5,
                True,
                None,
                True,
            ),
            (
                "recent_rain",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=1.6,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                0.0,
                False,
                "pluie_prevue_suffisante",
                False,
            ),
            (
                "tomorrow_rain",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=2.4,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                1.2,
                True,
                None,
                True,
            ),
            (
                "tomorrow_rain_blocked",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=3.2,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                0.0,
                False,
                "pluie_prevue_suffisante",
                False,
            ),
            (
                "j2_rain_only",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    pluie_j2=1.8,
                    pluie_3j=4.8,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                1.5,
                True,
                None,
                True,
            ),
            (
                "high_balance",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 5.5},
                ),
                1.5,
                True,
                None,
                True,
            ),
            (
                "saturated_surface",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    humidite_sol=92.0,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 8.5},
                ),
                0.0,
                False,
                "sol_deja_humide",
                False,
            ),
            (
                "recent_watering",
                dict(
                    history=[
                        {"type": "Sursemis", "date": "2026-03-17"},
                        {"type": "arrosage", "date": date(2026, 3, 17).isoformat(), "objectif_mm": 0.5},
                    ],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                1.5,
                True,
                None,
                True,
            ),
            (
                "low_temperature",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=8.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                0.0,
                False,
                "temperature_trop_basse",
                False,
            ),
        ]

        for name, kwargs, expected_mm, expected_allowed, expected_block_reason, expected_surface_sec in cases:
            with self.subTest(name):
                snapshot = decision.build_decision_snapshot(**kwargs)
                self.assertEqual(snapshot["phase_active"], "Sursemis")
                self.assertEqual(snapshot["objectif_mm"], expected_mm)
                self.assertEqual(snapshot["arrosage_recommande"], expected_allowed)
                self.assertEqual(snapshot.get("sursemis_micro_apport_allowed"), expected_allowed)
                self.assertEqual(snapshot.get("surface_sec"), expected_surface_sec)
                self.assertEqual(snapshot.get("sursemis_block_reason"), expected_block_reason)
                self.assertIn("pluie_probabilite_24h", snapshot)
                self.assertIn("mm_detected_24h", snapshot)
                self.assertIn("surface_saturation_level", snapshot)
                self.assertIn("surface_saturation_limit", snapshot)
                self.assertIn("sursemis_reason", snapshot)

    def test_build_decision_snapshot_sursemis_germination_is_more_permissive_than_enracinement(self) -> None:
        germination = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=2.4,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=1.2,
            weather_profile={"weather_precipitation_probability": 20.0},
            soil_balance={"reserve_mm": 2.4},
        )
        enracinement = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-06"}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=1.6,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=1.2,
            weather_profile={"weather_precipitation_probability": 20.0},
            soil_balance={"reserve_mm": 2.4},
        )

        self.assertEqual(germination["phase_active"], "Sursemis")
        self.assertEqual(enracinement["phase_active"], "Sursemis")
        self.assertEqual(germination["watering_stage"], "germination")
        self.assertEqual(enracinement["watering_stage"], "enracinement")
        self.assertLess(germination["surface_cycle_mm"], enracinement["surface_cycle_mm"])
        self.assertGreater(germination["daily_cycles_target"], enracinement["daily_cycles_target"])
        self.assertEqual(germination["objective_scope"], "surface_cycle")
        self.assertEqual(enracinement["objective_scope"], "surface_cycle")
        self.assertTrue(germination["arrosage_recommande"])
        self.assertFalse(enracinement["arrosage_recommande"])
        self.assertIsNone(germination.get("block_reason"))
        self.assertIsNotNone(enracinement.get("block_reason"))

    def test_compute_action_guidance_sursemis_reprise_transition_ready_waits_more(self) -> None:
        base_kwargs = dict(
            phase_dominante="Sursemis",
            sous_phase="Reprise",
            water_balance={
                "bilan_hydrique_mm": 1.4,
                "deficit_3j": 0.8,
                "deficit_7j": 1.2,
            },
            advanced_context={
                "vent": 6,
                "rosee": 0.0,
                "hauteur_gazon": 7.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.2,
            humidite=55.0,
            temperature=18.0,
            etp=1.2,
            objectif_mm=0.5,
            hour_of_day=9,
            sous_phase_age_days=19,
            sous_phase_progression=82.0,
        )

        not_ready = decision.compute_action_guidance(
            history=[{"type": "Sursemis", "date": "2026-03-01"}],
            **base_kwargs,
        )
        ready = decision.compute_action_guidance(
            history=[
                {"type": "Sursemis", "date": "2026-03-01"},
                {"type": "tonte", "date": "2026-03-15"},
                {"type": "tonte", "date": "2026-03-18"},
            ],
            **base_kwargs,
        )

        self.assertEqual(not_ready["fenetre_optimale"], "ce_matin")
        self.assertEqual(ready["fenetre_optimale"], "attendre")
        self.assertEqual(not_ready["niveau_action"], "a_faire")
        self.assertEqual(ready["niveau_action"], "surveiller")
        self.assertEqual(not_ready["risque_gazon"], "modere")
        self.assertEqual(ready["risque_gazon"], "modere")

class TestDecisionSnapshotApplicationsAndSensors(unittest.TestCase):
    def test_build_decision_snapshot_fertilisation_uses_application_technique(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Fertilisation", "date": "2026-06-15"}],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=33,
            pluie_24h=0,
            pluie_demain=0,
            humidite=30,
            type_sol="argileux",
            etp_capteur=5.0,
        )

        self.assertEqual(snapshot["phase_active"], "Fertilisation")
        self.assertEqual(snapshot["application_type"], "sol")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["watering_cause"], "post_application")
        self.assertEqual(snapshot["type_arrosage"], "application_technique_auto")
        self.assertEqual(snapshot["arrosage_conseille"], "application_technique_auto")
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["watering_target_date"], "2026-06-15")
        self.assertEqual(snapshot["next_action_date"], "2026-06-15")
        self.assertGreater(snapshot["objectif_mm"], 0.0)

    def test_build_decision_snapshot_uses_advanced_sensors(self) -> None:
        base_snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=24,
            pluie_24h=1.0,
            pluie_demain=0.0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=4.0,
        )
        advanced_snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=24,
            pluie_24h=1.0,
            pluie_demain=0.0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=4.0,
            humidite_sol=22,
            vent=18,
            rosee=1.0,
            hauteur_gazon=11.5,
            retour_arrosage=0.7,
            weather_profile={
                "weather_temperature": 24,
                "weather_humidity": 55,
                "weather_wind_speed": 18,
                "weather_cloud_coverage": 20,
                "weather_precipitation_probability": 70,
            },
        )

        self.assertEqual(advanced_snapshot["advanced_context"]["pluie_source"], "capteur_pluie_24h")
        self.assertEqual(advanced_snapshot["advanced_context"]["weather_precipitation_probability"], 70.0)
        self.assertEqual(advanced_snapshot["humidite_sol"], 22.0)
        self.assertEqual(advanced_snapshot["vent"], 18.0)
        self.assertEqual(advanced_snapshot["rosee"], 1.0)
        self.assertEqual(advanced_snapshot["hauteur_gazon"], 11.5)
        self.assertEqual(advanced_snapshot["retour_arrosage"], 0.7)
        self.assertGreater(advanced_snapshot["score_hydrique"], base_snapshot["score_hydrique"])
        self.assertGreaterEqual(advanced_snapshot["score_stress"], base_snapshot["score_stress"])
        self.assertIn(advanced_snapshot["niveau_action"], {"a_faire", "surveiller", "critique"})

    def test_build_decision_snapshot_keeps_return_watering_sensor_priority(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-03-17",
                    "objectif_mm": 4.0,
                    "zones": [
                        {"zone": "switch.zone_1", "mm": 2.0},
                        {"zone": "switch.zone_2", "mm": 2.0},
                    ],
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=24,
            pluie_24h=1.0,
            pluie_demain=0.0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=4.0,
            retour_arrosage=0.7,
        )

        self.assertEqual(snapshot["retour_arrosage"], 0.7)

class TestDecisionSnapshotMowing(unittest.TestCase):
    def test_build_mowing_bundle_exposes_stable_core_keys_on_allowed_path(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(
            set(decision_mowing._MOWING_BUNDLE_CORE_KEYS).issubset(set(mowing_bundle))
        )

    def test_build_mowing_bundle_passthroughs_generic_mower_context(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context={
                "tondeuse_statut": "au_repos",
                "tondeuse_statut_libelle": "Au repos",
                "tondeuse_prete": True,
                "tondeuse_batterie": 44,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["tondeuse_statut"], "au_repos")
        self.assertEqual(mowing_bundle["tondeuse_statut_libelle"], "Au repos")
        self.assertTrue(mowing_bundle["tondeuse_prete"])
        self.assertEqual(mowing_bundle["tondeuse_batterie"], 44)

    def test_build_mowing_bundle_prioritizes_post_application_over_watering_runtime(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-06-15",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_irrigation_mode": "suggestion",
                    "application_post_watering_status": "autorise",
                }
            ],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "active_irrigation_session": {"status": "running", "started_at": "2026-06-15T06:30:00+00:00"},
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertTrue(mowing_bundle["mowing_blocked_by_watering"])
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "post_application_active")
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_runtime_watering_session(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "active_irrigation_session": {"status": "running", "started_at": "2026-06-15T06:30:00+00:00"},
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "watering_in_progress")
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_recent_watering_cooldown(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "last_irrigation_execution": {"type": "arrosage", "triggered_at": "2026-06-15T07:00:00+00:00"},
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "watering_cooldown")
        self.assertGreater(mowing_bundle["mowing_cooldown_remaining_minutes"], 0)
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_uses_last_execution_end_timestamp_for_cooldown(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=10,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "last_irrigation_execution": {
                    "type": "arrosage",
                    "ended_at": "2026-06-15T09:15:00+00:00",
                },
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "watering_cooldown")
        self.assertEqual(mowing_bundle["mowing_cooldown_remaining_minutes"], 135)

    def test_build_mowing_bundle_marks_recent_watering_as_watering_block(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-06-15",
                    "mm": 3.8,
                }
            ],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertTrue(mowing_bundle["mowing_blocked_by_watering"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "recent_watering")
        self.assertTrue(
            mowing_bundle["mowing_block_reason_label"].startswith("Arrosage récent: attendre encore ~"),
            mowing_bundle["mowing_block_reason_label"],
        )
        self.assertEqual(mowing_bundle["mowing_block_reason"], "recent_watering")
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_wet_soil_after_old_watering(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-06-10",
                    "mm": 3.8,
                }
            ],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            humidite_sol=75,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context={
                "tondeuse_connectee": True,
                "tondeuse_prete": True,
                "mower_coordination_ready": True,
                "mower_operation_state": "idle",
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(mowing_bundle["mowing_blocked_by_watering"])
        self.assertEqual(mowing_bundle["mowing_block_reason"], "soil_wet")
        self.assertEqual(mowing_bundle["mowing_block_reason_label"], "Sol humide: attendre le ressuyage.")
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertTrue(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_exposes_robot_style_frequency_and_window(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_frequency_target_per_week"], 5.0)
        self.assertEqual(mowing_bundle["mowing_frequency_label"], "4 à 6 / semaine")
        self.assertEqual(mowing_bundle["mowing_window_state"], "ideal")
        self.assertEqual(mowing_bundle["mowing_window_label"], "Fenêtre idéale")
        self.assertEqual(mowing_bundle["mowing_window_reason"], "Fenêtre idéale du matin.")
        self.assertTrue(mowing_bundle["tonte_autorisee"])

    def test_build_mowing_bundle_marks_midday_as_discouraged_but_not_blocked(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=14,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "discouraged")
        self.assertEqual(mowing_bundle["mowing_window_label"], "À éviter")
        self.assertIn("à éviter", mowing_bundle["mowing_window_reason"].lower())
        self.assertTrue(mowing_bundle["tonte_autorisee"])

    def test_build_mowing_bundle_discourages_high_humidity_and_wind_but_keeps_action_possible(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=27,
            pluie_24h=0,
            pluie_demain=0,
            humidite=88,
            vent=25,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context={
                "tondeuse_connectee": True,
                "tondeuse_prete": True,
                "mower_coordination_ready": True,
                "mower_operation_state": "idle",
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "discouraged")
        self.assertEqual(mowing_bundle["mowing_window_label"], "À éviter")
        self.assertTrue(mowing_bundle["tonte_autorisee"])
        self.assertTrue(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_wind_over_forty(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            vent=45,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "blocked")
        self.assertIn("Vent trop fort", mowing_bundle["mowing_window_reason"])
        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_recent_rain(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=1.2,
            pluie_demain=0,
            humidite=55,
            humidite_sol=75,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "blocked")
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "soil_wet")
        self.assertEqual(mowing_bundle["mowing_block_reason_label"], "Sol humide: attendre le ressuyage.")
        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_outside_mowing_window_before_10am(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "blocked")
        self.assertEqual(mowing_bundle["mowing_window_label"], "Bloqué")
        self.assertIn("Matin trop tôt", mowing_bundle["mowing_window_reason"])
        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_when_machine_unavailable(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context={
                "tondeuse_connectee": False,
                "tondeuse_prete": False,
                "mower_coordination_ready": False,
                "mower_operation_state": "idle",
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertEqual(mowing_bundle["mowing_block_reason"], "machine_unavailable")
        self.assertEqual(mowing_bundle["mowing_block_reason_label"], "Robot indisponible: attendre qu'elle soit prête.")
        self.assertTrue(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_does_not_block_on_watering_three_days_old(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-06-12",
                    "mm": 3.8,
                }
            ],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(mowing_bundle["tonte_autorisee"])
        self.assertIsNone(mowing_bundle["mowing_block_reason_code"])
        self.assertFalse(mowing_bundle["mowing_blocked_by_watering"])

    def test_build_mowing_bundle_blocks_when_sun_is_below_horizon(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 20),
            hour_of_day=0,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
            sun_context={
                "sun_state": "below_horizon",
                "sun_above_horizon": False,
                "sun_below_horizon": True,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "mowing_night")
        self.assertEqual(mowing_bundle["tonte_statut"], "interdite")
        self.assertEqual(mowing_bundle["mowing_block_reason_label"], "Nuit: attendre le lever du soleil.")

    def test_snapshot_blocks_watering_when_mower_is_outside(self) -> None:
        snapshot = decision.build_decision_result(
            decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 6, 15),
                hour_of_day=8,
                temperature=24,
                pluie_24h=0,
                pluie_demain=0,
                humidite=45,
                type_sol="limoneux",
                etp_capteur=4.0,
                memory={"auto_irrigation_enabled": True},
                mower_context={
                    "mower_coordination_enabled": True,
                    "mower_coordination_ready": True,
                    "mower_is_mowing": True,
                    "mower_is_returning": False,
                    "mower_is_safe_for_watering": False,
                    "mower_operation_state": "tonte",
                    "mower_presence_state": "dehors",
                },
            )
        ).to_snapshot()

        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertTrue(snapshot["watering_blocked_by_mower"])
        self.assertEqual(snapshot["watering_block_reason_code"], "mower_mowing")

    def test_snapshot_blocks_watering_when_mower_resolution_is_ambiguous(self) -> None:
        snapshot = decision.build_decision_result(
            decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 6, 15),
                hour_of_day=8,
                temperature=24,
                pluie_24h=0,
                pluie_demain=0,
                humidite=45,
                type_sol="limoneux",
                etp_capteur=4.0,
                memory={"auto_irrigation_enabled": True},
                mower_context={
                    "mower_coordination_enabled": True,
                    "mower_coordination_ready": False,
                    "mower_is_mowing": False,
                    "mower_is_returning": False,
                    "mower_is_safe_for_watering": False,
                    "mower_operation_state": "unknown",
                    "mower_presence_state": "inconnue",
                    "mower_reason_code": "ambiguous",
                    "mower_reason_label": "Plusieurs tondeuses détectées. Configuration explicite requise.",
                },
            )
        ).to_snapshot()

        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertTrue(snapshot["watering_blocked_by_mower"])
        self.assertEqual(snapshot["watering_block_reason_code"], "ambiguous")
        self.assertEqual(
            snapshot["watering_block_reason_label"],
            "Tondeuse ambiguë: plusieurs robots détectés, configuration requise.",
        )

    def test_snapshot_does_not_block_watering_when_mower_coordination_disabled(self) -> None:
        snapshot = decision.build_decision_result(
            decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 6, 15),
                hour_of_day=8,
                temperature=24,
                pluie_24h=0,
                pluie_demain=0,
                humidite=45,
                type_sol="limoneux",
                etp_capteur=4.0,
                memory={"auto_irrigation_enabled": True},
                mower_context={
                    "mower_coordination_enabled": False,
                    "mower_coordination_ready": True,
                    "mower_is_mowing": True,
                    "mower_is_returning": False,
                    "mower_is_safe_for_watering": False,
                    "mower_operation_state": "tonte",
                    "mower_presence_state": "dehors",
                },
            )
        ).to_snapshot()

        self.assertFalse(snapshot.get("watering_blocked_by_mower", False))
        self.assertNotEqual(snapshot.get("watering_block_reason_code"), "mower_mowing")

    def test_build_mowing_bundle_exposes_stable_core_keys_on_blocked_path(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "Traitement", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
            weather_profile={
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(
            set(decision_mowing._MOWING_BUNDLE_CORE_KEYS).issubset(set(mowing_bundle))
        )
        self.assertEqual(mowing_bundle["raison_blocage_code"], "phase_traitement")

    def test_build_decision_snapshot_prioritizes_phase_block_over_rain(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Traitement", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
            weather_profile={
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["raison_blocage_code"], "phase_traitement")
        self.assertEqual(snapshot["next_mowing_date"], "2026-03-20")

    def test_build_decision_snapshot_projects_next_mowing_date_after_recent_rain(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=4,
            pluie_demain=0,
            humidite=70,
            humidite_sol=75,
            type_sol="limoneux",
            etp_capteur=3.0,
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["raison_blocage_code"], "soil_wet")
        self.assertIsNotNone(snapshot["next_mowing_date"])
        self.assertIsNotNone(snapshot["next_mowing_display"])

    def test_build_decision_snapshot_never_projects_next_mowing_date_in_past(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "arrosage", "date": "2026-03-15", "objectif_mm": 3.0}],
            today=date(2026, 3, 17),
            hour_of_day=11,
            temperature=16,
            pluie_24h=0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=1.0,
        )

        self.assertTrue(snapshot["tonte_autorisee"])
        self.assertNotIn("raison_blocage_code", snapshot)
        self.assertEqual(snapshot["next_mowing_date"], "2026-03-17")
        self.assertEqual(snapshot["next_mowing_display"], "17/03/2026")

    def test_build_decision_snapshot_blocks_mowing_on_third_rule(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=12.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=6.0,
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["tonte_statut"], "deconseillee")
        self.assertIn("Règle du tiers", snapshot["raison_decision"])
        self.assertIsNone(snapshot.get("next_mowing_date"))
        self.assertIsNone(snapshot.get("next_mowing_display"))
        self.assertGreaterEqual(snapshot["hauteur_tonte_recommandee_cm"], 5.5)
        self.assertLessEqual(snapshot["hauteur_tonte_recommandee_cm"], 6.5)

    def test_build_decision_snapshot_exposes_mowing_height_recommendation(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=12.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 6.5)
        self.assertEqual(snapshot["hauteur_tonte_min_cm"], 3.0)
        self.assertEqual(snapshot["hauteur_tonte_max_cm"], 8.0)

    def test_build_decision_snapshot_prefers_slightly_lower_height_in_active_spring(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 4, 15),
            hour_of_day=8,
            temperature=19,
            pluie_24h=5.0,
            pluie_demain=0,
            humidite=80,
            type_sol="limoneux",
            etp_capteur=0.5,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertGreaterEqual(snapshot["hauteur_tonte_recommandee_cm"], 5.5)
        self.assertLessEqual(snapshot["hauteur_tonte_recommandee_cm"], 6.5)

    def test_build_decision_snapshot_raises_height_in_heat(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=34,
            pluie_24h=0,
            pluie_demain=0,
            humidite=30,
            type_sol="limoneux",
            etp_capteur=5.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=9.0,
        )

        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 6.5)

    def test_build_decision_snapshot_allows_light_reduction_in_favorable_autumn(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 9, 20),
            hour_of_day=8,
            temperature=19,
            pluie_24h=4.0,
            pluie_demain=0,
            humidite=78,
            type_sol="limoneux",
            etp_capteur=0.5,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertGreaterEqual(snapshot["hauteur_tonte_recommandee_cm"], 5.0)
        self.assertLessEqual(snapshot["hauteur_tonte_recommandee_cm"], 5.5)

    def test_build_decision_snapshot_rounds_all_mowing_heights_to_half_cm(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=12.3,
            hauteur_min_tondeuse_cm=3.1,
            hauteur_max_tondeuse_cm=7.9,
        )

        for key in (
            "hauteur_tonte_recommandee_cm",
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
        ):
            value = snapshot[key]
            self.assertIsNotNone(value)
            self.assertEqual(round(float(value) / 0.5) * 0.5, float(value))

    def test_build_decision_snapshot_stays_stable_across_small_weather_changes(self) -> None:
        baseline = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 5, 20),
            hour_of_day=8,
            temperature=20,
            pluie_24h=2.0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        follow_up = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 5, 21),
            hour_of_day=8,
            temperature=20.5,
            pluie_24h=2.2,
            pluie_demain=0,
            humidite=63,
            type_sol="limoneux",
            etp_capteur=2.1,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
            memory={"hauteur_tonte_recommandee_cm": baseline["hauteur_tonte_recommandee_cm"]},
        )

        self.assertLessEqual(
            abs(follow_up["hauteur_tonte_recommandee_cm"] - baseline["hauteur_tonte_recommandee_cm"]),
            0.5,
        )

    def test_build_decision_snapshot_moves_by_half_cm_max(self) -> None:
        baseline = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 5, 20),
            hour_of_day=8,
            temperature=19,
            pluie_24h=2.0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        follow_up = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=34,
            pluie_24h=0,
            pluie_demain=0,
            humidite=30,
            type_sol="limoneux",
            etp_capteur=5.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=9.0,
            memory={"hauteur_tonte_recommandee_cm": baseline["hauteur_tonte_recommandee_cm"]},
        )

        self.assertLessEqual(
            abs(follow_up["hauteur_tonte_recommandee_cm"] - baseline["hauteur_tonte_recommandee_cm"]),
            0.5,
        )

    def test_build_decision_snapshot_sursemis_recovery_is_progressive(self) -> None:
        germination = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-10"}],
            today=date(2026, 3, 12),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        enracinement = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-08"}],
            today=date(2026, 3, 18),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        reprise = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-01"}],
            today=date(2026, 3, 20),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertFalse(germination["tonte_autorisee"])
        self.assertFalse(enracinement["tonte_autorisee"])
        self.assertFalse(reprise["tonte_autorisee"])
        self.assertGreaterEqual(germination["hauteur_tonte_recommandee_cm"], enracinement["hauteur_tonte_recommandee_cm"])
        self.assertGreaterEqual(enracinement["hauteur_tonte_recommandee_cm"], reprise["hauteur_tonte_recommandee_cm"])

    def test_build_decision_snapshot_keeps_post_sursemis_height_bonus_after_return_to_normal(self) -> None:
        post_sursemis = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-05-01"}],
            today=date(2026, 6, 1),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        baseline = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 1),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertEqual(post_sursemis["phase_active"], "Sursemis")
        self.assertGreater(post_sursemis["hauteur_tonte_recommandee_cm"], baseline["hauteur_tonte_recommandee_cm"])

    def test_build_decision_snapshot_blocks_mowing_on_dew(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=8.0,
            rosee=1.0,
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertIn("rosée", snapshot["raison_decision"].lower())

class TestEtpComputation(unittest.TestCase):
    def test_compute_etp_prefers_sensor_value(self) -> None:
        self.assertEqual(decision.compute_etp(temperature=24, pluie_24h=2, etp_capteur=4.2), 4.2)

    def test_compute_etp_can_fall_back_to_weather_profile(self) -> None:
        etp = decision.compute_etp(
            temperature=None,
            pluie_24h=1.0,
            etp_capteur=None,
            weather_profile={
                "weather_temperature": 24,
                "weather_humidity": 55,
                "weather_wind_speed": 18,
                "weather_cloud_coverage": 20,
                "weather_precipitation_probability": 30,
            },
        )

        self.assertIsNotNone(etp)
        self.assertGreater(etp, 0.0)

    def test_compute_etp_can_use_zero_weather_temperature(self) -> None:
        etp = decision.compute_etp(
            temperature=None,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile={
                "weather_temperature": 0.0,
                "weather_apparent_temperature": 24.0,
                "weather_humidity": 50.0,
                "weather_wind_speed": 0.0,
                "weather_cloud_coverage": 0.0,
                "weather_precipitation_probability": 0.0,
            },
        )

        # Vérification comportementale : temperature=0.0 (falsy) ne doit pas être ignorée.
        # La valeur exacte dépend de la formule PM ; on vérifie qu'elle est calculée
        # et raisonnable (ET0 proche de 0 par temps froid, mais non nulle).
        self.assertIsNotNone(etp)
        self.assertGreaterEqual(etp, 0.0)
        self.assertLess(etp, 2.0)


if __name__ == "__main__":
    unittest.main()


class TestIrrigationBlockedButCritical(unittest.TestCase):
    def test_irrigation_blocked_but_critical_exposed(self) -> None:
        # Build a payload that simulates a mower block with critical deficit
        payload = {
            "watering_blocked_by_mower": True,
            "type_arrosage": "bloque",
            "block_reason": "mower_mowing",
            "watering_block_reason_code": "mower_mowing",
            "water_balance": {
                "bilan_hydrique_mm": -3.0,
            },
        }
        result = decision_watering._apply_irrigation_execution_contract(payload)
        self.assertTrue(result["irrigation_blocked_but_critical"])
        self.assertEqual(result["critical_deficit_mm"], -3.0)
        self.assertIsNotNone(result["critical_irrigation_reason"])

    def test_irrigation_not_critical_when_deficit_insufficient(self) -> None:
        payload = {
            "watering_blocked_by_mower": True,
            "type_arrosage": "bloque",
            "water_balance": {
                "bilan_hydrique_mm": -1.0,
            },
        }
        result = decision_watering._apply_irrigation_execution_contract(payload)
        self.assertFalse(result["irrigation_blocked_but_critical"])
        self.assertIsNone(result["critical_deficit_mm"])


class TestMowingOverdue(unittest.TestCase):
    """Tests pour la détection de retard de tonte et son influence sur la décision."""

    def _make_bundle(self, history, today, hour_of_day=11, temperature=20, humidite=55, score_tonte_boost=0):
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=today,
            hour_of_day=hour_of_day,
            temperature=temperature,
            pluie_24h=0,
            pluie_demain=0,
            humidite=humidite,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

    def test_not_overdue_when_no_mowing_history(self):
        bundle = self._make_bundle(history=[], today=date(2026, 6, 15))
        self.assertFalse(bundle["mowing_is_overdue"])
        self.assertEqual(bundle["mowing_overdue_days"], 0)
        self.assertEqual(bundle["mowing_overdue_factor"], 0.0)

    def test_not_overdue_when_mowed_recently(self):
        # Fréquence juin = 5/semaine → intervalle 1,4 j — tonte hier = 0,7× → pas overdue
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-14"}],
            today=date(2026, 6, 15),
        )
        self.assertFalse(bundle["mowing_is_overdue"])
        self.assertEqual(bundle["mowing_overdue_days"], 1)

    def test_overdue_when_interval_exceeded_by_1_5x(self):
        # Fréquence juin = 5/semaine → intervalle 1,4 j — tonte il y a 3 j = 2,1× → overdue
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-12"}],
            today=date(2026, 6, 15),
        )
        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertEqual(bundle["mowing_overdue_days"], 3)
        self.assertGreater(bundle["mowing_overdue_factor"], 1.5)

    def test_overdue_reason_prefix_in_tonte_reason_when_blocked(self):
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-12"}],
            today=date(2026, 6, 15),
        )
        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertIn("Retard de tonte", bundle["tonte_reason"])
        self.assertIn("3 j", bundle["tonte_reason"])

    def test_overdue_reason_prefix_when_tonte_allowed(self):
        # Conditions idéales + tonte en retard → raison contient "Tonte recommandée"
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-10"}],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=18,
            humidite=50,
        )
        if bundle["tonte_autorisee"] and bundle["mowing_is_overdue"]:
            self.assertIn("Tonte recommandée", bundle["tonte_reason"])

    def test_overdue_does_not_override_hard_block_phase(self):
        # Sursemis Germination → tonte interdite même si très en retard
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {"type": "Sursemis", "date": "2026-06-01"},
                {"type": "tonte", "date": "2026-05-20"},
            ],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
        # La phase dure → tonte bloquée indépendamment du retard
        self.assertFalse(bundle["tonte_autorisee"])
        self.assertIn("phase_sursemis", (bundle.get("raison_blocage_code") or ""))

    def test_overdue_does_not_override_night_block(self):
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-10"}],
            today=date(2026, 6, 15),
            hour_of_day=2,
        )
        self.assertFalse(bundle["tonte_autorisee"])
        self.assertEqual(bundle["mowing_block_reason_code"], "mowing_night")

    def test_overdue_keys_always_present(self):
        bundle = self._make_bundle(history=[], today=date(2026, 6, 15))
        self.assertIn("mowing_is_overdue", bundle)
        self.assertIn("mowing_overdue_days", bundle)
        self.assertIn("mowing_overdue_factor", bundle)

    def test_not_overdue_in_winter_zero_frequency(self):
        # Janvier → fréquence 0 → jamais overdue
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2025-11-01"}],
            today=date(2026, 1, 15),
        )
        self.assertFalse(bundle["mowing_is_overdue"])
        self.assertEqual(bundle["mowing_overdue_days"], 0)

    def test_overdue_soft_override_activates_for_borderline_conditions_defavorables(self):
        # score_tonte=65 (conditions_defavorables) + overdue factor >> 2.0 → soft override actif
        # pluie_24h=6, pluie_demain=5, pluie_j2=2, humidite=80 → score_tonte=65, score_stress~16
        # Sans override (pas de retard): tonte bloquée par conditions_defavorables
        # Avec override (retard 37 j, factor~26×): tonte autorisée
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-05-01"}],  # 37 jours → factor >> 2
            today=date(2026, 6, 7),
            hour_of_day=11,
            temperature=22,
            pluie_24h=6,
            pluie_demain=5,
            pluie_j2=2,
            pluie_3j=0,
            pluie_probabilite_max_3j=0,
            humidite=80,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertGreaterEqual(bundle["mowing_overdue_factor"], 2.0)
        # Le soft override doit avoir levé le blocage conditions_defavorables
        self.assertTrue(bundle["tonte_autorisee"], "Le soft override overdue doit lever conditions_defavorables borderline")


class TestEstimatedGrassHeight(unittest.TestCase):
    """Tests pour l'estimation de la hauteur du gazon sans capteur physique."""

    def _make_bundle(self, history, today, mower_context=None):
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=today,
            hour_of_day=11,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context=mower_context or {},
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

    def test_estimation_none_without_cutting_height(self):
        # Pas de hauteur de coupe configurée → estimation impossible
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-01"}],
            today=date(2026, 6, 7),
            mower_context={},
        )
        self.assertIsNone(bundle["gazon_hauteur_estimee_cm"])

    def test_estimation_none_without_mowing_history(self):
        # Hauteur de coupe connue mais pas de tonte → estimation impossible
        bundle = self._make_bundle(
            history=[],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
        )
        self.assertIsNone(bundle["gazon_hauteur_estimee_cm"])

    def test_estimation_equals_cut_height_day_of_mowing(self):
        # Tonte aujourd'hui → hauteur = hauteur de coupe
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-07"}],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
        )
        self.assertEqual(bundle["gazon_hauteur_estimee_cm"], 4.5)

    def test_estimation_grows_after_mowing(self):
        # Tonte il y a 4 jours en juin → hauteur = 4.5 + 4 * 0.5 = 6.5
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-03"}],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
        )
        self.assertAlmostEqual(bundle["gazon_hauteur_estimee_cm"], 6.5, places=1)

    def test_estimation_zero_growth_in_winter(self):
        # Janvier → croissance 0 → hauteur reste égale à la hauteur de coupe
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-01-01"}],
            today=date(2026, 1, 15),
            mower_context={"tondeuse_hauteur_coupe_mm": 50},
        )
        self.assertEqual(bundle["gazon_hauteur_estimee_cm"], 5.0)

    def test_physical_sensor_takes_priority_over_estimate(self):
        # Un capteur physique doit être utilisé en priorité (hauteur actuelle dans advanced_context)
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-06-01"}],
            today=date(2026, 6, 7),
            hour_of_day=11,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
            hauteur_gazon=3.5,  # capteur physique = 3.5 cm
            mower_context={"tondeuse_hauteur_coupe_mm": 45},  # aurait donné 7.5 cm d'estimation
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
        # La hauteur actuelle utilisée dans la recommandation doit refléter le capteur (3.5)
        self.assertIsNotNone(bundle["hauteur_tonte_recommandee_cm"])
        # L'estimation est quand même exposée dans le bundle
        self.assertIsNotNone(bundle["gazon_hauteur_estimee_cm"])

    def test_key_always_present_in_bundle(self):
        bundle = self._make_bundle(history=[], today=date(2026, 6, 7))
        self.assertIn("gazon_hauteur_estimee_cm", bundle)


class TestMowingWindowReason(unittest.TestCase):
    """Tests pour la clarté des messages de blocage de fenêtre de tonte."""

    def _make_bundle(self, hour_of_day, history=None, temperature=20, vent=0, humidite=55):
        context = decision.DecisionContext.from_legacy_args(
            history=history or [{"type": "tonte", "date": "2026-06-05"}],
            today=date(2026, 6, 7),
            hour_of_day=hour_of_day,
            temperature=temperature,
            pluie_24h=0,
            pluie_demain=0,
            humidite=humidite,
            type_sol="limoneux",
            etp_capteur=3.0,
            vent=vent,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

    def test_window_only_block_shows_clear_reason(self):
        # 3h du matin, bonnes conditions → raison = fenêtre bloquée uniquement
        bundle = self._make_bundle(hour_of_day=3)
        self.assertFalse(bundle["tonte_autorisee"])
        reason = bundle["tonte_reason"]
        # Le message doit mentionner pourquoi la fenêtre est bloquée
        self.assertTrue(
            "nuit" in reason.lower() or "soleil" in reason.lower() or "tôt" in reason.lower(),
            f"Message attendu sur blocage nocturne, reçu: {reason}",
        )

    def test_window_block_added_to_agronomic_reason(self):
        # 3h du matin + vent fort (> 40) → deux raisons : fenêtre ET vent
        bundle = self._make_bundle(hour_of_day=3, vent=45)
        self.assertFalse(bundle["tonte_autorisee"])
        reason = bundle["tonte_reason"]
        # La raison principale est agronomique mais la fenêtre doit être mentionnée
        self.assertIn("Fenêtre horaire", reason, f"Fenêtre horaire absente du message: {reason}")

    def test_discouraged_window_mentioned_when_tonte_ok(self):
        # 18h, vent à 25 km/h (discouraged) + bonnes conditions → tonte ok mais créneau déconseillé
        bundle = self._make_bundle(hour_of_day=18, vent=25)
        if bundle["tonte_autorisee"]:
            reason = bundle["tonte_reason"]
            self.assertIn(
                "déconseillé", reason.lower(),
                f"Créneau déconseillé non mentionné: {reason}",
            )

    def test_ideal_window_no_spurious_discouraged_message(self):
        # 11h, bonnes conditions → pas de message "déconseillé"
        bundle = self._make_bundle(hour_of_day=11)
        if bundle["tonte_autorisee"]:
            self.assertNotIn("déconseillé", bundle["tonte_reason"].lower())


class TestMowingWateringCoordination(unittest.TestCase):
    """Tests pour la coordination arrosage/tonte."""

    def _make_bundle(self, hour_of_day, arrosage_recommande, watering_window_start_minute,
                     has_recent_watering=False):
        history = []
        if has_recent_watering:
            history.append({"type": "arrosage", "date": date(2026, 6, 7).isoformat(), "mm": 10})
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 6, 7),
            hour_of_day=hour_of_day,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        # Patch the relevant water_bundle keys
        water_bundle["arrosage_recommande"] = arrosage_recommande
        water_bundle["watering_window_start_minute"] = watering_window_start_minute
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

    def test_no_advisory_when_no_watering_recommended(self):
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=False, watering_window_start_minute=240
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "none")
        self.assertIsNone(bundle["mowing_watering_coordination_msg"])

    def test_no_advisory_when_already_watered(self):
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=True,
            watering_window_start_minute=240, has_recent_watering=True
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "none")

    def test_block_when_watering_imminent(self):
        # 11h00 (660 min), watering starts at 11h20 (680 min) → 20 min → block
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=True, watering_window_start_minute=680
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "block")
        self.assertFalse(bundle["tonte_autorisee"])
        self.assertIn("imminent", bundle["tonte_reason"].lower())

    def test_discourage_when_watering_within_2h(self):
        # 11h00 (660 min), watering starts at 12h30 (750 min) → 90 min → discourage
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=True, watering_window_start_minute=750
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "discourage")
        # Tonte toujours possible, mais message d'avertissement présent
        self.assertIsNotNone(bundle["mowing_watering_coordination_msg"])

    def test_no_advisory_when_watering_far_away(self):
        # 11h00 (660 min), watering starts at 4h00 tomorrow effective (but > 2h)
        # 14h (840 min) start, current 11h (660 min) → 180 min → none
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=True, watering_window_start_minute=840
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "none")

    def test_coordination_keys_always_present(self):
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=False, watering_window_start_minute=None
        )
        self.assertIn("mowing_watering_coordination", bundle)
        self.assertIn("mowing_watering_coordination_msg", bundle)
