from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return
    async_add_entities(
        [
            GazonAutoIrrigationSwitch(coordinator),
            GazonEveningCoolingSwitch(coordinator),
            GazonMowerCoordinationSwitch(coordinator),
            GazonAutoMowingDeclarationSwitch(coordinator),
        ]
    )


class GazonAutoIrrigationSwitch(GazonEntityBase, SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:sprinkler"
    _attr_translation_key = "auto_irrigation_enabled"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("switch", "arrosage_automatique")

    @property
    def is_on(self):
        return bool(self.coordinator.auto_irrigation_enabled)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_auto_irrigation_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_auto_irrigation_enabled(False)


class GazonEveningCoolingSwitch(GazonEntityBase, SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:weather-sunset-down"
    _attr_translation_key = "evening_cooling_enabled"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("switch", "rafraichissement_soir")

    @property
    def is_on(self):
        return bool(self.coordinator.evening_cooling_enabled)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_evening_cooling_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_evening_cooling_enabled(False)


class GazonMowerCoordinationSwitch(GazonEntityBase, SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:robot-mower"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Coordination tondeuse"
        self._set_entity_identity("switch", "coordination_tondeuse")

    @property
    def is_on(self):
        return bool(self.coordinator.mower_coordination_enabled)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_mower_coordination_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_mower_coordination_enabled(False)


class GazonAutoMowingDeclarationSwitch(GazonEntityBase, SwitchEntity):
    """Laisse l'intégration inscrire elle-même la tonte du jour.

    Coupé, l'historique de tonte ne dépend plus que d'un déclarant externe — c'est la
    situation qui a laissé passer sept jours de retard du 30/07 au 06/08/2026.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Déclaration auto de la tonte"
        self._set_entity_identity("switch", "declaration_tonte_auto")

    @property
    def is_on(self):
        return bool(self.coordinator.auto_mowing_declaration_enabled)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_set_auto_mowing_declaration_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_set_auto_mowing_declaration_enabled(False)
