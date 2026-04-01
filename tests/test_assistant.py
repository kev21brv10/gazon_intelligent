from __future__ import annotations

import unittest
from dataclasses import dataclass
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
        self.assertEqual(decision["reason"], "cooldown_24h")

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

    def test_build_assistant_decision_returns_none_when_no_action(self) -> None:
        decision = assistant.build_assistant_decision({})

        self.assertEqual(decision["action"], "none")
        self.assertEqual(decision["moment"], "none")
        self.assertEqual(decision["quantity_mm"], 0.0)
        self.assertEqual(decision["status"], "ok")
        self.assertEqual(decision["reason"], "conditions optimales")

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
        self.assertEqual(entity.extra_state_attributes["status"], "ok")
        self.assertEqual(entity.extra_state_attributes["reason"], "conditions optimales")

    def test_sensor_exposes_next_action_date_when_available(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "assistant": {
                    "action": "aucune_action",
                    "moment": "attendre",
                    "quantity_mm": 0.0,
                    "status": "ok",
                    "reason": "conditions optimales",
                    "next_action_date": "2026-03-27",
                    "next_action_display": "27/03/2026",
                }
            },
        )
        entity = sensor.GazonAssistantSensor(coordinator)

        self.assertEqual(entity.extra_state_attributes["next_action_date"], "2026-03-27")
        self.assertEqual(entity.extra_state_attributes["next_action_display"], "27/03/2026")
