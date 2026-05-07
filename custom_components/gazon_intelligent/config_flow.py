from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_INSTANCE_SLUG,
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
    CONF_ENTITE_TONDEUSE,
    CONF_CAPTEUR_TONDEUSE_ERREUR,
    CONF_CAPTEUR_TONDEUSE_BATTERIE,
    CONF_CAPTEUR_TONDEUSE_PLUIE,
    CONF_CAPTEUR_TONDEUSE_EN_CHARGE,
    CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART,
    CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE,
    CONF_HAUTEUR_MAX_TONDEUSE_CM,
    CONF_HAUTEUR_MIN_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
    CONF_TYPE_SOL,
    DEFAULT_TYPE_SOL,
    TYPES_SOL,
    SHARED_WEATHER_CONFIG_KEYS,
)
from .entity_ids import normalize_instance_slug
from .entity_migration import CURRENT_CONFIG_ENTRY_VERSION
from .shared_state import get_shared_state


def _d(val):
    return val if val is not None else vol.UNDEFINED


def _build_instance_title(instance_slug: str | None) -> str:
    if not instance_slug:
        return "Gazon Intelligent"
    humanized = instance_slug.replace("_", " ").strip()
    if not humanized:
        return "Gazon Intelligent"
    return f"Gazon Intelligent - {humanized.title()}"


