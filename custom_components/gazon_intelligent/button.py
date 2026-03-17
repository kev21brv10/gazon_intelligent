from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class _GazonBaseEntity(CoordinatorEntity):
    """Base entity to share device metadata."""

    @property
    def device_info(self) -> DeviceInfo:
        entry_id = self.coordinator.entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Gazon Intelligent",
            manufacturer="Custom",
            model="Gestion gazon",
        )

    @property
    def extra_state_attributes(self):
        return self.coordinator.get_used_entities_attributes()


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RetourModeNormalButton(coordinator),
            DateActionAujourdhuiButton(coordinator),
        ]
    )


class RetourModeNormalButton(_GazonBaseEntity, ButtonEntity):
    _attr_name = "Repasser en mode normal"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_retour_mode_normal"

    async def async_press(self):
        await self.coordinator.async_set_normal()


class DateActionAujourdhuiButton(_GazonBaseEntity, ButtonEntity):
    _attr_name = "Date action = aujourd'hui"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_date_action_today"

    async def async_press(self):
        await self.coordinator.async_set_date_action()
