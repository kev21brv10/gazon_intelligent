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
    CONF_TONDEUSE,
    CONF_CAPTEUR_PLUIE_24H,
    CONF_CAPTEUR_PLUIE_DEMAIN,
    CONF_CAPTEUR_TEMPERATURE,
    CONF_CAPTEUR_ETP,
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

        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE_1): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_ZONE_2): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_ZONE_3): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_ZONE_4): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_ZONE_5): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_DEBIT_ZONE_1, default=1.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=10, step=0.1, unit_of_measurement="mm/min")
                ),
                vol.Optional(CONF_DEBIT_ZONE_2): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=10, step=0.1, unit_of_measurement="mm/min")
                ),
                vol.Optional(CONF_DEBIT_ZONE_3): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=10, step=0.1, unit_of_measurement="mm/min")
                ),
                vol.Optional(CONF_DEBIT_ZONE_4): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=10, step=0.1, unit_of_measurement="mm/min")
                ),
                vol.Optional(CONF_DEBIT_ZONE_5): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.1, max=10, step=0.1, unit_of_measurement="mm/min")
                ),
                vol.Optional(CONF_TONDEUSE): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
                vol.Required(CONF_CAPTEUR_PLUIE_24H): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_CAPTEUR_PLUIE_DEMAIN): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_CAPTEUR_TEMPERATURE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_CAPTEUR_ETP): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema)
