from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.helpers.entity import EntityCategory

from .const import (
    CONF_DEBIT_ZONE_1,
    CONF_DEBIT_ZONE_2,
    CONF_DEBIT_ZONE_3,
    CONF_DEBIT_ZONE_4,
    CONF_DEBIT_ZONE_5,
    DOMAIN,
)
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonDebitZoneNumber(coordinator, 1, CONF_DEBIT_ZONE_1),
            GazonDebitZoneNumber(coordinator, 2, CONF_DEBIT_ZONE_2),
            GazonDebitZoneNumber(coordinator, 3, CONF_DEBIT_ZONE_3),
            GazonDebitZoneNumber(coordinator, 4, CONF_DEBIT_ZONE_4),
            GazonDebitZoneNumber(coordinator, 5, CONF_DEBIT_ZONE_5),
        ]
    )


class GazonDebitZoneNumber(GazonEntityBase, NumberEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0.0
    _attr_native_max_value = 200.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "mm/h"

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

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data("phase_active", "mode", "objectif_mm")
