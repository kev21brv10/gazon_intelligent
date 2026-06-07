from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from datetime import datetime
import sys
import types
from importlib import util
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


def _install_stubs() -> None:
    def ensure_module(name: str) -> types.ModuleType:
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            sys.modules[name] = module
        return module

    voluptuous = ensure_module("voluptuous")
    if not hasattr(voluptuous, "UNDEFINED"):
        voluptuous.UNDEFINED = object()

    class _Marker:
        def __init__(self, kind: str, *args, **kwargs):
            self.kind = kind
            self.args = args
            self.kwargs = kwargs

        def __hash__(self) -> int:
            return id(self)

    if not hasattr(voluptuous, "Schema"):
        class Schema:
            def __init__(self, schema):
                self.schema = schema

        voluptuous.Schema = Schema
    if not hasattr(voluptuous, "Required"):
        voluptuous.Required = lambda *args, **kwargs: _Marker("required", *args, **kwargs)
    if not hasattr(voluptuous, "Optional"):
        voluptuous.Optional = lambda *args, **kwargs: _Marker("optional", *args, **kwargs)
    if not hasattr(voluptuous, "All"):
        voluptuous.All = lambda *args, **kwargs: ("All", args, kwargs)
    if not hasattr(voluptuous, "Coerce"):
        voluptuous.Coerce = lambda *args, **kwargs: ("Coerce", args, kwargs)
    if not hasattr(voluptuous, "Range"):
        voluptuous.Range = lambda *args, **kwargs: ("Range", args, kwargs)
    if not hasattr(voluptuous, "In"):
        voluptuous.In = lambda *args, **kwargs: ("In", args, kwargs)

    homeassistant = ensure_module("homeassistant")
    ensure_module("homeassistant.config_entries")
    ensure_module("homeassistant.helpers")
    util_mod = ensure_module("homeassistant.util")
    if not hasattr(util_mod, "__path__"):
        util_mod.__path__ = []  # type: ignore[attr-defined]
    dt_mod = ensure_module("homeassistant.util.dt")
    dt_mod.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=TEST_TZ)  # type: ignore[attr-defined]

    config_entries = sys.modules["homeassistant.config_entries"]
    if not hasattr(config_entries, "ConfigEntry"):
        class ConfigEntry:
            pass

        config_entries.ConfigEntry = ConfigEntry
    if not hasattr(config_entries, "ConfigFlow"):
        class ConfigFlow:
            def __init_subclass__(cls, **kwargs):
                return super().__init_subclass__()

            def async_show_form(self, **kwargs):
                return kwargs

            def async_create_entry(self, **kwargs):
                return kwargs

            def async_update_reload_and_abort(self, entry, data_updates=None):
                return {"entry": entry, "data_updates": data_updates, "abort": True}

            async def async_set_unique_id(self, *args, **kwargs):
                return None

            def _abort_if_unique_id_configured(self):
                return None

            def _get_reconfigure_entry(self):
                return getattr(self, "_reconfigure_entry", None)

        config_entries.ConfigFlow = ConfigFlow
    if not hasattr(config_entries, "OptionsFlow"):
        class OptionsFlow:
            def __init_subclass__(cls, **kwargs):
                return super().__init_subclass__()

        config_entries.OptionsFlow = OptionsFlow

    selector_mod = ensure_module("homeassistant.helpers.selector")
    if not hasattr(selector_mod, "EntitySelectorConfig"):
        class EntitySelectorConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        selector_mod.EntitySelectorConfig = EntitySelectorConfig
    if not hasattr(selector_mod, "EntitySelector"):
        selector_mod.EntitySelector = lambda *args, **kwargs: ("EntitySelector", args, kwargs)
    if not hasattr(selector_mod, "TextSelector"):
        selector_mod.TextSelector = lambda *args, **kwargs: ("TextSelector", args, kwargs)
    if not hasattr(selector_mod, "NumberSelectorConfig"):
        class NumberSelectorConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        selector_mod.NumberSelectorConfig = NumberSelectorConfig
    if not hasattr(selector_mod, "NumberSelector"):
        selector_mod.NumberSelector = lambda *args, **kwargs: ("NumberSelector", args, kwargs)
    if not hasattr(selector_mod, "SelectSelectorConfig"):
        class SelectSelectorConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        selector_mod.SelectSelectorConfig = SelectSelectorConfig
    if not hasattr(selector_mod, "SelectSelector"):
        selector_mod.SelectSelector = lambda *args, **kwargs: ("SelectSelector", args, kwargs)


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_stubs()

