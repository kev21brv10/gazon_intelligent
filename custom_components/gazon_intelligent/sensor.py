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
    _attr_icon = "mdi:grass"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_phase_active"

    @property
    def native_value(self):
        return self._decision_value("phase_active")

    @property
    def extra_state_attributes(self):
        attrs = {}
        result_attrs = self._attrs_from_result("phase_dominante_source")
        if result_attrs:
            attrs.update(result_attrs)
        possible_values = self._possible_values_attr("phase_dominante")
        if possible_values:
            attrs.update(possible_values)
        result = self.decision_result
        if result is not None:
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict):
                configuration = extra.get("configuration")
                if isinstance(configuration, dict) and configuration:
                    attrs["configuration"] = configuration
                pluie_demain_source = extra.get("pluie_demain_source")
                if pluie_demain_source is not None:
                    if pluie_demain_source == "indisponible":
                        pluie_demain_source = "non disponible"
                    attrs["pluie_demain_source"] = pluie_demain_source
        if attrs:
            return attrs
        return self.coordinator.get_used_entities_attributes()


class GazonSousPhaseSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Sous-phase"
    _attr_has_entity_name = True
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_sous_phase"

    @property
    def native_value(self):
        return self._decision_value("sous_phase")

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "phase_dominante",
            "phase_dominante_source",
            "sous_phase_detail",
            "sous_phase_age_days",
            "sous_phase_progression",
        ) or {}
        possible_values = self._possible_values_attr("sous_phase")
        if possible_values:
            attrs.update(possible_values)
        return attrs or None


class GazonObjectifMmSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Objectif d'arrosage"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True
    _attr_icon = "mdi:water"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_objectif_mm"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self._decision_value("objectif_mm")

    @property
    def extra_state_attributes(self):
        return self._attrs_from_result("phase_active", "phase_dominante", "sous_phase")


class GazonTypeArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Type d'arrosage"
    _attr_has_entity_name = True
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_type_arrosage"

    @property
    def native_value(self):
        result = self.decision_result
        if result is not None:
            return result.display_label_for("type_arrosage")
        return self._decision_value("type_arrosage")

    @property
    def extra_state_attributes(self):
        result = self.decision_result
        if result is None:
            return self._possible_values_attr("type_arrosage")
        possible_values = result.possible_display_values_for("type_arrosage")
        if not possible_values:
            return None
        return {"possible_values": list(possible_values)}


class GazonTonteEtatSensor(GazonEntityBase, SensorEntity):
    _attr_name = "État de tonte"
    _attr_has_entity_name = True
    _attr_icon = "mdi:content-cut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_tonte_etat"

    @property
    def native_value(self):
        return self._decision_value("tonte_statut")

    @property
    def extra_state_attributes(self):
        attrs = {}
        result = self.decision_result
        if result is not None:
            for key in (
                "hauteur_tonte_recommandee_cm",
                "hauteur_tonte_min_cm",
                "hauteur_tonte_max_cm",
            ):
                value = getattr(result, key, None)
                if value is not None:
                    attrs[key] = value
        if not attrs:
            attrs = self._attrs_from_data(
                "hauteur_tonte_recommandee_cm",
                "hauteur_tonte_min_cm",
                "hauteur_tonte_max_cm",
            ) or {}
        possible_values = self._possible_values_attr("tonte_statut")
        if possible_values:
            attrs.update(possible_values)
        return attrs or None


class GazonConseilPrincipalSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Conseil principal"
    _attr_has_entity_name = True
    _attr_icon = "mdi:message-text-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_conseil_principal"

    @property
    def native_value(self):
        return self._decision_value("conseil_principal")


class GazonActionRecommandeeSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Action recommandée"
    _attr_has_entity_name = True
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_recommandee"

    @property
    def native_value(self):
        return self._decision_value("action_recommandee")


class GazonActionAEviterSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Action à éviter"
    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_a_eviter"

    @property
    def native_value(self):
        return self._decision_value("action_a_eviter")


class GazonNiveauActionSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Niveau d'action"
    _attr_has_entity_name = True
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_niveau_action"

    @property
    def native_value(self):
        return self._decision_value("niveau_action")

    @property
    def extra_state_attributes(self):
        return self._possible_values_attr("niveau_action")


class GazonFenetreOptimaleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Fenêtre optimale"
    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fenetre_optimale"

    @property
    def native_value(self):
        return self._decision_value("fenetre_optimale")


class GazonRisqueGazonSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Risque gazon"
    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_risque_gazon"

    @property
    def native_value(self):
        return self._decision_value("risque_gazon")
