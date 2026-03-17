from __future__ import annotations

from datetime import date, datetime, timedelta
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
        bilan_hydrique = self._compute_bilan_hydrique(
            etp=etp_calcule,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            type_sol=type_sol,
        )
        scores = self._compute_internal_scores(
            phase_active=phase_active,
            bilan_hydrique=bilan_hydrique,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            humidite=humidite,
            temperature=temperature,
            etp=etp_calcule,
        )
        objectif_mm = self._compute_objectif_mm(
            bilan_hydrique=bilan_hydrique,
            phase_active=phase_active,
            score_hydrique=scores["score_hydrique"],
            score_stress=scores["score_stress"],
        )
        decision = self._compute_decision(
            phase_active=phase_active,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            humidite=humidite,
            temperature=temperature,
            etp=etp_calcule,
            objectif_mm=objectif_mm,
            jours_restants=jours_restants,
            score_hydrique=scores["score_hydrique"],
            score_stress=scores["score_stress"],
            score_tonte=scores["score_tonte"],
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
            "bilan_hydrique_mm": bilan_hydrique,
            "objectif_mm": objectif_mm,
            "score_hydrique": scores["score_hydrique"],
            "score_stress": scores["score_stress"],
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
            "score_tonte": decision["score_tonte"],
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

    def _compute_recent_watering_mm(self, days: int = 2) -> float:
        """Somme l'arrosage déclaré récent (mm) sur une fenêtre glissante."""
        today = date.today()
        total = 0.0
        for item in self.history:
            if item.get("type") != "arrosage":
                continue
            raw_date = item.get("date")
            if not raw_date:
                continue
            try:
                d = date.fromisoformat(raw_date)
            except ValueError:
                continue
            delta = (today - d).days
            if delta < 0 or delta > days:
                continue
            mm = item.get("objectif_mm")
            if mm is None:
                continue
            try:
                total += float(mm)
            except (TypeError, ValueError):
                continue
        return total

    def _compute_bilan_hydrique(
        self,
        etp: float | None,
        pluie_24h: float | None,
        pluie_demain: float | None,
        type_sol: str,
    ) -> float:
        """Calcule un déficit hydrique (mm) centré sur ETP et apports récents."""
        etp_j = max(0.0, etp or 0.0)
        pluie_j = max(0.0, pluie_24h or 0.0)
        pluie_j1 = max(0.0, pluie_demain or 0.0)
        arrosage_recent = self._compute_recent_watering_mm(days=2)

        # Réserve utile approximative selon le sol (mm).
        reserve_sol = {
            "sableux": 8.0,
            "limoneux": 12.0,
            "argileux": 16.0,
        }.get(type_sol, 12.0)

        # Bilan 48h: évapotranspiration - apports utiles (pluie + arrosage).
        demande_48h = etp_j * 2.0
        apports_utiles = (pluie_j * 0.85) + (pluie_j1 * 0.35) + arrosage_recent
        deficit = max(0.0, demande_48h - apports_utiles)

        # Plus la réserve est grande, plus le déficit est amorti.
        deficit_pondere = deficit * (12.0 / reserve_sol)
        return round(max(0.0, min(deficit_pondere, 20.0)), 1)

    def _compute_objectif_mm(
        self,
        bilan_hydrique: float,
        phase_active: str,
        score_hydrique: int,
        score_stress: int,
    ) -> float:
        """Calcule l'objectif d'arrosage en mm à partir des scores internes."""

        if phase_active in ("Traitement", "Hivernage"):
            return 0.0

        # Noyau de décision: déficit + score hydrique + stress.
        base_mm = (bilan_hydrique * 0.65) + (score_hydrique * 0.045) + (score_stress * 0.015)
        if score_hydrique < 15:
            base_mm *= 0.2

        # Les phases deviennent des profils (cadre) et non le moteur principal.
        profile = {
            "Normal": (1.00, 0.0, 12.0),
            "Sursemis": (0.55, 0.5, 3.0),
            "Fertilisation": (0.75, 0.5, 3.5),
            "Biostimulant": (0.70, 0.4, 3.0),
            "Agent Mouillant": (0.85, 0.8, 4.0),
            "Scarification": (0.80, 0.6, 3.5),
        }.get(phase_active, (1.00, 0.0, 12.0))

        mult, min_mm, max_mm = profile
        objectif = base_mm * mult
        if score_hydrique < 20 and score_stress < 35:
            min_mm = 0.0
        objectif = max(min_mm, min(max_mm, objectif))
        return round(max(0.0, objectif), 1)

    def _compute_internal_scores(
        self,
        phase_active: str,
        bilan_hydrique: float,
        pluie_24h: float | None,
        pluie_demain: float | None,
        humidite: float | None,
        temperature: float | None,
        etp: float | None,
    ) -> dict[str, int]:
        """Calcule les scores internes 0..100 pour piloter la décision."""
        pluie_24h = pluie_24h or 0.0
        pluie_demain = pluie_demain or 0.0
        humidite = humidite or 0.0
        temperature = temperature or 0.0
        etp = etp or 0.0
        arrosage_recent = self._compute_recent_watering_mm(days=1)

        # Besoin hydrique structurel: déficit + climat + compensation pluie/arrosage.
        score_hydrique = bilan_hydrique * 5.0
        if etp >= 5:
            score_hydrique += 12
        elif etp >= 4:
            score_hydrique += 8
        elif etp >= 3:
            score_hydrique += 4
        if pluie_demain >= 8:
            score_hydrique -= 24
        elif pluie_demain >= 5:
            score_hydrique -= 16
        elif pluie_demain >= 2:
            score_hydrique -= 8
        if arrosage_recent >= 4:
            score_hydrique -= 18
        elif arrosage_recent >= 2:
            score_hydrique -= 10
        elif arrosage_recent > 0:
            score_hydrique -= 5
        if phase_active == "Sursemis":
            score_hydrique += 8
        elif phase_active == "Scarification":
            score_hydrique += 6
        score_hydrique = int(max(0.0, min(score_hydrique, 100.0)))

        # Stress global du gazon: thermique + hygrométrie + contexte phase.
        score_stress = 0.0
        if temperature >= 34:
            score_stress += 36
        elif temperature >= 30:
            score_stress += 26
        elif temperature >= 27:
            score_stress += 14
        if etp >= 5:
            score_stress += 24
        elif etp >= 4:
            score_stress += 16
        elif etp >= 3:
            score_stress += 8
        if humidite <= 35:
            score_stress += 18
        elif humidite <= 45:
            score_stress += 10
        elif humidite >= 90:
            score_stress += 10
        elif humidite >= 82:
            score_stress += 6
        if pluie_24h >= 10:
            score_stress += 14
        elif pluie_24h >= 6:
            score_stress += 8
        if phase_active in {"Sursemis", "Scarification", "Traitement"}:
            score_stress += 15
        elif phase_active in {"Fertilisation", "Biostimulant", "Agent Mouillant"}:
            score_stress += 6
        if pluie_demain >= 8 and temperature >= 30:
            score_stress -= 5
        score_stress = int(max(0.0, min(score_stress, 100.0)))

        # Décision tonte: croise humidité du sol/surface + stress + phase.
        score_tonte = 0.0
        if pluie_24h >= 6:
            score_tonte += 30
        elif pluie_24h >= 3:
            score_tonte += 18
        if pluie_demain >= 5:
            score_tonte += 12
        elif pluie_demain >= 2:
            score_tonte += 6
        if humidite >= 88:
            score_tonte += 16
        elif humidite >= 78:
            score_tonte += 8
        if arrosage_recent >= 3:
            score_tonte += 12
        elif arrosage_recent > 0:
            score_tonte += 6
        if phase_active == "Sursemis":
            score_tonte += 45
        elif phase_active in {"Traitement", "Hivernage"}:
            score_tonte += 38
        elif phase_active != "Normal":
            score_tonte += 18
        score_tonte += score_stress * 0.35
        score_tonte = int(max(0.0, min(score_tonte, 100.0)))

        return {
            "score_hydrique": score_hydrique,
            "score_stress": score_stress,
            "score_tonte": score_tonte,
        }

    def _compute_decision(
        self,
        phase_active: str,
        pluie_24h: float | None,
        pluie_demain: float | None,
        humidite: float | None,
        temperature: float | None,
        etp: float | None,
        objectif_mm: float,
        jours_restants: int,
        score_hydrique: int,
        score_stress: int,
        score_tonte: int,
    ) -> dict[str, Any]:
        pluie_24h = pluie_24h or 0.0
        pluie_demain = pluie_demain or 0.0
        humidite = humidite or 0.0
        temperature = temperature or 0.0
        etp = etp or 0.0
        arrosage_recent = self._compute_recent_watering_mm(days=1)
        now_hour = datetime.now().hour
        prochain_creneau = "ce matin" if now_hour < 9 else "demain matin"

        if score_hydrique >= 75 or score_stress >= 80:
            urgence = "haute"
        elif score_hydrique >= 40 or score_stress >= 55:
            urgence = "moyenne"
        else:
            urgence = "faible"

        if phase_active == "Traitement":
            return {
                "tonte_autorisee": False,
                "arrosage_auto_autorise": False,
                "arrosage_recommande": False,
                "type_arrosage": "bloque",
                "arrosage_conseille": "personnalise",
                "raison_decision": "Traitement actif: tonte et arrosage bloqués.",
                "conseil_principal": f"Laisser agir le traitement encore {jours_restants} jour(s).",
                "action_recommandee": "Surveiller l'état du gazon sans intervention hydrique.",
                "action_a_eviter": "Tondre ou arroser.",
                "urgence": "faible",
                "score_tonte": score_tonte,
            }
        if phase_active == "Hivernage":
            return {
                "tonte_autorisee": False,
                "arrosage_auto_autorise": False,
                "arrosage_recommande": False,
                "type_arrosage": "bloque",
                "arrosage_conseille": "personnalise",
                "raison_decision": "Hivernage actif: repos végétatif.",
                "conseil_principal": "Limiter les interventions et éviter les coupes stressantes.",
                "action_recommandee": "Surveiller uniquement.",
                "action_a_eviter": "Arrosages fréquents.",
                "urgence": "faible",
                "score_tonte": score_tonte,
            }
        if phase_active == "Sursemis":
            passages = 3 if objectif_mm >= 2 else 2
            return {
                "tonte_autorisee": False,
                "arrosage_auto_autorise": False,
                "arrosage_recommande": objectif_mm > 0,
                "type_arrosage": "manuel_frequent",
                "arrosage_conseille": "personnalise",
                "raison_decision": (
                    f"Sursemis actif + déficit hydrique {objectif_mm} mm. "
                    f"Pluie J+1 prévue: {pluie_demain:.1f} mm."
                ),
                "conseil_principal": f"Arroser {prochain_creneau} en {passages} passages courts.",
                "action_recommandee": f"Appliquer {objectif_mm} mm fractionnés ({passages}x).",
                "action_a_eviter": "Tondre avant levée complète.",
                "urgence": "haute" if score_hydrique >= 45 else "moyenne",
                "score_tonte": score_tonte,
            }

        tonte_ok = score_tonte < 45 and score_stress < 70
        auto_ok = phase_active in {"Normal", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"}
        recommande = score_hydrique >= 30 and objectif_mm > 0
        if not tonte_ok:
            if humidite >= 85:
                tonte_reason = "Humidité trop élevée: pelouse humide."
            elif pluie_24h >= 3:
                tonte_reason = "Pluie récente: sol encore humide."
            elif arrosage_recent > 0:
                tonte_reason = "Arrosage récent: attendre un ressuyage."
            elif temperature >= 30 and etp >= 4:
                tonte_reason = "Stress thermique élevé: limiter la tonte."
            else:
                tonte_reason = "Conditions défavorables à la tonte."
        else:
            tonte_reason = "Fenêtre tonte acceptable."

        pluie_significative = pluie_24h >= 4 or pluie_demain >= 4
        pluie_compensatrice = recommande and pluie_demain >= max(2.0, objectif_mm * 0.8)
        stress_thermique = temperature >= 30 and etp >= 4
        humidite_haute = humidite >= 85

        if phase_active == "Normal":
            if not recommande:
                if pluie_demain >= 2:
                    conseil_principal = (
                        "Pas d'arrosage aujourd'hui: la pluie prévue couvre le besoin court terme."
                    )
                    action_recommandee = "Laisser la pluie agir puis réévaluer demain."
                    action_a_eviter = "Cumuler pluie + arrosage sans contrôle."
                else:
                    conseil_principal = "Pas d'arrosage nécessaire pour le moment."
                    action_recommandee = "Réévaluer au prochain cycle météo."
                    action_a_eviter = "Arroser par réflexe."
            else:
                if pluie_compensatrice:
                    conseil_principal = (
                        "Reporter l'arrosage: la pluie de demain peut compenser une grande partie du déficit."
                    )
                    action_recommandee = (
                        f"Réduire l'apport à {max(0.0, round(objectif_mm * 0.4, 1))} mm maximum aujourd'hui."
                    )
                    action_a_eviter = "Lancer un cycle complet avant l'épisode pluvieux."
                elif stress_thermique:
                    conseil_principal = (
                        f"Arroser {prochain_creneau} en deux passages pour limiter l'évaporation."
                    )
                    action_recommandee = f"Appliquer {objectif_mm} mm fractionnés (2x)."
                    action_a_eviter = "Arroser entre 11h et 18h."
                elif humidite_haute:
                    conseil_principal = "Attendre un léger ressuyage avant arrosage."
                    action_recommandee = (
                        f"Programmer {objectif_mm} mm en fin de nuit si l'humidité baisse."
                    )
                    action_a_eviter = "Arroser immédiatement sur pelouse saturée."
                else:
                    conseil_principal = (
                        f"Arroser {prochain_creneau}: déficit hydrique estimé à {objectif_mm} mm."
                    )
                    action_recommandee = f"Appliquer {objectif_mm} mm sur les zones actives."
                    action_a_eviter = "Arroser en pleine journée."
        else:
            if not recommande:
                conseil_principal = f"Phase {phase_active}: pas d'arrosage requis pour l'instant."
                action_recommandee = "Surveiller les capteurs et l'évolution météo."
            elif phase_active == "Fertilisation":
                conseil_principal = "Fertilisation active: humidifier légèrement pour activer l'apport."
                action_recommandee = f"Appliquer {objectif_mm} mm en 1 à 2 passages."
            elif phase_active == "Scarification":
                conseil_principal = "Scarification: maintenir une humidité stable sans détremper."
                action_recommandee = f"Appliquer {objectif_mm} mm en apports courts."
            elif phase_active == "Agent Mouillant":
                conseil_principal = "Agent mouillant: faire pénétrer l'eau plus en profondeur."
                action_recommandee = f"Appliquer {objectif_mm} mm en cycle allongé."
            elif phase_active == "Biostimulant":
                conseil_principal = "Biostimulant: conserver un niveau hydrique modéré."
                action_recommandee = f"Appliquer {objectif_mm} mm en un passage."
            else:
                conseil_principal = f"Phase {phase_active}: maintenir un arrosage maîtrisé {prochain_creneau}."
                action_recommandee = f"Appliquer {objectif_mm} mm en tenant compte de l'humidité actuelle."
            action_a_eviter = "Tondre sur sol humide." if not tonte_ok else "Intervention agressive inutile."

        facteurs = [f"ETP={etp:.1f}", f"pluie24h={pluie_24h:.1f}", f"pluieJ+1={pluie_demain:.1f}"]
        if pluie_significative:
            facteurs.append("risque d'humidité élevé")
        if stress_thermique:
            facteurs.append("stress thermique")
        if arrosage_recent > 0:
            facteurs.append(f"arrosage récent={arrosage_recent:.1f} mm")
        if humidite_haute:
            facteurs.append("humidité air élevée")
        facteurs_txt = ", ".join(facteurs)

        return {
            "tonte_autorisee": tonte_ok,
            "arrosage_auto_autorise": auto_ok,
            "arrosage_recommande": recommande,
            "type_arrosage": "auto" if auto_ok else "personnalise",
            "arrosage_conseille": "auto" if phase_active == "Normal" else "personnalise",
            "raison_decision": (
                f"Phase {phase_active} active ({jours_restants} j restants). "
                f"Scores H={score_hydrique}/S={score_stress}/T={score_tonte}. {facteurs_txt}. {tonte_reason}"
            ),
            "conseil_principal": conseil_principal,
            "action_recommandee": action_recommandee,
            "action_a_eviter": action_a_eviter,
            "urgence": urgence if recommande else "faible",
            "score_tonte": score_tonte,
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
