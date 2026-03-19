from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonTonteAutoriseeBinarySensor(coordinator),
            GazonArrosageRecommandeBinarySensor(coordinator),
        ]
    )


class GazonTonteAutoriseeBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Tonte autorisée"
    _attr_has_entity_name = True
    _attr_icon = "mdi:content-cut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_tonte_autorisee"

    @property
    def is_on(self):
        return bool(self._decision_value("tonte_autorisee", False))

    @property
    def extra_state_attributes(self):
        return self._attrs_from_result("phase_active", "tonte_statut", "niveau_action", "fenetre_optimale", "risque_gazon")


class GazonArrosageRecommandeBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Arrosage recommandé"
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_recommande"

    @property
    def is_on(self):
        return bool(self._decision_value("arrosage_recommande", False))

    @property
    def extra_state_attributes(self):
        return self._attrs_from_result("objectif_mm", "type_arrosage")
