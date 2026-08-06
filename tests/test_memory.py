from __future__ import annotations

import unittest
from datetime import date
import importlib
from pathlib import Path
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch



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


def _ensure_homeassistant_dt_module() -> None:
    if "homeassistant.util.dt" in sys.modules:
        return
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
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=timezone.utc)  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_ensure_homeassistant_dt_module()

memory = importlib.import_module("custom_components.gazon_intelligent.memory")
const = importlib.import_module("custom_components.gazon_intelligent.const")
intervention = importlib.import_module("custom_components.gazon_intelligent.intervention_recommendation")
decision_models = importlib.import_module("custom_components.gazon_intelligent.decision_models")
phases = importlib.import_module("custom_components.gazon_intelligent.phases")
guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")


class MemoryCatalogTests(unittest.TestCase):
    def test_auto_irrigation_enabled_defaults_to_false_and_persists_confirmation(self) -> None:
        fresh_memory = memory.compute_memory([], today=date(2026, 3, 18))
        self.assertFalse(fresh_memory["auto_irrigation_enabled"])

        persisted = memory.compute_memory(
            [],
            today=date(2026, 3, 18),
            previous_memory={
                "auto_irrigation_enabled": True,
            },
        )
        self.assertTrue(persisted["auto_irrigation_enabled"])

    def test_mower_coordination_enabled_defaults_to_false_and_persists(self) -> None:
        fresh_memory = memory.compute_memory([], today=date(2026, 3, 18))
        self.assertFalse(fresh_memory["mower_coordination_enabled"])

        persisted = memory.compute_memory(
            [],
            today=date(2026, 3, 18),
            previous_memory={"mower_coordination_enabled": True},
        )
        self.assertTrue(persisted["mower_coordination_enabled"])

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

    def test_post_watering_pending_only_on_application_day(self) -> None:
        # L'arrosage technique d'incorporation (pending → conseil + override + auto)
        # ne doit se déclencher que le JOUR MÊME de l'épandage. Pour une application
        # plus ancienne (ex. déclarée rétroactivement), l'incorporation est présumée
        # faite → ni pending, ni ready, ni objectif.
        def _state(application_date: str, now: "memory.datetime") -> dict:
            return memory.compute_application_state(
                [
                    {
                        "type": "Fertilisation",
                        "date": application_date,
                        "declared_at": "2026-06-09T18:00:00+00:00",
                        "produit": "Floranid Twin Permanent",
                        "application_type": "sol",
                        "application_requires_watering_after": True,
                        "application_post_watering_mm": 1.0,
                        "application_irrigation_block_hours": 0.0,
                        "application_irrigation_delay_minutes": 0.0,
                        "application_irrigation_mode": "auto",
                    }
                ],
                now=now,
            )

        # 1. Jour même → pending actif (non-régression du cas légitime).
        same_day = _state("2026-06-09", memory.datetime(2026, 6, 9, 18, 0, tzinfo=memory.timezone.utc))
        self.assertTrue(same_day["application_post_watering_pending"])
        self.assertTrue(same_day["application_post_watering_ready"])
        self.assertGreater(same_day["application_post_watering_remaining_mm"], 0.0)

        # 2. Application antérieure (J-4, déclarée rétroactivement) → plus de pending.
        old = _state("2026-06-06", memory.datetime(2026, 6, 10, 8, 0, tzinfo=memory.timezone.utc))
        self.assertFalse(old["application_post_watering_pending"])
        self.assertFalse(old["application_post_watering_ready"])
        self.assertEqual(old["application_post_watering_status"], "termine")

        # 3. Cas limite J-1 : la bascule se fait bien dès le lendemain (J+1).
        yesterday = _state("2026-06-09", memory.datetime(2026, 6, 10, 0, 30, tzinfo=memory.timezone.utc))
        self.assertFalse(yesterday["application_post_watering_pending"])
        self.assertFalse(yesterday["application_post_watering_ready"])

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
        self.assertFalse(state["application_post_watering_ready"])
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

    def test_compute_application_state_tolerates_dirty_history_and_invalid_dates(self) -> None:
        state = memory.compute_application_state(
            [
                "invalid",
                None,
                {
                    "date": "2026-03-18",
                    "declared_at": "not-a-date",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_delay_minutes": 30.0,
                    "application_irrigation_mode": "auto",
                },
            ],
            now=memory.datetime(2026, 3, 18, 8, 45, tzinfo=memory.timezone.utc),
        )

        self.assertIsNone(state["derniere_application"])
        self.assertEqual(state["application_type"], "sol")
        self.assertTrue(state["application_requires_watering_after"])
        self.assertFalse(state["application_block_active"])
        self.assertEqual(state["application_post_watering_status"], "autorise")
        self.assertTrue(state["application_post_watering_pending"])
        self.assertTrue(state["application_post_watering_ready"])
        self.assertEqual(state["application_post_watering_remaining_mm"], 1.0)

    def test_compute_application_state_keeps_block_priority_over_post_watering(self) -> None:
        state = memory.compute_application_state(
            [
                {
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 2.0,
                    "application_irrigation_delay_minutes": 30.0,
                    "application_irrigation_mode": "auto",
                }
            ],
            now=memory.datetime(2026, 3, 18, 8, 15, tzinfo=memory.timezone.utc),
        )

        self.assertTrue(state["application_block_active"])
        self.assertEqual(state["application_post_watering_status"], "bloque")
        self.assertTrue(state["application_post_watering_pending"])
        self.assertFalse(state["application_post_watering_ready"])
        self.assertGreater(state["application_block_remaining_minutes"], 0.0)

    def test_compute_application_state_transitions_block_then_delay_then_authorized(self) -> None:
        history = [
            {
                "date": "2026-03-18",
                "declared_at": "2026-03-18T08:00:00+00:00",
                "application_type": "sol",
                "application_requires_watering_after": True,
                "application_post_watering_mm": 2.0,
                "application_irrigation_block_hours": 2.0,
                "application_irrigation_delay_minutes": 30.0,
                "application_irrigation_mode": "auto",
            }
        ]

        blocked = memory.compute_application_state(
            history,
            now=memory.datetime(2026, 3, 18, 8, 20, tzinfo=memory.timezone.utc),
        )
        self.assertEqual(blocked["application_post_watering_status"], "bloque")
        self.assertTrue(blocked["application_block_active"])

        still_blocked_after_delay = memory.compute_application_state(
            history,
            now=memory.datetime(2026, 3, 18, 8, 45, tzinfo=memory.timezone.utc),
        )
        self.assertEqual(still_blocked_after_delay["application_post_watering_status"], "bloque")
        self.assertTrue(still_blocked_after_delay["application_block_active"])
        self.assertFalse(still_blocked_after_delay["application_post_watering_ready"])

        ready_after_block = memory.compute_application_state(
            history,
            now=memory.datetime(2026, 3, 18, 10, 5, tzinfo=memory.timezone.utc),
        )
        self.assertEqual(ready_after_block["application_post_watering_status"], "autorise")
        self.assertFalse(ready_after_block["application_block_active"])
        self.assertTrue(ready_after_block["application_post_watering_ready"])

    def test_compute_next_reapplication_date_ignores_invalid_latest_date(self) -> None:
        next_date = memory.compute_next_reapplication_date(
            [
                {"type": "Fertilisation", "date": "2026-03-01", "reapplication_after_days": 21},
                {"type": "Biostimulant", "date": "invalid", "reapplication_after_days": 25},
            ],
            today=date(2026, 3, 18),
        )

        self.assertIsNone(next_date)

    def test_compute_memory_ignores_partial_feedback_with_invalid_advice_date(self) -> None:
        memory_state = memory.compute_memory(
            [],
            today=date(2026, 3, 19),
            previous_memory={
                "dernier_conseil": {
                    "date": "invalid",
                    "objectif_mm": 1.2,
                },
                "date_derniere_mise_a_jour": "2026-03-18",
            },
            decision={
                "objectif_mm": 0.8,
            },
        )

        self.assertIsNone(memory_state["feedback_observation"])

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

    def test_build_intervention_recommendation_normal_phase_is_neutral_for_maintenance_product(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 6, 18),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            temperature=22.0,
            forecast_temperature_today=22.0,
            temperature_source="capteur",
            products={
                "h2pro_trismart": {
                    "id": "h2pro_trismart",
                    "nom": "H2Pro TriSmart",
                    "type": "Agent Mouillant",
                    "usage_mode": "preventif",
                    "max_applications_per_year": 8,
                    "reapplication_after_days": 28,
                    "phase_compatible": ["Croissance", "Entretien"],
                    "application_months": [3, 4, 5, 6, 7, 8, 9, 10],
                    "temperature_min": 10,
                    "temperature_max": 30,
                }
            },
            history=[
                {
                    "type": "Agent Mouillant",
                    "date": "2026-04-30",
                    "produit_id": "h2pro_trismart",
                    "produit": "H2Pro TriSmart",
                    "reapplication_after_days": 28,
                    "produit_catalogue": {"id": "h2pro_trismart", "nom": "H2Pro TriSmart"},
                }
            ],
            application_state={},
        )

        # En phase Normal, un produit d'entretien n'est pas "hors phase" : la contrainte de
        # phase est neutre (met=True), sans pénalité, mais le produit ne passe pas
        # "recommandé" pour autant (phase_match reste False → reste "à préparer").
        self.assertFalse(recommendation["product"]["phase_match"])
        self.assertNotEqual(recommendation["status"], "recommended")
        phase_constraint = next(
            item for item in recommendation["constraints"] if item.get("code") == "phase_compatibility"
        )
        self.assertTrue(phase_constraint["met"])
        # Le libellé doit qualifier le PRODUIT ("entretien"), pas rebaptiser la phase du gazon,
        # qui est Normal : "Phase courante : entretien" faisait lire deux phases différentes
        # sur deux onglets de la carte. Il doit donc nommer la phase réelle.
        libelle = phase_constraint["label"].lower()
        self.assertIn("entretien", libelle)
        self.assertIn("normal", libelle)
        self.assertNotIn("phase courante", libelle)
        self.assertTrue(recommendation["context"]["current_phase_is_default_normal"])

    def test_build_intervention_recommendation_keeps_low_score_candidate_in_preparation(self) -> None:
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

        self.assertEqual(recommendation["status"], "preparation")
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

    def test_build_intervention_recommendation_softens_preparation_summary_for_weak_opportunity(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "humuslight": {
                    "id": "humuslight",
                    "nom": "Humuslight",
                    "type": "Biostimulant",
                    "usage_mode": "entretien",
                    "phase_compatible": ["Sursemis", "Croissance", "Entretien"],
                    "application_months": [3, 4, 5, 6, 7, 8, 9, 10],
                    "reapplication_after_days": 25,
                    "temperature_min": 8,
                    "temperature_max": 25,
                }
            },
            history=[
                {
                    "type": "Biostimulant",
                    "produit_id": "humuslight",
                    "produit": "Humuslight",
                    "date": "2026-03-12",
                    "date_action": "2026-03-12",
                    "reapplication_after_days": 25,
                }
            ],
            application_state={
                "type_arrosage": "aucune_action",
                "application_block_active": False,
                "application_post_watering_pending": False,
                "application_post_watering_status": "non_requis",
                "bilan_hydrique_mm": 21.7,
            },
            temperature=13.9,
            forecast_temperature_today=24.9,
            temperature_source="capteur",
        )

        self.assertEqual(recommendation["status"], "preparation")
        self.assertEqual(recommendation["context"]["opportunity_level"], "weak")
        self.assertEqual(recommendation["ui"]["summary"], "À envisager : Humuslight")

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
        self.assertIn(preventif["status"], {"preparation", "recommended"})
        self.assertIn(curatif["status"], {"preparation", "recommended"})

    def test_build_intervention_recommendation_blocks_when_temperature_far_too_cold(self) -> None:
        # Trop FROID (2 °C, attendu ≥ 8 °C) : on ne peut pas réchauffer → blocage maintenu.
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 10),
            phase_active="Sursemis",
            phase_source="historique_actif",
            sous_phase="Reprise",
            selected_product_id=None,
            selected_product_name=None,
            temperature=2.0,
            forecast_temperature_today=2.0,
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

    def test_build_intervention_recommendation_hot_day_advises_morning_not_blocked(self) -> None:
        # Trop CHAUD en journée (35 °C, max 28) : un produit s'applique tôt le matin → on NE
        # bloque PAS (sinon inapplicable tout l'été), on conseille le créneau frais du matin.
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
            history=[],
            application_state={},
        )

        self.assertNotEqual(recommendation["status"], "blocked")
        # La contrainte température existe mais n'est PAS bloquante.
        temp_constraint = next(
            (item for item in recommendation["constraints"] if item.get("code") == "temperature_range"),
            None,
        )
        self.assertIsNotNone(temp_constraint)
        self.assertFalse(temp_constraint.get("blocking"))
        self.assertNotIn(
            "temperature_out_of_range",
            [item.get("code") for item in recommendation.get("missing_requirements", [])],
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

    def test_build_intervention_recommendation_does_not_block_only_because_watering_profile_is_blocked(self) -> None:
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 4, 4),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            products={
                "h2pro_trismart": {
                    "id": "h2pro_trismart",
                    "nom": "H2Pro TriSmart",
                    "type": "Agent Mouillant",
                    "usage_mode": "preventif",
                    "max_applications_per_year": 6,
                    "reapplication_after_days": 28,
                    "phase_compatible": ["Croissance", "Entretien"],
                    "application_months": [4, 5, 6, 7, 8, 9],
                    "temperature_min": 10,
                    "temperature_max": 30,
                }
            },
            history=[],
            application_state={
                "type_arrosage": "bloque",
                "application_block_active": False,
                "application_post_watering_pending": False,
                "application_post_watering_status": "non_requis",
                "bilan_hydrique_mm": 15.7,
            },
            temperature=17.3,
            forecast_temperature_today=17.3,
            temperature_source="weather",
        )

        self.assertEqual(recommendation["status"], "preparation")
        self.assertEqual(recommendation["recommended_action"], "select_product")
        self.assertFalse(
            any(item.get("code") == "post_application_block" for item in recommendation["constraints"])
        )
        self.assertIn("Contexte hydrique excédentaire", recommendation["reasons"])

    def test_default_decision_time_comes_from_home_assistant_clock(self) -> None:
        fixed_now = datetime(2026, 4, 4, 14, 15, tzinfo=timezone(timedelta(hours=2)))
        with patch.object(decision_models.dt_util, "now", return_value=fixed_now), patch.object(
            phases.dt_util,
            "now",
            return_value=fixed_now,
        ):
            context = decision_models.DecisionContext.from_legacy_args(history=[])
            dominant = phases.compute_dominant_phase([], today=None)
            subphase = phases.compute_subphase("Normal", None, None, today=None, now=None)

        self.assertEqual(context.today, date(2026, 4, 4))
        self.assertEqual(dominant["phase_dominante"], "Normal")
        self.assertEqual(dominant["source"], "absence_phase")
        self.assertEqual(subphase["sous_phase"], "Normal")

    def test_normal_watering_profile_uses_daily_balance_instead_of_soil_reserve_for_blocking(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 15.6,
                "deficit_jour": 1.0,
                "deficit_3j": 3.4,
                "deficit_7j": 8.0,
                "arrosage_recent_7j": 0.5,
                "arrosage_recent": 0.5,
            },
            today=date(2026, 4, 4),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=19.1,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertIsNone(profile.get("block_reason"))
        self.assertEqual(profile["type_arrosage"], "aucune_action")
        self.assertFalse(profile["arrosage_recommande"])

    def test_normal_profile_uses_policy_max_as_fractionation_cap(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -20.0,
                "bilan_hydrique_journalier_mm": -4.0,
                "deficit_jour": 8.0,
                "deficit_3j": 16.0,
                "deficit_7j": 30.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 7, 10),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=35.0,
            temperature=31.0,
            etp=4.5,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertIsNone(profile.get("block_reason"))
        self.assertGreater(profile["mm_final_recommande"], 15.0)
        self.assertTrue(profile["arrosage_recommande"])
        self.assertGreaterEqual(profile["watering_passages"], 2)
        self.assertLessEqual(profile["fractionnement"]["max_mm_per_passage"], 15.0)

    def test_biostimulant_profile_uses_policy_range_and_light_support_floor(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Biostimulant",
            sous_phase="Réponse",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 18.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertIsNone(profile.get("block_reason"))
        self.assertEqual(profile["mm_final_recommande"], 3.0)
        self.assertEqual(profile["mm_requested"], 3.0)
        self.assertEqual(profile["watering_passages"], 1)
        self.assertTrue(profile["arrosage_recommande"])

    def test_biostimulant_profile_blocks_when_rain_compensates_support(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Biostimulant",
            sous_phase="Réponse",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 18.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=3.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertEqual(profile["block_reason"], "pluie_prevue_suffisante")
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertFalse(profile["arrosage_recommande"])

    def test_fertilisation_profile_uses_policy_range_and_single_pass(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Fertilisation",
            sous_phase="Application",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 18.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertIsNone(profile.get("block_reason"))
        self.assertEqual(profile["mm_final_recommande"], 5.0)
        self.assertEqual(profile["mm_requested"], 5.0)
        self.assertEqual(profile["watering_passages"], 1)
        self.assertEqual(profile["watering_pause_minutes"], 0)
        self.assertTrue(profile["arrosage_recommande"])

    def test_fertilisation_profile_blocks_when_rain_is_expected(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Fertilisation",
            sous_phase="Application",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 18.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=4.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertEqual(profile["block_reason"], "pluie_prevue_suffisante")
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertFalse(profile["arrosage_recommande"])

    def test_traitement_profile_requires_known_application_type(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Traitement",
            sous_phase="Application",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 18.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertEqual(profile["block_reason"], "application_type_required")
        self.assertEqual(profile["type_arrosage"], "bloque")
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertFalse(profile["arrosage_recommande"])

    def test_traitement_profile_blocks_foliaire_application(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Traitement",
            sous_phase="Application",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 18.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
            application_type="foliaire",
        )

        self.assertEqual(profile["block_reason"], "application_foliaire")
        self.assertEqual(profile["type_arrosage"], "bloque")
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertFalse(profile["arrosage_recommande"])

    def test_traitement_profile_uses_sol_application_support_range(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Traitement",
            sous_phase="Application",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 18.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
            application_type="sol",
        )

        self.assertIsNone(profile.get("block_reason"))
        self.assertEqual(profile["mm_final_recommande"], 3.0)
        self.assertEqual(profile["type_arrosage"], "auto")
        self.assertTrue(profile["arrosage_recommande"])

    def test_hivernage_profile_stays_blocked_by_default_via_policy(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Hivernage",
            sous_phase="Repos",
            water_balance={
                "bilan_hydrique_mm": -20.0,
                "bilan_hydrique_journalier_mm": -3.0,
                "deficit_jour": 3.0,
                "deficit_3j": 8.0,
                "deficit_7j": 18.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 1, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=35.0,
            temperature=8.0,
            etp=0.5,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertEqual(profile["block_reason"], "mode_bloque")
        self.assertEqual(profile["type_arrosage"], "bloque")
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertFalse(profile["arrosage_recommande"])

    def test_watering_profile_exposes_stable_core_keys_across_policy_backed_modes(self) -> None:
        expected_keys = {
            "deficit_brut_mm",
            "deficit_mm_brut",
            "deficit_mm_ajuste",
            "mm_cible",
            "mm_final_recommande",
            "mm_final",
            "mm_requested",
            "mm_applied",
            "mm_detected",
            "type_arrosage",
            "arrosage_recommande",
            "arrosage_auto_autorise",
            "arrosage_conseille",
            "watering_passages",
            "watering_pause_minutes",
            "fractionnement",
            "niveau_confiance",
            "confidence_score",
            "confidence_reasons",
            "raison_decision_base",
            "block_reason",
            "fenetre_optimale",
            "niveau_action",
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
            "recent_watering_count_7j",
            "recent_watering_mm_7j",
            "weekly_guardrail_mm_min",
            "weekly_guardrail_mm_max",
            "weekly_guardrail_reason",
            "season_label",
            "season_phase",
            "month_profile",
            "watering_bias",
            "mowing_bias",
            "intervention_bias",
            "risk_bias",
            "cooldown_24h_hours",
        }
        base_kwargs = {
            "water_balance": {
                "bilan_hydrique_mm": -1.0,
                "bilan_hydrique_journalier_mm": -1.0,
                "deficit_jour": 1.0,
                "deficit_3j": 2.0,
                "deficit_7j": 4.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent_jour": 0.0,
                "arrosage_recent": 0.0,
            },
            "today": date(2026, 4, 8),
            "pluie_24h": 0.0,
            "pluie_demain": 0.0,
            "pluie_j2": 0.0,
            "pluie_3j": 0.0,
            "pluie_probabilite_max_3j": 0.0,
            "humidite": 60.0,
            "temperature": 18.3,
            "etp": 1.1,
            "type_sol": "limoneux",
            "weather_profile": {},
            "history": [],
        }
        variants = [
            {"phase_dominante": "Normal", "sous_phase": "Normal"},
            {"phase_dominante": "Sursemis", "sous_phase": "Enracinement"},
            {"phase_dominante": "Traitement", "sous_phase": "Application", "application_type": "sol"},
            {"phase_dominante": "Fertilisation", "sous_phase": "Application"},
        ]

        for variant in variants:
            profile = guidance.compute_watering_profile(**base_kwargs, **variant)
            self.assertTrue(expected_keys.issubset(profile.keys()))

    def test_sursemis_profile_exposes_policy_strategy_metadata(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": 0.5,
                "bilan_hydrique_journalier_mm": 0.5,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent_jour": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
            sous_phase_age_days=5,
            sous_phase_progression=40.0,
        )

        self.assertEqual(profile["sursemis_policy_mode"], "sursemis")
        self.assertEqual(profile["sursemis_override_behavior"], "replace_all")
        self.assertEqual(profile["sursemis_execution_preferred"], "fractionated")
        self.assertEqual(profile["sursemis_daily_min_mm_per_cycle"], 2.0)
        self.assertEqual(profile["sursemis_daily_max_mm_per_cycle"], 4.0)
        self.assertEqual(profile["sursemis_daily_min_cycles"], 2)
        self.assertEqual(profile["sursemis_daily_max_cycles"], 3)
        self.assertEqual(profile["watering_strategy"], "semis_frequent")
        self.assertEqual(profile["objective_scope"], "surface_cycle")
        self.assertEqual(profile["watering_stage"], "enracinement")
        self.assertEqual(profile["surface_cycle_mm"], 3.0)
        self.assertEqual(profile["daily_cycles_target"], 1)
        self.assertEqual(profile["cycle_spacing_minutes"], 270)

    def test_agent_mouillant_profile_uses_policy_range(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Agent Mouillant",
            sous_phase="Application",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "reserve_hydrique_sol_mm": 18.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertIsNone(profile.get("block_reason"))
        self.assertEqual(profile["mm_final_recommande"], 5.0)
        self.assertEqual(profile["mm_requested"], 5.0)
        self.assertTrue(profile["arrosage_recommande"])

    def test_scarification_profile_uses_policy_range_when_conditions_are_met(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Scarification",
            sous_phase="Réponse",
            water_balance={
                "bilan_hydrique_mm": 1.0,
                "bilan_hydrique_journalier_mm": -1.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=18.3,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertIsNone(profile.get("block_reason"))
        self.assertEqual(profile["mm_final_recommande"], 5.0)
        self.assertTrue(profile["arrosage_recommande"])

    def test_scarification_profile_blocks_when_temperature_is_too_low(self) -> None:
        profile = guidance.compute_watering_profile(
            phase_dominante="Scarification",
            sous_phase="Réponse",
            water_balance={
                "bilan_hydrique_mm": 1.0,
                "bilan_hydrique_journalier_mm": -1.0,
                "deficit_jour": 0.0,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "arrosage_recent_7j": 0.0,
                "arrosage_recent": 0.0,
            },
            today=date(2026, 4, 8),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=8.0,
            etp=1.1,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

        self.assertEqual(profile["block_reason"], "temperature_trop_basse")
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertFalse(profile["arrosage_recommande"])


class PersistedSettingsSurviveComputeMemoryTests(unittest.TestCase):
    """`compute_memory` RECONSTRUIT la mémoire à chaque cycle du coordinateur (2 min) : tout
    réglage utilisateur absent du dict qu'elle renvoie est perdu, et l'entité correspondante
    repart sur sa valeur par défaut au refresh suivant.

    `evening_cooling_enabled` avait été ajouté au switch sans être reconduit ici : couper le
    rafraîchissement du soir ne tenait pas, l'interrupteur se rallumait tout seul. Ce test couvre
    tous les réglages persistés, pour que l'oubli ne se répète pas à la prochaine option.
    """

    REGLAGES_PERSISTES = (
        "auto_irrigation_enabled",
        "mower_coordination_enabled",
        "evening_cooling_enabled",
    )

    def _cycle(self, previous_memory):
        return memory.compute_memory(
            history=[],
            current_phase="Normal",
            decision={"phase_active": "Normal", "objectif_mm": 0.0},
            previous_memory=previous_memory,
            today=date(2026, 7, 22),
        )

    def test_un_reglage_coupe_reste_coupe(self) -> None:
        for cle in self.REGLAGES_PERSISTES:
            with self.subTest(reglage=cle):
                resultat = self._cycle({cle: False})
                self.assertIs(resultat.get(cle), False)

    def test_un_reglage_coupe_survit_a_plusieurs_cycles(self) -> None:
        # Le coordinateur rafraîchit toutes les 2 min : la perte se verrait au cycle suivant.
        etat = {cle: False for cle in self.REGLAGES_PERSISTES}
        for cycle in range(5):
            etat = self._cycle(etat)
            for cle in self.REGLAGES_PERSISTES:
                with self.subTest(reglage=cle, cycle=cycle):
                    self.assertIs(etat.get(cle), False)

    def test_chaque_reglage_est_toujours_present(self) -> None:
        resultat = self._cycle({})
        for cle in self.REGLAGES_PERSISTES:
            with self.subTest(reglage=cle):
                self.assertIn(cle, resultat)

    def test_sans_memoire_prealable_les_defauts_sappliquent(self) -> None:
        resultat = self._cycle(None)
        self.assertIs(resultat["auto_irrigation_enabled"], const.DEFAULT_AUTO_IRRIGATION_ENABLED)
        self.assertIs(
            resultat["mower_coordination_enabled"], const.DEFAULT_MOWER_COORDINATION_ENABLED
        )
        self.assertIs(resultat["evening_cooling_enabled"], const.DEFAULT_EVENING_COOLING_ENABLED)

    def test_un_reglage_active_reste_active(self) -> None:
        for cle in self.REGLAGES_PERSISTES:
            with self.subTest(reglage=cle):
                self.assertIs(self._cycle({cle: True}).get(cle), True)


class TemperatureCriterionReadabilityTests(unittest.TestCase):
    """Le critère de température doit dire QUEL thermomètre a décidé, et à la virgule.

    L'intégration décide sur le capteur extérieur, la carte affiche en en-tête l'entité météo.
    Les deux sont justes et diffèrent : on lisait « 23,8 °C » en haut d'écran et « 25.8 °C »
    dans le critère juste dessous — écart inexpliqué ET ponctuation différente sur le même
    écran (constaté le 31/07/2026).
    """

    @staticmethod
    def _eval(source: str | None):
        return intervention._temperature_evaluation(
            reference_temperature=25.8,
            temperature_min=10.0,
            temperature_max=30.0,
            reference_temperature_source=source,
        )

    def test_virgule_decimale_jamais_de_point(self) -> None:
        for source in ("capteur", "weather", "meteo_forecast", None):
            with self.subTest(source=source):
                reason = self._eval(source)["reason"]
                self.assertIn("25,8", reason)
                self.assertNotIn("25.8", reason)

    def test_la_source_est_nommee_quand_elle_est_connue(self) -> None:
        self.assertIn("au capteur", self._eval("capteur")["reason"])
        self.assertIn("selon la météo", self._eval("weather")["reason"])
        self.assertIn("selon la prévision", self._eval("meteo_forecast")["reason"])

    def test_sans_source_connue_le_libelle_reste_correct(self) -> None:
        # Ni source inventée, ni « °C » perdu, ni double « °C ».
        for source in (None, "", "non disponible", "source_inconnue"):
            with self.subTest(source=source):
                reason = self._eval(source)["reason"]
                self.assertIn("25,8 °C", reason)
                self.assertEqual(reason.count("°C"), 2, reason)  # la valeur + la plage attendue

    def test_hors_plage_porte_aussi_la_source(self) -> None:
        chaud = intervention._temperature_evaluation(
            reference_temperature=34.0, temperature_min=10.0, temperature_max=30.0,
            reference_temperature_source="capteur",
        )
        self.assertIn("34 °C au capteur", chaud["reason"])
        froid = intervention._temperature_evaluation(
            reference_temperature=2.0, temperature_min=10.0, temperature_max=30.0,
            reference_temperature_source="capteur",
        )
        self.assertIn("2 °C au capteur", froid["reason"])

    def test_le_libelle_de_contrainte_suit_la_meme_regle(self) -> None:
        label = self._eval("capteur")["label"]
        self.assertIn("25,8 °C au capteur", label)
        self.assertNotIn("25.8", label)

    def test_la_source_traverse_bien_build_intervention_recommendation(self) -> None:
        """Le CÂBLAGE, pas seulement la fonction.

        Une mutation qui remplaçait `reference_temperature_source=...` par `None` chez
        l'appelant passait tous les tests précédents : ils appelaient `_temperature_evaluation`
        en direct. Ce test-ci part du point d'entrée réel.
        """
        recommendation = intervention.build_intervention_recommendation(
            today=date(2026, 7, 31),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            temperature=25.8,
            forecast_temperature_today=31.0,
            temperature_source="capteur",
            products={
                "kick_pro": {
                    "id": "kick_pro", "nom": "Kick Pro", "type": "Agent Mouillant",
                    "usage_mode": "preventif", "reapplication_after_days": 21,
                    "phase_compatible": ["Entretien"],
                    "application_months": [4, 5, 6, 7, 8, 9, 10],
                    "temperature_min": 10, "temperature_max": 30,
                }
            },
            history=[],
            application_state={},
        )
        contrainte = next(
            item for item in recommendation["constraints"]
            if item.get("code") == "temperature_range"
        )
        self.assertIn("25,8 °C au capteur", contrainte["label"])
        self.assertIn("25,8 °C au capteur", recommendation["reason"])


class ApplicationConstraintsAffichablesTests(unittest.TestCase):
    """Les libellés de contraintes sont AFFICHÉS : ils doivent être présentables.

    Ils dormaient dans le payload sans jamais sortir. Le jour où la carte les a affichés
    (0.33.0), l'écran de Kévin a montré, sur son vrai catalogue :
      ⏳ Réapplication attendue jusqu'au **2026-08-12**   ← date ISO brute
      ⏳ Réapplication attendue jusqu'au 12/08/2026.      ← le MÊME fait, deux fois
    Reproduit ici sur le scénario réel : Kick Pro, appliqué le 22/07, délai 21 jours.
    """

    @staticmethod
    def _kick_pro():
        return intervention.build_intervention_recommendation(
            today=date(2026, 7, 31),
            phase_active="Normal",
            phase_source="absence_phase",
            sous_phase="Normal",
            selected_product_id=None,
            selected_product_name=None,
            temperature=28.6,
            forecast_temperature_today=31.0,
            temperature_source="capteur",
            products={
                "kick_pro": {
                    "id": "kick_pro", "nom": "Kick Pro", "type": "Agent Mouillant",
                    "usage_mode": "preventif", "reapplication_after_days": 21,
                    "phase_compatible": ["Entretien"],
                    "application_months": [4, 5, 6, 7, 8, 9, 10],
                    "temperature_min": 10, "temperature_max": 30,
                }
            },
            history=[{
                "type": "Agent Mouillant", "date": "2026-07-22",
                "produit_id": "kick_pro", "produit": "Kick Pro",
                "reapplication_after_days": 21,
                "produit_catalogue": {"id": "kick_pro", "nom": "Kick Pro"},
            }],
            application_state={},
        )

    def _contraintes(self):
        return self._kick_pro()["constraints"]

    def test_aucune_date_iso_brute_dans_un_libelle(self) -> None:
        import re
        for c in self._contraintes():
            self.assertIsNone(
                re.search(r"\d{4}-\d{2}-\d{2}", str(c.get("label") or "")),
                f"date ISO brute affichée : {c.get('label')!r}",
            )

    def test_la_date_de_reapplication_est_au_format_francais(self) -> None:
        delai = next(c for c in self._contraintes() if c["code"] == "reapplication_delay")
        self.assertIn("12/08/2026", delai["label"])
        self.assertTrue(delai["blocking"])
        self.assertFalse(delai["met"])

    def test_un_seul_bloquant_par_motif(self) -> None:
        """Compare les CODES, pas les libellés.

        Première version de ce test : elle vérifiait l'unicité des chaînes. Elle est passée
        au vert alors que le doublon était toujours là — parce que les deux entrées disent
        le même fait dans des mots différents (« possible à partir du 12/08 » contre
        « attendue jusqu'au 12/08 »). Un test qui compare des chaînes ne peut pas voir ça.
        """
        codes = [c["code"] for c in self._contraintes() if c.get("blocking")]
        self.assertEqual(codes, ["reapplication_delay"],
                         f"le récapitulatif est republié en doublon : {codes}")

    def test_le_recapitulatif_n_est_pas_republie(self) -> None:
        contraintes = self._contraintes()
        self.assertNotIn("post_application_block", {c["code"] for c in contraintes})
        # …et le motif reste lisible une fois, pas zéro.
        bloquants = [c["label"] for c in contraintes if c["blocking"]]
        self.assertEqual(len(bloquants), 1)
        self.assertIn("12/08/2026", bloquants[0])

    def test_le_blocage_reste_signale_dans_les_exigences_manquantes(self) -> None:
        # Le filtre ne porte QUE sur l'affichage : le moteur doit toujours voir
        # « attendre la fin du blocage ».
        codes = [m["code"] for m in self._kick_pro()["missing_requirements"]]
        self.assertIn("wait", codes)

    def test_l_attente_reste_prioritaire_hors_etat_bloque(self) -> None:
        """Le cas où la promotion de « wait » en tête compte réellement.

        En état « bloqué », `wait` est déjà ajouté en premier par un autre chemin : un test
        bâti là-dessus reste vert même si on casse la promotion — il ne prouve rien. En
        « préparation », c'est `prepare_declaration` qui arrive d'abord, et c'est cette
        branche-ci qui remet l'attente devant. Filtrer l'affichage ne doit pas la déplacer.
        """
        for etat, attendu in (("preparation", "prepare_declaration"), ("recommended", "select_product")):
            with self.subTest(etat=etat):
                _c, manquantes, _e = intervention._constraints_for_candidate(
                    candidate={"next_reapplication_date": "2026-08-12", "due": True,
                               "blocked_reason_codes": ["reapplication_delay"]},
                    state=etat,
                    block_reason="Un délai post-application est encore en cours.",
                    selected_ready=False,
                )
                codes = [m["code"] for m in manquantes]
                self.assertEqual(codes[0], "wait", f"attente non prioritaire : {codes}")
                self.assertIn(attendu, codes)

    def test_un_recapitulatif_PARTIELLEMENT_couvert_reste_affiche(self) -> None:
        """Le filtre ne doit écarter que le récapitulatif ENTIÈREMENT redondant.

        Version précédente de ce test : elle passait un `application_block_reason` en croyant
        déclencher `post_application_block`. Faux — pour un candidat complet, le motif vient de
        `best["blocked_reason"]`, pas de l'état d'application. Le test ne prouvait rien.
        On teste donc le garde-fou là où il vit.
        """
        candidat = {
            "next_reapplication_date": "2026-08-12",
            "due": False,
            "blocked_reason_codes": ["reapplication_delay", "opportunity_hard_block"],
        }
        contraintes, _manquantes, _etat = intervention._constraints_for_candidate(
            candidate=candidat,
            state="blocked",
            block_reason="Réapplication attendue jusqu'au 12/08/2026. · Sol gelé.",
            selected_ready=False,
        )
        codes = {c["code"] for c in contraintes}
        self.assertIn("reapplication_delay", codes)
        self.assertIn("post_application_block", codes,
                      "une partie du motif (opportunity_hard_block) n'a aucune contrainte "
                      "propre : le récapitulatif doit rester affiché")

    def test_un_recapitulatif_ENTIEREMENT_couvert_est_ecarte(self) -> None:
        candidat = {
            "next_reapplication_date": "2026-08-12",
            "due": False,
            "blocked_reason_codes": ["reapplication_delay"],
        }
        contraintes, _m, _e = intervention._constraints_for_candidate(
            candidate=candidat, state="blocked",
            block_reason="Réapplication attendue jusqu'au 12/08/2026.", selected_ready=False,
        )
        self.assertNotIn("post_application_block", {c["code"] for c in contraintes})

    def test_un_motif_venu_d_ailleurs_est_toujours_affiche(self) -> None:
        # Aucun code tracé = le motif ne vient pas du récapitulatif du candidat (vrai blocage
        # post-application). Il doit passer, sinon on perd une information unique.
        contraintes, _m, _e = intervention._constraints_for_candidate(
            candidate={"next_reapplication_date": "2026-08-12", "due": False},
            state="blocked",
            block_reason="L'arrosage post-application n'est pas encore terminé.",
            selected_ready=False,
        )
        self.assertIn("post_application_block", {c["code"] for c in contraintes})
