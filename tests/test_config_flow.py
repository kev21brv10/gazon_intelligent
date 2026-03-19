from __future__ import annotations

import unittest
from pathlib import Path
import sys
import types
from importlib import util


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
        def __init__(self, *args, **kwargs):
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
        voluptuous.Required = lambda *args, **kwargs: _Marker(*args, **kwargs)
    if not hasattr(voluptuous, "Optional"):
        voluptuous.Optional = lambda *args, **kwargs: _Marker(*args, **kwargs)
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

    config_entries = sys.modules["homeassistant.config_entries"]
    if not hasattr(config_entries, "ConfigEntry"):
        class ConfigEntry:
            pass

        config_entries.ConfigEntry = ConfigEntry
    if not hasattr(config_entries, "ConfigFlow"):
        class ConfigFlow:
            def __init_subclass__(cls, **kwargs):
                return super().__init_subclass__()

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


class ConfigFlowTests(unittest.TestCase):
    def test_build_schema_handles_first_install_without_current_data(self) -> None:
        schema = config_flow_mod.build_schema()

        self.assertIsNotNone(schema)

    def test_build_advanced_schema_handles_empty_current_data(self) -> None:
        schema = config_flow_mod.build_advanced_schema()

        self.assertIsNotNone(schema)


if __name__ == "__main__":
    unittest.main()
