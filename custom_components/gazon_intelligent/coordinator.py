from __future__ import annotations

from datetime import date, timedelta
from datetime import datetime, timezone
import asyncio
import logging
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    CONF_CAPTEUR_ETP,
    CONF_CAPTEUR_PLUIE_24H,
    CONF_CAPTEUR_PLUIE_DEMAIN,
    CONF_ENTITE_METEO,
    CONF_CAPTEUR_TEMPERATURE,
    CONF_CAPTEUR_HUMIDITE,
    CONF_CAPTEUR_HUMIDITE_SOL,
    CONF_CAPTEUR_VENT,
    CONF_CAPTEUR_ROSEE,
    CONF_CAPTEUR_HAUTEUR_GAZON,
    CONF_CAPTEUR_RETOUR_ARROSAGE,
    CONF_HAUTEUR_MAX_TONDEUSE_CM,
    CONF_HAUTEUR_MIN_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
    CONF_TYPE_SOL,
    DEFAULT_TYPE_SOL,
    WATERING_SESSION_END_GRACE_SECONDS,
    WATERING_SESSION_MIN_DURATION_SECONDS,
    WATERING_SESSION_MIN_SEGMENT_SECONDS,
)
from .decision import (
    build_decision_snapshot,
    compute_recent_watering_mm,
)
from .decision_models import DecisionResult
from .gazon_brain import GazonBrain
from .weather_adapter import WeatherAdapter

_LOGGER = logging.getLogger(__name__)


class GazonIntelligentCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinateur principal de l'intégration Gazon Intelligent."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise le coordinateur."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name="Gazon Intelligent",
            update_interval=timedelta(minutes=5),
        )
        self.entry = entry
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}.json")
        self._loaded = False
        self.brain = GazonBrain()
        self._auto_irrigation_task: asyncio.Task | None = None
        self._unsub_start_listener: CALLBACK_TYPE | None = None
        self._unsub_delayed_refresh: CALLBACK_TYPE | None = None
        self._unsub_zone_listeners: list[CALLBACK_TYPE] = []
        self._watering_session: dict[str, Any] | None = None
        self._unsub_watering_session_finalize: CALLBACK_TYPE | None = None
        self._zone_tracking_suspended = 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Récupère et calcule les données exposées par l'intégration."""
        if not self._loaded:
            await self._async_load_state()
            self._loaded = True

        weather_entity_id = self._get_conf(CONF_ENTITE_METEO)
        weather_profile = self._get_weather_profile(weather_entity_id)
        pluie_24h_sensor = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_24H))
        pluie_demain_sensor = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_DEMAIN))
        forecast_summary = await self._get_weather_forecast_summary(weather_entity_id)
        forecast_pluie_24h = forecast_summary.get("forecast_pluie_24h")
        forecast_pluie_demain = forecast_summary.get("forecast_pluie_demain")
        forecast_temperature_today = forecast_summary.get("forecast_temperature_today")
        if pluie_24h_sensor is not None:
            pluie_24h = pluie_24h_sensor
            pluie_24h_source = "capteur"
        else:
            pluie_24h = forecast_pluie_24h
            pluie_24h_source = "meteo_forecast" if pluie_24h is not None else "non disponible"
        if pluie_demain_sensor is not None:
            pluie_demain = pluie_demain_sensor
            pluie_demain_source = "capteur"
        else:
            pluie_demain = forecast_pluie_demain
            pluie_demain_source = "meteo_forecast" if pluie_demain is not None else "non disponible"

        temperature = self._get_float_state(self._get_conf(CONF_CAPTEUR_TEMPERATURE))
        if temperature is None:
            temperature = weather_profile.get("weather_temperature") or weather_profile.get("weather_apparent_temperature")
        if forecast_temperature_today is not None:
            try:
                forecast_temperature_today = float(forecast_temperature_today)
            except (TypeError, ValueError):
                forecast_temperature_today = None
        if forecast_temperature_today is not None:
            if temperature is None:
                temperature = forecast_temperature_today
            else:
                try:
                    temperature = max(float(temperature), forecast_temperature_today)
                except (TypeError, ValueError):
                    temperature = forecast_temperature_today
        etp_capteur = self._get_float_state(self._get_conf(CONF_CAPTEUR_ETP))
        humidite = self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE))
        if humidite is None:
            humidite = weather_profile.get("weather_humidity")
        humidite_sol = self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE_SOL))
        vent = self._get_float_state(self._get_conf(CONF_CAPTEUR_VENT))
        if vent is None:
            vent = weather_profile.get("weather_wind_speed")
        rosee = self._get_float_state(self._get_conf(CONF_CAPTEUR_ROSEE))
        if rosee is None:
            rosee = self._estimate_rosee(weather_profile, temperature, humidite)
        hauteur_gazon = self._get_float_state(self._get_conf(CONF_CAPTEUR_HAUTEUR_GAZON))
        retour_arrosage_sensor = self._get_float_state(self._get_conf(CONF_CAPTEUR_RETOUR_ARROSAGE))
        if retour_arrosage_sensor is not None and retour_arrosage_sensor > 0:
            retour_arrosage = retour_arrosage_sensor
        else:
            retour_arrosage_today = compute_recent_watering_mm(self.history, today=date.today(), days=0)
            retour_arrosage = retour_arrosage_today if retour_arrosage_today > 0 else None
        type_sol = self._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL
        hauteur_min_tondeuse_cm = self._get_float_conf(
            CONF_HAUTEUR_MIN_TONDEUSE_CM,
            DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
        )
        hauteur_max_tondeuse_cm = self._get_float_conf(
            CONF_HAUTEUR_MAX_TONDEUSE_CM,
            DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
        )
        snapshot = self.brain.compute_snapshot(
            today=date.today(),
            temperature=temperature,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            humidite=humidite,
            type_sol=type_sol,
            etp_capteur=etp_capteur,
            humidite_sol=humidite_sol,
            vent=vent,
            rosee=rosee,
            hauteur_gazon=hauteur_gazon,
            retour_arrosage=retour_arrosage,
            pluie_source=pluie_24h_source,
            pluie_demain_source=pluie_demain_source,
            weather_profile=weather_profile,
            hauteur_min_tondeuse_cm=hauteur_min_tondeuse_cm,
            hauteur_max_tondeuse_cm=hauteur_max_tondeuse_cm,
        )
        await self._async_save_state()

        return {
            "mode": snapshot["mode"],
            "phase_active": snapshot["phase_active"],
            "pluie_demain_source": pluie_demain_source,
            "objectif_mm": snapshot["objectif_mm"],
            "tonte_autorisee": snapshot["tonte_autorisee"],
            "tonte_statut": snapshot["tonte_statut"],
            "arrosage_recommande": snapshot["arrosage_recommande"],
            "type_arrosage": snapshot["type_arrosage"],
            "conseil_principal": snapshot["conseil_principal"],
            "action_recommandee": snapshot["action_recommandee"],
            "action_a_eviter": snapshot["action_a_eviter"],
            "niveau_action": snapshot["niveau_action"],
            "fenetre_optimale": snapshot["fenetre_optimale"],
            "risque_gazon": snapshot["risque_gazon"],
            "phase_dominante": snapshot["phase_dominante"],
            "phase_dominante_source": snapshot["phase_dominante_source"],
            "sous_phase": snapshot["sous_phase"],
            "sous_phase_detail": snapshot["sous_phase_detail"],
            "sous_phase_age_days": snapshot["sous_phase_age_days"],
            "sous_phase_progression": snapshot["sous_phase_progression"],
            "hauteur_tonte_recommandee_cm": snapshot.get("hauteur_tonte_recommandee_cm"),
            "hauteur_tonte_min_cm": snapshot.get("hauteur_tonte_min_cm"),
            "hauteur_tonte_max_cm": snapshot.get("hauteur_tonte_max_cm"),
        }

    @property
    def result(self) -> DecisionResult | None:
        """Retourne le résultat métier courant."""
        return self.brain.last_result

    @property
    def last_result(self) -> DecisionResult | None:
        """Alias de compatibilité pour le résultat métier courant."""
        return self.brain.last_result

    @property
    def mode(self) -> str:
        return self.brain.mode

    @mode.setter
    def mode(self, value: str) -> None:
        self.brain.mode = value

    @property
    def date_action(self) -> date | None:
        return self.brain.date_action

    @date_action.setter
    def date_action(self, value: date | None) -> None:
        self.brain.date_action = value

    @property
    def history(self) -> list[dict[str, Any]]:
        return self.brain.history

    @history.setter
    def history(self, value: list[dict[str, Any]]) -> None:
        self.brain.history = value

    @property
    def memory(self) -> dict[str, Any]:
        return self.brain.memory

    @memory.setter
    def memory(self, value: dict[str, Any]) -> None:
        self.brain.memory = value

    @property
    def products(self) -> dict[str, dict[str, Any]]:
        return self.brain.products

    @products.setter
    def products(self, value: dict[str, dict[str, Any]]) -> None:
        self.brain.products = value

    @property
    def soil_balance(self) -> dict[str, Any]:
        return self.brain.soil_balance

    @soil_balance.setter
    def soil_balance(self, value: dict[str, Any]) -> None:
        self.brain.soil_balance = value

    def _get_float_state(self, entity_id: str | None) -> float | None:
        """Retourne l'état float d'une entité Home Assistant."""
        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        if state is None:
            return None

        try:
            raw = str(state.state).strip().replace(",", ".")
            return float(raw)
        except (TypeError, ValueError):
            _LOGGER.debug("Impossible de convertir l'état de %s en float: %s", entity_id, state.state)
            return None

    def _get_float_conf(self, key: str, default: float | None = None) -> float | None:
        """Retourne une valeur de configuration numérique normalisée."""
        value = self._get_conf(key)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            _LOGGER.debug("Impossible de convertir la configuration %s en float: %s", key, value)
            return default

    def _get_weather_profile(self, weather_entity_id: str | None) -> dict[str, Any]:
        """Retourne les principaux attributs météo disponibles pour l'entité fournie."""
        if not weather_entity_id:
            return {}

        state = self.hass.states.get(weather_entity_id)
        if state is None:
            return {}

        return WeatherAdapter.profile_from_attributes(state.attributes)

    def _estimate_rosee(
        self,
        weather_profile: dict[str, Any],
        temperature: float | None,
        humidite: float | None,
    ) -> float | None:
        dew_point = weather_profile.get("weather_dew_point")
        if dew_point is not None and temperature is not None:
            try:
                if float(temperature) - float(dew_point) <= 2.0:
                    return 1.0
            except (TypeError, ValueError):
                pass
        if humidite is not None and humidite >= 88:
            return 0.8
        if weather_profile.get("weather_condition") in {"fog", "rainy", "pouring"}:
            return 1.0
        return None

    async def _get_weather_forecast_summary(self, weather_entity_id: str | None) -> dict[str, Any]:
        """Récupère les prévisions météo utiles du jour et de demain via weather.get_forecasts."""
        if not weather_entity_id:
            return {}

        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": weather_entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # pragma: no cover
            _LOGGER.debug("Echec weather.get_forecasts pour %s: %s", weather_entity_id, err)
            return {}

        if not isinstance(response, dict):
            return {}

        entity_data = response.get(weather_entity_id)
        if not isinstance(entity_data, dict):
            return {}

        forecasts = entity_data.get("forecast")
        if not isinstance(forecasts, list) or not forecasts:
            return {}

        return WeatherAdapter.forecast_summary(forecasts)

    async def async_set_mode(self, mode: str) -> None:
        """Définit le mode gazon."""
        if mode == "Normal":
            await self.async_set_normal()
            return
        await self.async_declare_intervention(mode)

    async def async_set_date_action(self, date_action: date | None = None) -> None:
        """Définit la date de la dernière intervention de phase."""
        self.brain.set_date_action(date_action)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_set_normal(self) -> None:
        """Réinitialise la phase active vers Normal (historique conservé)."""
        self.brain.set_normal()
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_declare_intervention(
        self,
        intervention: str,
        date_action: date | None = None,
        produit_id: str | None = None,
        produit: str | None = None,
        dose: str | None = None,
        zone: str | None = None,
        reapplication_after_days: int | None = None,
        note: str | None = None,
    ) -> None:
        self.brain.declare_intervention(
            intervention,
            date_action=date_action,
            produit_id=produit_id,
            produit=produit,
            dose=dose,
            zone=zone,
            reapplication_after_days=reapplication_after_days,
            note=note,
        )
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_record_mowing(self, date_action: date | None = None) -> None:
        self.brain.record_mowing(date_action)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_record_watering(
        self,
        date_action: date | None = None,
        objectif_mm: float | None = None,
        total_mm: float | None = None,
        zones: list[dict[str, Any]] | None = None,
        source: str = "service",
        detected_at: datetime | None = None,
    ) -> None:
        payload = self.brain.record_watering(
            date_action=date_action,
            objectif_mm=objectif_mm,
            total_mm=total_mm,
            zones=zones,
            source=source,
        )
        if detected_at is not None:
            payload["detected_at"] = detected_at.isoformat()
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_start_zone_monitoring(self) -> None:
        """Surveille les switches de zones pour reconstruire l'arrosage réel."""
        self._cancel_zone_monitoring()
        zone_ids = [entity_id for entity_id, _ in self._iter_zones_with_rate()]
        if not zone_ids:
            return
        self._unsub_zone_listeners = [
            async_track_state_change_event(self.hass, zone_ids, self._handle_zone_state_change)
        ]
        self._rebuild_watering_session_from_current_state()

    @callback
    def _handle_zone_state_change(self, event: Event) -> None:
        if self._zone_tracking_suspended > 0:
            return

        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if not entity_id or new_state is None:
            return

        new_is_on = str(new_state.state).lower() == "on"
        old_is_on = old_state is not None and str(old_state.state).lower() == "on"
        changed_at = getattr(new_state, "last_changed", None) or datetime.now(timezone.utc)

        if new_is_on:
            self._track_watering_zone_on(entity_id, changed_at)
            return

        if self._track_watering_zone_off(
            entity_id,
            changed_at,
            old_state.last_changed if old_is_on and old_state is not None else None,
        ):
            self._schedule_watering_session_finalize()

    def _ensure_watering_session(self, started_at: datetime) -> None:
        if self._watering_session is not None:
            return
        self._watering_session = {
            "started_at": started_at,
            "last_activity_at": started_at,
            "last_inactive_at": None,
            "zones": {},
            "active_zones": {},
            "zone_order": 0,
        }

    def _clear_watering_session(self) -> None:
        self._cancel_watering_session_finalize()
        self._watering_session = None

    def _cancel_watering_session_finalize(self) -> None:
        if self._unsub_watering_session_finalize:
            self._unsub_watering_session_finalize()
            self._unsub_watering_session_finalize = None

    def _schedule_watering_session_finalize(self) -> None:
        if self._watering_session is None:
            return
        self._cancel_watering_session_finalize()
        self._unsub_watering_session_finalize = async_call_later(
            self.hass,
            WATERING_SESSION_END_GRACE_SECONDS,
            self._async_finalize_watering_session,
        )

    def _rebuild_watering_session_from_current_state(self) -> None:
        """Reconstruit une session en cours à partir des zones déjà allumées."""
        if self._watering_session is not None:
            return

        active_zones: list[tuple[str, datetime]] = []
        now = datetime.now(timezone.utc)
        for entity_id, _ in self._iter_zones_with_rate():
            state = self.hass.states.get(entity_id)
            if state is None or str(state.state).lower() != "on":
                continue
            changed_at = getattr(state, "last_changed", None) or now
            if not isinstance(changed_at, datetime):
                changed_at = now
            active_zones.append((entity_id, changed_at))

        if not active_zones:
            return

        started_at = min(changed_at for _, changed_at in active_zones)
        self._watering_session = {
            "started_at": started_at,
            "last_activity_at": max(changed_at for _, changed_at in active_zones),
            "last_inactive_at": None,
            "zones": {},
            "active_zones": {},
            "zone_order": 0,
        }
        session = self._watering_session
        if session is None:
            return

        for order, (entity_id, changed_at) in enumerate(sorted(active_zones, key=lambda item: item[1]), start=1):
            rate_mm_h = max(0.0, self._get_zone_rate_mm_h(entity_id))
            session["zone_order"] = order
            session["active_zones"][entity_id] = changed_at
            session["zones"][entity_id] = {
                "order": order,
                "zone": entity_id,
                "entity_id": entity_id,
                "rate_mm_h": rate_mm_h,
                "duration_seconds": 0.0,
                "mm": 0.0,
                "started_at": changed_at,
                "ended_at": None,
            }

    def _build_watering_plan_from_state(self, plan_arrosage_entity_id: str) -> dict[str, Any] | None:
        """Lit le plan d'arrosage calculé depuis l'entité capteur."""
        plan_state = self.hass.states.get(plan_arrosage_entity_id)
        if plan_state is None:
            return None
        attributes = plan_state.attributes if isinstance(plan_state.attributes, dict) else {}
        zones = attributes.get("zones")
        if not isinstance(zones, list) or not zones:
            return None

        try:
            passages = max(1, int(attributes.get("passages", 1)))
        except (TypeError, ValueError):
            passages = 1
        try:
            pause_minutes = max(0, int(attributes.get("pause_between_passages_minutes", 0)))
        except (TypeError, ValueError):
            pause_minutes = 0

        normalized_zones: list[dict[str, Any]] = []
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            entity_id = str(zone.get("zone") or zone.get("entity_id") or "").strip()
            if not entity_id:
                continue
            duration_seconds = zone.get("duration_seconds")
            if duration_seconds is None:
                duration_min = zone.get("duration_min")
                try:
                    duration_seconds = float(duration_min) * 60.0 if duration_min is not None else None
                except (TypeError, ValueError):
                    duration_seconds = None
            try:
                duration_seconds = float(duration_seconds)
            except (TypeError, ValueError):
                continue
            if duration_seconds <= 0:
                continue
            normalized_zones.append(
                {
                    "zone": entity_id,
                    "entity_id": entity_id,
                    "rate_mm_h": zone.get("rate_mm_h"),
                    "duration_seconds": duration_seconds,
                    "duration_min": zone.get("duration_min"),
                    "mm": zone.get("mm"),
                }
            )

        if not normalized_zones:
            return None

        return {
            "objective_mm": attributes.get("objective_mm"),
            "total_duration_min": attributes.get("total_duration_min"),
            "zones": normalized_zones,
            "passages": passages,
            "pause_between_passages_minutes": pause_minutes,
        }

    def _track_watering_zone_on(self, entity_id: str, changed_at: datetime) -> None:
        self._ensure_watering_session(changed_at)
        session = self._watering_session
        if session is None:
            return
        if entity_id in session["active_zones"]:
            session["active_zones"][entity_id] = changed_at
            session["last_activity_at"] = changed_at
            return

        session["active_zones"][entity_id] = changed_at
        session["last_activity_at"] = changed_at
        zone_record = session["zones"].get(entity_id)
        if zone_record is None:
            session["zone_order"] += 1
            zone_record = {
                "order": session["zone_order"],
                "zone": entity_id,
                "entity_id": entity_id,
                "rate_mm_h": max(0.0, self._get_zone_rate_mm_h(entity_id)),
                "duration_seconds": 0.0,
                "mm": 0.0,
                "started_at": changed_at,
                "ended_at": None,
            }
            session["zones"][entity_id] = zone_record
        else:
            if zone_record.get("started_at") is None:
                zone_record["started_at"] = changed_at

        self._cancel_watering_session_finalize()

    def _track_watering_zone_off(
        self,
        entity_id: str,
        changed_at: datetime,
        fallback_start: datetime | None = None,
    ) -> bool:
        session = self._watering_session
        if session is None:
            if fallback_start is None:
                return False
            self._ensure_watering_session(fallback_start)
            session = self._watering_session
            if session is None:
                return False
            session["active_zones"][entity_id] = fallback_start
            zone_record = session["zones"].get(entity_id)
            if zone_record is None:
                session["zone_order"] += 1
                zone_record = {
                    "order": session["zone_order"],
                    "zone": entity_id,
                    "entity_id": entity_id,
                    "rate_mm_h": max(0.0, self._get_zone_rate_mm_h(entity_id)),
                    "duration_seconds": 0.0,
                    "mm": 0.0,
                    "started_at": fallback_start,
                    "ended_at": None,
                }
                session["zones"][entity_id] = zone_record

        start = session["active_zones"].pop(entity_id, None)
        if start is None:
            return False

        rate_mm_h = max(0.0, self._get_zone_rate_mm_h(entity_id))
        if rate_mm_h <= 0:
            return False

        duration_seconds = max((changed_at - start).total_seconds(), 0.0)
        if duration_seconds < WATERING_SESSION_MIN_SEGMENT_SECONDS:
            if not session["active_zones"]:
                session["last_inactive_at"] = changed_at
                return True
            return False

        zone_record = session["zones"].setdefault(
            entity_id,
            {
                "order": session["zone_order"] + 1,
                "zone": entity_id,
                "entity_id": entity_id,
                "rate_mm_h": rate_mm_h,
                "duration_seconds": 0.0,
                "mm": 0.0,
                "started_at": start,
                "ended_at": None,
            },
        )
        if zone_record.get("order") is None:
            session["zone_order"] += 1
            zone_record["order"] = session["zone_order"]
        elif zone_record["order"] > session["zone_order"]:
            session["zone_order"] = int(zone_record["order"])

        zone_record["rate_mm_h"] = rate_mm_h
        zone_record["started_at"] = zone_record.get("started_at") or start
        zone_record["ended_at"] = changed_at
        zone_record["duration_seconds"] = float(zone_record.get("duration_seconds", 0.0)) + duration_seconds
        zone_record["mm"] = float(zone_record.get("mm", 0.0)) + ((rate_mm_h * duration_seconds) / 3600.0)
        session["last_activity_at"] = changed_at
        if not session["active_zones"]:
            session["last_inactive_at"] = changed_at
            return True
        return False

    def _build_watering_session_payload(self) -> dict[str, Any] | None:
        session = self._watering_session
        if session is None:
            return
        if session["active_zones"]:
            return None

        ended_at = session.get("last_inactive_at")
        started_at = session.get("started_at")
        if not isinstance(ended_at, datetime) or not isinstance(started_at, datetime):
            return None

        session_duration_seconds = max((ended_at - started_at).total_seconds(), 0.0)
        if session_duration_seconds < WATERING_SESSION_MIN_DURATION_SECONDS:
            return None

        zones = []
        for zone_record in sorted(session["zones"].values(), key=lambda item: int(item.get("order", 0))):
            if not isinstance(zone_record, dict):
                continue
            duration_seconds = float(zone_record.get("duration_seconds", 0.0))
            mm = float(zone_record.get("mm", 0.0))
            if duration_seconds < WATERING_SESSION_MIN_SEGMENT_SECONDS or mm <= 0:
                continue
            duration_min = duration_seconds / 60.0
            zones.append(
                {
                    "order": int(zone_record.get("order", len(zones) + 1)),
                    "zone": zone_record.get("zone") or zone_record.get("entity_id"),
                    "entity_id": zone_record.get("entity_id") or zone_record.get("zone"),
                    "rate_mm_h": round(max(0.0, float(zone_record.get("rate_mm_h", 0.0))), 1),
                    "duration_min": round(max(0.0, duration_min), 1),
                    "duration_seconds": int(max(0.0, duration_seconds)),
                    "mm": round(mm, 1),
                }
            )

        if not zones:
            return None

        total_mm = round(sum(float(zone["mm"]) for zone in zones), 1)
        if total_mm <= 0:
            return None

        return {
            "date_action": ended_at.date(),
            "objectif_mm": total_mm,
            "total_mm": total_mm,
            "zones": zones,
            "source": "zone_session",
        }

    async def _async_finalize_watering_session(self, now) -> None:
        self._unsub_watering_session_finalize = None
        session = self._watering_session
        if session is None:
            return
        if session.get("active_zones"):
            return
        ended_at = session.get("last_inactive_at")
        if not isinstance(ended_at, datetime):
            return
        if not isinstance(now, datetime):
            now = datetime.now(timezone.utc)
        elapsed = (now - ended_at).total_seconds()
        if elapsed < WATERING_SESSION_END_GRACE_SECONDS:
            self._schedule_watering_session_finalize()
            return

        payload = self._build_watering_session_payload()
        self._clear_watering_session()
        if payload is None:
            return

        await self.async_record_watering(
            payload["date_action"],
            objectif_mm=payload["objectif_mm"],
            total_mm=payload["total_mm"],
            zones=payload["zones"],
            source=payload["source"],
            detected_at=ended_at,
        )

    async def async_register_product(
        self,
        product_id: str,
        nom: str,
        type_produit: str,
        dose_conseillee: str | None = None,
        reapplication_after_days: int | None = None,
        delai_avant_tonte_jours: int | None = None,
        phase_compatible: str | None = None,
        note: str | None = None,
    ) -> None:
        self.brain.register_product(
            product_id,
            nom,
            type_produit,
            dose_conseillee=dose_conseillee,
            reapplication_after_days=reapplication_after_days,
            delai_avant_tonte_jours=delai_avant_tonte_jours,
            phase_compatible=phase_compatible,
            note=note,
        )
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_remove_product(self, product_id: str) -> None:
        self.brain.remove_product(product_id)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_start_manual_irrigation(self, objectif_mm: float) -> None:
        """Déclenche une demande d'arrosage manuel via un événement HA."""
        await self.async_record_watering(objectif_mm=objectif_mm, total_mm=objectif_mm, source="manual")
        self.hass.bus.async_fire(
            "gazon_intelligent_manual_irrigation_requested",
            {
                "objectif_mm": float(objectif_mm),
                "mode": self.mode,
                "date_action": self.date_action.isoformat() if self.date_action else None,
            },
        )

    def _iter_zones_with_rate(self):
        """Itère sur les zones configurées avec leur débit converti en mm/min."""
        data = self.entry.data
        opts = self.entry.options
        for idx in range(1, 6):
            entity_id = opts.get(f"zone_{idx}", data.get(f"zone_{idx}"))
            rate_h = opts.get(f"debit_zone_{idx}", data.get(f"debit_zone_{idx}"))
            rate_mm_min = self._get_zone_rate_mm_min(entity_id, rate_h)
            if entity_id and rate_mm_min > 0:
                yield entity_id, rate_mm_min

    def _get_zone_rate_mm_min(self, entity_id: str | None, rate_h: Any | None = None) -> float:
        if not entity_id:
            return 0.0
        if rate_h is None:
            for idx in range(1, 6):
                if entity_id == self._get_conf(f"zone_{idx}"):
                    rate_h = self._get_conf(f"debit_zone_{idx}")
                    break
        try:
            return float(rate_h) / 60.0
        except (TypeError, ValueError):
            return 0.0

    def _get_zone_rate_mm_h(self, entity_id: str | None, rate_h: Any | None = None) -> float:
        if not entity_id:
            return 0.0
        if rate_h is None:
            for idx in range(1, 6):
                if entity_id == self._get_conf(f"zone_{idx}"):
                    rate_h = self._get_conf(f"debit_zone_{idx}")
                    break
        try:
            return float(rate_h or 0.0)
        except (TypeError, ValueError):
            return 0.0

    async def async_start_auto_irrigation(
        self,
        objectif_mm: float | None,
        plan_arrosage_entity_id: str | None = None,
    ) -> None:
        """Arrose automatiquement chaque zone en séquence selon le débit renseigné."""
        if self._auto_irrigation_task and not self._auto_irrigation_task.done():
            raise HomeAssistantError(
                "Un arrosage automatique est déjà en cours."
            )

        plan = None
        if plan_arrosage_entity_id:
            plan = self._build_watering_plan_from_state(plan_arrosage_entity_id)
            if plan is None:
                raise HomeAssistantError(
                    "Le plan d'arrosage est vide ou invalide."
                )
        else:
            objectif = float(objectif_mm) if objectif_mm is not None else float(
                self.data.get("objectif_mm", 0.0)
            )
            zones = list(self._iter_zones_with_rate())
            if not zones:
                raise HomeAssistantError(
                    "Aucune zone d'arrosage valide n'est configurée (zone + débit mm/h)."
                )

        async def _turn_off_zone(entity_id: str) -> None:
            try:
                await asyncio.shield(
                    self.hass.services.async_call(
                        "switch",
                        "turn_off",
                        {"entity_id": entity_id},
                        blocking=True,
                    )
                )
            except Exception as err:  # pragma: no cover - best effort cleanup
                _LOGGER.debug("Echec turn_off pour %s: %s", entity_id, err)

        async def _run_legacy_sequence():
            session_zones: list[dict[str, Any]] = []
            try:
                self._clear_watering_session()
                self._zone_tracking_suspended += 1
                for order, (entity_id, rate) in enumerate(zones, start=1):
                    if rate <= 0:
                        continue
                    duration = objectif / rate
                    if duration <= 0:
                        continue
                    await self.hass.services.async_call(
                        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
                    )
                    try:
                        await asyncio.sleep(max(duration, 0) * 60)
                    finally:
                        await _turn_off_zone(entity_id)
                    session_zones.append(
                        {
                            "order": order,
                            "zone": entity_id,
                            "entity_id": entity_id,
                            "rate_mm_h": rate * 60.0,
                            "duration_min": duration,
                            "mm": round(duration * rate, 1),
                        }
                    )
                if session_zones:
                    await self.async_record_watering(
                        date.today(),
                        objectif_mm=objectif,
                        zones=session_zones,
                        source="auto_irrigation",
                    )
            finally:
                self._zone_tracking_suspended = max(0, self._zone_tracking_suspended - 1)
                self._auto_irrigation_task = None

        async def _run_plan_sequence():
            assert plan is not None
            zones = list(plan["zones"])
            passages = max(1, int(plan["passages"]))
            pause_minutes = max(0, int(plan["pause_between_passages_minutes"]))
            started_zones: list[str] = []
            try:
                for passage_index in range(passages):
                    for zone in zones:
                        entity_id = str(zone["zone"])
                        duration_seconds = zone.get("duration_seconds")
                        try:
                            duration_seconds = float(duration_seconds)
                        except (TypeError, ValueError):
                            continue
                        if duration_seconds <= 0:
                            continue
                        await self.hass.services.async_call(
                            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
                        )
                        started_zones.append(entity_id)
                        try:
                            await asyncio.sleep(max(1, int(round(duration_seconds / passages))))
                        finally:
                            await _turn_off_zone(entity_id)
                    if passage_index < passages - 1 and pause_minutes > 0:
                        await asyncio.sleep(pause_minutes * 60)
            finally:
                cleanup_targets = list(dict.fromkeys(started_zones or [str(zone["zone"]) for zone in zones]))
                for entity_id in reversed(cleanup_targets):
                    await _turn_off_zone(entity_id)
                self._auto_irrigation_task = None

        sequence = _run_plan_sequence if plan is not None else _run_legacy_sequence
        self._auto_irrigation_task = self.hass.async_create_task(
            sequence(), "gazon_intelligent_auto_irrigation_sequence"
        )

    def schedule_post_start_refresh(self, delay_seconds: int = 30) -> None:
        """Planifie un refresh peu après le démarrage de Home Assistant."""
        self._cancel_post_start_refresh()

        @callback
        def _on_started(_event: Event | None = None) -> None:
            self._unsub_start_listener = None
            self._unsub_delayed_refresh = async_call_later(
                self.hass, delay_seconds, self._async_delayed_refresh
            )

        if self.hass.is_running:
            _on_started()
        else:
            self._unsub_start_listener = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _on_started
            )

    async def _async_delayed_refresh(self, _now) -> None:
        """Déclenche un refresh différé après redémarrage."""
        self._unsub_delayed_refresh = None
        await self.async_request_refresh()

    def _cancel_post_start_refresh(self) -> None:
        """Annule les callbacks de refresh post-démarrage."""
        if self._unsub_start_listener:
            self._unsub_start_listener()
            self._unsub_start_listener = None
        if self._unsub_delayed_refresh:
            self._unsub_delayed_refresh()
            self._unsub_delayed_refresh = None

    def _cancel_zone_monitoring(self) -> None:
        for unsub in self._unsub_zone_listeners:
            unsub()
        self._unsub_zone_listeners.clear()
        self._clear_watering_session()

    async def async_shutdown(self) -> None:
        """Nettoie les tâches en cours à la fermeture de l'intégration."""
        self._cancel_post_start_refresh()
        self._cancel_zone_monitoring()
        if self._auto_irrigation_task and not self._auto_irrigation_task.done():
            self._auto_irrigation_task.cancel()
            try:
                await self._auto_irrigation_task
            except asyncio.CancelledError:
                pass
        self._auto_irrigation_task = None

    def _get_conf(self, key: str) -> Any:
        """Récupère la valeur de configuration (options > data)."""
        return self.entry.options.get(key, self.entry.data.get(key))

    async def async_update_config(self, updates: dict[str, Any]) -> None:
        """Met à jour les options de config en gardant la valeur courante comme base."""
        new_options = dict(self.entry.options)
        new_options.update(updates)
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        await self.async_start_zone_monitoring()
        await self.async_request_refresh()

    def get_used_entities_attributes(self) -> dict[str, Any] | None:
        """Expose un contexte compact pour les attributs visibles."""
        pluie_demain_source = None
        if self.data:
            pluie_demain_source = self.data.get("pluie_demain_source")
            if pluie_demain_source == "indisponible":
                pluie_demain_source = "non disponible"
        phase_dominante_source = None
        if self.data:
            phase_dominante_source = self.data.get("phase_dominante_source")
        attrs = {
            "configuration": {
                "type_sol": self._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL,
            },
            "pluie_demain_source": pluie_demain_source,
            "phase_dominante_source": phase_dominante_source,
        }
        clean = {key: value for key, value in attrs.items() if value not in (None, "", {}, [])}
        configuration = clean.get("configuration")
        if isinstance(configuration, dict):
            configuration = {k: v for k, v in configuration.items() if v not in (None, "", {}, [])}
            if configuration:
                clean["configuration"] = configuration
            else:
                clean.pop("configuration", None)
        return clean or None

    async def _async_load_state(self) -> None:
        """Charge l'état persistant (mode, date_action)."""
        data = await self._store.async_load() or {}
        self.brain.load_state(data)

    async def _async_save_state(self) -> None:
        """Sauvegarde l'état persistant (mode, date_action)."""
        await self._store.async_save(self.brain.dump_state())
