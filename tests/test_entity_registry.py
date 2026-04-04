from __future__ import annotations

import asyncio
import importlib
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


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)


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

    switch_mod = ensure_module("homeassistant.components.switch")
    if not hasattr(switch_mod, "SwitchEntity"):
        switch_mod.SwitchEntity = type("SwitchEntity", (), {"__init__": lambda self, *args, **kwargs: None})

    button_mod = ensure_module("homeassistant.components.button")
    if not hasattr(button_mod, "ButtonEntity"):
        button_mod.ButtonEntity = type("ButtonEntity", (), {"__init__": lambda self, *args, **kwargs: None})

    select_mod = ensure_module("homeassistant.components.select")
    if not hasattr(select_mod, "SelectEntity"):
        select_mod.SelectEntity = type("SelectEntity", (), {"__init__": lambda self, *args, **kwargs: None})

    number_mod = ensure_module("homeassistant.components.number")
    if not hasattr(number_mod, "NumberEntity"):
        number_mod.NumberEntity = type("NumberEntity", (), {"__init__": lambda self, *args, **kwargs: None})

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

    const_mod = ensure_module("homeassistant.const")
    if not hasattr(const_mod, "EVENT_HOMEASSISTANT_STARTED"):
        const_mod.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"

    exceptions_mod = ensure_module("homeassistant.exceptions")
    if not hasattr(exceptions_mod, "HomeAssistantError"):
        class HomeAssistantError(Exception):
            pass

        exceptions_mod.HomeAssistantError = HomeAssistantError


_install_homeassistant_stubs()

entity_ids = importlib.import_module("custom_components.gazon_intelligent.entity_ids")
entity_migration = importlib.import_module("custom_components.gazon_intelligent.entity_migration")
sensor = importlib.import_module("custom_components.gazon_intelligent.sensor")
binary_sensor = importlib.import_module("custom_components.gazon_intelligent.binary_sensor")
switch = importlib.import_module("custom_components.gazon_intelligent.switch")
button = importlib.import_module("custom_components.gazon_intelligent.button")
number = importlib.import_module("custom_components.gazon_intelligent.number")
select = importlib.import_module("custom_components.gazon_intelligent.select")


@dataclass
class _FakeEntry:
    entry_id: str = "entry123"


@dataclass
class _FakeCoordinator:
    entry: _FakeEntry
    data: dict[str, object]


@dataclass
class _FakeRegistryEntry:
    entity_id: str
    unique_id: str
    config_entry_id: str


class _FakeRegistry:
    def __init__(self, entries: list[_FakeRegistryEntry]) -> None:
        self.entities = {entry.entity_id: entry for entry in entries}

    def async_update_entity(self, current_entity_id: str, *, new_entity_id: str) -> None:
        entry = self.entities.pop(current_entity_id)
        entry.entity_id = new_entity_id
        self.entities[new_entity_id] = entry


