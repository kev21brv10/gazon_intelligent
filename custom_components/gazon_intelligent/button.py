from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RetourModeNormalButton(coordinator),
            DateActionAujourdhuiButton(coordinator),
        ]
    )


class RetourModeNormalButton(GazonEntityBase, ButtonEntity):
    _attr_name = "Retour au mode normal"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_retour_mode_normal"

    async def async_press(self):
        await self.coordinator.async_set_normal()


class DateActionAujourdhuiButton(GazonEntityBase, ButtonEntity):
    _attr_name = "Noter la date du jour"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_date_action_today"

    async def async_press(self):
        await self.coordinator.async_set_date_action()
