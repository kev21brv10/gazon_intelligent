from __future__ import annotations

import logging
from typing import Any, Callable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType

try:
    from homeassistant.helpers import config_validation as cv
except ImportError:  # pragma: no cover - compatibility with test stubs / older envs
    cv = None

try:
    from homeassistant.helpers.service import async_extract_config_entry_ids, async_extract_entity_ids
except ImportError:  # pragma: no cover - compatibility with older HA versions
    async_extract_config_entry_ids = None
    async_extract_entity_ids = None

from .const import (
    DOMAIN,
    INTERVENTIONS_ACTIONS,
    MODES_GAZON,
)
from .entity_migration import (
    async_align_entity_ids,
    async_cleanup_obsolete_entities,
)
from .entity_ids import resolve_entry_instance_slug
from .coordinator import GazonIntelligentCoordinator
from .date_utils import parse_optional_date
from .migration import async_migrate_entry as _async_migrate_entry
from .shared_state import get_shared_state

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ("select", "number", "sensor", "binary_sensor", "switch", "button")
_ERR_NO_INSTANCE = "Aucune instance de Gazon Intelligent n'est configurée."
_ERR_AMBIGUOUS_INSTANCE = "Plusieurs instances de Gazon Intelligent existent. Fournissez une cible explicite."
_ERR_INVALID_DATE = "La date doit être au format JJ/MM/AAAA ou YYYY-MM-DD."
def _target_selector_value() -> vol.Any:
    return vol.Any(
        None,
        vol.Coerce(str),
        [vol.Coerce(str)],
    )


_SERVICE_TARGET_FIELD = {
    vol.Optional("entity_id"): _target_selector_value(),
    vol.Optional("device_id"): _target_selector_value(),
    vol.Optional("area_id"): _target_selector_value(),
}

SERVICE_SET_MODE = "set_mode"
SERVICE_SET_DATE_ACTION = "set_date_action"
SERVICE_RESET_MODE = "reset_mode"
SERVICE_START_MANUAL_IRRIGATION = "start_manual_irrigation"
SERVICE_START_AUTO_IRRIGATION = "start_auto_irrigation"
SERVICE_START_APPLICATION_IRRIGATION = "start_application_irrigation"
SERVICE_DECLARE_INTERVENTION = "declare_intervention"
SERVICE_REMOVE_LAST_APPLICATION = "remove_last_application"
SERVICE_DECLARE_MOWING = "declare_mowing"
SERVICE_DECLARE_WATERING = "declare_watering"
SERVICE_REGISTER_PRODUCT = "register_product"
SERVICE_REMOVE_PRODUCT = "remove_product"

if cv is None:
    CONFIG_SCHEMA = vol.Schema({})
else:
    try:
        CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
    except TypeError:  # pragma: no cover - compatibility with older helper signature
        CONFIG_SCHEMA = cv.config_entry_only_config_schema(vol.Schema({DOMAIN: dict}))


def _ensure_domain_data(hass: HomeAssistant) -> dict[str, GazonIntelligentCoordinator]:
    return hass.data.setdefault(DOMAIN, {})


def _get_coordinator(
    hass: HomeAssistant,
    entry_id: str | None = None,
) -> GazonIntelligentCoordinator:
    coordinators = _ensure_domain_data(hass)
    if entry_id:
        coordinator = coordinators.get(entry_id)
        if coordinator is not None:
            return coordinator
        raise HomeAssistantError(_ERR_NO_INSTANCE)
    if not coordinators:
        raise HomeAssistantError(_ERR_NO_INSTANCE)
    return next(iter(coordinators.values()))


def _coordinator_from_entity_id(hass: HomeAssistant, entity_id: str) -> GazonIntelligentCoordinator:
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity = registry.entities.get(entity_id)
    if entity is None:
        raise HomeAssistantError(f"L'entité cible {entity_id} est introuvable.")
    config_entry_id = getattr(entity, "config_entry_id", None)
    if not isinstance(config_entry_id, str) or not config_entry_id:
        raise HomeAssistantError(_ERR_NO_INSTANCE)
    coordinators = _ensure_domain_data(hass)
    coordinator = coordinators.get(config_entry_id)
    if coordinator is None:
        raise HomeAssistantError(_ERR_NO_INSTANCE)
    return coordinator


def _call_has_explicit_target(call: ServiceCall) -> bool:
    target_entity_id = call.data.get("entity_id")
    if isinstance(target_entity_id, str) and target_entity_id.strip():
        return True

    target = getattr(call, "target", None)
    if target is None:
        return False

    target_config_entry_ids = getattr(target, "config_entry_id", None)
    if isinstance(target_config_entry_ids, str) and target_config_entry_ids.strip():
        return True
    if isinstance(target_config_entry_ids, (list, tuple, set)) and len(target_config_entry_ids) == 1:
        return True

    target_entity_ids = getattr(target, "entity_id", None)
    if isinstance(target_entity_ids, str) and target_entity_ids.strip():
        return True
    if isinstance(target_entity_ids, (list, tuple, set)) and len(target_entity_ids) == 1:
        return True

    return False


