from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN
from .entity_base import GazonEntityBase
from .memory import compute_application_state, normalize_post_application_status


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonTonteAutoriseeBinarySensor(coordinator),
            GazonArrosageRecommandeBinarySensor(coordinator),
            GazonApplicationArrosageAutoriseBinarySensor(coordinator),
            GazonSignalIrrigationBinarySensor(coordinator),
            GazonSignalInterventionBinarySensor(coordinator),
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
        return self._attrs_from_result(
            "phase_active",
            "tonte_statut",
            "risque_gazon",
            "hauteur_tonte_recommandee_cm",
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
            "next_mowing_date",
            "next_mowing_display",
            "raison_blocage_tonte",
            "raison_blocage_code",
        )


class GazonArrosageRecommandeBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Irrigation"
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


class GazonApplicationArrosageAutoriseBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Irrigation post-application"
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_apres_application_autorise"

    @staticmethod
    def _empty_application_state() -> dict[str, object]:
        return {
            "derniere_application": None,
            "application_type": None,
            "application_requires_watering_after": False,
            "application_post_watering_mm": 0.0,
            "application_irrigation_block_hours": 0.0,
            "application_irrigation_delay_minutes": 0.0,
            "application_irrigation_mode": None,
            "application_label_notes": None,
            "application_post_watering_status": "indisponible",
            "declared_at": None,
            "application_block_until": None,
            "application_block_active": False,
            "application_block_remaining_minutes": 0.0,
            "application_post_watering_pending": False,
            "application_post_watering_ready_at": None,
            "application_post_watering_delay_remaining_minutes": 0.0,
            "application_post_watering_ready": False,
            "application_post_watering_remaining_mm": 0.0,
            "auto_irrigation_enabled": True,
        }

    def _application_state_keys(self) -> tuple[str, ...]:
        return (
            "derniere_application",
            "application_type",
            "application_requires_watering_after",
            "application_post_watering_mm",
            "application_irrigation_block_hours",
            "application_irrigation_delay_minutes",
            "application_irrigation_mode",
            "application_label_notes",
            "application_post_watering_status",
            "declared_at",
            "application_block_until",
            "application_block_active",
            "application_block_remaining_minutes",
            "application_post_watering_pending",
            "application_post_watering_ready_at",
            "application_post_watering_delay_remaining_minutes",
            "application_post_watering_ready",
            "application_post_watering_remaining_mm",
            "auto_irrigation_enabled",
        )

    def _state_from_memory(self, memory: dict[str, object]) -> dict[str, object]:
        state = {
            key: memory.get(key)
            for key in self._application_state_keys()
        }
        state["application_post_watering_status"] = normalize_post_application_status(
            state.get("application_post_watering_status")
        )
        summary = state.get("derniere_application")
        if isinstance(summary, dict) and summary:
            return state
        return {}

    def _application_state(self) -> dict[str, object]:
        memory = getattr(self.coordinator, "memory", None)
        if isinstance(memory, dict):
            state = self._state_from_memory(memory)
            if state:
                return state
        else:
            memory = None
        history = getattr(self.coordinator, "history", None)
        if isinstance(history, list):
            state = compute_application_state(history)
            if isinstance(memory, dict):
                state["auto_irrigation_enabled"] = memory.get(
                    "auto_irrigation_enabled",
                    state.get("auto_irrigation_enabled", True),
                )
            return state
        state = self._empty_application_state()
        if isinstance(memory, dict):
            state["auto_irrigation_enabled"] = memory.get("auto_irrigation_enabled", True)
        return state

    @property
    def is_on(self):
        state = self._application_state()
        auto_irrigation_enabled = bool(state.get("auto_irrigation_enabled", True))
        application_type = state.get("application_type")
        application_mode = str(state.get("application_irrigation_mode") or "").strip().lower()
        application_post_watering_status = normalize_post_application_status(
            state.get("application_post_watering_status")
        )
        return bool(
            application_type == "sol"
            and application_mode == "auto"
            and application_post_watering_status == "autorise"
            and auto_irrigation_enabled
        )

    @property
    def extra_state_attributes(self):
        state = self._application_state()
        attrs: dict[str, object] = {}
        for key in self._application_state_keys():
            value = state.get(key)
            if value not in (None, "", [], {}):
                attrs[key] = value
        return attrs or None


class GazonSignalIrrigationBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Signal irrigation"
    _attr_has_entity_name = True
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_signal_irrigation"

    @property
    def is_on(self):
        post_status = normalize_post_application_status(
            self._decision_value("application_post_watering_status")
        )
        if post_status == "autorise":
            return True
        return bool(self._decision_value("arrosage_recommande", False))

    @property
    def extra_state_attributes(self):
        post_status = normalize_post_application_status(
            self._decision_value("application_post_watering_status")
        )
        hydric_actionable = bool(self._decision_value("arrosage_recommande", False))
        type_arrosage = str(self._decision_value("type_arrosage") or "").strip().lower()
        if post_status == "autorise":
            trigger_kind = "post_application"
            source_status = post_status
        elif hydric_actionable:
            trigger_kind = "hydrique"
            source_status = type_arrosage or "on"
        else:
            trigger_kind = "none"
            source_status = post_status if post_status != "indisponible" else "off"
        summary_map = {
            "post_application": "Irrigation post-application autorisée",
            "hydrique": "Irrigation hydrique actionnable",
            "none": "Aucune irrigation actionnable",
        }
        attrs = {
            "source_entities": [
                f"binary_sensor.{DOMAIN}_arrosage_apres_application_autorise",
                f"binary_sensor.{DOMAIN}_arrosage_recommande",
            ],
            "source_status": source_status,
            "application_post_watering_status": post_status,
            "type_arrosage": type_arrosage or None,
            "trigger_kind": trigger_kind,
            "summary": summary_map[trigger_kind],
        }
        return {key: value for key, value in attrs.items() if value not in (None, "", [], {})}


class GazonSignalInterventionBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Signal intervention"
    _attr_has_entity_name = True
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_signal_intervention"

    def _intervention_payload(self) -> dict[str, object]:
        payload = self._decision_value("intervention_recommendation")
        if isinstance(payload, dict) and payload:
            return payload
        data = getattr(self.coordinator, "data", None)
        if isinstance(data, dict):
            payload = data.get("intervention_recommendation")
            if isinstance(payload, dict) and payload:
                return payload
        return {}

    @property
    def is_on(self):
        payload = self._intervention_payload()
        status = str(payload.get("status") or "").strip().lower()
        ready_to_declare = bool(payload.get("ready_to_declare"))
        return ready_to_declare or status == "recommended"

    @property
    def extra_state_attributes(self):
        payload = self._intervention_payload()
        if not payload:
            return None
        status = str(payload.get("status") or "unavailable").strip().lower()
        ready_to_declare = bool(payload.get("ready_to_declare"))
        selected_product_ready = bool(payload.get("selected_product_ready"))
        trigger_kind = "none"
        if ready_to_declare:
            trigger_kind = "ready"
        elif status == "recommended":
            trigger_kind = "recommended"
        elif status == "possible":
            trigger_kind = "soft"
        product = payload.get("product")
        if not isinstance(product, dict):
            product = {}
        ui = payload.get("ui")
        if not isinstance(ui, dict):
            ui = {}
        summary = ui.get("summary") or {
            "recommended": "Recommandé",
            "possible": "À préparer",
            "blocked": "Bloqué",
            "unavailable": "Non disponible",
        }.get(status, "Non disponible")
        attrs = {
            "source_entity": f"sensor.{DOMAIN}_prochaine_intervention",
            "source_status": status,
            "recommended_action": payload.get("recommended_action"),
            "product_id": product.get("id"),
            "product_name": product.get("name"),
            "ready_to_declare": ready_to_declare,
            "selected_product_ready": selected_product_ready,
            "trigger_kind": trigger_kind,
            "summary": summary,
        }
        return {key: value for key, value in attrs.items() if value not in (None, "", [], {})}
