from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    INTERVENTIONS_ACTIONS,
    MODES_GAZON,
)
from .entity_migration import (
    CURRENT_CONFIG_ENTRY_VERSION,
    async_cleanup_obsolete_entities,
)
from .coordinator import GazonIntelligentCoordinator
from .date_utils import parse_optional_date

PLATFORMS = ["select", "number", "sensor", "binary_sensor", "button"]

SERVICE_SET_MODE = "set_mode"
SERVICE_SET_DATE_ACTION = "set_date_action"
SERVICE_RESET_MODE = "reset_mode"
SERVICE_START_MANUAL_IRRIGATION = "start_manual_irrigation"
SERVICE_START_AUTO_IRRIGATION = "start_auto_irrigation"
SERVICE_DECLARE_INTERVENTION = "declare_intervention"
SERVICE_DECLARE_MOWING = "declare_mowing"
SERVICE_DECLARE_WATERING = "declare_watering"
SERVICE_REGISTER_PRODUCT = "register_product"
SERVICE_REMOVE_PRODUCT = "remove_product"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = GazonIntelligentCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await async_cleanup_obsolete_entities(hass, entry.entry_id)
    await coordinator.async_start_zone_monitoring()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.schedule_post_start_refresh(delay_seconds=30)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_MODE,
            _handle_set_mode,
            schema=vol.Schema(
                {
                    vol.Required("mode"): vol.In(MODES_GAZON)
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_DATE_ACTION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_DATE_ACTION,
            _handle_set_date_action,
            schema=vol.Schema({vol.Optional("date_action"): str}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RESET_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_MODE,
            _handle_reset_mode,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_START_MANUAL_IRRIGATION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_MANUAL_IRRIGATION,
            _handle_start_manual_irrigation,
            schema=vol.Schema(
                {
                    vol.Required("objectif_mm"): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0, max=30),
                    )
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_START_AUTO_IRRIGATION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_AUTO_IRRIGATION,
            _handle_start_auto_irrigation,
            schema=vol.Schema(
                {
                    vol.Optional("objectif_mm"): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0, max=30),
                    )
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_DECLARE_INTERVENTION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_DECLARE_INTERVENTION,
            _handle_declare_intervention,
            schema=vol.Schema(
                {
                    vol.Required("intervention"): vol.In(INTERVENTIONS_ACTIONS),
                    vol.Optional("date_action"): str,
                    vol.Optional("produit_id"): vol.Coerce(str),
                    vol.Optional("produit"): vol.Coerce(str),
                    vol.Optional("dose"): vol.Coerce(str),
                    vol.Optional("zone"): vol.Coerce(str),
                    vol.Optional("reapplication_after_days"): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=0, max=365),
                    ),
                    vol.Optional("note"): vol.Coerce(str),
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_REGISTER_PRODUCT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REGISTER_PRODUCT,
            _handle_register_product,
            schema=vol.Schema(
                {
                    vol.Required("product_id"): vol.Coerce(str),
                    vol.Required("nom"): vol.Coerce(str),
                    vol.Required("type"): vol.Coerce(str),
                    vol.Optional("dose_conseillee"): vol.Coerce(str),
                    vol.Optional("reapplication_after_days"): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=0, max=3650),
                    ),
                    vol.Optional("delai_avant_tonte_jours"): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=0, max=3650),
                    ),
                    vol.Optional("phase_compatible"): vol.Coerce(str),
                    vol.Optional("note"): vol.Coerce(str),
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_REMOVE_PRODUCT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REMOVE_PRODUCT,
            _handle_remove_product,
            schema=vol.Schema({vol.Required("product_id"): vol.Coerce(str)}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_DECLARE_MOWING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_DECLARE_MOWING,
            _handle_declare_mowing,
            schema=vol.Schema({vol.Optional("date_action"): str}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_DECLARE_WATERING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_DECLARE_WATERING,
            _handle_declare_watering,
            schema=vol.Schema(
                {
                    vol.Optional("date_action"): str,
                    vol.Optional("objectif_mm"): vol.All(
                        vol.Coerce(float),
                        vol.Range(min=0, max=30),
                    ),
                }
            ),
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id)

    if not hass.data[DOMAIN]:
        for service in (
            SERVICE_SET_MODE,
            SERVICE_SET_DATE_ACTION,
            SERVICE_RESET_MODE,
            SERVICE_START_MANUAL_IRRIGATION,
            SERVICE_START_AUTO_IRRIGATION,
            SERVICE_DECLARE_INTERVENTION,
            SERVICE_DECLARE_MOWING,
            SERVICE_DECLARE_WATERING,
            SERVICE_REGISTER_PRODUCT,
            SERVICE_REMOVE_PRODUCT,
        ):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migre les anciennes versions et nettoie les entités obsolètes."""
    if entry.version > CURRENT_CONFIG_ENTRY_VERSION:
        return False

    await async_cleanup_obsolete_entities(hass, entry.entry_id)

    if entry.version < CURRENT_CONFIG_ENTRY_VERSION:
        hass.config_entries.async_update_entry(entry, version=CURRENT_CONFIG_ENTRY_VERSION)

    return True


def _get_first_coordinator(hass: HomeAssistant) -> GazonIntelligentCoordinator:
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError("Aucune instance de Gazon Intelligent n'est configurée.")
    return next(iter(coordinators.values()))


async def _handle_set_mode(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    mode = call.data["mode"]
    if mode == "Normal":
        await coordinator.async_set_normal()
    else:
        await coordinator.async_declare_intervention(mode)


async def _handle_set_date_action(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)

    try:
        date_str = call.data.get("date_action")
        if date_str:
            date_action = parse_optional_date(date_str)
            if date_action is None:
                raise ValueError("La date doit être au format JJ/MM/AAAA.")
        else:
            date_action = None  # aujourd'hui par défaut
        await coordinator.async_set_date_action(date_action)
    except ValueError as err:
        raise HomeAssistantError("La date doit être au format JJ/MM/AAAA.") from err
    except Exception as err:  # pragma: no cover
        raise HomeAssistantError(f"Echec set_date_action: {err}") from err


async def _handle_reset_mode(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    await coordinator.async_set_normal()


async def _handle_start_manual_irrigation(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    await coordinator.async_start_manual_irrigation(call.data["objectif_mm"])


async def _handle_start_auto_irrigation(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    await coordinator.async_start_auto_irrigation(call.data.get("objectif_mm"))


async def _handle_declare_intervention(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    try:
        await coordinator.async_declare_intervention(
            call.data["intervention"],
            parse_optional_date(call.data.get("date_action")),
            call.data.get("produit_id"),
            call.data.get("produit"),
            call.data.get("dose"),
            call.data.get("zone"),
            call.data.get("reapplication_after_days"),
            call.data.get("note"),
        )
    except ValueError as err:
        raise HomeAssistantError(str(err) or "La date doit être au format JJ/MM/AAAA.") from err
    except Exception as err:  # pragma: no cover
        raise HomeAssistantError(f"Echec declare_intervention: {err}") from err


async def _handle_declare_mowing(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    try:
        await coordinator.async_record_mowing(parse_optional_date(call.data.get("date_action")))
    except ValueError as err:
        raise HomeAssistantError("La date doit être au format JJ/MM/AAAA.") from err


async def _handle_declare_watering(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    try:
        await coordinator.async_record_watering(
            parse_optional_date(call.data.get("date_action")),
            call.data.get("objectif_mm"),
        )
    except ValueError as err:
        raise HomeAssistantError("La date doit être au format JJ/MM/AAAA.") from err


async def _handle_register_product(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    try:
        await coordinator.async_register_product(
            call.data["product_id"],
            call.data["nom"],
            call.data["type"],
            call.data.get("dose_conseillee"),
            call.data.get("reapplication_after_days"),
            call.data.get("delai_avant_tonte_jours"),
            call.data.get("phase_compatible"),
            call.data.get("note"),
        )
    except Exception as err:  # pragma: no cover
        raise HomeAssistantError(f"Echec register_product: {err}") from err


async def _handle_remove_product(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    try:
        await coordinator.async_remove_product(call.data["product_id"])
    except Exception as err:  # pragma: no cover
        raise HomeAssistantError(f"Echec remove_product: {err}") from err
