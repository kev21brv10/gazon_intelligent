from __future__ import annotations

import unittest
from datetime import date
from importlib import util
from pathlib import Path
import sys


def _load_decision_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "gazon_intelligent"
        / "decision.py"
    )
    spec = util.spec_from_file_location("gazon_intelligent_decision", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {module_path}")
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


decision = _load_decision_module()


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
            {"type": "arrosage", "date": "2026-03-16", "objectif_mm": 3.0},
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
        self.assertTrue(snapshot["tonte_autorisee"])

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
        self.assertIn("20 à 30 min", snapshot["conseil_principal"])
        self.assertIn("20 à 30 min", snapshot["action_recommandee"])

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
