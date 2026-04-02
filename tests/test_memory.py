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
                "note": "Appliquer au matin",
            },
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["id"], "engrais_printemps")
        self.assertEqual(record["nom"], "Engrais printemps")
        self.assertEqual(record["type"], "Fertilisation")
        self.assertEqual(record["dose_conseillee"], "12.5")
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

        self.assertTrue(ready_state["application_post_watering_ready"])
        self.assertEqual(ready_state["application_post_watering_delay_remaining_minutes"], 0.0)

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
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "humuslight": {
                    "id": "humuslight",
                    "nom": "Humuslight",
                    "type": "Biostimulant",
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
        self.assertFalse(recommendation["ready_to_declare"])
        self.assertEqual(recommendation["selection"]["id"], None)
        self.assertTrue(all(isinstance(item, dict) for item in recommendation["constraints"]))
        self.assertTrue(all(isinstance(item, dict) for item in recommendation["missing_requirements"]))
