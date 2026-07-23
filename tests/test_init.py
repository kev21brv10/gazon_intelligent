from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock


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


def _ensure_module(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


LIFECYCLE_EVENTS: list[str] = []


def _install_homeassistant_stubs() -> None:
    homeassistant = _ensure_module("homeassistant")
    if not hasattr(homeassistant, "__path__"):
        homeassistant.__path__ = []  # type: ignore[attr-defined]

    config_entries_mod = _ensure_module("homeassistant.config_entries")
    core_mod = _ensure_module("homeassistant.core")
    exceptions_mod = _ensure_module("homeassistant.exceptions")
    util_mod = _ensure_module("homeassistant.util")
    if not hasattr(util_mod, "__path__"):
        util_mod.__path__ = []  # type: ignore[attr-defined]
    dt_mod = _ensure_module("homeassistant.util.dt")
    helpers_mod = _ensure_module("homeassistant.helpers")
    if not hasattr(helpers_mod, "__path__"):
        helpers_mod.__path__ = []  # type: ignore[attr-defined]
    helpers_typing_mod = _ensure_module("homeassistant.helpers.typing")
    entity_registry_mod = _ensure_module("homeassistant.helpers.entity_registry")
    service_mod = _ensure_module("homeassistant.helpers.service")

    class ConfigEntry:
        def __init__(self, entry_id: str = "entry123") -> None:
            self.entry_id = entry_id
            self._update_listeners: list = []
            self._on_unload: list = []

        def add_update_listener(self, listener):
            self._update_listeners.append(listener)

            def _unsub():
                if listener in self._update_listeners:
                    self._update_listeners.remove(listener)

            return _unsub

        def async_on_unload(self, fn):
            self._on_unload.append(fn)
            return fn

    class ServiceCall:
        def __init__(self, hass, data: dict[str, object] | None = None) -> None:
            self.hass = hass
            self.data = data or {}
            self.target_entity_ids = set()
            self.target_config_entry_ids = set()

    class HomeAssistantError(Exception):
        pass

    core_mod.HomeAssistant = object
    core_mod.ServiceCall = ServiceCall
    config_entries_mod.ConfigEntry = ConfigEntry
    exceptions_mod.HomeAssistantError = HomeAssistantError
    helpers_typing_mod.ConfigType = dict
    dt_mod.now = lambda: None
    entity_registry_mod.async_get = lambda hass: getattr(hass, "entity_registry", None)
    async def async_extract_entity_ids(call):
        return getattr(call, "target_entity_ids", set())

    async def async_extract_config_entry_ids(call):
        return getattr(call, "target_config_entry_ids", set())

    service_mod.async_extract_entity_ids = async_extract_entity_ids
    service_mod.async_extract_config_entry_ids = async_extract_config_entry_ids


def _install_voluptuous_stub() -> None:
    vol_mod = types.ModuleType("voluptuous")

    class Schema:
        def __init__(self, schema) -> None:
            self.schema = schema

        def __call__(self, value):
            return value

    def Required(value):
        return value

    def Optional(value):
        return value

    def In(value):
        return value

    def All(*validators):
        return validators

    def Coerce(type_):
        return type_

    def Range(**kwargs):
        return kwargs

    def Any(*validators):
        return validators

    vol_mod.Schema = Schema
    vol_mod.Required = Required
    vol_mod.Optional = Optional
    vol_mod.In = In
    vol_mod.All = All
    vol_mod.Coerce = Coerce
    vol_mod.Range = Range
    vol_mod.Any = Any
    sys.modules["voluptuous"] = vol_mod


class _FakeServices:
    def __init__(self) -> None:
        self._services: dict[tuple[str, str], dict[str, object]] = {}
        self.register_calls: list[tuple[str, str]] = []

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self._services

    def async_register(self, domain: str, service: str, handler, schema=None) -> None:
        self._services[(domain, service)] = {"handler": handler, "schema": schema}
        self.register_calls.append((domain, service))

    def async_remove(self, domain: str, service: str) -> None:
        self._services.pop((domain, service), None)


class _FakeConfigEntriesManager:
    def __init__(self) -> None:
        self.forward_calls: list[tuple[str, tuple[str, ...]]] = []
        self.unload_calls: list[tuple[str, tuple[str, ...]]] = []
        self.unload_result = True

    async def async_forward_entry_setups(self, entry, platforms) -> None:
        self.forward_calls.append((entry.entry_id, tuple(platforms)))

    async def async_unload_platforms(self, entry, platforms) -> bool:
        self.unload_calls.append((entry.entry_id, tuple(platforms)))
        return self.unload_result


class _FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.services = _FakeServices()
        self.config_entries = _FakeConfigEntriesManager()
        self.entity_registry = None


class _FakeRegistryEntity:
    def __init__(self, entity_id: str, unique_id: str, config_entry_id: str) -> None:
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.config_entry_id = config_entry_id


class _FakeEntityRegistry:
    def __init__(self, entities: list[_FakeRegistryEntity]) -> None:
        self.entities = {entity.entity_id: entity for entity in entities}


def _install_component_stubs() -> None:
    coordinator_mod = types.ModuleType("custom_components.gazon_intelligent.coordinator")
    migration_mod = types.ModuleType("custom_components.gazon_intelligent.migration")
    entity_migration_mod = types.ModuleType("custom_components.gazon_intelligent.entity_migration")
    date_utils_mod = types.ModuleType("custom_components.gazon_intelligent.date_utils")

    class FakeCoordinator:
        def __init__(self, hass, entry) -> None:
            self.hass = hass
            self.entry = entry
            self.entry_id = entry.entry_id
            self.async_set_normal = AsyncMock()
            self.async_set_mode = AsyncMock()
            self.async_declare_intervention = AsyncMock()
            self.async_set_date_action = AsyncMock()
            self.async_start_manual_irrigation = AsyncMock()
            self.async_start_auto_irrigation = AsyncMock()
            self.async_start_application_irrigation = AsyncMock()
            self.async_remove_last_application = AsyncMock()
            self.async_record_mowing = AsyncMock()
            self.async_record_watering = AsyncMock()
            self.async_register_product = AsyncMock()
            self.async_remove_product = AsyncMock()
            self.async_shutdown = AsyncMock(side_effect=self._shutdown)
            LIFECYCLE_EVENTS.append("coordinator:init")

        async def async_config_entry_first_refresh(self) -> None:
            LIFECYCLE_EVENTS.append("coordinator:first_refresh")

        async def async_start_source_monitoring(self) -> None:
            LIFECYCLE_EVENTS.append("coordinator:start_source")

        async def async_start_zone_monitoring(self) -> None:
            LIFECYCLE_EVENTS.append("coordinator:start_zone")

        async def async_start_auto_irrigation_monitoring(self) -> None:
            LIFECYCLE_EVENTS.append("coordinator:start_auto")

        def schedule_post_start_refresh(self, delay_seconds: int) -> None:
            LIFECYCLE_EVENTS.append(f"coordinator:schedule:{delay_seconds}")

        async def _shutdown(self) -> None:
            LIFECYCLE_EVENTS.append("coordinator:shutdown")

    async def async_cleanup_obsolete_entities(hass, entry_id: str) -> None:
        LIFECYCLE_EVENTS.append(f"entities:cleanup:{entry_id}")

    async def async_align_entity_ids(hass, entry_id: str, instance_slug=None, entity_registry=None) -> None:
        LIFECYCLE_EVENTS.append(f"entities:align:{entry_id}")

    async def async_migrate_entry(hass, entry) -> bool:
        return True

    def parse_optional_date(value: str | None):
        if value in (None, ""):
            return None
        if value == "bad":
            raise ValueError("bad date")
        day, month, year = str(value).split("/")
        return f"{year}-{month}-{day}"

    coordinator_mod.GazonIntelligentCoordinator = FakeCoordinator
    migration_mod.async_migrate_entry = async_migrate_entry
    entity_migration_mod.async_cleanup_obsolete_entities = async_cleanup_obsolete_entities
    entity_migration_mod.async_align_entity_ids = async_align_entity_ids
    date_utils_mod.parse_optional_date = parse_optional_date

    sys.modules["custom_components.gazon_intelligent.coordinator"] = coordinator_mod
    sys.modules["custom_components.gazon_intelligent.migration"] = migration_mod
    sys.modules["custom_components.gazon_intelligent.entity_migration"] = entity_migration_mod
    sys.modules["custom_components.gazon_intelligent.date_utils"] = date_utils_mod


def _load_init_module():
    for name in [
        "custom_components.gazon_intelligent",
        "custom_components.gazon_intelligent.__init__",
    ]:
        sys.modules.pop(name, None)
    _ensure_package("custom_components", PACKAGE_DIR.parent)
    _ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
    _install_homeassistant_stubs()
    _install_voluptuous_stub()
    _install_component_stubs()
    return importlib.import_module("custom_components.gazon_intelligent.__init__")


class InitModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        LIFECYCLE_EVENTS.clear()
        self.module = _load_init_module()
        self.entry = sys.modules["homeassistant.config_entries"].ConfigEntry("entry-1")
        self.hass = _FakeHass()

    def test_async_setup_initializes_domain_data_and_registers_services_idempotently(self) -> None:
        self.assertTrue(asyncio.run(self.module.async_setup(self.hass, {})))
        self.assertIn(self.module.DOMAIN, self.hass.data)
        self.assertEqual(len(self.hass.services.register_calls), 13)

        self.assertTrue(asyncio.run(self.module.async_setup(self.hass, {})))
        self.assertEqual(len(self.hass.services.register_calls), 13)

    def test_async_setup_entry_handles_empty_hass_data_and_runs_lifecycle_in_order(self) -> None:
        result = asyncio.run(self.module.async_setup_entry(self.hass, self.entry))

        self.assertTrue(result)
        self.assertIn(self.module.DOMAIN, self.hass.data)
        self.assertIn(self.entry.entry_id, self.hass.data[self.module.DOMAIN])
        self.assertEqual(
            LIFECYCLE_EVENTS,
            [
                "coordinator:init",
                "coordinator:first_refresh",
                "entities:cleanup:entry-1",
                "entities:align:entry-1",
                "coordinator:start_source",
                "coordinator:start_zone",
                "coordinator:start_auto",
                "coordinator:schedule:30",
            ],
        )
        self.assertEqual(
            self.hass.config_entries.forward_calls,
            [("entry-1", self.module.PLATFORMS)],
        )

    def test_async_unload_entry_does_not_crash_when_entry_is_missing(self) -> None:
        result = asyncio.run(self.module.async_unload_entry(self.hass, self.entry))

        self.assertTrue(result)
        self.assertEqual(self.hass.config_entries.unload_calls, [("entry-1", self.module.PLATFORMS)])

    def test_get_coordinator_raises_clean_error_when_no_instance_exists(self) -> None:
        error_type = sys.modules["homeassistant.exceptions"].HomeAssistantError
        with self.assertRaises(error_type) as ctx:
            self.module._get_coordinator(self.hass)
        self.assertEqual(str(ctx.exception), self.module._ERR_NO_INSTANCE)

    def test_handle_set_mode_keeps_main_handler_behavior(self) -> None:
        asyncio.run(self.module.async_setup_entry(self.hass, self.entry))
        coordinator = self.hass.data[self.module.DOMAIN][self.entry.entry_id]
        call = sys.modules["homeassistant.core"].ServiceCall(self.hass, {"mode": "Normal"})

        asyncio.run(self.module._handle_set_mode(call))

        coordinator.async_set_mode.assert_awaited_once_with("Normal")

    def test_handle_set_mode_resolves_target_from_entity_id(self) -> None:
        asyncio.run(self.module.async_setup_entry(self.hass, self.entry))
        coordinator = self.hass.data[self.module.DOMAIN][self.entry.entry_id]
        self.hass.entity_registry = _FakeEntityRegistry(
            [
                _FakeRegistryEntity(
                    "sensor.gazon_intelligent_assistant",
                    "entry-1_assistant",
                    self.entry.entry_id,
                )
            ]
        )
        call = sys.modules["homeassistant.core"].ServiceCall(
            self.hass,
            {"mode": "Normal", "entity_id": "sensor.gazon_intelligent_assistant"},
        )

        asyncio.run(self.module._handle_set_mode(call))

        coordinator.async_set_mode.assert_awaited_once_with("Normal")

    def test_handle_set_mode_resolves_target_from_service_target(self) -> None:
        asyncio.run(self.module.async_setup_entry(self.hass, self.entry))
        coordinator = self.hass.data[self.module.DOMAIN][self.entry.entry_id]
        self.hass.entity_registry = _FakeEntityRegistry(
            [
                _FakeRegistryEntity(
                    "sensor.gazon_intelligent_assistant",
                    "entry-1_assistant",
                    self.entry.entry_id,
                )
            ]
        )
        call = sys.modules["homeassistant.core"].ServiceCall(self.hass, {"mode": "Normal"})
        call.target_entity_ids = {"sensor.gazon_intelligent_assistant"}

        asyncio.run(self.module._handle_set_mode(call))

        coordinator.async_set_mode.assert_awaited_once_with("Normal")

    def test_handle_set_date_action_raises_clean_error_on_invalid_date(self) -> None:
        asyncio.run(self.module.async_setup_entry(self.hass, self.entry))
        call = sys.modules["homeassistant.core"].ServiceCall(self.hass, {"date_action": "bad"})
        error_type = sys.modules["homeassistant.exceptions"].HomeAssistantError

        with self.assertRaises(error_type) as ctx:
            asyncio.run(self.module._handle_set_date_action(call))

        self.assertEqual(str(ctx.exception), self.module._ERR_INVALID_DATE)


if __name__ == "__main__":
    unittest.main()


class TargetSelectorOrderTests(unittest.TestCase):
    """Le sélecteur « cible » de l'UI Home Assistant envoie TOUJOURS une liste. Or `vol.Any`
    retient le PREMIER validateur qui ne lève pas, et `vol.Coerce(str)` réussit sur n'importe
    quoi : placée après lui, la variante liste était du code mort et `["sensor.x"]` devenait la
    chaîne `"['sensor.x']"`. Le résolveur échouait alors sur « L'entité cible est introuvable » —
    ce qui a fait échouer un arrosage manuel programmé en production.

    Vérifié avec le vrai voluptuous : ancien ordre -> "['sensor.x']" ; nouvel ordre -> ['sensor.x'].
    Ici le stub réduit `Any(*v)` au tuple des validateurs et `Coerce(str)` à `str`, ce qui permet
    d'épingler l'ORDRE, seul élément en cause.
    """

    def setUp(self) -> None:
        self.module = _load_init_module()

    def test_la_variante_liste_precede_la_coercition_en_chaine(self) -> None:
        validators = list(self.module._target_selector_value())
        index_liste = next(
            i for i, v in enumerate(validators) if isinstance(v, list)
        )
        index_chaine = next(
            i for i, v in enumerate(validators) if v is str
        )
        self.assertLess(
            index_liste,
            index_chaine,
            "la variante liste doit précéder Coerce(str), sinon elle est inatteignable",
        )

    def test_les_trois_variantes_sont_presentes(self) -> None:
        validators = list(self.module._target_selector_value())
        self.assertIn(None, validators)
        self.assertTrue(any(isinstance(v, list) for v in validators))
        self.assertIn(str, validators)


class SingleTargetValueTests(unittest.TestCase):
    """`_single_target_value` normalise la cible, qu'elle arrive en chaîne ou en liste."""

    def setUp(self) -> None:
        self.module = _load_init_module()

    def test_chaine(self) -> None:
        self.assertEqual(self.module._single_target_value("sensor.a"), "sensor.a")

    def test_liste_dun_element(self) -> None:
        self.assertEqual(self.module._single_target_value(["sensor.a"]), "sensor.a")

    def test_liste_de_plusieurs_elements_est_ambigue(self) -> None:
        self.assertIsNone(self.module._single_target_value(["sensor.a", "sensor.b"]))

    def test_valeurs_vides(self) -> None:
        for valeur in (None, "", "   ", [], [""], ["  "]):
            with self.subTest(valeur=valeur):
                self.assertIsNone(self.module._single_target_value(valeur))


class CallHasExplicitTargetTests(unittest.TestCase):
    """Une cible fournie en liste — le cas normal depuis l'UI — était jugée absente, donc en
    multi-instances l'appel échouait sur « Plusieurs gazons existent… »."""

    def setUp(self) -> None:
        self.module = _load_init_module()

    def _call(self, data):
        return types.SimpleNamespace(data=data)

    def test_entity_id_en_liste_est_une_cible_explicite(self) -> None:
        self.assertTrue(self.module._call_has_explicit_target(self._call({"entity_id": ["sensor.a"]})))

    def test_entity_id_en_chaine_est_une_cible_explicite(self) -> None:
        self.assertTrue(self.module._call_has_explicit_target(self._call({"entity_id": "sensor.a"})))

    def test_device_id_et_area_id_sont_pris_en_compte(self) -> None:
        for cle in ("device_id", "area_id"):
            for valeur in ("abc123", ["abc123"]):
                with self.subTest(cle=cle, valeur=valeur):
                    self.assertTrue(
                        self.module._call_has_explicit_target(self._call({cle: valeur}))
                    )

    def test_absence_de_cible(self) -> None:
        self.assertFalse(self.module._call_has_explicit_target(self._call({})))
        self.assertFalse(self.module._call_has_explicit_target(self._call({"entity_id": None})))
