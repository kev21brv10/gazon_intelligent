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


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonTonteAutoriseeBinarySensor(coordinator),
            GazonArrosageAutoAutoriseBinarySensor(coordinator),
            GazonArrosageSpecialAutoriseBinarySensor(coordinator),
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


class GazonArrosageAutoAutoriseBinarySensor(_GazonBaseEntity, BinarySensorEntity):
    _attr_name = "Arrosage automatique autorisé"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_auto_autorise"

    @property
    def is_on(self):
        return self.coordinator.data["arrosage_auto_autorise"]


class GazonArrosageSpecialAutoriseBinarySensor(_GazonBaseEntity, BinarySensorEntity):
    _attr_name = "Arrosage modes spéciaux"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_special_autorise"

    @property
    def is_on(self):
        return self.coordinator.data["arrosage_special_autorise"]
