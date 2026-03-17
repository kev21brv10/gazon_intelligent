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

    def _attrs_from_data(self, *keys: str):
        attrs = {key: self.coordinator.data.get(key) for key in keys}
        clean = {k: v for k, v in attrs.items() if v is not None}
        return clean or None


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonPhaseActiveSensor(coordinator),
            GazonObjectifMmSensor(coordinator),
            GazonBilanHydriqueSensor(coordinator),
            GazonJoursRestantsSensor(coordinator),
            GazonEtpSensor(coordinator),
            GazonHumiditeSensor(coordinator),
            GazonDateActionSensor(coordinator),
            GazonDateFinSensor(coordinator),
            GazonPluie24hSensor(coordinator),
            GazonPluieDemainSensor(coordinator),
            GazonTemperatureSensor(coordinator),
            GazonArrosageConseilleSensor(coordinator),
            GazonTypeArrosageSensor(coordinator),
            GazonScoreHydriqueSensor(coordinator),
            GazonScoreStressSensor(coordinator),
            GazonScoreTonteSensor(coordinator),
            GazonRaisonDecisionSensor(coordinator),
            GazonConseilPrincipalSensor(coordinator),
            GazonActionRecommandeeSensor(coordinator),
            GazonActionAEviterSensor(coordinator),
            GazonUrgenceSensor(coordinator),
        ]
    )


class GazonPhaseActiveSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Phase active"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_phase_active"

    @property
    def native_value(self):
        return self.coordinator.data.get("phase_active")

    @property
    def extra_state_attributes(self):
        return self.coordinator.get_used_entities_attributes()


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

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "type_arrosage", "score_hydrique", "score_stress")


class GazonBilanHydriqueSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Bilan hydrique (déficit)"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_bilan_hydrique"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data.get("bilan_hydrique_mm")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("etp", "pluie_24h", "pluie_demain", "type_sol")


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

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "date_fin")


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

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("temperature", "pluie_24h")


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

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active")


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

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "jours_restants")


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

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("pluie_demain_source")


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
        # valeurs: auto / personnalise
        return self.coordinator.data.get("arrosage_conseille")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("type_arrosage", "phase_active")


class GazonTypeArrosageSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Type d'arrosage"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_type_arrosage"

    @property
    def native_value(self):
        return self.coordinator.data.get("type_arrosage")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "objectif_mm")


class GazonScoreHydriqueSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Score hydrique"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_score_hydrique"

    @property
    def native_value(self):
        return self.coordinator.data.get("score_hydrique")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("bilan_hydrique_mm", "objectif_mm")


class GazonScoreStressSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Score stress gazon"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_score_stress"

    @property
    def native_value(self):
        return self.coordinator.data.get("score_stress")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("temperature", "humidite", "etp")


class GazonScoreTonteSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Score tonte"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_score_tonte"

    @property
    def native_value(self):
        return self.coordinator.data.get("score_tonte")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "tonte_autorisee")


class GazonRaisonDecisionSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Raison décision"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_raison_decision"

    @property
    def native_value(self):
        return self.coordinator.data.get("raison_decision")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("urgence")


class GazonConseilPrincipalSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Conseil principal"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_conseil_principal"

    @property
    def native_value(self):
        return self.coordinator.data.get("conseil_principal")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("action_recommandee", "action_a_eviter")


class GazonActionRecommandeeSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Action recommandée"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_recommandee"

    @property
    def native_value(self):
        return self.coordinator.data.get("action_recommandee")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("objectif_mm", "type_arrosage")


class GazonActionAEviterSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Action à éviter"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_a_eviter"

    @property
    def native_value(self):
        return self.coordinator.data.get("action_a_eviter")


class GazonUrgenceSensor(_GazonBaseEntity, SensorEntity):
    _attr_name = "Urgence"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_urgence"

    @property
    def native_value(self):
        return self.coordinator.data.get("urgence")
