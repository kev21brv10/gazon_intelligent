from homeassistant.components.sensor import SensorEntity, SensorStateClass
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
            GazonObjectifMmSensor(coordinator),
            GazonJoursRestantsSensor(coordinator),
        ]
    )


class GazonObjectifMmSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Objectif d'arrosage"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_objectif_mm"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data["objectif_mm"]


class GazonJoursRestantsSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Jours restants de la phase"
    _attr_native_unit_of_measurement = "j"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_jours_restants"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data["jours_restants"]
