from __future__ import annotations

from datetime import date, timedelta
import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_CAPTEUR_ETP,
    CONF_CAPTEUR_PLUIE_24H,
    CONF_CAPTEUR_PLUIE_DEMAIN,
    CONF_CAPTEUR_TEMPERATURE,
    CONF_CAPTEUR_HUMIDITE,
    DEFAULT_MODE,
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
        self._config: dict[str, Any] = {**entry.data, **entry.options}
        self.mode: str = DEFAULT_MODE
        self.date_action: date | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Récupère et calcule les données exposées par l'intégration."""
        pluie_24h = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_24H))
        pluie_demain = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_DEMAIN))
        temperature = self._get_float_state(self._get_conf(CONF_CAPTEUR_TEMPERATURE))
        etp_capteur = self._get_float_state(self._get_conf(CONF_CAPTEUR_ETP))
        humidite = self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE))
        etp_calcule = self._compute_etp(temperature=temperature, pluie_24h=pluie_24h, etp_capteur=etp_capteur)

        return {
            "mode": self.mode,
            "phase_active": self.mode,
            "date_action": self.date_action.isoformat() if self.date_action else None,
            "date_fin": self._compute_date_fin().isoformat() if self._compute_date_fin() else None,
            "pluie_24h": pluie_24h,
            "pluie_demain": pluie_demain,
            "temperature": temperature,
            "etp": etp_calcule,
            "humidite": humidite,
            "objectif_mm": self._compute_objectif_mm(pluie_24h=pluie_24h),
            "tonte_autorisee": self._compute_tonte_autorisee(),
            "arrosage_auto_autorise": self._compute_arrosage_auto_autorise(),
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
            return float(state.state)
        except (TypeError, ValueError):
            _LOGGER.debug("Impossible de convertir l'état de %s en float: %s", entity_id, state.state)
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

    def _compute_objectif_mm(self, pluie_24h: float | None) -> float:
        """Calcule l'objectif d'arrosage en mm selon le mode."""
        pluie_24h = pluie_24h or 0.0

        if self.mode in ("Traitement", "Hivernage"):
            return 0.0

        if self.mode == "Sursemis":
            if pluie_24h > 5:
                return 0.0
            if pluie_24h > 2:
                return 1.0
            return 3.0

        if self.mode == "Fertilisation":
            return 1.5

        if self.mode == "Biostimulant":
            return 1.0

        if self.mode == "Agent Mouillant":
            return 2.0

        if self.mode == "Scarification":
            return 1.0

        # Mode Normal
        return 2.0

    def _compute_tonte_autorisee(self) -> bool:
        """Indique si la tonte est autorisée selon le mode actif."""
        return self.mode not in {
            "Sursemis",
            "Traitement",
            "Fertilisation",
            "Scarification",
            "Hivernage",
        }

    def _compute_arrosage_auto_autorise(self) -> bool:
        """Indique si l'arrosage automatique est autorisé.

        Reste géré en externe pour l'instant, on ne force rien ici.
        """
        return self.mode == "Normal"

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

        await self.async_request_refresh()

    async def async_set_date_action(self, date_action: date) -> None:
        """Définit la date réelle de l'action."""
        self.date_action = date_action
        await self.async_request_refresh()

    async def async_set_normal(self) -> None:
        """Réinitialise le système en mode Normal."""
        self.mode = "Normal"
        self.date_action = None
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
        objectif = float(objectif_mm) if objectif_mm is not None else float(
            self.data.get("objectif_mm", 0.0)
        )

        async def _run_zone(entity_id: str, duration_minutes: float) -> None:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": entity_id}, blocking=True
            )
            try:
                await asyncio.sleep(max(duration_minutes, 0) * 60)
            finally:
                await self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": entity_id}, blocking=False
                )

        async def _sequence():
            for entity_id, rate in self._iter_zones_with_rate():
                if rate <= 0:
                    continue
                duration = objectif / rate
                if duration <= 0:
                    continue
                await _run_zone(entity_id, duration)

        self.hass.async_create_task(
            _sequence(), "gazon_intelligent_auto_irrigation_sequence"
        )
    def _get_conf(self, key: str) -> Any:
        """Récupère la valeur de configuration (options > data)."""
        return self.entry.options.get(key, self.entry.data.get(key))
