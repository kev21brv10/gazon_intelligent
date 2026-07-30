from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
import types
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


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_stubs()

assistant = __import__("custom_components.gazon_intelligent.assistant", fromlist=["build_assistant_decision"])
sensor = __import__("custom_components.gazon_intelligent.sensor", fromlist=["GazonAssistantSensor"])


@dataclass
class _FakeEntry:
    entry_id: str = "entry123"


@dataclass
class _FakeCoordinator:
    entry: _FakeEntry
    data: dict[str, object]
    result: object | None = None
    last_result: object | None = None


class AssistantDecisionTests(unittest.TestCase):
    def test_build_assistant_decision_priority_is_explicit_and_stable(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "objectif_mm": 0.5,
                "arrosage_recommande": True,
                "fenetre_optimale": "ce_matin",
                "conseil_principal": "Arrose ce matin.",
                "phase_dominante": "Traitement",
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
            }
        )

        self.assertEqual(decision["action"], "arrosage")
        self.assertEqual(decision["moment"], "ce_matin")

    def test_build_assistant_decision_prefers_irrigation(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "objectif_mm": 0.5,
                "arrosage_recommande": True,
                "fenetre_optimale": "ce_matin",
                "conseil_principal": "Arrose ce matin.",
            }
        )

        self.assertEqual(decision["action"], "arrosage")
        self.assertEqual(decision["moment"], "ce_matin")
        self.assertEqual(decision["quantity_mm"], 0.5)
        self.assertEqual(decision["status"], "action_required")
        self.assertNotEqual(decision["reason"], "")

    def test_build_assistant_decision_marks_blocked_irrigation(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "objectif_mm": 0.5,
                "arrosage_recommande": True,
                "fenetre_optimale": "ce_matin",
                "block_reason": "cooldown_24h",
            }
        )

        self.assertEqual(decision["action"], "arrosage")
        self.assertEqual(decision["moment"], "attendre")
        self.assertEqual(decision["quantity_mm"], 0.0)
        self.assertEqual(decision["status"], "blocked")
        # Libellé changé en 0.28.0 : le garde n'est plus « 24 h glissantes » mais
        # « une fois par jour ». Le CODE `cooldown_24h` reste (contrat public consommé
        # par la carte et les automatisations) ; seul le texte affiché suit la réalité.
        self.assertEqual(decision["reason"], "Déjà arrosé aujourd'hui")

    def test_build_assistant_decision_irrigation_block_precedes_recommendation_reason(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "objectif_mm": 0.5,
                "arrosage_recommande": True,
                "fenetre_optimale": "ce_matin",
                "block_reason": "pluie_active",
                "conseil_principal": "Arrose ce matin.",
            }
        )

        self.assertEqual(decision["action"], "arrosage")
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["reason"], "Pluie active")

    def test_build_assistant_decision_prefers_critical_action_when_irrigation_absent(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "phase_dominante": "Traitement",
                "conseil_principal": "Traitement actif.",
            }
        )

        self.assertEqual(decision["action"], "traitement")
        self.assertEqual(decision["moment"], "maintenant")
        self.assertEqual(decision["quantity_mm"], 0.0)
        self.assertEqual(decision["status"], "action_required")
        self.assertEqual(decision["reason"], "Traitement actif.")

    def test_build_assistant_decision_does_not_keep_post_application_wait_message_when_done(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "phase_dominante": "Fertilisation",
                "application_type": "sol",
                "application_requires_watering_after": True,
                "application_post_watering_status": "termine",
                "application_post_watering_pending": False,
                "type_arrosage": "bloque",
                "block_reason": "sol_deja_humide",
                "fenetre_optimale": "attendre",
                "conseil_principal": "Traitement bloqué pour le moment.",
            }
        )

        self.assertEqual(decision["action"], "none")
        self.assertEqual(decision["status"], "blocked_due_to_conditions")
        self.assertEqual(decision["reason"], "Sol déjà humide")

    def test_build_assistant_decision_falls_back_to_mowing(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
            }
        )

        self.assertEqual(decision["action"], "tonte")
        self.assertEqual(decision["moment"], "maintenant")
        self.assertEqual(decision["quantity_mm"], 0.0)
        self.assertEqual(decision["status"], "action_required")
        self.assertEqual(decision["reason"], "Tonte autorisée")

    def test_build_assistant_decision_blocks_mowing_when_robot_is_not_ready(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
                "tondeuse_prete": False,
                "tondeuse_statut_libelle": "En charge",
                "tondeuse_raison": "Tondeuse en charge.",
            }
        )

        self.assertEqual(decision["action"], "tonte")
        self.assertEqual(decision["moment"], "attendre")
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["reason"], "Tondeuse en charge.")

    def test_build_assistant_decision_blocks_mowing_when_robot_is_actively_mowing(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
                "tondeuse_prete": True,
                "mower_operation_state": "tonte",
                "mower_operation_label": "Tonte en cours",
                "mower_reason_code": "mower_mowing",
                "mower_reason_label": "Tondeuse en cours de tonte.",
            }
        )

        self.assertEqual(decision["action"], "tonte")
        self.assertEqual(decision["moment"], "attendre")
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["reason"], "Tondeuse en cours de tonte.")

    def test_build_assistant_decision_blocks_mowing_with_battery_low_reason(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
                "tondeuse_prete": False,
                "tondeuse_statut_libelle": "Erreur",
                "tondeuse_raison": "Battery low",
            }
        )

        self.assertEqual(decision["action"], "tonte")
        self.assertEqual(decision["moment"], "attendre")
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["reason"], "Batterie faible")

    def test_build_assistant_decision_blocks_mowing_when_sun_is_below_horizon(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "tonte_autorisee": False,
                "tonte_statut": "interdite",
                "mowing_block_reason_code": "mowing_night",
                "mowing_block_reason_label": "Nuit: attendre le lever du soleil.",
                "tondeuse_prete": True,
            }
        )

        self.assertEqual(decision["action"], "tonte")
        self.assertEqual(decision["moment"], "attendre")
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["reason"], "Nuit: attendre le lever du soleil.")

    def test_build_assistant_decision_uses_mowing_block_reason_from_watering_coordination(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
                "mowing_block_reason_code": "watering_cooldown",
            }
        )

        self.assertEqual(decision["action"], "tonte")
        self.assertEqual(decision["moment"], "attendre")
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["reason"], "Cooldown tonte après arrosage")

    def test_build_assistant_decision_uses_mower_watering_block_reason(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "arrosage_recommande": True,
                "objectif_mm": 5.0,
                "type_arrosage": "bloque",
                "watering_block_reason_code": "mower_mowing",
            }
        )

        self.assertEqual(decision["action"], "arrosage")
        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["reason"], "Tondeuse en cours de tonte")

    def test_build_assistant_decision_ignores_incoherent_mowing_block_when_not_allowed(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "tonte_autorisee": False,
                "tonte_statut": "bloque",
                "raison_blocage_tonte": "Surface non sèche",
            }
        )

        self.assertEqual(decision["action"], "none")
        self.assertEqual(decision["status"], "no_need")

    def test_build_assistant_decision_returns_none_when_no_action(self) -> None:
        decision = assistant.build_assistant_decision({})

        self.assertEqual(decision["action"], "none")
        self.assertEqual(decision["moment"], "none")
        self.assertEqual(decision["quantity_mm"], 0.0)
        self.assertEqual(decision["status"], "no_need")
        self.assertEqual(decision["reason"], "conditions optimales")

    def test_build_assistant_decision_uses_blocked_snapshot_reason_when_no_action(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "type_arrosage": "bloque",
                "block_reason": "pluie_prevue_suffisante",
                "fenetre_optimale": "apres_pluie",
                "conseil_principal": "Phase Biostimulant: n'arrose pas pour l'instant.",
            }
        )

        self.assertEqual(decision["action"], "none")
        self.assertEqual(decision["moment"], "apres_pluie")
        self.assertEqual(decision["quantity_mm"], 0.0)
        self.assertEqual(decision["status"], "blocked_due_to_conditions")
        self.assertEqual(decision["reason"], "Pluie prévue suffisante")

    def test_build_assistant_decision_keeps_passive_irrigation_ok_when_objective_is_zero(self) -> None:
        decision = assistant.build_assistant_decision(
            {
                "type_arrosage": "bloque",
                "block_reason": "humidite_excessive",
                "fenetre_optimale": "attendre",
                "conseil_principal": "N'arrose pas pour le moment.",
                "objectif_mm": 0.0,
                "mm_requested": 0.0,
                "application_post_watering_status": "non_requis",
            }
        )

        self.assertEqual(decision["action"], "none")
        self.assertEqual(decision["moment"], "attendre")
        self.assertEqual(decision["quantity_mm"], 0.0)
        self.assertEqual(decision["status"], "blocked_due_to_conditions")
        self.assertEqual(decision["reason"], "Humidité excessive")

    def test_sensor_exposes_contract_from_snapshot(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "assistant": {
                    "action": "tonte",
                    "moment": "maintenant",
                    "quantity_mm": 0.0,
                    "status": "action_required",
                    "reason": "Tonte autorisée",
                    "next_action_date": "2026-03-28",
                    "next_action_display": "28/03/2026",
                }
            },
        )

        entity = sensor.GazonAssistantSensor(coordinator)

        self.assertEqual(entity.native_value, "tonte")
        self.assertEqual(entity.extra_state_attributes["action"], "tonte")
        self.assertEqual(entity.extra_state_attributes["moment"], "maintenant")
        self.assertEqual(entity.extra_state_attributes["quantity_mm"], 0.0)
        self.assertEqual(entity.extra_state_attributes["status"], "action_required")
        self.assertEqual(entity.extra_state_attributes["reason"], "Tonte autorisée")
        self.assertEqual(entity.extra_state_attributes["next_action_date"], "2026-03-28")
        self.assertEqual(entity.extra_state_attributes["next_action_display"], "28/03/2026")
        self.assertEqual(entity._attr_name, "Assistant")

    def test_sensor_uses_friendly_state_for_none_action(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={"assistant": assistant.DEFAULT_ASSISTANT_DECISION})
        entity = sensor.GazonAssistantSensor(coordinator)

        self.assertEqual(entity.native_value, "aucune_action")
        self.assertEqual(entity.extra_state_attributes["action"], "aucune_action")
        self.assertEqual(entity.extra_state_attributes["moment"], "attendre")
        self.assertEqual(entity.extra_state_attributes["status"], "no_need")
        self.assertEqual(entity.extra_state_attributes["reason"], "conditions optimales")

    def test_sensor_exposes_next_action_date_when_available(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "assistant": {
                    "action": "aucune_action",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "no_need",
                    "reason": "conditions optimales",
                    "next_action_date": "2026-03-27",
                    "next_action_display": "27/03/2026",
                }
            },
        )
        entity = sensor.GazonAssistantSensor(coordinator)

        self.assertEqual(entity.extra_state_attributes["next_action_date"], "2026-03-27")
        self.assertEqual(entity.extra_state_attributes["next_action_display"], "27/03/2026")

    def test_action_recommandee_sensor_falls_back_to_assistant_when_text_is_generic(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "action_recommandee": "Réévalue au prochain cycle météo.",
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
            },
        )

        entity = sensor.GazonActionRecommandeeSensor(coordinator)

        self.assertEqual(entity.native_value, "Tonte possible maintenant.")

    def test_action_recommandee_sensor_reports_blocked_conditions_for_irrigation(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "action_recommandee": "Réévalue au prochain cycle météo.",
                "type_arrosage": "bloque",
                "block_reason": "sol_deja_humide",
                "objectif_mm": 0.0,
                "mm_requested": 0.0,
                "conseil_principal": "N'arrose pas pour le moment.",
            },
        )

        entity = sensor.GazonActionRecommandeeSensor(coordinator)

        self.assertEqual(entity.native_value, "Arrosage bloqué par conditions: Sol déjà humide.")

    def test_action_recommandee_sensor_reports_low_battery_delay_for_mowing(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "action_recommandee": "Réévalue au prochain cycle météo.",
                "assistant": {
                    "action": "tonte",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "blocked",
                    "reason": "Battery low",
                },
            },
        )

        entity = sensor.GazonActionRecommandeeSensor(coordinator)

        self.assertEqual(entity.native_value, "Tonte différée: batterie faible.")

    def test_action_recommandee_sensor_reports_night_delay_from_sunrise_wording(self) -> None:
        # Ce cas portait le MÊME nom que le suivant : Python ne gardait que la seconde
        # définition et ce corps n'était jamais exécuté. Les deux motifs nocturnes sont
        # pourtant distincts et doivent être couverts séparément.
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "action_recommandee": "Réévalue au prochain cycle météo.",
                "assistant": {
                    "action": "tonte",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "blocked",
                    "reason": "Nuit: attendre le lever du soleil.",
                },
            },
        )

        entity = sensor.GazonActionRecommandeeSensor(coordinator)

        self.assertEqual(entity.native_value, "Tonte différée: nuit en cours.")

    def test_action_recommandee_sensor_reports_night_delay_for_mowing(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "action_recommandee": "Réévalue au prochain cycle météo.",
                "assistant": {
                    "action": "tonte",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "blocked",
                    "reason": "Période nocturne: attends le matin avant de tondre.",
                },
            },
        )

        entity = sensor.GazonActionRecommandeeSensor(coordinator)

        self.assertEqual(entity.native_value, "Tonte différée: nuit en cours.")

    def test_conseil_principal_exposes_public_action_recommandee(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "conseil_principal": "N'arrose pas pour le moment.",
                "action_recommandee": "Réévalue au prochain cycle météo.",
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
            },
        )

        entity = sensor.GazonConseilPrincipalSensor(coordinator)

        self.assertEqual(entity.extra_state_attributes["action_recommandee"], "Tonte possible maintenant.")

    def test_conseil_principal_sensor_builds_global_summary_for_card(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "conseil_principal": "N'arrose pas pour le moment.",
                "action_recommandee": "Réévalue au prochain cycle météo.",
                "arrosage_recommande": False,
                "application_post_watering_status": "non_requis",
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
                "intervention_recommendation": {
                    "status": "preparation",
                    "ready_to_declare": False,
                    "product": {"name": "H2Pro TriSmart"},
                },
            },
        )

        entity = sensor.GazonConseilPrincipalSensor(coordinator)

        expected = "Tonte possible maintenant."
        self.assertEqual(entity.native_value, expected)
        self.assertEqual(entity.extra_state_attributes["summary"], expected)
        self.assertEqual(entity.extra_state_attributes["niveau_action_hydrique"], "aucune_action")

    def test_public_action_prioritizes_watering_block_over_mowing(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "conseil_principal": "Tonte en cours.",
                "action_recommandee": "Réévalue au prochain cycle météo.",
                "type_arrosage": "bloque",
                "block_reason": "sol_non_adapte",
                "watering_cause": "hydrique",
                "arrosage_recommande": False,
                "assistant": {
                    "action": "tonte",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "blocked",
                    "reason": "Tondeuse en cours de tonte.",
                },
            },
        )

        action_entity = sensor.GazonActionRecommandeeSensor(coordinator)
        conseil_entity = sensor.GazonConseilPrincipalSensor(coordinator)

        expected = "Arrosage bloqué par conditions: Sol non adapté."
        self.assertEqual(action_entity.native_value, expected)
        self.assertEqual(conseil_entity.native_value, expected)
        self.assertEqual(conseil_entity.extra_state_attributes["summary"], expected)

    def test_conseil_principal_sensor_reports_low_battery_delay_for_mowing(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "assistant": {
                    "action": "tonte",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "blocked",
                    "reason": "Battery low",
                }
            },
        )

        entity = sensor.GazonConseilPrincipalSensor(coordinator)

        self.assertEqual(entity.native_value, "Tonte différée: batterie faible.")
        self.assertEqual(entity.extra_state_attributes["summary"], "Tonte différée: batterie faible.")

    def test_conseil_principal_sensor_reports_night_delay_from_sunrise_wording(self) -> None:
        # Doublon de nom corrigé : ce corps n'était jamais exécuté (cf. le cas jumeau ci-dessous,
        # qui couvre l'autre formulation nocturne).
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "assistant": {
                    "action": "tonte",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "blocked",
                    "reason": "Nuit: attendre le lever du soleil.",
                }
            },
        )

        entity = sensor.GazonConseilPrincipalSensor(coordinator)

        self.assertEqual(entity.native_value, "Tonte différée: nuit en cours.")
        self.assertEqual(entity.extra_state_attributes["summary"], "Tonte différée: nuit en cours.")

    def test_conseil_principal_sensor_reports_night_delay_for_mowing(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "assistant": {
                    "action": "tonte",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "blocked",
                    "reason": "Période nocturne: attends le matin avant de tondre.",
                }
            },
        )

        entity = sensor.GazonConseilPrincipalSensor(coordinator)

        self.assertEqual(entity.native_value, "Tonte différée: nuit en cours.")
        self.assertEqual(entity.extra_state_attributes["summary"], "Tonte différée: nuit en cours.")

    def test_public_niveau_action_promotes_non_hydric_required_action(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "niveau_action": "aucune_action",
                "objectif_mm": 0.0,
                "arrosage_recommande": False,
                "application_post_watering_status": "non_requis",
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
                "decision_resume": {
                    "action": "aucune_action",
                    "moment": "attendre",
                    "objectif_mm": 0.0,
                    "type_arrosage": "aucune_action",
                },
            },
        )

        niveau_entity = sensor.GazonNiveauActionSensor(coordinator)
        conseil_entity = sensor.GazonConseilPrincipalSensor(coordinator)

        self.assertEqual(niveau_entity.native_value, "a_faire")
        self.assertEqual(niveau_entity.extra_state_attributes["niveau_action_hydrique"], "aucune_action")
        self.assertEqual(conseil_entity.extra_state_attributes["niveau_action"], "a_faire")
        self.assertEqual(conseil_entity.extra_state_attributes["niveau_action_hydrique"], "aucune_action")