_load = util.spec_from_file_location
const_spec = _load("custom_components.gazon_intelligent.const", PACKAGE_DIR / "const.py")
assert const_spec and const_spec.loader
const_mod = util.module_from_spec(const_spec)
sys.modules["custom_components.gazon_intelligent.const"] = const_mod
const_spec.loader.exec_module(const_mod)

config_flow_spec = _load("custom_components.gazon_intelligent.config_flow", PACKAGE_DIR / "config_flow.py")
assert config_flow_spec and config_flow_spec.loader
config_flow_mod = util.module_from_spec(config_flow_spec)
sys.modules["custom_components.gazon_intelligent.config_flow"] = config_flow_mod
config_flow_spec.loader.exec_module(config_flow_mod)

entity_migration_spec = _load("custom_components.gazon_intelligent.entity_migration", PACKAGE_DIR / "entity_migration.py")
assert entity_migration_spec and entity_migration_spec.loader
entity_migration_mod = util.module_from_spec(entity_migration_spec)
sys.modules["custom_components.gazon_intelligent.entity_migration"] = entity_migration_mod
entity_migration_spec.loader.exec_module(entity_migration_mod)


class ConfigFlowTests(unittest.TestCase):
    def test_config_flow_version_matches_current_migration_version(self) -> None:
        self.assertEqual(
            config_flow_mod.GazonIntelligentConfigFlow.VERSION,
            entity_migration_mod.CURRENT_CONFIG_ENTRY_VERSION,
        )

    def test_base_schema_requires_only_primary_zone(self) -> None:
        schema = config_flow_mod.build_schema(None)
        required_fields = {
            key.args[0]
            for key in schema.schema
            if getattr(key, "kind", None) == "required"
        }
        optional_fields = {
            key.args[0]
            for key in schema.schema
            if getattr(key, "kind", None) == "optional"
        }

        self.assertIn(config_flow_mod.CONF_ZONE_1, required_fields)
        self.assertNotIn(config_flow_mod.CONF_ZONE_2, required_fields)
        self.assertIn(config_flow_mod.CONF_ZONE_2, optional_fields)
        self.assertIn(config_flow_mod.CONF_ZONE_3, optional_fields)
        self.assertIn(config_flow_mod.CONF_ZONE_4, optional_fields)
        self.assertIn(config_flow_mod.CONF_ZONE_5, optional_fields)

    def test_new_setup_schema_requires_instance_slug(self) -> None:
        schema = config_flow_mod.build_schema(include_instance_slug=True)
        required_fields = {
            key.args[0]
            for key in schema.schema
            if getattr(key, "kind", None) == "required"
        }

        self.assertIn(config_flow_mod.CONF_INSTANCE_SLUG, required_fields)

    def test_build_schema_handles_first_install_without_current_data(self) -> None:
        schema = config_flow_mod.build_schema()

        self.assertIsNotNone(schema)

    def test_build_schema_handles_explicit_none_current_data(self) -> None:
        schema = config_flow_mod.build_schema(None)

        self.assertIsNotNone(schema)

    def test_build_advanced_schema_handles_empty_current_data(self) -> None:
        schema = config_flow_mod.build_advanced_schema()

        self.assertIsNotNone(schema)
        optional_fields = {
            key.args[0]
            for key in schema.schema
            if getattr(key, "kind", None) == "optional"
        }
        self.assertIn(config_flow_mod.CONF_HAUTEUR_MIN_TONDEUSE_CM, optional_fields)
        self.assertIn(config_flow_mod.CONF_HAUTEUR_MAX_TONDEUSE_CM, optional_fields)
        self.assertIn(config_flow_mod.CONF_ENTITE_TONDEUSE, optional_fields)
        self.assertIn(config_flow_mod.CONF_CAPTEUR_TONDEUSE_ERREUR, optional_fields)
        self.assertIn(config_flow_mod.CONF_CAPTEUR_TONDEUSE_BATTERIE, optional_fields)
        self.assertIn(config_flow_mod.CONF_CAPTEUR_TONDEUSE_PLUIE, optional_fields)
        self.assertIn(config_flow_mod.CONF_CAPTEUR_TONDEUSE_EN_CHARGE, optional_fields)
        self.assertIn(config_flow_mod.CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART, optional_fields)
        self.assertIn(config_flow_mod.CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE, optional_fields)

    def test_shared_weather_defaults_are_loaded_from_shared_state(self) -> None:
        fake_hass = types.SimpleNamespace(data={})
        shared_state = config_flow_mod.get_shared_state(fake_hass)
        assert shared_state is not None
        shared_state.shared_config[config_flow_mod.CONF_ENTITE_METEO] = "weather.maison"
        shared_state.shared_config[config_flow_mod.CONF_CAPTEUR_PLUIE_24H] = "sensor.pluie_24h"

        defaults = config_flow_mod._shared_config_defaults(fake_hass)

        self.assertEqual(defaults[config_flow_mod.CONF_ENTITE_METEO], "weather.maison")
        self.assertEqual(defaults[config_flow_mod.CONF_CAPTEUR_PLUIE_24H], "sensor.pluie_24h")

    def test_advanced_schema_uses_shared_default_when_local_option_is_empty(self) -> None:
        schema = config_flow_mod.build_advanced_schema(
            {config_flow_mod.CONF_CAPTEUR_TEMPERATURE: None},
            shared_defaults={config_flow_mod.CONF_CAPTEUR_TEMPERATURE: "sensor.temperature_partagee"},
        )

        defaults = {
            key.args[0]: key.kwargs.get("default")
            for key in schema.schema
            if getattr(key, "kind", None) in {"required", "optional"}
        }

        self.assertEqual(
            defaults[config_flow_mod.CONF_CAPTEUR_TEMPERATURE],
            "sensor.temperature_partagee",
        )

    def test_shared_weather_config_can_be_cleared_with_none_or_empty_string(self) -> None:
        fake_hass = types.SimpleNamespace(data={})
        shared_state = config_flow_mod.get_shared_state(fake_hass)
        assert shared_state is not None
        shared_state.shared_config[config_flow_mod.CONF_ENTITE_METEO] = "weather.maison"
        shared_state.shared_config[config_flow_mod.CONF_CAPTEUR_PLUIE_24H] = "sensor.pluie_24h"

        asyncio.run(
            shared_state.async_update_shared_config(
                {
                    config_flow_mod.CONF_ENTITE_METEO: None,
                    config_flow_mod.CONF_CAPTEUR_PLUIE_24H: "",
                }
            )
        )

        self.assertNotIn(config_flow_mod.CONF_ENTITE_METEO, shared_state.shared_config)
        self.assertNotIn(config_flow_mod.CONF_CAPTEUR_PLUIE_24H, shared_state.shared_config)
        self.assertEqual(config_flow_mod._shared_config_defaults(fake_hass), {})

    def test_initial_flow_shows_sensors_second_page(self) -> None:
        flow = config_flow_mod.GazonIntelligentConfigFlow()
        base_input = {
            config_flow_mod.CONF_INSTANCE_SLUG: "jardin_avant",
            config_flow_mod.CONF_ZONE_1: "switch.zone_1",
            config_flow_mod.CONF_DEBIT_ZONE_1: 10,
            config_flow_mod.CONF_DEBIT_ZONE_2: 0,
            config_flow_mod.CONF_DEBIT_ZONE_3: 0,
            config_flow_mod.CONF_DEBIT_ZONE_4: 0,
            config_flow_mod.CONF_DEBIT_ZONE_5: 0,
            config_flow_mod.CONF_TYPE_SOL: "limoneux",
        }

        result = asyncio.run(flow.async_step_user(base_input))

        self.assertEqual(result["step_id"], "sensors")

    def test_new_instance_flow_uses_slugged_unique_id_and_title(self) -> None:
        flow = config_flow_mod.GazonIntelligentConfigFlow()
        recorded: dict[str, str] = {}

        async def fake_async_set_unique_id(value):
            recorded["unique_id"] = value

        flow.async_set_unique_id = fake_async_set_unique_id  # type: ignore[method-assign]
        flow._abort_if_unique_id_configured = lambda: None  # type: ignore[method-assign]

        base_input = {
            config_flow_mod.CONF_INSTANCE_SLUG: "jardin_avant",
            config_flow_mod.CONF_ZONE_1: "switch.zone_1",
            config_flow_mod.CONF_DEBIT_ZONE_1: 10,
            config_flow_mod.CONF_DEBIT_ZONE_2: 0,
            config_flow_mod.CONF_DEBIT_ZONE_3: 0,
            config_flow_mod.CONF_DEBIT_ZONE_4: 0,
            config_flow_mod.CONF_DEBIT_ZONE_5: 0,
            config_flow_mod.CONF_TYPE_SOL: "limoneux",
        }

        asyncio.run(flow.async_step_user(base_input))
        result = asyncio.run(flow.async_step_sensors({}))

        self.assertEqual(recorded["unique_id"], "gazon_intelligent:jardin_avant")
        self.assertEqual(result["title"], "Gazon Intelligent - Jardin Avant")

    def test_reconfigure_flow_updates_base_configuration(self) -> None:
        flow = config_flow_mod.GazonIntelligentConfigFlow()
        flow._reconfigure_entry = types.SimpleNamespace(
            data={
                config_flow_mod.CONF_ZONE_1: "switch.zone_1",
                config_flow_mod.CONF_DEBIT_ZONE_1: 10,
                config_flow_mod.CONF_TYPE_SOL: "limoneux",
            },
            options={},
        )

        form = asyncio.run(flow.async_step_reconfigure())

        self.assertEqual(form["step_id"], "reconfigure")

        updated = asyncio.run(
            flow.async_step_reconfigure(
                {
                    config_flow_mod.CONF_ZONE_1: "switch.zone_2",
                    config_flow_mod.CONF_DEBIT_ZONE_1: 12,
                    config_flow_mod.CONF_TYPE_SOL: "argileux",
                }
            )
        )

        self.assertTrue(updated["abort"])
        self.assertEqual(updated["entry"].data[config_flow_mod.CONF_ZONE_1], "switch.zone_1")
        self.assertEqual(updated["data_updates"][config_flow_mod.CONF_ZONE_1], "switch.zone_2")
        self.assertEqual(updated["data_updates"][config_flow_mod.CONF_DEBIT_ZONE_1], 12)
        self.assertEqual(updated["data_updates"][config_flow_mod.CONF_TYPE_SOL], "argileux")

    def test_reconfigure_flow_handles_empty_existing_config(self) -> None:
        flow = config_flow_mod.GazonIntelligentConfigFlow()
        flow._reconfigure_entry = types.SimpleNamespace(data={}, options={})

        form = asyncio.run(flow.async_step_reconfigure())

        self.assertEqual(form["step_id"], "reconfigure")


if __name__ == "__main__":
    unittest.main()