def _require_explicit_target_for_multi_instance(call: ServiceCall) -> None:
    coordinators = _ensure_domain_data(call.hass)
    if len(coordinators) <= 1:
        return
    if _call_has_explicit_target(call):
        return
    raise HomeAssistantError(
        "Plusieurs gazons existent. Fournissez un entity_id explicite, par exemple "
        "'binary_sensor.gazon_intelligent_tonte_autorisee' ou "
        "'binary_sensor.gazon_intelligent_gazon_potager_tonte_autorisee'."
    )


def _register_service_if_missing(
    hass: HomeAssistant,
    service_name: str,
    handler: Callable[[ServiceCall], Any],
    *,
    schema: vol.Schema | None = None,
) -> None:
    if hass.services.has_service(DOMAIN, service_name):
        return
    hass.services.async_register(
        DOMAIN,
        service_name,
        handler,
        schema=schema,
    )


async def _async_start_runtime_monitoring(coordinator: GazonIntelligentCoordinator) -> None:
    await coordinator.async_start_source_monitoring()
    await coordinator.async_start_zone_monitoring()
    await coordinator.async_start_auto_irrigation_monitoring()


async def _coordinator_from_call(call: ServiceCall) -> GazonIntelligentCoordinator:
    target_entity_id = call.data.get("entity_id")
    if isinstance(target_entity_id, str) and target_entity_id.strip():
        return _coordinator_from_entity_id(call.hass, target_entity_id.strip())

    if async_extract_config_entry_ids is not None:
        target_config_entry_ids = await async_extract_config_entry_ids(call)
        if target_config_entry_ids:
            if len(target_config_entry_ids) == 1:
                return _get_coordinator(call.hass, next(iter(target_config_entry_ids)))
            raise HomeAssistantError(_ERR_AMBIGUOUS_INSTANCE)

    if async_extract_entity_ids is not None:
        target_entity_ids = await async_extract_entity_ids(call)
        if target_entity_ids:
            if len(target_entity_ids) == 1:
                return _coordinator_from_entity_id(call.hass, next(iter(target_entity_ids)))
            raise HomeAssistantError(_ERR_AMBIGUOUS_INSTANCE)

    target = getattr(call, "target", None)
    if target is not None:
        target_config_entry_ids = getattr(target, "config_entry_id", None)
        if isinstance(target_config_entry_ids, str) and target_config_entry_ids.strip():
            return _get_coordinator(call.hass, target_config_entry_ids.strip())
        target_entity_ids = getattr(target, "entity_id", None)
        if isinstance(target_entity_ids, str) and target_entity_ids.strip():
            return _coordinator_from_entity_id(call.hass, target_entity_ids.strip())
        if isinstance(target_entity_ids, (list, tuple, set)) and len(target_entity_ids) == 1:
            return _coordinator_from_entity_id(call.hass, next(iter(target_entity_ids)))

    coordinators = _ensure_domain_data(call.hass)
    if not coordinators:
        raise HomeAssistantError(_ERR_NO_INSTANCE)
    if len(coordinators) == 1:
        return next(iter(coordinators.values()))

    legacy_coordinators = [
        coordinator
        for coordinator in coordinators.values()
        if resolve_entry_instance_slug(coordinator.entry) is None
    ]
    if len(legacy_coordinators) == 1:
        return legacy_coordinators[0]

    raise HomeAssistantError(_ERR_AMBIGUOUS_INSTANCE)


