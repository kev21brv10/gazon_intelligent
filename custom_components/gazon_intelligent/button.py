from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RetourModeNormalButton(coordinator),
            DateActionAujourdhuiButton(coordinator),
            JAiSursemeButton(coordinator),
            JAiFertiliseButton(coordinator),
            JAiTraiteButton(coordinator),
            JAiScarifieButton(coordinator),
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


class _InterventionButton(GazonEntityBase, ButtonEntity):
    _intervention_name: str = ""
    _attr_name = ""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self._intervention_name.lower().replace(' ', '_')}"

    async def async_press(self):
        await self.coordinator.async_declare_intervention(self._intervention_name)


class JAiSursemeButton(_InterventionButton):
    _intervention_name = "Sursemis"
    _attr_name = "Déclarer un sursemis"
    _attr_has_entity_name = True


class JAiFertiliseButton(_InterventionButton):
    _intervention_name = "Fertilisation"
    _attr_name = "Déclarer une fertilisation"
    _attr_has_entity_name = True


class JAiTraiteButton(_InterventionButton):
    _intervention_name = "Traitement"
    _attr_name = "Déclarer un traitement"
    _attr_has_entity_name = True


class JAiScarifieButton(_InterventionButton):
    _intervention_name = "Scarification"
    _attr_name = "Déclarer une scarification"
    _attr_has_entity_name = True
