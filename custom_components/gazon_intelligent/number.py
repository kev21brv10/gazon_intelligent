from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.helpers.entity import EntityCategory

from .const import (
    CONF_HAUTEUR_MAX_TONDEUSE_CM,
    CONF_HAUTEUR_MIN_TONDEUSE_CM,
    CONF_DEBIT_ZONE_1,
    CONF_DEBIT_ZONE_2,
    CONF_DEBIT_ZONE_3,
    CONF_DEBIT_ZONE_4,
    CONF_DEBIT_ZONE_5,
    DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
    DOMAIN,
)
from .entity_base import GazonEntityBase


_MOWER_HEIGHT_STEP_CM = 0.5


def _round_to_mower_step(value: float) -> float:
    return round(round(float(value) / _MOWER_HEIGHT_STEP_CM) * _MOWER_HEIGHT_STEP_CM, 2)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
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
        self._attr_unique_id = f"{coordinator.entry.entry_id}_debit_zone_{zone_index}"

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
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{suffix}"
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
