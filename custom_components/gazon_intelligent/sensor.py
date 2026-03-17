from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.const import UnitOfTemperature
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
            GazonEtpSensor(coordinator),
            GazonHumiditeSensor(coordinator),
            GazonDateActionSensor(coordinator),
            GazonDateFinSensor(coordinator),
            GazonPluie24hSensor(coordinator),
            GazonPluieDemainSensor(coordinator),
            GazonTemperatureSensor(coordinator),
            GazonArrosageConseilleSensor(coordinator),
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


class GazonEtpSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "ETP estimée"
    _attr_native_unit_of_measurement = "mm/j"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_etp"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data.get("etp")


class GazonHumiditeSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Humidité extérieure"
    _attr_native_unit_of_measurement = "%"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_humidite"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data.get("humidite")


class GazonDateActionSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Date de l'action"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_date_action"

    @property
    def native_value(self):
        return self.coordinator.data.get("date_action")


class GazonDateFinSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Date de fin de phase"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_date_fin"

    @property
    def native_value(self):
        return self.coordinator.data.get("date_fin")


class GazonPluie24hSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Pluie 24h"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_pluie_24h"

    @property
    def native_value(self):
        return self.coordinator.data.get("pluie_24h")


class GazonPluieDemainSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Pluie prévue demain"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_pluie_demain"

    @property
    def native_value(self):
        return self.coordinator.data.get("pluie_demain")


class GazonTemperatureSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Température extérieure"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_temperature"

    @property
    def native_value(self):
        return self.coordinator.data.get("temperature")


class GazonArrosageConseilleSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Arrosage (auto/personnalisé)"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_conseille"

    @property
    def native_value(self):
        # valeurs: auto / personnalise / interdit
        return self.coordinator.data.get("arrosage_conseille")
