from __future__ import annotations

from datetime import date, timedelta
from datetime import datetime, timezone
from math import isfinite
import asyncio
import logging
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    DEFAULT_AUTO_IRRIGATION_ENABLED,
    DEFAULT_EVENING_COOLING_ENABLED,
    DEFAULT_MOWER_COORDINATION_ENABLED,
    DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES,
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
    CONF_HAUTEUR_COUPE_TONDEUSE_MM,
    CONF_HAUTEUR_MAX_TONDEUSE_CM,
    CONF_HAUTEUR_MIN_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
    CONF_TYPE_SOL,
    DEFAULT_TYPE_SOL,
    WATERING_SESSION_END_GRACE_SECONDS,
    WATERING_SESSION_MIN_DURATION_SECONDS,
    WATERING_SESSION_MIN_SEGMENT_SECONDS,
    OBJECTIVE_SCOPE_SURFACE_CYCLE,
    WATERING_STRATEGY_SEMIS_FREQUENT,
    PLUIE_SOURCE_INDISPONIBLE,
    PLUIE_SOURCE_NON_DISPONIBLE,
)
from .decision_models import DecisionResult
from .gazon_brain import GazonBrain
from .decision_risk import compute_fungal_risk as _compute_fungal_risk
from .memory import compute_application_state
from .mower_adapter import build_mower_context, derive_related_entity_id
from .mower_coordination import build_mower_coordination_context
from .entity_ids import public_entity_id, resolve_entry_instance_slug
from .shared_state import get_shared_state, resolve_effective_config
from .const import SHARED_WEATHER_CONFIG_KEYS
from .water import (
    compute_recent_watering_mm,
    compute_eto_hourly as water_compute_eto_hourly,
    _zone_session_surface_mm,
    _zone_session_total_mm,
)
from .weather_adapter import WeatherAdapter
from .watering_plan import WateringPlan, build_watering_plan, normalize_existing_plan
from .watering_policy import resolve_semis_stage_program

_LOGGER = logging.getLogger(__name__)


def _clean_empty_attrs(attrs: dict[str, Any]) -> dict[str, Any] | None:
    """Retire les valeurs vides (None, '', {}, []) d'un dict d'attributs.

    Helper commun utilisé par get_used_entities_attributes et partout où
    on nettoie des attributs avant de les exposer à Home Assistant.
    Identique à _clean_public_attrs dans sensor.py — source unique de vérité.
    """
    clean = {key: value for key, value in attrs.items() if value not in (None, "", {}, [])}
    return clean or None


AUTO_IRRIGATION_AUTO_SOURCES = {
    "auto_irrigation",
    "application_technique",
    "application_technique_auto",
}

AUTO_IRRIGATION_CHECK_INTERVAL = timedelta(minutes=2)
# Cooldown anti-relance : après la fin d'un cycle auto, aucun NOUVEAU gros cycle ne peut
# repartir avant ce délai. La fenêtre du soir (petit rafraîchissement canicule) en est
# exemptée. Objectif : un seul gros cycle « du matin » par jour, fini les relances en
# boucle observées en canicule (le déclencheur repartait ~10 s après la fin du cycle).
AUTO_IRRIGATION_RELAUNCH_COOLDOWN = timedelta(hours=6)

# États Home Assistant qui signifient « pas de mesure » et ne doivent JAMAIS être traités comme
# une valeur (ni exposés en attribut, ni interprétés comme un code d'erreur).
_UNAVAILABLE_STATES: frozenset[str] = frozenset({"unavailable", "unknown", "none"})

# Motifs de blocage tondeuse qui NE SE RÉSOLVENT PAS d'eux-mêmes : robot à l'arrêt hors station,
# entité indisponible, tondeuse introuvable ou ambiguë. Seuls ceux-là ouvrent l'arrosage de
# détresse (cf. `_should_launch_auto_irrigation`) — « tonte en cours » et « retour à la station »
# en sont volontairement exclus : ils se terminent seuls et arroser alors tremperait le robot en
# plein cycle, ce que la coordination existe précisément pour éviter.
# Seuls états de `sun.sun` qui portent une information : tout le reste (`unavailable`, `unknown`)
# signifie « position du soleil inconnue », pas « il fait nuit ».
_SUN_KNOWN_STATES: frozenset[str] = frozenset({"above_horizon", "below_horizon"})

_MOWER_BLOCK_REASONS_PERSISTANTS: frozenset[str] = frozenset(
    {"mower_not_stowed", "mower_unreliable", "ambiguous", "missing", "configured_missing"}
)

# DURÉE MINIMALE du blocage tondeuse avant que l'arrosage de détresse s'autorise.
# Le code de motif ne suffit pas à prouver la persistance : au redémarrage de Home Assistant,
# l'intégration démarre AVANT celle de la tondeuse et lit son entité comme absente pendant
# quelques secondes — `configured_missing`, donc un motif classé « persistant ».
# Constaté le 29/07/2026 à 03:11:34 : l'exception s'est armée sur cette absence transitoire, alors
# que le robot était à la station, batterie à 100 %. Elle contourne à la fois le blocage tondeuse
# ET la fenêtre horaire (`fenetre_optimale`, cf. `_should_launch_auto_irrigation`) : sans ce délai,
# un simple redémarrage en pleine nuit avec un déficit critique pouvait déclencher un arrosage à
# 3 h du matin, à rebours de la règle « toujours arroser à l'aube ».
# Un robot réellement coincé dehors le reste des heures ; une course au démarrage dure des
# secondes. 30 minutes séparent les deux sans retarder sensiblement un vrai cas de détresse.
_MOWER_DISTRESS_MIN_BLOCK_MINUTES: float = 30.0

# Fenêtres pour lesquelles un renoncement à arroser est un vrai REFUS, digne d'être tracé.
# Doit rester un sous-ensemble de `POSSIBLE_FENETRE_OPTIMALE_VALUES` (decision_models.py) :
# une valeur inventée ici désactive silencieusement la trace pour cette fenêtre.
_SKIP_RECORDED_WINDOWS: frozenset[str] = frozenset({"ce_matin", "demain_matin", "maintenant", "soir"})

# Journée civile de repli quand le lever/coucher du soleil est inconnu (`sun.sun` pas encore
# publié au démarrage). 06:00 → 21:00 : volontairement large, elle n'a qu'à tenir quelques
# secondes. Voir `_et_elapsed_fraction` pour ce que l'ancien repli à 1.0 a coûté.
_FALLBACK_DAY_START_MINUTE: int = 6 * 60
_FALLBACK_DAY_END_MINUTE: int = 21 * 60

_COORDINATOR_SNAPSHOT_KEYS: tuple[str, ...] = (
    "mode",
    "phase_active",
    "objectif_mm",
    "tonte_autorisee",
    "tonte_statut",
    "arrosage_recommande",
    "watering_cause",
    # Fractionnement : _get_canonical_watering_plan et la construction des sessions les lisent
    # dans self.data. Ils ne figuraient pas ici, donc self.data.get(...) rendait toujours None →
    # repli sur 1 passage / 0 min de pause : l'arrosage profond n'était JAMAIS fractionné en
    # pratique, malgré le calcul correct côté guidance (risque de ruissellement sur grosse dose).
    "watering_passages",
    "watering_pause_minutes",
    "type_arrosage",
    "conseil_principal",
    "action_recommandee",
    "action_a_eviter",
    "niveau_action",
    "fenetre_optimale",
    "risque_gazon",
    "risque_gazon_raisons",
    "phase_dominante",
    "phase_dominante_source",
    "sous_phase",
    "sous_phase_detail",
    "sous_phase_age_days",
    "sous_phase_progression",
    "hauteur_tonte_recommandee_cm",
    "hauteur_tonte_min_cm",
    "hauteur_tonte_max_cm",
    "hauteur_tonte_garde_fou_label",
    "tondeuse_source_entity",
    "tondeuse_nom",
    "tondeuse_etat_brut",
    "tondeuse_statut",
    "tondeuse_statut_libelle",
    "tondeuse_connectee",
    "tondeuse_prete",
    "tondeuse_raison",
    "tondeuse_en_charge",
    "tondeuse_pluie",
    "tondeuse_erreur",
    "tondeuse_erreur_libelle",
    "tondeuse_batterie",
    "tondeuse_prochain_depart",
    "tondeuse_prochain_depart_display",
    "tondeuse_hauteur_coupe_mm",
    "tondeuse_resolution_state",
    "tondeuse_resolution_reason",
    "tondeuse_resolution_candidate_count",
    "mower_coordination_enabled",
    "mower_coordination_ready",
    "mower_presence_state",
    "mower_presence_label",
    "mower_operation_state",
    "mower_operation_label",
    "mower_is_docked",
    "mower_is_outside",
    "mower_is_mowing",
    "mower_is_returning",
    "mower_is_safe_for_watering",
    "mower_reason_code",
    "mower_reason_label",
    "mower_battery",
    "mower_next_departure",
    "mower_resolution_state",
    "mower_resolution_reason",
    "mower_resolution_candidate_count",
    "watering_blocked_by_mower",
    "watering_block_reason_code",
    "watering_block_reason_label",
    "mowing_blocked_by_watering",
    "mowing_block_reason_code",
    "mowing_block_reason_label",
    "mowing_cooldown_remaining_minutes",
    "mowing_post_application_active",
    "mowing_is_overdue",
    "mowing_overdue_days",
    "mowing_overdue_factor",
    "gazon_hauteur_estimee_cm",
    "gazon_pousse_jour_cm",
    "mowing_watering_coordination",
    "mowing_watering_coordination_msg",
    "mowing_cooldown_after_watering_minutes",
    "semis_followup_state",
    "semis_followup_due_at",
    "semis_followup_due_display",
    "semis_cycles_completed_today",
    "semis_cycles_remaining_today",
    "semis_daily_cycles_target",
    "semis_cycle_spacing_minutes",
    "semis_last_cycle_at",
    "semis_last_cycle_display",
    "derniere_application",
    "application_type",
    "application_requires_watering_after",
    "application_post_watering_mm",
    "application_irrigation_block_hours",
    "application_label_notes",
    "application_post_watering_status",
    "application_block_until",
    "application_block_active",
    "application_post_watering_pending",
    "application_post_watering_remaining_mm",
    "season_label",
    "season_phase",
    "month_profile",
    "watering_bias",
    "mowing_bias",
    "intervention_bias",
    "risk_bias",
    "feedback_observation",
    "assistant",
    "intervention_recommendation",
    # LOT A — santé capteurs
    "sensor_health",
    # LOT B — urgence hydrique malgré blocage
    "irrigation_blocked_but_critical",
    "critical_deficit_mm",
    "critical_irrigation_reason",
    # LOT E — risque fongique
    "fungal_risk_level",
    "fungal_risk_score",
    "fungal_risk_reasons",
    "fungal_risk_evening_block",
    "fungal_risk_reduce_watering",
)


