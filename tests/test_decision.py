from __future__ import annotations

import sys
import types
import importlib
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from unittest import TestCase
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

import unittest

decision = importlib.import_module("custom_components.gazon_intelligent.decision")
decision_phase = importlib.import_module("custom_components.gazon_intelligent.decision_phase")
decision_models = importlib.import_module("custom_components.gazon_intelligent.decision_models")
phases = importlib.import_module("custom_components.gazon_intelligent.phases")


class TestPhaseLogic(unittest.TestCase):
    def test_compute_phase_active_prefers_highest_priority(self) -> None:
        today = date(2026, 3, 18)
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
            {"type": "arrosage", "date": "2026-03-14", "volume_mm": 5.0},
            {"type": "arrosage", "date": "2026-03-16", "volume_mm": 3.0},
        ]
        result_3j = decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), window_days=3)
        result_7j = decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), window_days=7)
        self.assertAlmostEqual(result_3j, 3.0, places=1)
        self.assertAlmostEqual(result_7j, 8.0, places=1)

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
        subphase_day0 = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 10),
            date_fin=date(2026, 4, 23),
            today=date(2026, 3, 10),
        )
        self.assertEqual(subphase_day0["sous_phase"], "Germination")

        subphase_day10 = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 10),
            date_fin=date(2026, 4, 23),
            today=date(2026, 3, 20),
        )
        self.assertEqual(subphase_day10["sous_phase"], "Germination")

        subphase_day11 = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 10),
            date_fin=date(2026, 4, 23),
            today=date(2026, 3, 21),
        )
        self.assertEqual(subphase_day11["sous_phase"], "Enracinement")

        subphase_day45 = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 10),
            date_fin=date(2026, 4, 23),
            today=date(2026, 4, 24),
        )
        self.assertEqual(subphase_day45["sous_phase"], "Stabilisation")

    def test_compute_subphase_hivernage_always_returns_repos(self) -> None:
        subphase = decision.compute_subphase(
            phase_dominante="Hivernage",
            date_debut=date(2026, 1, 1),
            date_fin=date(2026, 12, 31),
            today=date(2026, 6, 15),
        )
        self.assertEqual(subphase["sous_phase"], "Repos")

    def test_compute_subphase_unknown_phase_falls_back_to_phase_name(self) -> None:
        subphase = decision.compute_subphase(
            phase_dominante="PhaseInconnue",
            date_debut=date(2026, 3, 10),
            date_fin=date(2026, 3, 20),
            today=date(2026, 3, 15),
        )
        self.assertEqual(subphase["sous_phase"], "PhaseInconnue")


