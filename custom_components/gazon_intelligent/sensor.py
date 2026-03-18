from homeassistant.components.sensor import SensorEntity, SensorStateClass

from .const import DOMAIN
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonTonteEtatSensor(coordinator),
            GazonConseilPrincipalSensor(coordinator),
            GazonActionRecommandeeSensor(coordinator),
            GazonActionAEviterSensor(coordinator),
            GazonNiveauActionSensor(coordinator),
            GazonFenetreOptimaleSensor(coordinator),
            GazonRisqueGazonSensor(coordinator),
            GazonPhaseActiveSensor(coordinator),
            GazonSousPhaseSensor(coordinator),
            GazonObjectifMmSensor(coordinator),
            GazonTypeArrosageSensor(coordinator),
        ]
    )


class GazonPhaseActiveSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Phase dominante"
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


class GazonSousPhaseSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Sous-phase"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_sous_phase"

    @property
    def native_value(self):
        value = self.coordinator.data.get("sous_phase")
        if value not in (None, "", "unknown", "unavailable"):
            return value

        phase = self.coordinator.data.get("phase_dominante") or self.coordinator.data.get("phase_active")
        age = self.coordinator.data.get("sous_phase_age_days")
        try:
            age_days = int(age) if age is not None else 0
        except (TypeError, ValueError):
            age_days = 0

        if phase == "Sursemis":
            if age_days <= 7:
                return "Germination"
            if age_days <= 14:
                return "Enracinement"
            return "Reprise"
        if phase == "Traitement":
            if age_days <= 1:
                return "Application"
            if age_days <= 2:
                return "Rémanence"
            return "Suivi"
        if phase == "Fertilisation":
            if age_days <= 1:
                return "Réponse"
            if age_days <= 3:
                return "Assimilation"
            return "Stabilisation"
        if phase == "Biostimulant":
            if age_days <= 1:
                return "Réponse"
            if age_days <= 2:
                return "Consolidation"
            return "Stabilisation"
        if phase == "Agent Mouillant":
            if age_days <= 1:
                return "Pénétration"
            if age_days <= 3:
                return "Répartition"
            return "Stabilisation"
        if phase == "Scarification":
            if age_days <= 2:
                return "Cicatrisation"
            if age_days <= 5:
                return "Reprise"
            return "Stabilisation"
        if phase == "Hivernage":
            return "Repos"
        return phase or "Inconnu"

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "phase_dominante",
            "phase_dominante_source",
            "sous_phase_detail",
            "sous_phase_age_days",
            "sous_phase_progression",
        )


class GazonObjectifMmSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Objectif d'arrosage"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_objectif_mm"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data.get("objectif_mm")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "phase_dominante", "sous_phase")


class GazonTypeArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Type d'arrosage"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_type_arrosage"

    @property
    def native_value(self):
        return self.coordinator.data.get("type_arrosage")


class GazonTonteEtatSensor(GazonEntityBase, SensorEntity):
    _attr_name = "État de tonte"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_tonte_etat"

    @property
    def native_value(self):
        return self.coordinator.data.get("tonte_statut")


class GazonConseilPrincipalSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Conseil principal"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_conseil_principal"

    @property
    def native_value(self):
        return self.coordinator.data.get("conseil_principal")


class GazonActionRecommandeeSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Action recommandée"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_recommandee"

    @property
    def native_value(self):
        return self.coordinator.data.get("action_recommandee")


class GazonActionAEviterSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Action à éviter"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_a_eviter"

    @property
    def native_value(self):
        return self.coordinator.data.get("action_a_eviter")


class GazonNiveauActionSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Niveau d'action"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_niveau_action"

    @property
    def native_value(self):
        return self.coordinator.data.get("niveau_action")


class GazonFenetreOptimaleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Fenêtre optimale"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fenetre_optimale"

    @property
    def native_value(self):
        return self.coordinator.data.get("fenetre_optimale")


class GazonRisqueGazonSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Risque gazon"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_risque_gazon"

    @property
    def native_value(self):
        return self.coordinator.data.get("risque_gazon")
