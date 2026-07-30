from __future__ import annotations

from typing import Any

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
    CONF_CAPTEUR_RAYONNEMENT,
    CONF_CAPTEUR_PRESSION,
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


_OPTIONAL_CLEARABLE_KEYS = (
    CONF_ZONE_2,
    CONF_ZONE_3,
    CONF_ZONE_4,
    CONF_ZONE_5,
    CONF_CAPTEUR_PLUIE_24H,
    CONF_CAPTEUR_PLUIE_DEMAIN,
    CONF_CAPTEUR_TEMPERATURE,
    CONF_CAPTEUR_ETP,
    CONF_CAPTEUR_HUMIDITE,
    CONF_CAPTEUR_HUMIDITE_SOL,
    CONF_CAPTEUR_VENT,
    CONF_CAPTEUR_ROSEE,
    CONF_CAPTEUR_RAYONNEMENT,
    CONF_CAPTEUR_PRESSION,
    CONF_CAPTEUR_HAUTEUR_GAZON,
    CONF_CAPTEUR_RETOUR_ARROSAGE,
    CONF_ENTITE_TONDEUSE,
    CONF_CAPTEUR_TONDEUSE_ERREUR,
    CONF_CAPTEUR_TONDEUSE_BATTERIE,
    CONF_CAPTEUR_TONDEUSE_PLUIE,
    CONF_CAPTEUR_TONDEUSE_EN_CHARGE,
    CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART,
    CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE,
)

# Clés de config qui contiennent des entity_id et doivent être validées
# à la soumission du formulaire capteurs (hors sélecteur UI).
_OPTIONAL_ENTITY_KEYS = (
    CONF_ENTITE_METEO,
    CONF_CAPTEUR_PLUIE_24H,
    CONF_CAPTEUR_PLUIE_DEMAIN,
    CONF_CAPTEUR_TEMPERATURE,
    CONF_CAPTEUR_ETP,
    CONF_CAPTEUR_HUMIDITE,
    CONF_CAPTEUR_HUMIDITE_SOL,
    CONF_CAPTEUR_VENT,
    CONF_CAPTEUR_ROSEE,
    CONF_CAPTEUR_RAYONNEMENT,
    CONF_CAPTEUR_PRESSION,
    CONF_CAPTEUR_HAUTEUR_GAZON,
    CONF_CAPTEUR_RETOUR_ARROSAGE,
    CONF_ENTITE_TONDEUSE,
    CONF_CAPTEUR_TONDEUSE_ERREUR,
    CONF_CAPTEUR_TONDEUSE_BATTERIE,
    CONF_CAPTEUR_TONDEUSE_PLUIE,
    CONF_CAPTEUR_TONDEUSE_EN_CHARGE,
    CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART,
    CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE,
)

# Clés effaçables par l'OPTIONS FLOW (formulaire « Configurer » = capteurs uniquement).
# Les zones en sont EXCLUES : ce formulaire ne les affiche pas, or `_normalize_optional_clears`
# y injectait `zone_2..zone_5 = None` dans entry.options à chaque validation. Les clés existant
# alors — à None — le repli `opts.get(k, data.get(k))` du coordinateur ne se déclenchait jamais
# et les zones 2 à 5 cessaient silencieusement d'être arrosées, sans erreur ni notification.
# Le flow « Reconfigurer », lui, affiche bien les champs zones : il garde le tuple complet.
_OPTIONS_CLEARABLE_KEYS = tuple(
    key
    for key in _OPTIONAL_CLEARABLE_KEYS
    if key not in (CONF_ZONE_2, CONF_ZONE_3, CONF_ZONE_4, CONF_ZONE_5)
)


def _normalize_optional_clears(
    payload: dict | None,
    keys: tuple[str, ...] = _OPTIONAL_CLEARABLE_KEYS,
) -> dict:
    normalized = dict(payload or {})
    for key in keys:
        normalized.setdefault(key, None)
    return normalized


def _replace_with_base_config(
    current: dict | None,
    payload: dict | None,
) -> dict:
    merged = dict(current or {})
    normalized = _normalize_optional_clears(payload)
    # `update` et surtout PAS une compréhension de dictionnaire : `merged` est pré-rempli avec la
    # configuration EXISTANTE, qu'une compréhension écraserait — on perdrait tous les réglages non
    # touchés lors d'une reconfiguration.
    merged.update(normalized)
    for idx in range(1, 6):
        zone_key = f"zone_{idx}"
        rate_key = f"debit_zone_{idx}"
        try:
            rate_value = float(merged.get(rate_key, 0.0) or 0.0)
        except (TypeError, ValueError):
            rate_value = 0.0
        if rate_value <= 0:
            merged[zone_key] = None
    return merged


