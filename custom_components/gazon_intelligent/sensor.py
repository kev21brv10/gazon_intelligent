from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import EntityCategory

from .entity_base import GazonEntityBase
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonPhaseActiveSensor(coordinator),
            GazonTonteEtatSensor(coordinator),
            GazonRaisonDecisionSensor(coordinator),
            GazonConseilPrincipalSensor(coordinator),
            GazonActionRecommandeeSensor(coordinator),
            GazonActionAEviterSensor(coordinator),
            GazonNiveauActionSensor(coordinator),
            GazonFenetreOptimaleSensor(coordinator),
            GazonRisqueGazonSensor(coordinator),
            GazonProchaineReevaluationSensor(coordinator),
            GazonSousPhaseSensor(coordinator),
            GazonObjectifMmSensor(coordinator),
            GazonJoursRestantsSensor(coordinator),
            GazonDateActionSensor(coordinator),
            GazonDateFinSensor(coordinator),
            GazonArrosageConseilleSensor(coordinator),
            GazonTypeArrosageSensor(coordinator),
            GazonBilanHydriqueSensor(coordinator),
            GazonEtpSensor(coordinator),
            GazonHumiditeSensor(coordinator),
            GazonPluie24hSensor(coordinator),
            GazonPluieDemainSensor(coordinator),
            GazonTemperatureSensor(coordinator),
            GazonScoreHydriqueSensor(coordinator),
            GazonScoreStressSensor(coordinator),
            GazonScoreTonteSensor(coordinator),
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
    _attr_name = "Stade actuel"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_sous_phase"

    @property
    def native_value(self):
        return self.coordinator.data.get("sous_phase")

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
        return self._attrs_from_data(
            "phase_active",
            "phase_dominante",
            "sous_phase",
            "type_arrosage",
            "score_hydrique",
            "score_stress",
        )


class GazonBilanHydriqueSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Manque d'eau estimé"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_bilan_hydrique"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data.get("bilan_hydrique_mm")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "etp",
            "pluie_24h",
            "pluie_demain",
            "pluie_efficace",
            "arrosage_recent",
            "arrosage_recent_jour",
            "arrosage_recent_3j",
            "arrosage_recent_7j",
            "deficit_jour",
            "deficit_3j",
            "deficit_7j",
            "type_sol",
        )


class GazonJoursRestantsSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Jours restants de la phase"
    _attr_native_unit_of_measurement = "j"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_jours_restants"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data.get("jours_restants")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "phase_dominante", "sous_phase", "date_fin")


class GazonEtpSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Besoin en eau du jour (ETP)"
    _attr_native_unit_of_measurement = "mm/j"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

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


class GazonHumiditeSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Humidité extérieure"
    _attr_native_unit_of_measurement = "%"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_humidite"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.coordinator.data.get("humidite")


class GazonDateActionSensor(GazonEntityBase, SensorEntity):
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


class GazonDateFinSensor(GazonEntityBase, SensorEntity):
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


class GazonPluie24hSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Pluie 24h"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_pluie_24h"

    @property
    def native_value(self):
        return self.coordinator.data.get("pluie_24h")


class GazonPluieDemainSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Pluie prévue demain"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_pluie_demain"

    @property
    def native_value(self):
        return self.coordinator.data.get("pluie_demain")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("pluie_demain_source")


class GazonTemperatureSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Température extérieure"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_temperature"

    @property
    def native_value(self):
        return self.coordinator.data.get("temperature")


class GazonArrosageConseilleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Arrosage conseillé"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_conseille"

    @property
    def native_value(self):
        # valeurs: auto / personnalise
        return self.coordinator.data.get("arrosage_conseille")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("type_arrosage", "phase_active", "phase_dominante", "sous_phase")


class GazonTypeArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Mode d'arrosage"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_type_arrosage"

    @property
    def native_value(self):
        return self.coordinator.data.get("type_arrosage")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "objectif_mm")


class GazonScoreHydriqueSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Niveau de manque d'eau"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_score_hydrique"

    @property
    def native_value(self):
        return self.coordinator.data.get("score_hydrique")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("bilan_hydrique_mm", "objectif_mm")


class GazonScoreStressSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Niveau de stress du gazon"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_score_stress"

    @property
    def native_value(self):
        return self.coordinator.data.get("score_stress")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("temperature", "humidite", "etp")


class GazonScoreTonteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Risque de tonte"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_score_tonte"

    @property
    def native_value(self):
        return self.coordinator.data.get("score_tonte")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "phase_active",
            "phase_dominante",
            "sous_phase",
            "tonte_autorisee",
            "tonte_statut",
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
        )


class GazonTonteEtatSensor(GazonEntityBase, SensorEntity):
    _attr_name = "État de tonte"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_tonte_etat"

    @property
    def native_value(self):
        return self.coordinator.data.get("tonte_statut")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "tonte_autorisee",
            "score_tonte",
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
            "raison_decision",
        )


class GazonRaisonDecisionSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Pourquoi ce choix"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_raison_decision"

    @property
    def native_value(self):
        return self.coordinator.data.get("raison_decision")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("niveau_action", "fenetre_optimale", "risque_gazon", "prochaine_reevaluation")


class GazonConseilPrincipalSensor(GazonEntityBase, SensorEntity):
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
        return self._attrs_from_data(
            "phase_dominante",
            "sous_phase",
            "action_recommandee",
            "action_a_eviter",
            "prochaine_reevaluation",
        )


class GazonActionRecommandeeSensor(GazonEntityBase, SensorEntity):
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
        return self._attrs_from_data("objectif_mm", "type_arrosage", "phase_dominante", "sous_phase")


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

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_dominante", "sous_phase", "risque_gazon")


class GazonFenetreOptimaleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Fenêtre optimale"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fenetre_optimale"

    @property
    def native_value(self):
        return self.coordinator.data.get("fenetre_optimale")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("niveau_action", "phase_dominante", "sous_phase")


class GazonRisqueGazonSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Risque gazon"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_risque_gazon"

    @property
    def native_value(self):
        return self.coordinator.data.get("risque_gazon")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "phase_dominante",
            "sous_phase",
            "score_hydrique",
            "score_stress",
            "score_tonte",
            "prochaine_reevaluation",
        )


class GazonProchaineReevaluationSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Prochaine réévaluation"
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_prochaine_reevaluation"

    @property
    def native_value(self):
        return self.coordinator.data.get("prochaine_reevaluation")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("niveau_action", "fenetre_optimale", "risque_gazon", "raison_decision")
