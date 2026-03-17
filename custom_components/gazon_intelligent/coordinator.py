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

_LOGGER = logging.getLogger(__name__)

PHASE_DURATIONS_DAYS: dict[str, int] = {
    "Normal": 0,
    "Sursemis": 21,
    "Traitement": 2,
    "Fertilisation": 2,
    "Biostimulant": 1,
    "Agent Mouillant": 1,
    "Scarification": 7,
    "Hivernage": 999,
}

PHASE_PRIORITIES: dict[str, int] = {
    "Traitement": 100,
    "Hivernage": 95,
    "Sursemis": 90,
    "Scarification": 80,
    "Fertilisation": 70,
    "Agent Mouillant": 60,
    "Biostimulant": 50,
}


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
        etp_calcule = self._compute_etp(temperature=temperature, pluie_24h=pluie_24h, etp_capteur=etp_capteur)
        phase_active, date_action, date_fin = self._compute_phase_active(temperature=temperature)
        jours_restants = self._compute_jours_restants_for(phase_active=phase_active, date_fin=date_fin)
        self.mode = phase_active
        self.date_action = date_action
        objectif_mm = self._compute_objectif_mm(
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            type_sol=type_sol,
            phase_active=phase_active,
        )
        decision = self._compute_decision(
            phase_active=phase_active,
            pluie_24h=pluie_24h,
            objectif_mm=objectif_mm,
            jours_restants=jours_restants,
        )

        return {
            "mode": phase_active,
            "phase_active": phase_active,
            "date_action": date_action,
            "date_fin": date_fin,
            "pluie_24h": pluie_24h,
            "pluie_demain": pluie_demain,
            "pluie_demain_source": pluie_demain_source,
            "temperature": temperature,
            "etp": etp_calcule,
            "humidite": humidite,
            "type_sol": type_sol,
            "objectif_mm": objectif_mm,
            "tonte_autorisee": decision["tonte_autorisee"],
            "arrosage_auto_autorise": decision["arrosage_auto_autorise"],
            "arrosage_recommande": decision["arrosage_recommande"],
            "type_arrosage": decision["type_arrosage"],
            "arrosage_conseille": decision["arrosage_conseille"],
            "raison_decision": decision["raison_decision"],
            "conseil_principal": decision["conseil_principal"],
            "action_recommandee": decision["action_recommandee"],
            "action_a_eviter": decision["action_a_eviter"],
            "urgence": decision["urgence"],
            "jours_restants": jours_restants,
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

    def _phase_duration_days(self, phase: str) -> int:
        return PHASE_DURATIONS_DAYS.get(phase, 0)

    def _is_hivernage(self, temperature: float | None) -> bool:
        today = date.today()
        if today.month in {11, 12, 1, 2}:
            return True
        if temperature is not None and temperature <= 5:
            return True
        return False

    def _compute_phase_active(self, temperature: float | None) -> tuple[str, date | None, date | None]:
        """Détermine la phase dominante à partir de l'historique."""
        today = date.today()
        best: tuple[int, date] | None = None
        active_phase: str | None = None
        active_date: date | None = None
        active_end: date | None = None
        for item in self.history:
            phase = item.get("type")
            if phase not in INTERVENTIONS_ACTIONS:
                continue
            raw_date = item.get("date")
            if not raw_date:
                continue
            try:
                start = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if start > today:
                continue
            duration = self._phase_duration_days(phase)
            end = start + timedelta(days=duration)
            if today > end:
                continue
            priority = PHASE_PRIORITIES.get(phase, 0)
            rank = (priority, start)
            if best is None or rank > best:
                best = rank
                active_phase = phase
                active_date = start
                active_end = end

        if active_phase:
            return active_phase, active_date, active_end
        if self._is_hivernage(temperature):
            return "Hivernage", None, None
        return "Normal", None, None

    def _soil_factor(self, type_sol: str) -> float:
        """Retourne un coefficient selon le type de sol."""
        factors = {
            "sableux": 1.2,
            "limoneux": 1.0,
            "argileux": 0.85,
        }
        return factors.get(type_sol, 1.0)

    def _forecast_factor(self, pluie_demain: float | None) -> float:
        """Réduit l'objectif en fonction de la pluie prévue demain."""
        if pluie_demain is None:
            return 1.0
        if pluie_demain >= 8.0:
            return 0.0
        if pluie_demain >= 5.0:
            return 0.4
        if pluie_demain >= 2.0:
            return 0.75
        return 1.0

    def _compute_objectif_mm(
        self,
        pluie_24h: float | None,
        pluie_demain: float | None,
        type_sol: str,
        phase_active: str,
    ) -> float:
        """Calcule l'objectif d'arrosage en mm selon le mode."""
        pluie_24h = pluie_24h or 0.0

        if phase_active in ("Traitement", "Hivernage"):
            return 0.0

        if phase_active == "Sursemis":
            if pluie_24h > 5:
                base = 0.0
            elif pluie_24h > 2:
                base = 1.0
            else:
                base = 3.0
        elif phase_active == "Fertilisation":
            base = 1.5
        elif phase_active == "Biostimulant":
            base = 1.0
        elif phase_active == "Agent Mouillant":
            base = 2.0
        elif phase_active == "Scarification":
            base = 1.0
        else:
            # Mode Normal : viser ~25 mm/semaine pour 3 arrosages/sem ≈ 8.3 mm par passage
            base = 8.3

        objectif = base * self._soil_factor(type_sol) * self._forecast_factor(pluie_demain)
        return round(max(0.0, objectif), 1)

    def _compute_decision(
        self,
        phase_active: str,
        pluie_24h: float | None,
        objectif_mm: float,
        jours_restants: int,
    ) -> dict[str, Any]:
        pluie_24h = pluie_24h or 0.0
        if phase_active == "Traitement":
            return {
                "tonte_autorisee": False,
                "arrosage_auto_autorise": False,
                "arrosage_recommande": False,
                "type_arrosage": "bloque",
                "arrosage_conseille": "personnalise",
                "raison_decision": "Traitement actif: tonte et arrosage bloqués.",
                "conseil_principal": "Laisser agir le traitement.",
                "action_recommandee": "Attendre la fin du traitement.",
                "action_a_eviter": "Tondre ou arroser.",
                "urgence": "faible",
            }
        if phase_active == "Hivernage":
            return {
                "tonte_autorisee": False,
                "arrosage_auto_autorise": False,
                "arrosage_recommande": False,
                "type_arrosage": "bloque",
                "arrosage_conseille": "personnalise",
                "raison_decision": "Hivernage actif: repos végétatif.",
                "conseil_principal": "Limiter les interventions.",
                "action_recommandee": "Surveiller uniquement.",
                "action_a_eviter": "Arrosages fréquents.",
                "urgence": "faible",
            }
        if phase_active == "Sursemis":
            return {
                "tonte_autorisee": False,
                "arrosage_auto_autorise": False,
                "arrosage_recommande": objectif_mm > 0,
                "type_arrosage": "manuel_frequent",
                "arrosage_conseille": "personnalise",
                "raison_decision": "Sursemis actif: maintenir l'humidité sans stress.",
                "conseil_principal": "Arroser en passages courts et réguliers.",
                "action_recommandee": f"Appliquer {objectif_mm} mm fractionnés.",
                "action_a_eviter": "Tondre avant levée complète.",
                "urgence": "haute" if objectif_mm > 0 else "moyenne",
            }

        tonte_ok = phase_active == "Normal" and pluie_24h < 6
        auto_ok = phase_active in {"Normal", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"}
        recommande = objectif_mm > 0
        return {
            "tonte_autorisee": tonte_ok,
            "arrosage_auto_autorise": auto_ok,
            "arrosage_recommande": recommande,
            "type_arrosage": "auto" if auto_ok else "personnalise",
            "arrosage_conseille": "auto" if phase_active == "Normal" else "personnalise",
            "raison_decision": f"Phase {phase_active} active ({jours_restants} j restants).",
            "conseil_principal": "Suivre l'objectif d'arrosage calculé.",
            "action_recommandee": f"Appliquer {objectif_mm} mm.",
            "action_a_eviter": "Tondre sur sol détrempé." if not tonte_ok else "Aucune action bloquante.",
            "urgence": "moyenne" if recommande else "faible",
        }

    def _compute_etp(
        self,
        temperature: float | None,
        pluie_24h: float | None,
        etp_capteur: float | None,
    ) -> float | None:
        """Renvoie l'ETP fournie ou une estimation simple (mm/jour)."""
        if etp_capteur is not None:
            return etp_capteur

        if temperature is None:
            return None

        # Approximation grossière : 0.08 * T + correction pluie
        base = max(0.0, 0.08 * temperature)
        correction = max(0.0, (pluie_24h or 0) * 0.05)
        return max(0.0, base - correction)

    def _compute_jours_restants_for(self, phase_active: str, date_fin: date | None) -> int:
        if phase_active == "Hivernage":
            return 999
        if not date_fin:
            return 0
        return max((date_fin - date.today()).days, 0)

    async def async_set_mode(self, mode: str) -> None:
        """Définit le mode gazon."""
        if mode == "Normal":
            await self.async_set_normal()
            return
        await self.async_declare_intervention(mode)

    async def async_set_date_action(self, date_action: date | None = None) -> None:
        """Définit la date de la dernière intervention de phase."""
        target_date = date_action or date.today()
        for idx in range(len(self.history) - 1, -1, -1):
            item_type = self.history[idx].get("type")
            if item_type in INTERVENTIONS_ACTIONS:
                self.history[idx]["date"] = target_date.isoformat()
                break
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
        end = start + timedelta(days=self._phase_duration_days(item_type))
        return today > end

    async def async_declare_intervention(self, intervention: str, date_action: date | None = None) -> None:
        if intervention not in INTERVENTIONS_ACTIONS:
            raise HomeAssistantError(f"Intervention non supportée: {intervention}")
        self._append_history(
            {
                "type": intervention,
                "date": (date_action or date.today()).isoformat(),
            }
        )
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