def _build_base_fields(current: dict | None, *, include_instance_slug: bool = False) -> dict:
    current = current or {}
    fields = {}
    if include_instance_slug:
        fields[vol.Required(CONF_INSTANCE_SLUG, default=_d(current.get(CONF_INSTANCE_SLUG)))] = str
    fields.update({
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
        vol.Required(CONF_DEBIT_ZONE_1, default=_d(current.get(CONF_DEBIT_ZONE_1, 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
        vol.Required(CONF_DEBIT_ZONE_2, default=_d(current.get(CONF_DEBIT_ZONE_2, 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
        vol.Required(CONF_DEBIT_ZONE_3, default=_d(current.get(CONF_DEBIT_ZONE_3, 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
        vol.Required(CONF_DEBIT_ZONE_4, default=_d(current.get(CONF_DEBIT_ZONE_4, 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
        vol.Required(CONF_DEBIT_ZONE_5, default=_d(current.get(CONF_DEBIT_ZONE_5, 0.0))): vol.All(vol.Coerce(float), vol.Range(min=0, max=200)),
        vol.Required(CONF_TYPE_SOL, default=_d(current.get(CONF_TYPE_SOL, DEFAULT_TYPE_SOL))): vol.In(TYPES_SOL),
    })
    return fields


def build_schema(current: dict | None = None, *, include_instance_slug: bool = False):
    current = current or {}
    return vol.Schema(_build_base_fields(current, include_instance_slug=include_instance_slug))


def _shared_config_defaults(hass=None) -> dict[str, object]:
    if hass is None:
        return {}
    shared_state = get_shared_state(hass, create=False)
    if shared_state is None:
        return {}
    return {
        key: value
        for key, value in shared_state.shared_config.items()
        if key in SHARED_WEATHER_CONFIG_KEYS and value not in (None, "", [], {})
    }


def build_advanced_schema(current: dict | None = None, *, shared_defaults: dict | None = None):
    current = dict(current or {})
    if isinstance(shared_defaults, dict):
        for key, value in shared_defaults.items():
            if key in SHARED_WEATHER_CONFIG_KEYS and key not in current and value not in (None, "", [], {}):
                current[key] = value
    return vol.Schema(
        {
            vol.Required(CONF_ENTITE_METEO, default=_d(current.get(CONF_ENTITE_METEO))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Optional(CONF_CAPTEUR_PLUIE_24H, default=_d(current.get(CONF_CAPTEUR_PLUIE_24H))): selector.EntitySelector(
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
            vol.Optional(CONF_CAPTEUR_HAUTEUR_GAZON, default=_d(current.get(CONF_CAPTEUR_HAUTEUR_GAZON))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_ENTITE_TONDEUSE, default=_d(current.get(CONF_ENTITE_TONDEUSE))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="lawn_mower")
            ),
            vol.Optional(
                CONF_CAPTEUR_TONDEUSE_ERREUR,
                default=_d(current.get(CONF_CAPTEUR_TONDEUSE_ERREUR)),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_CAPTEUR_TONDEUSE_BATTERIE,
                default=_d(current.get(CONF_CAPTEUR_TONDEUSE_BATTERIE)),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_CAPTEUR_TONDEUSE_PLUIE,
                default=_d(current.get(CONF_CAPTEUR_TONDEUSE_PLUIE)),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
            vol.Optional(
                CONF_CAPTEUR_TONDEUSE_EN_CHARGE,
                default=_d(current.get(CONF_CAPTEUR_TONDEUSE_EN_CHARGE)),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
            vol.Optional(
                CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART,
                default=_d(current.get(CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART)),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE,
                default=_d(current.get(CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE)),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="number")),
            vol.Optional(
                CONF_HAUTEUR_MIN_TONDEUSE_CM,
                default=_d(current.get(CONF_HAUTEUR_MIN_TONDEUSE_CM, DEFAULT_HAUTEUR_MIN_TONDEUSE_CM)),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=15.0)),
            vol.Optional(
                CONF_HAUTEUR_MAX_TONDEUSE_CM,
                default=_d(current.get(CONF_HAUTEUR_MAX_TONDEUSE_CM, DEFAULT_HAUTEUR_MAX_TONDEUSE_CM)),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=15.0)),
            vol.Optional(CONF_CAPTEUR_RETOUR_ARROSAGE, default=_d(current.get(CONF_CAPTEUR_RETOUR_ARROSAGE))): selector.EntitySelector(
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
        }
    )


class GazonIntelligentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    VERSION = CURRENT_CONFIG_ENTRY_VERSION

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            instance_slug = normalize_instance_slug(user_input.get(CONF_INSTANCE_SLUG))
            if instance_slug is None:
                return self.async_show_form(
                    step_id="user",
                    data_schema=build_schema(include_instance_slug=True),
                    errors={"base": "invalid_instance_slug"},
                )
            self._base_user_input = {**dict(user_input), CONF_INSTANCE_SLUG: instance_slug}
            return self.async_show_form(
                step_id="sensors",
                data_schema=build_advanced_schema(shared_defaults=_shared_config_defaults(getattr(self, "hass", None))),
            )

        return self.async_show_form(step_id="user", data_schema=build_schema(include_instance_slug=True))

    async def async_step_sensors(self, user_input=None):
        if user_input is not None:
            data = {**getattr(self, "_base_user_input", {}), **user_input}
            instance_slug = normalize_instance_slug(data.get(CONF_INSTANCE_SLUG))
            if instance_slug is None:
                return self.async_show_form(
                    step_id="user",
                    data_schema=build_schema(include_instance_slug=True),
                    errors={"base": "invalid_instance_slug"},
                )
            data[CONF_INSTANCE_SLUG] = instance_slug
            await self.async_set_unique_id(f"{DOMAIN}:{instance_slug}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_build_instance_title(instance_slug),
                data=data,
            )

        return self.async_show_form(
            step_id="sensors",
            data_schema=build_advanced_schema(
                getattr(self, "_base_user_input", {}),
                shared_defaults=_shared_config_defaults(getattr(self, "hass", None)),
            ),
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        current = {**entry.data, **entry.options}

        if user_input is not None:
            return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(step_id="reconfigure", data_schema=build_schema(current))

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

        return self.async_show_form(
            step_id="user",
            data_schema=build_advanced_schema(current, shared_defaults=_shared_config_defaults(getattr(self, "hass", None))),
        )
