from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GazonAutoIrrigationSwitch(coordinator)])


class GazonAutoIrrigationSwitch(GazonEntityBase, SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:sprinkler"
    _attr_translation_key = "auto_irrigation_enabled"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_automatique"

    @property
    def is_on(self):
        return bool(self.coordinator.auto_irrigation_enabled)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_auto_irrigation_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_auto_irrigation_enabled(False)
