from homeassistant.components.select import SelectEntity

from .const import DOMAIN, DEFAULT_MODE, MODES_GAZON
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GazonModeSelect(coordinator)])


class GazonModeSelect(GazonEntityBase, SelectEntity):
    _attr_name = "Mode expert"
    _attr_options = MODES_GAZON
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_mode"

    @property
    def current_option(self):
        return self.coordinator.data.get("mode", DEFAULT_MODE)

    async def async_select_option(self, option: str):
        await self.coordinator.async_set_mode(option)

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "phase_active",
            "phase_dominante",
            "phase_dominante_source",
            "sous_phase",
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
            "prochaine_reevaluation",
        )
