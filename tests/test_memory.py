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

memory = importlib.import_module("custom_components.gazon_intelligent.memory")
intervention = importlib.import_module("custom_components.gazon_intelligent.intervention_recommendation")


class MemoryCatalogTests(unittest.TestCase):
    def test_auto_irrigation_enabled_defaults_to_true_and_persists(self) -> None:
        fresh_memory = memory.compute_memory([], today=date(2026, 3, 18))
        self.assertTrue(fresh_memory["auto_irrigation_enabled"])

        persisted = memory.compute_memory(
            [],
            today=date(2026, 3, 18),
            previous_memory={"auto_irrigation_enabled": False},
        )
        self.assertFalse(persisted["auto_irrigation_enabled"])

    def test_normalize_product_record_keeps_simple_catalog_fields(self) -> None:
        record = memory.normalize_product_record(
            "Engrais Printemps",
            {
                "nom": "Engrais printemps",
                "type": "Fertilisation",
                "dose_conseillee": "12.5",
                "usage_mode": "Entretien",
                "max_applications_per_year": "6",
                "reapplication_after_days": "21",
                "delai_avant_tonte_jours": "2",
                "phase_compatible": ["Sursemis", "Croissance", "Entretien"],
                "application_months": "3,4,5,9,10",
                "application_type": "sol",
                "application_requires_watering_after": "true",
                "application_post_watering_mm": "1.5",
                "application_irrigation_block_hours": "0",
                "application_irrigation_delay_minutes": "15",
                "application_irrigation_mode": "manuel",
                "application_label_notes": "Appliquer au matin",
                "temperature_min": "8",
                "temperature_max": "28",
                "note": "Appliquer au matin",
            },
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["id"], "engrais_printemps")
        self.assertEqual(record["nom"], "Engrais printemps")
        self.assertEqual(record["type"], "Fertilisation")
        self.assertEqual(record["dose_conseillee"], "12.5")
        self.assertEqual(record["usage_mode"], "entretien")
        self.assertEqual(record["max_applications_per_year"], 6)
        self.assertEqual(record["reapplication_after_days"], 21)
        self.assertEqual(record["delai_avant_tonte_jours"], 2)
        self.assertEqual(record["phase_compatible"], ["Sursemis", "Croissance", "Entretien"])
        self.assertEqual(record["application_months"], [3, 4, 5, 9, 10])
        self.assertEqual(record["application_months_label"], "Mars à Mai, Septembre à Octobre")
        self.assertEqual(record["application_type"], "sol")
        self.assertTrue(record["application_requires_watering_after"])
        self.assertEqual(record["application_post_watering_mm"], 1.5)
        self.assertEqual(record["application_irrigation_block_hours"], 0.0)
        self.assertEqual(record["application_irrigation_delay_minutes"], 15.0)
        self.assertEqual(record["application_irrigation_mode"], "manuel")
        self.assertEqual(record["application_label_notes"], "Appliquer au matin")
        self.assertEqual(record["temperature_min"], 8.0)
        self.assertEqual(record["temperature_max"], 28.0)

    def test_application_months_helpers_normalize_and_format_ranges(self) -> None:
        months = memory.normalize_application_months("mars à mai + septembre à octobre")
        self.assertEqual(months, [3, 4, 5, 9, 10])
        self.assertEqual(memory.format_application_months_label(months), "Mars à Mai, Septembre à Octobre")

    def test_build_application_summary_includes_product_id(self) -> None:
        summary = memory.build_application_summary(
            {
                "type": "Fertilisation",
                "date": "2026-03-18",
                "produit_id": "engrais_printemps",
                "produit": "Engrais printemps",
                "dose": "12.5",
                "zone": "zone_1",
                "note": "Test",
                "reapplication_after_days": 21,
                "source": "service",
                "application_type": "sol",
                "application_requires_watering_after": True,
                "application_post_watering_mm": 1.0,
                "application_irrigation_block_hours": 0.0,
                "application_irrigation_delay_minutes": 30.0,
                "application_irrigation_mode": "auto",
                "application_label_notes": "Notes produit",
                "produit_catalogue": {
                    "id": "engrais_printemps",
                    "nom": "Engrais printemps",
                    "application_months": [3, 4, 5, 9, 10],
                },
                "declared_at": "2026-03-18T08:00:00+00:00",
            }
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["produit_id"], "engrais_printemps")
        self.assertEqual(summary["libelle"], "Engrais printemps")
        self.assertEqual(summary["reapplication_after_days"], 21)
        self.assertEqual(summary["application_type"], "sol")
        self.assertTrue(summary["application_requires_watering_after"])
        self.assertEqual(summary["application_post_watering_mm"], 1.0)
        self.assertEqual(summary["application_irrigation_block_hours"], 0.0)
        self.assertEqual(summary["application_irrigation_delay_minutes"], 30.0)
        self.assertEqual(summary["application_irrigation_mode"], "auto")
        self.assertEqual(summary["application_label_notes"], "Notes produit")
        self.assertEqual(summary["application_months"], [3, 4, 5, 9, 10])
        self.assertEqual(summary["application_months_label"], "Mars à Mai, Septembre à Octobre")
        self.assertEqual(summary["date_action"], "2026-03-18")
        self.assertEqual(summary["declared_at"], "2026-03-18T08:00:00+00:00")

    def test_compute_application_state_tracks_block_and_pending_water(self) -> None:
        state = memory.compute_application_state(
            [
                {
                    "type": "Traitement",
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "produit": "Fongicide X",
                    "application_type": "foliaire",
                    "application_requires_watering_after": False,
                    "application_post_watering_mm": 0.0,
                    "application_irrigation_block_hours": 24.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "suggestion",
                    "application_label_notes": "Attendre 24 h",
                },
                {
                    "type": "arrosage",
                    "date": "2026-03-18",
                    "objectif_mm": 0.5,
                    "source": "manual",
                },
            ],
            now=memory.datetime(2026, 3, 18, 9, 0, tzinfo=memory.timezone.utc),
        )

        self.assertEqual(state["application_type"], "foliaire")
        self.assertFalse(state["application_requires_watering_after"])
        self.assertEqual(state["application_post_watering_status"], "bloque")
        self.assertEqual(state["application_irrigation_block_hours"], 24.0)
        self.assertEqual(state["application_irrigation_delay_minutes"], 0.0)
        self.assertEqual(state["application_irrigation_mode"], "suggestion")
        self.assertTrue(state["application_block_active"])
        self.assertGreater(state["application_block_remaining_minutes"], 0.0)
        self.assertFalse(state["application_post_watering_pending"])
        self.assertFalse(state["application_post_watering_ready"])
        self.assertEqual(state["application_post_watering_remaining_mm"], 0.0)

    def test_compute_application_state_tracks_delay_and_ready(self) -> None:
        state = memory.compute_application_state(
            [
                {
                    "type": "Fertilisation",
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "produit": "Engrais printemps",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 90.0,
                    "application_irrigation_mode": "manuel",
                }
            ],
            now=memory.datetime(2026, 3, 18, 8, 45, tzinfo=memory.timezone.utc),
        )

        self.assertEqual(state["application_post_watering_status"], "en_attente")
        self.assertEqual(state["application_irrigation_delay_minutes"], 90.0)
        self.assertEqual(state["application_irrigation_mode"], "manuel")
        self.assertFalse(state["application_post_watering_ready"])
        self.assertGreater(state["application_post_watering_delay_remaining_minutes"], 0.0)

        ready_state = memory.compute_application_state(
            [
                {
                    "type": "Fertilisation",
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "produit": "Engrais printemps",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 30.0,
                    "application_irrigation_mode": "auto",
                }
            ],
            now=memory.datetime(2026, 3, 18, 8, 45, tzinfo=memory.timezone.utc),
        )

        self.assertEqual(ready_state["application_post_watering_status"], "autorise")
        self.assertTrue(ready_state["application_post_watering_ready"])
        self.assertEqual(ready_state["application_post_watering_delay_remaining_minutes"], 0.0)

    def test_compute_application_state_marks_completed_post_watering(self) -> None:
        state = memory.compute_application_state(
            [
                {
                    "type": "Fertilisation",
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "produit": "Engrais printemps",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 30.0,
                    "application_irrigation_mode": "auto",
                },
                {
                    "type": "arrosage",
                    "date": "2026-03-18",
                    "objectif_mm": 1.2,
                    "source": "manual",
                },
            ],
            now=memory.datetime(2026, 3, 18, 9, 0, tzinfo=memory.timezone.utc),
        )

        self.assertEqual(state["application_post_watering_status"], "termine")
        self.assertFalse(state["application_post_watering_pending"])
        self.assertEqual(state["application_post_watering_remaining_mm"], 0.0)

    def test_compute_application_state_marks_non_required_post_watering(self) -> None:
        state = memory.compute_application_state(
            [
                {
                    "type": "Biostimulant",
                    "date": "2026-03-12",
                    "declared_at": "2026-04-01T21:24:28.946171+00:00",
                    "produit": "Humuslight",
                    "application_type": "sol",
                    "application_requires_watering_after": False,
                    "application_post_watering_mm": 0.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "suggestion",
                }
            ],
            now=memory.datetime(2026, 4, 2, 9, 0, tzinfo=memory.timezone.utc),
        )

        self.assertEqual(state["application_post_watering_status"], "non_requis")
        self.assertFalse(state["application_block_active"])
        self.assertFalse(state["application_post_watering_pending"])
        self.assertFalse(state["application_post_watering_ready"])

    def test_normalize_post_application_status_accepts_legacy_non_autorise(self) -> None:
        self.assertEqual(memory.normalize_post_application_status("non_autorise"), "termine")

    def test_compute_next_reapplication_date_prefers_latest_item(self) -> None:
        next_date = memory.compute_next_reapplication_date(
            [
                {"type": "Fertilisation", "date": "2026-03-01", "reapplication_after_days": 21},
                {"type": "Biostimulant", "date": "2026-03-10", "reapplication_after_days": 25},
            ],
            today=date(2026, 3, 18),
        )

        self.assertEqual(next_date, "2026-04-04")

    def test_compute_memory_builds_feedback_observation_without_name_error(self) -> None:
        history = [
            {
                "type": "arrosage",
                "date": "2026-03-18",
                "objectif_mm": 1.2,
                "source": "auto",
            }
        ]

        memory_state = memory.compute_memory(
            history,
            today=date(2026, 3, 19),
            previous_memory={
                "dernier_conseil": {
                    "date": "2026-03-18",
                    "objectif_mm": 1.2,
                },
                "date_derniere_mise_a_jour": "2026-03-18",
            },
            decision={
                "deficit_mm_ajuste": 0.8,
                "deficit_brut_mm": 1.0,
                "objectif_mm": 0.8,
                "type_arrosage": "auto",
                "risque_gazon": "modere",
                "heat_stress_level": "normal",
                "mm_final": 0.8,
            },
        )

        self.assertIsNotNone(memory_state["feedback_observation"])
        assert memory_state["feedback_observation"] is not None
        self.assertEqual(memory_state["feedback_observation"]["window"], "24h")
        self.assertEqual(memory_state["feedback_observation"]["recommended_mm"], 1.2)
        self.assertEqual(memory_state["feedback_observation"]["observed_mm"], 1.2)
        self.assertEqual(memory_state["feedback_observation"]["delta_mm"], 0.0)
        self.assertEqual(memory_state["feedback_observation"]["source"], "observation_only")

    def test_build_intervention_recommendation_prefers_in_season_due_product(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Sursemis",
            phase_source="historique_actif",
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            temperature=20.0,
            forecast_temperature_today=19.0,
            temperature_source="capteur",
            products={
                "humuslight": {
                    "id": "humuslight",
                    "nom": "Humuslight",
                    "type": "Biostimulant",
                    "usage_mode": "preventif",
                    "max_applications_per_year": 2,
                    "reapplication_after_days": 25,
                    "phase_compatible": ["Sursemis", "Croissance", "Entretien"],
                    "application_months": [3, 4, 5, 9, 10],
                    "temperature_min": 8,
                    "temperature_max": 28,
                }
            },
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-12",
                    "produit_id": "humuslight",
                    "produit": "Humuslight",
                    "reapplication_after_days": 25,
                    "produit_catalogue": {
                        "id": "humuslight",
                        "nom": "Humuslight",
                    },
                }
            ],
            application_state={},
        )

        self.assertEqual(recommendation["schema_version"], 3)
        self.assertEqual(recommendation["status"], "recommended")
        self.assertIsInstance(recommendation["score"], int)
        self.assertGreaterEqual(recommendation["score"], 0)
        self.assertLessEqual(recommendation["score"], 100)
        self.assertEqual(recommendation["product"]["id"], "humuslight")
        self.assertEqual(recommendation["product"]["months_label"], "Mars à Mai, Septembre à Octobre")
        self.assertTrue(recommendation["product"]["phase_match"])
        self.assertTrue(recommendation["product"]["month_match"])
        self.assertTrue(recommendation["product"]["due"])
        self.assertTrue(any(item.get("code") == "temperature_range" and item.get("met") for item in recommendation["constraints"]))
        self.assertFalse(recommendation["ready_to_declare"])
        self.assertEqual(recommendation["selection"]["id"], None)
        self.assertTrue(all(isinstance(item, dict) for item in recommendation["constraints"]))
        self.assertTrue(all(isinstance(item, dict) for item in recommendation["missing_requirements"]))
        self.assertEqual(recommendation["context"]["current_phase_source"], "historique_actif")
        self.assertFalse(recommendation["context"]["current_phase_is_default_normal"])
        self.assertEqual(
            next(item for item in recommendation["constraints"] if item.get("code") == "phase_compatibility")["value"]["current"],
            "Sursemis",
        )
        self.assertEqual(
            next(item for item in recommendation["constraints"] if item.get("code") == "application_months")["value"]["current_month"],
            4,
        )

    def test_build_intervention_recommendation_keeps_low_score_candidate_possible(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Sursemis",
            phase_source="historique_actif",
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "simple": {
                    "id": "simple",
                    "nom": "Simple",
                    "type": "Biostimulant",
                    "usage_mode": "preventif",
                    "phase_compatible": ["Sursemis"],
                    "application_months": [4],
                }
            },
            history=[],
            application_state={},
            temperature=20.0,
            forecast_temperature_today=20.0,
            temperature_source="capteur",
        )

        self.assertEqual(recommendation["status"], "possible")
        self.assertEqual(recommendation["recommended_action"], "select_product")
        self.assertLess(recommendation["score"], 71)

    def test_build_intervention_recommendation_marks_default_normal_source(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "simple": {
                    "id": "simple",
                    "nom": "Simple",
                    "type": "Biostimulant",
                    "usage_mode": "preventif",
                    "phase_compatible": ["Normal"],
                    "application_months": [4],
                }
            },
            history=[],
            application_state={},
            temperature=20.0,
            forecast_temperature_today=20.0,
            temperature_source="capteur",
        )

        self.assertEqual(recommendation["context"]["current_phase"], "Normal")
        self.assertEqual(recommendation["context"]["current_phase_source"], "absence_phase")
        self.assertTrue(recommendation["context"]["current_phase_is_default_normal"])

    def test_build_intervention_recommendation_uses_explicit_block_reason_for_preventive_wetting_agent(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "mouillant_preventif": {
                    "id": "mouillant_preventif",
                    "nom": "Mouillant préventif",
                    "type": "Agent Mouillant",
                    "usage_mode": "preventif",
                    "phase_compatible": ["Normal"],
                    "application_months": [4],
                }
            },
            history=[],
            application_state={
                "application_block_active": True,
                "application_block_reason": "sol déjà humide",
            },
            temperature=20.0,
            forecast_temperature_today=20.0,
            temperature_source="capteur",
        )

        self.assertEqual(recommendation["status"], "blocked")
        self.assertIn("Agent mouillant préventif", recommendation["reason"])
        self.assertIn("sol déjà humide", recommendation["reason"])

    def test_build_intervention_recommendation_penalizes_fertilisation_more_than_biostimulant_in_normal_phase(self) -> None:
        fertilisation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "engrais": {
                    "id": "engrais",
                    "nom": "Engrais test",
                    "type": "Fertilisation",
                    "usage_mode": "entretien",
                    "max_applications_per_year": 2,
                    "reapplication_after_days": 25,
                    "phase_compatible": ["Normal"],
                    "application_months": [4],
                    "temperature_min": 8,
                    "temperature_max": 28,
                }
            },
            history=[
                {
                    "type": "Fertilisation",
                    "date": "2026-03-12",
                    "produit_id": "engrais",
                    "produit": "Engrais test",
                    "reapplication_after_days": 25,
                    "produit_catalogue": {
                        "id": "engrais",
                        "nom": "Engrais test",
                    },
                }
            ],
            application_state={},
            temperature=20.0,
            forecast_temperature_today=20.0,
            temperature_source="capteur",
        )

        biostimulant = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "stim": {
                    "id": "stim",
                    "nom": "Stim test",
                    "type": "Biostimulant",
                    "usage_mode": "entretien",
                    "max_applications_per_year": 2,
                    "reapplication_after_days": 25,
                    "phase_compatible": ["Normal"],
                    "application_months": [4],
                    "temperature_min": 8,
                    "temperature_max": 28,
                }
            },
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-12",
                    "produit_id": "stim",
                    "produit": "Stim test",
                    "reapplication_after_days": 25,
                    "produit_catalogue": {
                        "id": "stim",
                        "nom": "Stim test",
                    },
                }
            ],
            application_state={},
            temperature=20.0,
            forecast_temperature_today=20.0,
            temperature_source="capteur",
        )

        self.assertLess(fertilisation["score"], biostimulant["score"])
        self.assertEqual(fertilisation["status"], "recommended")
        self.assertEqual(biostimulant["status"], "recommended")

    def test_build_intervention_recommendation_gives_mouillant_curatif_more_priority_than_preventif_on_clear_opportunity(self) -> None:
        preventif = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Sursemis",
            phase_source="historique_actif",
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "mouillant_preventif": {
                    "id": "mouillant_preventif",
                    "nom": "Mouillant préventif",
                    "type": "Agent Mouillant",
                    "usage_mode": "preventif",
                    "max_applications_per_year": 6,
                    "reapplication_after_days": 21,
                    "phase_compatible": ["Sursemis", "Croissance", "Entretien"],
                    "application_months": [4, 5, 6, 7, 8, 9],
                    "temperature_min": 10,
                    "temperature_max": 30,
                }
            },
            history=[],
            application_state={
                "bilan_hydrique_mm": -1.2,
                "hydric_balance_level": "déficit",
            },
            temperature=20.0,
            forecast_temperature_today=20.0,
            temperature_source="capteur",
        )

        curatif = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Sursemis",
            phase_source="historique_actif",
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "mouillant_curatif": {
                    "id": "mouillant_curatif",
                    "nom": "Mouillant curatif",
                    "type": "Agent Mouillant",
                    "usage_mode": "curatif",
                    "max_applications_per_year": 6,
                    "reapplication_after_days": 21,
                    "phase_compatible": ["Sursemis", "Croissance", "Entretien"],
                    "application_months": [4, 5, 6, 7, 8, 9],
                    "temperature_min": 10,
                    "temperature_max": 30,
                }
            },
            history=[],
            application_state={
                "bilan_hydrique_mm": -1.2,
                "hydric_balance_level": "déficit",
            },
            temperature=20.0,
            forecast_temperature_today=20.0,
            temperature_source="capteur",
        )

        self.assertLess(preventif["score"], curatif["score"])
        self.assertIn(preventif["status"], {"possible", "recommended"})
        self.assertIn(curatif["status"], {"possible", "recommended"})

    def test_build_intervention_recommendation_blocks_when_temperature_is_far_out_of_range(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Sursemis",
            phase_source="historique_actif",
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            temperature=35.0,
            forecast_temperature_today=35.0,
            temperature_source="capteur",
            products={
                "humuslight": {
                    "id": "humuslight",
                    "nom": "Humuslight",
                    "type": "Biostimulant",
                    "usage_mode": "preventif",
                    "max_applications_per_year": 2,
                    "reapplication_after_days": 25,
                    "phase_compatible": ["Sursemis", "Croissance", "Entretien"],
                    "application_months": [3, 4, 5, 9, 10],
                    "temperature_min": 8,
                    "temperature_max": 28,
                }
            },
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-12",
                    "produit_id": "humuslight",
                    "produit": "Humuslight",
                    "reapplication_after_days": 25,
                    "produit_catalogue": {
                        "id": "humuslight",
                        "nom": "Humuslight",
                    },
                }
            ],
            application_state={},
        )

        self.assertEqual(recommendation["status"], "blocked")
        self.assertEqual(recommendation["recommended_action"], "wait")
        self.assertTrue(
            any(item.get("code") == "temperature_range" and item.get("blocking") for item in recommendation["constraints"])
        )
        self.assertTrue(
            any(item.get("code") == "temperature_out_of_range" for item in recommendation["missing_requirements"])
        )

    def test_build_intervention_recommendation_blocks_when_annual_limit_is_reached(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Sursemis",
            phase_source="historique_actif",
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "humuslight": {
                    "id": "humuslight",
                    "nom": "Humuslight",
                    "type": "Biostimulant",
                    "usage_mode": "preventif",
                    "max_applications_per_year": 1,
                    "reapplication_after_days": 25,
                    "phase_compatible": ["Sursemis", "Croissance", "Entretien"],
                    "application_months": [3, 4, 5, 9, 10],
                }
            },
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-12",
                    "produit_id": "humuslight",
                    "produit": "Humuslight",
                    "reapplication_after_days": 25,
                    "produit_catalogue": {
                        "id": "humuslight",
                        "nom": "Humuslight",
                    },
                }
            ],
            application_state={},
        )

        self.assertEqual(recommendation["status"], "blocked")
        self.assertEqual(recommendation["recommended_action"], "wait")
        self.assertTrue(
            any(item.get("code") == "annual_applications_limit" for item in recommendation["constraints"])
        )

    def test_build_intervention_recommendation_blocks_when_post_application_context_is_not_ready(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Sursemis",
            phase_source="historique_actif",
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "humuslight": {
                    "id": "humuslight",
                    "nom": "Humuslight",
                    "type": "Biostimulant",
                    "usage_mode": "preventif",
                    "max_applications_per_year": 2,
                    "reapplication_after_days": 25,
                    "phase_compatible": ["Sursemis", "Croissance", "Entretien"],
                    "application_months": [3, 4, 5, 9, 10],
                    "temperature_min": 8,
                    "temperature_max": 28,
                }
            },
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-12",
                    "produit_id": "humuslight",
                    "produit": "Humuslight",
                    "reapplication_after_days": 25,
                    "produit_catalogue": {
                        "id": "humuslight",
                        "nom": "Humuslight",
                    },
                }
            ],
            application_state={
                "application_post_watering_status": "en_attente",
            },
        )

        self.assertEqual(recommendation["status"], "blocked")
        self.assertEqual(recommendation["recommended_action"], "wait")
        self.assertTrue(
            any(
                "post-application" in str(item.get("hint") or "").lower() or "post-application" in str(item.get("label") or "").lower()
                for item in recommendation["missing_requirements"]
            )
        )