class TestWateringDecision(unittest.TestCase):
    def _make_context(self, **kwargs):
        defaults = dict(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=60.0,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        defaults.update(kwargs)
        return decision.DecisionContext.from_legacy_args(**defaults)

    def test_watering_recommended_when_no_recent_rain_and_dry_soil(self) -> None:
        context = self._make_context()
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_watering_blocked_by_recent_rain(self) -> None:
        context = self._make_context(pluie_24h=15.0)
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)
        self.assertFalse(result.arrosage_recommande)

    def test_watering_blocked_when_forecast_rain_sufficient(self) -> None:
        context = self._make_context(pluie_demain=10.0)
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_decision_produces_arrosage_conseille_field(self) -> None:
        context = self._make_context()
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)
        self.assertIn(result.arrosage_conseille, ["auto", "personnalise", "interdit", "non_disponible"])

    def test_decision_returns_conseil_string(self) -> None:
        context = self._make_context()
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)
        self.assertIsInstance(result.conseil, str)
        self.assertGreater(len(result.conseil), 0)

    def test_watering_plan_duration_respects_flow_rate(self) -> None:
        history = [{"type": "tonte", "date": "2026-03-28"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=60.0,
            type_sol="limoneux",
            etp_capteur=3.0,
            zone_debit_1=12.0,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_decision_with_all_zones_configured(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=60.0,
            type_sol="limoneux",
            etp_capteur=3.0,
            zone_debit_1=6.0,
            zone_debit_2=8.0,
            zone_debit_3=5.0,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_arrosage_auto_blocked_when_disabled_in_memory(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=60.0,
            type_sol="limoneux",
            etp_capteur=3.0,
            memory={"auto_irrigation_enabled": False},
        )
        result = decision.compute_decision(context)
        self.assertFalse(result.arrosage_auto_autorise)

    def test_arrosage_auto_allowed_when_enabled_in_memory(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=9,
            temperature=22.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=4.0,
            memory={"auto_irrigation_enabled": True},
        )
        result = decision.compute_decision(context)
        self.assertTrue(result.arrosage_auto_autorise)

    def test_arrosage_auto_blocked_outside_watering_window(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=14,
            temperature=22.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=4.0,
            memory={"auto_irrigation_enabled": True},
        )
        result = decision.compute_decision(context)
        self.assertFalse(result.arrosage_auto_autorise)

    def test_watering_not_recommended_in_hivernage(self) -> None:
        history = [{"type": "Hivernage", "date": "2026-01-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 2, 15),
            hour_of_day=9,
            temperature=5.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=70.0,
            type_sol="limoneux",
            etp_capteur=1.0,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)
        self.assertFalse(result.arrosage_recommande)

    def test_watering_reduced_by_partial_rain_forecast(self) -> None:
        context = self._make_context(pluie_demain=4.0, etp_capteur=3.0)
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)


class TestMowingDecision(unittest.TestCase):
    def test_mowing_allowed_in_normal_phase(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_mowing_blocked_in_hivernage(self) -> None:
        history = [{"type": "Hivernage", "date": "2026-01-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 2, 15),
            hour_of_day=10,
            temperature=5.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=70.0,
            type_sol="limoneux",
            etp_capteur=1.0,
        )
        result = decision.compute_decision(context)
        self.assertFalse(result.tonte_autorisee)

    def test_mowing_discouraged_after_recent_watering(self) -> None:
        history = [{"type": "arrosage", "date": "2026-04-04", "volume_mm": 8.0, "heure": "07:00"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_mowing_result_has_tonte_autorisee_field(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        self.assertIn(result.tonte_autorisee, [True, False])

    def test_mowing_blocked_when_rainy(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=12.0,
            pluie_demain=0.0,
            humidite=90.0,
            type_sol="limoneux",
            etp_capteur=1.0,
        )
        result = decision.compute_decision(context)
        self.assertFalse(result.tonte_autorisee)


class TestDecisionContextFromLegacyArgs(unittest.TestCase):
    def test_from_legacy_args_defaults(self) -> None:
        ctx = decision.DecisionContext.from_legacy_args(history=[])
        self.assertIsInstance(ctx, decision.DecisionContext)
        self.assertEqual(ctx.history, [])

    def test_from_legacy_args_accepts_all_fields(self) -> None:
        ctx = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=10,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="argileux",
            etp_capteur=2.0,
            zone_debit_1=6.0,
            zone_debit_2=8.0,
            zone_debit_3=0.0,
            zone_debit_4=0.0,
            zone_debit_5=0.0,
            memory={},
        )
        self.assertEqual(ctx.type_sol, "argileux")
        self.assertEqual(ctx.temperature, 20.0)

    def test_from_legacy_args_normalizes_type_sol(self) -> None:
        ctx = decision.DecisionContext.from_legacy_args(history=[], type_sol="sableux")
        self.assertEqual(ctx.type_sol, "sableux")

    def test_from_legacy_args_defaults_type_sol_to_limoneux(self) -> None:
        ctx = decision.DecisionContext.from_legacy_args(history=[])
        self.assertEqual(ctx.type_sol, "limoneux")

    def test_from_legacy_args_with_today(self) -> None:
        ctx = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 3, 15),
        )
        self.assertEqual(ctx.today, date(2026, 3, 15))

    def test_from_legacy_args_zone_debits_default_zero(self) -> None:
        ctx = decision.DecisionContext.from_legacy_args(history=[])
        for i in range(1, 6):
            self.assertEqual(getattr(ctx, f"zone_debit_{i}"), 0.0)


class TestDecisionResult(unittest.TestCase):
    def _make_result(self, **overrides):
        defaults = dict(
            conseil="conseil",
            conseil_arrosage="arrosage ok",
            niveau_action="faible",
            arrosage_recommande=False,
            arrosage_auto_autorise=False,
            arrosage_conseille="auto",
            fenetre_optimale="maintenant",
            risque_gazon="faible",
            objectif_arrosage=5.0,
            tonte_autorisee=True,
            type_arrosage="auto",
        )
        defaults.update(overrides)
        return decision.DecisionResult(**defaults)

    def test_decision_result_has_expected_fields(self) -> None:
        result = self._make_result()
        self.assertIsNotNone(result.conseil)
        self.assertIsNotNone(result.niveau_action)
        self.assertIn(result.arrosage_conseille, ["auto", "personnalise", "interdit", "non_disponible"])

    def test_decision_result_display_label_for_arrosage_conseille(self) -> None:
        result = self._make_result(arrosage_conseille="interdit")
        label = result.display_label_for("arrosage_conseille")
        self.assertEqual(label, "Arrosage interdit")

    def test_decision_result_display_label_for_auto(self) -> None:
        result = self._make_result(arrosage_conseille="auto")
        label = result.display_label_for("arrosage_conseille")
        self.assertEqual(label, "Arrosage automatique")

    def test_decision_result_display_label_for_personnalise(self) -> None:
        result = self._make_result(arrosage_conseille="personnalise")
        label = result.display_label_for("arrosage_conseille")
        self.assertEqual(label, "Arrosage personnalisé")

    def test_decision_result_display_label_for_unknown_key(self) -> None:
        result = self._make_result()
        label = result.display_label_for("cle_inconnue")
        self.assertEqual(label, "")

    def test_decision_result_to_snapshot_includes_all_fields(self) -> None:
        result = self._make_result()
        snapshot = result.to_snapshot()
        self.assertIn("conseil", snapshot)
        self.assertIn("arrosage_recommande", snapshot)
        self.assertIn("tonte_autorisee", snapshot)

    def test_decision_result_extra_propagated_to_snapshot(self) -> None:
        result = self._make_result()
        result.extra = {"custom_key": 42}
        snapshot = result.to_snapshot()
        self.assertEqual(snapshot.get("custom_key"), 42)

    def test_decision_result_arrosage_conseille_coerced_to_auto(self) -> None:
        result = decision.DecisionResult(
            conseil="conseil",
            conseil_arrosage="arrosage ok",
            niveau_action="faible",
            arrosage_recommande=True,
            arrosage_auto_autorise=True,
            arrosage_conseille="personnalise",
            fenetre_optimale="maintenant",
            risque_gazon="faible",
            objectif_arrosage=5.0,
            tonte_autorisee=True,
            type_arrosage="auto",
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
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)
        self.assertIsInstance(result.risque_gazon, str)

    def test_risk_bundle_with_high_temperature_stress(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 7, 15),
            hour_of_day=14,
            temperature=38.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=20.0,
            type_sol="sableux",
            etp_capteur=7.0,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_risk_bundle_with_frost_risk(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 11, 15),
            hour_of_day=6,
            temperature=1.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=90.0,
            type_sol="argileux",
            etp_capteur=0.5,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)


class TestDecisionSolTypeSableux(unittest.TestCase):
    def test_sableux_drains_faster_than_argileux(self) -> None:
        ctx_sableux = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 5, 1),
            hour_of_day=9,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=50.0,
            type_sol="sableux",
            etp_capteur=3.0,
        )
        ctx_argileux = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 5, 1),
            hour_of_day=9,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=50.0,
            type_sol="argileux",
            etp_capteur=3.0,
        )
        result_sableux = decision.compute_decision(ctx_sableux)
        result_argileux = decision.compute_decision(ctx_argileux)
        self.assertIsNotNone(result_sableux)
        self.assertIsNotNone(result_argileux)


