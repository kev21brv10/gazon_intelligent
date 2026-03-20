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

decision = importlib.import_module("custom_components.gazon_intelligent.decision")
decision_watering = importlib.import_module("custom_components.gazon_intelligent.decision_watering")


class DecisionEngineTests(unittest.TestCase):
    def test_compute_phase_active_prefers_highest_priority(self) -> None:
        today = date(2026, 3, 17)
        history = [
            {"type": "Sursemis", "date": "2026-03-10"},
            {"type": "Traitement", "date": "2026-03-16"},
        ]

        phase, start, end = decision.compute_phase_active(history, today=today, temperature=18)

        self.assertEqual(phase, "Traitement")
        self.assertEqual(start, date(2026, 3, 16))
        self.assertEqual(end, date(2026, 3, 18))

    def test_compute_phase_active_falls_back_to_hivernage(self) -> None:
        phase, start, end = decision.compute_phase_active([], today=date(2026, 1, 15), temperature=12)

        self.assertEqual(phase, "Hivernage")
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

    def test_compute_recent_watering_mm_uses_session_totals(self) -> None:
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

        self.assertEqual(total, 3.6)

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
        self.assertEqual(dominant["date_fin"], date(2026, 3, 19))

    def test_compute_subphase_tracks_sursemis_progression(self) -> None:
        subphase = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 7),
            date_fin=date(2026, 3, 28),
            today=date(2026, 3, 17),
        )

        self.assertEqual(subphase["sous_phase"], "Enracinement")
        self.assertEqual(subphase["age_jours"], 10)
        self.assertEqual(subphase["progression"], 48)
        self.assertEqual(subphase["detail"], "Sursemis / Enracinement")

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

    def test_build_decision_snapshot_uses_persistent_soil_balance(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
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

        self.assertEqual(snapshot["bilan_hydrique_mm"], 14.0)
        self.assertAlmostEqual(snapshot["bilan_hydrique_journalier_mm"], -2.9, places=1)
        self.assertEqual(snapshot["bilan_hydrique_precedent_mm"], 11.0)
        self.assertEqual(snapshot["soil_balance"]["reserve_mm"], 14.0)

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
        self.assertEqual(memory["dernier_arrosage_significatif"]["date"], "2026-03-16")
        self.assertEqual(memory["derniere_phase_active"], "Sursemis")
        self.assertEqual(memory["derniere_application"]["libelle"], "Engrais printemps")
        self.assertEqual(memory["derniere_application"]["type"], "Fertilisation")
        self.assertEqual(memory["derniere_application"]["dose"], "12.5")
        self.assertEqual(memory["prochaine_reapplication"], "2026-04-07")
        self.assertEqual(memory["dernier_conseil"]["conseil_principal"], "Arroser ce matin")
        self.assertEqual(memory["dernier_conseil"]["prochaine_reevaluation"], "dans 24 h")

    def test_build_decision_snapshot_normal_recommends_watering(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["phase_dominante"], "Normal")
        self.assertEqual(snapshot["sous_phase"], "Normal")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertTrue(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "auto")
        self.assertEqual(snapshot["arrosage_conseille"], "auto")
        self.assertIn(snapshot["tonte_statut"], {"autorisee", "autorisee_avec_precaution", "a_surveiller"})
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["risque_gazon"], "eleve")
        self.assertEqual(snapshot["prochaine_reevaluation"], "dans 24 h")
        self.assertGreater(snapshot["objectif_mm"], 0)
        self.assertLess(snapshot["bilan_hydrique_mm"], 0)
        self.assertEqual(snapshot["decision_resume"]["action"], "arrosage")
        self.assertTrue(snapshot["tonte_autorisee"])

    def test_build_decision_snapshot_normal_suppresses_micro_watering(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=1.0,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["niveau_action"], "aucune_action")
        self.assertNotIn("0.0 mm", snapshot["conseil_principal"])
        self.assertNotIn("0.0 mm", snapshot["action_recommandee"])
        self.assertEqual(snapshot["action_a_eviter"], "Éviter tout arrosage inutile.")

    def test_build_decision_snapshot_reduces_watering_when_rain_compensates(self) -> None:
        dry_snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        rainy_snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            pluie_24h=0,
            pluie_demain=3.0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
        )

        self.assertTrue(rainy_snapshot["arrosage_recommande"])
        self.assertLess(rainy_snapshot["objectif_mm"], dry_snapshot["objectif_mm"])
        self.assertEqual(rainy_snapshot["objectif_mm"], rainy_snapshot["decision_resume"]["objectif_mm"])
        self.assertLessEqual(rainy_snapshot["objectif_mm"], rainy_snapshot["objectif_mm_brut"])
        self.assertIn("Réduis", rainy_snapshot["action_recommandee"])

    def test_build_decision_snapshot_normal_uses_soil_fractionation(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=30,
            pluie_24h=0,
            pluie_demain=0,
            humidite=45,
            type_sol="argileux",
            etp_capteur=4.5,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertGreaterEqual(snapshot["watering_passages"], 2)
        self.assertIn("passages courts", snapshot["action_recommandee"])

    def test_build_decision_snapshot_treatment_blocks_actions(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Traitement", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
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

    def test_build_decision_snapshot_foliar_application_blocks_auto_watering(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[
                {
                    "type": "Traitement",
                    "date": "2026-03-20",
                    "declared_at": "2026-03-20T08:00:00+00:00",
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
            today=date(2026, 3, 20),
            hour_of_day=10,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_type"], "foliaire")
        self.assertTrue(snapshot["application_block_active"])
        self.assertGreater(snapshot["application_block_remaining_minutes"], 0.0)
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertIn("fenêtre de protection", snapshot["conseil_principal"])
        self.assertEqual(snapshot["application_label_notes"], "Pas d'arrosage après application")
        self.assertEqual(snapshot["application_irrigation_mode"], "suggestion")

    def test_build_decision_snapshot_sol_application_uses_application_technique(self) -> None:
        snapshot = decision.build_decision_snapshot(
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
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_type"], "sol")
        self.assertFalse(snapshot["application_block_active"])
        self.assertTrue(snapshot["application_post_watering_ready"])
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertTrue(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "application_technique")
        self.assertEqual(snapshot["arrosage_conseille"], "application_technique")
        self.assertGreater(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["decision_resume"]["type_arrosage"], "application_technique")
        self.assertEqual(snapshot["application_irrigation_mode"], "auto")

    def test_build_decision_snapshot_sol_application_manual_mode_requires_button(self) -> None:
        snapshot = decision.build_decision_snapshot(
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
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_irrigation_mode"], "manuel")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "application_technique")
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
        self.assertEqual(snapshot["fenetre_optimale"], "demain_matin")
        self.assertEqual(snapshot["watering_target_date"], "2026-03-18")
        self.assertIn("demain matin", snapshot["conseil_principal"])
        self.assertNotIn("ce matin", snapshot["conseil_principal"])
        self.assertIn("20 à 30 min", snapshot["action_recommandee"])

    def test_compute_objectif_mm_sursemis_germination_is_more_humid(self) -> None:
        germination = decision.compute_objectif_mm(
            phase_dominante="Sursemis",
            sous_phase="Germination",
            water_balance={
                "bilan_hydrique_mm": 0.8,
                "deficit_3j": 1.5,
                "deficit_7j": 3.0,
            },
            today=date(2026, 3, 17),
            pluie_demain=0,
            humidite=60,
            temperature=18.0,
            etp=1.2,
            type_sol="limoneux",
        )
        enracinement = decision.compute_objectif_mm(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": 0.8,
                "deficit_3j": 1.5,
                "deficit_7j": 3.0,
            },
            today=date(2026, 3, 17),
            pluie_demain=0,
            humidite=60,
            temperature=18.0,
            etp=1.2,
            type_sol="limoneux",
        )

        self.assertGreater(germination, enracinement)
        self.assertGreater(germination, 0.0)

    def test_compute_objectif_mm_keeps_small_sursemis_watering_floor(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": 10.8,
                "deficit_3j": 2.8,
                "deficit_7j": 8.6,
            },
            today=date(2026, 3, 17),
            pluie_demain=0,
            humidite=50,
            temperature=18.7,
            etp=1.4,
            type_sol="limoneux",
        )

        self.assertEqual(objectif, 0.5)

    def test_compute_action_guidance_sursemis_waits_until_6am(self) -> None:
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

        early = decision.compute_action_guidance(hour_of_day=5, **base_kwargs)
        acceptable = decision.compute_action_guidance(hour_of_day=6, **base_kwargs)

        self.assertEqual(early["fenetre_optimale"], "demain_matin")
        self.assertEqual(acceptable["fenetre_optimale"], "maintenant")

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

        self.assertEqual(cool["watering_window_start_minute"], 330)
        self.assertEqual(cool["watering_window_end_minute"], 600)
        self.assertEqual(hot["watering_window_start_minute"], 360)
        self.assertEqual(hot["watering_window_end_minute"], 540)
        self.assertEqual(cool["watering_window_profile"], "cool")
        self.assertEqual(hot["watering_window_profile"], "hot")

    def test_compute_action_guidance_allows_evening_when_conditions_match(self) -> None:
        guidance = decision.compute_action_guidance(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.6,
                "deficit_3j": 2.1,
                "deficit_7j": 3.9,
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
            objectif_mm=2.0,
            hour_of_day=19,
        )

        self.assertEqual(guidance["fenetre_optimale"], "soir")
        self.assertTrue(guidance["watering_evening_allowed"])
        self.assertEqual(guidance["watering_evening_start_minute"], 1080)
        self.assertEqual(guidance["watering_evening_end_minute"], 1260)

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

    def test_build_decision_snapshot_sursemis_objectif_zero_never_recommends_zero_mm(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            pluie_24h=1.0,
            pluie_demain=3.0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=0.5,
        )

        self.assertEqual(snapshot["phase_active"], "Sursemis")
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["niveau_action"], "surveiller")
        self.assertEqual(snapshot["decision_resume"]["action"], "surveillance")
        self.assertNotIn("0.0 mm", snapshot["action_recommandee"])
        self.assertNotIn("0.0 mm", snapshot["conseil_principal"])
        self.assertEqual(snapshot["action_a_eviter"], "Éviter tout arrosage inutile.")

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
        self.assertEqual(snapshot["type_arrosage"], "application_technique")
        self.assertEqual(snapshot["arrosage_conseille"], "application_technique")
        self.assertGreater(snapshot["objectif_mm"], 0.0)
        self.assertIn("arrose", snapshot["conseil_principal"].lower())
        self.assertIn("application technique", snapshot["raison_decision"].lower())

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

        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 8.0)
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

        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 9.0)

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

        self.assertGreaterEqual(snapshot["hauteur_tonte_recommandee_cm"], 6.5)
        self.assertLessEqual(snapshot["hauteur_tonte_recommandee_cm"], 7.0)

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


if __name__ == "__main__":
    unittest.main()
