from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonAutoIrrigationSwitch(coordinator),
            GazonMowerCoordinationSwitch(coordinator),
        ]
    )


class GazonAutoIrrigationSwitch(GazonEntityBase, SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:sprinkler"
    _attr_translation_key = "auto_irrigation_enabled"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("switch", "arrosage_automatique")

    @property
    def is_on(self):
        return bool(self.coordinator.auto_irrigation_enabled)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_auto_irrigation_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_auto_irrigation_enabled(False)


class GazonMowerCoordinationSwitch(GazonEntityBase, SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:robot-mower"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Coordination tondeuse"
        self._set_entity_identity("switch", "coordination_tondeuse")

    @property
    def is_on(self):
        return bool(self.coordinator.mower_coordination_enabled)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_mower_coordination_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_mower_coordination_enabled(False)