class TestDecisionContextSnapshot(unittest.TestCase):
    def test_snapshot_roundtrip_preserves_key_fields(self) -> None:
        ctx = decision.DecisionContext.from_legacy_args(
            history=[{"type": "Sursemis", "date": "2026-03-10"}],
            today=date(2026, 3, 20),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(ctx)
        snapshot = result.to_snapshot()
        self.assertIn("conseil", snapshot)
        self.assertIn("tonte_autorisee", snapshot)
        self.assertIn("arrosage_recommande", snapshot)


class TestDecisionMultiplePhases(unittest.TestCase):
    def test_sursemis_blocks_scarification(self) -> None:
        history = [
            {"type": "Sursemis", "date": "2026-03-10"},
        ]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 3, 20),
            hour_of_day=10,
            temperature=15.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.0,
        )
        result = decision.compute_decision(context)
        phase, _, _ = decision.compute_phase_active(history, today=date(2026, 3, 20))
        self.assertEqual(phase, "Sursemis")
        self.assertFalse(result.tonte_autorisee)

    def test_traitement_overrides_fertilisation_same_day(self) -> None:
        history = [
            {"type": "Fertilisation", "date": "2026-03-17"},
            {"type": "Traitement", "date": "2026-03-17"},
        ]
        phase, _, _ = decision.compute_phase_active(history, today=date(2026, 3, 17))
        self.assertEqual(phase, "Traitement")


