import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_ZONE_1,
    CONF_ZONE_2,
    CONF_ZONE_3,
    CONF_ZONE_4,
    CONF_ZONE_5,
    CONF_DEBIT_ZONE_1,
    CONF_DEBIT_ZONE_2,
    CONF_DEBIT_ZONE_3,
    CONF_DEBIT_ZONE_4,
    CONF_DEBIT_ZONE_5,
    CONF_ENTITE_METEO,
    CONF_CAPTEUR_PLUIE_24H,
    CONF_CAPTEUR_PLUIE_DEMAIN,
    CONF_CAPTEUR_TEMPERATURE,
    CONF_CAPTEUR_ETP,
    CONF_CAPTEUR_HUMIDITE,
    CONF_CAPTEUR_HUMIDITE_SOL,
    CONF_CAPTEUR_VENT,
    CONF_CAPTEUR_ROSEE,
    CONF_CAPTEUR_HAUTEUR_GAZON,
    CONF_CAPTEUR_RETOUR_ARROSAGE,
    CONF_CAPTEUR_PLUIE_FINE,
    CONF_TYPE_SOL,
    DEFAULT_TYPE_SOL,
    TYPES_SOL,
)


def build_schema(current: dict | None = None):
    current = current or {}
    def _d(val):
        return val if val is not None else vol.UNDEFINED
    return vol.Schema(
        {
            vol.Required(CONF_ZONE_1, default=_d(current.get(CONF_ZONE_1))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_ZONE_2, default=_d(current.get(CONF_ZONE_2))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_ZONE_3, default=_d(current.get(CONF_ZONE_3))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_ZONE_4, default=_d(current.get(CONF_ZONE_4))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_ZONE_5, default=_d(current.get(CONF_ZONE_5))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_DEBIT_ZONE_1, default=_d(current.get(CONF_DEBIT_ZONE_1, 60.0))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=200, step=1, unit_of_measurement="mm/h")
            ),
            vol.Optional(CONF_DEBIT_ZONE_2, default=_d(current.get(CONF_DEBIT_ZONE_2))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=200, step=1, unit_of_measurement="mm/h")
            ),
            vol.Optional(CONF_DEBIT_ZONE_3, default=_d(current.get(CONF_DEBIT_ZONE_3))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=200, step=1, unit_of_measurement="mm/h")
            ),
            vol.Optional(CONF_DEBIT_ZONE_4, default=_d(current.get(CONF_DEBIT_ZONE_4))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=200, step=1, unit_of_measurement="mm/h")
            ),
            vol.Optional(CONF_DEBIT_ZONE_5, default=_d(current.get(CONF_DEBIT_ZONE_5))): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=200, step=1, unit_of_measurement="mm/h")
            ),
            vol.Optional(CONF_ENTITE_METEO, default=_d(current.get(CONF_ENTITE_METEO))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Required(CONF_CAPTEUR_PLUIE_24H, default=_d(current.get(CONF_CAPTEUR_PLUIE_24H))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_PLUIE_DEMAIN, default=_d(current.get(CONF_CAPTEUR_PLUIE_DEMAIN))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_TEMPERATURE, default=_d(current.get(CONF_CAPTEUR_TEMPERATURE))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_ETP, default=_d(current.get(CONF_CAPTEUR_ETP))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_HUMIDITE, default=_d(current.get(CONF_CAPTEUR_HUMIDITE))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_HUMIDITE_SOL, default=_d(current.get(CONF_CAPTEUR_HUMIDITE_SOL))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_VENT, default=_d(current.get(CONF_CAPTEUR_VENT))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_ROSEE, default=_d(current.get(CONF_CAPTEUR_ROSEE))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_HAUTEUR_GAZON, default=_d(current.get(CONF_CAPTEUR_HAUTEUR_GAZON))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_RETOUR_ARROSAGE, default=_d(current.get(CONF_CAPTEUR_RETOUR_ARROSAGE))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_CAPTEUR_PLUIE_FINE, default=_d(current.get(CONF_CAPTEUR_PLUIE_FINE))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_TYPE_SOL, default=_d(current.get(CONF_TYPE_SOL, DEFAULT_TYPE_SOL))): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=TYPES_SOL,
                )
            ),
        }
    )


class GazonIntelligentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Gazon Intelligent",
                data=user_input,
            )

        return self.async_show_form(step_id="user", data_schema=build_schema())

    @staticmethod
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return GazonOptionsFlow(entry)


class GazonOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        current = {**self.entry.data, **self.entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="user", data_schema=build_schema(current))