# Veilleur de vanne : cadence de contrôle pendant un segment d'arrosage, et nombre de
# relances tolérées avant d'abréger. Une seule relance : un relais qui retombe deux fois
# n'est plus un accident.
_ZONE_WATCH_INTERVAL_S = 15.0
_ZONE_WATCH_MAX_RELANCES = 1


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
        self.shared_state = get_shared_state(hass)
        self._loaded = False
        self.brain = GazonBrain()
        if self.shared_state is not None:
            self.brain.products = self.shared_state.products
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
        self._zone_tracking_resumed_at: datetime | None = None
        # Optionnel : `_ensure_irrigation_runtime_bootstrap` le remet à None puis le recrée
        # quand une boucle asyncio devient disponible.
        self._irrigation_launch_lock: asyncio.Lock | None = asyncio.Lock()
        self._latest_full_snapshot: dict[str, Any] | None = None
        self._runtime_state: dict[str, Any] = {
            "active_irrigation_session": None,
            "last_irrigation_execution": None,
            "last_auto_irrigation_reason": None,
            "last_auto_irrigation_completed_at": None,
            "auto_irrigation_safety_lock": False,
            # Garde anti-démarrage : reste False tant qu'aucun cycle de données sain
            # n'a eu lieu. Volontairement NON persisté → se réarme à chaque (re)démarrage.
            "auto_irrigation_bootstrap_complete": False,
        }

    def _current_datetime(self) -> datetime:
        now_getter = getattr(dt_util, "now", None)
        if callable(now_getter):
            current = now_getter()
            if isinstance(current, datetime):
                return current
        return datetime.now(timezone.utc)

    def _current_utc_datetime(self) -> datetime:
        utcnow_getter = getattr(dt_util, "utcnow", None)
        if callable(utcnow_getter):
            current = utcnow_getter()
            if isinstance(current, datetime):
                if current.tzinfo is None:
                    current = current.replace(tzinfo=timezone.utc)
                return current.astimezone(timezone.utc)
        current = self._current_datetime()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _current_date(self) -> date:
        return self._current_datetime().date()

    def _local_timezone(self):
        current = self._current_datetime()
        if isinstance(current, datetime) and current.tzinfo is not None:
            return current.tzinfo
        return timezone.utc

    def _local_datetime_text(self, value: Any) -> str | None:
        if value in (None, "", [], {}):
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        if isinstance(value, datetime):
            dt_value = value
        else:
            text = str(value).strip()
            if not text:
                return None
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                dt_value = datetime.fromisoformat(text)
            except ValueError:
                try:
                    return date.fromisoformat(text[:10]).strftime("%d/%m/%Y")
                except ValueError:
                    return text
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=self._local_timezone())
        return dt_value.astimezone(self._local_timezone()).strftime("%d/%m/%Y à %H:%M")

    async def _finalize_pending_irrigation_user_action(
        self,
        *,
        execution: dict[str, Any] | None,
        fallback_reason: str | None = None,
        persist_only: bool = False,
    ) -> None:
        if not isinstance(execution, dict):
            return
        execution_status = str(execution.get("status") or "").strip().lower()
        completion_status = str(execution.get("completion_status") or "").strip().lower()
        if execution_status != "completed" and not completion_status.startswith("completed"):
            return
        memory = self.memory if isinstance(getattr(self, "memory", None), dict) else {}
        latest_action = memory.get("derniere_action_utilisateur") if isinstance(memory, dict) else None
        if not isinstance(latest_action, dict):
            return
        if str(latest_action.get("state") or "").strip().lower() != "en_attente":
            return
        action = str(latest_action.get("action") or "").strip()
        if not action:
            return
        plan_type = latest_action.get("plan_type")
        zone_count = latest_action.get("zone_count")
        passages = latest_action.get("passages")
        # `execution` est garanti dict par la sortie anticipée en tête de fonction, et n'est pas
        # réaffecté entre-temps : le second `isinstance` était toujours vrai.
        source = str(execution.get("source") or "").strip().lower()
        reason = fallback_reason
        if not reason:
            if source == "application_technique_auto":
                reason = "Arrosage post-produit automatique exécuté avec succès."
            elif source == "auto_irrigation":
                reason = "Arrosage automatique exécuté avec succès."
            elif source in {"manual_irrigation", "manual_force"}:
                reason = "Arrosage manuel exécuté avec succès."
            elif source == "manual_application":
                reason = "Arrosage technique exécuté avec succès."
            else:
                reason = "Arrosage terminé avec succès."
        if persist_only:
            self.brain.record_user_action(
                action=action,
                state="ok",
                reason=reason,
                plan_type=plan_type,
                zone_count=zone_count,
                passages=passages,
            )
            await self._async_save_state()
            return
        await self.async_record_user_action(
            action=action,
            state="ok",
            reason=reason,
            plan_type=plan_type,
            zone_count=zone_count,
            passages=passages,
        )

    def _current_snapshot(self) -> dict[str, Any]:
        latest_full_snapshot = getattr(self, "_latest_full_snapshot", None)
        if isinstance(latest_full_snapshot, dict):
            return dict(latest_full_snapshot)
        data = getattr(self, "data", None)
        return dict(data) if isinstance(data, dict) else {}

    def _resolve_precipitation_inputs(
        self,
        *,
        pluie_24h_sensor: float | None,
        pluie_demain_sensor: float | None,
        forecast_summary: dict[str, Any],
    ) -> tuple[float | None, str, float | None, str]:
        forecast_pluie_24h = forecast_summary.get("forecast_pluie_24h")
        forecast_pluie_demain = forecast_summary.get("forecast_pluie_demain")
        # `pluie_24h` / `pluie_demain` sont OPTIONNELLES : ni capteur ni prévision n'est garanti,
        # et le libellé de source dit explicitement « non disponible » dans ce cas.
        pluie_24h: float | None
        pluie_demain: float | None
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
        return pluie_24h, pluie_24h_source, pluie_demain, pluie_demain_source

    def _resolve_temperature_inputs(
        self,
        *,
        weather_profile: dict[str, Any],
        forecast_summary: dict[str, Any],
    ) -> tuple[float | None, str, float | None]:
        temperature_source = "capteur"
        # VALIDER DÈS LA LECTURE. Cette valeur ne sert pas qu'à l'affichage : elle construit
        # `temperature_reference_hydrique`, qui pilote seule l'ET0 et donc les doses d'arrosage.
        # Elle n'était filtrée que plus loin, pour l'autre usage : un capteur qui déraille (glitch
        # Netatmo, défaut de câblage) à 80 °C était bien rejeté là-bas, mais avait déjà contaminé
        # la référence hydrique ici — d'où une ET0 délirante et un sur-arrosage.
        temperature = self._validate_sensor_value(
            self._get_float_state(self._get_conf(CONF_CAPTEUR_TEMPERATURE)),
            "temperature",
        )
        if temperature is None:
            weather_temperature = weather_profile.get("weather_temperature")
            weather_apparent_temperature = weather_profile.get("weather_apparent_temperature")
            if weather_temperature is not None:
                temperature = weather_temperature
                temperature_source = "weather"
            elif weather_apparent_temperature is not None:
                temperature = weather_apparent_temperature
                temperature_source = "weather"

        forecast_temperature_today = forecast_summary.get("forecast_temperature_today")
        if forecast_temperature_today is not None:
            try:
                forecast_temperature_today = float(forecast_temperature_today)
            except (TypeError, ValueError):
                forecast_temperature_today = None
            # Même garde-fou sur la prévision : elle pèse 70 % de la référence hydrique le matin
            # et sert de repli quand le capteur manque.
            forecast_temperature_today = self._validate_sensor_value(
                forecast_temperature_today, "temperature"
            )
        if forecast_temperature_today is not None:
            if temperature is None:
                temperature = forecast_temperature_today
                temperature_source = "meteo_forecast"
        elif temperature is None:
            temperature_source = "non disponible"

        temperature_reference_hydrique = None
        if forecast_temperature_today is not None and temperature is not None:
            current_hour = self._current_datetime().hour
            if current_hour < 12:
                temperature_reference_hydrique = (0.7 * forecast_temperature_today) + (0.3 * temperature)
            else:
                temperature_reference_hydrique = (0.3 * forecast_temperature_today) + (0.7 * temperature)
        elif forecast_temperature_today is not None:
            temperature_reference_hydrique = forecast_temperature_today
        elif temperature is not None:
            temperature_reference_hydrique = temperature
        if temperature_reference_hydrique is not None:
            temperature_reference_hydrique = round(float(temperature_reference_hydrique), 1)

        return temperature, temperature_source, temperature_reference_hydrique

    def _compute_hourly_eto(
        self,
        *,
        weather_profile: dict[str, Any],
        temperature: float | None,
        humidite: float | None,
        vent: float | None,
    ) -> dict[str, Any]:
        """ET0 de référence HORAIRE (mm/h) — FAO-56 Eq. 53, à partir des capteurs mesurés.

        Renvoie toujours un dict (jamais None) : `value` vaut None quand les entrées
        indispensables manquent, avec `reason` pour le diagnostic.

        ⚠️ Cette valeur PILOTE l'arrosage depuis la 0.19.0 — ce n'est pas un simple indicateur.
        Chaîne : `weather_profile["eto_hourly_mm_h"]` → `gazon_brain` (× Kc) → `soil_balance`
        (`_accumulate_elapsed_etp`, intégration au fil du temps) → réserve du sol → déplétion →
        seuil MAD → déclenchement et dose. `value = None` fait retomber le ledger sur le prorata
        de l'ET0 journalière (comportement d'avant la 0.19.0), jamais sur un débit nul.
        """
        latitude = weather_profile.get("ha_latitude")
        longitude = weather_profile.get("ha_longitude")
        if temperature is None or latitude is None or longitude is None:
            return {"value": None, "reason": "position ou température indisponible"}
        humidity = humidite if humidite is not None else weather_profile.get("weather_humidity")
        if humidity is None:
            return {"value": None, "reason": "humidité indisponible"}
        radiation = self._get_float_state(self._get_conf(CONF_CAPTEUR_RAYONNEMENT))
        pressure = self._get_float_state(self._get_conf(CONF_CAPTEUR_PRESSION))
        # BORNES DE PLAUSIBILITÉ. Le sélecteur de configuration filtre désormais par device_class,
        # mais une entrée déjà enregistrée peut porter une autre unité — et l'erreur est
        # silencieuse ET grave : un rayonnement lu en kW/m² (au lieu de W/m²) divise l'ET0 par ~5,
        # le sol ne sèche plus et l'arrosage ne part jamais, même en canicule. Hors bornes → on
        # ignore la valeur et on retombe sur le modèle, ce que le diagnostic rend visible.
        if radiation is not None and not (0.0 <= radiation <= 1400.0):
            _LOGGER.warning(
                "Rayonnement hors bornes (%.1f) — attendu en W/m² (0-1400). Valeur ignorée : "
                "vérifie l'unité du capteur configuré.",
                radiation,
            )
            radiation = None
        if pressure is not None and not (800.0 <= pressure <= 1100.0):
            _LOGGER.warning(
                "Pression hors bornes (%.1f) — attendue en hPa (800-1100). Valeur ignorée : "
                "vérifie l'unité du capteur configuré.",
                pressure,
            )
            pressure = None
        wind = vent if vent is not None else weather_profile.get("weather_wind_speed")
        cloud = weather_profile.get("weather_cloud_coverage")
        # Un capteur peut publier `nan` : `_get_float_state` le laisse passer (float("nan") ne lève
        # pas), et un NaN se propagerait jusqu'au ledger où il gèlerait le débit de la réserve en
        # silence. On valide donc la finitude de TOUTES les entrées numériques avant de calculer.
        for _candidate in (temperature, humidity, radiation, pressure, wind, cloud):
            if _candidate is not None and not isfinite(float(_candidate)):
                return {"value": None, "reason": "entrée non finie"}
        if radiation is None and cloud is None:
            # Ni rayonnement mesuré, ni couverture nuageuse : le modèle supposerait un ciel à
            # 50 % (soit quasi clair, r_nu ≈ 0,93) et viderait la réserve à ce rythme TOUS LES
            # JOURS, pluie comprise → arrosage prématuré. Mieux vaut rendre la main au prorata
            # de l'ET0 journalière, qui tient compte de la météo du jour.
            return {"value": None, "reason": "rayonnement et nébulosité indisponibles"}
        now_utc = self._current_datetime().astimezone(timezone.utc)
        try:
            value = water_compute_eto_hourly(
                temperature=float(temperature),
                humidity=float(humidity),
                # Pression standard au niveau de la mer si non mesurée : n'intervient que via la
                # constante psychrométrique, dont l'effet reste faible devant le rayonnement.
                pressure_hpa=float(pressure) if pressure is not None else 1013.0,
                wind_kmh=float(wind) if wind is not None else 5.0,
                # Un capteur de vent configuré est supposé en km/h (standard HA, ex. Netatmo) ;
                # sinon on transmet l'unité déclarée par l'entité météo, qui peut être en m/s.
                wind_unit="km/h" if vent is not None else weather_profile.get("weather_wind_speed_unit"),
                radiation_wm2=float(radiation) if radiation is not None else None,
                cloud_pct=float(cloud) if cloud is not None else None,
                latitude=float(latitude),
                longitude=float(longitude),
                day_of_year=now_utc.timetuple().tm_yday,
                hour_utc=now_utc.hour + now_utc.minute / 60.0,
            )
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            # Entrées non numériques ou températures absurdes (ZeroDivisionError à −237,3 °C,
            # OverflowError en dessous) : ce chemin tourne toutes les 2 min, il ne doit JAMAIS
            # faire tomber le cycle du coordinateur.
            return {"value": None, "reason": "entrées invalides"}
        if not isfinite(value):
            return {"value": None, "reason": "taux non fini"}
        # NB : un taux NUL est LÉGITIME (la nuit, sans rayonnement) et doit être conservé — le
        # traiter comme absent ferait retomber le ledger sur le prorata, qui à 21 h vaut la
        # journée ENTIÈRE estimée et écraserait le cumul mesuré.
        return {
            "value": round(value, 4),
            "radiation_source": "capteur" if radiation is not None else "modele_nuages",
            "radiation_wm2": radiation,
            "pressure_source": "capteur" if pressure is not None else "standard_1013",
            "wind_kmh": wind,
        }

    def _build_public_snapshot_data(
        self,
        snapshot: dict[str, Any],
        *,
        pluie_demain_source: str,
        temperature: float | None,
        temperature_source: str,
        temperature_reference_hydrique: float | None,
        forecast_summary: dict[str, Any],
        et0_source: str,
        eto_hourly: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        eto_hourly = eto_hourly or {}
        payload: dict[str, Any] = {
            "eto_horaire_mm_h": eto_hourly.get("value"),
            "eto_horaire_diagnostic": eto_hourly,
            "pluie_demain_source": pluie_demain_source,
            "temperature_source": temperature_source,
            "temperature_reference_hydrique": temperature_reference_hydrique,
            "forecast_temperature_today": forecast_summary.get("forecast_temperature_today"),
            "et0_source": et0_source,
            "forecast_pluie_j2": forecast_summary.get("forecast_pluie_j2"),
            "forecast_pluie_3j": forecast_summary.get("forecast_pluie_3j"),
            "forecast_probabilite_max_3j": forecast_summary.get("forecast_probabilite_max_3j"),
            "temperature": temperature,
        }
        for key in _COORDINATOR_SNAPSHOT_KEYS:
            payload[key] = snapshot.get(key)
        payload["auto_irrigation_enabled"] = snapshot.get(
            "auto_irrigation_enabled",
            self.auto_irrigation_enabled,
        )
        # Diagnostic « pourquoi l'arrosage auto ne part pas » : raison du dernier passage
        # de _should_launch_auto_irrigation (mise à jour par _maybe_schedule juste avant)
        # + état du verrou de sécurité. Exploités par le capteur de blocage.
        last_reason = self._runtime_state.get("last_auto_irrigation_reason")
        payload["auto_irrigation_block_reason"] = (
            last_reason.get("reason") if isinstance(last_reason, dict) else None
        )
        payload["auto_irrigation_safety_lock"] = bool(
            self._runtime_state.get("auto_irrigation_safety_lock")
        )
        return payload

    async def _async_update_data(self) -> dict[str, Any]:
        """Récupère et calcule les données exposées par l'intégration."""
        if not self._loaded:
            await self._async_load_state()
            self._loaded = True

        weather_entity_id = self._get_conf(CONF_ENTITE_METEO)
        weather_profile = self._get_weather_profile(weather_entity_id)
        try:
            _ha_conf = getattr(getattr(self, "hass", None), "config", None)
            _ha_lat = getattr(_ha_conf, "latitude", None) if _ha_conf is not None else None
            _ha_lon = getattr(_ha_conf, "longitude", None) if _ha_conf is not None else None
            if _ha_lat is not None:
                weather_profile["ha_latitude"] = float(_ha_lat)
                weather_profile["ha_day_of_year"] = self._current_date().timetuple().tm_yday
            # Longitude : requise par l'ET0 HORAIRE (angle horaire solaire, FAO-56 Eq. 28).
            # La latitude seule suffit au calcul journalier, pas au pas de temps horaire.
            if _ha_lon is not None:
                weather_profile["ha_longitude"] = float(_ha_lon)
        except Exception:  # noqa: BLE001 — ne jamais bloquer le cycle sur une lat manquante
            pass
        pluie_24h_sensor = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_24H))
        pluie_demain_sensor = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_DEMAIN))
        forecast_summary = await self._get_weather_forecast_summary(weather_entity_id)
        forecast_pluie_j2 = forecast_summary.get("forecast_pluie_j2")
        forecast_pluie_3j = forecast_summary.get("forecast_pluie_3j")
        forecast_probabilite_max_3j = forecast_summary.get("forecast_probabilite_max_3j")
        sun_context = self._get_sun_context()
        sunset_minute = self._sunset_minute_from_context(sun_context)
        if sunset_minute is not None:
            # Transmis à la guidance (via weather_profile) pour le garde-fou « séchage
            # avant la nuit » de l'arrosage du soir en canicule.
            weather_profile["sunset_minute"] = sunset_minute
        # Fraction d'ET du jour déjà écoulée (affichage de la réserve : descente progressive).
        weather_profile["et_elapsed_fraction"] = self._et_elapsed_fraction(sun_context)
        pluie_24h_sensor = self._validate_sensor_value(pluie_24h_sensor, "pluie")
        pluie_demain_sensor = self._validate_sensor_value(pluie_demain_sensor, "pluie")
        pluie_24h, pluie_24h_source, pluie_demain, pluie_demain_source = self._resolve_precipitation_inputs(
            pluie_24h_sensor=pluie_24h_sensor,
            pluie_demain_sensor=pluie_demain_sensor,
            forecast_summary=forecast_summary,
        )
        raw_temperature, temperature_source, temperature_reference_hydrique = self._resolve_temperature_inputs(
            weather_profile=weather_profile,
            forecast_summary=forecast_summary,
        )
        temperature = self._validate_sensor_value(raw_temperature, "temperature")
        if temperature is None and raw_temperature is not None:
            temperature_source = "non disponible"
        etp_capteur = self._validate_sensor_value(
            self._get_float_state(self._get_conf(CONF_CAPTEUR_ETP)), "etp"
        )
        if etp_capteur is not None:
            et0_source = "capteur"
        elif weather_profile.get("ha_latitude") is not None:
            et0_source = "fallback_pm_location"
        else:
            et0_source = "fallback_pm"
        humidite = self._validate_sensor_value(
            self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE)), "humidite"
        )
        if humidite is None:
            humidite = weather_profile.get("weather_humidity")
        humidite_sol = self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE_SOL))
        vent = self._get_float_state(self._get_conf(CONF_CAPTEUR_VENT))
        if vent is None:
            vent = weather_profile.get("weather_wind_speed")
        rosee = self._get_float_state(self._get_conf(CONF_CAPTEUR_ROSEE))
        if rosee is None:
            rosee = self._estimate_rosee(weather_profile, temperature, humidite)
        # ET0 HORAIRE (FAO-56 Eq. 53) — ⚠️ ENTRE DANS LA DÉCISION depuis la 0.19.0 : publiée juste
        # en dessous dans `weather_profile`, elle est convertie en ETc par gazon_brain puis
        # INTÉGRÉE PAR LE LEDGER pour débiter la réserve du sol (donc la dose et le déclenchement).
        # Ne pas la traiter comme un simple diagnostic : la retirer casserait le bilan sol.
        eto_hourly = self._compute_hourly_eto(
            weather_profile=weather_profile,
            temperature=temperature,
            humidite=humidite,
            vent=vent,
        )
        # Transmis au bilan sol (via gazon_brain) : le ledger intègre ce taux au fil du temps
        # plutôt que d'étaler l'ET0 journalière estimée. Absent → repli prorata (historique).
        weather_profile["eto_hourly_mm_h"] = eto_hourly.get("value")
        hauteur_gazon = self._get_float_state(self._get_conf(CONF_CAPTEUR_HAUTEUR_GAZON))
        retour_arrosage_sensor = self._get_float_state(self._get_conf(CONF_CAPTEUR_RETOUR_ARROSAGE))
        if retour_arrosage_sensor is not None and retour_arrosage_sensor > 0:
            retour_arrosage = retour_arrosage_sensor
        else:
            # Choix explicite (Kévin, 25/06/2026) : arrosages EXTERNES (`zone_session`) totalement
            # ignorés → ils ne reviennent pas non plus par le « retour d'arrosage » (qui alimente
            # le modèle déficit). Seuls les arrosages pilotés par l'intégration sont pris en compte.
            retour_arrosage_today = compute_recent_watering_mm(
                self.history, today=self._current_date(), days=0, include_external=False
            )
            # None = aucun retour relevé aujourd'hui (et non « zéro millimètre »).
            retour_arrosage = retour_arrosage_today if retour_arrosage_today > 0 else None  # type: ignore[assignment]
        type_sol = self._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL
        hauteur_min_tondeuse_cm = self._get_float_conf(
            CONF_HAUTEUR_MIN_TONDEUSE_CM,
            DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
        )
        hauteur_max_tondeuse_cm = self._get_float_conf(
            CONF_HAUTEUR_MAX_TONDEUSE_CM,
            DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
        )
        mower_context = self._build_mower_snapshot()
        runtime_context = self._build_runtime_context()
        current_dt = self._current_datetime()
        snapshot = self.brain.compute_snapshot(
            today=self._current_date(),
            # ⚠️ HEURE DÉCIMALE, pas l'heure entière. Avec `current_dt.hour`, la pousse du
            # gazon et les fenêtres n'avançaient que par PALIERS D'UNE HEURE : mesuré le
            # 31/07/2026, `jour_cm` valait exactement 0,0246 à 01 h 56 comme à 01 h 58,
            # puis sautait à 0,0505 à 02 h. Aucune comparaison d'heure n'est une égalité
            # (uniquement des < et >=), le flottant est donc sans effet de bord.
            hour_of_day=current_dt.hour + current_dt.minute / 60.0,
            temperature=temperature,
            forecast_temperature_today=forecast_summary.get("forecast_temperature_today"),
            temperature_source=temperature_source,
            temperature_reference_hydrique=temperature_reference_hydrique,
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
            et0_source=et0_source,
            sun_context=sun_context,
            mower_context=mower_context,
            runtime_context=runtime_context,
        )
        snapshot.update(runtime_context)
        # LOT A — santé capteurs (calculé ici pour garantir la présence dans coordinator.data)
        snapshot["sensor_health"] = {
            "temperature_valid": temperature is not None,
            # Tester le CAPTEUR, pas la valeur résolue : `pluie_24h` reprend la valeur du capteur
            # quand il en a une, et retombe sur la prévision sinon — l'expression d'origine
            # (`pluie_24h is not None or pluie_24h_sensor is None`) était donc toujours vraie et le
            # voyant ne pouvait jamais signaler un capteur pluie en panne. Même forme que etp_valid.
            "pluie_valid": pluie_24h_sensor is not None or self._get_conf(CONF_CAPTEUR_PLUIE_24H) is None,
            "etp_valid": etp_capteur is not None or self._get_conf(CONF_CAPTEUR_ETP) is None,
            "humidity_valid": humidite is not None or self._get_conf(CONF_CAPTEUR_HUMIDITE) is None,
            # QUALITÉ DE L'ET0 HORAIRE (0.19.0) : depuis qu'elle pilote le bilan sol, savoir si
            # elle tourne sur des valeurs MESURÉES ou sur des replis n'est plus un détail. Le
            # rayonnement est le plus déterminant (repli = ciel déduit des nuages) ; le vent
            # compte aussi beaucoup (un vent PRÉVU au lieu de mesuré est ce qui donnait 9 mm/j
            # au lieu de 6). Exposé ici pour rester au même endroit que le reste de la santé
            # capteurs, donc visible sans activer les entités de diagnostic.
            "eto_radiation_measured": eto_hourly.get("radiation_source") == "capteur",
            "eto_pressure_measured": eto_hourly.get("pressure_source") == "capteur",
            "eto_hourly_available": eto_hourly.get("value") is not None,
        }
        # LOT E — risque fongique (calculé ici pour garantir la présence dans coordinator.data)
        _fungal = _compute_fungal_risk(
            temperature=temperature,
            humidite=humidite,
            rosee=rosee,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            hour_of_day=current_dt.hour + current_dt.minute / 60.0,
        )
        snapshot.update(_fungal)
        if runtime_context.get("active_irrigation_session") is None:
            await self._finalize_pending_irrigation_user_action(
                execution=runtime_context.get("last_irrigation_execution"),
                persist_only=True,
            )
        self._latest_full_snapshot = dict(snapshot)
        _LOGGER.debug("Gazon Intelligent V2 observability: %s", self._build_observability_payload(snapshot))
        await self._async_save_state()
        # Armer l'arrosage auto une fois le premier snapshot sain calculé. Le startup_guard
        # de _should_launch_auto_irrigation bloque tout déclenchement tant que ce flag est
        # absent/False, pour éviter d'agir pendant le démarrage de HA (capteurs unavailable).
        self._ensure_irrigation_runtime_bootstrap()
        if not self._runtime_state.get("auto_irrigation_bootstrap_complete"):
            snapshot_sain = temperature is not None and snapshot.get("objectif_mm") is not None
            if snapshot_sain:
                self._runtime_state["auto_irrigation_bootstrap_complete"] = True
        maybe_schedule = self._maybe_schedule_auto_irrigation(snapshot)
        if asyncio.iscoroutine(maybe_schedule):
            await maybe_schedule

        return self._build_public_snapshot_data(
            snapshot,
            pluie_demain_source=pluie_demain_source,
            temperature=temperature,
            temperature_source=temperature_source,
            temperature_reference_hydrique=temperature_reference_hydrique,
            forecast_summary=forecast_summary,
            et0_source=et0_source,
            eto_hourly=eto_hourly,
        )

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

    @property
    def evening_cooling_enabled(self) -> bool:
        memory = self.memory
        if isinstance(memory, dict):
            return bool(
                memory.get("evening_cooling_enabled", DEFAULT_EVENING_COOLING_ENABLED)
            )
        return DEFAULT_EVENING_COOLING_ENABLED

    async def async_set_evening_cooling_enabled(self, enabled: bool) -> None:
        """Autorise ou bloque le rafraîchissement du soir en canicule."""
        self.memory["evening_cooling_enabled"] = bool(enabled)
        await self._async_save_state()
        await self.async_request_refresh()

    @property
    def mower_coordination_enabled(self) -> bool:
        memory = self.memory
        if isinstance(memory, dict):
            return bool(
                memory.get("mower_coordination_enabled", DEFAULT_MOWER_COORDINATION_ENABLED)
            )
        return DEFAULT_MOWER_COORDINATION_ENABLED

    async def async_set_mower_coordination_enabled(self, enabled: bool) -> None:
        """Active ou neutralise la coordination tondeuse dans les automatismes."""
        self.memory["mower_coordination_enabled"] = bool(enabled)
        await self._async_save_state()
        await self.async_request_refresh()

    @property
    def mowing_cooldown_after_watering_minutes(self) -> int:
        memory = self.memory
        if isinstance(memory, dict):
            raw_value = memory.get(
                "mowing_cooldown_after_watering_minutes",
                DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES,
            )
            try:
                return max(0, int(float(raw_value)))
            except (TypeError, ValueError):
                return DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES
        return DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES

    async def async_set_mowing_cooldown_after_watering_minutes(self, minutes: float) -> None:
        """Met à jour le délai global avant reprise de la tonte après arrosage."""
        try:
            normalized = max(0, int(round(float(minutes))))
        except (TypeError, ValueError):
            normalized = DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES
        self.memory["mowing_cooldown_after_watering_minutes"] = normalized
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

    def _validate_sensor_value(self, value: float | None, sensor_type: str) -> float | None:
        """Valide une valeur capteur et rejette les aberrations."""
        if value is None:
            return None
        if sensor_type == "temperature":
            if value < -20 or value > 55:
                _LOGGER.warning("Valeur température aberrante rejetée: %s°C", value)
                return None
        elif sensor_type == "pluie":
            if value < 0 or value > 150:
                _LOGGER.warning("Valeur pluie aberrante rejetée: %s mm", value)
                return None
        elif sensor_type == "etp":
            if value < 0 or value > 15:
                _LOGGER.warning("Valeur ETP aberrante rejetée: %s mm", value)
                return None
        elif sensor_type == "humidite":
            if value < 0 or value > 100:
                _LOGGER.warning("Valeur humidité aberrante rejetée: %s%%", value)
                return None
        return value

    def _get_float_state(self, entity_id: str | None) -> float | None:
        """Retourne l'état float d'une entité Home Assistant."""
        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        if state is None:
            return None

        try:
            raw = str(state.state).strip().replace(",", ".")
            value = float(raw)
        except (TypeError, ValueError):
            _LOGGER.debug("Impossible de convertir l'état de %s en float: %s", entity_id, state.state)
            return None
        # `float("nan")` et `float("inf")` NE lèvent PAS : un capteur publiant `nan` propagerait
        # une valeur non finie dans tous les calculs (ET0, bilan sol, scores), où elle contamine
        # silencieusement chaque opération. Une valeur non finie est une ABSENCE de mesure.
        if not isfinite(value):
            _LOGGER.debug("État non fini ignoré pour %s: %s", entity_id, state.state)
            return None
        return value

    def _get_text_state(self, entity_id: str | None) -> str | None:
        """Retourne l'état textuel d'une entité Home Assistant, ou None si indisponible.

        `unavailable`/`unknown` sont des ABSENCES de mesure, pas des valeurs. Les laisser
        passer avait deux conséquences réelles : le capteur d'erreur de la tondeuse devenu
        indisponible (cas courant à chaque redémarrage) était lu comme un CODE D'ERREUR, et la
        tonte se retrouvait bloquée par un « Robot en erreur » imaginaire ; et l'heure du
        prochain départ s'affichait littéralement « unavailable » dans les attributs publics.
        """
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        text = str(state.state or "").strip()
        if text.lower() in _UNAVAILABLE_STATES:
            return None
        return text or None

    def _get_bool_state(self, entity_id: str | None) -> bool | None:
        """Retourne l'état booléen standardisé d'une entité Home Assistant."""
        raw = self._get_text_state(entity_id)
        if raw is None:
            return None
        lowered = raw.lower()
        if lowered in {"on", "true", "home", "detected"}:
            return True
        if lowered in {"off", "false", "not_home", "clear"}:
            return False
        return None

    def _discover_mower_candidates(self) -> list[str]:
        """Liste les robots tondeuse détectés dans Home Assistant."""
        hass = getattr(self, "hass", None)
        states = getattr(hass, "states", None)
        async_all = getattr(states, "async_all", None)
        if not callable(async_all):
            return []

        candidates: list[tuple[int, str]] = []
        try:
            mower_states = list(async_all("lawn_mower"))
        except TypeError:
            mower_states = list(async_all())
        for state in mower_states:
            entity_id = getattr(state, "entity_id", None)
            if not isinstance(entity_id, str) or not entity_id.strip():
                continue
            raw_state = str(getattr(state, "state", "") or "").strip().lower()
            priority = 0 if raw_state not in {"unavailable", "unknown"} else 1
            candidates.append((priority, entity_id.strip()))

        if not candidates:
            return []

        candidates.sort(key=lambda item: (item[0], item[1]))
        return [entity_id for _priority, entity_id in candidates]

    def _resolve_mower_selection(self) -> dict[str, Any]:
        """Résout la tondeuse active sans sélection silencieuse ambiguë."""
        configured = self._get_conf(CONF_ENTITE_TONDEUSE)
        if isinstance(configured, str):
            configured = configured.strip()
            if configured:
                hass = getattr(self, "hass", None)
                states = getattr(hass, "states", None)
                get_state = getattr(states, "get", None)
                mower_state = get_state(configured) if callable(get_state) else None
                state_exists = mower_state is not None
                return {
                    "entity_id": configured,
                    "resolution_state": "configured" if state_exists else "configured_missing",
                    "resolution_reason": (
                        "Tondeuse configurée explicitement." if state_exists else "Tondeuse configurée introuvable."
                    ),
                    "resolution_candidate_count": len(self._discover_mower_candidates()),
                }

        candidates = self._discover_mower_candidates()
        candidate_count = len(candidates)
        if candidate_count == 1:
            return {
                "entity_id": candidates[0],
                "resolution_state": "fallback_single",
                "resolution_reason": "Tondeuse découverte automatiquement.",
                "resolution_candidate_count": candidate_count,
            }
        if candidate_count == 0:
            return {
                "entity_id": None,
                "resolution_state": "missing",
                "resolution_reason": "Aucune tondeuse détectée.",
                "resolution_candidate_count": 0,
            }
        return {
            "entity_id": None,
            "resolution_state": "ambiguous",
            "resolution_reason": "Plusieurs tondeuses détectées. Configure une tondeuse explicitement.",
            "resolution_candidate_count": candidate_count,
        }

    def _resolve_mower_related_entity_id(self, mower_entity_id: str | None, config_key: str, platform: str, suffix: str) -> str | None:
        configured = self._get_conf(config_key)
        if isinstance(configured, str):
            configured = configured.strip()
            if configured:
                return configured
        return derive_related_entity_id(mower_entity_id, platform, suffix)

    def _resolve_mower_cutting_height_mm(self, mower_entity_id: str | None) -> float | None:
        configured_height = self._get_float_state(
            self._resolve_mower_related_entity_id(
                mower_entity_id,
                CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE,
                "number",
                "hauteur_de_coupe",
            )
        )
        if configured_height is not None and configured_height > 0:
            return configured_height
        manual_height = self._get_float_conf(CONF_HAUTEUR_COUPE_TONDEUSE_MM, 0.0)
        if manual_height is not None and manual_height > 0:
            return manual_height
        return configured_height

    def _build_mower_snapshot(self) -> dict[str, Any]:
        """Normalise les signaux d'un robot tondeuse Home Assistant."""
        mower_selection = self._resolve_mower_selection()
        mower_entity_id = mower_selection.get("entity_id")
        cutting_height_mm = self._resolve_mower_cutting_height_mm(mower_entity_id)
        resolution_state = mower_selection.get("resolution_state")
        resolution_reason = mower_selection.get("resolution_reason")
        resolution_candidate_count = mower_selection.get("resolution_candidate_count")
        if not isinstance(mower_entity_id, str) or not mower_entity_id:
            raw_context = build_mower_context(
                entity_id=None,
                entity_name=None,
                raw_state="unknown",
                available=False,
                cutting_height_mm=cutting_height_mm,
                resolution_state=resolution_state,
                resolution_reason=resolution_reason,
                resolution_candidate_count=resolution_candidate_count,
            )
            raw_context.update(
                {
                    "tondeuse_statut": "inconnu",
                    "tondeuse_statut_libelle": "Inconnu",
                    "tondeuse_connectee": False,
                    "tondeuse_prete": False,
                    "tondeuse_raison": resolution_reason,
                }
            )
            return {
                **raw_context,
                **build_mower_coordination_context(
                    raw_context,
                    enabled=self.mower_coordination_enabled,
                ),
            }

        hass = getattr(self, "hass", None)
        states = getattr(hass, "states", None)
        get_state = getattr(states, "get", None)
        mower_state = get_state(mower_entity_id) if callable(get_state) else None
        if mower_state is None:
            raw_context = build_mower_context(
                entity_id=mower_entity_id,
                entity_name=None,
                raw_state="unavailable",
                available=False,
                cutting_height_mm=cutting_height_mm,
                resolution_state=resolution_state,
                resolution_reason=resolution_reason,
                resolution_candidate_count=resolution_candidate_count,
            )
            raw_context["tondeuse_raison"] = resolution_reason
            return {
                **raw_context,
                **build_mower_coordination_context(
                    raw_context,
                    enabled=self.mower_coordination_enabled,
                ),
            }

        raw_state = str(mower_state.state or "").strip()
        available = raw_state.lower() not in {"unavailable", "unknown"}
        raw_context = build_mower_context(
            entity_id=mower_entity_id,
            entity_name=getattr(mower_state, "name", None),
            raw_state=raw_state,
            available=available,
            charging=self._get_bool_state(
                self._resolve_mower_related_entity_id(
                    mower_entity_id,
                    CONF_CAPTEUR_TONDEUSE_EN_CHARGE,
                    "binary_sensor",
                    "en_charge",
                )
            ),
            rain=self._get_bool_state(
                self._resolve_mower_related_entity_id(
                    mower_entity_id,
                    CONF_CAPTEUR_TONDEUSE_PLUIE,
                    "binary_sensor",
                    "capteur_de_pluie",
                )
            ),
            error_raw=self._get_text_state(
                self._resolve_mower_related_entity_id(
                    mower_entity_id,
                    CONF_CAPTEUR_TONDEUSE_ERREUR,
                    "sensor",
                    "erreur",
                )
            ),
            battery_percent=self._get_float_state(
                self._resolve_mower_related_entity_id(
                    mower_entity_id,
                    CONF_CAPTEUR_TONDEUSE_BATTERIE,
                    "sensor",
                    "batterie",
                )
            ),
            next_schedule_raw=self._get_text_state(
                self._resolve_mower_related_entity_id(
                    mower_entity_id,
                    CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART,
                    "sensor",
                    "prochain_programme",
                )
            ),
            cutting_height_mm=cutting_height_mm,
            resolution_state=resolution_state,
            resolution_reason=resolution_reason,
            resolution_candidate_count=resolution_candidate_count,
        )
        return {
            **raw_context,
            **build_mower_coordination_context(
                raw_context,
                enabled=self.mower_coordination_enabled,
            ),
        }

    def _build_runtime_context(self) -> dict[str, Any]:
        semis_progress = self._semis_cycle_progress()
        return {
            # Instant courant UTC réel. Les modules de décision sont purs (sans accès à Home
            # Assistant ni à la base de fuseaux) : sans cette valeur ils reconstruisaient « maintenant »
            # à partir de today + hour_of_day, or hour_of_day est une heure LOCALE (Europe/Paris)
            # qu'ils estampillaient en UTC — les durées écoulées étaient donc surestimées de
            # l'offset local (1 h en hiver, 2 h en été) face aux horodatages d'arrosage, eux en UTC réel.
            "now_utc": self._serialize_runtime_value(self._current_utc_datetime()),
            "active_irrigation_session": self._get_active_irrigation_session(),
            "last_irrigation_execution": self._runtime_state.get("last_irrigation_execution"),
            "mowing_cooldown_after_watering_minutes": self.mowing_cooldown_after_watering_minutes,
            "semis_followup_state": semis_progress.get("state") if semis_progress else None,
            "semis_followup_due_at": self._serialize_runtime_value(
                semis_progress.get("next_due_at") if semis_progress else None
            ),
            "semis_followup_due_display": semis_progress.get("next_due_display") if semis_progress else None,
            "semis_cycles_completed_today": semis_progress.get("cycles_completed_today") if semis_progress else None,
            "semis_cycles_remaining_today": semis_progress.get("cycles_remaining_today") if semis_progress else None,
            "semis_daily_cycles_target": semis_progress.get("daily_cycles_target") if semis_progress else None,
            "semis_cycle_spacing_minutes": semis_progress.get("cycle_spacing_minutes") if semis_progress else None,
            "semis_last_cycle_at": self._serialize_runtime_value(
                semis_progress.get("last_cycle_at") if semis_progress else None
            ),
            "semis_last_cycle_display": semis_progress.get("last_cycle_display") if semis_progress else None,
        }

    def _semis_cycle_history_items(self) -> list[dict[str, Any]]:
        history = getattr(self, "history", None)
        if not isinstance(history, list):
            return []
        today = self._current_date().isoformat()
        items: list[dict[str, Any]] = []
        for item in history:
            if not isinstance(item, dict) or str(item.get("type") or "").strip() != "arrosage":
                continue
            recorded_at = item.get("recorded_at") or item.get("detected_at") or item.get("date")
            recorded_dt = self._parse_datetime_value(recorded_at)
            if recorded_dt is not None:
                if recorded_dt.date().isoformat() != today:
                    continue
            else:
                recorded_date = str(recorded_at or "").strip()
                if recorded_date != today:
                    continue
            strategy = str(item.get("watering_strategy") or "").strip()
            scope = str(item.get("objective_scope") or "").strip()
            if strategy == WATERING_STRATEGY_SEMIS_FREQUENT or scope == OBJECTIVE_SCOPE_SURFACE_CYCLE:
                items.append(item)
                continue
            if item.get("surface_cycle_mm") not in (None, ""):
                items.append(item)
        return items

    def _semis_cycle_progress(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any] | None:
        snapshot = snapshot if isinstance(snapshot, dict) else self._current_snapshot()
        strategy = str(snapshot.get("watering_strategy") or "").strip()
        objective_scope = str(snapshot.get("objective_scope") or "").strip()
        if strategy != WATERING_STRATEGY_SEMIS_FREQUENT or objective_scope != OBJECTIVE_SCOPE_SURFACE_CYCLE:
            return None

        try:
            surface_cycle_mm = float(
                snapshot.get("surface_cycle_mm")
                or snapshot.get("objectif_mm")
                or snapshot.get("objective_mm")
                or 0.0
            )
        except (TypeError, ValueError):
            surface_cycle_mm = 0.0
        try:
            daily_cycles_target = int(snapshot.get("daily_cycles_target") or 1)
        except (TypeError, ValueError):
            daily_cycles_target = 1
        try:
            cycle_spacing_minutes = int(snapshot.get("cycle_spacing_minutes") or 0)
        except (TypeError, ValueError):
            cycle_spacing_minutes = 0

        if surface_cycle_mm <= 0 or daily_cycles_target <= 0:
            return None

        watering_stage = str(snapshot.get("watering_stage") or "").strip()
        transition_ready = bool(snapshot.get("seeding_transition_ready") or False)
        stage_name, stage_program = resolve_semis_stage_program(
            watering_stage,
            transition_ready=transition_ready,
        )
        cycle_slots_minutes = list(stage_program.cycle_slots_minutes[:daily_cycles_target])
        if len(cycle_slots_minutes) < daily_cycles_target:
            fallback_spacing = max(cycle_spacing_minutes, stage_program.cycle_spacing_minutes_min)
            while len(cycle_slots_minutes) < daily_cycles_target:
                if not cycle_slots_minutes:
                    cycle_slots_minutes.append(stage_program.cycle_slots_minutes[0])
                else:
                    cycle_slots_minutes.append(cycle_slots_minutes[-1] + fallback_spacing)

        cycles_completed_today = len(self._semis_cycle_history_items())
        cycles_remaining_today = max(0, daily_cycles_target - cycles_completed_today)
        last_cycle_at: datetime | None = None
        history_items = self._semis_cycle_history_items()
        if history_items:
            last_item = history_items[-1]
            recorded_at = last_item.get("recorded_at") or last_item.get("detected_at") or last_item.get("date")
            last_cycle_at = self._parse_datetime_value(recorded_at)

        now = self._current_datetime()
        next_due_at: datetime | None = None
        if cycles_remaining_today > 0:
            slot_index = min(cycles_completed_today, len(cycle_slots_minutes) - 1)
            due_minutes = cycle_slots_minutes[slot_index]
            next_due_at = now.replace(
                hour=due_minutes // 60,
                minute=due_minutes % 60,
                second=0,
                microsecond=0,
            )
            if last_cycle_at is not None and cycle_spacing_minutes > 0:
                spacing_due_at = last_cycle_at + timedelta(minutes=cycle_spacing_minutes)
                if spacing_due_at > next_due_at:
                    next_due_at = spacing_due_at

        if cycles_remaining_today <= 0:
            state = "complete"
        elif next_due_at is not None and next_due_at > now:
            state = "waiting"
        else:
            state = "ready"

        return {
            "state": state,
            "next_due_at": next_due_at,
            "next_due_display": self._local_datetime_text(next_due_at) if next_due_at is not None else None,
            "cycles_completed_today": cycles_completed_today,
            "cycles_remaining_today": cycles_remaining_today,
            "daily_cycles_target": daily_cycles_target,
            "cycle_spacing_minutes": cycle_spacing_minutes,
            "last_cycle_at": last_cycle_at,
            "last_cycle_display": self._local_datetime_text(last_cycle_at) if last_cycle_at is not None else None,
            "surface_cycle_mm": round(surface_cycle_mm, 1),
            "watering_strategy": strategy,
            "objective_scope": objective_scope,
            "watering_stage": stage_name,
            "cycle_slots_minutes": tuple(cycle_slots_minutes),
        }

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

    def _get_sun_context(self) -> dict[str, Any]:
        """Retourne le contexte solaire courant utilisé comme garde-fou jour/nuit."""
        hass = getattr(self, "hass", None)
        states = getattr(hass, "states", None)
        if states is None:
            return {}
        state = states.get("sun.sun")
        if state is None:
            return {}
        sun_state = str(state.state or "").strip().lower()
        attrs = state.attributes or {}
        return {
            "sun_entity_id": "sun.sun",
            "sun_state": sun_state or None,
            # None quand l'état n'est ni l'un ni l'autre (`unavailable` au démarrage) : un `False`
            # signifierait « il fait nuit », alors que la consigne est « on ne sait pas ». Les
            # consommateurs testent `is None` pour activer leur repli horaire — le garde-fou de
            # nuit de la tonte était sinon purement et simplement désactivé.
            "sun_above_horizon": (sun_state == "above_horizon") if sun_state in _SUN_KNOWN_STATES else None,
            "sun_below_horizon": (sun_state == "below_horizon") if sun_state in _SUN_KNOWN_STATES else None,
            "sun_next_rising": attrs.get("next_rising"),
            "sun_next_setting": attrs.get("next_setting"),
            "sun_elevation": attrs.get("elevation"),
        }

    def _sunset_minute_from_context(self, sun_context: dict[str, Any]) -> int | None:
        """Minute locale (depuis minuit) du prochain coucher du soleil, ou None."""
        return self._sun_event_minute_from_context(sun_context, "sun_next_setting")

    def _sunrise_minute_from_context(self, sun_context: dict[str, Any]) -> int | None:
        """Minute locale (depuis minuit) du prochain lever du soleil, ou None."""
        return self._sun_event_minute_from_context(sun_context, "sun_next_rising")

    def _sun_event_minute_from_context(self, sun_context: dict[str, Any], key: str) -> int | None:
        if not isinstance(sun_context, dict):
            return None
        raw = sun_context.get(key)
        if not raw:
            return None
        try:
            parsed = dt_util.parse_datetime(str(raw))
            if parsed is None:
                return None
            local = dt_util.as_local(parsed)
            return local.hour * 60 + local.minute
        except (TypeError, ValueError):
            return None

    def _et_elapsed_fraction(self, sun_context: dict[str, Any]) -> float:
        """Fraction de l'évapotranspiration du jour déjà écoulée, d'après le soleil.

        L'ET se produit le jour : 0 avant le lever, monte linéairement jusqu'à 1 au coucher,
        reste à 1 la nuit.

        Ce n'est PAS un simple confort d'affichage : cette fraction amorce le débit du bilan sol
        (`etp_prorata` dans `soil_balance.update_soil_balance`) et fixe donc la réserve à partir de
        laquelle la dose d'arrosage est calculée. Un ancien commentaire la disait « affichage
        uniquement, sans risque » — c'était faux, et coûteux.

        SOLEIL INCONNU → repli sur une journée civile approximative, JAMAIS sur 1.0.
        `sun.sun` peut manquer du state machine pendant le démarrage de Home Assistant : le
        contexte revient vide et le lever/coucher sont `None`. L'ancien repli à 1.0 signifiait
        alors « toute la journée est écoulée » — le 29/07/2026 à 03:11, un redémarrage a ainsi
        débité **6,2 mm d'ETc d'un coup à 3 h du matin**, faisant chuter la réserve de 8,0 à
        1,8 mm alors que rien n'avait évaporé depuis minuit. Et l'accumulation ne recule jamais :
        l'erreur se fige pour toute la journée et fausse la dose de l'arrosage d'aube.
        C'était la « falaise de minuit » revenue par une autre porte.
        """
        sunrise = self._sunrise_minute_from_context(sun_context)
        sunset = self._sunset_minute_from_context(sun_context)
        if sunrise is None or sunset is None or sunset <= sunrise:
            # Fenêtre civile large : volontairement grossière, elle n'a qu'à tenir le temps que
            # `sun.sun` apparaisse. Toute valeur horaire vaut mieux qu'un « journée finie » à 3 h.
            sunrise, sunset = _FALLBACK_DAY_START_MINUTE, _FALLBACK_DAY_END_MINUTE
        now = self._current_datetime()
        now_minute = now.hour * 60 + now.minute
        if now_minute <= sunrise:
            return 0.0
        if now_minute >= sunset:
            return 1.0
        return max(0.0, min(1.0, (now_minute - sunrise) / (sunset - sunrise)))

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
            "post-produit",
            "application",
        ):
            if marker in lowered:
                return marker
        return reason

    def _build_observability_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        today = self._current_date()
        payload = {
            "phase": snapshot.get("phase_active"),
            "sous_phase": snapshot.get("sous_phase"),
            "watering_cause": snapshot.get("watering_cause"),
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
        self.brain.set_mode(mode)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_set_date_action(self, date_action: date | None = None) -> None:
        """Définit la date de la dernière intervention de phase."""
        self.brain.set_date_action(date_action)
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_set_normal(self) -> None:
        """Réinitialise la phase active vers Normal (historique conservé)."""
        self.brain.set_normal()
        # Lève le verrou de sécurité d'arrosage : « Retour au mode normal » (bouton ou
        # service reset_mode) est l'action utilisateur explicite « j'ai vérifié les vannes,
        # on peut reprendre ». Sans ça, un seul échec de fermeture de vanne bloquerait
        # l'arrosage auto définitivement, sans aucun recours.
        self._ensure_irrigation_runtime_bootstrap()
        self._runtime_state["auto_irrigation_safety_lock"] = False
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
            selected_product_id=self.selected_product_id,
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

    async def async_record_mowing(
        self,
        date_action: date | None = None,
        hauteur_coupe_mm: float | None = None,
    ) -> None:
        if hauteur_coupe_mm is None:
            mower_ctx = self._build_mower_snapshot()
            hauteur_coupe_mm = mower_ctx.get("tondeuse_hauteur_coupe_mm")
        self.brain.record_mowing(date_action, hauteur_coupe_mm=hauteur_coupe_mm)
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
        started_at: datetime | None = None,
        watering_cause: str | None = None,
        mm_scope: str | None = None,
        mm_interpretation: str | None = None,
        watering_strategy: str | None = None,
        objective_scope: str | None = None,
        watering_stage: str | None = None,
        surface_cycle_mm: float | None = None,
        daily_cycles_target: int | None = None,
        cycle_spacing_minutes: int | None = None,
        surface_moisture_target: str | None = None,
        surface_dryness_risk: str | None = None,
        runoff_risk: str | None = None,
        seeding_transition_ready: bool | None = None,
        seeding_block_reason: str | None = None,
    ) -> None:
        payload = self.brain.record_watering(
            date_action=date_action,
            objectif_mm=objectif_mm,
            total_mm=total_mm,
            zones=zones,
            source=source,
            watering_cause=self._normalize_watering_cause(watering_cause, source=source),
            mm_scope=mm_scope,
            mm_interpretation=mm_interpretation,
            watering_strategy=watering_strategy,
            objective_scope=objective_scope,
            watering_stage=watering_stage,
            surface_cycle_mm=surface_cycle_mm,
            daily_cycles_target=daily_cycles_target,
            cycle_spacing_minutes=cycle_spacing_minutes,
            surface_moisture_target=surface_moisture_target,
            surface_dryness_risk=surface_dryness_risk,
            runoff_risk=runoff_risk,
            seeding_transition_ready=seeding_transition_ready,
            seeding_block_reason=seeding_block_reason,
        )
        if detected_at is not None:
            payload["detected_at"] = detected_at.isoformat()
            # `ended_at` explicite : `resolve_history_moment` le lit en PREMIER, et il vaut le
            # même instant que `detected_at`. Le calcul d'espacement (cooldown 24 h) ne bouge
            # donc pas — seul l'AFFICHAGE change, en lisant `started_at`.
            payload["ended_at"] = detected_at.isoformat()
        if started_at is not None:
            payload["started_at"] = started_at.isoformat()
        await self._async_save_state()
        await self.async_request_refresh()

    async def async_recalibrate_reserve(self, reserve_mm: float, freeze_day: bool = True) -> None:
        """Recale la réserve hydrique du sol à une valeur connue (calibration manuelle)."""
        self.brain.recalibrate_soil_reserve(
            float(reserve_mm), today=self._current_date(), freeze_day=bool(freeze_day)
        )
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
        await self._restore_active_irrigation_session()
        # Ne reconstruire une session passive (à partir des vannes actuellement ouvertes)
        # QUE si aucun cycle piloté n'est actif/repris. Sinon le suivi passif est suspendu
        # par le cycle → l'événement de fermeture serait ignoré, laissant une session
        # « fantôme » non finalisée qui bloquerait tout arrosage ultérieur.
        if self._get_active_irrigation_session() is None:
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
        ):
            entity_id = self._get_conf(key)
            if isinstance(entity_id, str) and entity_id:
                entity_ids.append(entity_id)
        mower_selection = self._resolve_mower_selection()
        mower_entity_id = mower_selection.get("entity_id")
        if isinstance(mower_entity_id, str) and mower_entity_id:
            entity_ids.append(mower_entity_id)
            for platform, suffix in (
                ("sensor", "batterie"),
                ("binary_sensor", "capteur_de_pluie"),
                ("binary_sensor", "en_charge"),
                ("sensor", "erreur"),
                ("sensor", "prochain_programme"),
                ("number", "hauteur_de_coupe"),
            ):
                related_entity_id = derive_related_entity_id(mower_entity_id, platform, suffix)
                if related_entity_id:
                    entity_ids.append(related_entity_id)
        return list(dict.fromkeys(entity_ids))

    async def async_start_source_monitoring(self) -> None:
        """Surveille les capteurs sources pour rafraîchir les entités dérivées."""
        self._cancel_source_monitoring()
        entity_ids = self._source_entity_ids()
        # Mémorise les entités surveillées pour détecter un vrai changement de capteur
        # (vs un simple ajustement de débit/hauteur) côté listener d'options.
        self._monitored_source_entities = set(entity_ids)
        if not entity_ids:
            return
        self._unsub_source_listeners = [
            async_track_state_change_event(self.hass, entity_ids, self._handle_source_state_change)
        ]

    def source_config_changed(self) -> bool:
        """Indique si les entités sources surveillées (capteurs / météo / tondeuse) ont
        changé depuis le dernier démarrage du monitoring. Permet de ne recharger
        l'intégration sur changement d'options que si un capteur a réellement changé —
        un simple réglage de débit/hauteur (entité number) est appliqué en place."""
        return set(self._source_entity_ids()) != getattr(self, "_monitored_source_entities", set())

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
        snapshot = self._current_snapshot()
        if not snapshot:
            return
        maybe_schedule = self._maybe_schedule_auto_irrigation(snapshot)
        if asyncio.iscoroutine(maybe_schedule):
            await maybe_schedule

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
        changed_at = getattr(new_state, "last_changed", None) or self._current_utc_datetime()

        if new_is_on:
            self._track_watering_zone_on(entity_id, changed_at)
            return

        fallback_start = (
            old_state.last_changed if old_is_on and old_state is not None else None
        )

        # Anti-doublon de fin de cycle auto : le moniteur passif est gelé pendant tout le
        # cycle piloté, mais le OFF du DERNIER passage arrive parfois une fraction de
        # seconde APRÈS la levée de la garde (course entre le `finally` qui décrémente la
        # garde et la livraison de l'événement d'état). Sans ce filtre, ce OFF traînant
        # reconstruit le passage via son `last_changed` (antérieur à la reprise) et le
        # réenregistre en `zone_session` doublon → sur-crédit de la réserve et du budget
        # hebdo. On ignore donc tout OFF dont le segment a DÉMARRÉ pendant la fenêtre gelée
        # (≤ instant de reprise) ; un arrosage manuel/externe postérieur démarre après la
        # reprise et reste tracé normalement.
        segment_start = fallback_start
        session = self._watering_session
        if session is not None:
            tracked_start = session["active_zones"].get(entity_id)
            if tracked_start is not None:
                segment_start = tracked_start
        resumed_at = self._zone_tracking_resumed_at
        if (
            segment_start is not None
            and resumed_at is not None
            and segment_start <= resumed_at
        ):
            return

        if self._track_watering_zone_off(
            entity_id,
            changed_at,
            fallback_start,
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
        try:
            self._cancel_watering_session_finalize()
        finally:
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
        now = self._current_utc_datetime()
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
                        duration_seconds = float(duration_seconds)  # type: ignore[arg-type]
                    except (TypeError, ValueError):
                        continue
                    if duration_seconds > 0:
                        total_seconds += duration_seconds
                try:
                    pause_minutes = max(0, int(plan.get("pause_between_passages_minutes", 0)))
                except (TypeError, ValueError):
                    pause_minutes = 0
                if total_seconds > 0:
                    try:
                        passages = max(1, int(plan.get("passages", 1)))
                    except (TypeError, ValueError):
                        passages = 1
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
                        duration_seconds = float(duration_seconds)  # type: ignore[arg-type]
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
        attributes = plan_state.attributes if isinstance(plan_state.attributes, Mapping) else {}
        plan = normalize_existing_plan(attributes)
        if plan is None:
            return None
        return plan.as_dict()

    def _build_watering_plan_summary_for_user_action(
        self,
        objectif_mm: float | None = None,
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(plan, dict):
            normalized = normalize_existing_plan(plan)
            if normalized is not None:
                return normalized.as_dict()

        canonical = self._get_canonical_watering_plan(objectif_mm=objectif_mm)
        if canonical is None:
            objective = float(
                objectif_mm if objectif_mm is not None else self.data.get("objectif_mm") or 0.0
            )
            passages = self.data.get("watering_passages") or 1
            pause_minutes = self.data.get("watering_pause_minutes") or 0
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
        summary = canonical.as_dict()
        summary["min_duration_min"] = round(
            min(zone.duration_s for zone in canonical.zones) / 60.0, 1
        ) if canonical.zones else 0.0
        summary["max_duration_min"] = round(
            max(zone.duration_s for zone in canonical.zones) / 60.0, 1
        ) if canonical.zones else 0.0
        return summary

    def _plan_arrosage_entity_id(self) -> str:
        """Résout l'entité du plan d'arrosage courant."""
        fallback = public_entity_id("sensor", "plan_arrosage", instance_slug=resolve_entry_instance_slug(self.entry))
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

    def _local_date_of(self, moment: datetime) -> date:
        """Date CIVILE d'un instant, dans le fuseau de l'utilisateur.

        `_parse_datetime_value` normalise tout en UTC ; comparer son `.date()` à
        `self._current_date()` — une date LOCALE — mélangeait donc deux référentiels. En
        Europe/Paris l'été, tout ce qui se produit entre 00 h et 02 h locales porte la date de
        la VEILLE en UTC : un arrosage manuel à 00 h 20 était vu comme « hier », le motif
        `recent_watering` ne se posait pas, et l'auto pouvait arroser par-dessus le matin même.
        """
        as_local = getattr(dt_util, "as_local", None) if dt_util is not None else None
        return (as_local(moment) if callable(as_local) else moment).date()

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

    def _new_runtime_id(self, prefix: str) -> str:
        timestamp = self._current_utc_datetime().strftime("%Y%m%dT%H%M%SZ")
        return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"

    def _ensure_irrigation_runtime_bootstrap(self) -> None:
        if not hasattr(self, "_irrigation_launch_lock"):
            self._irrigation_launch_lock = None
        if self._irrigation_launch_lock is None:
            try:
                self._irrigation_launch_lock = asyncio.Lock()
            except RuntimeError:
                self._irrigation_launch_lock = None
        runtime_state = getattr(self, "_runtime_state", None)
        if not isinstance(runtime_state, dict):
            self._runtime_state = {
                "active_irrigation_session": None,
                "last_irrigation_execution": None,
                "last_auto_irrigation_reason": None,
                "last_auto_irrigation_completed_at": None,
                "auto_irrigation_safety_lock": False,
                "auto_irrigation_bootstrap_complete": False,
            }
            return
        runtime_state.setdefault("active_irrigation_session", None)
        runtime_state.setdefault("last_irrigation_execution", None)
        runtime_state.setdefault("last_auto_irrigation_reason", None)
        runtime_state.setdefault("last_auto_irrigation_completed_at", None)
        runtime_state.setdefault("auto_irrigation_safety_lock", False)
        runtime_state.setdefault("auto_irrigation_bootstrap_complete", False)

    def _serialized_runtime_state(self) -> dict[str, Any]:
        self._ensure_irrigation_runtime_bootstrap()
        # Build lightweight persisted session
        active_session = self._runtime_state.get("active_irrigation_session")
        persisted_watering_session = None
        if isinstance(active_session, dict):
            zones_raw = active_session.get("zones")
            zone_ids: list[str] = []
            if isinstance(zones_raw, dict):
                zone_ids = list(zones_raw.keys())
            elif isinstance(zones_raw, list):
                zone_ids = [z.get("entity_id") or z.get("zone") or "" for z in zones_raw if isinstance(z, dict)]
            persisted_watering_session = {
                "started_at": self._serialize_runtime_value(active_session.get("started_at")),
                "zones": zone_ids,
                "source": active_session.get("source"),
            }
        last_execution = self._runtime_state.get("last_irrigation_execution")
        return {
            "active_irrigation_session": self._serialize_runtime_value(active_session),
            "last_irrigation_execution": self._serialize_runtime_value(last_execution),
            "last_auto_irrigation_reason": self._serialize_runtime_value(
                self._runtime_state.get("last_auto_irrigation_reason")
            ),
            "last_auto_irrigation_completed_at": self._serialize_runtime_value(
                self._runtime_state.get("last_auto_irrigation_completed_at")
            ),
            "auto_irrigation_safety_lock": bool(
                self._runtime_state.get("auto_irrigation_safety_lock")
            ),
            "persisted_watering_session": persisted_watering_session,
            "last_irrigation_execution_persisted": self._serialize_runtime_value(last_execution),
        }

    def _serialize_runtime_value(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: self._serialize_runtime_value(val) for key, val in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._serialize_runtime_value(item) for item in value]
        return value

    def _deserialize_active_irrigation_session(self, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        session = dict(payload)
        for key in ("started_at", "paused_until", "last_update", "ended_at", "current_zone_started_at"):
            if key in session:
                session[key] = self._parse_datetime_value(session.get(key))
        return session

    def _restore_runtime_state(self, runtime: dict[str, Any] | None) -> None:
        self._ensure_irrigation_runtime_bootstrap()
        runtime = runtime if isinstance(runtime, dict) else {}
        active_session = self._deserialize_active_irrigation_session(
            runtime.get("active_irrigation_session")
        )
        # Restore persisted watering session if recent (< 4h)
        if active_session is None:
            persisted = runtime.get("persisted_watering_session")
            if isinstance(persisted, dict):
                started_at = self._parse_datetime_value(persisted.get("started_at"))
                if started_at is not None:
                    age_hours = (self._current_utc_datetime() - started_at).total_seconds() / 3600.0
                    if age_hours <= 4.0:
                        active_session = {"started_at": started_at, "source": persisted.get("source"), "zones": persisted.get("zones", [])}
                    else:
                        _LOGGER.warning("Session persistée ignorée: trop ancienne (%.1fh)", age_hours)
        last_execution = runtime.get("last_irrigation_execution") or runtime.get("last_irrigation_execution_persisted")
        if isinstance(last_execution, dict):
            last_execution = self._serialize_runtime_value(last_execution)
        else:
            last_execution = None
        last_auto_irrigation_reason = runtime.get("last_auto_irrigation_reason")
        if isinstance(last_auto_irrigation_reason, dict):
            last_auto_irrigation_reason = self._serialize_runtime_value(last_auto_irrigation_reason)
        else:
            last_auto_irrigation_reason = None
        self._runtime_state = {
            "active_irrigation_session": active_session,
            "last_irrigation_execution": last_execution,
            "last_auto_irrigation_reason": last_auto_irrigation_reason,
            "last_auto_irrigation_completed_at": runtime.get("last_auto_irrigation_completed_at"),
            "auto_irrigation_safety_lock": bool(runtime.get("auto_irrigation_safety_lock")),
        }

    def _get_active_irrigation_session(self) -> dict[str, Any] | None:
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        session = self._runtime_state.get("active_irrigation_session")
        if not isinstance(session, dict):
            return None
        if self._is_finished_irrigation_session(session):
            status = "failed" if session.get("last_error") else "completed"
            self._persist_execution_snapshot(session, status=status, error=session.get("last_error"))
            self._set_active_irrigation_session(None)
            return None
        return session if isinstance(session, dict) else None

    def _set_active_irrigation_session(self, session: dict[str, Any] | None) -> None:
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        self._runtime_state["active_irrigation_session"] = session if isinstance(session, dict) else None

    def _set_last_irrigation_execution(self, execution: dict[str, Any] | None) -> None:
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        self._runtime_state["last_irrigation_execution"] = execution if isinstance(execution, dict) else None

    def _set_last_auto_irrigation_reason(self, reason: str | None) -> None:
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        if reason is None:
            self._runtime_state["last_auto_irrigation_reason"] = None
            return
        self._runtime_state["last_auto_irrigation_reason"] = {
            "reason": str(reason),
            "recorded_at": self._current_utc_datetime(),
        }

    def _auto_irrigation_safety_lock_active(self) -> bool:
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        return bool(self._runtime_state.get("auto_irrigation_safety_lock"))

    async def _persist_runtime_state(self) -> None:
        save_state = getattr(self, "_async_save_state", None)
        if callable(save_state):
            await save_state()

    async def _set_irrigation_safety_lock(self, error: str, failed_zone: str | None = None) -> None:
        self._runtime_state["auto_irrigation_safety_lock"] = True
        execution = self._runtime_state.get("last_irrigation_execution")
        if not isinstance(execution, dict):
            execution = {}
        execution["last_error"] = str(error)
        if failed_zone:
            execution["last_failed_zone"] = str(failed_zone)
        execution["auto_irrigation_safety_lock"] = True
        self._set_last_irrigation_execution(execution)
        await self._persist_runtime_state()

    def _emit_irrigation_event(self, event_name: str, payload: dict[str, Any]) -> None:
        hass = getattr(self, "hass", None)
        bus = getattr(hass, "bus", None)
        async_fire = getattr(bus, "async_fire", None)
        if callable(async_fire):
            async_fire(event_name, payload)

    def _is_finished_irrigation_session(self, session: dict[str, Any]) -> bool:
        status = str(session.get("status") or "").strip().lower()
        if status in {"completed", "failed", "cancelled"}:
            return True
        active_zones = session.get("active_zones")
        has_active_zones = bool(active_zones) if isinstance(active_zones, (dict, list, tuple, set)) else False
        if has_active_zones or session.get("current_zone"):
            return False
        try:
            planned_total_seconds = max(0.0, float(session.get("planned_total_seconds") or 0.0))
        except (TypeError, ValueError):
            planned_total_seconds = 0.0
        # Des segments restent-ils à exécuter ? Si oui, le cycle N'EST PAS terminé, quelle que soit
        # la durée écoulée — sinon une coupure de HA plus longue que la durée planifiée (typiquement
        # pendant la pause inter-passages) clôturait le cycle et ABANDONNAIT le 2ᵉ passage (6 mm au
        # lieu de 12). L'heuristique « elapsed >= planned » ne vaut que pour un cycle sans travail
        # restant (session ancienne sans zones_pending → repli sur le comportement historique).
        zones_pending = session.get("zones_pending")
        has_pending_segments = isinstance(zones_pending, list) and len(zones_pending) > 0
        started_at = session.get("started_at")
        if planned_total_seconds > 0 and isinstance(started_at, datetime) and not has_pending_segments:
            elapsed_seconds = max((self._current_utc_datetime() - started_at).total_seconds(), 0.0)
            if elapsed_seconds >= planned_total_seconds:
                return True
        try:
            current_passage = max(1, int(session.get("current_passage") or 1))
        except (TypeError, ValueError):
            current_passage = 1
        try:
            passage_count = max(1, int(session.get("passage_count") or 1))
        except (TypeError, ValueError):
            passage_count = 1
        # zones_pending déjà résolu plus haut (has_pending_segments).
        if current_passage >= passage_count and not has_pending_segments and isinstance(zones_pending, list):
            return True
        return False

    def _build_runtime_payload_for_event(self, session: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if isinstance(session, dict):
            for key in (
                "session_id",
                "run_id",
                "source",
                "strategy",
                "status",
                "current_passage",
                "watering_cause",
                "watering_strategy",
                "objective_scope",
                "watering_stage",
                "surface_cycle_mm",
                "daily_cycles_target",
                "cycle_spacing_minutes",
            ):
                value = session.get(key)
                if value not in (None, "", [], {}):
                    payload[key] = value
        for key, value in extra.items():
            if value not in (None, "", [], {}):
                payload[key] = self._serialize_runtime_value(value)
        return payload

    @staticmethod
    def _normalize_watering_cause(value: Any, *, source: str | None = None) -> str:
        raw_cause = str(value or "").strip().lower()
        if raw_cause in {"hydrique", "post_application", "rafraichissement_soir"}:
            return raw_cause
        raw_source = str(source or "").strip().lower()
        if raw_source in {"application_technique", "application_technique_auto", "manual_application"}:
            return "post_application"
        return "hydrique"

    def _get_canonical_watering_plan(
        self,
        *,
        objectif_mm: float | None = None,
        plan_arrosage_entity_id: str | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> WateringPlan | None:
        if plan_arrosage_entity_id:
            hass = getattr(self, "hass", None)
            states = getattr(hass, "states", None)
            plan_state = states.get(plan_arrosage_entity_id) if states is not None else None
            attrs = plan_state.attributes if plan_state is not None and isinstance(plan_state.attributes, Mapping) else {}
            normalized = normalize_existing_plan(attrs)
            if normalized is not None:
                return normalized

        try:
            objective = float(
                objectif_mm if objectif_mm is not None else self._current_snapshot().get("objectif_mm", 0.0)
            )
        except (TypeError, ValueError):
            objective = 0.0
        if objective <= 0:
            return None
        zones_cfg = [(entity_id, rate_mm_min * 60.0) for entity_id, rate_mm_min in self._iter_zones_with_rate()]
        if not zones_cfg:
            return None
        # LE SNAPSHOT D'ABORD, `self.data` seulement en repli.
        # `_maybe_schedule_auto_irrigation` tourne À L'INTÉRIEUR de `_async_update_data`, donc AVANT
        # que Home Assistant n'affecte le nouveau `self.data` : pendant tout le lancement, `self.data`
        # porte encore le cycle PRÉCÉDENT. Or l'objectif, lui, vient du snapshot frais — les deux
        # sources étaient désynchronisées.
        # Le biais allait systématiquement dans le mauvais sens : le fractionnement n'existe qu'au-delà
        # de FRACTIONNEMENT_NORMAL_SEUIL_MM, et c'est justement la transition « dose nulle → grosse
        # dose » (expiration du cooldown 24 h dans la fenêtre du matin, cas quotidien) qui le perdait.
        # Résultat mesuré : 11,2 mm délivrés en UN passage sans pause, au lieu de 2 passages + 25 min.
        _plan_source: Mapping[str, Any] = (
            snapshot if isinstance(snapshot, Mapping) and "watering_passages" in snapshot
            else (self.data if isinstance(self.data, Mapping) else {})
        )
        passages = _plan_source.get("watering_passages", 1)
        pause_minutes = _plan_source.get("watering_pause_minutes", 0)
        try:
            passages = max(1, int(passages or 1))
        except (TypeError, ValueError):
            passages = 1
        try:
            pause_minutes = max(0, int(pause_minutes or 0))
        except (TypeError, ValueError):
            pause_minutes = 0
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        watering_strategy = str(snapshot.get("watering_strategy") or "").strip() or None
        objective_scope = str(snapshot.get("objective_scope") or "").strip() or None
        watering_stage = str(snapshot.get("watering_stage") or "").strip() or None
        surface_cycle_mm = snapshot.get("surface_cycle_mm")
        daily_cycles_target = snapshot.get("daily_cycles_target")
        cycle_spacing_minutes = snapshot.get("cycle_spacing_minutes")
        surface_moisture_target = snapshot.get("surface_moisture_target")
        surface_dryness_risk = snapshot.get("surface_dryness_risk")
        runoff_risk = snapshot.get("runoff_risk")
        seeding_transition_ready = snapshot.get("seeding_transition_ready")
        seeding_block_reason = snapshot.get("seeding_block_reason")
        return build_watering_plan(
            objective,
            zones_cfg,
            passages=passages,
            pause_minutes=pause_minutes,
            watering_strategy=watering_strategy,
            objective_scope=objective_scope,
            watering_stage=watering_stage,
            surface_cycle_mm=surface_cycle_mm,
            daily_cycles_target=daily_cycles_target,
            cycle_spacing_minutes=cycle_spacing_minutes,
            surface_moisture_target=surface_moisture_target,
            surface_dryness_risk=surface_dryness_risk,
            runoff_risk=runoff_risk,
            seeding_transition_ready=seeding_transition_ready,
            seeding_block_reason=seeding_block_reason,
        )

    def _evening_cooling_done_today(self) -> bool:
        """True si un rafraîchissement du soir a déjà été enregistré aujourd'hui.

        Garde anti-boucle : comme le rafraîchissement est exempté du cooldown anti-relance, on
        s'assure qu'il ne part qu'UNE fois par soir (sinon il pourrait se relancer dans sa fenêtre)."""
        history = getattr(self, "history", None)
        if not isinstance(history, list):
            return False
        today = self._current_date()
        for item in reversed(history):
            if not isinstance(item, dict) or item.get("type") != "arrosage":
                continue
            if str(item.get("watering_cause") or "").strip().lower() != "rafraichissement_soir":
                continue
            recorded = item.get("recorded_at") or item.get("detected_at") or item.get("date")
            recorded_dt = self._parse_datetime_value(recorded)
            if recorded_dt is not None:
                if self._local_date_of(recorded_dt) == today:
                    return True
                continue
            if str(recorded or "").strip().startswith(today.isoformat()):
                return True
        return False

    def _recent_watering_block_active(self, objective_mm: float | None = None) -> bool:
        objective = float(objective_mm or 0.0)
        if objective <= 0:
            return False
        history = getattr(self, "history", None)
        if not isinstance(history, list):
            return False
        today = self._current_date()
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
                if self._local_date_of(recorded_dt) == today:
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
        runtime_session = self._get_active_irrigation_session()
        if isinstance(runtime_session, dict) and runtime_session.get("status") in {
            "running",
            "paused",
            "recovery_required",
        }:
            return True
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

    def _shared_valve_busy_elsewhere(self) -> bool:
        """Vrai si une AUTRE instance du domaine arrose une vanne physique partagée.

        Deux pelouses peuvent piloter le même relais (Sonoff 4CH). Le garde local
        `_watering_session_active` ne voit que ses propres sessions ; sans ce
        complément, deux instances pourraient ouvrir la même vanne. Garde purement
        ADDITIVE et en LECTURE SEULE de l'état des sœurs — jamais
        `_get_active_irrigation_session` (qui purge une session finie) : le seul
        effet possible est de REFUSER un lancement (sens de défaillance sûr, jamais
        de double-arrosage).

        En config réelle, la vanne partagée du Potager est neutralisée (débit 0) :
        `_iter_zones_with_rate` ne la yield pas → intersection vide → ce garde reste
        DORMANT (aucun changement de comportement). Il ne se déclenche que si deux
        instances déclarent un débit > 0 sur la même vanne — le seul cas qui peut
        réellement entrer en collision.
        """
        hass = getattr(self, "hass", None)
        domain_data = getattr(hass, "data", {}).get(DOMAIN) if hass is not None else None
        if not isinstance(domain_data, dict) or len(domain_data) < 2:
            return False
        try:
            my_valves = {entity_id for entity_id, _rate in self._iter_zones_with_rate()}
        except Exception:  # pragma: no cover - best effort fallback
            return False
        if not my_valves:
            return False
        for other in domain_data.values():
            if other is self or not isinstance(other, GazonIntelligentCoordinator):
                continue
            runtime = getattr(other, "_runtime_state", None)
            session = runtime.get("active_irrigation_session") if isinstance(runtime, dict) else None
            if not isinstance(session, dict):
                continue
            status = str(session.get("status") or "").strip().lower()
            if status not in {"running", "paused", "recovery_required"}:
                continue
            # Prédicat PUR (aucune mutation) : ignore une session en réalité terminée
            # mais pas encore purgée, pour ne jamais bloquer un lancement à tort.
            if self._is_finished_irrigation_session(session):
                continue
            try:
                other_valves = {entity_id for entity_id, _rate in other._iter_zones_with_rate()}
            except Exception:  # pragma: no cover - best effort fallback
                continue
            if my_valves & other_valves:
                return True
        return False

    def _mower_block_age_minutes(self, snapshot: dict[str, Any]) -> float:
        """Depuis combien de minutes le MÊME blocage tondeuse dure-t-il ? 0 si aucun ou s'il change.

        Volontairement NON persisté (absent de `_serialized_runtime_state`) : après un redémarrage
        de Home Assistant, le compteur repart de zéro et l'arrosage de détresse doit à nouveau
        observer un blocage continu avant de s'armer. C'est le sens protecteur — ne pas « corriger »
        en l'ajoutant au stockage, ce serait rouvrir la course au démarrage que ce compteur ferme.
        """
        reason = str(snapshot.get("watering_block_reason_code") or "").strip().lower()
        watch = self._runtime_state.get("mower_block_watch")
        if not reason or not bool(snapshot.get("watering_blocked_by_mower")):
            if watch is not None:
                self._runtime_state["mower_block_watch"] = None
            return 0.0
        now = self._current_utc_datetime()
        if isinstance(watch, dict) and str(watch.get("reason") or "") == reason:
            since = self._parse_datetime_value(watch.get("since"))
            if since is not None:
                return max(0.0, (now - since).total_seconds() / 60.0)
        self._runtime_state["mower_block_watch"] = {"reason": reason, "since": now.isoformat()}
        return 0.0

    def _should_launch_auto_irrigation(self, snapshot: dict[str, Any]) -> tuple[bool, str]:
        # Relevé AVANT toute sortie anticipée : sinon l'ancienneté mesurée dépendrait du motif de
        # sortie du cycle précédent, et un blocage réel pourrait n'être « vu » qu'au moment où
        # l'arrosage redevient recommandé — soit 30 minutes de retard sur une vraie détresse.
        mower_block_age_minutes = self._mower_block_age_minutes(snapshot)
        if self._auto_irrigation_safety_lock_active():
            return False, "safety_lock"
        if not self._runtime_state.get("auto_irrigation_bootstrap_complete"):
            return False, "startup_guard"
        if not self.auto_irrigation_enabled:
            return False, "auto_irrigation_disabled"
        # `auto_irrigation_user_confirmed` a été RETIRÉE ici le 29/07/2026 (arbitrage de Kévin) :
        # jamais écrite dans les 39 modules ni présente dans le stockage réel, elle valait toujours
        # None et cette garde ne s'est donc jamais déclenchée. L'interrupteur « arrosage
        # automatique » (`self.auto_irrigation_enabled`, vérifié juste au-dessus) remplit
        # exactement ce rôle, lui bien câblé. Ne pas la réintroduire.

        objectif_mm = float(snapshot.get("objectif_mm") or 0.0)
        if objectif_mm <= 0:
            return False, "no_objective"
        if not bool(snapshot.get("arrosage_recommande")):
            return False, "not_recommended"

        # Blocages explicites : type_arrosage bloqué, irrigation_blocked, tondeuse
        type_arrosage = str(snapshot.get("type_arrosage") or "").strip().lower()
        post_status = str(snapshot.get("application_post_watering_status") or "").strip().lower()
        post_application_auto_ready = (
            type_arrosage == "application_technique_auto"
            and post_status == "autorise"
            and bool(snapshot.get("arrosage_auto_autorise"))
        )
        # L'arrosage d'incorporation post-application est TECHNIQUE : il fait pénétrer le produit
        # dans le sol via l'eau (cf. fertigation). Un sol déjà humide ne doit donc PAS le bloquer —
        # c'est justement dans l'eau que le produit descend. On exempte l'incorporation auto du SEUL
        # motif « sol déjà humide » ; tous les autres motifs (pluie, tondeuse, sécurité, type bloqué)
        # restent bloquants.
        block_reason = snapshot.get("block_reason")
        block_reason_bloquant = block_reason is not None and not (
            post_application_auto_ready and block_reason == "sol_deja_humide"
        )
        # EXCEPTION DE DÉTRESSE — motif TONDEUSE uniquement.
        # Le blocage par la tondeuse n'a ni délai d'expiration ni porte de sortie : robot coincé
        # dehors, batterie à plat hors zone, API du fabricant en panne… `watering_blocked_by_mower`
        # reste vrai indéfiniment et l'arrosage auto n'est JAMAIS relancé — y compris réserve à sec
        # en pleine canicule (constaté le 05/07/2026 : réserve 0 mm à 32 °C pendant un blocage
        # tondeuse). Un robot mouillé est un moindre mal qu'un gazon grillé : il est conçu pour la
        # pluie et embarque son propre capteur.
        # L'exception est étroite : elle exige un déficit RÉELLEMENT critique
        # (`irrigation_blocked_but_critical`) ET un motif tondeuse PERSISTANT. Les états transitoires
        # (tonte en cours, retour à la station) en sont exclus : ils se résolvent seuls, et arroser
        # pendant que le robot tond le tremperait en plein cycle. Tous les autres motifs (pluie,
        # sol détrempé, sécurité, cooldown) restent bloquants, et le switch « arrosage auto » de
        # l'utilisateur est vérifié bien en amont — cette exception ne peut pas le contourner.
        mower_reason = str(snapshot.get("watering_block_reason_code") or "").strip().lower()
        mower_distress_override = (
            bool(snapshot.get("watering_blocked_by_mower"))
            and bool(snapshot.get("irrigation_blocked_but_critical"))
            and mower_reason in _MOWER_BLOCK_REASONS_PERSISTANTS
            and str(block_reason or "").strip().lower() == mower_reason
            # Le code de motif dit « ce genre de blocage ne se résout pas seul », pas « celui-ci
            # dure depuis longtemps ». Il faut les deux : cf. _MOWER_DISTRESS_MIN_BLOCK_MINUTES.
            and mower_block_age_minutes >= _MOWER_DISTRESS_MIN_BLOCK_MINUTES
        )
        if mower_distress_override:
            _LOGGER.warning(
                "Arrosage de détresse : le blocage tondeuse (%s, depuis %d min) est contourné car "
                "le sol est en déficit critique (%s). Vérifie l'état du robot — il est probablement "
                "bloqué dehors.",
                mower_reason,
                int(mower_block_age_minutes),
                snapshot.get("critical_deficit_mm"),
            )
        if not mower_distress_override and (
            type_arrosage == "bloque"
            or bool(snapshot.get("irrigation_blocked"))
            or bool(snapshot.get("watering_blocked_by_mower"))
            or block_reason_bloquant
        ):
            return False, "irrigation_blocked"
        if not mower_distress_override and not bool(snapshot.get("arrosage_auto_autorise")):
            return False, "auto_not_allowed"
        if not bool(snapshot.get("irrigation_execution_allowed", True)):
            return False, "execution_not_allowed"

        fenetre = str(snapshot.get("fenetre_optimale") or "").strip()
        # Le blocage tondeuse force lui-même `fenetre_optimale = "attendre"` : sans cette
        # exemption, l'arrosage de détresse resterait bloqué par le verrou qu'il vient de lever.
        if (
            not post_application_auto_ready
            and not mower_distress_override
            and fenetre in {"", "unknown", "unavailable", "none", "attendre"}
        ):
            return False, "window_unavailable"

        if self._watering_session_active() or self._shared_valve_busy_elsewhere():
            return False, "watering_in_progress"

        target_date = str(snapshot.get("watering_target_date") or "").strip()
        today_str = self._current_date().isoformat()
        if target_date and today_str < target_date:
            return False, "target_date_future"

        semis_progress = self._semis_cycle_progress(snapshot)
        if semis_progress is not None and not post_application_auto_ready:
            if int(semis_progress.get("cycles_remaining_today") or 0) <= 0:
                return False, "semis_target_reached"
            if str(semis_progress.get("state") or "") == "waiting":
                return False, "semis_cycle_pending"
        elif (
            not post_application_auto_ready
            and fenetre != "soir"
            and self._recent_watering_block_active(objectif_mm)
        ):
            # La fenêtre du soir (rafraîchissement canicule) n'est PAS bloquée par l'eau déjà
            # appliquée aujourd'hui : son but est de refroidir, pas de combler un déficit. La
            # protection anti-boucle est assurée par le cooldown de relance ci-dessous.
            return False, "recent_watering"

        if post_application_auto_ready:
            return True, "post_application_ready"

        # Rafraîchissement du soir (canicule) = petit arrosage TECHNIQUE → EXEMPTÉ du cooldown
        # anti-relance (sinon une recharge normale récente le bloquerait, cf. demande Kévin).
        # Garde anti-boucle dédiée à la place : il ne part qu'UNE fois par soir (déjà enregistré
        # en `rafraichissement_soir` aujourd'hui → on ne relance pas). Avec la fenêtre étroite
        # coucher-30→coucher, ça suffit à empêcher toute boucle.
        is_evening_cooling = (
            str(snapshot.get("watering_cause") or "").strip().lower() == "rafraichissement_soir"
        )
        if is_evening_cooling:
            if self._evening_cooling_done_today():
                return False, "evening_cooling_done"
        # Cooldown anti-relance (recharge normale uniquement) : après un cycle auto terminé, on
        # n'autorise pas un nouveau cycle avant AUTO_IRRIGATION_RELAUNCH_COOLDOWN (cause des
        # relances en boucle en canicule, où le déclencheur repartait ~10 s après la fin du cycle).
        # EXEMPTÉ aussi : le Sursemis (`semis_progress`), qui arrose volontairement plusieurs fois
        # par jour. Basé sur la fin du dernier cycle (état runtime persisté), pas sur l'historique
        # écrit en différé — donc fiable même juste après la clôture du cycle.
        elif semis_progress is None:
            last_completed = self._parse_datetime_value(
                self._runtime_state.get("last_auto_irrigation_completed_at")
            )
            if last_completed is not None:
                elapsed = (self._current_utc_datetime() - last_completed).total_seconds()
                if elapsed < AUTO_IRRIGATION_RELAUNCH_COOLDOWN.total_seconds():
                    return False, "relaunch_cooldown"

        current = self._current_datetime()
        current_minutes = current.hour * 60 + current.minute
        window_start = int(snapshot.get("watering_window_start_minute") or 0)
        window_end = int(snapshot.get("watering_window_end_minute") or 0)
        evening_start = int(snapshot.get("watering_evening_start_minute") or 1080)
        evening_end = int(snapshot.get("watering_evening_end_minute") or 1260)
        # Fenêtre réelle du rafraîchissement du soir = coucher-30 → coucher (calculée par la
        # décision). Les clés `watering_evening_*_minute` transitent par `advanced_context`
        # (decision.py) qui ne les porte pas → elles arrivent ici à None et retombent sur le défaut
        # figé 18-20 h, ce qui bloquerait à tort le lancement du cooling à ~coucher-30 (~21 h en
        # canicule). On lit donc la fenêtre fiable exposée par la décision via `evening_cooling_debug`
        # (mappée 1:1 depuis le profil, sans chemin concurrent). Repli sur les clés/défaut sinon.
        cooling_debug = snapshot.get("evening_cooling_debug")
        if isinstance(cooling_debug, dict):
            cooling_window = cooling_debug.get("evening_window_minutes")
            if (
                isinstance(cooling_window, (list, tuple))
                and len(cooling_window) == 2
                and cooling_window[0] is not None
                and cooling_window[1] is not None
            ):
                evening_start = int(cooling_window[0])
                evening_end = int(cooling_window[1])

        if fenetre == "soir":
            # La fenêtre « soir » n'est posée par la décision QUE si le vrai test du soir est
            # passé (coucher connu + marge ≥ 90 min + air ≤ 60 % + pas de risque fongique, dans
            # `_evening_window_allowed`). On ne re-vérifie donc pas `watering_evening_allowed`
            # ici (ce flag transite par un autre chemin, peu fiable, et bloquait à tort le
            # lancement) : « soir » fait foi. On contrôle seulement le créneau horaire.
            if not (evening_start <= current_minutes < evening_end):
                return False, "outside_evening_window"
        elif not (window_start <= current_minutes < window_end):
            return False, "outside_window"

        return True, "ready"

    _SKIP_NOISE_REASONS: frozenset[str] = frozenset(
        {
            "safety_lock",
            "startup_guard",
            "auto_irrigation_disabled",
            "no_objective",
            "not_recommended",
            "window_unavailable",
            "watering_in_progress",
            "target_date_future",
            "semis_target_reached",
            "semis_cycle_pending",
            "outside_window",
            "outside_evening_window",
            "relaunch_cooldown",
        }
    )

    def _maybe_record_skip(self, snapshot: dict[str, Any], reason: str) -> None:
        if reason in self._SKIP_NOISE_REASONS:
            return
        if not bool(snapshot.get("arrosage_recommande")):
            return
        fenetre = str(snapshot.get("fenetre_optimale") or "").strip()
        # DÉFAUT CORRIGÉ (29/07/2026) : le filtre testait `"matin"`, une valeur qui N'EXISTE PAS.
        # Les fenêtres réelles sont `ce_matin` / `demain_matin` / `maintenant` (cf.
        # `POSSIBLE_FENETRE_OPTIMALE_VALUES`, contre lequel `DecisionResult` normalise). Seuls les
        # refus du SOIR étaient donc enregistrés — et le diagnostic « derniers refus » laissait
        # croire qu'aucun refus matinal n'avait eu lieu, alors que le matin est la fenêtre
        # décisive. Un diagnostic qui ne couvre que la moitié des cas est pire qu'absent.
        # `apres_pluie` et `attendre` restent exclus : y renoncer n'est pas un refus, c'est le
        # comportement attendu.
        if fenetre not in _SKIP_RECORDED_WINDOWS:
            return

        today_str = self._current_date().isoformat()
        skip_key = f"{today_str}:{fenetre}"
        # `skip_keys_today` n'est JAMAIS restaurée depuis le stockage (absente des deux
        # constructeurs de `_runtime_state`) et son unique écrivain, plus bas, écrit une liste :
        # le `or []` suffit, le test de type était inatteignable.
        recorded: list[str] = self._runtime_state.get("skip_keys_today") or []
        if skip_key in recorded:
            return
        recorded.append(skip_key)
        self._runtime_state["skip_keys_today"] = recorded[-20:]

        objectif_mm: float | None = None
        try:
            v = float(snapshot.get("objectif_mm") or 0.0)
            objectif_mm = v if v > 0 else None
        except (TypeError, ValueError):
            pass

        raison_decision = str(snapshot.get("raison_decision") or "").strip() or None
        self.brain.record_skip(
            reason=reason,
            fenetre=fenetre,
            objectif_mm=objectif_mm,
            raison_decision=raison_decision,
        )

    async def _maybe_schedule_auto_irrigation(self, snapshot: dict[str, Any]) -> None:
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        if self._irrigation_launch_lock is None:
            self._irrigation_launch_lock = asyncio.Lock()
        async with self._irrigation_launch_lock:
            auto_task = getattr(self, "_auto_irrigation_task", None)
            scheduler_task = getattr(self, "_auto_irrigation_scheduler_task", None)
            if auto_task and not auto_task.done():
                return
            if scheduler_task and not scheduler_task.done():
                return

            should_launch, reason = self._should_launch_auto_irrigation(snapshot)
            self._set_last_auto_irrigation_reason(reason)
            if not should_launch:
                self._maybe_record_skip(snapshot, reason)
                await self._persist_runtime_state()
                return

            plan_entity_id = self._plan_arrosage_entity_id()
            plan = self._get_canonical_watering_plan(
                plan_arrosage_entity_id=plan_entity_id,
                snapshot=snapshot,
            )
            objectif_mm = None
            if plan is None:
                try:
                    objectif_mm = float(snapshot.get("objectif_mm") or 0.0)
                except (TypeError, ValueError):
                    objectif_mm = 0.0
                plan = self._get_canonical_watering_plan(objectif_mm=objectif_mm, snapshot=snapshot)
            if plan is None:
                self._set_last_auto_irrigation_reason("no_plan_available")
                await self._persist_runtime_state()
                return
            plan_feedback = plan.as_dict()
            auto_source = (
                "application_technique_auto"
                if str(snapshot.get("type_arrosage") or "").strip().lower() == "application_technique_auto"
                else "auto_irrigation"
            )
            action_label = (
                "Arrosage post-produit automatique"
                if auto_source == "application_technique_auto"
                else "Arrosage automatique"
            )

            async def _runner() -> None:
                self._emit_irrigation_event(
                    "gazon_intelligent_auto_irrigation_scheduled",
                    {
                        "reason": reason,
                        "watering_cause": snapshot.get("watering_cause"),
                        "plan_type": plan.plan_type,
                        "zone_count": len(plan.zones),
                        "passages": plan.passage_count,
                    },
                )
                await self.async_record_user_action(
                    action=action_label,
                    state="en_attente",
                    reason=f"{action_label} lancé, attente de la fin de la séquence.",
                    plan_type=str(plan_feedback.get("plan_type") or "no_plan"),
                    zone_count=int(plan_feedback.get("zone_count") or 0),
                    passages=int(plan_feedback.get("passages") or 1),
                )
                try:
                    await self.async_start_auto_irrigation(
                        objectif_mm,
                        plan_entity_id if plan_entity_id else None,
                        source=auto_source,
                        watering_cause=self._normalize_watering_cause(
                            snapshot.get("watering_cause"),
                            source=auto_source,
                        ),
                        user_action_context={
                            "action": action_label,
                            "success_reason": f"{action_label} exécuté avec succès.",
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
            return None
        if session["active_zones"]:
            return None

        ended_at = session.get("last_inactive_at")
        started_at = session.get("started_at")
        if not isinstance(ended_at, datetime) or not isinstance(started_at, datetime):
            return None

        session_duration_seconds = max((ended_at - started_at).total_seconds(), 0.0)
        if session_duration_seconds < WATERING_SESSION_MIN_DURATION_SECONDS:
            return None

        zones: list[dict[str, Any]] = []
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

        zones_total_mm = _zone_session_total_mm(zones) or 0.0
        objective_mm = self._round_runtime_mm(session.get("target_mm"))
        surface_mm = _zone_session_surface_mm(zones, objective_mm=objective_mm) or 0.0
        if surface_mm <= 0 and zones_total_mm <= 0:
            return None

        return {
            "date_action": ended_at.date(),
            # ⚠️ DÉBUT ET FIN, tous les deux. `started_at` servait uniquement à calculer la durée
            # puis était jeté : l'historique ne gardait que l'instant de FIN, et l'affichage
            # annonçait donc « arrosé à 05:18 » pour un cycle parti à 03:45:13 — treize secondes
            # après l'ouverture de la fenêtre. Signalé par Kévin le 04/08/2026, vérifié sur les
            # vannes : Z1 03:45→04:18, Z2 04:18→04:51, Z3 04:51→05:18.
            "started_at": started_at,
            "ended_at": ended_at,
            "objectif_mm": surface_mm,
            "objective_mm": surface_mm,
            "total_mm": surface_mm,
            "session_total_mm": surface_mm,
            "zones_total_mm": zones_total_mm,
            "mm_scope": "global_surface",
            "mm_interpretation": "surface_uniform",
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
            now = self._current_utc_datetime()
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
            started_at=payload.get("started_at"),
        )

    async def async_register_product(
        self,
        product_id: str,
        nom: str,
        type_produit: str,
        dose_conseillee: str | None = None,
        usage_mode: str | None = None,
        max_applications_per_year: int | None = None,
        reapplication_after_days: int | None = None,
        delai_avant_tonte_jours: int | None = None,
        phase_compatible: str | list[str] | None = None,
        application_months: str | list[int] | None = None,
        application_type: str | None = None,
        application_requires_watering_after: bool | None = None,
        application_post_watering_mm: float | None = None,
        application_irrigation_block_hours: float | None = None,
        application_irrigation_delay_minutes: float | None = None,
        application_irrigation_mode: str | None = None,
        application_label_notes: str | None = None,
        note: str | None = None,
        temperature_min: float | None = None,
        temperature_max: float | None = None,
    ) -> None:
        self.brain.register_product(
            product_id,
            nom,
            type_produit,
            dose_conseillee=dose_conseillee,
            usage_mode=usage_mode,
            max_applications_per_year=max_applications_per_year,
            reapplication_after_days=reapplication_after_days,
            delai_avant_tonte_jours=delai_avant_tonte_jours,
            phase_compatible=phase_compatible,
            application_months=application_months,
            application_type=application_type,
            application_requires_watering_after=application_requires_watering_after,
            application_post_watering_mm=application_post_watering_mm,
            application_irrigation_block_hours=application_irrigation_block_hours,
            application_irrigation_delay_minutes=application_irrigation_delay_minutes,
            application_irrigation_mode=application_irrigation_mode,
            application_label_notes=application_label_notes,
            note=note,
            temperature_min=temperature_min,
            temperature_max=temperature_max,
        )
        if self.shared_state is not None:
            await self.shared_state.async_save()
        await self._async_save_state()
        await self._async_refresh_all_coordinators()

    async def async_remove_product(self, product_id: str) -> None:
        self.brain.remove_product(product_id)
        if self.shared_state is not None:
            await self.shared_state.async_save()
        await self._async_save_state()
        await self._async_refresh_all_coordinators()

    async def async_remove_last_application(self) -> None:
        self.brain.remove_last_application()
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
                watering_cause="hydrique",
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
                watering_cause="hydrique",
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
                    watering_cause="post_application",
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
            # ENTITÉ : `or` et non `get(..., défaut)` — le défaut de `get` ne sert que si la clé est
            # ABSENTE. Une clé présente mais à None (ce que l'options flow écrivait) masquait la
            # valeur réelle d'entry.data et faisait disparaître la zone du plan, en silence.
            entity_id = opts.get(f"zone_{idx}") or data.get(f"zone_{idx}")
            # DÉBIT : surtout PAS `or` — 0.0 est FALSY mais parfaitement significatif, c'est la
            # façon offerte à l'utilisateur de neutraliser une zone. Avec `or`, un débit mis à 0
            # dans les options retombait sur l'ancienne valeur d'entry.data et RÉACTIVAIT la zone.
            # Cas réel : l'instance « Gazon Potager » pointe zone_1 sur la vanne de la zone 3 de la
            # pelouse principale, neutralisée par un débit à 0 — le `or` la remettait en service.
            # Il faut donc un test explicite sur None, qui distingue « absent » de « zéro voulu ».
            rate_h = opts.get(f"debit_zone_{idx}")
            if rate_h is None:
                rate_h = data.get(f"debit_zone_{idx}")
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
            # `rate_h` peut être absent (zone non configurée) : le `except` le traite, comme il
            # traite une valeur non numérique. Un débit inconnu vaut zéro → zone neutralisée.
            return float(rate_h) / 60.0  # type: ignore[arg-type]
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

    def _build_pending_zone_segments(self, plan: WateringPlan) -> list[dict[str, Any]]:
        pending: list[dict[str, Any]] = []
        for passage in range(1, plan.passage_count + 1):
            for zone_index, zone in enumerate(plan.zones):
                # Durée/mm PAR PASSAGE (zone_for_passage), pas la dose pleine : sur un cycle
                # fractionné (passages > 1), stocker `zone.duration_s`/`zone.mm` par passage
                # surestimait chaque segment (2 passages → 2× la dose affichée dans zones_pending).
                # Inerte aujourd'hui (l'exécution, le mm crédité et la reprise recalculent tous via
                # zone_for_passage), mais c'était un piège : un futur code lisant ces valeurs pour
                # la reprise aurait double-dosé. On stocke donc la valeur réellement délivrée.
                segment = plan.zone_for_passage(zone_index, passage)
                pending.append(
                    {
                        "passage": passage,
                        "zone_index": zone_index,
                        "zone": zone.zone,
                        "duration_s": segment.duration_s,
                        "mm": round(segment.mm, 1),
                    }
                )
        return pending

    def _build_zone_execution_record(
        self,
        *,
        zone,
        passage: int,
        order: int,
        effective_duration_s: float | None = None,
    ) -> dict[str, Any]:
        # `effective_duration_s` = temps pendant lequel la vanne a RÉELLEMENT été ouverte.
        # Sans lui, un relais retombé en cours de segment créditait quand même la dose pleine.
        prevu_s = float(zone.duration_s)
        reel_s = prevu_s if effective_duration_s is None else max(0.0, float(effective_duration_s))
        ratio = 1.0 if prevu_s <= 0 else min(1.0, reel_s / prevu_s)
        record: dict[str, Any] = {
            "order": order,
            "passage": passage,
            "zone": zone.zone,
            "entity_id": zone.zone,
            "rate_mm_h": round(zone.rate_mm_h, 1),
            "duration_s": int(reel_s),
            "duration_seconds": int(reel_s),
            "duration_min": round(reel_s / 60.0, 1),
            "mm": round(zone.mm * ratio, 1),
        }
        if ratio < 0.995:
            record["interrupted"] = True
            record["planned_duration_s"] = int(prevu_s)
        return record

    def _build_active_irrigation_session(
        self,
        *,
        plan: WateringPlan,
        source: str,
        strategy: str,
        watering_cause: str = "hydrique",
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = self._current_utc_datetime()
        return {
            "session_id": session_id or self._new_runtime_id("sess"),
            "run_id": run_id or self._new_runtime_id("irrig"),
            "source": source,
            "strategy": strategy,
            "watering_cause": self._normalize_watering_cause(watering_cause, source=source),
            "watering_strategy": plan.watering_strategy or strategy,
            "objective_scope": plan.objective_scope,
            "watering_stage": plan.watering_stage,
            "surface_cycle_mm": plan.surface_cycle_mm,
            "daily_cycles_target": plan.daily_cycles_target,
            "cycle_spacing_minutes": plan.cycle_spacing_minutes,
            "surface_moisture_target": plan.surface_moisture_target,
            "surface_dryness_risk": plan.surface_dryness_risk,
            "runoff_risk": plan.runoff_risk,
            "seeding_transition_ready": plan.seeding_transition_ready,
            "seeding_block_reason": plan.seeding_block_reason,
            "status": "running",
            "target_mm": round(plan.objective_mm, 1),
            "plan": plan.as_runtime_dict(),
            "passage_count": plan.passage_count,
            "current_passage": 1,
            "current_zone_index": 0,
            "current_zone": None,
            "active_zones": [],
            "zones_done": [],
            "zones_failed": [],
            "zones_pending": self._build_pending_zone_segments(plan),
            "planned_total_seconds": float(plan.total_duration_s),
            "started_at": now,
            "last_activity_at": now,
            "paused_until": None,
            "last_update": now,
            "last_error": None,
        }

    @staticmethod
    def _round_runtime_mm(value: Any) -> float:
        try:
            return round(max(0.0, float(value or 0.0)), 1)
        except (TypeError, ValueError):
            return 0.0

    def _build_execution_plan_metrics(self, session: dict[str, Any]) -> dict[str, Any]:
        plan = session.get("plan")
        if not isinstance(plan, dict):
            return {
                "planned_mm": 0.0,
                "planned_zone_count": 0,
                "planned_zone_segments": 0,
                "planned_total_seconds": self._round_runtime_mm(session.get("planned_total_seconds")),
            }
        zones = plan.get("zones")
        if not isinstance(zones, list):
            zones = []
        passage_count = max(1, int(plan.get("passages") or session.get("passage_count") or 1))
        planned_zone_count = len(zones)
        planned_zone_segments = planned_zone_count * passage_count
        planned_mm = self._round_runtime_mm(sum(self._round_runtime_mm(zone.get("mm")) for zone in zones))
        planned_total_seconds = 0.0
        try:
            planned_total_seconds = max(0.0, float(session.get("planned_total_seconds") or 0.0))
        except (TypeError, ValueError):
            planned_total_seconds = 0.0
        return {
            "planned_mm": planned_mm,
            "planned_zone_count": planned_zone_count,
            "planned_zone_segments": planned_zone_segments,
            "planned_total_seconds": int(round(planned_total_seconds)),
        }

    def _build_execution_reconciliation(
        self,
        session: dict[str, Any],
        *,
        status: str,
        recorded_watering: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan_metrics = self._build_execution_plan_metrics(session)
        zones_done = list(session.get("zones_done") or [])
        zones_failed = list(session.get("zones_failed") or [])
        executed_mm = self._round_runtime_mm(sum(self._round_runtime_mm(zone.get("mm")) for zone in zones_done))
        objective_mm = self._round_runtime_mm(session.get("target_mm"))
        planned_mm = self._round_runtime_mm(plan_metrics.get("planned_mm"))
        detected_mm = None
        if isinstance(recorded_watering, dict):
            detected_mm = recorded_watering.get("zones_total_mm")
            if detected_mm is None:
                detected_mm = recorded_watering.get("total_mm")
            if detected_mm is None:
                detected_mm = recorded_watering.get("session_total_mm")
            if detected_mm is None:
                detected_mm = recorded_watering.get("objectif_mm")
        detected_mm_value = None if detected_mm is None else self._round_runtime_mm(detected_mm)
        planned_zone_segments = int(plan_metrics.get("planned_zone_segments") or 0)
        executed_zone_segments = len(zones_done)
        failed_zone_segments = len(zones_failed)
        remaining_zone_segments = max(0, planned_zone_segments - executed_zone_segments - failed_zone_segments)
        planned_gap_mm = self._round_runtime_mm(planned_mm - executed_mm)
        detection_gap_mm = (
            self._round_runtime_mm(detected_mm_value - executed_mm)
            if detected_mm_value is not None
            else None
        )
        if status == "completed" and remaining_zone_segments == 0 and not zones_failed:
            completion_status = "completed"
        elif status == "completed":
            completion_status = "completed_partial"
        elif status == "failed" and executed_zone_segments > 0:
            completion_status = "failed_partial"
        else:
            completion_status = "failed"
        if completion_status == "completed" and detection_gap_mm in (None, 0.0):
            confidence = "high"
        elif completion_status in {"completed", "completed_partial"}:
            confidence = "medium"
        else:
            confidence = "low"
        return {
            "objective_mm": objective_mm,
            "planned_mm": planned_mm,
            "executed_mm": executed_mm,
            "detected_mm": detected_mm_value,
            "planned_gap_mm": planned_gap_mm,
            "detection_gap_mm": detection_gap_mm,
            "planned_zone_segments": planned_zone_segments,
            "executed_zone_segments": executed_zone_segments,
            "failed_zone_segments": failed_zone_segments,
            "remaining_zone_segments": remaining_zone_segments,
            "completion_status": completion_status,
            "confidence": confidence,
            "observation_source": (
                str(recorded_watering.get("source"))
                if isinstance(recorded_watering, dict) and recorded_watering.get("source")
                else None
            ),
        }

    def _detect_execution_anomalies(
        self,
        session: dict[str, Any],
        *,
        reconciliation: dict[str, Any],
        status: str,
    ) -> list[str]:
        anomalies: list[str] = []
        if status != "completed":
            anomalies.append("execution_not_completed")
        if reconciliation.get("failed_zone_segments", 0):
            anomalies.append("zone_failures")
        if reconciliation.get("remaining_zone_segments", 0):
            anomalies.append("segments_remaining")
        planned_gap_mm = self._round_runtime_mm(reconciliation.get("planned_gap_mm"))
        if planned_gap_mm >= 0.5:
            anomalies.append("executed_below_plan")
        detection_gap = reconciliation.get("detection_gap_mm")
        if detection_gap is not None and self._round_runtime_mm(abs(float(detection_gap))) >= 0.5:
            anomalies.append("detected_gap")
        if session.get("last_error"):
            anomalies.append("runtime_error")
        if bool(self._runtime_state.get("auto_irrigation_safety_lock")):
            anomalies.append("safety_lock")
        return anomalies

    def _persist_execution_snapshot(
        self,
        session: dict[str, Any],
        *,
        status: str,
        error: str | None = None,
        recorded_watering: dict[str, Any] | None = None,
    ) -> None:
        ended_at = self._current_utc_datetime()
        reconciliation = self._build_execution_reconciliation(
            session,
            status=status,
            recorded_watering=recorded_watering,
        )
        anomalies = self._detect_execution_anomalies(
            session,
            reconciliation=reconciliation,
            status=status,
        )
        plan_metrics = self._build_execution_plan_metrics(session)
        execution = {
            "session_id": session.get("session_id"),
            "run_id": session.get("run_id"),
            "source": session.get("source"),
            "strategy": session.get("strategy"),
            "watering_cause": self._normalize_watering_cause(
                session.get("watering_cause"),
                source=str(session.get("source") or ""),
            ),
            "target_mm": session.get("target_mm"),
            "planned_mm": plan_metrics.get("planned_mm"),
            "planned_zone_count": plan_metrics.get("planned_zone_count"),
            "planned_zone_segments": plan_metrics.get("planned_zone_segments"),
            "planned_total_seconds": plan_metrics.get("planned_total_seconds"),
            "status": status,
            "zones_done": list(session.get("zones_done") or []),
            "zones_failed": list(session.get("zones_failed") or []),
            "started_at": session.get("started_at"),
            "ended_at": ended_at,
            "last_error": error or session.get("last_error"),
            "reconciliation": reconciliation,
            "execution_anomalies": anomalies,
            "execution_confidence": reconciliation.get("confidence"),
            "completion_status": reconciliation.get("completion_status"),
        }
        self._set_last_irrigation_execution(execution)

    def _zone_semble_ouverte(self, entity_id: str) -> bool:
        """La vanne est-elle (encore) ouverte ?

        ⚠️ `unavailable` / `unknown` ne valent PAS « fermée ». Au redémarrage de Home Assistant
        l'entité disparaît quelques instants alors que le relais, lui, n'a pas bougé : conclure
        « fermée » couperait le comptage d'une eau réellement versée. Dans le doute on considère
        la vanne ouverte — c'est le seul repli qui ne perde pas d'eau réelle.
        """
        # Le veilleur ne doit JAMAIS pouvoir faire échouer un arrosage : toute lecture qui
        # tourne mal se lit « ouverte », c'est-à-dire « on ne change rien au comportement ».
        try:
            states = getattr(getattr(self, "hass", None), "states", None)
            state = states.get(entity_id) if states is not None else None
        except Exception:  # pragma: no cover - lecture d'état défensive
            return True
        if state is None:
            return True
        valeur = str(getattr(state, "state", "") or "").strip().lower()
        if valeur in {"unavailable", "unknown", ""}:
            return True
        return valeur == "on"

    async def _attendre_zone_ouverte(
        self, entity_id: str, duration_s: float, session: dict[str, Any]
    ) -> float:
        """Attend la durée du segment EN VÉRIFIANT que la vanne reste ouverte.

        L'exécuteur dormait en AVEUGLE : si le relais retombait — sécurité firmware, coupure,
        commande externe — il comptait quand même la dose entière. Des millimètres fantômes
        étaient alors crédités au bilan du sol pour de l'eau jamais versée, et le gazon séchait
        pendant que le modèle le croyait arrosé.

        Retourne les secondes pendant lesquelles la vanne a RÉELLEMENT été ouverte.
        """
        restant = max(0.0, float(duration_s))
        ouverte_s = 0.0
        relances = 0
        vue_ouverte = False
        while restant > 0:
            pas = min(_ZONE_WATCH_INTERVAL_S, restant)
            await asyncio.sleep(pas)
            restant -= pas
            if self._zone_semble_ouverte(entity_id):
                vue_ouverte = True
                ouverte_s += pas
                continue
            if not vue_ouverte:
                # ⚠️ On n'a JAMAIS constaté l'ouverture de cette vanne. Deux causes possibles :
                # la commande met un instant à se refléter dans l'état, ou l'entité ne rapporte
                # pas son état du tout. Dans les deux cas, conclure « elle est retombée »
                # abrégerait TOUS les segments et plus rien ne serait arrosé. Le veilleur
                # n'agit donc que sur une preuve : avoir vu la vanne ouverte, PUIS fermée.
                # Sans preuve, on compte le temps comme avant — pas de régression, seulement
                # pas d'amélioration.
                ouverte_s += pas
                continue
            if relances >= _ZONE_WATCH_MAX_RELANCES:
                # Deuxième chute : ce n'est plus un accident. On abrège le segment plutôt que
                # de dormir sur une vanne fermée, et on ne compte que ce qui a coulé.
                session.setdefault("zones_failed", []).append(
                    {
                        "passage": session.get("current_passage"),
                        "zone": entity_id,
                        "status": "zone_dropped",
                        "error": "La vanne s'est refermée seule pendant l'arrosage.",
                    }
                )
                _LOGGER.warning(
                    "Zone %s refermée seule pendant l'arrosage : segment abrégé à %.0f s",
                    entity_id,
                    ouverte_s,
                )
                break
            relances += 1
            _LOGGER.warning("Zone %s retombée pendant l'arrosage : relance %d", entity_id, relances)
            try:
                await self.hass.services.async_call(
                    "switch", "turn_on", {"entity_id": entity_id}, blocking=True
                )
            except Exception:  # pragma: no cover - on abrège plutôt que d'insister
                _LOGGER.warning("Relance de la zone %s impossible : segment abrégé", entity_id)
                break
        return ouverte_s

    async def _safe_turn_off_zone(self, entity_id: str, session: dict[str, Any]) -> None:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                await asyncio.shield(
                    self.hass.services.async_call(
                        "switch",
                        "turn_off",
                        {"entity_id": entity_id},
                        blocking=True,
                    )
                )
                return
            except Exception as err:  # pragma: no cover - safety path
                last_error = err
                if attempt < 2:
                    await asyncio.sleep(0.2)
        message = f"Echec arrêt zone {entity_id}: {last_error}"
        session["status"] = "failed"
        session["last_error"] = message
        session["active_zones"] = []
        session["last_update"] = self._current_utc_datetime()
        session["last_activity_at"] = session["last_update"]
        session.setdefault("zones_failed", []).append(
            {
                "passage": session.get("current_passage"),
                "zone_index": session.get("current_zone_index"),
                "zone": entity_id,
                "status": "shutdown_uncertain",
                "error": message,
            }
        )
        self._persist_execution_snapshot(session, status="failed", error=message)
        await self._set_irrigation_safety_lock(message, entity_id)
        self._emit_irrigation_event(
            "gazon_intelligent_auto_irrigation_failed",
            self._build_runtime_payload_for_event(
                session,
                failed_zone=entity_id,
                error=message,
                shutdown_uncertain=True,
            ),
        )
        raise HomeAssistantError(message)

    async def _execute_canonical_watering_plan(
        self,
        *,
        plan: WateringPlan,
        source: str,
        strategy: str,
        watering_cause: str = "hydrique",
        user_action_context: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
    ) -> None:
        user_action_context = dict(user_action_context or {})
        # ATTENDRE QUE LES VANNES RÉPONDENT AVANT DE LANCER. `switch.turn_on` sur une entité
        # `unavailable` ne lève aucune erreur : la commande part dans le vide, aucune goutte n'est
        # délivrée, et la dose complète est pourtant comptabilisée en fin de cycle — le gazon
        # reste sec pendant que l'intégration affiche un arrosage réussi et crédite la réserve.
        # Ce garde existait déjà mais n'était branché que sur le chemin de REPRISE après
        # redémarrage ; le lancement normal (auto comme manuel) ne le traversait pas.
        zone_ids = [getattr(z, "zone", None) for z in (plan.zones or [])]
        if session is None and not await self._wait_for_zones_available(zone_ids):
            _LOGGER.error(
                "Arrosage annulé : vannes indisponibles après 60 s (%s). Aucune commande envoyée, "
                "aucune dose comptabilisée.",
                ", ".join(str(z) for z in zone_ids if z) or "aucune zone",
            )
            self._emit_irrigation_event(
                "gazon_intelligent_auto_irrigation_failed",
                {"reason": "zones_unavailable", "zones": [str(z) for z in zone_ids if z]},
            )
            return
        runtime_session = session or self._build_active_irrigation_session(
            plan=plan,
            source=source,
            strategy=strategy,
            watering_cause=watering_cause,
        )
        runtime_session["watering_cause"] = self._normalize_watering_cause(
            runtime_session.get("watering_cause"),
            source=source,
        )
        runtime_session["planned_total_seconds"] = float(plan.total_duration_s)
        runtime_session.setdefault("last_activity_at", runtime_session.get("started_at"))
        self._set_active_irrigation_session(runtime_session)
        await self._persist_runtime_state()
        self._emit_irrigation_event(
            "gazon_intelligent_auto_irrigation_started",
            self._build_runtime_payload_for_event(runtime_session, target_mm=plan.objective_mm),
        )
        error_reason: str | None = None
        cancelled = False
        executed_zones: list[dict[str, Any]] = list(runtime_session.get("zones_done") or [])
        # Suspend le moniteur passif de sessions pendant tout le cycle piloté (passages ET
        # pauses) : c'est ce cycle qui enregistre l'arrosage (source auto/manuel). Sans ça,
        # le moniteur passif finalise un doublon `zone_session` à chaque pause inter-passage
        # (la garde _zone_tracking_suspended était déclarée mais jamais armée → l'arrosage
        # était compté plusieurs fois, sur-créditant la réserve et le budget hebdo).
        self._zone_tracking_suspended += 1
        try:
            start_passage = max(1, int(runtime_session.get("current_passage") or 1))
            start_zone_index = max(0, int(runtime_session.get("current_zone_index") or 0))
            # Reprise après redémarrage : temps restant à appliquer à la 1ʳᵉ zone reprise
            # (calculé dans _resume_active_irrigation_session, vanne restée ouverte incluse).
            resume_remaining_s = runtime_session.pop("resume_zone_remaining_s", None)
            for passage in range(start_passage, plan.passage_count + 1):
                runtime_session["status"] = "running"
                runtime_session["current_passage"] = passage
                if passage != start_passage:
                    start_zone_index = 0
                for zone_index, zone in enumerate(plan.zones[start_zone_index:], start=start_zone_index):
                    zone_segment = plan.zone_for_passage(zone_index, passage)
                    sleep_duration_s = float(zone_segment.duration_s)
                    if resume_remaining_s is not None and passage == start_passage and zone_index == start_zone_index:
                        # On ne ré-arrose que le temps restant de la zone interrompue.
                        try:
                            sleep_duration_s = max(0.0, float(resume_remaining_s))
                        except (TypeError, ValueError):
                            sleep_duration_s = float(zone_segment.duration_s)
                        resume_remaining_s = None
                    if zone_segment.duration_s <= 0 or sleep_duration_s <= 0:
                        continue
                    runtime_session["current_zone_index"] = zone_index
                    runtime_session["current_zone"] = zone.zone
                    runtime_session["current_zone_started_at"] = self._current_utc_datetime()
                    runtime_session["active_zones"] = [zone.zone]
                    runtime_session["last_update"] = runtime_session["current_zone_started_at"]
                    runtime_session["last_activity_at"] = runtime_session["last_update"]
                    await self._persist_runtime_state()
                    self._emit_irrigation_event(
                        "gazon_intelligent_auto_irrigation_zone_started",
                        self._build_runtime_payload_for_event(
                            runtime_session,
                            zone=zone.zone,
                            duration_s=zone_segment.duration_s,
                        ),
                    )
                    try:
                        await self.hass.services.async_call(
                            "switch",
                            "turn_on",
                            {"entity_id": zone.zone},
                            blocking=True,
                        )
                    except Exception as err:
                        message = f"Echec démarrage zone {zone.zone}: {err}"
                        runtime_session["status"] = "failed"
                        runtime_session["last_error"] = message
                        runtime_session["last_update"] = self._current_utc_datetime()
                        runtime_session["last_activity_at"] = runtime_session["last_update"]
                        runtime_session.setdefault("zones_failed", []).append(
                            {
                                "passage": passage,
                                "zone_index": zone_index,
                                "zone": zone.zone,
                                "status": "turn_on_failed",
                                "error": message,
                            }
                        )
                        await self._persist_runtime_state()
                        raise HomeAssistantError(message) from err

                    try:
                        ouverte_s = await self._attendre_zone_ouverte(
                            zone.zone, sleep_duration_s, runtime_session
                        )
                    finally:
                        await self._safe_turn_off_zone(zone.zone, runtime_session)

                    record = self._build_zone_execution_record(
                        zone=zone_segment,
                        passage=passage,
                        order=len(executed_zones) + 1,
                        effective_duration_s=ouverte_s,
                    )
                    executed_zones.append(record)
                    runtime_session["zones_done"] = executed_zones
                    runtime_session["zones_pending"] = [
                        pending
                        for pending in runtime_session.get("zones_pending", [])
                        if not (
                            int(pending.get("passage") or 0) == passage
                            and int(pending.get("zone_index") or -1) == zone_index
                        )
                    ]
                    runtime_session["active_zones"] = []
                    runtime_session["current_zone"] = None
                    runtime_session["current_zone_started_at"] = None
                    runtime_session["current_zone_index"] = zone_index + 1
                    runtime_session["last_update"] = self._current_utc_datetime()
                    runtime_session["last_activity_at"] = runtime_session["last_update"]
                    await self._persist_runtime_state()
                    self._emit_irrigation_event(
                        "gazon_intelligent_auto_irrigation_zone_finished",
                        self._build_runtime_payload_for_event(
                            runtime_session,
                            zone=zone.zone,
                            duration_s=zone_segment.duration_s,
                            mm=zone_segment.mm,
                        ),
                    )

                if passage < plan.passage_count and plan.pause_between_passages_s > 0:
                    runtime_session["status"] = "paused"
                    runtime_session["current_passage"] = passage + 1
                    runtime_session["current_zone_index"] = 0
                    runtime_session["paused_until"] = self._current_utc_datetime() + timedelta(
                        seconds=plan.pause_between_passages_s
                    )
                    runtime_session["last_update"] = self._current_utc_datetime()
                    runtime_session["last_activity_at"] = runtime_session["last_update"]
                    await self._persist_runtime_state()
                    await asyncio.sleep(plan.pause_between_passages_s)
                    runtime_session["status"] = "running"
                    runtime_session["paused_until"] = None
                    runtime_session["last_update"] = self._current_utc_datetime()
                    runtime_session["last_activity_at"] = runtime_session["last_update"]
                    await self._persist_runtime_state()

            zones_total_mm = round(sum(float(zone.get("mm") or 0.0) for zone in executed_zones), 1)
            surface_mm = round(float(plan.objective_mm), 1)
            semis_strategy = str(plan.watering_strategy or "").strip() == WATERING_STRATEGY_SEMIS_FREQUENT
            # Annotée : sans ça la valeur est inférée comme l'union de TOUS les types du
            # littéral, et les 13 arguments qu'on en tire plus bas étaient signalés un par un
            # alors qu'ils sont chacun du bon type à leur clé.
            recorded_watering: dict[str, Any] = {
                "date_action": self._current_date().isoformat(),
                "objectif_mm": float(surface_mm),
                "objective_mm": float(surface_mm),
                "total_mm": float(surface_mm),
                "session_total_mm": float(surface_mm),
                "zones_total_mm": float(zones_total_mm),
                "mm_scope": "surface_cycle" if semis_strategy else "global_surface",
                "mm_interpretation": "surface_cycle" if semis_strategy else "surface_uniform",
                "zones": list(executed_zones),
                "source": source,
                "watering_cause": runtime_session.get("watering_cause"),
                "watering_strategy": runtime_session.get("watering_strategy") or plan.watering_strategy,
                "objective_scope": runtime_session.get("objective_scope") or plan.objective_scope,
                "watering_stage": runtime_session.get("watering_stage") or plan.watering_stage,
                "surface_cycle_mm": runtime_session.get("surface_cycle_mm") or plan.surface_cycle_mm or surface_mm,
                "daily_cycles_target": runtime_session.get("daily_cycles_target") or plan.daily_cycles_target,
                "cycle_spacing_minutes": runtime_session.get("cycle_spacing_minutes") or plan.cycle_spacing_minutes,
                "surface_moisture_target": runtime_session.get("surface_moisture_target") or plan.surface_moisture_target,
                "surface_dryness_risk": runtime_session.get("surface_dryness_risk") or plan.surface_dryness_risk,
                "runoff_risk": runtime_session.get("runoff_risk") or plan.runoff_risk,
                "seeding_transition_ready": runtime_session.get("seeding_transition_ready")
                if runtime_session.get("seeding_transition_ready") is not None
                else plan.seeding_transition_ready,
                "seeding_block_reason": runtime_session.get("seeding_block_reason") or plan.seeding_block_reason,
            }
            await self.async_record_watering(
                self._current_date(),
                objectif_mm=surface_mm,
                total_mm=surface_mm,
                zones=executed_zones,
                source=source,
                watering_cause=runtime_session.get("watering_cause"),
                mm_scope=recorded_watering["mm_scope"],
                mm_interpretation=recorded_watering["mm_interpretation"],
                watering_strategy=recorded_watering["watering_strategy"],
                objective_scope=recorded_watering["objective_scope"],
                watering_stage=recorded_watering["watering_stage"],
                surface_cycle_mm=recorded_watering["surface_cycle_mm"],
                daily_cycles_target=recorded_watering["daily_cycles_target"],
                cycle_spacing_minutes=recorded_watering["cycle_spacing_minutes"],
                surface_moisture_target=recorded_watering["surface_moisture_target"],
                surface_dryness_risk=recorded_watering["surface_dryness_risk"],
                runoff_risk=recorded_watering["runoff_risk"],
                seeding_transition_ready=recorded_watering["seeding_transition_ready"],
                seeding_block_reason=recorded_watering["seeding_block_reason"],
            )
            self._persist_execution_snapshot(
                runtime_session,
                status="completed",
                recorded_watering=recorded_watering,
            )
            self._emit_irrigation_event(
                "gazon_intelligent_auto_irrigation_completed",
                self._build_runtime_payload_for_event(
                    runtime_session,
                    total_mm=surface_mm,
                    completion_status="completed",
                ),
            )
            if user_action_context:
                await self.async_record_user_action(
                    action=str(user_action_context.get("action")),
                    state="ok",
                    reason=str(user_action_context.get("success_reason") or "Arrosage terminé avec succès."),
                    plan_type=user_action_context.get("plan_type"),
                    zone_count=user_action_context.get("zone_count"),
                    passages=user_action_context.get("passages"),
                )
        except asyncio.CancelledError:
            cancelled = True
            raise
        except HomeAssistantError as err:
            error_reason = str(err)
            runtime_session["status"] = "failed"
            runtime_session["last_error"] = error_reason
            runtime_session["active_zones"] = []
            runtime_session["last_update"] = self._current_utc_datetime()
            runtime_session["last_activity_at"] = runtime_session["last_update"]
            self._persist_execution_snapshot(runtime_session, status="failed", error=error_reason)
            await self._persist_runtime_state()
            self._emit_irrigation_event(
                "gazon_intelligent_auto_irrigation_failed",
                self._build_runtime_payload_for_event(
                    runtime_session,
                    error=error_reason,
                    completion_status="failed",
                ),
            )
            if user_action_context:
                await self.async_record_user_action(
                    action=str(user_action_context.get("action")),
                    state="refuse",
                    reason=error_reason,
                    plan_type=user_action_context.get("plan_type"),
                    zone_count=user_action_context.get("zone_count"),
                    passages=user_action_context.get("passages"),
                )
        except Exception as err:  # pragma: no cover - best effort cleanup
            error_reason = str(err)
            runtime_session["status"] = "failed"
            runtime_session["last_error"] = error_reason
            runtime_session["active_zones"] = []
            runtime_session["last_update"] = self._current_utc_datetime()
            runtime_session["last_activity_at"] = runtime_session["last_update"]
            self._persist_execution_snapshot(runtime_session, status="failed", error=error_reason)
            await self._persist_runtime_state()
            self._emit_irrigation_event(
                "gazon_intelligent_auto_irrigation_failed",
                self._build_runtime_payload_for_event(
                    runtime_session,
                    error=error_reason,
                    completion_status="failed",
                ),
            )
            _LOGGER.exception("Echec arrosage automatique (%s)", source)
            if user_action_context:
                await self.async_record_user_action(
                    action=str(user_action_context.get("action")),
                    state="refuse",
                    reason=error_reason,
                    plan_type=user_action_context.get("plan_type"),
                    zone_count=user_action_context.get("zone_count"),
                    passages=user_action_context.get("passages"),
                )
        finally:
            # La garde compteur (armée avant la boucle, donc avant toute ouverture de vanne
            # du cycle) suffit à empêcher le moniteur passif de doublonner ce cycle. On NE
            # purge PAS la session passive ici : une session externe/manuelle légitime en
            # fenêtre de grâce (vannes déjà fermées, finalize en attente) ne bloque pas le
            # lancement auto — l'effacer ferait perdre son enregistrement.
            self._zone_tracking_suspended = max(0, self._zone_tracking_suspended - 1)
            if self._zone_tracking_suspended == 0:
                # Mémorise l'instant de reprise du moniteur passif : tout OFF dont le
                # segment a démarré avant cet instant appartient au cycle qu'on vient de
                # piloter (cf. _handle_zone_state_change) et ne doit pas être recompté.
                self._zone_tracking_resumed_at = self._current_utc_datetime()
            self._auto_irrigation_task = None
            if not cancelled:
                if str(source or "") == "auto_irrigation":
                    # Arme le cooldown anti-relance : un cycle auto vient de se terminer.
                    self._runtime_state["last_auto_irrigation_completed_at"] = self._current_utc_datetime()
                self._set_active_irrigation_session(None)
                await self._persist_runtime_state()

    async def _wait_for_zones_available(
        self, zone_ids: list[str | None], timeout_s: float = 60.0, poll_s: float = 1.0
    ) -> bool:
        """Attend que les vannes (switch) soient disponibles avant d'agir.

        Après un redémarrage de HA, les entités restent 'unavailable' quelques secondes : agir
        trop tôt enverrait les commandes dans le vide. Renvoie True dès que toutes sont
        disponibles, False si le délai est dépassé (l'appareil ne répond pas)."""
        ids = [str(z) for z in (zone_ids or []) if z]
        if not ids:
            return True
        waited = 0.0
        while waited < timeout_s:
            ready = True
            for zid in ids:
                state = self.hass.states.get(zid)
                if state is None or str(state.state).lower() in {"unavailable", "unknown"}:
                    ready = False
                    break
            if ready:
                return True
            await asyncio.sleep(poll_s)
            waited += poll_s
        return False

    async def _resume_active_irrigation_session(self, session: dict[str, Any]) -> None:
        plan = normalize_existing_plan(session.get("plan"))
        if plan is None:
            session["status"] = "failed"
            session["last_error"] = "Plan persistant invalide."
            self._persist_execution_snapshot(session, status="failed", error=session["last_error"])
            self._set_active_irrigation_session(None)
            await self._persist_runtime_state()
            return

        # Attendre que l'appareil d'arrosage (vannes) soit disponible avant toute action :
        # au boot, la vanne est restée ouverte mais l'entité HA est 'unavailable' un instant.
        if not await self._wait_for_zones_available([getattr(z, "zone", None) for z in (plan.zones or [])]):
            session["status"] = "failed"
            session["last_error"] = "device_unavailable_on_resume"
            self._persist_execution_snapshot(session, status="failed", error=session["last_error"])
            self._set_active_irrigation_session(None)
            await self._persist_runtime_state()
            return

        if session.get("status") == "paused":
            paused_until = session.get("paused_until")
            if isinstance(paused_until, datetime):
                delay = max(0.0, (paused_until - self._current_utc_datetime()).total_seconds())
                if delay > 0:
                    await asyncio.sleep(delay)
            session["status"] = "running"
            session["paused_until"] = None
        elif session.get("status") == "running" and session.get("current_zone"):
            current_zone = str(session.get("current_zone"))
            zone_index = int(session.get("current_zone_index") or 0)
            passage = int(session.get("current_passage") or 1)
            # La vanne est restée ouverte pendant le redémarrage : le temps écoulé depuis le
            # démarrage de la zone compte comme de l'arrosage. On reprend donc la zone pour son
            # TEMPS RESTANT (durée cible − temps déjà écoulé), au lieu de la sauter.
            started = session.get("current_zone_started_at")
            try:
                target_s = float(plan.zone_for_passage(zone_index, passage).duration_s)
            except Exception:  # pragma: no cover - plan dégradé
                target_s = 0.0
            remaining_s = target_s
            if isinstance(started, datetime) and target_s > 0:
                elapsed = (self._current_utc_datetime() - started).total_seconds()
                remaining_s = target_s - max(0.0, elapsed)
            if remaining_s > WATERING_SESSION_MIN_SEGMENT_SECONDS:
                # Il reste de l'eau à mettre → on reprend la MÊME zone pour le temps restant.
                session["resume_zone_remaining_s"] = remaining_s
                session["status"] = "running"
            else:
                # La zone a reçu sa dose (voire plus) pendant l'indisponibilité → on la ferme
                # proprement et on passe à la suivante.
                try:
                    await self._safe_turn_off_zone(current_zone, session)
                except HomeAssistantError:
                    return
                session.setdefault("zones_failed", []).append(
                    {
                        "passage": passage,
                        "zone_index": zone_index,
                        "zone": current_zone,
                        "status": "completed_during_downtime",
                        "error": "restart_recovery",
                    }
                )
                session["status"] = "recovery_required"
                session["active_zones"] = []
                session["current_zone"] = None
                session["current_zone_started_at"] = None
                session["current_zone_index"] = zone_index + 1
                session["last_error"] = "restart_recovery"

        session["last_update"] = self._current_utc_datetime()
        session["last_activity_at"] = session["last_update"]
        await self._persist_runtime_state()

        await self._execute_canonical_watering_plan(
            plan=plan,
            source=str(session.get("source") or "auto_irrigation"),
            strategy=str(session.get("strategy") or "plan"),
            watering_cause=self._normalize_watering_cause(
                session.get("watering_cause"),
                source=str(session.get("source") or "auto_irrigation"),
            ),
            session=session,
        )

    async def _restore_active_irrigation_session(self) -> None:
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        session = self._runtime_state.get("active_irrigation_session")
        if not isinstance(session, dict):
            return
        if self._is_finished_irrigation_session(session):
            status = "failed" if session.get("last_error") else "completed"
            self._persist_execution_snapshot(session, status=status, error=session.get("last_error"))
            self._set_active_irrigation_session(None)
            if status == "completed":
                await self._finalize_pending_irrigation_user_action(
                    execution=self._runtime_state.get("last_irrigation_execution"),
                )
            await self._persist_runtime_state()
            return
        if self._auto_irrigation_safety_lock_active():
            # Verrou de sécurité actif (vanne non confirmée fermée lors d'un cycle) : ne
            # PAS reprendre l'arrosage au redémarrage. On marque la session échouée ;
            # la reprise restera gelée tant que le verrou n'est pas levé (bouton « Retour
            # au mode normal » / service reset_mode).
            session["status"] = "failed"
            session["last_error"] = "safety_lock_active"
            self._persist_execution_snapshot(session, status="failed", error="safety_lock_active")
            self._set_active_irrigation_session(None)
            await self._persist_runtime_state()
            return
        if not self.auto_irrigation_enabled and str(session.get("source") or "") == "auto_irrigation":
            # L'arrosage automatique a été COUPÉ avant ce redémarrage : reprendre le cycle
            # reviendrait à passer outre une décision explicite. La reprise ne consultait pas
            # ce drapeau — un cycle interrompu repartait donc tout seul, auto désactivé.
            # Une session MANUELLE, elle, reste légitime : l'utilisateur l'a demandée.
            session["status"] = "cancelled"
            session["last_error"] = "auto_irrigation_disabled"
            self._persist_execution_snapshot(session, status="cancelled", error="auto_irrigation_disabled")
            self._set_active_irrigation_session(None)
            await self._persist_runtime_state()
            return
        if self._auto_irrigation_task and not self._auto_irrigation_task.done():
            return
        if session.get("status") not in {"running", "paused", "recovery_required"}:
            return
        self._auto_irrigation_task = self.hass.async_create_task(
            self._resume_active_irrigation_session(session),
            "gazon_intelligent_auto_irrigation_resume",
        )

    async def async_stop_irrigation(self, *, reason: str | None = None) -> dict[str, Any]:
        """Arrête immédiatement le cycle d'arrosage en cours.

        Trois choses doivent arriver ensemble, sinon l'arrêt laisse le système dans un état
        pire que l'arrosage qu'il interrompt :

        1. **La vanne se referme.** C'est déjà acquis : le `sleep` de chaque segment est
           enveloppé d'un `try/finally` qui appelle `_safe_turn_off_zone`, lui-même protégé
           par `asyncio.shield` — la fermeture survit donc à l'annulation de la tâche.
        2. **La session est effacée.** Le `finally` de `_execute_canonical_watering_plan` ne
           purge la session que `if not cancelled` : ce choix sert l'arrêt de Home Assistant,
           où la session DOIT survivre pour être reprise au redémarrage. Un arrêt volontaire
           veut l'inverse — sans purge explicite ici, la session resterait « en cours » et
           `_maybe_resume_active_irrigation_session` la relancerait au prochain démarrage.
        3. **L'eau déjà versée est enregistrée.** Sinon le bilan du sol ne la voit pas et le
           système réarrose : c'est la cause racine « le système ne voit pas ce qu'il vient
           d'arroser ». Les zones terminées sont dans `zones_done` ; la zone interrompue en
           plein segment n'y est PAS (son enregistrement se fait après le `try/finally`), on
           la reconstitue donc au prorata du temps réellement écoulé.

        Idempotent : sans arrosage en cours, ne fait rien et le dit.
        """
        session = self._get_active_irrigation_session()
        task = getattr(self, "_auto_irrigation_task", None)
        task_vivante = task is not None and not task.done()

        if not isinstance(session, dict) and not task_vivante:
            return {"stopped": False, "reason": "aucun_arrosage_en_cours", "applied_mm": 0.0}

        # Relevé AVANT annulation : après, la session peut avoir été rincée par le `finally`.
        instantane = dict(session) if isinstance(session, dict) else {}
        zone_en_cours = instantane.get("current_zone")
        debut_zone = instantane.get("current_zone_started_at")
        passage = int(instantane.get("current_passage") or 1)
        index_zone = int(instantane.get("current_zone_index") or 0)
        source = str(instantane.get("source") or "auto_irrigation")

        if task_vivante and task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # pragma: no cover - la tâche a déjà journalisé son échec
                _LOGGER.debug("Arrêt d'arrosage : la tâche s'est terminée en erreur", exc_info=True)

        # Relu APRÈS l'annulation : une zone a pu se terminer normalement entre-temps.
        session_apres = self._get_active_irrigation_session()
        if isinstance(session_apres, dict):
            instantane = dict(session_apres)
        zones_faites: list[dict[str, Any]] = [
            dict(z) for z in (instantane.get("zones_done") or []) if isinstance(z, dict)
        ]

        zone_partielle = self._build_interrupted_zone_record(
            session=instantane,
            zone=zone_en_cours,
            started_at=debut_zone,
            passage=passage,
            zone_index=index_zone,
            order=len(zones_faites) + 1,
        )
        if zone_partielle is not None:
            zones_faites.append(zone_partielle)

        applique_mm = self._round_runtime_mm(
            sum(self._round_runtime_mm(z.get("mm")) for z in zones_faites)
        )

        if applique_mm > 0:
            # `source` conservé (auto_irrigation / manual…) pour que les garde-fous existants
            # comptent cette eau comme n'importe quelle autre ; c'est `watering_cause` qui
            # porte l'information « cycle interrompu ».
            await self.async_record_watering(
                self._current_date(),
                objectif_mm=applique_mm,
                total_mm=applique_mm,
                zones=zones_faites,
                source=source,
                watering_cause="arret_manuel",
                mm_scope="global_surface",
                mm_interpretation="surface_uniform",
            )

        self._set_active_irrigation_session(None)
        self._auto_irrigation_task = None
        await self._persist_runtime_state()

        motif = str(reason or "").strip() or "Arrêt demandé."
        self._emit_irrigation_event(
            "gazon_intelligent_auto_irrigation_stopped",
            {
                "reason": motif,
                "applied_mm": applique_mm,
                "zone_count": len(zones_faites),
                "interrupted_zone": zone_en_cours,
                "source": source,
            },
        )
        await self.async_record_user_action(
            action="stop_irrigation",
            state="ok",
            reason=f"{motif} {applique_mm:.1f} mm déjà appliqués.".strip(),
        )
        await self.async_request_refresh()
        return {
            "stopped": True,
            "applied_mm": applique_mm,
            "zone_count": len(zones_faites),
            "interrupted_zone": zone_en_cours,
        }

    def _build_interrupted_zone_record(
        self,
        *,
        session: dict[str, Any],
        zone: Any,
        started_at: Any,
        passage: int,
        zone_index: int,
        order: int,
    ) -> dict[str, Any] | None:
        """Reconstitue au prorata la zone coupée en plein segment.

        Sans elle, arrêter un cycle à mi-zone perdrait cette eau pour le bilan du sol.
        On borne au segment planifié : une horloge qui aurait sauté ne doit pas créditer
        plus que ce que la vanne pouvait physiquement délivrer.
        """
        if not zone or not isinstance(started_at, datetime):
            return None
        segment = next(
            (
                s
                for s in (session.get("zones_pending") or [])
                if isinstance(s, dict)
                and str(s.get("zone")) == str(zone)
                and int(s.get("passage") or 0) == passage
                and int(s.get("zone_index") or -1) == zone_index
            ),
            None,
        )
        if segment is None:
            return None
        duree_prevue_s = float(segment.get("duration_s") or 0.0)
        mm_prevus = float(segment.get("mm") or 0.0)
        if duree_prevue_s <= 0 or mm_prevus <= 0:
            return None
        ecoule_s = (self._current_utc_datetime() - started_at).total_seconds()
        ecoule_s = max(0.0, min(ecoule_s, duree_prevue_s))
        mm = self._round_runtime_mm(mm_prevus * (ecoule_s / duree_prevue_s))
        if mm <= 0:
            return None
        return {
            "order": order,
            "passage": passage,
            "zone": str(zone),
            "entity_id": str(zone),
            "duration_s": int(ecoule_s),
            "duration_seconds": int(ecoule_s),
            "duration_min": round(ecoule_s / 60.0, 1),
            "mm": mm,
            "interrupted": True,
        }

    async def async_start_auto_irrigation(
        self,
        objectif_mm: float | None,
        plan_arrosage_entity_id: str | None = None,
        source: str = "auto_irrigation",
        watering_cause: str | None = None,
        user_action_context: dict[str, Any] | None = None,
    ) -> None:
        """Arrose automatiquement chaque zone en séquence selon le débit renseigné."""
        source = str(source or "auto_irrigation")
        user_action_context = dict(user_action_context or {})
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        if self._irrigation_launch_lock is None:
            self._irrigation_launch_lock = asyncio.Lock()
        if self._irrigation_launch_lock.locked() and source not in AUTO_IRRIGATION_AUTO_SOURCES:
            raise HomeAssistantError("Un lancement d'arrosage est déjà en préparation.")
        async with self._irrigation_launch_lock:
            if source in AUTO_IRRIGATION_AUTO_SOURCES and self._auto_irrigation_safety_lock_active():
                raise HomeAssistantError("L'arrosage automatique est verrouillé après une erreur critique.")
            if source in AUTO_IRRIGATION_AUTO_SOURCES and not self.auto_irrigation_enabled:
                raise HomeAssistantError("L'arrosage automatique est désactivé.")
            # Même garde inerte retirée ici (cf. `_should_launch_auto_irrigation`) : l'exception
            # qu'elle levait n'a jamais pu se produire.
            if self._watering_session_active():
                raise HomeAssistantError("Un arrosage est déjà en cours.")
            # Relues dans des locales : `getattr(...) and self._attr.done()` garde bien contre
            # l'absence, mais rend la protection invisible au vérificateur comme au lecteur.
            _auto_task = getattr(self, "_auto_irrigation_task", None)
            _sched_task = getattr(self, "_auto_irrigation_scheduler_task", None)
            if _auto_task is not None and not _auto_task.done():
                raise HomeAssistantError("Un arrosage automatique est déjà en cours.")
            if (
                _sched_task is not None
                and not _sched_task.done()
                and source not in AUTO_IRRIGATION_AUTO_SOURCES
            ):
                raise HomeAssistantError("Un arrosage automatique est déjà programmé.")

            plan = self._get_canonical_watering_plan(
                objectif_mm=objectif_mm,
                plan_arrosage_entity_id=plan_arrosage_entity_id,
                snapshot=self._current_snapshot(),
            )
            if plan is None:
                if plan_arrosage_entity_id:
                    raise HomeAssistantError("Le plan d'arrosage est vide ou invalide.")
                raise HomeAssistantError(
                    "Aucune zone d'arrosage valide n'est configurée (zone + débit mm/h)."
                )
            strategy = "plan" if plan_arrosage_entity_id else "fallback"
            self._auto_irrigation_task = self.hass.async_create_task(
                self._execute_canonical_watering_plan(
                    plan=plan,
                    source=source,
                    strategy=strategy,
                    watering_cause=self._normalize_watering_cause(watering_cause, source=source),
                    user_action_context=user_action_context,
                ),
                "gazon_intelligent_auto_irrigation_sequence",
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
        self._cancel_watering_session_finalize()
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
        """Récupère la valeur effective (options > partagé > data > défaut)."""
        default = DEFAULT_TYPE_SOL if key == CONF_TYPE_SOL else None
        try:
            entry = self.hass.config_entries.async_get_entry(self.entry.entry_id) or self.entry
        except AttributeError:
            entry = self.entry
        resolved = resolve_effective_config(
            entry,
            key,
            shared_state=getattr(self, "shared_state", None),
            default=default,
        )
        return resolved.get("effective_value")

    async def async_update_config(self, updates: dict[str, Any]) -> None:
        """Met à jour les options de config en gardant la valeur courante comme base."""
        new_options = dict(self.entry.options)
        new_options.update(updates)
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        shared_state = getattr(self, "shared_state", None)
        if shared_state is not None:
            shared_updates = {key: value for key, value in updates.items() if key in SHARED_WEATHER_CONFIG_KEYS}
            if shared_updates:
                await shared_state.async_update_shared_config(shared_updates)
                await self._async_refresh_all_coordinators(restart_monitoring=True)
                return
        await self.async_request_refresh()
        await self.async_start_source_monitoring()
        await self.async_start_zone_monitoring()
        await self.async_request_refresh()

    async def _async_refresh_all_coordinators(self, *, restart_monitoring: bool = False) -> None:
        coordinators = self.hass.data.get(DOMAIN)
        if not isinstance(coordinators, dict):
            return
        refresh_tasks: list[asyncio.Task] = []
        for coordinator in coordinators.values():
            if not isinstance(coordinator, GazonIntelligentCoordinator):
                continue
            if restart_monitoring:
                await coordinator.async_start_source_monitoring()
                await coordinator.async_start_zone_monitoring()
            refresh_tasks.append(self.hass.async_create_task(coordinator.async_request_refresh()))
        if refresh_tasks:
            await asyncio.gather(*refresh_tasks, return_exceptions=True)

    def get_used_entities_attributes(self) -> dict[str, Any] | None:
        """Expose un contexte compact pour les attributs visibles."""
        pluie_demain_source = None
        if self.data:
            pluie_demain_source = self.data.get("pluie_demain_source")
            if pluie_demain_source == PLUIE_SOURCE_INDISPONIBLE:
                pluie_demain_source = PLUIE_SOURCE_NON_DISPONIBLE
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
        clean = _clean_empty_attrs(attrs) or {}
        configuration = clean.get("configuration")
        if isinstance(configuration, dict):
            configuration = _clean_empty_attrs(configuration)
            if configuration:
                clean["configuration"] = configuration
            else:
                clean.pop("configuration", None)
        return clean or None

    async def _async_load_state(self) -> None:
        """Charge l'état persistant (mode, date_action)."""
        shared_state = getattr(self, "shared_state", None)
        if shared_state is not None:
            await shared_state.async_load()
        data = await self._store.async_load() or {}
        shared_products = shared_state.products if shared_state is not None else None
        self.brain.load_state(data, shared_products=shared_products)
        if shared_state is not None and not shared_state.shared_config:
            await shared_state.async_bootstrap_from_entry(self.entry)
        if shared_state is not None:
            await shared_state.async_save()
        self._restore_runtime_state(data.get("runtime"))

    async def _async_save_state(self) -> None:
        """Sauvegarde l'état persistant (mode, date_action)."""
        # Écriture IMMÉDIATE et volontaire (pas de `async_delay_save`) : cette méthode est aussi
        # appelée aux transitions d'arrosage (ouverture/fermeture de vanne, verrou de sécurité),
        # où l'état DOIT survivre à une coupure de HA pour ne pas laisser une vanne « oubliée » ou
        # reprendre un cycle fantôme. Un debounce global gagnerait quelques écouts SD au prix de
        # cette durabilité — compromis refusé (cf. audit [6]). HA écrit déjà fréquemment `.storage`.
        payload = self.brain.dump_state()
        payload["runtime"] = self._serialized_runtime_state()
        await self._store.async_save(payload)
