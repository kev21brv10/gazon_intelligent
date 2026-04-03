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
    _attr_name = "Irrigation recommandée"
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