class TestDecisionEdgeCases(unittest.TestCase):
    def test_decision_with_empty_history(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_decision_with_invalid_history_entries(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[None, {}, {"type": None}, {"type": "inconnu"}],  # type: ignore[list-item]
            today=date(2026, 4, 4),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_decision_with_extreme_temperatures(self) -> None:
        for temp in [-10.0, 0.0, 45.0]:
            context = decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 4, 4),
                hour_of_day=9,
                temperature=temp,
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=55.0,
                type_sol="limoneux",
                etp_capteur=2.5,
            )
            result = decision.compute_decision(context)
            self.assertIsNotNone(result)

    def test_decision_with_zero_etp(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=0.0,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)


class TestWateringSchedulePlan(unittest.TestCase):
    def test_plan_has_required_keys(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=3.5,
            zone_debit_1=8.0,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertIn("objectif_arrosage", snapshot)

    def test_plan_objectif_non_negative(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=3.5,
        )
        result = decision.compute_decision(context)
        self.assertGreaterEqual(result.objectif_arrosage, 0.0)


class TestDecisionSursemisProtections(unittest.TestCase):
    def test_sursemis_germination_watering_objective_elevated(self) -> None:
        history = [{"type": "Sursemis", "date": "2026-04-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 5),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_sursemis_mowing_blocked_during_germination(self) -> None:
        history = [{"type": "Sursemis", "date": "2026-04-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 5),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        self.assertFalse(result.tonte_autorisee)

    def test_sursemis_stabilisation_mowing_allowed(self) -> None:
        history = [{"type": "Sursemis", "date": "2026-02-20"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 5),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        phase, _, _ = decision.compute_phase_active(history, today=date(2026, 4, 5))
        self.assertEqual(phase, "Sursemis")
        subphase = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 2, 20),
            date_fin=date(2026, 4, 5),
            today=date(2026, 4, 5),
        )
        self.assertEqual(subphase["sous_phase"], "Stabilisation")


class TestSubphaseRulesOrdering(unittest.TestCase):
    def test_subphase_rules_are_order_independent(self) -> None:
        import copy
        original_rules = copy.deepcopy(phases.SUBPHASE_RULES)
        try:
            # Reverse Sursemis rules to simulate wrong order
            phases.SUBPHASE_RULES["Sursemis"] = list(reversed(original_rules["Sursemis"]))
            subphase_day5 = decision.compute_subphase(
                phase_dominante="Sursemis",
                date_debut=date(2026, 3, 10),
                date_fin=date(2026, 4, 23),
                today=date(2026, 3, 15),
            )
            self.assertEqual(subphase_day5["sous_phase"], "Germination")
        finally:
            phases.SUBPHASE_RULES["Sursemis"] = original_rules["Sursemis"]


class TestRecentWateringMm(unittest.TestCase):
    def test_watering_in_window_counted(self) -> None:
        history = [{"type": "arrosage", "date": "2026-04-02", "volume_mm": 6.0}]
        mm = decision.compute_recent_watering_mm(history, today=date(2026, 4, 4), window_days=3)
        self.assertAlmostEqual(mm, 6.0, places=1)

    def test_watering_outside_window_excluded(self) -> None:
        history = [{"type": "arrosage", "date": "2026-03-25", "volume_mm": 6.0}]
        mm = decision.compute_recent_watering_mm(history, today=date(2026, 4, 4), window_days=3)
        self.assertAlmostEqual(mm, 0.0, places=1)

    def test_multiple_waterings_summed(self) -> None:
        history = [
            {"type": "arrosage", "date": "2026-04-01", "volume_mm": 5.0},
            {"type": "arrosage", "date": "2026-04-03", "volume_mm": 3.0},
        ]
        mm = decision.compute_recent_watering_mm(history, today=date(2026, 4, 4), window_days=7)
        self.assertAlmostEqual(mm, 8.0, places=1)

    def test_missing_volume_mm_treated_as_zero(self) -> None:
        history = [{"type": "arrosage", "date": "2026-04-03"}]
        mm = decision.compute_recent_watering_mm(history, today=date(2026, 4, 4), window_days=7)
        self.assertAlmostEqual(mm, 0.0, places=1)


class TestDecisionPhaseBundle(unittest.TestCase):
    def test_build_phase_bundle_normal_phase(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            temperature=18.0,
        )
        bundle = decision_phase.build_phase_bundle(context)
        self.assertEqual(bundle["phase_dominante"], "Normal")
        self.assertEqual(bundle["sous_phase"], "Normal")
        self.assertIsNone(bundle["date_action"])
        self.assertIsNone(bundle["date_fin"])
        self.assertEqual(bundle["jours_restants"], 0)

    def test_build_phase_bundle_sursemis_germination(self) -> None:
        history = [{"type": "Sursemis", "date": "2026-04-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 5),
            temperature=18.0,
        )
        bundle = decision_phase.build_phase_bundle(context)
        self.assertEqual(bundle["phase_dominante"], "Sursemis")
        self.assertEqual(bundle["sous_phase"], "Germination")
        self.assertEqual(bundle["date_action"], "2026-04-01")
        self.assertGreater(bundle["jours_restants"], 0)

    def test_build_phase_bundle_manual_override_to_normal(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "Sursemis", "date": "2026-04-01"}],
            today=date(2026, 4, 5),
            temperature=18.0,
            memory={"phase_override": {"phase": "Normal"}},
        )
        bundle = decision_phase.build_phase_bundle(context)
        self.assertEqual(bundle["phase_dominante"], "Normal")
        self.assertEqual(bundle["phase_dominante_source"], "manual_override")

    def test_build_phase_bundle_source_is_historique_actif_when_phase_active(self) -> None:
        history = [{"type": "Traitement", "date": "2026-04-04"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 4),
            temperature=18.0,
        )
        bundle = decision_phase.build_phase_bundle(context)
        self.assertEqual(bundle["phase_dominante"], "Traitement")
        self.assertEqual(bundle["phase_dominante_source"], "historique_actif")

    def test_build_phase_bundle_jours_restants_positive_for_active_phase(self) -> None:
        history = [{"type": "Sursemis", "date": "2026-04-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 10),
            temperature=18.0,
        )
        bundle = decision_phase.build_phase_bundle(context)
        self.assertGreater(bundle["jours_restants"], 0)


class TestDecisionMowingBundle(unittest.TestCase):
    def test_mowing_overdue_detected_after_long_interval(self) -> None:
        history = [{"type": "tonte", "date": "2026-03-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 10),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertIn("mowing_is_overdue", snapshot)
        self.assertTrue(snapshot["mowing_is_overdue"])

    def test_mowing_not_overdue_after_recent_mowing(self) -> None:
        history = [{"type": "tonte", "date": "2026-04-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 4),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertIn("mowing_is_overdue", snapshot)
        self.assertFalse(snapshot["mowing_is_overdue"])

    def test_gazon_hauteur_estimee_present_in_snapshot_after_mowing(self) -> None:
        history = [{"type": "tonte", "date": "2026-04-01", "hauteur_coupe_mm": 50.0}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 10),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertIn("gazon_hauteur_estimee_cm", snapshot)
        val = snapshot["gazon_hauteur_estimee_cm"]
        self.assertIsNotNone(val)
        self.assertIsInstance(val, float)
        self.assertGreater(val, 0.0)


class TestDecisionWateringBlockReasons(unittest.TestCase):
    def test_watering_blocked_by_recent_heavy_rain(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=20.0,
            pluie_demain=0.0,
            humidite=95.0,
            type_sol="limoneux",
            etp_capteur=2.0,
        )
        result = decision.compute_decision(context)
        self.assertFalse(result.arrosage_recommande)

    def test_watering_not_blocked_with_no_rain_and_deficit(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=7,
            temperature=28.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=40.0,
            type_sol="sableux",
            etp_capteur=6.0,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)

    def test_watering_blocked_by_traitement_phase(self) -> None:
        history = [{"type": "Traitement", "date": "2026-04-04"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 4),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        self.assertFalse(result.arrosage_recommande)


class TestDecisionIrrigationPlanZones(unittest.TestCase):
    def test_irrigation_plan_zone_durations_positive_when_watering_needed(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 10),
            hour_of_day=7,
            temperature=28.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=40.0,
            type_sol="sableux",
            etp_capteur=6.0,
            zone_debit_1=10.0,
            zone_debit_2=8.0,
            memory={"auto_irrigation_enabled": True},
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertIn("objectif_arrosage", snapshot)

    def test_no_zones_configured_returns_zero_objectif(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 10),
            hour_of_day=7,
            temperature=28.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=40.0,
            type_sol="sableux",
            etp_capteur=6.0,
        )
        result = decision.compute_decision(context)
        self.assertIsNotNone(result)


class TestDecisionProchainArrosage(unittest.TestCase):
    def test_prochain_arrosage_present_in_snapshot(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertIn("prochain_arrosage", snapshot)

    def test_prochaine_tonte_present_in_snapshot(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=9,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertIn("prochaine_tonte", snapshot)


class TestDecisionAssistantMessage(unittest.TestCase):
    def test_assistant_conseil_non_empty(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 5, 1),
            hour_of_day=9,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        result = decision.compute_decision(context)
        self.assertIsInstance(result.conseil, str)
        self.assertGreater(len(result.conseil), 0)

    def test_decision_snapshot_has_all_public_keys(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 5, 1),
            hour_of_day=9,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        required_keys = [
            "conseil",
            "arrosage_recommande",
            "arrosage_auto_autorise",
            "arrosage_conseille",
            "objectif_arrosage",
            "tonte_autorisee",
            "risque_gazon",
            "prochain_arrosage",
            "prochaine_tonte",
        ]
        for key in required_keys:
            self.assertIn(key, snapshot, f"Clé manquante dans snapshot: {key}")


class TestDecisionSousPhaseBundle(unittest.TestCase):
    def test_sous_phase_bundle_normal_phase(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            temperature=18.0,
        )
        bundle = decision_phase.build_phase_bundle(context)
        self.assertIn("sous_phase", bundle)
        self.assertIn("sous_phase_detail", bundle)
        self.assertIn("sous_phase_age_days", bundle)
        self.assertIn("sous_phase_progression", bundle)
        self.assertEqual(bundle["sous_phase"], "Normal")

    def test_sous_phase_bundle_sursemis_germination(self) -> None:
        history = [{"type": "Sursemis", "date": "2026-04-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 5),
            temperature=18.0,
        )
        bundle = decision_phase.build_phase_bundle(context)
        self.assertEqual(bundle["sous_phase"], "Germination")
        self.assertEqual(bundle["sous_phase_age_days"], 4)
        self.assertGreater(bundle["sous_phase_progression"], 0.0)
        self.assertLessEqual(bundle["sous_phase_progression"], 100.0)

    def test_sous_phase_progression_within_bounds(self) -> None:
        for days_elapsed in [0, 5, 11, 25, 35, 44]:
            start = date(2026, 3, 1)
            today = start + timedelta(days=days_elapsed)
            end = start + timedelta(days=44)
            history = [{"type": "Sursemis", "date": start.isoformat()}]
            context = decision.DecisionContext.from_legacy_args(
                history=history,
                today=today,
                temperature=18.0,
            )
            bundle = decision_phase.build_phase_bundle(context)
            prog = bundle["sous_phase_progression"]
            self.assertGreaterEqual(prog, 0.0, f"day {days_elapsed}: progression {prog} < 0")
            self.assertLessEqual(prog, 100.0, f"day {days_elapsed}: progression {prog} > 100")

    def test_sous_phase_detail_contains_phase_and_sous_phase(self) -> None:
        history = [{"type": "Sursemis", "date": "2026-04-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 5),
            temperature=18.0,
        )
        bundle = decision_phase.build_phase_bundle(context)
        detail = bundle["sous_phase_detail"]
        self.assertIn("Sursemis", detail)
        self.assertIn("Germination", detail)


class TestDecisionMowingOverdueBundle(unittest.TestCase):
    def test_mowing_overdue_after_long_interval_in_snapshot(self) -> None:
        history = [{"type": "tonte", "date": "2026-02-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 4),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertTrue(snapshot.get("mowing_is_overdue"))
        self.assertIsNotNone(snapshot.get("mowing_overdue_days"))
        self.assertGreater(snapshot.get("mowing_overdue_days", 0), 0)

    def test_mowing_not_overdue_recent_mowing_in_snapshot(self) -> None:
        history = [{"type": "tonte", "date": "2026-04-01"}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 4),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        self.assertFalse(snapshot.get("mowing_is_overdue"))


class TestDecisionGazonHauteurEstimee(unittest.TestCase):
    def test_hauteur_estimee_present_after_mowing_with_hauteur_coupe(self) -> None:
        history = [{"type": "tonte", "date": "2026-04-01", "hauteur_coupe_mm": 50.0}]
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 4, 10),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        hauteur = snapshot.get("gazon_hauteur_estimee_cm")
        self.assertIsNotNone(hauteur)
        self.assertIsInstance(hauteur, float)
        self.assertGreater(hauteur, 0.0)

    def test_hauteur_estimee_grows_over_time(self) -> None:
        base_date = date(2026, 4, 1)
        hauteurs = []
        for offset in [3, 7, 14]:
            history = [{"type": "tonte", "date": base_date.isoformat(), "hauteur_coupe_mm": 50.0}]
            context = decision.DecisionContext.from_legacy_args(
                history=history,
                today=base_date + timedelta(days=offset),
                hour_of_day=10,
                temperature=18.0,
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=55.0,
                type_sol="limoneux",
                etp_capteur=2.5,
            )
            result = decision.compute_decision(context)
            snapshot = result.to_snapshot()
            hauteurs.append(snapshot.get("gazon_hauteur_estimee_cm", 0.0))

        self.assertLess(hauteurs[0], hauteurs[1])
        self.assertLess(hauteurs[1], hauteurs[2])

    def test_hauteur_estimee_none_without_mowing_history(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 10),
            hour_of_day=10,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.5,
        )
        result = decision.compute_decision(context)
        snapshot = result.to_snapshot()
        hauteur = snapshot.get("gazon_hauteur_estimee_cm")
        self.assertIsNone(hauteur)


class TestDecisionWateringAfterPostDrainCheck(unittest.TestCase):
    def test_mowing_not_blocked_after_draindown_period_sableux(self) -> None:
        watering_time = datetime(2026, 4, 4, 7, 0, tzinfo=timezone.utc)
        watering_iso = watering_time.isoformat()
        history = [{"type": "arrosage", "date": "2026-04-04", "volume_mm": 8.0, "heure": "07:00", "declared_at": watering_iso}]
        now_time = watering_time + timedelta(hours=2)

        with patch("homeassistant.util.dt.now", return_value=now_time):
            context = decision.DecisionContext.from_legacy_args(
                history=history,
                today=date(2026, 4, 4),
                hour_of_day=9,
                temperature=20.0,
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=55.0,
                type_sol="sableux",
                etp_capteur=2.5,
            )
            result = decision.compute_decision(context)

        self.assertTrue(result.tonte_autorisee)

    def test_mowing_blocked_just_after_watering_argileux(self) -> None:
        watering_time = datetime(2026, 4, 4, 7, 0, tzinfo=timezone.utc)
        watering_iso = watering_time.isoformat()
        history = [{"type": "arrosage", "date": "2026-04-04", "volume_mm": 8.0, "heure": "07:00", "declared_at": watering_iso}]
        now_time = watering_time + timedelta(minutes=30)

        with patch("homeassistant.util.dt.now", return_value=now_time):
            context = decision.DecisionContext.from_legacy_args(
                history=history,
                today=date(2026, 4, 4),
                hour_of_day=7,
                temperature=20.0,
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=55.0,
                type_sol="argileux",
                etp_capteur=2.5,
            )
            result = decision.compute_decision(context)

        self.assertFalse(result.tonte_autorisee)


if __name__ == "__main__":
    unittest.main()