def _async_register_services(hass: HomeAssistant) -> None:
    _register_service_if_missing(
        hass,
        SERVICE_SET_MODE,
        _handle_set_mode,
        schema=vol.Schema({**_SERVICE_TARGET_FIELD, vol.Required("mode"): vol.In(MODES_GAZON)}),
    )
    _register_service_if_missing(
        hass,
        SERVICE_SET_DATE_ACTION,
        _handle_set_date_action,
        schema=vol.Schema({**_SERVICE_TARGET_FIELD, vol.Optional("date_action"): str}),
    )
    _register_service_if_missing(
        hass,
        SERVICE_RESET_MODE,
        _handle_reset_mode,
        schema=vol.Schema(dict(_SERVICE_TARGET_FIELD)),
    )
    _register_service_if_missing(
        hass,
        SERVICE_START_MANUAL_IRRIGATION,
        _handle_start_manual_irrigation,
        schema=vol.Schema(
            {
                **_SERVICE_TARGET_FIELD,
                vol.Required("objectif_mm"): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0, max=30),
                )
            }
        ),
    )
    _register_service_if_missing(
        hass,
        SERVICE_START_AUTO_IRRIGATION,
        _handle_start_auto_irrigation,
        schema=vol.Schema(
            {
                **_SERVICE_TARGET_FIELD,
                vol.Optional("objectif_mm"): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0, max=30),
                ),
                vol.Optional("plan_arrosage_entity"): vol.Coerce(str),
                vol.Optional("source"): vol.Coerce(str),
            }
        ),
    )
    _register_service_if_missing(
        hass,
        SERVICE_START_APPLICATION_IRRIGATION,
        _handle_start_application_irrigation,
        schema=vol.Schema(dict(_SERVICE_TARGET_FIELD)),
    )
    _register_service_if_missing(
        hass,
        SERVICE_DECLARE_INTERVENTION,
        _handle_declare_intervention,
        schema=vol.Schema(
            {
                **_SERVICE_TARGET_FIELD,
                vol.Required("intervention"): vol.In(INTERVENTIONS_ACTIONS),
                vol.Optional("date_action"): str,
                vol.Optional("produit_id"): vol.Coerce(str),
                vol.Optional("produit"): vol.Coerce(str),
                vol.Optional("zone"): vol.Coerce(str),
                vol.Optional("note"): vol.Coerce(str),
            }
        ),
    )
    _register_service_if_missing(
        hass,
        SERVICE_REMOVE_LAST_APPLICATION,
        _handle_remove_last_application,
        schema=vol.Schema(dict(_SERVICE_TARGET_FIELD)),
    )
    _register_service_if_missing(
        hass,
        SERVICE_REGISTER_PRODUCT,
        _handle_register_product,
        schema=vol.Schema(
            {
                **_SERVICE_TARGET_FIELD,
                vol.Required("product_id"): vol.Coerce(str),
                vol.Required("nom"): vol.Coerce(str),
                vol.Required("type"): vol.Coerce(str),
                vol.Optional("dose_conseillee"): vol.Coerce(str),
                vol.Optional("usage_mode"): vol.In(["preventif", "curatif", "entretien", "rattrapage"]),
                vol.Optional("max_applications_per_year"): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=3650),
                ),
                vol.Optional("reapplication_after_days"): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=3650),
                ),
                vol.Optional("delai_avant_tonte_jours"): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=3650),
                ),
                vol.Optional("phase_compatible"): vol.Any([vol.Coerce(str)], vol.Coerce(str)),
                vol.Optional("application_months"): vol.Any([vol.Coerce(int)], vol.Coerce(str)),
                vol.Optional("application_type"): vol.In(["sol", "foliaire"]),
                vol.Optional("application_requires_watering_after"): vol.Coerce(bool),
                vol.Optional("application_post_watering_mm"): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0, max=10),
                ),
                vol.Optional("application_irrigation_block_hours"): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0, max=72),
                ),
                vol.Optional("application_irrigation_delay_minutes"): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0, max=1440),
                ),
                vol.Optional("application_irrigation_mode"): vol.In(["auto", "manuel", "suggestion"]),
                vol.Optional("application_label_notes"): vol.Coerce(str),
                vol.Optional("note"): vol.Coerce(str),
                vol.Optional("temperature_min"): vol.Coerce(float),
                vol.Optional("temperature_max"): vol.Coerce(float),
            }
        ),
    )
    _register_service_if_missing(
        hass,
        SERVICE_REMOVE_PRODUCT,
        _handle_remove_product,
        schema=vol.Schema({**_SERVICE_TARGET_FIELD, vol.Required("product_id"): vol.Coerce(str)}),
    )
    _register_service_if_missing(
        hass,
        SERVICE_DECLARE_MOWING,
        _handle_declare_mowing,
        schema=vol.Schema({**_SERVICE_TARGET_FIELD, vol.Optional("date_action"): str}),
    )
    _register_service_if_missing(
        hass,
        SERVICE_DECLARE_WATERING,
        _handle_declare_watering,
        schema=vol.Schema(
            {
                **_SERVICE_TARGET_FIELD,
                vol.Optional("date_action"): str,
                vol.Optional("objectif_mm"): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0, max=30),
                ),
            }
        ),
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _ensure_domain_data(hass)
    get_shared_state(hass)
    _async_register_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await _async_migrate_entry(hass, entry)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _async_register_services(hass)

    # 1. création du coordinator
    coordinator = GazonIntelligentCoordinator(hass, entry)
    # 2. first refresh
    await coordinator.async_config_entry_first_refresh()
    # 3. enregistrement dans hass.data
    domain_data = _ensure_domain_data(hass)
    domain_data[entry.entry_id] = coordinator
    # 4. cleanup entities
    await async_cleanup_obsolete_entities(hass, entry.entry_id)
    # 5. forward platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # 6. align entity ids
    await async_align_entity_ids(hass, entry.entry_id, instance_slug=resolve_entry_instance_slug(entry))
    # 7. démarrage monitoring
    await _async_start_runtime_monitoring(coordinator)
    # 8. refresh différé
    coordinator.schedule_post_start_refresh(delay_seconds=30)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = _ensure_domain_data(hass)
    coordinator = domain_data.get(entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if coordinator is not None:
            await coordinator.async_shutdown()
        domain_data.pop(entry.entry_id, None)

    return unload_ok


async def _handle_set_mode(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    mode = call.data["mode"]
    await coordinator.async_set_mode(mode)


async def _handle_set_date_action(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)

    try:
        date_str = call.data.get("date_action")
        if date_str:
            date_action = parse_optional_date(date_str)
            if date_action is None:
                raise ValueError(_ERR_INVALID_DATE)
        else:
            date_action = None  # aujourd'hui par défaut
        await coordinator.async_set_date_action(date_action)
    except ValueError as err:
        raise HomeAssistantError(_ERR_INVALID_DATE) from err


async def _handle_reset_mode(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    await coordinator.async_set_normal()


async def _handle_start_manual_irrigation(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    await coordinator.async_start_manual_irrigation(call.data["objectif_mm"])


async def _handle_start_auto_irrigation(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    await coordinator.async_start_auto_irrigation(
        call.data.get("objectif_mm"),
        call.data.get("plan_arrosage_entity"),
        source=str(call.data.get("source") or "auto_irrigation"),
    )


async def _handle_start_application_irrigation(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    await coordinator.async_start_application_irrigation()


async def _handle_declare_intervention(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    try:
        await coordinator.async_declare_intervention(
            intervention=call.data["intervention"],
            date_action=parse_optional_date(call.data.get("date_action")),
            produit_id=call.data.get("produit_id"),
            produit=call.data.get("produit"),
            zone=call.data.get("zone"),
            note=call.data.get("note"),
        )
    except (HomeAssistantError, ValueError) as err:
        _LOGGER.debug("Echec declare_intervention pour %s: %s", call.data.get("intervention"), err)
        raise HomeAssistantError(str(err) or "La date doit être au format JJ/MM/AAAA.") from err


async def _handle_remove_last_application(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    try:
        await coordinator.async_remove_last_application()
    except (HomeAssistantError, ValueError) as err:
        _LOGGER.debug("Echec remove_last_application: %s", err)
        raise HomeAssistantError(f"Echec remove_last_application: {err}") from err


async def _handle_declare_mowing(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    try:
        await coordinator.async_record_mowing(parse_optional_date(call.data.get("date_action")))
    except ValueError as err:
        raise HomeAssistantError(_ERR_INVALID_DATE) from err


async def _handle_declare_watering(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    try:
        await coordinator.async_record_watering(
            parse_optional_date(call.data.get("date_action")),
            call.data.get("objectif_mm"),
        )
    except ValueError as err:
        raise HomeAssistantError(_ERR_INVALID_DATE) from err


async def _handle_register_product(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    phase_compatible: Any = call.data.get("phase_compatible")
    if isinstance(phase_compatible, list):
        phase_compatible = [str(item) for item in phase_compatible if str(item).strip()]
    try:
        await coordinator.async_register_product(
            call.data["product_id"],
            call.data["nom"],
            call.data["type"],
            call.data.get("dose_conseillee"),
            call.data.get("usage_mode"),
            call.data.get("max_applications_per_year"),
            call.data.get("reapplication_after_days"),
            call.data.get("delai_avant_tonte_jours"),
            phase_compatible,
            call.data.get("application_months"),
            call.data.get("application_type"),
            call.data.get("application_requires_watering_after"),
            call.data.get("application_post_watering_mm"),
            call.data.get("application_irrigation_block_hours"),
            call.data.get("application_irrigation_delay_minutes"),
            call.data.get("application_irrigation_mode"),
            call.data.get("application_label_notes"),
            call.data.get("note"),
            call.data.get("temperature_min"),
            call.data.get("temperature_max"),
        )
    except (HomeAssistantError, ValueError) as err:
        _LOGGER.debug("Echec register_product pour %s: %s", call.data.get("product_id"), err)
        raise HomeAssistantError(f"Echec register_product: {err}") from err


async def _handle_remove_product(call: ServiceCall) -> None:
    _require_explicit_target_for_multi_instance(call)
    coordinator = await _coordinator_from_call(call)
    try:
        await coordinator.async_remove_product(call.data["product_id"])
    except (HomeAssistantError, ValueError) as err:
        _LOGGER.debug("Echec remove_product pour %s: %s", call.data.get("product_id"), err)
        raise HomeAssistantError(f"Echec remove_product: {err}") from err
