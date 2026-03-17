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
)

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
        self._auto_irrigation_task: asyncio.Task | None = None
        self._unsub_start_listener: CALLBACK_TYPE | None = None
        self._unsub_delayed_refresh: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Récupère et calcule les données exposées par l'intégration."""
        if not self._loaded:
            await self._async_load_state()
            self._loaded = True

        pluie_24h = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_24H))
        pluie_demain = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_DEMAIN))
        if pluie_demain is None:
            pluie_demain = await self._get_forecast_pluie_demain(self._get_conf(CONF_ENTITE_METEO))
        temperature = self._get_float_state(self._get_conf(CONF_CAPTEUR_TEMPERATURE))
        etp_capteur = self._get_float_state(self._get_conf(CONF_CAPTEUR_ETP))
        humidite = self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE))
        type_sol = self._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL
        etp_calcule = self._compute_etp(temperature=temperature, pluie_24h=pluie_24h, etp_capteur=etp_capteur)

        return {
            "mode": self.mode,
            "phase_active": self.mode,
            "date_action": self.date_action,
            "date_fin": self._compute_date_fin(),
            "pluie_24h": pluie_24h,
            "pluie_demain": pluie_demain,
            "temperature": temperature,
            "etp": etp_calcule,
            "humidite": humidite,
            "type_sol": type_sol,
            "objectif_mm": self._compute_objectif_mm(
                pluie_24h=pluie_24h,
                pluie_demain=pluie_demain,
                type_sol=type_sol,
            ),
            "tonte_autorisee": self._compute_tonte_autorisee(),
            "arrosage_conseille": self._compute_arrosage_conseille(),
            "jours_restants": self._compute_jours_restants(),
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

    def _get_mode_duration_days(self) -> int:
        """Retourne la durée théorique du mode en jours."""
        durations = {
            "Normal": 0,
            "Sursemis": 21,
            "Traitement": 2,
            "Fertilisation": 2,
            "Biostimulant": 1,
            "Agent Mouillant": 1,
            "Scarification": 7,
            "Hivernage": 999,
        }
        return durations.get(self.mode, 0)

    def _compute_date_fin(self) -> date | None:
        """Calcule la date de fin théorique du mode."""
        if not self.date_action:
            return None

        duration = self._get_mode_duration_days()
        if duration == 999:
            return None

        return self.date_action + timedelta(days=duration)

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
    ) -> float:
        """Calcule l'objectif d'arrosage en mm selon le mode."""
        pluie_24h = pluie_24h or 0.0

        if self.mode in ("Traitement", "Hivernage"):
            return 0.0

        if self.mode == "Sursemis":
            if pluie_24h > 5:
                base = 0.0
            elif pluie_24h > 2:
                base = 1.0
            else:
                base = 3.0
        elif self.mode == "Fertilisation":
            base = 1.5
        elif self.mode == "Biostimulant":
            base = 1.0
        elif self.mode == "Agent Mouillant":
            base = 2.0
        elif self.mode == "Scarification":
            base = 1.0
        else:
            # Mode Normal : viser ~25 mm/semaine pour 3 arrosages/sem ≈ 8.3 mm par passage
            base = 8.3

        objectif = base * self._soil_factor(type_sol) * self._forecast_factor(pluie_demain)
        return round(max(0.0, objectif), 1)

    def _compute_tonte_autorisee(self) -> bool:
        """Indique si la tonte est autorisée selon le mode actif."""
        # Autorisée uniquement en mode Normal
        return self.mode == "Normal"

    def _compute_arrosage_conseille(self) -> str:
        """Retourne le conseil d'arrosage : auto / personnalise."""
        if self.mode == "Normal":
            return "auto"
        return "personnalise"

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

    def _compute_jours_restants(self) -> int:
        """Calcule le nombre de jours restants pour le mode en cours."""
        if not self.date_action:
            return 0

        duration = self._get_mode_duration_days()
        if duration == 999:
            return 999

        date_fin = self._compute_date_fin()
        if date_fin is None:
            return 0

        return max((date_fin - date.today()).days, 0)

    async def async_set_mode(self, mode: str) -> None:
        """Définit le mode gazon."""
        self.mode = mode

        # On ne réécrit pas la date si elle existe déjà,
        # pour éviter de casser un mode rétroactif.
        if self.date_action is None and mode != "Normal":
            self.date_action = date.today()

        if mode == "Normal":
            self.date_action = None

        await self._async_save_state()
        await self.async_request_refresh()

    async def async_set_date_action(self, date_action: date | None = None) -> None:
        """Définit la date réelle de l'action (par défaut aujourd'hui)."""
        self.date_action = date_action or date.today()
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_set_normal(self) -> None:
        """Réinitialise le système en mode Normal."""
        self.mode = "Normal"
        self.date_action = None
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_start_manual_irrigation(self, objectif_mm: float) -> None:
        """Déclenche une demande d'arrosage manuel via un événement HA."""
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

    async def _async_save_state(self) -> None:
        """Sauvegarde l'état persistant (mode, date_action)."""
        await self._store.async_save(
            {
                "mode": self.mode,
                "date_action": self.date_action.isoformat() if self.date_action else None,
            }
        )