class EntityRegistryTests(unittest.TestCase):
    def test_all_exposed_entities_have_known_suffixes(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={})
        entities = [
            sensor.GazonPhaseActiveSensor(coordinator),
            sensor.GazonSousPhaseSensor(coordinator),
            sensor.GazonObjectifMmSensor(coordinator),
            sensor.GazonTypeArrosageSensor(coordinator),
            sensor.GazonPlanArrosageSensor(coordinator),
            sensor.GazonDernierArrosageDetecteSensor(coordinator),
            sensor.GazonDerniereApplicationSensor(coordinator),
            sensor.GazonDerniereActionUtilisateurSensor(coordinator),
            sensor.GazonCatalogueProduitsSensor(coordinator),
            sensor.GazonInterventionRecommendationSensor(coordinator),
            sensor.GazonDebugInterventionSensor(coordinator),
            sensor.GazonScoreNiveauSensor(coordinator),
            sensor.GazonProchaineFenetreOptimaleSensor(coordinator),
            sensor.GazonProchainBlocageAttenduSensor(coordinator),
            sensor.GazonArrosageEnCoursSensor(coordinator),
            sensor.GazonTonteEtatSensor(coordinator),
            sensor.GazonHauteurTonteSensor(coordinator),
            sensor.GazonConseilPrincipalSensor(coordinator),
            sensor.GazonAssistantSensor(coordinator),
            sensor.GazonActionRecommandeeSensor(coordinator),
            sensor.GazonActionAEviterSensor(coordinator),
            sensor.GazonNiveauActionSensor(coordinator),
            sensor.GazonFenetreOptimaleSensor(coordinator),
            sensor.GazonRisqueGazonSensor(coordinator),
            binary_sensor.GazonTonteAutoriseeBinarySensor(coordinator),
            binary_sensor.GazonArrosageRecommandeBinarySensor(coordinator),
            binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator),
            binary_sensor.GazonSignalIrrigationBinarySensor(coordinator),
            binary_sensor.GazonSignalInterventionBinarySensor(coordinator),
            switch.GazonAutoIrrigationSwitch(coordinator),
            button.ArroserMaintenantButton(coordinator),
            button.RetourModeNormalButton(coordinator),
            button.DateActionAujourdhuiButton(coordinator),
            select.GazonModeSelect(coordinator),
            select.GazonInterventionProductSelect(coordinator),
            number.GazonDebitZoneNumber(coordinator, 1, "debit_zone_1"),
            number.GazonDebitZoneNumber(coordinator, 2, "debit_zone_2"),
            number.GazonDebitZoneNumber(coordinator, 3, "debit_zone_3"),
            number.GazonDebitZoneNumber(coordinator, 4, "debit_zone_4"),
            number.GazonDebitZoneNumber(coordinator, 5, "debit_zone_5"),
            number.GazonMowerSettingNumber(
                coordinator,
                "Hauteur min tondeuse",
                "hauteur_min_tondeuse_cm",
                "hauteur_min_tondeuse_cm",
                0.5,
                15.0,
                3.0,
            ),
            number.GazonMowerSettingNumber(
                coordinator,
                "Hauteur max tondeuse",
                "hauteur_max_tondeuse_cm",
                "hauteur_max_tondeuse_cm",
                0.5,
                15.0,
                8.0,
            ),
        ]
        suffixes = {
            entity._attr_unique_id.split("_", 1)[1]  # noqa: SLF001
            for entity in entities
        }

        self.assertEqual(suffixes, entity_ids.ACTIVE_ENTITY_SUFFIXES)
        self.assertEqual(
            {entity.entity_id for entity in entities},
            {
                entity_ids.public_entity_id(entity_ids.public_entity_domain(suffix), suffix)
                for suffix in entity_ids.ACTIVE_ENTITY_SUFFIXES
            },
        )

    def test_button_labels_are_explicit(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={})
        self.assertEqual(button.ArroserMaintenantButton(coordinator)._attr_name, "Arrosage manuel immédiat")
        self.assertEqual(
            switch.GazonAutoIrrigationSwitch(coordinator)._attr_translation_key,
            "auto_irrigation_enabled",
        )

    def test_config_numbers_do_not_expose_decision_attributes(self) -> None:
        self.assertNotIn("extra_state_attributes", number.GazonDebitZoneNumber.__dict__)
        self.assertNotIn("extra_state_attributes", number.GazonMowerSettingNumber.__dict__)
        self.assertEqual(number.GazonMowerSettingNumber._attr_native_step, 0.5)

    def test_mode_select_remains_config_only(self) -> None:
        self.assertNotIn("extra_state_attributes", select.GazonModeSelect.__dict__)

    def test_entity_registry_alignment_renames_known_entities(self) -> None:
        registry = _FakeRegistry(
            [
                _FakeRegistryEntry(
                    entity_id="select.gazon_intelligent_produit_selectionne",
                    unique_id="entry123_produit_intervention",
                    config_entry_id="entry123",
                ),
                _FakeRegistryEntry(
                    entity_id="switch.gazon_intelligent_auto_irrigation_enabled",
                    unique_id="entry123_arrosage_automatique",
                    config_entry_id="entry123",
                ),
            ]
        )

        updates = asyncio.run(entity_migration.async_align_entity_ids(None, "entry123", entity_registry=registry))

        self.assertEqual(
            updates,
            [
                (
                    "select.gazon_intelligent_produit_selectionne",
                    "select.gazon_intelligent_produit_d_intervention",
                ),
                (
                    "switch.gazon_intelligent_auto_irrigation_enabled",
                    "switch.gazon_intelligent_arrosage_automatique_autorise",
                ),
            ],
        )
        self.assertIn("select.gazon_intelligent_produit_d_intervention", registry.entities)
        self.assertIn("switch.gazon_intelligent_arrosage_automatique_autorise", registry.entities)
