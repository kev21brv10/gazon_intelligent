from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
import types
import unittest
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
    ensure_module("homeassistant.helpers")
    util_mod = ensure_module("homeassistant.util")
    if not hasattr(util_mod, "__path__"):
        util_mod.__path__ = []  # type: ignore[attr-defined]
    dt_mod = ensure_module("homeassistant.util.dt")
    dt_mod.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=TEST_TZ)  # type: ignore[attr-defined]

    helpers_entity_mod = ensure_module("homeassistant.helpers.entity")
    if not hasattr(helpers_entity_mod, "DeviceInfo"):
        class DeviceInfo(dict):
            pass

        helpers_entity_mod.DeviceInfo = DeviceInfo

    update_coordinator_mod = ensure_module("homeassistant.helpers.update_coordinator")
    if not hasattr(update_coordinator_mod, "CoordinatorEntity"):
        class CoordinatorEntity:
            def __init__(self, coordinator):
                self.coordinator = coordinator

        update_coordinator_mod.CoordinatorEntity = CoordinatorEntity


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_stubs()

decision_models = __import__("custom_components.gazon_intelligent.decision_models", fromlist=["DecisionResult"])
entity_base = __import__("custom_components.gazon_intelligent.entity_base", fromlist=["GazonEntityBase"])


@dataclass
class _FakeEntry:
    entry_id: str = "entry123"


@dataclass
class _FakeCoordinator:
    entry: _FakeEntry
    data: object | None = None
    result: object | None = None
    last_result: object | None = None


class _ProbeEntity(entity_base.GazonEntityBase):
    pass


def _make_result(**overrides):
    payload = {
        "phase_dominante": "Normal",
        "sous_phase": "Normal",
        "action_recommandee": "",
        "action_a_eviter": "",
        "niveau_action": "surveiller",
        "fenetre_optimale": "attendre",
        "risque_gazon": "faible",
        "objectif_arrosage": 1.2,
        "tonte_autorisee": True,
        "extra": {},
    }
    payload.update(overrides)
    return decision_models.DecisionResult(**payload)


class EntityBaseTests(unittest.TestCase):
    def test_decision_value_prefers_result_then_extra_over_snapshot(self) -> None:
        result = _make_result(
            objectif_arrosage=2.34,
            extra={"temperature": 21.26},
        )
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={"objectif_mm": 9.9, "temperature": 11.1},
            result=result,
        )
        entity = _ProbeEntity(coordinator)

        self.assertEqual(entity._decision_value("objectif_mm"), 2.3)
        self.assertEqual(entity._decision_value("temperature"), 21.3)

    def test_decision_value_falls_back_to_last_result(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={"niveau_action": "critique"},
            last_result=_make_result(niveau_action="a_faire"),
        )
        entity = _ProbeEntity(coordinator)

        self.assertEqual(entity._decision_value("niveau_action"), "a_faire")

    def test_decision_value_falls_back_to_snapshot_data_when_no_result_exists(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={"reserve_stock_mm": 17, "temperature": 18.26},
        )
        entity = _ProbeEntity(coordinator)

        self.assertEqual(entity._decision_value("reserve_stock_mm"), 17.0)
        self.assertEqual(entity._decision_value("temperature"), 18.3)

    def test_normalization_preserves_shapes_for_dicts_lists_and_scalars(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "water_balance": {
                    "temperature": 19.26,
                    "reserve_stock_mm": 12,
                    "history": [0.33333, 1.66666],
                }
            },
        )
        entity = _ProbeEntity(coordinator)

        self.assertEqual(
            entity._decision_value("water_balance"),
            {
                "temperature": 19.3,
                "reserve_stock_mm": 12.0,
                "history": [0.333, 1.667],
            },
        )

    def test_possible_values_attr_uses_legacy_fallback_without_result(self) -> None:
        entity = _ProbeEntity(_FakeCoordinator(entry=_FakeEntry(), data={}))

        self.assertEqual(
            entity._possible_values_attr("niveau_action"),
            {"possible_values": ["aucune_action", "surveiller", "a_faire", "critique"]},
        )

    def test_attrs_from_data_tolerate_missing_or_invalid_snapshot(self) -> None:
        missing_data_entity = _ProbeEntity(types.SimpleNamespace(entry=_FakeEntry()))
        invalid_data_entity = _ProbeEntity(_FakeCoordinator(entry=_FakeEntry(), data="invalid"))

        self.assertEqual(missing_data_entity._decision_value("temperature", "fallback"), "fallback")
        self.assertIsNone(missing_data_entity._attrs_from_data("temperature", "objectif_mm"))
        self.assertEqual(invalid_data_entity._decision_value("temperature", "fallback"), "fallback")
        self.assertIsNone(invalid_data_entity._attrs_from_data("temperature", "objectif_mm"))

    def test_decision_attrs_keep_result_priority_without_merging_snapshot(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={"temperature": 14.2, "objectif_mm": 9.9},
            result=_make_result(objectif_arrosage=1.4),
        )
        entity = _ProbeEntity(coordinator)

        self.assertEqual(entity._decision_attrs("objectif_mm", "temperature"), {"objectif_mm": 1.4})


if __name__ == "__main__":
    unittest.main()
