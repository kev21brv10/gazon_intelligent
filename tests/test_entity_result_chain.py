from __future__ import annotations

import unittest
from dataclasses import dataclass
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
TEST_TZ = ZoneInfo("Europe/Paris")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


def _install_homeassistant_stubs() -> None:
    def ensure_module(name: str) -> types.ModuleType:
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            sys.modules[name] = module
        return module

    ensure_module("homeassistant")
    ensure_module("homeassistant.components")
    ensure_module("homeassistant.helpers")
    util_mod = ensure_module("homeassistant.util")
    if not hasattr(util_mod, "__path__"):
        util_mod.__path__ = []  # type: ignore[attr-defined]
    dt_mod = ensure_module("homeassistant.util.dt")
    dt_mod.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=TEST_TZ)  # type: ignore[attr-defined]

    sensor_mod = ensure_module("homeassistant.components.sensor")
    if not hasattr(sensor_mod, "SensorEntity"):
        sensor_mod.SensorEntity = type("SensorEntity", (), {"__init__": lambda self, *args, **kwargs: None})
    if not hasattr(sensor_mod, "SensorStateClass"):
        sensor_mod.SensorStateClass = type("SensorStateClass", (), {"MEASUREMENT": "measurement"})
    if not hasattr(sensor_mod, "SensorEntityCategory"):
        sensor_mod.SensorEntityCategory = type("SensorEntityCategory", (), {"DIAGNOSTIC": "diagnostic"})

    binary_sensor_mod = ensure_module("homeassistant.components.binary_sensor")
    if not hasattr(binary_sensor_mod, "BinarySensorEntity"):
        binary_sensor_mod.BinarySensorEntity = type("BinarySensorEntity", (), {"__init__": lambda self, *args, **kwargs: None})

    select_mod = ensure_module("homeassistant.components.select")
    if not hasattr(select_mod, "SelectEntity"):
        select_mod.SelectEntity = type("SelectEntity", (), {"__init__": lambda self, *args, **kwargs: None})

    helpers_entity_mod = ensure_module("homeassistant.helpers.entity")
    if not hasattr(helpers_entity_mod, "DeviceInfo"):
        class DeviceInfo(dict):
            pass

        helpers_entity_mod.DeviceInfo = DeviceInfo
    if not hasattr(helpers_entity_mod, "EntityCategory"):
        class EntityCategory:
            CONFIG = "config"
            DIAGNOSTIC = "diagnostic"

        helpers_entity_mod.EntityCategory = EntityCategory

    update_coordinator_mod = ensure_module("homeassistant.helpers.update_coordinator")
    if not hasattr(update_coordinator_mod, "CoordinatorEntity"):
        class CoordinatorEntity:
            def __init__(self, coordinator):
                self.coordinator = coordinator

        update_coordinator_mod.CoordinatorEntity = CoordinatorEntity

    exceptions_mod = ensure_module("homeassistant.exceptions")
    if not hasattr(exceptions_mod, "HomeAssistantError"):
        class HomeAssistantError(Exception):
            pass

        exceptions_mod.HomeAssistantError = HomeAssistantError


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_stubs()

decision_models = __import__("custom_components.gazon_intelligent.decision_models", fromlist=["DecisionResult"])
sensor = __import__("custom_components.gazon_intelligent.sensor", fromlist=["GazonPhaseActiveSensor"])
binary_sensor = __import__("custom_components.gazon_intelligent.binary_sensor", fromlist=["GazonTonteAutoriseeBinarySensor"])
select = __import__("custom_components.gazon_intelligent.select", fromlist=["GazonModeSelect"])


@dataclass
class _FakeEntry:
    entry_id: str = "entry123"


@dataclass
class _FakeCoordinator:
    entry: _FakeEntry
    data: dict[str, object]
    result: object | None = None
    last_result: object | None = None
    history: list[dict[str, object]] | None = None
    memory: dict[str, object] | None = None


def _make_result():
    return decision_models.DecisionResult(
        phase_dominante="Sursemis",
        sous_phase="Enracinement",
        action_recommandee="Arroser demain matin en 2 passages courts.",
        action_a_eviter="Tondre avant levée complète.",
        niveau_action="critique",
        fenetre_optimale="demain_matin",
        risque_gazon="eleve",
        objectif_arrosage=1.2,
        tonte_autorisee=True,
        hauteur_tonte_recommandee_cm=7.0,
        hauteur_tonte_min_cm=3.0,
        hauteur_tonte_max_cm=8.0,
        conseil_principal="Arroser demain matin.",
        tonte_statut="autorisee",
        arrosage_recommande=True,
        arrosage_auto_autorise=True,
        type_arrosage="fractionne",
        arrosage_conseille="fractionne",
        watering_passages=2,
        watering_pause_minutes=25,
        phase_dominante_source="historique_actif",
        sous_phase_detail="Sursemis / Enracinement",
        sous_phase_age_days=12,
        sous_phase_progression=57,
        prochaine_reevaluation="dans 24 h",
        urgence="moyenne",
        raison_decision="Test DecisionResult-first.",
        score_hydrique=42,
        score_stress=33,
        score_tonte=12,
        extra={
            "configuration": {"type_sol": "argileux"},
            "pluie_demain_source": "meteo_forecast",
            "temperature_source": "capteur",
            "forecast_temperature_today": 18.2,
            "bilan_hydrique_mm": -1.8,
            "deficit_3j": 1.2,
            "deficit_7j": 2.4,
            "pluie_demain": 0.8,
            "temperature": 26.5,
            "etp": 3.1,
            "watering_target_date": "2026-03-18",
            "watering_window_start_minute": 360,
            "watering_window_end_minute": 570,
            "watering_evening_start_minute": 1080,
            "watering_evening_end_minute": 1260,
            "watering_window_profile": "mild",
            "watering_evening_allowed": False,
        },
    )


def _local_text(iso_value: str) -> str:
    return datetime.fromisoformat(iso_value).astimezone(TEST_TZ).strftime("%d/%m/%Y à %H:%M")


