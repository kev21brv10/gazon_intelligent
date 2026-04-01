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
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    DEFAULT_AUTO_IRRIGATION_ENABLED,
    APPLICATION_TYPE_FOLIAIRE,
    APPLICATION_TYPE_SOL,
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
from .memory import compute_application_state
from .weather_adapter import WeatherAdapter

_LOGGER = logging.getLogger(__name__)

AUTO_IRRIGATION_AUTO_SOURCES = {
    "auto_irrigation",
    "application_technique",
    "application_technique_auto",
}

AUTO_IRRIGATION_CHECK_INTERVAL = timedelta(minutes=2)


class GazonIntelligentCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinateur principal de l'intégration Gazon Intelligent."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise le coordinateur."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name="Gazon Intelligent",
            update_interval=timedelta(minutes=2),
        )
        self.entry = entry
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}.json")
        self._loaded = False
        self.brain = GazonBrain()
        self._auto_irrigation_task: asyncio.Task | None = None
        self._auto_irrigation_scheduler_task: asyncio.Task | None = None
        self._unsub_start_listener: CALLBACK_TYPE | None = None
        self._unsub_delayed_refresh: CALLBACK_TYPE | None = None
        self._unsub_auto_irrigation_monitor: CALLBACK_TYPE | None = None
        self._unsub_source_listeners: list[CALLBACK_TYPE] = []
        self._unsub_zone_listeners: list[CALLBACK_TYPE] = []
        self._source_refresh_task: asyncio.Task | None = None
        self._auto_irrigation_monitor_task: asyncio.Task | None = None
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
        forecast_pluie_j2 = forecast_summary.get("forecast_pluie_j2")
        forecast_pluie_3j = forecast_summary.get("forecast_pluie_3j")
        forecast_probabilite_max_3j = forecast_summary.get("forecast_probabilite_max_3j")
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

        temperature_source = "capteur"
        temperature = self._get_float_state(self._get_conf(CONF_CAPTEUR_TEMPERATURE))
        if temperature is None:
            weather_temperature = weather_profile.get("weather_temperature")
            weather_apparent_temperature = weather_profile.get("weather_apparent_temperature")
            if weather_temperature is not None:
                temperature = weather_temperature
                temperature_source = "weather"
            elif weather_apparent_temperature is not None:
                temperature = weather_apparent_temperature
                temperature_source = "weather"
        if forecast_temperature_today is not None:
            try:
                forecast_temperature_today = float(forecast_temperature_today)
            except (TypeError, ValueError):
                forecast_temperature_today = None
        if forecast_temperature_today is not None:
            if temperature is None:
                temperature = forecast_temperature_today
                temperature_source = "meteo_forecast"
        elif temperature is None:
            temperature_source = "non disponible"
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
            forecast_temperature_today=forecast_temperature_today,
            temperature_source=temperature_source,
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
            pluie_j2=forecast_pluie_j2,
            pluie_3j=forecast_pluie_3j,
            pluie_probabilite_max_3j=forecast_probabilite_max_3j,
        )
        _LOGGER.debug("Gazon Intelligent V2 observability: %s", self._build_observability_payload(snapshot))
        await self._async_save_state()
        self._maybe_schedule_auto_irrigation(snapshot)

        return {
            "mode": snapshot["mode"],
            "phase_active": snapshot["phase_active"],
            "pluie_demain_source": pluie_demain_source,
            "temperature_source": temperature_source,
            "forecast_temperature_today": forecast_temperature_today,
            "forecast_pluie_j2": forecast_pluie_j2,
            "forecast_pluie_3j": forecast_pluie_3j,
            "forecast_probabilite_max_3j": forecast_probabilite_max_3j,
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
            "derniere_application": snapshot.get("derniere_application"),
            "application_type": snapshot.get("application_type"),
            "application_requires_watering_after": snapshot.get("application_requires_watering_after"),
            "application_post_watering_mm": snapshot.get("application_post_watering_mm"),
            "application_irrigation_block_hours": snapshot.get("application_irrigation_block_hours"),
            "application_label_notes": snapshot.get("application_label_notes"),
            "application_block_until": snapshot.get("application_block_until"),
            "application_block_active": snapshot.get("application_block_active"),
            "application_post_watering_pending": snapshot.get("application_post_watering_pending"),
            "application_post_watering_remaining_mm": snapshot.get("application_post_watering_remaining_mm"),
            "auto_irrigation_enabled": snapshot.get(
                "auto_irrigation_enabled",
                self.auto_irrigation_enabled,
            ),
            "feedback_observation": snapshot.get("feedback_observation"),
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
    def auto_irrigation_enabled(self) -> bool:
        memory = self.memory
        if isinstance(memory, dict):
            return bool(
                memory.get("auto_irrigation_enabled", DEFAULT_AUTO_IRRIGATION_ENABLED)
            )
        return DEFAULT_AUTO_IRRIGATION_ENABLED

    async def async_set_auto_irrigation_enabled(self, enabled: bool) -> None:
        """Autorise ou bloque l'arrosage automatique globalement."""
        self.memory["auto_irrigation_enabled"] = bool(enabled)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_set_selected_product(self, product_id: str | None) -> None:
        """Sélectionne le produit d'intervention courant."""
        self.brain.selected_product_id = product_id
        await self._async_save_state()
        await self.async_request_refresh()

    @property
    def products(self) -> dict[str, dict[str, Any]]:
        return self.brain.products

    @products.setter
    def products(self, value: dict[str, dict[str, Any]]) -> None:
        self.brain.products = value

    @property
    def selected_product_id(self) -> str | None:
        return self.brain.selected_product_id

    @selected_product_id.setter
    def selected_product_id(self, value: str | None) -> None:
        self.brain.selected_product_id = value

    @property
    def selected_product_name(self) -> str | None:
        return self.brain.selected_product_name

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

    def _extract_block_reason(self, snapshot: dict[str, Any]) -> str | None:
        reason = str(snapshot.get("block_reason") or snapshot.get("raison_decision") or "").strip()
        if not reason:
            return None
        lowered = reason.lower()
        for marker in (
            "pluie prévue suffisante",
            "pluie prévue",
            "humidité élevée",
            "garde-fou hebdomadaire",
            "mode bloqué",
            "arrosage bloqué",
            "application",
        ):
            if marker in lowered:
                return marker
        return reason

    def _build_observability_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        today = date.today()
        payload = {
            "phase": snapshot.get("phase_active"),
            "sous_phase": snapshot.get("sous_phase"),
            "type_arrosage": snapshot.get("type_arrosage"),
            "deficit_brut_mm": snapshot.get("deficit_brut_mm"),
            "deficit_mm_ajuste": snapshot.get("deficit_mm_ajuste"),
            "mm_cible": snapshot.get("mm_cible"),
            "mm_final": snapshot.get("mm_final"),
            "mm_requested": snapshot.get("mm_requested"),
            "mm_applied": snapshot.get("mm_applied"),
            "mm_detected": snapshot.get("mm_detected"),
            "mm_applied_today": round(compute_recent_watering_mm(self.history, today=today, days=0), 1),
            "mm_detected_24h": round(compute_recent_watering_mm(self.history, today=today, days=1), 1),
            "mm_detected_48h": round(compute_recent_watering_mm(self.history, today=today, days=2), 1),
            "heat_stress_level": snapshot.get("heat_stress_level"),
            "heat_stress_phase": snapshot.get("heat_stress_phase"),
            "confidence_level": snapshot.get("niveau_confiance"),
            "confidence_score": snapshot.get("confidence_score"),
            "block_reason": self._extract_block_reason(snapshot),
            "weekly_guardrail_mm_min": snapshot.get("weekly_guardrail_mm_min"),
            "weekly_guardrail_mm_max": snapshot.get("weekly_guardrail_mm_max"),
            "soil_profile": snapshot.get("soil_profile"),
            "soil_retention_factor": snapshot.get("soil_retention_factor"),
            "soil_drainage_factor": snapshot.get("soil_drainage_factor"),
            "soil_infiltration_factor": snapshot.get("soil_infiltration_factor"),
            "soil_need_factor": snapshot.get("soil_need_factor"),
            "feedback_observation": self.memory.get("feedback_observation"),
        }
        return {key: value for key, value in payload.items() if value is not None}

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
        application_type: str | None = None,
        application_requires_watering_after: bool | None = None,
        application_post_watering_mm: float | None = None,
        application_irrigation_block_hours: float | None = None,
        application_irrigation_delay_minutes: float | None = None,
        application_irrigation_mode: str | None = None,
        application_label_notes: str | None = None,
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
            application_type=application_type,
            application_requires_watering_after=application_requires_watering_after,
            application_post_watering_mm=application_post_watering_mm,
            application_irrigation_block_hours=application_irrigation_block_hours,
            application_irrigation_delay_minutes=application_irrigation_delay_minutes,
            application_irrigation_mode=application_irrigation_mode,
            application_label_notes=application_label_notes,
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

    def _source_entity_ids(self) -> list[str]:
        entity_ids: list[str] = []
        weather_entity_id = self._get_conf(CONF_ENTITE_METEO)
        if isinstance(weather_entity_id, str) and weather_entity_id:
            entity_ids.append(weather_entity_id)
        for key in (
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
        ):
            entity_id = self._get_conf(key)
            if isinstance(entity_id, str) and entity_id:
                entity_ids.append(entity_id)
        return list(dict.fromkeys(entity_ids))

    async def async_start_source_monitoring(self) -> None:
        """Surveille les capteurs sources pour rafraîchir les entités dérivées."""
        self._cancel_source_monitoring()
        entity_ids = self._source_entity_ids()
        if not entity_ids:
            return
        self._unsub_source_listeners = [
            async_track_state_change_event(self.hass, entity_ids, self._handle_source_state_change)
        ]

    async def async_start_auto_irrigation_monitoring(self) -> None:
        """Surveille l'état courant pour déclencher l'arrosage automatique sans dépendre d'un refresh."""
        self._cancel_auto_irrigation_monitoring()
        self._unsub_auto_irrigation_monitor = async_track_time_interval(
            self.hass,
            self._handle_auto_irrigation_monitor_tick,
            AUTO_IRRIGATION_CHECK_INTERVAL,
        )

    @callback
    def _handle_auto_irrigation_monitor_tick(self, _now: datetime) -> None:
        if self._auto_irrigation_monitor_task and not self._auto_irrigation_monitor_task.done():
            return

        self._auto_irrigation_monitor_task = self.hass.async_create_task(
            self._async_auto_irrigation_monitor_tick(),
            "gazon_intelligent_auto_irrigation_monitor",
        )

        def _clear_auto_irrigation_monitor_task(task: asyncio.Task) -> None:
            if self._auto_irrigation_monitor_task is task:
                self._auto_irrigation_monitor_task = None

        self._auto_irrigation_monitor_task.add_done_callback(_clear_auto_irrigation_monitor_task)

    async def _async_auto_irrigation_monitor_tick(self) -> None:
        snapshot = dict(self.data) if isinstance(self.data, dict) else {}
        if not snapshot:
            return
        self._maybe_schedule_auto_irrigation(snapshot)

    @callback
    def _handle_source_state_change(self, event: Event) -> None:
        if self._source_refresh_task and not self._source_refresh_task.done():
            return

        self._source_refresh_task = self.hass.async_create_task(
            self.async_request_refresh(),
            "gazon_intelligent_source_refresh",
        )

        def _clear_source_refresh_task(task: asyncio.Task) -> None:
            if self._source_refresh_task is task:
                self._source_refresh_task = None

        self._source_refresh_task.add_done_callback(_clear_source_refresh_task)

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
            "planned_total_seconds": 0.0,
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
        session["planned_total_seconds"] = self._estimate_watering_session_total_seconds(session)

    def _estimate_watering_session_total_seconds(self, session: dict[str, Any] | None = None) -> float:
        """Estime la durée totale planifiée d'une session active."""
        total_seconds = 0.0
        hass = getattr(self, "hass", None)
        states = getattr(hass, "states", None)
        plan = None
        if states is not None:
            plan = self._build_watering_plan_from_state(self._plan_arrosage_entity_id())
        if isinstance(plan, dict):
            zones = plan.get("zones")
            if isinstance(zones, list) and zones:
                for zone in zones:
                    if not isinstance(zone, dict):
                        continue
                    duration_seconds = zone.get("duration_seconds")
                    try:
                        duration_seconds = float(duration_seconds)
                    except (TypeError, ValueError):
                        continue
                    if duration_seconds > 0:
                        total_seconds += duration_seconds
                try:
                    passages = max(1, int(plan.get("passages", 1)))
                except (TypeError, ValueError):
                    passages = 1
                try:
                    pause_minutes = max(0, int(plan.get("pause_between_passages_minutes", 0)))
                except (TypeError, ValueError):
                    pause_minutes = 0
                if total_seconds > 0:
                    total_seconds *= passages
                    if passages > 1 and pause_minutes > 0:
                        total_seconds += pause_minutes * 60.0 * (passages - 1)
                    if total_seconds > 0:
                        return total_seconds

            total_duration_min = plan.get("total_duration_min")
            try:
                total_seconds = max(0.0, float(total_duration_min or 0.0)) * 60.0
            except (TypeError, ValueError):
                total_seconds = 0.0
            if total_seconds > 0:
                try:
                    passages = max(1, int(plan.get("passages", 1)))
                except (TypeError, ValueError):
                    passages = 1
                try:
                    pause_minutes = max(0, int(plan.get("pause_between_passages_minutes", 0)))
                except (TypeError, ValueError):
                    pause_minutes = 0
                if passages > 1 and pause_minutes > 0:
                    total_seconds += pause_minutes * 60.0 * (passages - 1)
                return total_seconds

        if isinstance(session, dict):
            zones = session.get("zones")
            if isinstance(zones, dict) and zones:
                for zone in zones.values():
                    if not isinstance(zone, dict):
                        continue
                    duration_seconds = zone.get("duration_seconds")
                    try:
                        duration_seconds = float(duration_seconds)
                    except (TypeError, ValueError):
                        continue
                    if duration_seconds > 0:
                        total_seconds += duration_seconds
                if total_seconds > 0:
                    return total_seconds

        return 0.0

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

    def _plan_type_for_zone_count(self, zone_count: int) -> str:
        if zone_count <= 0:
            return "no_plan"
        if zone_count > 1:
            return "multi_zone"
        return "single_zone"

    def _build_watering_plan_summary_for_user_action(
        self,
        objectif_mm: float | None = None,
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(plan, dict):
            zones = plan.get("zones")
            if not isinstance(zones, list):
                zones = []
            zone_count = plan.get("zone_count")
            try:
                zone_count = int(zone_count) if zone_count is not None else len(zones)
            except (TypeError, ValueError):
                zone_count = len(zones)
            passages = plan.get("passages", 1)
            try:
                passages = max(1, int(passages))
            except (TypeError, ValueError):
                passages = 1
            summary = dict(plan)
            summary["zone_count"] = zone_count
            summary["passages"] = passages
            summary["fractionation"] = passages > 1
            summary["plan_type"] = self._plan_type_for_zone_count(zone_count)
            return summary

        objective = float(
            objectif_mm if objectif_mm is not None else self.data.get("objectif_mm") or 0.0
        )
        passages = self.data.get("watering_passages") or 1
        pause_minutes = self.data.get("watering_pause_minutes") or 0
        try:
            passages = max(1, int(passages))
        except (TypeError, ValueError):
            passages = 1
        try:
            pause_minutes = max(0, int(pause_minutes))
        except (TypeError, ValueError):
            pause_minutes = 0

        zones: list[dict[str, Any]] = []
        max_minutes = 0.0
        min_minutes = 99999.0
        if objective > 0:
            for entity_id, rate_mm_min in self._iter_zones_with_rate():
                rate_mm_h = rate_mm_min * 60.0
                if rate_mm_h <= 0:
                    continue
                duration_min = (objective / rate_mm_h) * 60.0
                if duration_min <= 0:
                    continue
                rounded_duration = max(0.5, round(duration_min * 2.0) / 2.0)
                rounded_duration = min(rounded_duration, 180.0)
                max_minutes = max(max_minutes, rounded_duration)
                min_minutes = min(min_minutes, rounded_duration)
                zones.append(
                    {
                        "zone": entity_id,
                        "entity_id": entity_id,
                        "rate_mm_h": round(rate_mm_h, 1),
                        "objectif_mm": round(objective, 1),
                        "duration_min": round(rounded_duration, 1),
                        "duration_seconds": int(round(rounded_duration * 60.0)),
                    }
                )

        if not zones or objective <= 0:
            return {
                "objective_mm": round(max(0.0, objective), 1),
                "zones": [],
                "zone_count": 0,
                "total_duration_min": 0.0,
                "min_duration_min": 0.0,
                "max_duration_min": 0.0,
                "fractionation": False,
                "passages": passages,
                "pause_between_passages_minutes": pause_minutes,
                "source": "no_plan",
                "plan_type": "no_plan",
            }

        total_duration_min = round(sum(float(zone["duration_min"]) for zone in zones), 1)
        return {
            "objective_mm": round(objective, 1),
            "zones": zones,
            "zone_count": len(zones),
            "total_duration_min": total_duration_min,
            "min_duration_min": round(min_minutes, 1),
            "max_duration_min": round(max_minutes, 1),
            "fractionation": passages > 1,
            "passages": passages,
            "pause_between_passages_minutes": pause_minutes,
            "source": "calculated_from_objective",
            "plan_type": self._plan_type_for_zone_count(len(zones)),
        }

    def _plan_arrosage_entity_id(self) -> str:
        """Résout l'entité du plan d'arrosage courant."""
        fallback = "sensor.gazon_intelligent_plan_d_arrosage"
        unique_id = f"{self.entry.entry_id}_plan_arrosage"
        try:
            from homeassistant.helpers import entity_registry as er  # local import for HA runtime

            registry = er.async_get(self.hass)
            get_entity_id = getattr(registry, "async_get_entity_id", None)
            if callable(get_entity_id):
                entity_id = get_entity_id("sensor", DOMAIN, unique_id)
                if isinstance(entity_id, str) and entity_id:
                    return entity_id
        except Exception:  # pragma: no cover - fallback only
            _LOGGER.debug("Impossible de résoudre le capteur de plan d'arrosage via le registre.", exc_info=True)
        return fallback

    async def async_record_user_action(
        self,
        action: str,
        state: str,
        reason: str | None = None,
        plan_type: str | None = None,
        zone_count: int | None = None,
        passages: int | None = None,
        triggered_at: datetime | None = None,
    ) -> dict[str, Any]:
        summary = self.brain.record_user_action(
            action=action,
            state=state,
            reason=reason,
            plan_type=plan_type,
            zone_count=zone_count,
            passages=passages,
            triggered_at=triggered_at,
        )
        await self._async_save_state()
        await self.async_request_refresh()
        return summary

    def _parse_datetime_value(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value).strip()
            if not text:
                return None
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _recent_watering_block_active(self, objective_mm: float | None = None) -> bool:
        objective = float(objective_mm or 0.0)
        if objective <= 0:
            return False
        history = getattr(self, "history", None)
        if not isinstance(history, list):
            return False
        today = date.today()
        for item in reversed(history):
            if not isinstance(item, dict) or item.get("type") != "arrosage":
                continue
            recorded_at = (
                item.get("recorded_at")
                or item.get("detected_at")
                or item.get("date")
            )
            recorded_dt = self._parse_datetime_value(recorded_at)
            total_mm = item.get("total_mm") or item.get("session_total_mm") or item.get("objectif_mm")
            try:
                total_mm_value = float(total_mm or 0.0)
            except (TypeError, ValueError):
                total_mm_value = 0.0
            if recorded_dt is not None:
                if recorded_dt.date() == today:
                    return total_mm_value >= objective
                return False
            recorded_date = str(recorded_at or "").strip()
            if not recorded_date:
                continue
            if recorded_date == today.isoformat():
                return total_mm_value >= objective
            return False
        return False

    def _watering_session_active(self) -> bool:
        session = getattr(self, "_watering_session", None)
        if isinstance(session, dict):
            active_zones = session.get("active_zones")
            if isinstance(active_zones, dict) and active_zones:
                return True

        hass = getattr(self, "hass", None)
        states = getattr(hass, "states", None)
        if states is None:
            return False

        try:
            for entity_id, _rate in self._iter_zones_with_rate():
                state = states.get(entity_id)
                if state is not None and str(state.state).lower() == "on":
                    return True
        except Exception:  # pragma: no cover - best effort fallback
            _LOGGER.debug("Impossible de vérifier l'état courant des zones d'arrosage.", exc_info=True)
        return False

    def _should_launch_auto_irrigation(self, snapshot: dict[str, Any]) -> tuple[bool, str]:
        if not self.auto_irrigation_enabled:
            return False, "auto_irrigation_disabled"

        objectif_mm = float(snapshot.get("objectif_mm") or 0.0)
        if objectif_mm <= 0:
            return False, "no_objective"
        if not bool(snapshot.get("arrosage_recommande")):
            return False, "not_recommended"

        fenetre = str(snapshot.get("fenetre_optimale") or "").strip()
        if fenetre in {"", "unknown", "unavailable", "none", "attendre"}:
            return False, "window_unavailable"

        if self._watering_session_active():
            return False, "watering_in_progress"

        target_date = str(snapshot.get("watering_target_date") or "").strip()
        today_str = date.today().isoformat()
        if target_date and today_str < target_date:
            return False, "target_date_future"

        if self._recent_watering_block_active(objectif_mm):
            return False, "recent_watering"

        current = datetime.now().astimezone()
        current_minutes = current.hour * 60 + current.minute
        window_start = int(snapshot.get("watering_window_start_minute") or 0)
        window_end = int(snapshot.get("watering_window_end_minute") or 0)
        evening_start = int(snapshot.get("watering_evening_start_minute") or 1080)
        evening_end = int(snapshot.get("watering_evening_end_minute") or 1260)
        evening_allowed = bool(snapshot.get("watering_evening_allowed"))

        if fenetre == "soir":
            if not evening_allowed:
                return False, "evening_disabled"
            if not (evening_start <= current_minutes < evening_end):
                return False, "outside_evening_window"
        elif not (window_start <= current_minutes < window_end):
            return False, "outside_window"

        return True, "ready"

    def _maybe_schedule_auto_irrigation(self, snapshot: dict[str, Any]) -> None:
        auto_task = getattr(self, "_auto_irrigation_task", None)
        scheduler_task = getattr(self, "_auto_irrigation_scheduler_task", None)
        if auto_task and not auto_task.done():
            return
        if scheduler_task and not scheduler_task.done():
            return

        should_launch, _reason = self._should_launch_auto_irrigation(snapshot)
        if not should_launch:
            return

        plan_entity_id = self._plan_arrosage_entity_id()
        plan = self._build_watering_plan_from_state(plan_entity_id)
        objectif_mm = None
        if plan is None:
            try:
                objectif_mm = float(snapshot.get("objectif_mm") or 0.0)
            except (TypeError, ValueError):
                objectif_mm = 0.0
            if objectif_mm <= 0:
                return
            plan_feedback = self._build_watering_plan_summary_for_user_action(objectif_mm=objectif_mm)
        else:
            plan_feedback = self._build_watering_plan_summary_for_user_action(plan=plan)

        async def _runner() -> None:
            await self.async_record_user_action(
                action="Arrosage automatique",
                state="en_attente",
                reason="Arrosage automatique lancé, attente de la fin de la séquence.",
                plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                zone_count=int(plan_feedback.get("zone_count") or 0),
                passages=int(plan_feedback.get("passages") or 1),
            )
            try:
                await self.async_start_auto_irrigation(
                    objectif_mm,
                    plan_entity_id if plan is not None else None,
                    source="auto_irrigation",
                    user_action_context={
                        "action": "Arrosage automatique",
                        "success_reason": "Arrosage automatique exécuté avec succès.",
                        "plan_type": str(plan_feedback.get("plan_type") or "no_plan"),
                        "zone_count": int(plan_feedback.get("zone_count") or 0),
                        "passages": int(plan_feedback.get("passages") or 1),
                    },
                )
            except HomeAssistantError as err:
                await self.async_record_user_action(
                    action="Arrosage automatique",
                    state="refuse",
                    reason=str(err),
                    plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                    zone_count=int(plan_feedback.get("zone_count") or 0),
                    passages=int(plan_feedback.get("passages") or 1),
                )
                _LOGGER.debug("Arrosage automatique ignoré: %s", err)
            finally:
                self._auto_irrigation_scheduler_task = None

        self._auto_irrigation_scheduler_task = self.hass.async_create_task(
            _runner(),
            "gazon_intelligent_auto_irrigation_scheduler",
        )

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

        if float(session.get("planned_total_seconds") or 0.0) <= 0:
            estimated_total_seconds = self._estimate_watering_session_total_seconds(session)
            if estimated_total_seconds > 0:
                session["planned_total_seconds"] = estimated_total_seconds

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
        application_type: str | None = None,
        application_requires_watering_after: bool | None = None,
        application_post_watering_mm: float | None = None,
        application_irrigation_block_hours: float | None = None,
        application_irrigation_delay_minutes: float | None = None,
        application_irrigation_mode: str | None = None,
        application_label_notes: str | None = None,
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
            application_type=application_type,
            application_requires_watering_after=application_requires_watering_after,
            application_post_watering_mm=application_post_watering_mm,
            application_irrigation_block_hours=application_irrigation_block_hours,
            application_irrigation_delay_minutes=application_irrigation_delay_minutes,
            application_irrigation_mode=application_irrigation_mode,
            application_label_notes=application_label_notes,
            note=note,
        )
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_remove_product(self, product_id: str) -> None:
        self.brain.remove_product(product_id)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_start_manual_irrigation(self, objectif_mm: float) -> None:
        """Déclenche un arrosage manuel réel sur l'objectif fourni."""
        try:
            objectif = max(0.0, float(objectif_mm))
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("Aucun objectif d'arrosage disponible pour un arrosage manuel.") from err

        if objectif <= 0:
            await self.async_record_user_action(
                action="Arrosage manuel",
                state="refuse",
                reason="Action bloquée (conditions non remplies). Aucun objectif d'arrosage disponible.",
                plan_type="no_plan",
                zone_count=0,
                passages=1,
            )
            raise HomeAssistantError("Aucun objectif d'arrosage disponible pour un arrosage manuel.")

        plan_feedback = self._build_watering_plan_summary_for_user_action(objectif_mm=objectif)
        await self.async_record_user_action(
            action="Arrosage manuel",
            state="en_attente",
            reason="Arrosage manuel lancé, attente de la fin de la séquence.",
            plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
            zone_count=int(plan_feedback.get("zone_count") or 0),
            passages=int(plan_feedback.get("passages") or 1),
        )
        try:
            await self.async_start_auto_irrigation(
                objectif,
                source="manual_irrigation",
                user_action_context={
                    "action": "Arrosage manuel",
                    "success_reason": "Arrosage manuel exécuté avec succès.",
                    "plan_type": str(plan_feedback.get("plan_type") or "no_plan"),
                    "zone_count": int(plan_feedback.get("zone_count") or 0),
                    "passages": int(plan_feedback.get("passages") or 1),
                },
            )
        except HomeAssistantError as err:
            await self.async_record_user_action(
                action="Arrosage manuel",
                state="refuse",
                reason=str(err),
                plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                zone_count=int(plan_feedback.get("zone_count") or 0),
                passages=int(plan_feedback.get("passages") or 1),
            )
            raise

        self.hass.bus.async_fire(
            "gazon_intelligent_manual_irrigation_requested",
            {
                "objectif_mm": float(objectif),
                "mode": self.mode,
                "date_action": self.date_action.isoformat() if self.date_action else None,
                "source": "manual_irrigation",
            },
        )

    def _current_objective_mm(self) -> float:
        result = self.result
        if result is not None:
            value = getattr(result, "objectif_arrosage", None)
            try:
                if value is not None:
                    return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict):
                value = extra.get("objectif_mm")
                try:
                    if value is not None:
                        return max(0.0, float(value))
                except (TypeError, ValueError):
                    pass

        data = getattr(self, "data", None)
        if isinstance(data, dict):
            value = data.get("objectif_mm")
            try:
                if value is not None:
                    return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
        return 0.0

    async def async_force_manual_irrigation(self) -> None:
        """Déclenche un arrosage manuel immédiat sur l'objectif courant."""
        objectif_mm = self._current_objective_mm()
        if objectif_mm <= 0:
            await self.async_record_user_action(
                action="Arrosage manuel immédiat",
                state="refuse",
                reason="Action bloquée (conditions non remplies). Aucun objectif d'arrosage disponible.",
                plan_type="no_plan",
                zone_count=0,
                passages=1,
            )
            raise HomeAssistantError("Aucun objectif d'arrosage disponible pour un arrosage manuel immédiat.")

        plan_feedback = self._build_watering_plan_summary_for_user_action(objectif_mm=objectif_mm)
        await self.async_record_user_action(
            action="Arrosage manuel immédiat",
            state="en_attente",
            reason="Arrosage manuel lancé, attente de la fin de la séquence.",
            plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
            zone_count=int(plan_feedback.get("zone_count") or 0),
            passages=int(plan_feedback.get("passages") or 1),
        )
        try:
            await self.async_start_auto_irrigation(
                objectif_mm,
                source="manual_force",
                user_action_context={
                    "action": "Arrosage manuel immédiat",
                    "success_reason": "Arrosage manuel exécuté avec succès.",
                    "plan_type": str(plan_feedback.get("plan_type") or "no_plan"),
                    "zone_count": int(plan_feedback.get("zone_count") or 0),
                    "passages": int(plan_feedback.get("passages") or 1),
                },
            )
        except HomeAssistantError as err:
            await self.async_record_user_action(
                action="Arrosage manuel immédiat",
                state="refuse",
                reason=str(err),
                plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                zone_count=int(plan_feedback.get("zone_count") or 0),
                passages=int(plan_feedback.get("passages") or 1),
            )
            raise

    async def async_start_application_irrigation(self) -> None:
        """Déclenche un arrosage contrôlé après application, si requis."""
        application_state = compute_application_state(self.history)
        application_summary = application_state.get("derniere_application")
        application_type = application_state.get("application_type")
        application_mode = str(application_state.get("application_irrigation_mode") or "").strip().lower()
        application_type_known = application_type in {APPLICATION_TYPE_SOL, APPLICATION_TYPE_FOLIAIRE}
        planned_objectif_mm = float(
            application_state.get("application_post_watering_remaining_mm")
            or application_state.get("application_post_watering_mm")
            or 0.0
        )
        plan_feedback = self._build_watering_plan_summary_for_user_action(objectif_mm=planned_objectif_mm)

        async def _reject_application_irrigation(
            message: str,
            *,
            state: str = "refuse",
            reason: str | None = None,
            plan_type: str = "no_plan",
            zone_count: int = 0,
            passages: int = 1,
        ) -> None:
            await self.async_record_user_action(
                action="Arroser maintenant",
                state=state,
                reason=reason or message,
                plan_type=plan_type,
                zone_count=zone_count,
                passages=passages,
            )
            raise HomeAssistantError(message)

        if application_summary and not application_type_known:
            await _reject_application_irrigation(
                "Le type d'application est inconnu: aucun arrosage automatique ne peut être lancé.",
            )
        if application_state.get("application_block_active"):
            await _reject_application_irrigation(
                "L'arrosage est bloqué par la fenêtre de protection de l'application.",
                state="bloque",
                reason=(
                    f"L'arrosage est bloqué par la fenêtre de protection. "
                    f"Temps restant={float(application_state.get('application_block_remaining_minutes') or 0.0):.0f} min."
                ),
                plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                zone_count=int(plan_feedback.get("zone_count") or 0),
                passages=int(plan_feedback.get("passages") or 1),
            )

        if application_summary and application_type == "foliaire":
            await _reject_application_irrigation(
                "L'application foliaire bloque l'arrosage automatique pendant la fenêtre de protection.",
                state="bloque",
                reason="Application foliaire: l'arrosage automatique reste bloqué pendant la fenêtre de protection.",
                plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                zone_count=int(plan_feedback.get("zone_count") or 0),
                passages=int(plan_feedback.get("passages") or 1),
            )

        application_requires_watering_after = bool(
            application_state.get("application_requires_watering_after", False)
        )
        application_post_watering_pending = bool(
            application_state.get("application_post_watering_pending", False)
        )
        application_post_watering_ready = bool(
            application_state.get("application_post_watering_ready", False)
        )
        application_delay_remaining = float(
            application_state.get("application_post_watering_delay_remaining_minutes") or 0.0
        )
        if application_summary and application_requires_watering_after:
            if not application_post_watering_pending:
                await _reject_application_irrigation(
                    "Aucun arrosage technique n'est requis pour l'application courante.",
                )
            if not application_post_watering_ready:
                await _reject_application_irrigation(
                    f"L'arrosage technique est différé: attendre encore {application_delay_remaining:.0f} minute(s)."
                    ,
                    state="en_attente",
                    reason=(
                        f"L'arrosage technique est différé: attendre encore {application_delay_remaining:.0f} minute(s)."
                    ),
                    plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                    zone_count=int(plan_feedback.get("zone_count") or 0),
                    passages=int(plan_feedback.get("passages") or 1),
                )
            if application_mode == "suggestion":
                await _reject_application_irrigation(
                    "Cette application est en mode suggestion uniquement: aucun arrosage ne doit être lancé.",
                    reason="Cette application est en mode suggestion uniquement: aucun arrosage ne doit être lancé.",
                    plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                    zone_count=int(plan_feedback.get("zone_count") or 0),
                    passages=int(plan_feedback.get("passages") or 1),
                )
            objectif_mm = planned_objectif_mm
            if objectif_mm <= 0:
                await _reject_application_irrigation(
                    "Aucun arrosage technique n'est requis pour l'application courante.",
                )
            try:
                await self.async_start_auto_irrigation(
                    objectif_mm,
                    source="manual_application",
                    user_action_context={
                        "action": "Arroser maintenant",
                        "success_reason": "Arrosage technique exécuté avec succès.",
                        "plan_type": str(plan_feedback.get("plan_type") or "no_plan"),
                        "zone_count": int(plan_feedback.get("zone_count") or 0),
                        "passages": int(plan_feedback.get("passages") or 1),
                    },
                )
            except HomeAssistantError as err:
                await _reject_application_irrigation(
                    str(err),
                    reason=str(err),
                    plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                    zone_count=int(plan_feedback.get("zone_count") or 0),
                    passages=int(plan_feedback.get("passages") or 1),
                )
            await self.async_record_user_action(
                action="Arroser maintenant",
                state="en_attente",
                reason="Arrosage technique lancé, attente de la fin de la séquence.",
                plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                zone_count=int(plan_feedback.get("zone_count") or 0),
                passages=int(plan_feedback.get("passages") or 1),
            )
            return

        if application_summary:
            await _reject_application_irrigation(
                "Cette application ne requiert pas d'arrosage technique.",
            )

        await _reject_application_irrigation(
            "Aucune application en cours ne requiert d'arrosage technique.",
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
        source: str = "auto_irrigation",
        user_action_context: dict[str, Any] | None = None,
    ) -> None:
        """Arrose automatiquement chaque zone en séquence selon le débit renseigné."""
        source = str(source or "auto_irrigation")
        user_action_context = dict(user_action_context or {})
        if source in AUTO_IRRIGATION_AUTO_SOURCES and not self.auto_irrigation_enabled:
            raise HomeAssistantError("L'arrosage automatique est désactivé.")
        if self._watering_session_active():
            raise HomeAssistantError("Un arrosage est déjà en cours.")
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

        async def _finalize_user_action(state: str, reason: str) -> None:
            action = user_action_context.get("action")
            if not action:
                return
            await self.async_record_user_action(
                action=str(action),
                state=state,
                reason=reason,
                plan_type=user_action_context.get("plan_type"),
                zone_count=user_action_context.get("zone_count"),
                passages=user_action_context.get("passages"),
            )

        def _begin_watering_session(planned_total_seconds: float) -> None:
            started_at = datetime.now(timezone.utc)
            clear_session = getattr(self, "_clear_watering_session", None)
            if callable(clear_session):
                clear_session()
            ensure_session = getattr(self, "_ensure_watering_session", None)
            if callable(ensure_session):
                ensure_session(started_at)
                session = getattr(self, "_watering_session", None)
                if isinstance(session, dict):
                    session["started_at"] = started_at
                    session["last_activity_at"] = started_at
                    session["last_inactive_at"] = None
                    session["zones"] = {}
                    session["active_zones"] = {}
                    session["zone_order"] = 0
                    session["planned_total_seconds"] = max(0.0, float(planned_total_seconds or 0.0))
                    return
            self._watering_session = {
                "started_at": started_at,
                "last_activity_at": started_at,
                "last_inactive_at": None,
                "zones": {},
                "active_zones": {},
                "zone_order": 0,
                "planned_total_seconds": max(0.0, float(planned_total_seconds or 0.0)),
            }

        async def _run_fallback_sequence():
            session_zones: list[dict[str, Any]] = []
            error_reason: str | None = None
            cancelled = False
            planned_total_seconds = 0.0
            session_refresh_requested = False
            for _order, (_entity_id, rate) in enumerate(zones, start=1):
                if rate <= 0:
                    continue
                duration = objectif / rate
                if duration <= 0:
                    continue
                planned_total_seconds += max(duration, 0.0) * 60.0
            try:
                _begin_watering_session(planned_total_seconds)
                self._zone_tracking_suspended += 1
                for order, (entity_id, rate) in enumerate(zones, start=1):
                    if rate <= 0:
                        continue
                    duration = objectif / rate
                    if duration <= 0:
                        continue
                    session = self._watering_session
                    if session is not None:
                        started_at = datetime.now(timezone.utc)
                        session["active_zones"][entity_id] = started_at
                        session["last_activity_at"] = started_at
                    session["zones"][entity_id] = {
                            "order": order,
                            "zone": entity_id,
                            "entity_id": entity_id,
                            "rate_mm_h": rate * 60.0,
                            "duration_seconds": duration * 60.0,
                            "duration_min": duration,
                            "mm": round(duration * rate, 1),
                            "started_at": started_at,
                            "ended_at": None,
                        }
                    if not session_refresh_requested:
                        refresh = getattr(self, "async_request_refresh", None)
                        if callable(refresh):
                            await refresh()
                        session_refresh_requested = True
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
            except asyncio.CancelledError:
                cancelled = True
                raise
            except HomeAssistantError as err:
                error_reason = str(err)
                _LOGGER.debug("Echec arrosage automatique (%s): %s", source, err)
            except Exception as err:  # pragma: no cover - best effort cleanup
                error_reason = str(err)
                _LOGGER.exception("Echec arrosage automatique (%s)", source)
            finally:
                self._zone_tracking_suspended = max(0, self._zone_tracking_suspended - 1)
                self._auto_irrigation_task = None
                self._clear_watering_session()
                if session_zones:
                    await self.async_record_watering(
                        date.today(),
                        objectif_mm=objectif,
                        zones=session_zones,
                        source=source,
                    )
                if user_action_context and not cancelled:
                    if error_reason is None:
                        await _finalize_user_action(
                            "ok",
                            str(user_action_context.get("success_reason") or "Arrosage terminé avec succès."),
                        )
                    else:
                        await _finalize_user_action("refuse", error_reason)

        async def _run_plan_sequence():
            assert plan is not None
            zones = list(plan["zones"])
            passages = max(1, int(plan["passages"]))
            pause_minutes = max(0, int(plan["pause_between_passages_minutes"]))
            started_zones: list[str] = []
            error_reason: str | None = None
            cancelled = False
            planned_total_seconds = 0.0
            session_refresh_requested = False
            for passage_index in range(passages):
                for zone in zones:
                    duration_seconds = zone.get("duration_seconds")
                    try:
                        duration_seconds = float(duration_seconds)
                    except (TypeError, ValueError):
                        continue
                    if duration_seconds <= 0:
                        continue
                    planned_total_seconds += duration_seconds
                if passage_index < passages - 1 and pause_minutes > 0:
                    planned_total_seconds += pause_minutes * 60.0
            try:
                _begin_watering_session(planned_total_seconds)
                self._zone_tracking_suspended += 1
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
                        session = self._watering_session
                        if session is not None:
                            started_at = datetime.now(timezone.utc)
                            session["active_zones"][entity_id] = started_at
                            session["last_activity_at"] = started_at
                            session["zones"][entity_id] = {
                                "order": len(session["zones"]) + 1,
                                "zone": entity_id,
                                "entity_id": entity_id,
                                "rate_mm_h": zone.get("rate_mm_h"),
                                "duration_seconds": duration_seconds,
                                "duration_min": zone.get("duration_min"),
                                "mm": zone.get("mm"),
                            "started_at": started_at,
                            "ended_at": None,
                        }
                        if not session_refresh_requested:
                            refresh = getattr(self, "async_request_refresh", None)
                            if callable(refresh):
                                await refresh()
                            session_refresh_requested = True
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
            except asyncio.CancelledError:
                cancelled = True
                raise
            except HomeAssistantError as err:
                error_reason = str(err)
                _LOGGER.debug("Echec arrosage automatique (%s): %s", source, err)
            except Exception as err:  # pragma: no cover - best effort cleanup
                error_reason = str(err)
                _LOGGER.exception("Echec arrosage automatique (%s)", source)
            finally:
                self._zone_tracking_suspended = max(0, self._zone_tracking_suspended - 1)
                cleanup_targets = list(dict.fromkeys(started_zones or [str(zone["zone"]) for zone in zones]))
                for entity_id in reversed(cleanup_targets):
                    await _turn_off_zone(entity_id)
                self._auto_irrigation_task = None
                self._clear_watering_session()
                if user_action_context and not cancelled:
                    if error_reason is None:
                        await _finalize_user_action(
                            "ok",
                            str(user_action_context.get("success_reason") or "Arrosage terminé avec succès."),
                        )
                    else:
                        await _finalize_user_action("refuse", error_reason)

        sequence = _run_plan_sequence if plan is not None else _run_fallback_sequence
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

    def _cancel_source_monitoring(self) -> None:
        for unsub in self._unsub_source_listeners:
            unsub()
        self._unsub_source_listeners.clear()
        if self._source_refresh_task and not self._source_refresh_task.done():
            self._source_refresh_task.cancel()
        self._source_refresh_task = None

    def _cancel_auto_irrigation_monitoring(self) -> None:
        if self._unsub_auto_irrigation_monitor:
            self._unsub_auto_irrigation_monitor()
            self._unsub_auto_irrigation_monitor = None
        if self._auto_irrigation_monitor_task and not self._auto_irrigation_monitor_task.done():
            self._auto_irrigation_monitor_task.cancel()
        self._auto_irrigation_monitor_task = None

    async def async_shutdown(self) -> None:
        """Nettoie les tâches en cours à la fermeture de l'intégration."""
        self._cancel_post_start_refresh()
        self._cancel_auto_irrigation_monitoring()
        self._cancel_source_monitoring()
        self._cancel_zone_monitoring()
        if self._auto_irrigation_scheduler_task and not self._auto_irrigation_scheduler_task.done():
            self._auto_irrigation_scheduler_task.cancel()
            try:
                await self._auto_irrigation_scheduler_task
            except asyncio.CancelledError:
                pass
        self._auto_irrigation_scheduler_task = None
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
        await self.async_start_source_monitoring()
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
