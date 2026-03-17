from __future__ import annotations

from datetime import datetime

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .coordinator import GazonIntelligentCoordinator

PLATFORMS = ["select", "sensor", "binary_sensor", "button"]

SERVICE_SET_MODE = "set_mode"
SERVICE_SET_DATE_ACTION = "set_date_action"
SERVICE_RESET_MODE = "reset_mode"
SERVICE_START_MANUAL_IRRIGATION = "start_manual_irrigation"
SERVICE_START_AUTO_IRRIGATION = "start_auto_irrigation"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = GazonIntelligentCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.schedule_post_start_refresh(delay_seconds=30)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_MODE,
            _handle_set_mode,
            schema=vol.Schema(
                {
                    vol.Required("mode"): vol.In(
                        [
                            "Normal",
                            "Sursemis",
                            "Traitement",
                            "Fertilisation",
                            "Biostimulant",
                            "Agent Mouillant",
                            "Scarification",
                            "Hivernage",
                        ]
                    )
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
        ):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return unload_ok


def _get_first_coordinator(hass: HomeAssistant) -> GazonIntelligentCoordinator:
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError("Aucune instance de Gazon Intelligent n'est configurée.")
    return next(iter(coordinators.values()))


async def _handle_set_mode(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)
    await coordinator.async_set_mode(call.data["mode"])


async def _handle_set_date_action(call: ServiceCall) -> None:
    hass = call.hass
    coordinator = _get_first_coordinator(hass)

    try:
        date_str = call.data.get("date_action")
        if date_str:
            date_action = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            date_action = None  # aujourd'hui par défaut
        await coordinator.async_set_date_action(date_action)
    except ValueError as err:
        raise HomeAssistantError("La date doit être au format AAAA-MM-JJ.") from err
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