class DecisionResultChainTests(unittest.TestCase):
    def test_watering_sensors_return_explicit_defaults_without_history(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})

        plan_sensor = sensor.GazonPlanArrosageSensor(coordinator)
        watering_progress_sensor = sensor.GazonArrosageEnCoursSensor(coordinator)
        last_watering_sensor = sensor.GazonDernierArrosageDetecteSensor(coordinator)
        last_application_sensor = sensor.GazonDerniereApplicationSensor(coordinator)
        last_user_action_sensor = sensor.GazonDerniereActionUtilisateurSensor(coordinator)
        catalogue_sensor = sensor.GazonCatalogueProduitsSensor(coordinator)
        application_allowed_sensor = binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator)

        self.assertEqual(plan_sensor.native_value, 0.0)
        self.assertEqual(plan_sensor.extra_state_attributes["objective_mm"], 0.0)
        self.assertEqual(plan_sensor.extra_state_attributes["zone_count"], 0)
        self.assertEqual(plan_sensor.extra_state_attributes["total_duration_min"], 0.0)
        self.assertEqual(plan_sensor.extra_state_attributes["duration_human"], "0 min")
        self.assertEqual(plan_sensor.extra_state_attributes["source"], "no_plan")
        self.assertEqual(plan_sensor.extra_state_attributes["reason"], "objective_non_positive")
        self.assertEqual(plan_sensor.extra_state_attributes["plan_type"], "no_plan")
        self.assertEqual(plan_sensor.extra_state_attributes["summary"], "Aucun cycle calculé")
        self.assertFalse(plan_sensor.extra_state_attributes["fractionation"])

        self.assertEqual(watering_progress_sensor.native_value, 0.0)
        self.assertFalse(watering_progress_sensor.extra_state_attributes["active"])
        self.assertEqual(watering_progress_sensor.extra_state_attributes["summary"], "Aucun arrosage en cours")
        self.assertEqual(watering_progress_sensor.extra_state_attributes["detail"], "Aucune session active")

        self.assertEqual(last_watering_sensor.native_value, 0.0)
        self.assertEqual(last_watering_sensor.extra_state_attributes["source"], "none")
        self.assertEqual(last_watering_sensor.extra_state_attributes["zone_count"], 0)
        self.assertEqual(last_watering_sensor.extra_state_attributes["total_mm"], 0.0)
        self.assertEqual(last_watering_sensor.extra_state_attributes["summary"], "Aucun arrosage détecté")
        self.assertNotIn("objectif_mm", last_watering_sensor.extra_state_attributes)
        self.assertNotIn("session_total_mm", last_watering_sensor.extra_state_attributes)
        self.assertEqual(last_application_sensor.native_value, "Aucune application")
        self.assertEqual(last_application_sensor.extra_state_attributes["summary"], "Aucune application détectée")
        self.assertEqual(last_user_action_sensor.native_value, "aucune_action")
        self.assertEqual(last_user_action_sensor.extra_state_attributes["summary"], "Aucune action récente")
        self.assertEqual(catalogue_sensor.native_value, 0)
        self.assertEqual(catalogue_sensor.extra_state_attributes["products_count"], 0)
        self.assertEqual(catalogue_sensor.extra_state_attributes["summary"], "Aucun produit enregistré")
        self.assertFalse(application_allowed_sensor.is_on)
        self.assertNotIn("application_type", application_allowed_sensor.extra_state_attributes)

    def test_intervention_product_select_reflects_catalogue_and_selection(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})
        coordinator.products = {
            "bio-1": {"id": "bio-1", "nom": "Bio Boost"},
            "engrais-printemps": {"id": "engrais-printemps", "nom": "Engrais Printemps"},
        }
        coordinator.selected_product_id = "engrais-printemps"

        product_select = select.GazonInterventionProductSelect(coordinator)

        self.assertEqual(product_select.options, ["Bio Boost", "Engrais Printemps"])
        self.assertEqual(product_select.current_option, "Engrais Printemps")
        self.assertEqual(product_select.extra_state_attributes["selected_product_id"], "engrais-printemps")
        self.assertEqual(product_select.extra_state_attributes["selected_product_name"], "Engrais Printemps")

    def test_debug_intervention_sensor_exposes_existing_payload(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "intervention_recommendation": {
                    "status": "possible",
                    "score": 23,
                    "recommended_action": "select_product",
                    "reason": "Phase moins adaptée (Croissance, Entretien)",
                    "why_now": "Phase moins adaptée (Croissance, Entretien) · Température compatible (15.3 °C, attendu 10 à 30 °C)",
                    "reasons": [
                        "Phase moins adaptée (Croissance, Entretien)",
                        "Mois compatibles (Avril à Septembre)",
                        "Température compatible (15.3 °C, attendu 10 à 30 °C)",
                    ],
                    "missing_requirements": [
                        {
                            "code": "prepare_declaration",
                            "label": "Préparer la déclaration avec le produit proposé",
                            "blocking": False,
                            "value": {"product_id": "h2pro_trismart", "product_name": "H2Pro TriSmart"},
                        }
                    ],
                    "constraints": [
                        {
                            "code": "phase_compatibility",
                            "label": "Phase moins adaptée (Croissance, Entretien)",
                            "blocking": False,
                            "met": False,
                        },
                        {
                            "code": "temperature_range",
                            "label": "Température compatible (15.3 °C, attendu 10 à 30 °C)",
                            "blocking": False,
                            "met": True,
                        },
                        {
                            "code": "catalogue_empty",
                            "label": "Aucun produit enregistré",
                            "blocking": True,
                            "met": False,
                        },
                    ],
                    "product": {
                        "id": "h2pro_trismart",
                        "name": "H2Pro TriSmart",
                        "type": "Agent Mouillant",
                        "months": [4, 5, 6, 7, 8, 9],
                        "months_label": "Avril à Septembre",
                        "temperature_value": 15.3,
                        "temperature_min": 10,
                        "temperature_max": 30,
                        "temperature_source": "capteur",
                    },
                    "context": {
                        "catalogue_count": 4,
                        "eligible_count": 0,
                        "blocked_products_count": 1,
                        "current_month": 4,
                        "current_phase": "Normal",
                        "current_sub_phase": "Normal",
                    },
                    "ui": {
                        "summary": "À préparer",
                        "hint": "Phase moins adaptée (Croissance, Entretien)",
                    },
                }
            },
            result=None,
            history=[],
            memory={},
        )

        debug_sensor = sensor.GazonDebugInterventionSensor(coordinator)

        self.assertEqual(debug_sensor.native_value, "preparation")
        attrs = debug_sensor.extra_state_attributes
        self.assertEqual(attrs["runtime_probe"], "constraints_probe_20260404_01")
        self.assertEqual(attrs["score"], 23)
        self.assertEqual(attrs["status"], "preparation")
        self.assertEqual(attrs["recommended_action"], "select_product")
        self.assertEqual(attrs["product_id"], "h2pro_trismart")
        self.assertEqual(attrs["product_name"], "H2Pro TriSmart")
        self.assertEqual(attrs["summary"], "À préparer")
        self.assertEqual(attrs["context"]["phase"], "Normal")
        self.assertEqual(attrs["context"]["month"], 4)
        self.assertEqual(attrs["context"]["temperature"], 15.3)
        blocking_constraints = [item for item in attrs["constraints"] if item["impact"] == "bloquant"]
        non_blocking_constraints = [item for item in attrs["constraints"] if item["impact"] != "bloquant"]
        self.assertEqual(len(blocking_constraints), 1)
        self.assertEqual(len(non_blocking_constraints), 2)
        self.assertEqual(blocking_constraints[0]["impact"], "bloquant")
        self.assertEqual(non_blocking_constraints[0]["impact"], "dégradant")
        self.assertEqual(attrs["constraints"][0]["impact"], "dégradant")
        self.assertEqual(attrs["constraints"][1]["impact"], "neutre")
        self.assertEqual(attrs["constraints"][2]["impact"], "bloquant")
        self.assertNotIn("ui_summary", attrs)
        self.assertNotIn("ui_hint", attrs)
        self.assertEqual(attrs["reasons"], [
            "Phase moins adaptée (Croissance, Entretien)",
            "Mois compatibles (Avril à Septembre)",
            "Température compatible (15.3 °C, attendu 10 à 30 °C)",
        ])

    def test_intervention_recommendation_sensor_normalizes_constraint_context(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "intervention_recommendation": {
                    "status": "possible",
                    "score": 23,
                    "recommended_action": "select_product",
                    "reason": "Phase moins adaptée (Croissance, Entretien)",
                    "why_now": "Phase moins adaptée (Croissance, Entretien) · Température compatible (15.3 °C, attendu 10 à 30 °C)",
                    "reasons": [
                        "Phase moins adaptée (Croissance, Entretien)",
                        "Mois compatibles (Avril à Septembre)",
                        "Température compatible (15.3 °C, attendu 10 à 30 °C)",
                    ],
                    "constraints": [
                        {
                            "code": "phase_compatibility",
                            "label": "Phase moins adaptée (Croissance, Entretien)",
                            "blocking": False,
                            "met": False,
                            "value": {
                                "expected": ["Croissance", "Entretien"],
                                "current": None,
                                "matched": False,
                            },
                        },
                        {
                            "code": "application_months",
                            "label": "Mois compatibles (Avril à Septembre)",
                            "blocking": False,
                            "met": True,
                            "value": {
                                "months": [4, 5, 6, 7, 8, 9],
                                "current_month": None,
                                "matched": True,
                            },
                        },
                    ],
                    "product": {
                        "id": "h2pro_trismart",
                        "name": "H2Pro TriSmart",
                        "type": "Agent Mouillant",
                        "months": [4, 5, 6, 7, 8, 9],
                        "months_label": "Avril à Septembre",
                        "temperature_value": 15.3,
                        "temperature_min": 10,
                        "temperature_max": 30,
                        "temperature_source": "capteur",
                    },
                    "context": {
                        "catalogue_count": 4,
                        "eligible_count": 0,
                        "blocked_products_count": 1,
                        "current_month": 4,
                        "current_phase": "Normal",
                        "current_sub_phase": "Normal",
                    },
                    "ui": {
                        "summary": "À préparer",
                        "hint": "Phase moins adaptée (Croissance, Entretien)",
                    },
                }
            },
            result=None,
            history=[],
            memory={},
        )

        recommendation_sensor = sensor.GazonInterventionRecommendationSensor(coordinator)

        attrs = recommendation_sensor.extra_state_attributes
        self.assertEqual(attrs["runtime_probe"], "constraints_probe_20260404_01")
        self.assertEqual(attrs["current_phase"], "Normal")
        self.assertEqual(attrs["current_month"], 4)
        self.assertEqual(attrs["summary"], "À préparer")
        self.assertEqual(attrs["hint"], "Phase moins adaptée (Croissance, Entretien)")

        debug_sensor = sensor.GazonDebugInterventionSensor(coordinator)
        payload = debug_sensor.extra_state_attributes
        phase_constraint = next(item for item in payload["constraints"] if item.get("code") == "phase_compatibility")
        month_constraint = next(item for item in payload["constraints"] if item.get("code") == "application_months")
        self.assertEqual(phase_constraint["value"]["current"], "Normal")
        self.assertEqual(month_constraint["value"]["current_month"], 4)

    def test_intervention_recommendation_sensor_prefers_coordinator_data_over_result_cache(self) -> None:
        stale_result = _make_result()
        stale_result.extra["intervention_recommendation"] = {
            "status": "blocked",
            "score": 12,
            "recommended_action": "wait",
            "constraints": [
                {
                    "code": "phase_compatibility",
                    "label": "Phase moins adaptée",
                    "blocking": False,
                    "met": False,
                    "value": {
                        "expected": ["Croissance", "Entretien"],
                        "current": None,
                        "matched": False,
                    },
                },
                {
                    "code": "application_months",
                    "label": "Mois compatibles",
                    "blocking": False,
                    "met": True,
                    "value": {
                        "months": [4, 5, 6, 7, 8, 9],
                        "current_month": None,
                        "matched": True,
                    },
                },
            ],
            "context": {
                "current_phase": "Normal",
                "current_month": 4,
            },
        }
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "intervention_recommendation": {
                    "status": "possible",
                    "score": 23,
                    "recommended_action": "select_product",
                    "constraints": [
                        {
                            "code": "phase_compatibility",
                            "label": "Phase moins adaptée (Croissance, Entretien)",
                            "blocking": False,
                            "met": False,
                            "value": {
                                "expected": ["Croissance", "Entretien"],
                                "current": None,
                                "matched": False,
                            },
                        },
                        {
                            "code": "application_months",
                            "label": "Mois compatibles (Avril à Septembre)",
                            "blocking": False,
                            "met": True,
                            "value": {
                                "months": [4, 5, 6, 7, 8, 9],
                                "current_month": None,
                                "matched": True,
                            },
                        },
                    ],
                    "product": {
                        "id": "h2pro_trismart",
                        "name": "H2Pro TriSmart",
                        "type": "Agent Mouillant",
                        "months": [4, 5, 6, 7, 8, 9],
                        "months_label": "Avril à Septembre",
                        "temperature_value": 15.3,
                        "temperature_min": 10,
                        "temperature_max": 30,
                        "temperature_source": "capteur",
                    },
                    "context": {
                        "catalogue_count": 4,
                        "eligible_count": 0,
                        "blocked_products_count": 1,
                        "current_month": 4,
                        "current_phase": "Normal",
                        "current_sub_phase": "Normal",
                    },
                    "ui": {
                        "summary": "À préparer",
                        "hint": "Phase moins adaptée (Croissance, Entretien)",
                    },
                }
            },
            result=stale_result,
            history=[],
            memory={},
        )

        recommendation_sensor = sensor.GazonInterventionRecommendationSensor(coordinator)
        attrs = recommendation_sensor.extra_state_attributes
        self.assertEqual(attrs["runtime_probe"], "constraints_probe_20260404_01")
        self.assertEqual(attrs["current_phase"], "Normal")
        self.assertEqual(attrs["current_month"], 4)
        self.assertEqual(attrs["product_id"], "h2pro_trismart")
        self.assertEqual(attrs["product_name"], "H2Pro TriSmart")

        debug_sensor = sensor.GazonDebugInterventionSensor(coordinator)
        debug_attrs = debug_sensor.extra_state_attributes
        phase_constraint = next(item for item in debug_attrs["constraints"] if item.get("code") == "phase_compatibility")
        month_constraint = next(item for item in debug_attrs["constraints"] if item.get("code") == "application_months")
        self.assertEqual(phase_constraint["value"]["current"], "Normal")
        self.assertEqual(month_constraint["value"]["current_month"], 4)

    def test_projection_entities_use_existing_states_and_signals(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "intervention_recommendation": {
                    "status": "possible",
                    "score": 7,
                    "recommended_action": "select_product",
                    "ready_to_declare": False,
                    "selected_product_ready": False,
                    "product": {
                        "id": "floranid_twin_permanent",
                        "name": "Floranid Twin Permanent",
                    },
                    "ui": {
                        "summary": "À préparer : Floranid Twin Permanent",
                        "hint": "Phase moins adaptée (Croissance, Entretien)",
                    },
                    "context": {
                        "current_phase": "Normal",
                        "current_month": 4,
                    },
                },
                "fenetre_optimale": "attendre",
                "block_reason": "sol_deja_humide",
                "confidence_score": 90,
                "phase_active": "Normal",
                "temperature": 6.9,
                "application_post_watering_status": "non_requis",
                "arrosage_recommande": False,
                "type_arrosage": "bloque",
                "auto_irrigation_enabled": True,
            },
            result=None,
            history=[],
            memory={},
        )

        score_sensor = sensor.GazonScoreNiveauSensor(coordinator)
        window_sensor = sensor.GazonProchaineFenetreOptimaleSensor(coordinator)
        block_sensor = sensor.GazonProchainBlocageAttenduSensor(coordinator)
        irrigation_signal = binary_sensor.GazonSignalIrrigationBinarySensor(coordinator)
        intervention_signal = binary_sensor.GazonSignalInterventionBinarySensor(coordinator)

        self.assertEqual(score_sensor.native_value, "faible")
        score_attrs = score_sensor.extra_state_attributes
        self.assertIsNotNone(score_attrs)
        assert score_attrs is not None
        self.assertEqual(score_attrs["score"], 7)
        self.assertEqual(score_attrs["score_level"], "faible")
        self.assertEqual(score_attrs["tone"], "neutral")
        self.assertEqual(score_attrs["summary"], "Pertinence faible (7/100)")
        self.assertEqual(score_attrs["source_entity"], "sensor.gazon_intelligent_prochaine_intervention")

        self.assertEqual(window_sensor.native_value, "attendre")
        window_attrs = window_sensor.extra_state_attributes
        self.assertIsNotNone(window_attrs)
        assert window_attrs is not None
        self.assertEqual(window_attrs["source_state"], "attendre")
        self.assertEqual(window_attrs["block_reason"], "sol_deja_humide")
        self.assertEqual(window_attrs["confidence_score"], 90)
        self.assertEqual(window_attrs["phase"], "Normal")
        self.assertEqual(window_attrs["month"], 4)
        self.assertEqual(window_attrs["temperature"], 6.9)
        self.assertEqual(window_attrs["summary"], "Prochaine fenêtre: Attendre")

        self.assertEqual(block_sensor.native_value, "sol_deja_humide")
        block_attrs = block_sensor.extra_state_attributes
        self.assertIsNotNone(block_attrs)
        assert block_attrs is not None
        self.assertEqual(block_attrs["source_status"], "bloque")
        self.assertEqual(block_attrs["block_reason"], "sol_deja_humide")
        self.assertEqual(block_attrs["block_label"], "Sol déjà humide")
        self.assertEqual(block_attrs["summary"], "Blocage attendu: Sol déjà humide")

        self.assertFalse(irrigation_signal.is_on)
        irrigation_attrs = irrigation_signal.extra_state_attributes
        self.assertIsNotNone(irrigation_attrs)
        assert irrigation_attrs is not None
        self.assertEqual(irrigation_attrs["trigger_kind"], "none")
        self.assertEqual(irrigation_attrs["application_post_watering_status"], "non_requis")
        self.assertEqual(irrigation_attrs["summary"], "Aucune irrigation actionnable")

        self.assertFalse(intervention_signal.is_on)
        intervention_attrs = intervention_signal.extra_state_attributes
        self.assertIsNotNone(intervention_attrs)
        assert intervention_attrs is not None
        self.assertEqual(intervention_attrs["source_status"], "preparation")
        self.assertEqual(intervention_attrs["trigger_kind"], "soft")
        self.assertEqual(intervention_attrs["summary"], "À préparer : Floranid Twin Permanent")

        coordinator.data["intervention_recommendation"] = {
            **coordinator.data["intervention_recommendation"],
            "status": "recommended",
            "ready_to_declare": False,
            "selected_product_ready": False,
            "ui": {
                "summary": "Recommandé",
            },
        }
        self.assertTrue(intervention_signal.is_on)
        intervention_attrs = intervention_signal.extra_state_attributes
        self.assertIsNotNone(intervention_attrs)
        assert intervention_attrs is not None
        self.assertEqual(intervention_attrs["trigger_kind"], "recommended")
        self.assertEqual(intervention_attrs["summary"], "Recommandé")

        coordinator.data["intervention_recommendation"] = {
            **coordinator.data["intervention_recommendation"],
            "ready_to_declare": True,
            "selected_product_ready": True,
            "ui": {
                "summary": "Prêt à déclarer",
            },
        }
        self.assertTrue(intervention_signal.is_on)
        intervention_attrs = intervention_signal.extra_state_attributes
        self.assertIsNotNone(intervention_attrs)
        assert intervention_attrs is not None
        self.assertEqual(intervention_attrs["trigger_kind"], "ready")
        self.assertEqual(intervention_attrs["summary"], "Prêt à déclarer")

        coordinator.data["application_post_watering_status"] = "autorise"
        self.assertTrue(irrigation_signal.is_on)
        irrigation_attrs = irrigation_signal.extra_state_attributes
        self.assertIsNotNone(irrigation_attrs)
        assert irrigation_attrs is not None
        self.assertEqual(irrigation_attrs["trigger_kind"], "post_application")
        self.assertEqual(irrigation_attrs["source_status"], "autorise")
        self.assertEqual(irrigation_attrs["summary"], "Irrigation post-application autorisée")

        coordinator.data["application_post_watering_status"] = "non_requis"
        coordinator.data["arrosage_recommande"] = True
        coordinator.data["type_arrosage"] = "auto"
        self.assertTrue(irrigation_signal.is_on)
        irrigation_attrs = irrigation_signal.extra_state_attributes
        self.assertIsNotNone(irrigation_attrs)
        assert irrigation_attrs is not None
        self.assertEqual(irrigation_attrs["trigger_kind"], "hydrique")
        self.assertEqual(irrigation_attrs["source_status"], "auto")
        self.assertEqual(irrigation_attrs["summary"], "Irrigation hydrique actionnable")

    def test_expected_block_sensor_reports_none_cleanly_without_real_block_reason(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "fenetre_optimale": "attendre",
                "confidence_score": 92,
                "phase_active": "Normal",
                "temperature": 18.9,
            },
            result=None,
            history=[],
            memory={},
        )

        block_sensor = sensor.GazonProchainBlocageAttenduSensor(coordinator)

        self.assertEqual(block_sensor.native_value, "aucun")
        attrs = block_sensor.extra_state_attributes
        self.assertIsNotNone(attrs)
        assert attrs is not None
        self.assertEqual(attrs["source_status"], "attendre")
        self.assertEqual(attrs["summary"], "Aucun blocage attendu")
        self.assertNotIn("block_reason", attrs)
        self.assertNotIn("block_label", attrs)

    def test_objectif_sensor_prefers_daily_hydric_balance_over_soil_reserve_for_labels(self) -> None:
        result = _make_result()
        result.extra.update(
            {
                "bilan_hydrique_mm": 15.6,
                "bilan_hydrique_journalier_mm": -1.1,
                "bilan_hydrique_precedent_mm": 16.7,
                "deficit_3j": 3.4,
                "deficit_7j": 8.0,
            }
        )
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={},
        )

        objectif_sensor = sensor.GazonObjectifMmSensor(coordinator)
        attrs = objectif_sensor.extra_state_attributes

        self.assertEqual(objectif_sensor.native_value, 1.2)
        self.assertEqual(attrs["bilan_hydrique_mm"], -1.1)
        self.assertEqual(attrs["bilan_hydrique_journalier_mm"], -1.1)
        self.assertEqual(attrs["reserve_hydrique_sol_mm"], 15.6)
        self.assertEqual(attrs["hydric_balance_level"], "déficit")
        self.assertEqual(attrs["hydric_strategy"], "arroser profondément")

    def test_intervention_product_select_includes_application_months(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})
        coordinator.products = {
            "humuslight": {
                "id": "humuslight",
                "nom": "Humuslight",
                "application_months": [3, 4, 5, 9, 10],
                "application_months_label": "Mars à Mai, Septembre à Octobre",
            }
        }
        coordinator.selected_product_id = "humuslight"

        product_select = select.GazonInterventionProductSelect(coordinator)

        self.assertEqual(product_select.options, ["Humuslight · Mars à Mai, Septembre à Octobre"])
        self.assertEqual(product_select.current_option, "Humuslight · Mars à Mai, Septembre à Octobre")
        self.assertEqual(
            product_select.extra_state_attributes["selected_product_months_label"],
            "Mars à Mai, Septembre à Octobre",
        )

    def test_intervention_product_select_handles_empty_catalogue(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})

        product_select = select.GazonInterventionProductSelect(coordinator)

        self.assertEqual(product_select.options, [])
        self.assertIsNone(product_select.current_option)
        self.assertIsNone(product_select.extra_state_attributes["selected_product_id"])
        self.assertIsNone(product_select.extra_state_attributes["selected_product_name"])
        self.assertNotIn("selected_product_months", product_select.extra_state_attributes)
        self.assertEqual(product_select.extra_state_attributes["summary"], "Aucun produit enregistré")

    def test_intervention_product_select_maps_label_to_product_id(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})
        coordinator.products = {
            "bio-1": {"id": "bio-1", "nom": "Bio Boost"},
        }
        coordinator.async_set_selected_product = AsyncMock()

        product_select = select.GazonInterventionProductSelect(coordinator)
        asyncio.run(product_select.async_select_option("Bio Boost"))

        coordinator.async_set_selected_product.assert_awaited_once_with("bio-1")

    def test_intervention_product_select_handles_duplicate_names(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})
        coordinator.products = {
            "bio-1": {"id": "bio-1", "nom": "Produit Standard"},
            "bio-2": {"id": "bio-2", "nom": "Produit Standard"},
        }

        product_select = select.GazonInterventionProductSelect(coordinator)

        self.assertEqual(
            product_select.options,
            ["Aucun produit sélectionné", "Produit Standard — bio-1", "Produit Standard — bio-2"],
        )
        self.assertEqual(product_select.current_option, "Aucun produit sélectionné")
        self.assertEqual(product_select.extra_state_attributes["summary"], "Aucun produit sélectionné")

    def test_intervention_product_select_can_clear_selection(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})
        coordinator.products = {
            "bio-1": {"id": "bio-1", "nom": "Bio Boost"},
            "bio-2": {"id": "bio-2", "nom": "Produit Standard"},
        }
        coordinator.selected_product_id = "bio-1"
        coordinator.async_set_selected_product = AsyncMock()

        product_select = select.GazonInterventionProductSelect(coordinator)
        asyncio.run(product_select.async_select_option("Aucun produit sélectionné"))

        coordinator.async_set_selected_product.assert_awaited_once_with(None)

    def test_intervention_product_select_defaults_to_single_product(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})
        coordinator.products = {
            "bio-1": {"id": "bio-1", "nom": "Bio Boost"},
        }

        product_select = select.GazonInterventionProductSelect(coordinator)

        self.assertEqual(product_select.options, ["Bio Boost"])
        self.assertEqual(product_select.current_option, "Bio Boost")
        self.assertEqual(product_select.extra_state_attributes["selected_product_id"], "bio-1")
        self.assertNotIn("selected_product_usage_mode", product_select.extra_state_attributes)
        self.assertEqual(product_select.extra_state_attributes["summary"], "Produit sélectionné : Bio Boost")

    def test_niveau_action_sensor_uses_friendly_state_for_no_action(self) -> None:
        result = _make_result()
        result.niveau_action = "surveiller"
        result.objectif_arrosage = 0.0
        result.arrosage_recommande = False
        result.type_arrosage = "personnalise"
        result.decision_resume = {
            "action": "aucune_action",
            "moment": "attendre",
            "objectif_mm": 0.0,
            "type_arrosage": "aucune_action",
        }
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=result, history=[], memory={})

        niveau_sensor = sensor.GazonNiveauActionSensor(coordinator)
        type_sensor = sensor.GazonTypeArrosageSensor(coordinator)
        conseil_sensor = sensor.GazonConseilPrincipalSensor(coordinator)
        irrigation_sensor = binary_sensor.GazonArrosageRecommandeBinarySensor(coordinator)
        irrigation_signal = binary_sensor.GazonSignalIrrigationBinarySensor(coordinator)

        self.assertEqual(niveau_sensor.native_value, "aucune_action")
        self.assertIn("aucune_action", niveau_sensor.extra_state_attributes["possible_values"])
        self.assertEqual(type_sensor.native_value, "Aucune action")
        self.assertIn("Aucune action", type_sensor.extra_state_attributes["possible_values"])
        self.assertNotIn("Réglage personnalisé", type_sensor.extra_state_attributes["possible_values"])
        self.assertEqual(conseil_sensor.extra_state_attributes["type_arrosage"], "aucune_action")
        self.assertEqual(irrigation_sensor.extra_state_attributes["type_arrosage"], "aucune_action")
        self.assertEqual(irrigation_signal.extra_state_attributes["type_arrosage"], "aucune_action")

    def test_watering_progress_sensor_exposes_active_session(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})
        started_at = datetime(2026, 3, 21, 8, 0, tzinfo=timezone.utc)
        coordinator._watering_session = {
            "started_at": started_at,
            "last_activity_at": started_at,
            "last_inactive_at": None,
            "zones": {
                "switch.zone_1": {
                    "order": 1,
                    "zone": "switch.zone_1",
                    "entity_id": "switch.zone_1",
                    "rate_mm_h": 10.0,
                    "duration_seconds": 180.0,
                    "mm": 0.5,
                    "started_at": started_at,
                    "ended_at": None,
                }
            },
            "active_zones": {"switch.zone_1": started_at},
            "zone_order": 1,
        }

        progress_sensor = sensor.GazonArrosageEnCoursSensor(coordinator)

        self.assertEqual(progress_sensor.native_value, 0.0)
        self.assertTrue(progress_sensor.extra_state_attributes["active"])
        self.assertEqual(progress_sensor.extra_state_attributes["active_zone_count"], 1)
        self.assertEqual(progress_sensor.extra_state_attributes["zone_count"], 1)
        self.assertEqual(progress_sensor.extra_state_attributes["started_at_utc"], started_at.isoformat())
        self.assertIn("Démarré", progress_sensor.extra_state_attributes["detail"])
        self.assertTrue(progress_sensor.extra_state_attributes["summary"].startswith("Arrosage en cours"))

    def test_plan_sensor_distinguishes_single_zone_without_fractionation(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "objectif_mm": 1.0,
                "zone_1": "switch.zone_1",
                "debit_zone_1": 60.0,
            },
            result=None,
            history=[],
            memory={},
        )

        plan_sensor = sensor.GazonPlanArrosageSensor(coordinator)

        self.assertEqual(plan_sensor.native_value, 1.0)
        self.assertEqual(plan_sensor.extra_state_attributes["plan_type"], "single_zone")
        self.assertFalse(plan_sensor.extra_state_attributes["fractionation"])
        self.assertEqual(plan_sensor.extra_state_attributes["zone_count"], 1)

    def test_watering_window_sensor_exposes_contextual_status(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=_make_result(),
            history=[],
            memory={},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)

        self.assertEqual(window_sensor.native_value, "demain_matin")
        self.assertEqual(window_sensor.extra_state_attributes["status"], "auto")
        self.assertEqual(window_sensor.extra_state_attributes["next_action"], "Aucune action requise")
        self.assertEqual(window_sensor.extra_state_attributes["summary"], "Arrosage prévu demain matin (auto)")
        self.assertEqual(window_sensor.extra_state_attributes["next_action_date"], "2026-03-18")
        self.assertEqual(window_sensor.extra_state_attributes["next_action_display"], "18/03/2026")
        self.assertNotIn("watering_target_date", window_sensor.extra_state_attributes)

    def test_watering_window_sensor_exposes_morning_same_day_status(self) -> None:
        result = _make_result()
        result.fenetre_optimale = "ce_matin"
        result.extra["watering_target_date"] = date(2026, 3, 17).isoformat()

        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)

        self.assertEqual(window_sensor.native_value, "ce_matin")
        self.assertEqual(window_sensor.extra_state_attributes["summary"], "Arrosage prévu ce matin (auto)")
        self.assertEqual(window_sensor.extra_state_attributes["next_action_date"], "2026-03-17")
        self.assertEqual(window_sensor.extra_state_attributes["next_action_display"], "17/03/2026")
        self.assertNotIn("watering_target_date", window_sensor.extra_state_attributes)

    def test_watering_window_sensor_uses_manual_immediate_wording(self) -> None:
        result = _make_result()
        result.extra["application_irrigation_mode"] = "manuel"
        result.extra["application_type"] = "sol"
        result.extra["application_requires_watering_after"] = True
        result.extra["application_post_watering_pending"] = True
        result.extra["application_post_watering_ready"] = True
        result.extra["application_block_active"] = False
        result.extra["objective_mm"] = 1.0
        result.extra["watering_target_date"] = "2026-03-18"
        result.extra["derniere_application"] = {
            "libelle": "Engrais granulé",
            "application_type": "sol",
            "application_requires_watering_after": True,
        }
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)

        self.assertEqual(window_sensor.extra_state_attributes["next_action"], "Arrosage manuel immédiat")
        self.assertNotIn("Forcer", window_sensor.extra_state_attributes["next_action"])

    def test_auto_irrigation_switch_off_blocks_auto_window_and_application_sensor(self) -> None:
        result = _make_result()
        result.extra["auto_irrigation_enabled"] = False
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={"auto_irrigation_enabled": False},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)
        application_allowed_sensor = binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator)

        self.assertEqual(window_sensor.extra_state_attributes["status"], "bloque")
        self.assertEqual(window_sensor.extra_state_attributes["summary"], "Arrosage automatique désactivé")
        self.assertEqual(window_sensor.extra_state_attributes["next_action"], "Réactiver l'arrosage automatique")
        self.assertFalse(window_sensor.extra_state_attributes["auto_irrigation_enabled"])
        self.assertFalse(application_allowed_sensor.is_on)
        self.assertFalse(application_allowed_sensor.extra_state_attributes["auto_irrigation_enabled"])

    def test_watering_window_sensor_blocks_unknown_application_type(self) -> None:
        result = _make_result()
        result.extra["derniere_application"] = {
            "libelle": "Produit inconnu",
            "type": "Traitement",
            "application_type": "autre",
            "application_requires_watering_after": True,
        }
        result.extra["application_type"] = "autre"
        result.extra["application_requires_watering_after"] = True
        result.extra["application_block_active"] = False
        result.extra["application_post_watering_pending"] = False
        result.extra["arrosage_recommande"] = False
        result.extra["objectif_mm"] = 0.0
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)

        self.assertEqual(window_sensor.extra_state_attributes["status"], "bloque")
        self.assertIn("type d'application inconnu", window_sensor.extra_state_attributes["summary"])
        self.assertEqual(window_sensor.extra_state_attributes["next_action"], "Vérifier le type d'application")

    def test_application_entities_surface_latest_application_state(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=None,
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "produit_id": "humuslight",
                    "produit": "Humuslight",
                    "dose": "12.5",
                    "source": "service",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "auto",
                    "application_label_notes": "Bien arroser après application",
                }
            ],
        )

        last_application_sensor = sensor.GazonDerniereApplicationSensor(coordinator)
        application_allowed_sensor = binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator)

        self.assertEqual(last_application_sensor.native_value, "Humuslight")
        self.assertEqual(last_application_sensor.extra_state_attributes["application_type"], "sol")
        self.assertEqual(last_application_sensor.extra_state_attributes["application_irrigation_mode"], "auto")
        self.assertNotIn("application_type", application_allowed_sensor.extra_state_attributes["derniere_application"])
        self.assertNotIn(
            "application_requires_watering_after",
            application_allowed_sensor.extra_state_attributes["derniere_application"],
        )
        self.assertTrue(application_allowed_sensor.is_on)
        self.assertEqual(application_allowed_sensor.extra_state_attributes["application_post_watering_mm"], 1.0)

    def test_application_state_falls_back_to_history_without_memory(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=None,
            history=[
                {
                    "type": "Fertilisation",
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "produit": "Engrais printemps",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "auto",
                }
            ],
            memory=None,
        )

        last_application_sensor = sensor.GazonDerniereApplicationSensor(coordinator)
        application_allowed_sensor = binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator)

        self.assertEqual(last_application_sensor.native_value, "Engrais printemps")
        self.assertEqual(
            last_application_sensor.extra_state_attributes["summary"],
            "Dernière application: Engrais printemps - le 18/03/2026 - type sol - mode auto",
        )
        self.assertEqual(
            last_application_sensor.extra_state_attributes["last_application_when"],
            "18/03/2026",
        )
        self.assertTrue(application_allowed_sensor.is_on)
        self.assertEqual(application_allowed_sensor.extra_state_attributes["application_type"], "sol")

    def test_catalogue_products_sensor_lists_registered_products(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})
        coordinator.products = {
            "bio-1": {
                "id": "bio-1",
                "nom": "Bio Boost",
                "type": "Biostimulant",
                "application_type": "sol",
                "application_requires_watering_after": True,
            },
            "engrais-printemps": {
                "id": "engrais-printemps",
                "nom": "Engrais Printemps",
                "type": "Fertilisation",
                "application_type": "sol",
                "application_irrigation_mode": "suggestion",
            },
        }

        catalogue_sensor = sensor.GazonCatalogueProduitsSensor(coordinator)

        self.assertEqual(catalogue_sensor.native_value, 2)
        self.assertEqual(catalogue_sensor.extra_state_attributes["products_count"], 2)
        self.assertEqual(
            catalogue_sensor.extra_state_attributes["product_ids"],
            ["bio-1", "engrais-printemps"],
        )
        self.assertEqual(
            catalogue_sensor.extra_state_attributes["product_names"],
            ["Bio Boost", "Engrais Printemps"],
        )
        self.assertEqual(
            catalogue_sensor.extra_state_attributes["products_summary"][0]["id"],
            "bio-1",
        )
        self.assertNotIn("phase_compatible", catalogue_sensor.extra_state_attributes["products_summary"][0])
        self.assertEqual(
            catalogue_sensor.extra_state_attributes["products_summary"][1]["application_irrigation_mode"],
            "suggestion",
        )
        self.assertNotIn("application_label_notes", catalogue_sensor.extra_state_attributes["products_summary"][1])

    def test_user_action_sensor_exposes_human_readable_summary(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=None,
            history=[],
            memory={
                "derniere_action_utilisateur": {
                    "state": "en_attente",
                    "action": "Arrosage manuel",
                    "triggered_at": "2026-03-18T08:15:00+00:00",
                    "reason": "Séquence lancée",
                    "plan_type": "single_zone",
                    "zone_count": 1,
                    "passages": 1,
                }
            },
        )

        action_sensor = sensor.GazonDerniereActionUtilisateurSensor(coordinator)

        self.assertEqual(action_sensor.native_value, "en_attente")
        self.assertEqual(
            action_sensor.extra_state_attributes["summary"],
            f"Dernière exécution: Arrosage manuel - le {_local_text('2026-03-18T08:15:00+00:00')} - état en_attente",
        )
        self.assertEqual(
            action_sensor.extra_state_attributes["last_action_when"],
            _local_text("2026-03-18T08:15:00+00:00"),
        )
        self.assertEqual(action_sensor.extra_state_attributes["execution_action"], "Arrosage manuel")
        self.assertEqual(action_sensor.extra_state_attributes["execution_state"], "en_attente")
        self.assertEqual(action_sensor.extra_state_attributes["execution_plan_type"], "single_zone")
        self.assertEqual(action_sensor.extra_state_attributes["executed_zone_count"], 1)
        self.assertEqual(action_sensor.extra_state_attributes["executed_passages"], 1)
        self.assertEqual(action_sensor.extra_state_attributes["execution_reason"], "Séquence lancée")
        self.assertEqual(
            action_sensor.extra_state_attributes["execution_triggered_at"],
            "2026-03-18T08:15:00+00:00",
        )
        self.assertNotIn("action", action_sensor.extra_state_attributes)
        self.assertNotIn("plan_type", action_sensor.extra_state_attributes)
        self.assertNotIn("zone_count", action_sensor.extra_state_attributes)
        self.assertNotIn("passages", action_sensor.extra_state_attributes)

    def test_conseil_principal_sensor_surfaces_summary_in_attributes(self) -> None:
        result = _make_result()
        result.decision_resume = {
            "faire": True,
            "action": "arrosage",
            "moment": "demain_matin",
            "objectif_mm": 1.2,
            "type_arrosage": "manuel_frequent",
            "niveau_action": "a_faire",
            "risque_gazon": "eleve",
        }
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
        )

        advice_sensor = sensor.GazonConseilPrincipalSensor(coordinator)

        self.assertEqual(advice_sensor.native_value, "Arroser demain matin.")
        self.assertEqual(advice_sensor.extra_state_attributes["summary"], "Arroser demain matin.")
        self.assertEqual(advice_sensor.extra_state_attributes["action_type"], "arrosage")
        self.assertEqual(advice_sensor.extra_state_attributes["action_moment"], "demain_matin")
        self.assertEqual(advice_sensor.extra_state_attributes["objectif_mm"], 1.2)
        self.assertEqual(advice_sensor.extra_state_attributes["type_arrosage"], "manuel_frequent")
        self.assertEqual(advice_sensor.extra_state_attributes["next_action_date"], "2026-03-18")
        self.assertEqual(advice_sensor.extra_state_attributes["next_action_display"], "18/03/2026")
        self.assertNotIn("conseil_principal", advice_sensor.extra_state_attributes)

    def test_tonte_sensor_exposes_block_reason_only_when_blocked(self) -> None:
        result = _make_result()
        result.tonte_autorisee = False
        result.tonte_statut = "interdite"
        result.extra["raison_blocage_tonte"] = "Hauteur trop basse."
        result.extra["raison_blocage_code"] = "hauteur_tonte_insuffisante"
        result.extra["next_mowing_date"] = "2026-04-07"
        result.extra["next_mowing_display"] = "07/04/2026"
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
        )

        tonte_sensor = binary_sensor.GazonTonteAutoriseeBinarySensor(coordinator)

        self.assertFalse(tonte_sensor.is_on)
        self.assertEqual(tonte_sensor.extra_state_attributes["raison_blocage_tonte"], "Hauteur trop basse.")
        self.assertEqual(tonte_sensor.extra_state_attributes["raison_blocage_code"], "hauteur_tonte_insuffisante")
        self.assertEqual(tonte_sensor.extra_state_attributes["next_mowing_date"], "2026-04-07")
        self.assertEqual(tonte_sensor.extra_state_attributes["next_mowing_display"], "07/04/2026")
        self.assertNotIn("niveau_action", tonte_sensor.extra_state_attributes)
        self.assertNotIn("fenetre_optimale", tonte_sensor.extra_state_attributes)

    def test_entities_read_decision_result_before_legacy_snapshot(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "phase_active": "Normal",
                "sous_phase_age_days": 20,
                "objectif_mm": 9.9,
                "tonte_autorisee": False,
                "arrosage_recommande": False,
                "tonte_statut": "interdite",
                "niveau_action": "faible",
                "fenetre_optimale": "attendre",
                "risque_gazon": "faible",
                "phase_dominante_source": "legacy",
                "pluie_demain_source": "legacy",
                "configuration": {"type_sol": "sableux"},
                "zone_1": "switch.zone_1",
                "zone_2": "switch.zone_2",
                "debit_zone_1": 60.0,
                "debit_zone_2": 30.0,
            },
            result=_make_result(),
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-03-18",
                    "source": "zone_session",
                    "detected_at": "2026-03-18T06:14:00+00:00",
                    "objectif_mm": 4.0,
                    "total_mm": 4.0,
                    "session_total_mm": 4.0,
                    "zone_count": 2,
                    "zones": [
                        {
                            "order": 1,
                            "zone": "switch.zone_1",
                            "entity_id": "switch.zone_1",
                            "rate_mm_h": 60.0,
                            "duration_min": 2.0,
                            "duration_seconds": 120,
                            "mm": 2.0,
                        },
                        {
                            "order": 2,
                            "zone": "switch.zone_2",
                            "entity_id": "switch.zone_2",
                            "rate_mm_h": 30.0,
                            "duration_min": 4.0,
                            "duration_seconds": 240,
                            "mm": 2.0,
                        },
                    ],
                }
            ],
        )

        phase_sensor = sensor.GazonPhaseActiveSensor(coordinator)
        sous_phase_sensor = sensor.GazonSousPhaseSensor(coordinator)
        objectif_sensor = sensor.GazonObjectifMmSensor(coordinator)
        fenetre_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)
        type_arrosage_sensor = sensor.GazonTypeArrosageSensor(coordinator)
        plan_sensor = sensor.GazonPlanArrosageSensor(coordinator)
        last_watering_sensor = sensor.GazonDernierArrosageDetecteSensor(coordinator)
        hauteur_sensor = sensor.GazonHauteurTonteSensor(coordinator)
        tonte_sensor = binary_sensor.GazonTonteAutoriseeBinarySensor(coordinator)
        arrosage_sensor = binary_sensor.GazonArrosageRecommandeBinarySensor(coordinator)

        self.assertEqual(phase_sensor.native_value, "Sursemis")
        self.assertEqual(phase_sensor.extra_state_attributes["phase_dominante_source"], "historique_actif")
        self.assertEqual(phase_sensor.extra_state_attributes["pluie_demain_source"], "meteo_forecast")
        self.assertEqual(phase_sensor.extra_state_attributes["type_sol"], "argileux")
        self.assertNotIn("configuration", phase_sensor.extra_state_attributes)
        self.assertEqual(sous_phase_sensor.native_value, "Enracinement")
        self.assertEqual(sous_phase_sensor.extra_state_attributes["sous_phase_age_days"], 12)
        self.assertEqual(objectif_sensor.native_value, 1.2)
        self.assertEqual(objectif_sensor.extra_state_attributes["bilan_hydrique_mm"], -1.8)
        self.assertEqual(objectif_sensor.extra_state_attributes["deficit_3j"], 1.2)
        self.assertEqual(objectif_sensor.extra_state_attributes["deficit_7j"], 2.4)
        self.assertEqual(objectif_sensor.extra_state_attributes["pluie_demain"], 0.8)
        self.assertEqual(objectif_sensor.extra_state_attributes["temperature"], 26.5)
        self.assertEqual(objectif_sensor.extra_state_attributes["forecast_temperature_today"], 18.2)
        self.assertEqual(objectif_sensor.extra_state_attributes["temperature_source"], "capteur")
        self.assertEqual(objectif_sensor.extra_state_attributes["etp"], 3.1)
        self.assertEqual(objectif_sensor.extra_state_attributes["hydric_balance_level"], "déficit")
        self.assertEqual(objectif_sensor.extra_state_attributes["hydric_strategy"], "arroser profondément")
        self.assertEqual(fenetre_sensor.native_value, "demain_matin")
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_window_start_minute"], 360)
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_window_end_minute"], 570)
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_evening_start_minute"], 1080)
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_evening_end_minute"], 1260)
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_window_profile"], "mild")
        self.assertFalse(fenetre_sensor.extra_state_attributes["watering_evening_allowed"])
        self.assertEqual(fenetre_sensor.extra_state_attributes["next_action_date"], "2026-03-18")
        self.assertEqual(fenetre_sensor.extra_state_attributes["next_action_display"], "18/03/2026")
        self.assertEqual(type_arrosage_sensor.native_value, "Arrosage fractionné")
        self.assertEqual(hauteur_sensor.native_value, 7.0)
        self.assertEqual(hauteur_sensor.extra_state_attributes["hauteur_tonte_min_cm"], 3.0)
        self.assertEqual(hauteur_sensor.extra_state_attributes["hauteur_tonte_max_cm"], 8.0)
        self.assertEqual(hauteur_sensor.extra_state_attributes["tonte_statut"], "autorisee")
        self.assertEqual(hauteur_sensor.extra_state_attributes["phase_active"], "Sursemis")
        self.assertEqual(
            type_arrosage_sensor.extra_state_attributes["possible_values"],
            [
                "Aucune action",
                "Arrosage bloqué",
                "Réglage personnalisé",
                "Arrosage manuel fréquent",
                "Arrosage fractionné",
                "Arrosage technique",
                "Arrosage automatique",
            ],
        )
        self.assertEqual(plan_sensor.native_value, 3.5)
        self.assertEqual(plan_sensor.extra_state_attributes["objective_mm"], 1.2)
        self.assertEqual(plan_sensor.extra_state_attributes["objectif_mm"], 1.2)
        self.assertEqual(plan_sensor.extra_state_attributes["zone_count"], 2)
        self.assertTrue(plan_sensor.extra_state_attributes["fractionation"])
        self.assertEqual(plan_sensor.extra_state_attributes["plan_type"], "multi_zone")
        self.assertEqual(plan_sensor.extra_state_attributes["source"], "calculated_from_objective")
        self.assertEqual(plan_sensor.extra_state_attributes["total_duration_min"], 3.5)
        self.assertEqual(plan_sensor.extra_state_attributes["duration_human"], "3 min 30")
        self.assertEqual(plan_sensor.extra_state_attributes["summary"], "2 zones • 1.2 mm • 3 min 30")
        self.assertEqual(plan_sensor.extra_state_attributes["passages"], 2)
        self.assertEqual(plan_sensor.extra_state_attributes["pause_between_passages_minutes"], 25)
        self.assertNotIn("min_duration_min", plan_sensor.extra_state_attributes)
        self.assertNotIn("max_duration_min", plan_sensor.extra_state_attributes)
        self.assertEqual(plan_sensor.extra_state_attributes["zones"][0]["zone"], "switch.zone_1")
        self.assertEqual(plan_sensor.extra_state_attributes["zones"][0]["duration_min"], 1.0)
        self.assertEqual(plan_sensor.extra_state_attributes["zones"][1]["duration_min"], 2.5)
        self.assertEqual(last_watering_sensor.native_value, 4.0)
        self.assertEqual(last_watering_sensor.extra_state_attributes["source"], "zone_session")
        self.assertEqual(last_watering_sensor.extra_state_attributes["date_action"], "2026-03-18")
        self.assertEqual(last_watering_sensor.extra_state_attributes["detected_at"], _local_text("2026-03-18T06:14:00+00:00"))
        self.assertEqual(last_watering_sensor.extra_state_attributes["detected_at_utc"], "2026-03-18T06:14:00+00:00")
        self.assertEqual(
            last_watering_sensor.extra_state_attributes["last_watering_when"],
            _local_text("2026-03-18T06:14:00+00:00"),
        )
        self.assertIn(
            f"Dernier arrosage: 4.0 mm le {_local_text('2026-03-18T06:14:00+00:00')}",
            last_watering_sensor.extra_state_attributes["summary"],
        )
        self.assertEqual(last_watering_sensor.extra_state_attributes["zone_count"], 2)
        self.assertEqual(last_watering_sensor.extra_state_attributes["zones_used"], ["switch.zone_1", "switch.zone_2"])
        self.assertEqual(last_watering_sensor.extra_state_attributes["total_mm"], 4.0)
        self.assertNotIn("objectif_mm", last_watering_sensor.extra_state_attributes)
        self.assertNotIn("session_total_mm", last_watering_sensor.extra_state_attributes)
        self.assertEqual(last_watering_sensor.extra_state_attributes["zones"][0]["order"], 1)
        self.assertEqual(last_watering_sensor.extra_state_attributes["zones"][1]["order"], 2)
        self.assertTrue(tonte_sensor.is_on)
        self.assertTrue(arrosage_sensor.is_on)
        self.assertEqual(
            tonte_sensor.extra_state_attributes["hauteur_tonte_recommandee_cm"],
            7.0,
        )
        self.assertEqual(tonte_sensor.extra_state_attributes["hauteur_tonte_min_cm"], 3.0)
        self.assertEqual(tonte_sensor.extra_state_attributes["hauteur_tonte_max_cm"], 8.0)
        self.assertNotIn("niveau_action", tonte_sensor.extra_state_attributes)
        self.assertNotIn("fenetre_optimale", tonte_sensor.extra_state_attributes)
        self.assertNotIn("raison_blocage_tonte", tonte_sensor.extra_state_attributes)
        self.assertIn("possible_values", phase_sensor.extra_state_attributes)
        self.assertIn("possible_values", sous_phase_sensor.extra_state_attributes)

        self.assertEqual(
            phase_sensor.extra_state_attributes["possible_values"],
            [
                "Normal",
                "Sursemis",
                "Traitement",
                "Fertilisation",
                "Biostimulant",
                "Agent Mouillant",
                "Scarification",
                "Hivernage",
            ],
        )
        self.assertIn("Germination", sous_phase_sensor.extra_state_attributes["possible_values"])
        self.assertEqual(
            decision_models.DecisionResult(
                phase_dominante="Normal",
                sous_phase="Normal",
                action_recommandee="",
                action_a_eviter="",
                niveau_action="a_faire",
                fenetre_optimale="maintenant",
                risque_gazon="faible",
                objectif_arrosage=0.0,
                tonte_autorisee=True,
            ).possible_values["niveau_action"],
            ("aucune_action", "surveiller", "a_faire", "critique"),
        )

    def test_sous_phase_is_not_recomputed_locally(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "phase_active": "Sursemis",
                "sous_phase_age_days": 20,
            },
            result=_make_result(),
        )
        result = sensor.GazonSousPhaseSensor(coordinator).native_value

        self.assertEqual(result, "Enracinement")

    def test_pluie_demain_source_is_normalized_when_legacy_snapshot_uses_indisponible(self) -> None:
        result = _make_result()
        result.extra["pluie_demain_source"] = "indisponible"
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={"pluie_demain_source": "indisponible"},
            result=result,
        )

        phase_sensor = sensor.GazonPhaseActiveSensor(coordinator)

        self.assertEqual(phase_sensor.extra_state_attributes["pluie_demain_source"], "non disponible")


if __name__ == "__main__":
    unittest.main()
