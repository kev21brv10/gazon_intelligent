from __future__ import annotations

from datetime import date, timedelta
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
    CONF_TYPE_SOL,
    DEFAULT_MODE,
    DEFAULT_TYPE_SOL,
    INTERVENTIONS_ACTIONS,
)
from .decision import (
    build_decision_snapshot,
    compute_memory,
    compute_recent_watering_mm,
    phase_duration_days,
)
from .memory import normalize_product_id, normalize_product_record
from .weather_sources import extract_weather_profile, extract_weather_forecast_summary

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
        self.mode: str = DEFAULT_MODE
        self.date_action: date | None = None
        self.history: list[dict[str, Any]] = []
        self.memory: dict[str, Any] = {
            "historique_total": 0,
            "derniere_tonte": None,
            "dernier_arrosage": None,
            "dernier_arrosage_significatif": None,
            "derniere_phase_active": DEFAULT_MODE,
            "dernier_conseil": None,
            "derniere_application": None,
            "prochaine_reapplication": None,
            "catalogue_produits": 0,
            "date_derniere_mise_a_jour": None,
        }
        self.products: dict[str, dict[str, Any]] = {}
        self._auto_irrigation_task: asyncio.Task | None = None
        self._unsub_start_listener: CALLBACK_TYPE | None = None
        self._unsub_delayed_refresh: CALLBACK_TYPE | None = None
        self._unsub_zone_listeners: list[CALLBACK_TYPE] = []
        self._zone_start_times: dict[str, Any] = {}
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
            pluie_24h_source = "meteo_forecast" if pluie_24h is not None else "indisponible"
        if pluie_demain_sensor is not None:
            pluie_demain = pluie_demain_sensor
            pluie_demain_source = "capteur"
        else:
            pluie_demain = forecast_pluie_demain
            pluie_demain_source = "meteo_forecast" if pluie_demain is not None else "indisponible"

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
        retour_arrosage_today = compute_recent_watering_mm(self.history, today=date.today(), days=0)
        retour_arrosage = retour_arrosage_today if retour_arrosage_today > 0 else None
        type_sol = self._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL
        snapshot = build_decision_snapshot(
            history=self.history,
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
            weather_profile=weather_profile,
        )
        self.mode = snapshot["phase_active"]
        self.date_action = snapshot["date_action"]
        self.memory = compute_memory(
            history=self.history,
            current_phase=snapshot["phase_active"],
            decision=snapshot,
            previous_memory=self.memory,
            today=date.today(),
        )
        self.memory["catalogue_produits"] = len(self.products)

        return {
            "mode": snapshot["mode"],
            "phase_active": snapshot["phase_active"],
            "date_action": snapshot["date_action"],
            "date_fin": snapshot["date_fin"],
            "advanced_context": snapshot["advanced_context"],
            "pluie_24h": pluie_24h,
            "pluie_demain": pluie_demain,
            "pluie_24h_source": pluie_24h_source,
            "pluie_demain_source": pluie_demain_source,
            "temperature": temperature,
            "etp": snapshot["etp"],
            "humidite": humidite,
            "type_sol": type_sol,
            "humidite_sol": snapshot["humidite_sol"],
            "vent": snapshot["vent"],
            "rosee": snapshot["rosee"],
            "hauteur_gazon": snapshot["hauteur_gazon"],
            "retour_arrosage": snapshot["retour_arrosage"],
            "pluie_source": snapshot["pluie_source"],
            "bilan_hydrique_mm": snapshot["bilan_hydrique_mm"],
            "objectif_mm": snapshot["objectif_mm"],
            "score_hydrique": snapshot["score_hydrique"],
            "score_stress": snapshot["score_stress"],
            "tonte_autorisee": snapshot["tonte_autorisee"],
            "tonte_statut": snapshot["tonte_statut"],
            "arrosage_auto_autorise": snapshot["arrosage_auto_autorise"],
            "arrosage_recommande": snapshot["arrosage_recommande"],
            "type_arrosage": snapshot["type_arrosage"],
            "arrosage_conseille": snapshot["arrosage_conseille"],
            "raison_decision": snapshot["raison_decision"],
            "conseil_principal": snapshot["conseil_principal"],
            "action_recommandee": snapshot["action_recommandee"],
            "action_a_eviter": snapshot["action_a_eviter"],
            "niveau_action": snapshot["niveau_action"],
            "fenetre_optimale": snapshot["fenetre_optimale"],
            "risque_gazon": snapshot["risque_gazon"],
            "urgence": snapshot["urgence"],
            "prochaine_reevaluation": snapshot["prochaine_reevaluation"],
            "score_tonte": snapshot["score_tonte"],
            "jours_restants": snapshot["jours_restants"],
            "memoire": self.memory,
            "derniere_application": self.memory.get("derniere_application"),
            "prochaine_reapplication": self.memory.get("prochaine_reapplication"),
            "catalogue_produits": len(self.products),
            "historique_total": len(self.history),
        }

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

    def _get_weather_profile(self, weather_entity_id: str | None) -> dict[str, Any]:
        """Retourne les principaux attributs météo disponibles pour l'entité fournie."""
        if not weather_entity_id:
            return {}

        state = self.hass.states.get(weather_entity_id)
        if state is None:
            return {}

        return extract_weather_profile(state.attributes)

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

        return extract_weather_forecast_summary(forecasts)

    async def async_set_mode(self, mode: str) -> None:
        """Définit le mode gazon."""
        if mode == "Normal":
            await self.async_set_normal()
            return
        await self.async_declare_intervention(mode)

    async def async_set_date_action(self, date_action: date | None = None) -> None:
        """Définit la date de la dernière intervention de phase."""
        target_date = date_action or date.today()
        updated = False
        for idx in range(len(self.history) - 1, -1, -1):
            item_type = self.history[idx].get("type")
            if item_type in INTERVENTIONS_ACTIONS:
                self.history[idx]["date"] = target_date.isoformat()
                updated = True
                break
        if not updated and self.mode in INTERVENTIONS_ACTIONS:
            self._append_history(
                {
                    "type": self.mode,
                    "date": target_date.isoformat(),
                }
            )
        self.date_action = target_date
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_set_normal(self) -> None:
        """Réinitialise la phase active vers Normal (historique conservé)."""
        today = date.today()
        self.history = [
            item for item in self.history
            if item.get("type") not in INTERVENTIONS_ACTIONS
            or not item.get("date")
            or self._is_history_item_expired(item, today)
        ]
        self.mode = "Normal"
        self.date_action = None
        await self._async_save_state()
        await self.async_request_refresh()

    def _is_history_item_expired(self, item: dict[str, Any], today: date) -> bool:
        item_type = item.get("type")
        if item_type not in INTERVENTIONS_ACTIONS:
            return False
        raw_date = item.get("date")
        if not raw_date:
            return False
        try:
            start = date.fromisoformat(raw_date)
        except ValueError:
            return False
        end = start + timedelta(days=phase_duration_days(item_type))
        return today > end

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
        if intervention not in INTERVENTIONS_ACTIONS:
            raise HomeAssistantError(f"Intervention non supportée: {intervention}")
        target_date = date_action or date.today()
        product_record = self._resolve_product_record(produit_id)
        if product_record:
            produit = produit or product_record.get("nom")
            if dose is None:
                dose_conseillee = product_record.get("dose_conseillee")
                if dose_conseillee not in (None, ""):
                    dose = str(dose_conseillee)
            if reapplication_after_days is None:
                reapplication_after_days = product_record.get("reapplication_after_days")
        item: dict[str, Any] = {
            "type": intervention,
            "date": target_date.isoformat(),
            "source": "service",
        }
        if product_record:
            item["produit_id"] = product_record.get("id")
            item["produit_catalogue"] = product_record
        if produit:
            item["produit"] = produit
        if dose is not None:
            item["dose"] = dose
        if zone:
            item["zone"] = zone
        if reapplication_after_days is not None:
            item["reapplication_after_days"] = int(reapplication_after_days)
        if note:
            item["note"] = note
        self._append_history(item)
        self.mode = intervention
        self.date_action = target_date
        await self._async_save_state()
        await self.async_request_refresh()

    def _resolve_product_record(self, product_id: str | None) -> dict[str, Any] | None:
        normalized = normalize_product_id(product_id)
        if not normalized:
            return None
        product = self.products.get(normalized)
        if not isinstance(product, dict):
            return None
        return product

    async def async_record_mowing(self, date_action: date | None = None) -> None:
        self._append_history(
            {
                "type": "tonte",
                "date": (date_action or date.today()).isoformat(),
            }
        )
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_record_watering(self, date_action: date | None = None, objectif_mm: float | None = None) -> None:
        payload: dict[str, Any] = {
            "type": "arrosage",
            "date": (date_action or date.today()).isoformat(),
        }
        if objectif_mm is not None:
            payload["objectif_mm"] = float(objectif_mm)
        self._append_history(payload)
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

        if new_is_on:
            self._zone_start_times[entity_id] = new_state.last_changed
            return

        start = self._zone_start_times.pop(entity_id, None)
        if start is None and old_is_on and old_state is not None:
            start = old_state.last_changed
        if start is None:
            return

        rate_mm_min = self._get_zone_rate_mm_min(entity_id)
        if rate_mm_min <= 0:
            return

        duration_minutes = max((new_state.last_changed - start).total_seconds() / 60.0, 0.0)
        objectif_mm = round(duration_minutes * rate_mm_min, 1)
        if objectif_mm <= 0:
            return

        self.hass.async_create_task(
            self._async_record_switch_watering(entity_id, objectif_mm, new_state.last_changed)
        )

    async def _async_record_switch_watering(self, entity_id: str, objectif_mm: float, ended_at) -> None:
        self._append_history(
            {
                "type": "arrosage",
                "date": ended_at.date().isoformat(),
                "objectif_mm": float(objectif_mm),
                "source": "zone_switch",
                "zone": entity_id,
            }
        )
        await self._async_save_state()
        await self.async_request_refresh()

    def _append_history(self, item: dict[str, Any]) -> None:
        self.history.append(item)
        self.history = self.history[-300:]

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
        record = normalize_product_record(
            product_id,
            {
                "nom": nom,
                "type": type_produit,
                "dose_conseillee": dose_conseillee,
                "reapplication_after_days": reapplication_after_days,
                "delai_avant_tonte_jours": delai_avant_tonte_jours,
                "phase_compatible": phase_compatible,
                "note": note,
            },
        )
        if record is None:
            raise HomeAssistantError("Identifiant ou produit invalide.")
        self.products[record["id"]] = record
        self.memory["catalogue_produits"] = len(self.products)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_remove_product(self, product_id: str) -> None:
        normalized = normalize_product_id(product_id)
        if not normalized:
            raise HomeAssistantError("Identifiant produit invalide.")
        self.products.pop(normalized, None)
        self.memory["catalogue_produits"] = len(self.products)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_start_manual_irrigation(self, objectif_mm: float) -> None:
        """Déclenche une demande d'arrosage manuel via un événement HA."""
        await self.async_record_watering(objectif_mm=objectif_mm)
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

    async def async_start_auto_irrigation(self, objectif_mm: float | None) -> None:
        """Arrose automatiquement chaque zone en séquence selon le débit renseigné."""
        if self._auto_irrigation_task and not self._auto_irrigation_task.done():
            raise HomeAssistantError(
                "Un arrosage automatique est déjà en cours."
            )

        objectif = float(objectif_mm) if objectif_mm is not None else float(
            self.data.get("objectif_mm", 0.0)
        )
        zones = list(self._iter_zones_with_rate())
        if not zones:
            raise HomeAssistantError(
                "Aucune zone d'arrosage valide n'est configurée (zone + débit mm/h)."
            )

        async def _run_zone(entity_id: str, duration_minutes: float) -> None:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": entity_id}, blocking=True
            )
            try:
                await asyncio.sleep(max(duration_minutes, 0) * 60)
            finally:
                await self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": entity_id}, blocking=True
                )

        async def _sequence():
            try:
                self._zone_tracking_suspended += 1
                for entity_id, rate in zones:
                    if rate <= 0:
                        continue
                    duration = objectif / rate
                    if duration <= 0:
                        continue
                    await _run_zone(entity_id, duration)
                await self.async_record_watering(objectif_mm=objectif)
            finally:
                self._zone_tracking_suspended = max(0, self._zone_tracking_suspended - 1)
                self._auto_irrigation_task = None

        self._auto_irrigation_task = self.hass.async_create_task(
            _sequence(), "gazon_intelligent_auto_irrigation_sequence"
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
        self._zone_start_times.clear()

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
        attrs = {
            "configuration": {
                "type_sol": self._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL,
            },
            "pluie_demain_source": self.data.get("pluie_demain_source") if self.data else None,
            "phase_dominante_source": self.data.get("phase_dominante_source") if self.data else None,
            "niveau_action": self.data.get("niveau_action") if self.data else None,
            "fenetre_optimale": self.data.get("fenetre_optimale") if self.data else None,
            "risque_gazon": self.data.get("risque_gazon") if self.data else None,
            "tonte_autorisee": self.data.get("tonte_autorisee") if self.data else None,
            "tonte_statut": self.data.get("tonte_statut") if self.data else None,
            "prochaine_reevaluation": self.data.get("prochaine_reevaluation") if self.data else None,
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
        mode = data.get("mode")
        if mode:
            self.mode = mode
        date_str = data.get("date_action")
        if date_str:
            try:
                self.date_action = date.fromisoformat(date_str)
            except ValueError:
                self.date_action = None
        history = data.get("history")
        if isinstance(history, list):
            self.history = [item for item in history if isinstance(item, dict)]
        else:
            self.history = []
        products = data.get("products")
        if isinstance(products, dict):
            self.products = {}
            for key, value in products.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                cleaned = dict(value)
                cleaned.pop("sol_compatible", None)
                self.products[key] = cleaned
        else:
            self.products = {}
        memory = data.get("memory")
        if isinstance(memory, dict):
            self.memory = memory
        else:
            self.memory = {
                "historique_total": len(self.history),
                "derniere_tonte": None,
                "dernier_arrosage": None,
                "dernier_arrosage_significatif": None,
                "derniere_phase_active": self.mode,
                "dernier_conseil": None,
                "derniere_application": None,
                "prochaine_reapplication": None,
                "catalogue_produits": len(self.products),
                "date_derniere_mise_a_jour": None,
            }

    async def _async_save_state(self) -> None:
        """Sauvegarde l'état persistant (mode, date_action)."""
        await self._store.async_save(
            {
                "mode": self.mode,
                "date_action": self.date_action.isoformat() if self.date_action else None,
                "history": self.history[-300:],
                "products": self.products,
                "memory": self.memory,
            }
        )
