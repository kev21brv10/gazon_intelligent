from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DEFAULT_MODE, DOMAIN, MODES_GAZON
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonModeSelect(coordinator),
        ]
    )


class GazonModeSelect(GazonEntityBase, SelectEntity):
    _attr_name = "Mode du gazon"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_mode"

    @property
    def options(self):
        return MODES_GAZON

    @property
    def current_option(self):
        return self.coordinator.data.get("mode", DEFAULT_MODE)

    async def async_select_option(self, option: str):
        await self.coordinator.async_set_mode(option)

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "phase_dominante_source", "pluie_demain_source")
