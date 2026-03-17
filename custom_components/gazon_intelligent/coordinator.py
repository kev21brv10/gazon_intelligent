from __future__ import annotations

from datetime import date, timedelta
import asyncio
import logging
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
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
    CONF_TYPE_SOL,
    DEFAULT_MODE,
    DEFAULT_TYPE_SOL,
    INTERVENTIONS_ACTIONS,
)
from .decision import build_decision_snapshot, phase_duration_days

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
        self._auto_irrigation_task: asyncio.Task | None = None
        self._unsub_start_listener: CALLBACK_TYPE | None = None
        self._unsub_delayed_refresh: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Récupère et calcule les données exposées par l'intégration."""
        if not self._loaded:
            await self._async_load_state()
            self._loaded = True

        pluie_24h = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_24H))
        pluie_demain_entity = self._get_conf(CONF_CAPTEUR_PLUIE_DEMAIN)
        pluie_demain = self._get_float_state(pluie_demain_entity)
        pluie_demain_source = "capteur"
        if pluie_demain is None:
            pluie_demain = await self._get_forecast_pluie_demain(self._get_conf(CONF_ENTITE_METEO))
            pluie_demain_source = "meteo_forecast" if pluie_demain is not None else "indisponible"
        temperature = self._get_float_state(self._get_conf(CONF_CAPTEUR_TEMPERATURE))
        etp_capteur = self._get_float_state(self._get_conf(CONF_CAPTEUR_ETP))
        humidite = self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE))
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
        )
        self.mode = snapshot["phase_active"]
        self.date_action = snapshot["date_action"]

        return {
            "mode": snapshot["mode"],
            "phase_active": snapshot["phase_active"],
            "date_action": snapshot["date_action"],
            "date_fin": snapshot["date_fin"],
            "pluie_24h": pluie_24h,
            "pluie_demain": pluie_demain,
            "pluie_demain_source": pluie_demain_source,
            "temperature": temperature,
            "etp": snapshot["etp"],
            "humidite": humidite,
            "type_sol": type_sol,
            "bilan_hydrique_mm": snapshot["bilan_hydrique_mm"],
            "objectif_mm": snapshot["objectif_mm"],
            "score_hydrique": snapshot["score_hydrique"],
            "score_stress": snapshot["score_stress"],
            "tonte_autorisee": snapshot["tonte_autorisee"],
            "arrosage_auto_autorise": snapshot["arrosage_auto_autorise"],
            "arrosage_recommande": snapshot["arrosage_recommande"],
            "type_arrosage": snapshot["type_arrosage"],
            "arrosage_conseille": snapshot["arrosage_conseille"],
            "raison_decision": snapshot["raison_decision"],
            "conseil_principal": snapshot["conseil_principal"],
            "action_recommandee": snapshot["action_recommandee"],
            "action_a_eviter": snapshot["action_a_eviter"],
            "urgence": snapshot["urgence"],
            "score_tonte": snapshot["score_tonte"],
            "jours_restants": snapshot["jours_restants"],
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

    async def _get_forecast_pluie_demain(self, weather_entity_id: str | None) -> float | None:
        """Récupère la pluie prévue demain (mm) via weather.get_forecasts."""
        if not weather_entity_id:
            return None

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
            return None

        if not isinstance(response, dict):
            return None

        entity_data = response.get(weather_entity_id)
        if not isinstance(entity_data, dict):
            return None

        forecasts = entity_data.get("forecast")
        if not isinstance(forecasts, list) or not forecasts:
            return None

        idx = 1 if len(forecasts) > 1 else 0
        tomorrow = forecasts[idx]
        if not isinstance(tomorrow, dict):
            return None

        precipitation = tomorrow.get("precipitation")
        if precipitation is None:
            return None

        try:
            return float(str(precipitation).strip().replace(",", "."))
        except (TypeError, ValueError):
            return None

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
        if updated:
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

    async def async_declare_intervention(self, intervention: str, date_action: date | None = None) -> None:
        if intervention not in INTERVENTIONS_ACTIONS:
            raise HomeAssistantError(f"Intervention non supportée: {intervention}")
        target_date = date_action or date.today()
        self._append_history(
            {
                "type": intervention,
                "date": target_date.isoformat(),
            }
        )
        self.mode = intervention
        self.date_action = target_date
        await self._async_save_state()
        await self.async_request_refresh()

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

    def _append_history(self, item: dict[str, Any]) -> None:
        self.history.append(item)
        self.history = self.history[-300:]

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
            if entity_id and rate_h:
                try:
                    rate_h_float = float(rate_h)
                    rate_mm_min = rate_h_float / 60.0
                    yield entity_id, rate_mm_min
                except (TypeError, ValueError):
                    continue

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
                for entity_id, rate in zones:
                    if rate <= 0:
                        continue
                    duration = objectif / rate
                    if duration <= 0:
                        continue
                    await _run_zone(entity_id, duration)
                await self.async_record_watering(objectif_mm=objectif)
            finally:
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

    async def async_shutdown(self) -> None:
        """Nettoie les tâches en cours à la fermeture de l'intégration."""
        self._cancel_post_start_refresh()
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

    def get_used_entities_attributes(self) -> dict[str, Any]:
        """Expose les entités/config utilisées dans les attributs des entités."""
        attrs = {
            "entites_utilisees": {
                "zone_1": self._get_conf("zone_1"),
                "zone_2": self._get_conf("zone_2"),
                "zone_3": self._get_conf("zone_3"),
                "zone_4": self._get_conf("zone_4"),
                "zone_5": self._get_conf("zone_5"),
                "capteur_pluie_24h": self._get_conf(CONF_CAPTEUR_PLUIE_24H),
                "capteur_pluie_demain": self._get_conf(CONF_CAPTEUR_PLUIE_DEMAIN),
                "entite_meteo": self._get_conf(CONF_ENTITE_METEO),
                "capteur_temperature": self._get_conf(CONF_CAPTEUR_TEMPERATURE),
                "capteur_etp": self._get_conf(CONF_CAPTEUR_ETP),
                "capteur_humidite": self._get_conf(CONF_CAPTEUR_HUMIDITE),
            },
            "configuration": {
                "type_sol": self._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL,
            },
            "pluie_demain_source": self.data.get("pluie_demain_source") if self.data else None,
            "historique_resume": {
                "total": len(self.history),
                "derniere_intervention": self.history[-1] if self.history else None,
            },
        }
        return attrs

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

    async def _async_save_state(self) -> None:
        """Sauvegarde l'état persistant (mode, date_action)."""
        await self._store.async_save(
            {
                "mode": self.mode,
                "date_action": self.date_action.isoformat() if self.date_action else None,
                "history": self.history[-300:],
            }
        )
