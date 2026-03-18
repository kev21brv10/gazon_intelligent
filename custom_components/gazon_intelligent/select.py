from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory

from .const import (
    CONF_CAPTEUR_HAUTEUR_GAZON,
    CONF_CAPTEUR_HUMIDITE_SOL,
    CONF_CAPTEUR_ROSEE,
    CONF_CAPTEUR_VENT,
    CONF_TYPE_SOL,
    DEFAULT_MODE,
    DEFAULT_TYPE_SOL,
    DOMAIN,
    MODES_GAZON,
    TYPES_SOL,
)
from .entity_base import GazonEntityBase


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonModeSelect(coordinator),
            GazonTypeSolSelect(coordinator),
            GazonSensorBindingSelect(
                coordinator,
                key=CONF_CAPTEUR_HAUTEUR_GAZON,
                name="Capteur hauteur du gazon",
            ),
            GazonSensorBindingSelect(
                coordinator,
                key=CONF_CAPTEUR_HUMIDITE_SOL,
                name="Capteur humidité du sol",
            ),
            GazonSensorBindingSelect(
                coordinator,
                key=CONF_CAPTEUR_VENT,
                name="Capteur vent",
            ),
            GazonSensorBindingSelect(
                coordinator,
                key=CONF_CAPTEUR_ROSEE,
                name="Capteur rosée",
            ),
        ]
    )


class GazonModeSelect(GazonEntityBase, SelectEntity):
    _attr_name = "Mode du gazon"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_mode"

    @property
    def options(self):
        return MODES_GAZON

    @property
    def current_option(self):
        return self.coordinator.data.get("mode", DEFAULT_MODE)

    async def async_select_option(self, option: str):
        await self.coordinator.async_set_mode(option)

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "phase_active",
            "phase_dominante",
            "phase_dominante_source",
            "sous_phase",
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
            "prochaine_reevaluation",
        )


class GazonTypeSolSelect(GazonEntityBase, SelectEntity):
    _attr_name = "Type de sol"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_type_sol"

    @property
    def options(self):
        return TYPES_SOL

    @property
    def current_option(self):
        return self.coordinator._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL

    async def async_select_option(self, option: str):
        await self.coordinator.async_update_config({CONF_TYPE_SOL: option})

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "phase_active",
            "bilan_hydrique_mm",
            "score_hydrique",
            "score_stress",
            "score_tonte",
        )


class GazonSensorBindingSelect(GazonEntityBase, SelectEntity):
    """Permet de rebrancher un capteur depuis l'UI Home Assistant."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._config_key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"

    @property
    def options(self):
        options = ["Aucun"]
        seen: set[str] = set()

        current = self.coordinator._get_conf(self._config_key)
        if current:
            current_option = self._format_option(current, missing_ok=True)
            options.append(current_option)
            seen.add(current_option)

        for state in sorted(self.hass.states.async_all(), key=lambda st: st.entity_id):
            if not state.entity_id.startswith("sensor."):
                continue
            option = self._format_option(state.entity_id, state.attributes.get("friendly_name"))
            if option not in seen:
                options.append(option)
                seen.add(option)

        return options

    @property
    def current_option(self):
        current = self.coordinator._get_conf(self._config_key)
        if not current:
            return "Aucun"
        return self._format_option(current, missing_ok=True)

    async def async_select_option(self, option: str):
        if option == "Aucun":
            await self.coordinator.async_update_config({self._config_key: None})
            return

        entity_id = self._parse_option(option)
        await self.coordinator.async_update_config({self._config_key: entity_id})

    def _format_option(self, entity_id: str, friendly_name: str | None = None, missing_ok: bool = False) -> str:
        label = friendly_name or entity_id
        if missing_ok and friendly_name is None:
            label = "Entité absente"
        return f"{entity_id} | {label}"

    def _parse_option(self, option: str) -> str:
        if " | " not in option:
            return option
        return option.split(" | ", 1)[0].strip()

    @property
    def extra_state_attributes(self):
        return self._attrs_from_data(
            "phase_active",
            "pluie_demain_source",
            "pluie_source",
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
        )
