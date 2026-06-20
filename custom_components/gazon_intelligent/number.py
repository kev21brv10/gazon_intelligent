from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.helpers.entity import EntityCategory
try:
    from homeassistant.helpers.restore_state import RestoreEntity
except Exception:  # pragma: no cover - fallback for unit tests / stripped envs
    class RestoreEntity:  # type: ignore[too-many-ancestors]
        async def async_get_last_state(self):
            return None

from .const import (
    CONF_HAUTEUR_MAX_TONDEUSE_CM,
    CONF_HAUTEUR_MIN_TONDEUSE_CM,
    CONF_HAUTEUR_COUPE_TONDEUSE_MM,
    CONF_DEBIT_ZONE_1,
    CONF_DEBIT_ZONE_2,
    CONF_DEBIT_ZONE_3,
    CONF_DEBIT_ZONE_4,
    CONF_DEBIT_ZONE_5,
    DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
    DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES,
    DOMAIN,
)
from .entity_base import GazonEntityBase


_MOWER_HEIGHT_STEP_CM = 0.5


def _round_to_mower_step(value: float) -> float:
    return round(round(float(value) / _MOWER_HEIGHT_STEP_CM) * _MOWER_HEIGHT_STEP_CM, 2)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return
    async_add_entities(
        [
            GazonDebitZoneNumber(coordinator, 1, CONF_DEBIT_ZONE_1),
            GazonDebitZoneNumber(coordinator, 2, CONF_DEBIT_ZONE_2),
            GazonDebitZoneNumber(coordinator, 3, CONF_DEBIT_ZONE_3),
            GazonDebitZoneNumber(coordinator, 4, CONF_DEBIT_ZONE_4),
            GazonDebitZoneNumber(coordinator, 5, CONF_DEBIT_ZONE_5),
            GazonMowerSettingNumber(
                coordinator,
                "Hauteur min tondeuse",
                "hauteur_min_tondeuse_cm",
                CONF_HAUTEUR_MIN_TONDEUSE_CM,
                0.5,
                15.0,
                DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
            ),
            GazonMowerSettingNumber(
                coordinator,
                "Hauteur max tondeuse",
                "hauteur_max_tondeuse_cm",
                CONF_HAUTEUR_MAX_TONDEUSE_CM,
                0.5,
                15.0,
                DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
            ),
            GazonMowerCuttingHeightNumber(coordinator),
            GazonMowingCooldownNumber(coordinator),
        ]
    )


class GazonDebitZoneNumber(GazonEntityBase, NumberEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0.0
    _attr_native_max_value = 200.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "mm/h"
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator, zone_index: int, config_key: str) -> None:
        super().__init__(coordinator)
        self._zone_index = zone_index
        self._config_key = config_key
        self._attr_name = f"Débit zone {zone_index}"
        self._set_entity_identity("number", f"debit_zone_{zone_index}")

    @property
    def native_value(self):
        value = self.coordinator._get_conf(self._config_key)
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_config({self._config_key: float(value)})


class GazonMowerSettingNumber(GazonEntityBase, NumberEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "cm"
    _attr_icon = "mdi:content-cut"

    def __init__(
        self,
        coordinator,
        label: str,
        suffix: str,
        config_key: str,
        native_min: float,
        native_max: float,
        default_value: float,
    ) -> None:
        super().__init__(coordinator)
        self._config_key = config_key
        self._default_value = default_value
        self._attr_name = label
        self._set_entity_identity("number", suffix)
        self._attr_native_min_value = native_min
        self._attr_native_max_value = native_max

    @property
    def native_value(self):
        value = self.coordinator._get_conf(self._config_key)
        if value is None:
            return _round_to_mower_step(self._default_value)
        try:
            return _round_to_mower_step(value)
        except (TypeError, ValueError):
            return _round_to_mower_step(self._default_value)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_config({self._config_key: _round_to_mower_step(value)})


class GazonMowerCuttingHeightNumber(RestoreEntity, GazonEntityBase, NumberEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = "mm"
    _attr_icon = "mdi:content-cut"

    # Bornes DYNAMIQUES dérivées des réglages configurables « Hauteur min/max tondeuse » (cm → mm).
    # Générique : chacun règle la plage de SA tondeuse (3-6 cm, 0,5-10 cm…) et le slider suit —
    # aucune valeur codée en dur, donc une tondeuse 0-100 mm fonctionne aussi.
    def _configured_bound_mm(self, config_key: str, default_cm: float) -> float:
        value = self.coordinator._get_conf(config_key)
        try:
            return round(float(value) * 10.0, 1)
        except (TypeError, ValueError):
            return round(float(default_cm) * 10.0, 1)

    @property
    def native_min_value(self) -> float:
        return self._configured_bound_mm(CONF_HAUTEUR_MIN_TONDEUSE_CM, DEFAULT_HAUTEUR_MIN_TONDEUSE_CM)

    @property
    def native_max_value(self) -> float:
        return self._configured_bound_mm(CONF_HAUTEUR_MAX_TONDEUSE_CM, DEFAULT_HAUTEUR_MAX_TONDEUSE_CM)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._config_key = CONF_HAUTEUR_COUPE_TONDEUSE_MM
        self._default_value: float | None = 50.0
        self._restored_native_value: float | None = None
        self._attr_name = "Hauteur de coupe tondeuse"
        self._set_entity_identity("number", "hauteur_coupe_tondeuse")

    async def async_added_to_hass(self) -> None:
        parent_added = getattr(super(), "async_added_to_hass", None)
        if callable(parent_added):
            await parent_added()
        self._restored_native_value = await self._async_get_last_state_float()

    async def _async_get_last_state_float(self) -> float | None:
        getter = getattr(self, "async_get_last_state", None)
        if not callable(getter):
            return None
        state = await getter()
        if state is None:
            return None
        raw = getattr(state, "state", None)
        try:
            value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
        if value is None or value <= 0:
            return None
        return value

    @staticmethod
    def _round_to_cutting_height_step(value: float) -> float:
        return round(round(float(value) / 5.0) * 5.0, 2)

    @property
    def native_value(self):
        value = self.coordinator._get_conf(self._config_key)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = None
        if numeric is not None and numeric > 0:
            rounded = self._round_to_cutting_height_step(numeric)
            return max(self.native_min_value, min(rounded, self.native_max_value))

        restored = self._restored_native_value
        if restored is not None and restored > 0:
            rounded = self._round_to_cutting_height_step(restored)
            return max(self.native_min_value, min(rounded, self.native_max_value))

        return self._default_value

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_config({self._config_key: self._round_to_cutting_height_step(value)})


class GazonMowingCooldownNumber(GazonEntityBase, NumberEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0.0
    _attr_native_max_value = 1440.0
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Délai reprise tonte après arrosage"
        self._set_entity_identity("number", "delai_reprise_tonte_apres_arrosage")

    @property
    def native_value(self):
        value = self.coordinator.mowing_cooldown_after_watering_minutes
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_mowing_cooldown_after_watering_minutes(value)