def _zone_field_default(current: dict, zone_key: str, rate_key: str):
    try:
        rate_value = float(current.get(rate_key, 0.0) or 0.0)
    except (TypeError, ValueError):
        rate_value = 0.0
    if rate_value <= 0:
        return vol.UNDEFINED
    return _d(current.get(zone_key))


def _build_instance_title(instance_slug: str | None) -> str:
    if not instance_slug:
        return "Gazon Intelligent"
    humanized = instance_slug.replace("_", " ").strip()
    if not humanized:
        return "Gazon Intelligent"
    return f"Gazon Intelligent - {humanized.title()}"


def _build_base_fields(current: dict | None, *, include_instance_slug: bool = False) -> dict:
    current = current or {}
    # Annotation explicite : un dict de schéma voluptuous est hétérogène par nature (marqueurs
    # Required/Optional en clés, validateurs str / EntitySelector / vol.All / vol.In en valeurs).
    # Sans elle, mypy infère le type depuis la PREMIÈRE entrée insérée — `dict[Required, type[str]]`
    # quand include_instance_slug est vrai — puis rejette toutes les suivantes.
    fields: dict[Any, Any] = {}
    if include_instance_slug:
        fields[vol.Required(CONF_INSTANCE_SLUG, default=_d(current.get(CONF_INSTANCE_SLUG)))] = str
    fields.update({
        vol.Required(CONF_ZONE_1, default=_zone_field_default(current, CONF_ZONE_1, CONF_DEBIT_ZONE_1)): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="switch")
        ),
        vol.Optional(CONF_ZONE_2, default=_zone_field_default(current, CONF_ZONE_2, CONF_DEBIT_ZONE_2)): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="switch")
        ),
        vol.Optional(CONF_ZONE_3, default=_zone_field_default(current, CONF_ZONE_3, CONF_DEBIT_ZONE_3)): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="switch")
        ),
        vol.Optional(CONF_ZONE_4, default=_zone_field_default(current, CONF_ZONE_4, CONF_DEBIT_ZONE_4)): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="switch")
        ),
        vol.Optional(CONF_ZONE_5, default=_zone_field_default(current, CONF_ZONE_5, CONF_DEBIT_ZONE_5)): selector.EntitySelector(
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
            if (
                key in SHARED_WEATHER_CONFIG_KEYS
                and current.get(key) in (None, "", [], {})
                and value not in (None, "", [], {})
            ):
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
            # `device_class` filtre la liste proposée : ces deux entrées pilotent le bilan sol,
            # et une unité inattendue le fausse massivement (rayonnement en kW/m² → ET0 −81 %,
            # donc un sol qui ne sèche plus et un arrosage qui ne part jamais).
            vol.Optional(CONF_CAPTEUR_RAYONNEMENT, default=_d(current.get(CONF_CAPTEUR_RAYONNEMENT))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="irradiance")
            ),
            vol.Optional(CONF_CAPTEUR_PRESSION, default=_d(current.get(CONF_CAPTEUR_PRESSION))): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="atmospheric_pressure")
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
            # Validation des entity_id optionnels : si une valeur est fournie
            # (hors UI selector), on vérifie que l'entité existe dans HA.
            hass = getattr(self, "hass", None)
            if hass is not None:
                invalid_entities = [
                    key for key in _OPTIONAL_ENTITY_KEYS
                    if data.get(key) and not hass.states.get(data[key])
                ]
                if invalid_entities:
                    return self.async_show_form(
                        step_id="sensors",
                        data_schema=build_advanced_schema(
                            getattr(self, "_base_user_input", {}),
                            shared_defaults=_shared_config_defaults(hass),
                        ),
                        errors={key: "entity_not_found" for key in invalid_entities},
                    )
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
            updated_data = _replace_with_base_config(entry.data, dict(user_input))
            if not hasattr(self, "hass") or self.hass is None:
                return self.async_update_reload_and_abort(entry, data_updates=updated_data)
            self.hass.config_entries.async_update_entry(entry, data=updated_data)
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

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
            merged = {
                **self.entry.options,
                **_normalize_optional_clears(dict(user_input), _OPTIONS_CLEARABLE_KEYS),
            }
            # Nettoyage des entrées déjà polluées par l'ancien comportement : une clé de zone
            # laissée à None dans les options masque la valeur réelle d'entry.data.
            for zone_key in (CONF_ZONE_2, CONF_ZONE_3, CONF_ZONE_4, CONF_ZONE_5):
                if merged.get(zone_key) is None:
                    merged.pop(zone_key, None)
            return self.async_create_entry(title="", data=merged)

        return self.async_show_form(
            step_id="user",
            data_schema=build_advanced_schema(current, shared_defaults=_shared_config_defaults(getattr(self, "hass", None))),
        )
