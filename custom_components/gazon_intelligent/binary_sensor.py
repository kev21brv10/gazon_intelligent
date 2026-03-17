from homeassistant.components.binary_sensor import BinarySensorEntity
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

    def _attrs_from_data(self, *keys: str):
        attrs = {key: self.coordinator.data.get(key) for key in keys}
        clean = {k: v for k, v in attrs.items() if v is not None}
        return clean or None


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonTonteAutoriseeBinarySensor(coordinator),
            GazonArrosageAutoAutoriseBinarySensor(coordinator),
            GazonArrosageRecommandeBinarySensor(coordinator),
        ]
    )


class GazonTonteAutoriseeBinarySensor(_GazonBaseEntity, BinarySensorEntity):
    _attr_name = "Tonte autorisée"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_tonte_autorisee"

    @property
    def is_on(self):
        return self.coordinator.data["tonte_autorisee"]

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "score_tonte", "raison_decision")


class GazonArrosageAutoAutoriseBinarySensor(_GazonBaseEntity, BinarySensorEntity):
    _attr_name = "Arrosage auto autorisé"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_auto_autorise"

    @property
    def is_on(self):
        return self.coordinator.data.get("arrosage_auto_autorise", False)

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "type_arrosage", "objectif_mm")


class GazonArrosageRecommandeBinarySensor(_GazonBaseEntity, BinarySensorEntity):
    _attr_name = "Arrosage recommandé"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_recommande"

    @property
    def is_on(self):
        return self.coordinator.data.get("arrosage_recommande", False)

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("objectif_mm", "score_hydrique", "conseil_principal", "urgence")
