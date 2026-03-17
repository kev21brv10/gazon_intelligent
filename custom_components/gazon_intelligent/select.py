from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODES_GAZON


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GazonModeSelect(coordinator)])


class GazonModeSelect(CoordinatorEntity, SelectEntity):
    _attr_name = "Mode gazon"
    _attr_options = MODES_GAZON
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_mode"

    @property
    def current_option(self):
        return self.coordinator.data["mode"]

    async def async_select_option(self, option: str):
        await self.coordinator.async_set_mode(option)

    @property
    def extra_state_attributes(self):
        attrs = self.coordinator.get_used_entities_attributes()
        # Le sélecteur conserve le contexte système complet.
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        entry_id = self.coordinator.entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Gazon Intelligent",
            manufacturer="Custom",
            model="Mode gazon",
        )
