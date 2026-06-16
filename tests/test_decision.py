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
guidance_module = importlib.import_module("custom_components.gazon_intelligent.guidance")

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

        phase, start, end = decision.compute_phase_active(history, today=today)

        self.assertEqual(phase, "Traitement")
        self.assertEqual(start, date(2026, 3, 16))
        self.assertEqual(end, date(2026, 3, 17))

    def test_compute_phase_active_stays_normal_without_active_history_even_when_cold(self) -> None:
        phase, start, end = decision.compute_phase_active([], today=date(2026, 1, 15))

        self.assertEqual(phase, "Normal")
        self.assertIsNone(start)
        self.assertIsNone(end)

        phase, start, end = decision.compute_phase_active([], today=date(2026, 4, 14))

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

        dominant = decision.compute_dominant_phase(history, today=date(2026, 3, 17))

        self.assertEqual(dominant["phase_dominante"], "Traitement")
        self.assertEqual(dominant["source"], "historique_actif")
        self.assertEqual(dominant["date_debut"], date(2026, 3, 17))
        self.assertEqual(dominant["date_fin"], date(2026, 3, 18))

    def test_compute_dominant_phase_expires_single_day_phase_on_next_day(self) -> None:
        dominant = decision.compute_dominant_phase(
            [{"type": "Biostimulant", "date": "2026-03-17"}],
            today=date(2026, 3, 18),
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

    def test_compute_subphase_terminal_progression_bounded_by_phase_duration(self) -> None:
        # Stabilisation = jours 35-45 d'un Sursemis de 45j. Au jour 44, la
        # progression doit être proche de la fin (~85-95 %), pas ~1 % comme
        # lorsque la sentinelle 999 était prise pour une durée réelle.
        subphase = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 4, 26),
            date_fin=date(2026, 6, 10),
            today=date(2026, 6, 9),
            now=datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(subphase["sous_phase"], "Stabilisation")
        self.assertEqual(subphase["age_jours"], 44)
        self.assertGreaterEqual(subphase["progression"], 80.0)
        self.assertLessEqual(subphase["progression"], 100.0)

    def test_compute_subphase_hivernage_terminal_stays_open_ended(self) -> None:
        # Hivernage (durée 999): la sous-phase Repos reste volontairement
        # ouverte, le cap par durée de phase ne doit pas s'appliquer.
        subphase = decision.compute_subphase(
            phase_dominante="Hivernage",
            date_debut=date(2026, 1, 1),
            date_fin=None,
            today=date(2026, 1, 11),
            now=datetime(2026, 1, 11, 6, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(subphase["sous_phase"], "Repos")
        self.assertLess(subphase["progression"], 5.0)

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

    def test_rain_signals_ignore_high_probability_when_quantity_is_trace(self) -> None:
        # Une averse de trace (0,8 mm) annoncée à 95 % ne doit PAS bloquer l'arrosage
        # d'un sol sec — c'était la cause d'un faux « pluie prévue suffisante ».
        compensatrice, proche = guidance_module._rain_signals(
            objective_reference_mm=12.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.8,
            pluie_3j=0.8,
            pluie_probabilite_max_3j=95.0,
        )
        self.assertFalse(compensatrice)
        self.assertFalse(proche)

    def test_rain_signals_block_when_high_probability_and_real_quantity(self) -> None:
        # Forte probabilité + quantité réelle (5 mm) → on considère la pluie suffisante.
        compensatrice, proche = guidance_module._rain_signals(
            objective_reference_mm=12.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=2.2,
            pluie_3j=5.0,
            pluie_probabilite_max_3j=85.0,
        )
        self.assertTrue(compensatrice or proche)

    def test_evening_cooling_allowed_in_extreme_heat_with_drying_margin(self) -> None:
        # Chaleur extrême + air sec + coucher du soleil dans 2 h → petit arrosage de
        # rafraîchissement du soir autorisé (l'herbe sèchera avant la nuit).
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=30.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="extreme",
            minutes_to_sunset=120,
        )
        self.assertTrue(allowed)

    def test_evening_cooling_blocked_when_too_close_to_sunset(self) -> None:
        # Coucher dans 60 min (< 90) → pas d'arrosage du soir (séchage insuffisant).
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=30.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="extreme",
            minutes_to_sunset=60,
        )
        self.assertFalse(allowed)

    def test_evening_cooling_blocked_when_sunset_unknown(self) -> None:
        # Coucher du soleil inconnu (pas de capteur) → on s'abstient le soir en canicule.
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=30.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="extreme",
            minutes_to_sunset=None,
        )
        self.assertFalse(allowed)

    def test_evening_cooling_blocked_when_humidity_high(self) -> None:
        # Air humide → séchage trop lent → pas d'arrosage du soir (risque maladie).
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=80.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="extreme",
            minutes_to_sunset=120,
        )
        self.assertFalse(allowed)

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


if __name__ == "__main__":
    unittest.main()