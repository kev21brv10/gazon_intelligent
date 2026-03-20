from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass

from .const import DOMAIN
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonTonteEtatSensor(coordinator),
            GazonHauteurTonteSensor(coordinator),
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
            GazonPlanArrosageSensor(coordinator),
            GazonDernierArrosageDetecteSensor(coordinator),
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


class GazonHauteurTonteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Hauteur de tonte conseillée"
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "cm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:content-cut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_hauteur_tonte"

    @property
    def native_value(self):
        return self._decision_value("hauteur_tonte_recommandee_cm")

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
            "tonte_statut",
            "phase_active",
        )
        return attrs or None


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
        return self._attrs_from_result(
            "phase_active",
            "phase_dominante",
            "sous_phase",
            "bilan_hydrique_mm",
            "deficit_3j",
            "deficit_7j",
            "pluie_demain",
            "temperature",
            "etp",
        )


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


class GazonDernierArrosageDetecteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Dernier arrosage détecté"
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_dernier_arrosage_detecte"

    def _latest_zone_session(self) -> dict[str, object] | None:
        history = getattr(self.coordinator, "history", None)
        if not isinstance(history, list):
            return None
        for item in reversed(history):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "arrosage" and item.get("source") == "zone_session":
                return item
        return None

    @property
    def native_value(self):
        session = self._latest_zone_session()
        if not session:
            return 0.0
        for key in ("total_mm", "session_total_mm", "objectif_mm"):
            value = session.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @property
    def extra_state_attributes(self):
        session = self._latest_zone_session()
        if not session:
            return {
                "source": "none",
                "zone_count": 0,
                "objectif_mm": 0.0,
                "total_mm": 0.0,
            }

        zones = session.get("zones")
        zone_details: list[dict[str, object]] = []
        zones_used: list[str] = []
        if isinstance(zones, list):
            for zone in zones:
                if not isinstance(zone, dict):
                    continue
                zone_id = zone.get("entity_id") or zone.get("zone")
                if zone_id is not None:
                    zones_used.append(str(zone_id))
                zone_detail = {
                    key: zone.get(key)
                    for key in (
                        "order",
                        "zone",
                        "entity_id",
                        "rate_mm_h",
                        "duration_min",
                        "duration_seconds",
                        "mm",
                    )
                    if zone.get(key) is not None
                }
                if zone_detail:
                    zone_details.append(zone_detail)

        attrs: dict[str, object] = {
            "date_action": session.get("date"),
            "source": session.get("source"),
            "detected_at": session.get("detected_at") or session.get("date"),
            "zone_count": session.get("zone_count") if session.get("zone_count") is not None else len(zone_details),
            "zones_used": zones_used,
            "zones": zone_details,
        }
        for key in ("objectif_mm", "total_mm", "session_total_mm"):
            if session.get(key) is not None:
                attrs[key] = session.get(key)
        clean = {key: value for key, value in attrs.items() if value not in (None, "", [], {})}
        return clean or None


class GazonPlanArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Plan d'arrosage"
    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_plan_arrosage"

    def _latest_objective(self) -> float | None:
        result = self.decision_result
        if result is not None:
            value = getattr(result, "objectif_arrosage", None)
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                pass
        data = getattr(self.coordinator, "data", None)
        if isinstance(data, dict):
            value = data.get("objectif_mm")
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                return None
        return None

    def _watering_passages(self) -> int:
        result = self.decision_result
        if result is not None:
            value = getattr(result, "watering_passages", None)
            try:
                if value is not None:
                    return max(1, int(value))
            except (TypeError, ValueError):
                pass
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict):
                value = extra.get("watering_passages")
                try:
                    if value is not None:
                        return max(1, int(value))
                except (TypeError, ValueError):
                    pass
        data = getattr(self.coordinator, "data", None)
        if isinstance(data, dict):
            value = data.get("watering_passages")
            try:
                if value is not None:
                    return max(1, int(value))
            except (TypeError, ValueError):
                pass
        return 1

    def _watering_pause_minutes(self) -> int:
        result = self.decision_result
        if result is not None:
            value = getattr(result, "watering_pause_minutes", None)
            try:
                if value is not None:
                    return max(0, int(value))
            except (TypeError, ValueError):
                pass
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict):
                value = extra.get("watering_pause_minutes")
                try:
                    if value is not None:
                        return max(0, int(value))
                except (TypeError, ValueError):
                    pass
        data = getattr(self.coordinator, "data", None)
        if isinstance(data, dict):
            value = data.get("watering_pause_minutes")
            try:
                if value is not None:
                    return max(0, int(value))
            except (TypeError, ValueError):
                pass
        return 0

    def _build_plan(self) -> dict[str, object] | None:
        objective = self._latest_objective()
        def _empty_plan(reason: str) -> dict[str, object]:
            return {
                "objective_mm": round(max(0.0, objective or 0.0), 1),
                "zones": [],
                "zone_count": 0,
                "total_duration_min": 0.0,
                "min_duration_min": 0.0,
                "max_duration_min": 0.0,
                "fractionation": False,
                "passages": self._watering_passages(),
                "pause_between_passages_minutes": self._watering_pause_minutes(),
                "source": "no_plan",
                "reason": reason,
            }

        if objective is None or objective <= 0:
            return _empty_plan("objective_non_positive")

        def _conf(key: str):
            getter = getattr(self.coordinator, "_get_conf", None)
            if callable(getter):
                return getter(key)
            entry = getattr(self.coordinator, "entry", None)
            if entry is not None:
                options = getattr(entry, "options", None)
                if isinstance(options, dict) and key in options:
                    return options.get(key)
                data = getattr(entry, "data", None)
                if isinstance(data, dict) and key in data:
                    return data.get(key)
            data = getattr(self.coordinator, "data", None)
            if isinstance(data, dict):
                return data.get(key)
            return None

        zones: list[dict[str, object]] = []
        max_minutes = 0.0
        min_minutes = 99999.0
        for idx in range(1, 6):
            entity_id = _conf(f"zone_{idx}")
            raw_rate = _conf(f"debit_zone_{idx}")
            if not entity_id:
                continue
            try:
                rate_mm_h = float(raw_rate)
            except (TypeError, ValueError):
                continue
            if rate_mm_h <= 0:
                continue
            duration_min = (objective / rate_mm_h) * 60.0
            if duration_min <= 0:
                continue
            rounded_duration = max(0.5, round(duration_min * 2.0) / 2.0)
            rounded_duration = min(rounded_duration, 180.0)
            max_minutes = max(max_minutes, rounded_duration)
            min_minutes = min(min_minutes, rounded_duration)
            zones.append(
                {
                    "zone": entity_id,
                    "rate_mm_h": round(rate_mm_h, 1),
                    "objectif_mm": round(objective, 1),
                    "duration_min": round(rounded_duration, 1),
                    "duration_seconds": int(round(rounded_duration * 60.0)),
                }
            )

        if not zones:
            return _empty_plan("no_valid_zones")

        total_duration_min = round(sum(float(zone["duration_min"]) for zone in zones), 1)
        if total_duration_min <= 0:
            return _empty_plan("non_positive_total_duration")

        return {
            "objective_mm": round(objective, 1),
            "zones": zones,
            "zone_count": len(zones),
            "total_duration_min": total_duration_min,
            "min_duration_min": round(min_minutes, 1),
            "max_duration_min": round(max_minutes, 1),
            "fractionation": len(zones) > 1,
            "passages": self._watering_passages(),
            "pause_between_passages_minutes": self._watering_pause_minutes(),
            "source": "calculated_from_objective",
        }

    @property
    def native_value(self):
        plan = self._build_plan()
        if plan is None:
            return None
        return plan["total_duration_min"]

    @property
    def extra_state_attributes(self):
        plan = self._build_plan()
        if plan is None:
            return None
        return plan


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
