from __future__ import annotations

from datetime import date, timedelta
from datetime import datetime, timezone
from math import isfinite
import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    WATERING_CAUSES,
    DOMAIN,
    DEFAULT_AUTO_IRRIGATION_ENABLED,
    DEFAULT_AUTO_MOWING_DECLARATION_ENABLED,
    DEFAULT_AUTO_MOWING_DECLARATION_MINUTES,
    DEFAULT_EVENING_COOLING_ENABLED,
    DEFAULT_MOWER_COORDINATION_ENABLED,
    DEFAULT_MOWER_CONTROL_MODE,
    DEFAULT_MOWER_START_WINDOW_POLICY,
    DEFAULT_MOWER_CONTROL_MIN_BATTERY,
    DEFAULT_MOWER_CONTROL_COMMAND_COOLDOWN_MINUTES,
    DEFAULT_MOWER_GARAGE_CLOSE_AFTER_DOCK,
    DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES,
    DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES,
    DEFAULT_MOWER_GARAGE_OPEN_BEFORE_START,
    DEFAULT_MOWER_GARAGE_OPEN_FOR_RETURN,
    DEFAULT_MOWER_GARAGE_MIN_OPEN_POSITION,
    DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES,
    CONF_CAPTEUR_ETP,
    CONF_CAPTEUR_PLUIE_24H,
    CONF_CAPTEUR_PLUIE_ACTUELLE,
    CONF_CAPTEUR_PLUIE_CUMUL,
    CONF_CAPTEUR_PLUIE_DEMAIN,
    CONF_ENTITE_METEO,
    CONF_CAPTEUR_TEMPERATURE,
    CONF_CAPTEUR_HUMIDITE,
    CONF_CAPTEUR_HUMIDITE_SOL,
    CONF_CAPTEUR_VENT,
    CONF_CAPTEUR_ROSEE,
    CONF_CAPTEUR_POINT_DE_ROSEE,
    CONF_CAPTEUR_RAYONNEMENT,
    CONF_CAPTEUR_PRESSION,
    CONF_CAPTEUR_HAUTEUR_GAZON,
    CONF_CAPTEUR_RETOUR_ARROSAGE,
    CONF_ENTITE_POMPE,
    CONF_ENTITE_TONDEUSE,
    CONF_ENTITE_VOLET_GARAGE_TONDEUSE,
    CONF_CAPTEUR_TONDEUSE_ERREUR,
    CONF_CAPTEUR_TONDEUSE_BATTERIE,
    CONF_CAPTEUR_TONDEUSE_PLUIE,
    CONF_CAPTEUR_TONDEUSE_EN_CHARGE,
    CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART,
    CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE,
    CONF_HAUTEUR_COUPE_TONDEUSE_MM,
    CONF_HAUTEUR_MAX_TONDEUSE_CM,
    CONF_HAUTEUR_MIN_TONDEUSE_CM,
    CONF_PILOTAGE_TONDEUSE,
    CONF_TONDEUSE_CRENEAUX_DEPART,
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
from .decision_risk import (
    compute_fungal_risk as _compute_fungal_risk,
    update_fungal_wetness_state,
)
from .memory import compute_application_state
from .decision_mowing import _NO_ERROR_CODES
from .mower_adapter import build_mower_context, derive_related_entity_id
from .mower_coordination import build_mower_coordination_context
from .mower_control import evaluate_mower_control
from .entity_ids import public_entity_id, resolve_entry_instance_slug
from .shared_state import get_shared_state, resolve_effective_config
from .soil_balance import appliquer_cliquet_pluie
from .const import CONF_REGLAGES, SHARED_WEATHER_CONFIG_KEYS
from .reglages import lire as lire_reglage
from .reglages import nettoyer as nettoyer_reglages
from . import ia
from . import notifications
from . import sources as sources_meteo
from .guidance import SEMIS_VENT_MAX_KMH
from .coordinator_constants import (
    AUTO_IRRIGATION_AUTO_SOURCES,
    AUTO_IRRIGATION_CHECK_INTERVAL,
    AUTO_IRRIGATION_RELAUNCH_COOLDOWN,
    _BATTERIE_RETOUR_VIDE_PCT,
    _ECHANTILLON_MAX_MINUTES,
    _FALLBACK_DAY_END_MINUTE,
    _FALLBACK_DAY_START_MINUTE,
    _MOWER_BLOCK_REASONS_PERSISTANTS,
    _MOWER_DISTRESS_MIN_BLOCK_MINUTES,
    _PASSES_JOURNAL_MAX,
    _PASSES_MIN_POUR_APPRENDRE,
    _PLUIE_GAIN_MAX_PAR_PAS_MM,
    _PLUIE_LAME_FENETRE_MINUTES,
    _PLUIE_LAME_MAX_ENTREES,
    _PLUIE_MESUREE_FENETRE_MINUTES,
    _PLUIE_MESUREE_HAUSSE_MIN_MM,
    _RECOMMANDATION_IGNOREE_MINUTES,
    _SKIP_RECORDED_WINDOWS,
    _SUN_KNOWN_STATES,
    _ZONE_WATCH_INTERVAL_S,
    _ZONE_WATCH_MAX_RELANCES,
    WATERING_SUNRISE_MARGIN_MINUTES,
)
from .coordinator_helpers import (
    _clean_empty_attrs,
    _float_conf_value,
    _mediane,
    _passe_a_retenir,
    _to_float_or_none,
)
from .coordinator_irrigation import (
    build_pending_zone_segments,
    build_zone_execution_record,
    is_matching_zone_segment,
    plan_morning_departure,
    zone_rate_mm_h,
    zone_rate_mm_min,
)
from .coordinator_runtime import (
    WATERING_RECORDED_KEY,
    build_execution_plan_metrics,
    build_active_irrigation_session as build_runtime_active_irrigation_session,
    build_runtime_payload_for_event,
    current_objective_mm,
    deserialize_active_irrigation_session,
    is_finished_irrigation_session,
    local_date_of as runtime_local_date_of,
    local_datetime_text,
    minutes_creditables as runtime_minutes_creditables,
    new_runtime_id,
    normalize_watering_cause,
    parse_datetime_value,
    round_runtime_mm,
    serialize_runtime_value,
)
from .coordinator_observability import (
    build_observability_payload,
    etp_ecoulee_du_jour,
    extract_block_reason,
)
from .coordinator_states import (
    get_bool_state,
    get_float_state,
    get_state_unit,
    get_text_state,
    validate_sensor_value,
)
from .coordinator_weather import (
    estimate_rosee,
    et_elapsed_fraction,
    sun_event_minute_from_context,
    sunset_today_minute_from_context,
)
from .water import (
    wind_speed_to_kmh as _wind_speed_to_kmh,
    pression_vers_hpa as _pression_vers_hpa,
    compute_recent_watering_mm,
    compute_eto_hourly as water_compute_eto_hourly,
    _zone_session_surface_mm,
    _zone_session_total_mm,
    surface_mm_depuis_segments,
)
from .weather_adapter import WeatherAdapter
from .watering_plan import ZonePlan, WateringPlan, build_watering_plan, normalize_existing_plan
from .watering_policy import repartir_creneaux_semis, resolve_semis_stage_program

_LOGGER = logging.getLogger(__name__)

_MOWER_JOB_DOCKED_GRACE_MINUTES = 60

# Un arrêt demandé pendant les toutes dernières écritures ne doit pas rester suspendu si le
# stockage Home Assistant se bloque. La tâche continue sous shield : elle porte l'événement de fin,
# le cooldown et la dernière exécution, donc l'annuler créerait un état plus ambigu que l'attente.
_STOP_FINALIZATION_TIMEOUT_SECONDS = 30.0

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
    "risque_gazon_brut",
    "risque_amortissement",
    "stress_palier_et0",
    "stress_palier_et0_montee",
    "semis_meteo_ajustement",
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
    "hauteur_tonte_motif",
    "semis_mode",
    "semis_age_jours",
    "plantules_levee_date",
    "plantules_hauteur_estimee_cm",
    "plantules_premiere_coupe_date",
    "plantules_coupes",
    "derniere_tonte_date",
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
    "tondeuse_resolution_probe",
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
    "mower_dock_signal_fort",
    "mower_reason_code",
    "mower_reason_label",
    "mower_battery",
    "mower_next_departure",
    "mower_control_mode",
    "mower_control_state",
    "mower_control_reason",
    "mower_control_pending_action",
    "mower_control_last_action",
    "mower_control_last_action_at",
    "mower_control_last_error",
    "mower_control_cycle_state",
    "mower_control_resume_required",
    "mower_control_resume_reason",
    "mower_garage_entity",
    "mower_garage_state",
    "mower_resolution_state",
    "mower_resolution_reason",
    "mower_resolution_candidate_count",
    "mower_resolution_probe",
    # ⚠️ FIABILITÉ DE LA MACHINE — cumul de la journée. Sans ces clés, il faut rejouer
    # l'historique à la main pour découvrir que le robot passe plus de temps coincé qu'à
    # tondre (03/08/2026 : 174 min tondues contre 318 bloquées).
    "mower_blocked_minutes_today",
    "mower_mowing_minutes_today",
    "mower_block_count_today",
    "mower_reliability_today",
    # ⚠️ AUTO-DÉCLARATION — sans ces clés, impossible de savoir POURQUOI une tonte n'a pas été
    # inscrite (interrupteur coupé ? sous le seuil ? tondeuse injoignable ?). Un automatisme
    # muet qui n'agit pas est indiscernable d'un automatisme cassé.
    "mower_job_completion_state",
    "mower_job_followed_id",
    "mower_job_seen_incomplete",
    "mower_job_minutes_total",
    "mower_job_resume_possible",
    "mower_job_paused_since",
    "mower_auto_declaration_state",
    "mower_auto_declaration_threshold_minutes",
    "mower_auto_declared_today",
    # Ajoutée en 0.82.0 : la grandeur RÉELLEMENT comparée au plancher. Sans elle à l'écran,
    # « travail_trop_court » ne dit pas s'il manquait dix minutes ou une heure — et c'est
    # justement ce qu'il fallait savoir pour trouver le défaut du 08/09.
    "mower_travail_termine_minutes_jour",
    # ⚠️ CARNET DE PASSES — observation pure, aucune décision n'en dépend. Préfixe `mower_`
    # obligatoire : deux filtres de recopie (decision_mowing, decision) ne laissent passer du
    # contexte tondeuse que `tondeuse_` et `mower_`. Une clé `mowing_…` y meurt en silence.
    "mower_pass_in_progress",
    "mower_pass_count_today",
    "mower_last_pass_minutes",
    "mower_last_pass_battery_start",
    "mower_last_pass_battery_end",
    "mower_last_pass_end_reason",
    "mower_passes_observed",
    "mower_full_pass_minutes_median",
    "mower_autonomous_return_battery_median",
    "mower_passes_per_day_median",
    "mower_recommendation_ignored_minutes",
    "mower_recommendation_ignored",
    "mower_job_progress_pct",
    "mower_job_id",
    "mower_job_status_raw",
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
    "semis_weather_cycles_target",
    "semis_cycles_limited_by_window",
    "semis_cycles_limit_reason",
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
    "application_en_cours",
    "application_foliaire_en_cours",
    "application_foliaire_label",
    "application_inconnue_en_cours",
    "application_inconnue_label",
    "application_block_label",
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
    "fungal_wetness_duration_hours",
    "fungal_wetness_source",
    "fungal_wetness_status",
)


def _changer_de_reference(suivi: dict[str, Any], entite: Any, lecture: float) -> None:
    """Un pluviomètre remplacé repart de SA lecture ; le total du jour et la lame récente restent.

    ⚠️ UN AUTRE CAPTEUR NE SE COMPARE PAS AU MAXIMUM DE L'ANCIEN (0.95.0, la page change les
    entrées). Plus bas, il ne compterait plus rien tant qu'il n'a pas dépassé ce maximum — des
    semaines de pluie perdues pour le compteur, qui ne repart jamais à zéro. Plus haut, l'écart
    serait pris pour une averse. Aucun des deux n'est de la pluie : la nouvelle lecture devient la
    référence, et rien n'est compté sur ce cycle.
    Un suivi d'avant la 0.95.0 n'a pas d'entité : il adopte celle du moment, sans rien changer.
    Sans référence du tout, rien n'est inventé : « aucune référence = aucun total » (PR #49).
    """
    entite = str(entite or "")
    if suivi.get("entite") not in (None, entite) and suivi.get("pic") is not None:
        suivi["pic"] = lecture
    suivi["entite"] = entite


class GazonIntelligentCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinateur principal de l'intégration Gazon Intelligent."""

    # Traçage du cycle (instrumentation pure). Annoté au niveau de la classe : mypy déduisait
    # sinon le type `None` de la première affectation et refusait l'origine textuelle.
    _cycle_origine_demandee: str | None = None
    _cycle_sequence: int = 0
    # ⚠️ Vrai UNIQUEMENT pendant `_async_update_data`. Lu par
    # `_rafraichir_apres_action_utilisateur` pour interdire la réentrance — voir sa docstring.
    _dans_le_cycle: bool = False
    # (réglages bruts lus dans les options, réglages nettoyés) — voir `_reglages_instance`.
    _reglages_cache: tuple[Any, dict[str, Any]] | None = None
    # Entrées configurées introuvables dans Home Assistant, et depuis quand (mémoire seule).
    _mesures_absentes_depuis: dict[str, datetime] | None = None
    _rosees_ignorees: set[str] | None = None

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
        # Non persisté : chaque redémarrage impose au moins un cycle complet sans commande.
        self._mower_control_bootstrap_complete = False
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
        return local_datetime_text(value, local_timezone=self._local_timezone())

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
        pluie_cumul_jour: float | None = None,
    ) -> tuple[float | None, str, float | None, str]:
        forecast_pluie_24h = forecast_summary.get("forecast_pluie_24h")
        forecast_pluie_demain = forecast_summary.get("forecast_pluie_demain")
        # `pluie_24h` / `pluie_demain` sont OPTIONNELLES : ni capteur ni prévision n'est garanti,
        # et le libellé de source dit explicitement « non disponible » dans ce cas.
        pluie_24h: float | None
        pluie_demain: float | None
        # ⚠️ PRIORITÉ AU TOTAL DÉRIVÉ DU COMPTEUR PROPRE. Quand `capteur_pluie_cumul` est
        # renseigné, l'intégration dérive elle-même le total du jour depuis un compteur monotone,
        # avec cliquet sur le maximum et mémoire persistée. C'est structurellement meilleur qu'un
        # cumul journalier fourni tel quel :
        #   · il ne peut PAS redescendre — mesuré sur le Netatmo du voisin : 3,6 → 3,0 mm dans la
        #     même journée, ce qui est impossible pour une pluie et a imposé un cliquet correctif ;
        #   · sa remise à zéro tombe à NOTRE minuit, pas plusieurs dizaines de minutes après ;
        #   · il vient du jardin, pas de chez le voisin. Mesuré le 08/09/2026 sur le même épisode :
        #     station 1,4 mm contre Netatmo 0,7 — un facteur DEUX.
        # ⚠️ Le libellé commence par « capteur » à dessein : `gazon_brain` teste ce PRÉFIXE pour
        # décider si la valeur est une mesure (à créditer au sol) ou une prévision (à ignorer).
        if pluie_cumul_jour is not None:
            pluie_24h = float(pluie_cumul_jour)
            pluie_24h_source = "capteur_cumul_station"
        elif pluie_24h_sensor is not None:
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
        _pression_entite = self._get_conf(CONF_CAPTEUR_PRESSION)
        pressure = self._get_float_state(_pression_entite)
        if pressure is not None:
            # La chaîne ET0 attend des hPa (`p_kpa = pressure_hpa / 10`). Le WS90 publie des kPa.
            pressure = round(_pression_vers_hpa(pressure, self._get_state_unit(_pression_entite)), 2)
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
        # ⚠️ LE SUIVI DES GRAINES N'ARRIVAIT À AUCUN CAPTEUR (0.96.1). Il entre dans la décision
        # par le contexte d'exécution, mais `DecisionResult` ne le porte pas : les neuf clés
        # `semis_*` de la liste ci-dessus valaient donc toujours `None`, et la page ne savait ni
        # combien de cycles étaient faits ni l'heure du suivant. Recalculé ici sur la décision
        # qui vient d'être prise.
        payload.update(self._suivi_des_graines(snapshot))
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
        # Étape 2 : l'heure de départ réellement visée ce matin et la fin prévue (minutes locales),
        # par la même fonction que le lanceur, exemptions comprises (semis, post-produit, soir,
        # blocage tondeuse : rien de calé à annoncer). Rien non plus sans arrosage demandé, ni
        # quand l'arrosage automatique ne partira pas de lui-même.
        try:
            objectif_publie = float(snapshot.get("objectif_mm") or 0.0)
        except (TypeError, ValueError):
            objectif_publie = 0.0
        depart = (
            self._morning_departure(snapshot)
            if objectif_publie > 0 and self._auto_irrigation_can_start(snapshot)
            else None
        )
        payload["watering_departure_minute"] = depart["departure_minute"] if depart else None
        payload["watering_end_minute"] = depart["end_minute"] if depart else None
        return payload

    async def _async_update_data(self) -> dict[str, Any]:
        """Récupère et calcule les données exposées par l'intégration."""
        self._dans_le_cycle = True
        try:
            return await self._calculer_donnees()
        finally:
            # `finally` et non une remise à zéro en fin de méthode : une exception au milieu du
            # cycle laisserait sinon le drapeau levé pour toujours, et TOUTES les actions de
            # l'utilisateur retomberaient définitivement sur le chemin lent.
            self._dans_le_cycle = False

    async def _rafraichir_apres_action_utilisateur(self) -> None:
        """Rafraîchissement IMMÉDIAT : quelqu'un vient d'agir, il attend devant son écran.

        ⚠️ POURQUOI CETTE MÉTHODE EXISTE — mesuré le 10/09/2026 : « quand je clique j'ai
        quelques secondes avant que ça se mette à jour ». Le coordinateur s'initialise sans
        debouncer personnalisé, il hérite donc de celui de Home Assistant :

            REQUEST_REFRESH_DEFAULT_COOLDOWN  = 10 s
            REQUEST_REFRESH_DEFAULT_IMMEDIATE = True   (HA 2026.2.3)

        `immediate=True` fait passer le PREMIER appel tout de suite, puis ferme la porte
        pendant dix secondes : les demandes suivantes sont regroupées et n'aboutissent qu'à
        l'expiration du délai. Or `async_request_refresh` n'est pas sollicité que par les
        actions : chaque changement d'un capteur suivi (station météo, tondeuse, vannes) en
        demande un aussi. Sur cette installation le debouncer est donc presque toujours dans sa
        fenêtre, et un clic attendait le reste des dix secondes.

        Le clic passait bien, le service s'exécutait, le cerveau était à jour : seule la
        REPUBLICATION des capteurs attendait. Une attente invisible se lit « ça n'a pas marché ».

        ⚠️ ON NE TOUCHE PAS AU CHEMIN DES CAPTEURS. Un capteur météo qui bouge peut attendre dix
        secondes ; c'est même ce qui protège cette installation d'un recalcul en boucle. Seules
        les actions de l'utilisateur passent devant.

        ⚠️ RÉENTRANCE INTERDITE, ET GARDÉE PAR LE CODE. Rafraîchir depuis l'INTÉRIEUR du cycle
        de mise à jour se rappellerait lui-même. Le piège est connu ici : c'est lui qui a imposé
        l'écriture synchrone dans le cerveau pour la déclaration automatique de tonte, où le
        commentaire dit « jamais `async_record_mowing` : celle-ci appelle
        `async_request_refresh()`, or on est à l'intérieur du cycle ». Cette promesse tenait par
        la discipline ; elle tient désormais par une garde. Depuis le cycle, on retombe sur le
        chemin débouncé, qui lui est sûr.
        """
        if self._dans_le_cycle:
            await self.async_request_refresh()
            return
        await self.async_refresh()

    async def _calculer_donnees(self) -> dict[str, Any]:
        """Corps du cycle. Séparé pour que `_async_update_data` porte le drapeau de réentrance."""
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
        # ⚠️ Sur `pluie_24h_sensor` — le capteur RÉEL — et surtout pas sur `pluie_24h`, qui
        # retombe sur la prévision quand le capteur manque. Nourrir la garde « il pleut » avec
        # un repli météo la ramènerait exactement à l'aveuglement qu'elle vient de corriger.
        weather_profile.update(self._suivre_pluie_mesuree(pluie_24h_sensor))
        weather_profile.update(self._lire_pluie_actuelle())
        weather_profile.update(self._suivre_pluie_du_jour())
        pluie_24h, pluie_24h_source, pluie_demain, pluie_demain_source = self._resolve_precipitation_inputs(
            pluie_24h_sensor=pluie_24h_sensor,
            pluie_demain_sensor=pluie_demain_sensor,
            forecast_summary=forecast_summary,
            # Renseigné par `_suivre_pluie_du_jour()` juste au-dessus, et `None` tant que
            # `capteur_pluie_cumul` n'est pas configuré — l'installation sans compteur garde
            # donc exactement son comportement actuel.
            pluie_cumul_jour=weather_profile.get("pluie_cumul_jour_mm"),
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
        # ⚠️ On conserve la valeur DU CAPTEUR avant tout repli météo : les drapeaux de santé
        # testaient la valeur RÉSOLUE, donc post-repli, et ne pouvaient pratiquement jamais être
        # faux. Mesuré sur 144 h : `temperature_valid` faux 0,08 h et `humidity_valid` 0,08 h,
        # contre 2,19 h pour `pluie_valid` — qui teste bien son capteur — alors que les trois
        # sont alimentés par LA MÊME station. Instant citable : le 29/07/2026 à 17:57:46,
        # `temperature_valid: true` alors que le capteur était indisponible depuis 17:52:53 et
        # que l'ET0 tournait sur le repli météo.
        humidite_capteur = self._validate_sensor_value(
            self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE)), "humidite"
        )
        humidite = humidite_capteur
        if humidite is None:
            humidite = weather_profile.get("weather_humidity")
        humidite_sol = self._get_float_state(self._get_conf(CONF_CAPTEUR_HUMIDITE_SOL))
        _vent_entite = self._get_conf(CONF_CAPTEUR_VENT)
        vent_capteur = self._get_float_state(_vent_entite)
        if vent_capteur is not None:
            # ⚠️ NORMALISÉ UNE FOIS, À LA SOURCE. Tout l'aval (seuils de tonte à 20/40 km/h,
            # ET0 qui reçoit `wind_unit="km/h"`) garde ses hypothèses actuelles, et une unité
            # absente ou inconnue laisse la valeur telle quelle : rien ne change pour une
            # installation existante.
            vent_capteur = round(_wind_speed_to_kmh(vent_capteur, self._get_state_unit(_vent_entite)), 2)
        vent = vent_capteur
        if vent is None:
            vent = weather_profile.get("weather_wind_speed")
        current_dt = self._current_datetime()
        rosee = self._lire_rosee()
        rosee_mesuree = rosee
        # Repli de repli : un point de rosée MESURÉ dans le jardin (0.97.24), prioritaire sur
        # celui de l'entité météo — seulement lu quand « Rosée sur l'herbe » n'est pas branché,
        # juste au-dessus.
        point_de_rosee_capteur = self._validate_sensor_value(
            self._get_float_state(self._get_conf(CONF_CAPTEUR_POINT_DE_ROSEE)), "temperature"
        )
        if rosee is None:
            rosee = self._estimate_rosee(weather_profile, temperature, humidite, point_de_rosee_capteur)
        if rosee_mesuree is not None:
            _wetness_source = "sensor"
            _wetness_observation = rosee_mesuree
        elif (
            (temperature is not None and humidite is not None)
            or point_de_rosee_capteur is not None
            or weather_profile.get("weather_dew_point") is not None
            or weather_profile.get("weather_condition") is not None
        ):
            _wetness_source = "estimated"
            _wetness_observation = rosee if rosee is not None else 0.0
        else:
            _wetness_source = "unavailable"
            _wetness_observation = None
        _fungal_wetness = update_fungal_wetness_state(
            self._runtime_state.get("fungal_wetness"),
            observed_at=current_dt,
            leaf_wetness=_wetness_observation,
            source=_wetness_source,
        )
        self._runtime_state["fungal_wetness"] = _fungal_wetness
        _fungal_wetness_hours = (
            float(_fungal_wetness.get("wet_minutes") or 0.0) / 60.0
            if _fungal_wetness.get("status") != "unknown"
            else 0.0
        )
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
            # Choix explicite (25/06/2026) : arrosages EXTERNES (`zone_session`) totalement
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
        mower_context.update(self._suivre_fiabilite_tondeuse(mower_context))
        mower_context.update(self._suivre_passes_tondeuse(mower_context))
        mower_context.update(self._suivre_recommandation_ignoree(mower_context))
        mower_context.update(self._lire_progression_tonte())
        # Déclarée AVANT `compute_snapshot` : le retard de tonte est alors corrigé dès ce
        # cycle-ci. La placer après repousserait la correction de deux minutes pour rien.
        mower_context.update(self._declarer_tonte_du_jour(mower_context))
        runtime_context = self._build_runtime_context()
        # Réglages de la page « Gazon », relus à chaque cycle depuis les options de l'entrée.
        self.brain.reglages = self._reglages_instance()
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
            risk_context={
                "amortissement": self._runtime_state.get("risque_amortissement"),
                "palier_et0": self._runtime_state.get("stress_palier_et0"),
                "palier_et0_montee": self._runtime_state.get("stress_palier_et0_montee"),
                "semis_meteo_ajustement": self._runtime_state.get("semis_meteo_ajustement"),
                "fungal_wetness_duration_hours": _fungal_wetness_hours,
                "fungal_wetness_source": _fungal_wetness.get("source"),
            },
            runtime_context=runtime_context,
        )
        snapshot.update(runtime_context)
        # ⚠️ LA MÉMOIRE REPART DU CYCLE PRÉCÉDENT, SINON L'AMORTISSEMENT NE SERT À RIEN. Non
        # rangée ici, elle serait vide à chaque cycle : le niveau brut passerait toujours, et
        # les quatorze bascules du 31/08 reviendraient telles quelles.
        _palier_et0 = snapshot.get("stress_palier_et0")
        if isinstance(_palier_et0, int) and not isinstance(_palier_et0, bool):
            self._runtime_state["stress_palier_et0"] = _palier_et0
        _montee_et0 = snapshot.get("stress_palier_et0_montee")
        self._runtime_state["stress_palier_et0_montee"] = (
            _montee_et0 if isinstance(_montee_et0, dict) else None
        )
        _memoire_risque = snapshot.get("risque_amortissement")
        if isinstance(_memoire_risque, dict):
            self._runtime_state["risque_amortissement"] = _memoire_risque
        # ⚠️ MÊME PIÈGE QUE `stress_palier_et0` : sans cette mémoire reportée au cycle
        # suivant, l'ajustement météo des cycles de graines rebasculerait sur le niveau brut
        # à chaque bruit de mesure/prévision (18/09/2026, cf. `_ajustement_meteo_graines`).
        _semis_ajustement = snapshot.get("semis_meteo_ajustement")
        if isinstance(_semis_ajustement, str) and _semis_ajustement:
            self._runtime_state["semis_meteo_ajustement"] = _semis_ajustement
        # LOT A — santé capteurs (calculé ici pour garantir la présence dans coordinator.data)
        snapshot["decision_cycle"] = self._tracer_cycle()
        snapshot["sensor_health"] = self._build_sensor_health(
            temperature_source=temperature_source,
            humidite_capteur=humidite_capteur,
            vent_capteur=vent_capteur,
            etp_capteur=etp_capteur,
            pluie_24h_sensor=pluie_24h_sensor,
            weather_profile=weather_profile,
            eto_hourly=eto_hourly,
            temperature=temperature,
            humidite=humidite,
            vent=vent,
        )
        # LOT E — risque fongique (calculé ici pour garantir la présence dans coordinator.data)
        _fungal = _compute_fungal_risk(
            temperature=temperature,
            humidite=humidite,
            rosee=rosee,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            hour_of_day=current_dt.hour + current_dt.minute / 60.0,
            wetness_duration_hours=_fungal_wetness_hours,
            wetness_source=_fungal_wetness.get("source"),
        )
        snapshot.update(_fungal)
        snapshot["fungal_wetness_status"] = _fungal_wetness.get("status")
        if runtime_context.get("active_irrigation_session") is None:
            await self._finalize_pending_irrigation_user_action(
                execution=runtime_context.get("last_irrigation_execution"),
                persist_only=True,
            )
        await self._async_apply_mower_control(snapshot)
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
        await self._rafraichir_apres_action_utilisateur()

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
        await self._rafraichir_apres_action_utilisateur()

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
        await self._rafraichir_apres_action_utilisateur()

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
        await self._rafraichir_apres_action_utilisateur()

    @property
    def auto_mowing_declaration_enabled(self) -> bool:
        """L'intégration déclare-t-elle elle-même la tonte du jour ?"""
        memory = self.memory
        if isinstance(memory, dict):
            return bool(
                memory.get(
                    "auto_mowing_declaration_enabled",
                    DEFAULT_AUTO_MOWING_DECLARATION_ENABLED,
                )
            )
        return DEFAULT_AUTO_MOWING_DECLARATION_ENABLED

    async def async_set_auto_mowing_declaration_enabled(self, enabled: bool) -> None:
        """Autorise ou coupe l'auto-déclaration de la tonte."""
        self.memory["auto_mowing_declaration_enabled"] = bool(enabled)
        await self._async_save_state()
        await self._rafraichir_apres_action_utilisateur()

    @property
    def auto_mowing_declaration_minutes(self) -> int:
        """Minutes de tonte cumulées à partir desquelles la journée compte comme tondue."""
        memory = self.memory
        if isinstance(memory, dict):
            raw_value = memory.get(
                "auto_mowing_declaration_minutes",
                DEFAULT_AUTO_MOWING_DECLARATION_MINUTES,
            )
            try:
                return max(1, int(float(raw_value)))
            except (TypeError, ValueError):
                return DEFAULT_AUTO_MOWING_DECLARATION_MINUTES
        return DEFAULT_AUTO_MOWING_DECLARATION_MINUTES

    async def async_set_auto_mowing_declaration_minutes(self, minutes: float) -> None:
        """Met à jour le plancher de crédibilité de l'auto-déclaration."""
        try:
            normalized = max(1, int(round(float(minutes))))
        except (TypeError, ValueError):
            normalized = DEFAULT_AUTO_MOWING_DECLARATION_MINUTES
        self.memory["auto_mowing_declaration_minutes"] = normalized
        await self._async_save_state()
        await self._rafraichir_apres_action_utilisateur()

    async def async_set_selected_product(self, product_id: str | None) -> None:
        """Sélectionne le produit d'intervention courant."""
        self.brain.selected_product_id = product_id
        await self._async_save_state()
        await self._rafraichir_apres_action_utilisateur()

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
        return validate_sensor_value(value, sensor_type, _LOGGER)

    def _get_state_unit(self, entity_id: str | None) -> str | None:
        """Unité déclarée par l'entité, ou `None`.

        ⚠️ Home Assistant publie l'unité dans chaque entité — il suffit de la lire au lieu de
        la supposer. Le code supposait des km/h dès qu'un capteur de vent était configuré
        (`"km/h" if vent is not None`), et ne lisait l'unité que sur l'entité météo de repli.
        Un capteur en m/s — le Shelly WS90 par exemple — était donc divisé par 3,6 à tort,
        sous-estimant le vent d'autant dans l'ET0 et rendant les seuils de tonte inatteignables.
        """
        return get_state_unit(getattr(self, "hass", None), entity_id)

    def _get_float_state(self, entity_id: str | None) -> float | None:
        """Retourne l'état float d'une entité Home Assistant."""
        return get_float_state(getattr(self, "hass", None), entity_id, _LOGGER)

    def _get_text_state(self, entity_id: str | None) -> str | None:
        """Retourne l'état textuel d'une entité Home Assistant, ou None si indisponible.

        `unavailable`/`unknown` sont des ABSENCES de mesure, pas des valeurs. Les laisser
        passer avait deux conséquences réelles : le capteur d'erreur de la tondeuse devenu
        indisponible (cas courant à chaque redémarrage) était lu comme un CODE D'ERREUR, et la
        tonte se retrouvait bloquée par un « Robot en erreur » imaginaire ; et l'heure du
        prochain départ s'affichait littéralement « unavailable » dans les attributs publics.
        """
        return get_text_state(getattr(self, "hass", None), entity_id)

    def _get_bool_state(self, entity_id: str | None) -> bool | None:
        """Retourne l'état booléen standardisé d'une entité Home Assistant."""
        return get_bool_state(getattr(self, "hass", None), entity_id)

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
                # ⚠️ INSTRUMENTATION (aucun changement de comportement).
                # « Je n'ai pas pu interroger » et « l'entité n'existe pas » produisaient le
                # MÊME verdict `configured_missing`. C'est la signature de la famille : une
                # incapacité devient une affirmation. Or on a mesuré le 06/08/2026 à 13:41:44
                # un `configured_missing` publié alors que `lawn_mower.esperance_jr` était
                # `docked` SANS un seul changement d'état de 13:40 à 13:47 (requête
                # `significant_changes_only=false`). Le transitoire est donc INTERNE.
                # `resolution_probe` sépare enfin les deux cas — à lire avant de corriger.
                if not callable(get_state):
                    probe = "machine_etats_injoignable"
                    mower_state = None
                else:
                    mower_state = get_state(configured)
                    probe = "entite_absente" if mower_state is None else "ok"
                state_exists = mower_state is not None
                return {
                    "entity_id": configured,
                    "resolution_state": "configured" if state_exists else "configured_missing",
                    "resolution_reason": (
                        "Tondeuse configurée explicitement." if state_exists else "Tondeuse configurée introuvable."
                    ),
                    "resolution_probe": probe,
                    "resolution_candidate_count": len(self._discover_mower_candidates()),
                }

        candidates = self._discover_mower_candidates()
        candidate_count = len(candidates)
        if candidate_count == 1:
            return {
                "entity_id": candidates[0],
                "resolution_state": "fallback_single",
                "resolution_reason": "Tondeuse découverte automatiquement.",
                "resolution_probe": "ok",
                "resolution_candidate_count": candidate_count,
            }
        if candidate_count == 0:
            return {
                "entity_id": None,
                "resolution_state": "missing",
                "resolution_reason": "Aucune tondeuse détectée.",
                "resolution_probe": "aucun_candidat",
                "resolution_candidate_count": 0,
            }
        return {
            "entity_id": None,
            "resolution_state": "ambiguous",
            "resolution_reason": "Plusieurs tondeuses détectées. Configure une tondeuse explicitement.",
            "resolution_probe": "plusieurs_candidats",
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
        resolution_probe = mower_selection.get("resolution_probe")
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
                resolution_probe=resolution_probe,
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
                resolution_probe=resolution_probe,
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
            resolution_probe=resolution_probe,
        )
        return {
            **raw_context,
            # ⚠️ SEUL POINT D'APPEL QUI PORTE `passe_ouverte`, et c'est vérifié : les deux
            # autres sont les chemins dégradés (tondeuse non résolue, entité indisponible) où
            # `tondeuse_connectee` vaut False. `_presence_state` y retourne « inconnue » avant
            # de regarder l'état : l'argument y serait inerte, et le passer quand même
            # laisserait croire à une couverture qui n'existe pas.
            **build_mower_coordination_context(
                raw_context,
                enabled=self.mower_coordination_enabled,
                passe_ouverte=self._passe_tondeuse_ouverte(),
                dock_signal_vu=self._dock_signal_tondeuse_vu(),
            ),
        }

    def _suivi_des_graines(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        """Où en sont les cycles des graines aujourd'hui (tout à `None` hors semis)."""
        semis_progress = self._semis_cycle_progress(snapshot)
        return {
            "semis_followup_state": semis_progress.get("state") if semis_progress else None,
            "semis_followup_due_at": self._serialize_runtime_value(
                semis_progress.get("next_due_at") if semis_progress else None
            ),
            "semis_followup_due_display": semis_progress.get("next_due_display") if semis_progress else None,
            "semis_cycles_completed_today": semis_progress.get("cycles_completed_today") if semis_progress else None,
            "semis_cycles_remaining_today": semis_progress.get("cycles_remaining_today") if semis_progress else None,
            "semis_daily_cycles_target": semis_progress.get("daily_cycles_target") if semis_progress else None,
            "semis_weather_cycles_target": semis_progress.get("weather_cycles_target") if semis_progress else None,
            "semis_cycles_limited_by_window": semis_progress.get("window_limited_cycles") if semis_progress else None,
            "semis_cycles_limit_reason": semis_progress.get("window_limit_reason") if semis_progress else None,
            "semis_cycle_spacing_minutes": semis_progress.get("cycle_spacing_minutes") if semis_progress else None,
            "semis_last_cycle_at": self._serialize_runtime_value(
                semis_progress.get("last_cycle_at") if semis_progress else None
            ),
            "semis_last_cycle_display": semis_progress.get("last_cycle_display") if semis_progress else None,
        }

    def _build_runtime_context(self) -> dict[str, Any]:
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
            **self._suivi_des_graines(),
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
        reglages = self._reglages_instance()
        stage_name, stage_program = resolve_semis_stage_program(
            watering_stage,
            transition_ready=transition_ready,
            reglages=reglages,
        )
        # La valeur du snapshot peut provenir d'une ancienne version ou d'un réglage
        # incomplet. L'exécuteur reste la dernière barrière : jamais moins que le minimum
        # agronomique du stade (120 min en germination).
        cycle_spacing_minutes = max(
            cycle_spacing_minutes,
            stage_program.cycle_spacing_minutes_min,
        )
        cycle_slots_minutes = list(
            repartir_creneaux_semis(
                stage_program,
                daily_cycles_target,
                reglages=reglages,
            )
        )
        if len(cycle_slots_minutes) < daily_cycles_target:
            fallback_spacing = cycle_spacing_minutes
            while len(cycle_slots_minutes) < daily_cycles_target:
                if not cycle_slots_minutes:
                    cycle_slots_minutes.append(stage_program.cycle_slots_minutes[0])
                else:
                    cycle_slots_minutes.append(cycle_slots_minutes[-1] + fallback_spacing)

        weather_cycles_target = daily_cycles_target
        cycles_completed_today = len(self._semis_cycle_history_items())
        now = self._current_datetime()
        window_end = snapshot.get("watering_window_acceptable_end_minute")
        effective_end: float | None = None
        if window_end is not None:
            try:
                effective_end = float(window_end)
            except (TypeError, ValueError):
                pass
            if effective_end is not None:
                daily_cycles_target = min(
                    daily_cycles_target,
                    sum(slot < effective_end for slot in cycle_slots_minutes),
                )
        try:
            closing_minutes = float(reglages.get("graines_fenetre_fin", 17 * 60))
        except (TypeError, ValueError):
            closing_minutes = None
        window_limit_reason = None
        if daily_cycles_target < weather_cycles_target:
            window_limit_reason = (
                "weather"
                if closing_minutes is None or (effective_end is not None and effective_end < closing_minutes)
                else "schedule"
            )
        if closing_minutes is not None and now.hour * 60 + now.minute >= closing_minutes:
            daily_cycles_target = min(daily_cycles_target, cycles_completed_today)
            if daily_cycles_target < weather_cycles_target:
                window_limit_reason = "closed"

        cycles_remaining_today = max(0, daily_cycles_target - cycles_completed_today)
        last_cycle_at: datetime | None = None
        history_items = self._semis_cycle_history_items()
        if history_items:
            last_item = history_items[-1]
            cycle_started_at = (
                last_item.get("started_at")
                or last_item.get("recorded_at")
                or last_item.get("detected_at")
                or last_item.get("date")
            )
            last_cycle_at = self._parse_datetime_value(cycle_started_at)

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
        else:
            # Le programme du jour est fini, mais le prochain arrosage n'est pas inconnu :
            # c'est le premier créneau du lendemain, selon les réglages actuels. On conserve
            # aussi la barrière entre deux départs si un cycle exceptionnel s'est terminé tard.
            first_slot = cycle_slots_minutes[0]
            next_due_at = (now + timedelta(days=1)).replace(
                hour=first_slot // 60,
                minute=first_slot % 60,
                second=0,
                microsecond=0,
            )
            if last_cycle_at is not None:
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
            "weather_cycles_target": weather_cycles_target,
            "window_limited_cycles": daily_cycles_target < weather_cycles_target,
            "window_limit_reason": window_limit_reason,
            "cycle_spacing_minutes": cycle_spacing_minutes,
            "last_cycle_at": last_cycle_at,
            "last_cycle_display": self._local_datetime_text(last_cycle_at) if last_cycle_at is not None else None,
            "surface_cycle_mm": round(surface_cycle_mm, 1),
            "watering_strategy": strategy,
            "objective_scope": objective_scope,
            "watering_stage": stage_name,
            "cycle_slots_minutes": tuple(cycle_slots_minutes),
            "semis_meteo_ajustement": snapshot.get("semis_meteo_ajustement"),
        }

    def _get_float_conf(self, key: str, default: float | None = None) -> float | None:
        """Retourne une valeur de configuration numérique normalisée."""
        return _float_conf_value(self._get_conf(key), key=key, default=default, logger=_LOGGER)

    def _get_weather_profile(self, weather_entity_id: str | None) -> dict[str, Any]:
        """Retourne les principaux attributs météo disponibles pour l'entité fournie."""
        if not weather_entity_id:
            return {}

        state = self.hass.states.get(weather_entity_id)
        if state is None:
            return {}

        # ⚠️ `state.state` EN PLUS des attributs : chez Home Assistant la condition météo est
        # l'ÉTAT de l'entité `weather.*`, jamais un attribut. Ne transmettre que les attributs
        # rendait `weather_condition` systématiquement nul, et avec lui tout le garde
        # « il pleut en ce moment » — arrosage comme tonte. Voir `extract_weather_profile`.
        return WeatherAdapter.profile_from_attributes(state.attributes, condition=state.state)

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
        """Minute locale (depuis minuit) du coucher du soleil DU JOUR, ou None.

        Pas le « prochain » : une fois le soleil couché, `next_setting` désigne le lendemain, lu à
        l'heure du lendemain, faux d'une heure la veille d'un changement d'heure (cf.
        `sunset_today_minute_from_context`). Le lever, lui, reste le prochain : c'est celui du
        départ d'arrosage à venir.
        """
        return sunset_today_minute_from_context(sun_context, dt_util, self._current_date())

    def _sunrise_minute_from_context(self, sun_context: dict[str, Any]) -> int | None:
        """Minute locale (depuis minuit) du prochain lever du soleil, ou None."""
        return self._sun_event_minute_from_context(sun_context, "sun_next_rising")

    def _sun_event_minute_from_context(self, sun_context: dict[str, Any], key: str) -> int | None:
        return sun_event_minute_from_context(sun_context, key, dt_util)

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
        # Fenêtre civile large : volontairement grossière, elle n'a qu'à tenir le temps que
        # `sun.sun` apparaisse. Toute valeur horaire vaut mieux qu'un « journée finie » à 3 h.
        return et_elapsed_fraction(
            now=self._current_datetime(),
            sunrise_minute=self._sunrise_minute_from_context(sun_context),
            sunset_minute=self._sunset_minute_from_context(sun_context),
            fallback_day_start_minute=_FALLBACK_DAY_START_MINUTE,
            fallback_day_end_minute=_FALLBACK_DAY_END_MINUTE,
        )

    def _lire_rosee(self) -> float | None:
        """La rosée sur l'herbe mesurée, ou `None` pour l'estimer.

        ⚠️ UN POINT DE ROSÉE EST IGNORÉ (0.96.0). Le moteur lit « au-dessus de 0 = herbe mouillée »
        (blocage de tonte, ressuyage, risque de maladies) : une température de 11 °C y dirait
        « mouillée » pour toujours. Le 17/09/2026, le point de rosée de la station a été branché
        par « Configurer » ; la page le refusait déjà. Signalé une fois par entité dans le journal.
        """
        entity_id = self._get_conf(CONF_CAPTEUR_ROSEE)
        if not isinstance(entity_id, str) or not entity_id:
            return None
        hass = getattr(self, "hass", None)
        etat = hass.states.get(entity_id) if hass is not None else None
        attributs = getattr(etat, "attributes", None) or {}
        if sources_meteo.interdit(
            sources_meteo.PAR_CLE[CONF_CAPTEUR_ROSEE],
            unite=attributs.get("unit_of_measurement"),
            classe=attributs.get("device_class"),
        ):
            signalees = self._rosees_ignorees
            if signalees is None:
                signalees = self._rosees_ignorees = set()
            if entity_id not in signalees:
                signalees.add(entity_id)
                _LOGGER.warning(
                    "« Rosée sur l'herbe » : %s donne une température (un point de rosée), pas une "
                    "humidité du feuillage. Ignoré : la rosée est estimée. À retirer sur la page "
                    "« Gazon » (Réglages → Installation → Entrées de l'intégration → Rosée sur l'herbe "
                    "→ Changer → Aucune).",
                    entity_id,
                )
            return None
        return self._get_float_state(entity_id)

    def _estimate_rosee(
        self,
        weather_profile: dict[str, Any],
        temperature: float | None,
        humidite: float | None,
        point_de_rosee: float | None = None,
    ) -> float | None:
        return estimate_rosee(weather_profile, temperature, humidite, point_de_rosee)

    def _minutes_creditables(self, precedent_iso: Any, maintenant: datetime) -> float:
        """Minutes à créditer entre deux échantillons — 0.0 si le trou est trop grand.

        ⚠️ Au-delà du plafond, l'écart n'est PAS une durée : c'est un arrêt de Home Assistant.
        Créditer un trou de quatre heures comme du temps de tonte transformerait un
        redémarrage en journée de travail. Le plafond est partagé par le cumul de fiabilité
        et par le carnet de passes : deux implémentations de la même règle finiraient par
        diverger, et l'une des deux mentirait sans qu'on sache laquelle.
        """
        return runtime_minutes_creditables(
            precedent_iso,
            maintenant,
            parser=self._parse_datetime_value,
            max_minutes=_ECHANTILLON_MAX_MINUTES,
        )

    def _lire_progression_tonte(self) -> dict[str, Any]:
        """Où en est le TRAVAIL en cours, d'après la tondeuse elle-même.

        ⚠️ ELLE PILOTE L'ÉCRITURE DE LA TONTE DEPUIS LA 0.61.0. Ce bloc a longtemps porté
        « observation seule — rien n'est branché sur une décision », vrai le jour où il a été
        écrit et faux dès la 0.61.0 — puis resté en place huit versions de plus.
        `mower_job_progress_pct` et `mower_job_id` alimentent `_suivre_travail_tondeuse`, donc
        la détection du PASSAGE à 100 % — la garde qui décide si une tonte s'inscrit dans
        l'historique. Un commentaire périmé est pire qu'une absence de commentaire : il autorise
        à toucher au code en croyant qu'il ne décide de rien. (Corrigé le 09/09/2026, en même
        temps que le mensonge jumeau de `_suivre_pluie_du_jour`.)

        Le carnet compte des PASSES ; il n'a jamais su ce qu'est un TRAVAIL. Cette entité le
        dit : une progression 0 → 100 % et un `task_id` stable qui survit à la recharge, donc
        qui recolle deux passes séparées par une charge en un seul travail.

        Mesuré le 25/08/2026 : 13:20:38 progression → 0 (nouvelle tâche), montée régulière,
        17:24:11 → 100, au garage à 17:26:51.

        ⚠️ LES DEUX INCONNUES D'ALORS, ET CE QU'ELLES SONT DEVENUES :
          · `task_status` vaut 2 — on ignore toujours son vocabulaire, donc on le publie BRUT
            et **aucune décision ne s'y appuie** ;
          · « une COUPE DE BORDURE monte-t-elle aussi à 100 ? » — **oui**, mesuré le 02/09/2026.
            « progression = 100 » veut donc bien dire « une tâche s'est terminée », jamais « le
            gazon est tondu ». C'est de là que vient le plancher de minutes, et c'est pour la
            même raison que la 0.82.0 cumule les travaux terminés de la journée plutôt que de
            faire confiance à une complétion isolée.

        ⚠️ Le suffixe de l'entité dépend de la langue de l'intégration tondeuse. Absente,
        la réponse est `None` partout — une absence, jamais un zéro.
        """
        vide: dict[str, Any] = {
            "mower_job_progress_pct": None,
            "mower_job_id": None,
            "mower_job_status_raw": None,
        }
        try:
            selection = self._resolve_mower_selection()
            entity_id = derive_related_entity_id(
                selection.get("entity_id"), "sensor", "progression_de_la_tonte"
            )
            if not entity_id:
                return vide
            states = getattr(getattr(self, "hass", None), "states", None)
            get_state = getattr(states, "get", None)
            etat = get_state(entity_id) if callable(get_state) else None
            if etat is None:
                return vide
            attrs = getattr(etat, "attributes", None) or {}
            tache = attrs.get("task_id")
            statut = attrs.get("task_status")
            return {
                "mower_job_progress_pct": _to_float_or_none(getattr(etat, "state", None)),
                "mower_job_id": str(tache) if tache not in (None, "") else None,
                "mower_job_status_raw": statut if statut is not None else None,
            }
        except Exception:  # noqa: BLE001 — une observation ne fait jamais tomber le cycle
            _LOGGER.debug("Progression de la tonte indisponible", exc_info=True)
            return vide

    def _suivre_recommandation_ignoree(self, mower_context: dict[str, Any]) -> dict[str, Any]:
        """Depuis combien de temps la tonte est recommandée sans que rien ne parte.

        ⚠️ Lit `action_possible` du cycle PRÉCÉDENT : ce hook tourne avant `compute_snapshot`,
        donc la décision du cycle courant n'existe pas encore. Même motif que le carnet.

        ⚠️ Muet quand la coordination est coupée : l'utilisateur a alors choisi de piloter à la
        main, et personne n'est censé écouter. Crier au silence serait crier sur une décision.
        """
        vide: dict[str, Any] = {
            "mower_recommendation_ignored_minutes": None,
            "mower_recommendation_ignored": None,
        }
        try:
            if not bool(mower_context.get("mower_coordination_enabled")):
                self._runtime_state.pop("mower_recommendation_ignored_since", None)
                return vide

            recommandee = self._booleen_publie_au_cycle_precedent("action_possible")
            au_garage = bool(mower_context.get("mower_is_docked"))
            # Elle est sortie, ou plus rien n'est recommandé : quelqu'un a écouté (ou il n'y
            # avait rien à écouter). Dans les deux cas le compteur repart de zéro.
            if recommandee is not True or not au_garage:
                self._runtime_state.pop("mower_recommendation_ignored_since", None)
                return {**vide, "mower_recommendation_ignored": False} if recommandee is not None else vide

            maintenant = self._current_datetime()
            depuis = self._parse_datetime_value(
                self._runtime_state.get("mower_recommendation_ignored_since")
            )
            if depuis is None:
                self._runtime_state["mower_recommendation_ignored_since"] = maintenant.isoformat()
                return {**vide, "mower_recommendation_ignored_minutes": 0.0,
                        "mower_recommendation_ignored": False}

            ecoule = (maintenant - depuis).total_seconds() / 60.0
            if ecoule < 0.0:
                return vide
            return {
                "mower_recommendation_ignored_minutes": round(ecoule, 1),
                "mower_recommendation_ignored": ecoule >= _RECOMMANDATION_IGNOREE_MINUTES,
            }
        except Exception:  # noqa: BLE001 — un compteur d'observation ne fait pas tomber le cycle
            _LOGGER.debug("Suivi de la recommandation ignorée indisponible", exc_info=True)
            return vide

    def _cumuler_lame_glissante(
        self, suivi: dict[str, Any], gain: float, maintenant: datetime
    ) -> float:
        """Lame d'eau tombée dans les dernières heures. Source unique des DEUX pluviomètres.

        ⚠️ ON N'EFFACE JAMAIS, ON LAISSE VIEILLIR. C'est toute la différence avec l'« épisode »
        du premier jet, qui remettait le compteur à zéro dès qu'une hausse arrivait après un
        trou : un auget de traîne annulait alors le ressuyage de l'averse précédente. Ici une
        hausse ne peut qu'AJOUTER ; ce qui sort de la fenêtre part de lui-même.

        ⚠️ APPELÉ MÊME SANS LECTURE FRAÎCHE (`gain = 0`). Un pluviomètre `unavailable` ne doit
        pas faire disparaître la pluie qu'il a mesurée dix minutes plus tôt — c'est le second
        défaut qu'a trouvé la revue : la lame de la station s'évanouissait pendant ses coupures,
        et le maximum des deux retombait alors sur le seul voisin. Le vieillissement est une
        affaire d'horloge, pas de lecture.

        ⚠️ Rend toujours un nombre, jamais `None` : quand le suivi existe, « rien dans la
        fenêtre » est une MESURE (0 mm), pas une absence. L'absence, c'est l'appelant qui la
        signale en ne nous appelant pas.
        """
        historique = suivi.get("lame_gains")
        if not isinstance(historique, list):
            historique = []
        if gain > 0.0:
            historique = [*historique, [maintenant.isoformat(), round(float(gain), 3)]]

        # On ne garde que des entrées lisibles et non datées du futur (horloge qui recule).
        propres: list[tuple[Any, Any, float]] = []
        for entree in historique:
            if not isinstance(entree, (list, tuple)) or len(entree) != 2:
                continue
            instant = self._parse_datetime_value(entree[0])
            valeur = _to_float_or_none(entree[1])
            if instant is None or valeur is None or valeur <= 0.0 or instant > maintenant:
                continue
            propres.append((instant, entree[0], valeur))
        propres.sort(key=lambda e: e[0])

        if not propres:
            suivi["lame_gains"] = []
            return 0.0

        # ⚠️ LA FENÊTRE SE MESURE DEPUIS LA DERNIÈRE GOUTTE, PAS DEPUIS CHAQUE GOUTTE — relevé
        # par la revue Codex sur la PR #49, et c'est un vrai trou. Le ressuyage court à partir
        # de la dernière hausse ; une averse qui DURE voyait donc son début sortir de la fenêtre
        # pendant que le délai tournait encore. Exemple donné : 4 mm entre 12:00 et 14:00 → à
        # 16:00 la première moitié de l'averse a expiré, la lame retombe à ~2 mm, le délai
        # calculé passe de 180 à ~107 min — déjà écoulés — et la tonte repart une heure trop tôt.
        # La lame MAIGRISSAIT pendant le délai qu'elle avait elle-même armé.
        #
        # On remonte donc le temps depuis la dernière hausse et on s'arrête au premier TROU plus
        # long que la fenêtre : c'est l'averse en cours, prise entière, quelle que soit sa durée.
        # Une averse de six heures reste un seul événement.
        if (maintenant - propres[-1][0]) > timedelta(minutes=_PLUIE_LAME_FENETRE_MINUTES):
            # Rien depuis une fenêtre entière : le couvert a séché, l'averse est close.
            suivi["lame_gains"] = []
            return 0.0

        fenetre = timedelta(minutes=_PLUIE_LAME_FENETRE_MINUTES)
        evenement: list[tuple[Any, Any, float]] = [propres[-1]]
        for precedent in reversed(propres[:-1]):
            if evenement[-1][0] - precedent[0] > fenetre:
                break  # un trou plus long que la fenêtre : l'averse d'avant est une autre
            evenement.append(precedent)

        evenement.reverse()
        suivi["lame_gains"] = [[e[1], e[2]] for e in evenement][-_PLUIE_LAME_MAX_ENTREES:]
        return round(sum(e[2] for e in evenement), 2)

    def _suivre_pluie_du_jour(self) -> dict[str, Any]:
        """Total de pluie du jour, dérivé d'un compteur CUMULATIF qui ne se réinitialise pas.

        ⚠️ ELLE ALIMENTE LE BILAN SOL DEPUIS LA 0.79.0. Ce bloc a porté d'une version à
        l'autre un avertissement « observation seule, n'alimente aucune décision » devenu
        FAUX le jour même où la 0.79.0 l'a branchée : `_resolve_precipitation_inputs` la prend désormais en priorité sur
        `capteur_pluie_24h` (source `capteur_cumul_station`). Un commentaire périmé est pire
        qu'une absence de commentaire — il autorise à toucher au code en croyant qu'il ne
        décide de rien. Vérifié le 09/09/2026 sur la vraie station : nuit du 08→09,
        compteur 2,1 → 2,3, cumul du jour 0,2 mm, réserve 10,8 → 11,0. Le crédit vient d'ici.

        ⚠️ ON NE COMPTE QUE LE DÉPASSEMENT DU MAXIMUM DÉJÀ VU. Le compteur du WS90 chute
        parfois à 0 puis revient à sa valeur : un simple `delta` compterait la remontée comme
        de la pluie — 250 mm d'un coup. Le maximum, lui, ne redescend jamais.

        ⚠️ LES DEUX MÉMOIRES SONT PERSISTÉES. Sans elles, un redémarrage ferait repartir le
        maximum de la lecture courante : la première vraie hausse serait perdue, et surtout
        une chute parasite suivie d'un redémarrage recompterait tout le compteur.
        """
        vide: dict[str, Any] = {
            "pluie_cumul_jour_mm": None,
            "pluie_cumul_pic_mm": None,
            "pluie_gain_rejete_mm": None,
            "pluie_cumul_lame_mm": None,
        }
        try:
            _suivi_lame = self._runtime_state.get("pluie_cumul")
            lecture = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_CUMUL))
            if lecture is None:
                # ⚠️ PAS DE LECTURE ≠ PAS DE PLUIE. La station tombe en `unavailable` par
                # à-coups (16 min autour du basculement du 09/09) ; sa lame doit continuer de
                # vieillir toute seule, sinon le ressuyage qu'elle a armé s'évanouit avec elle.
                if isinstance(_suivi_lame, dict):
                    _lame = self._cumuler_lame_glissante(
                        _suivi_lame, 0.0, self._current_datetime()
                    )
                    self._runtime_state["pluie_cumul"] = _suivi_lame
                    return {**vide, "pluie_cumul_lame_mm": _lame}
                return vide

            suivi = self._runtime_state.get("pluie_cumul")
            if not isinstance(suivi, dict):
                suivi = {}
            aujourd_hui = self._current_date().isoformat()
            if suivi.get("date") != aujourd_hui:
                suivi["date"] = aujourd_hui
                suivi["total_jour"] = 0.0   # ⚠️ NOTRE minuit, pas celui du capteur.
            _changer_de_reference(suivi, self._get_conf(CONF_CAPTEUR_PLUIE_CUMUL), lecture)

            pic = _to_float_or_none(suivi.get("pic"))
            # ⚠️ AUCUNE RÉFÉRENCE = AUCUN TOTAL, PAS UN TOTAL DE ZÉRO. Relevé par la revue
            # Codex sur la PR #49. Au tout premier cycle — installation neuve, ou état
            # d'exécution persisté perdu — le compteur s'initialise sur la lecture courante et
            # le total du jour vaut 0. Or `_resolve_precipitation_inputs` lui donne la PRIORITÉ
            # sur `capteur_pluie_24h` depuis la 0.79.0 : un zéro sans référence écrasait donc
            # un capteur qui, lui, savait qu'il était tombé 10 mm ce matin. Le bilan du sol
            # perdait la pluie de la journée entière et pouvait lancer un arrosage inutile.
            # `None` laisse le capteur 24 h reprendre la main ; dès le cycle suivant la
            # référence existe et le total dérivé redevient légitime, y compris à zéro.
            _sans_reference = pic is None
            rejete = _to_float_or_none(suivi.get("gain_rejete")) or 0.0
            _lame_retenue = 0.0
            if pic is not None:
                gain = lecture - pic
                if gain > 0.0:
                    if gain <= _PLUIE_GAIN_MAX_PAR_PAS_MM:
                        suivi["total_jour"] = round(float(suivi.get("total_jour") or 0.0) + gain, 2)
                        # ⚠️ C'est CETTE station qui est sur la pelouse : quand elle voit une
                        # averse que le voisin sous-estime, c'est elle qui doit fixer la durée
                        # du ressuyage. Un gain ABERRANT (branche `else`) n'y entre pas plus
                        # que dans le total : sinon une trame corrompue armerait le maximum.
                        _lame_retenue = gain
                    else:
                        # Saut impossible en deux minutes : on ne le compte pas, mais on le
                        # GARDE en trace. Un rejet silencieux serait indiscernable d'une panne.
                        rejete = round(rejete + gain, 2)
            suivi["pic"] = lecture if pic is None else max(pic, lecture)
            suivi["gain_rejete"] = rejete
            lame = self._cumuler_lame_glissante(suivi, _lame_retenue, self._current_datetime())
            self._runtime_state["pluie_cumul"] = suivi

            return {
                "pluie_cumul_jour_mm": (
                    None if _sans_reference else round(float(suivi.get("total_jour") or 0.0), 2)
                ),
                "pluie_cumul_pic_mm": suivi["pic"],
                "pluie_gain_rejete_mm": rejete,
                "pluie_cumul_lame_mm": lame,
            }
        except Exception:  # noqa: BLE001 — une observation ne fait jamais tomber le cycle
            _LOGGER.debug("Total de pluie du jour indisponible", exc_info=True)
            return vide

    def _lire_pluie_actuelle(self) -> dict[str, Any]:
        """Pleut-il MAINTENANT, dit directement par un capteur — sans rien déduire.

        ⚠️ OBSERVATION SEULE POUR L'INSTANT. Publiée à côté de `pluie_mesuree_active` pour
        qu'on puisse comparer les deux sur plusieurs averses avant de faire dépendre une
        décision de celle-ci. C'est la méthode qui a évité deux erreurs sur la garde pluie.

        ⚠️ POURQUOI ELLE EXISTE. Tout l'appareillage actuel — détecteur de hausse, cliquet,
        horodatage sur la dernière hausse — approxime « pleut-il ? » à partir d'un CUMUL
        journalier, faute de mieux. Un cumul ne le dit pas : 3,6 mm y restent affichés toute
        la journée après l'averse. De là viennent la fausse averse du 16/08 (bruit lu comme
        une hausse) et celle du 29/08 (remise à zéro mal détectée sous 1 mm).
        Or la station expose depuis toujours une pluie INSTANTANÉE, qui répond sans calcul.

        ⚠️ `None` reste une absence. Capteur non configuré, injoignable ou illisible : on ne
        conclut rien, surtout pas « il ne pleut pas ».
        """
        vide: dict[str, Any] = {"pluie_actuelle_mm": None, "pluie_actuelle_active": None}
        try:
            valeur = self._get_float_state(self._get_conf(CONF_CAPTEUR_PLUIE_ACTUELLE))
            if valeur is None:
                return vide
            return {"pluie_actuelle_mm": valeur, "pluie_actuelle_active": valeur > 0.0}
        except Exception:  # noqa: BLE001 — une observation ne fait jamais tomber le cycle
            _LOGGER.debug("Pluie instantanée indisponible", exc_info=True)
            return vide

    def _suivre_pluie_mesuree(self, cumul_mm: float | None) -> dict[str, Any]:
        """Dit s'il pleut EN CE MOMENT, d'après le pluviomètre et non d'après la prévision.

        ⚠️ On reçoit un CUMUL, pas une intensité : 3,2 mm restent affichés toute la journée
        après l'averse. C'est la HAUSSE qui signe une pluie en cours, jamais la valeur.

        ⚠️ Une BAISSE n'est pas une pluie négative : c'est la remise à zéro du capteur, et elle
        est fréquente ici — mesurée 10 fois le 04/08/2026 en une seule journée. On se recale
        alors sur la nouvelle valeur SANS horodater, et l'averse précédente garde sa fraîcheur.

        ⚠️ Sans capteur, sans lecture, ou au tout premier cycle, la réponse est `None` et non
        `False` : « je ne sais pas » ne doit pas se transformer en « il ne pleut pas », sans
        quoi on aurait remplacé un aveuglement par un autre.
        """
        vide: dict[str, Any] = {
            "pluie_mesuree_active": None,
            "pluie_mesuree_cumul_mm": None,
            "pluie_mesuree_minutes_depuis_hausse": None,
            "pluie_mesuree_lame_mm": None,
        }
        try:
            maintenant = self._current_datetime()
            suivi = self._runtime_state.get("pluie_mesuree")
            if not isinstance(suivi, dict):
                suivi = {}

            cumul = _to_float_or_none(cumul_mm)
            if cumul is None:
                # ⚠️ PAS DE LECTURE ≠ PAS DE PLUIE, ici comme pour la station. Sans cette
                # branche la lame du voisin s'évanouissait à la première coupure, et le
                # maximum des deux retombait sur la seule station — le défaut symétrique de
                # celui qu'a trouvé la revue. Le vieillissement est une affaire d'horloge.
                _lame_orpheline = self._cumuler_lame_glissante(suivi, 0.0, maintenant)
                self._runtime_state["pluie_mesuree"] = suivi
                return {**vide, "pluie_mesuree_lame_mm": _lame_orpheline}
            _changer_de_reference(suivi, self._get_conf(CONF_CAPTEUR_PLUIE_24H), cumul)

            precedent = _to_float_or_none(suivi.get("pic"))
            derniere_hausse = suivi.get("derniere_hausse")

            # ⚠️ COMPARER AU PIC DU JOUR, PAS À LA LECTURE PRÉCÉDENTE. Ce capteur oscille
            # toute la journée, et une remontée après un décrochage n'est PAS une averse.
            # Mesuré le 16/08/2026, journée sans une goutte après 05:52 :
            #     05:52 3,6 · 06:22 3,5 · 08:33 4,2 · 09:32 3,7 · 10:32 3,6 · 11:26 3,5
            #     12:20 3,3 · 12:26 3,1 · 12:38 3,3 · 13:07 3,4 · 13:19 3,3 · 13:25 3,2 · 14:25 3,6
            # Comparer à la lecture précédente criait « il pleut » QUATRE fois (08:33, 12:38,
            # 13:07, 14:25). Seul un dépassement du maximum du jour est une pluie nouvelle —
            # c'est le cliquet déjà arbitré pour le bilan sol, réutilisé et non réécrit.
            # Le troisième retour (remise à zéro) n'est pas testé ici, volontairement : une
            # remise à zéro fait TOMBER le pic, donc l'écart est négatif et le seuil ne peut
            # pas être franchi. Le banc de mutation l'a prouvé — la garde `not remise_a_zero`
            # écrite d'abord était morte, aucune mutation ne pouvait la tuer.
            retenue, pic, _ = appliquer_cliquet_pluie(cumul, precedent)

            # ⚠️ LA LAME D'EAU RÉCENTE, à côté du « il pleut ». On additionne TOUTE hausse
            # positive, sans le seuil de 0,05 mm : celui-ci filtre le bruit flottant pour dire
            # « il pleut », il n'a rien à faire dans une somme. Le cliquet a déjà écarté les
            # baisses, donc chaque hausse retenue est de la pluie réelle.
            gain = (pic - precedent) if precedent is not None else 0.0
            _lame_mm = self._cumuler_lame_glissante(suivi, gain, maintenant)

            if precedent is not None and pic - precedent >= _PLUIE_MESUREE_HAUSSE_MIN_MM:
                derniere_hausse = maintenant.isoformat()

            suivi["pic"] = pic
            suivi["derniere_hausse"] = derniere_hausse
            self._runtime_state["pluie_mesuree"] = suivi

            if precedent is None:
                # Première lecture : aucune comparaison possible, donc aucune conclusion —
                # sauf la lame, qui vit dans la fenêtre glissante et peut venir d'avant le
                # redémarrage.
                return {**vide, "pluie_mesuree_cumul_mm": retenue, "pluie_mesuree_lame_mm": _lame_mm}

            depuis = None
            horodatage = self._parse_datetime_value(derniere_hausse)
            if horodatage is not None:
                ecoule = (maintenant - horodatage).total_seconds() / 60.0
                if ecoule >= 0.0:
                    depuis = round(ecoule, 1)

            return {
                "pluie_mesuree_active": depuis is not None and depuis <= _PLUIE_MESUREE_FENETRE_MINUTES,
                "pluie_mesuree_cumul_mm": retenue,
                "pluie_mesuree_minutes_depuis_hausse": depuis,
                "pluie_mesuree_lame_mm": _lame_mm,
            }
        except Exception:  # noqa: BLE001 — un suivi d'observation ne fait jamais tomber le cycle
            _LOGGER.debug("Suivi de la pluie mesurée indisponible", exc_info=True)
            return vide

    def _suivre_fiabilite_tondeuse(self, mower_context: dict[str, Any]) -> dict[str, Any]:
        """Cumule le temps bloqué et le temps tondu de la journée, et en tire un état.

        ⚠️ L'intégration voyait chaque erreur passer sans en garder aucune trace : impossible
        de savoir, sans rejouer l'historique à la main, que le robot passait plus de temps
        coincé qu'à tondre. Mesuré du 02 au 05/08/2026 :

            jour     tondu     bloqué   épisodes
            02/08    130 min   123 min      3
            03/08    174 min   318 min      2      ← bloquée ~2× plus qu'elle ne tond
            04/08    286 min   321 min      6
            05/08    302 min    53 min      3

        contre **zéro blocage** les 26, 28 et 30/07. Ce n'est pas de l'usure, c'est un
        changement — et il faut pouvoir le voir sans requête d'historique.

        ⚠️ RÈGLE DE LA MAISON : une absence de mesure n'est PAS « pas de blocage ». Quand la
        tondeuse est injoignable, on avance l'horloge sans rien créditer — sinon une panne de
        liaison se lirait comme une journée parfaite.
        """
        vide = {
            "mower_blocked_minutes_today": None,
            "mower_mowing_minutes_today": None,
            "mower_block_count_today": None,
            "mower_reliability_today": None,
        }
        try:
            maintenant = self._current_datetime()
            aujourd_hui = self._current_date().isoformat()
            etat = self._runtime_state.get("mower_health")
            if not isinstance(etat, dict) or etat.get("date") != aujourd_hui:
                etat = {
                    "date": aujourd_hui, "blocked_minutes": 0.0, "mowing_minutes": 0.0,
                    "block_count": 0, "last_seen_at": None, "last_kind": None,
                }

            connectee = mower_context.get("tondeuse_connectee") is True
            erreur = str(mower_context.get("tondeuse_erreur") or "").strip().lower()
            en_erreur = connectee and bool(erreur) and erreur not in _NO_ERROR_CODES
            en_tonte = connectee and bool(mower_context.get("mower_is_mowing"))
            genre = "bloquee" if en_erreur else ("tonte" if en_tonte else ("repos" if connectee else None))

            if etat.get("last_kind") in {"bloquee", "tonte"}:
                ecoule = self._minutes_creditables(etat.get("last_seen_at"), maintenant)
                if ecoule > 0.0:
                    cle = "blocked_minutes" if etat["last_kind"] == "bloquee" else "mowing_minutes"
                    etat[cle] = round(float(etat.get(cle) or 0.0) + ecoule, 2)

            if genre == "bloquee" and etat.get("last_kind") != "bloquee":
                etat["block_count"] = int(etat.get("block_count") or 0) + 1

            etat["last_seen_at"] = maintenant.isoformat()
            etat["last_kind"] = genre
            self._runtime_state["mower_health"] = etat

            bloque = float(etat.get("blocked_minutes") or 0.0)
            tondu = float(etat.get("mowing_minutes") or 0.0)
            episodes = int(etat.get("block_count") or 0)
            if bloque <= 0.0 and episodes == 0:
                fiabilite = "normale"
            elif tondu > 0.0 and bloque >= tondu:
                fiabilite = "critique"
            elif episodes >= 3 or (tondu > 0.0 and bloque >= 0.2 * tondu):
                fiabilite = "degradee"
            else:
                fiabilite = "normale"

            return {
                "mower_blocked_minutes_today": round(bloque, 1),
                "mower_mowing_minutes_today": round(tondu, 1),
                "mower_block_count_today": episodes,
                "mower_reliability_today": fiabilite,
            }
        except Exception:  # noqa: BLE001 - un compteur ne doit jamais casser un cycle
            return vide

    def _passe_tondeuse_ouverte(self) -> bool:
        """Une passe est-elle en cours ? C'est la mémoire de « sortie et pas revenue ».

        ⚠️ Lue par la coordination pour que `idle` ne soit plus pris pour une rentrée. Le carnet
        est écrit APRÈS la coordination dans le cycle : on lit donc l'état du cycle PRÉCÉDENT,
        ce qui est exactement ce qu'il faut — les signaux forts (`docked`, charge, tonte, retour)
        font les transitions du cycle courant, `idle` ne fait que conserver l'état déjà prouvé.

        ⚠️ Les TROIS points d'appel de `build_mower_coordination_context` passent par ce helper.
        N'en câbler qu'un ferait diverger deux descriptions du même fait — la famille de défaut
        n°1 de ce projet, déjà payée quatre fois.
        """
        carnet = self._runtime_state.get("mower_passes")
        return isinstance(carnet, dict) and isinstance(carnet.get("en_cours"), dict)

    def _dock_signal_tondeuse_vu(self) -> bool:
        """A-t-on DÉJÀ vu cette tondeuse annoncer sa station par un signal fort ?

        ⚠️ Mémoire collante, et c'est le point : elle décide si le cliquet « passe ouverte »
        de la coordination a le droit de tenir. Une tondeuse qui ne dit que `idle` à sa station
        ne repassera jamais `dockee` ; sans ce drapeau, sa passe reste ouverte pour toujours
        et l'arrosage ne repart plus jamais (signalé par la revue Codex sur la PR #48).

        ⚠️ Le drapeau vit DANS le carnet de passes, pas à côté : `mower_passes` est déjà
        sérialisé et restauré en bloc. Une clé de plus au même endroit voyage toute seule,
        là où une clé sœur aurait dû traverser les deux listes blanches — le piège n°1 du projet.

        Faux tant qu'aucun signal fort n'a été vu : le cliquet est alors relâché. C'est le bon
        sens de la panne — au pire on retombe sur le comportement d'avant la 0.70.0 pendant
        quelques cycles, là où l'inverse bloque l'arrosage définitivement.
        """
        carnet = self._runtime_state.get("mower_passes")
        return isinstance(carnet, dict) and carnet.get("dock_signal_vu") is True

    def _suivre_passes_tondeuse(self, mower_context: dict[str, Any]) -> dict[str, Any]:
        """Tient le carnet des passes garage → garage, et en tire un profil mesuré.

        ⚠️ POURQUOI. Le cumul de minutes de la journée ne dit pas si le jardin a été tondu :
        plus la machine se bloque, plus elle repart, plus elle accumule de minutes. Du 30/07
        au 08/08/2026 :

            jour     passes   minutes   blocages
            30/07       1        49         0
            02/08       2       130         1
            05/08       4       302         3      ← le pire jour, le plus gros total
            08/08       2       127         0      ← la journée parfaite, moitié moins

        L'unité de travail réelle, c'est la PASSE. Et sa fin dit ce qui s'est passé — quatre
        cas, pas trois :

            batterie_vide     rentrée à 10 % après 109 min
            retour_autonome   rentrée à 96 % après 18 min, tonte toujours autorisée
            rappelee          rentrée à 58 % parce que la tonte venait d'être INTERDITE
            bloquee           immobilisée en plein jardin

        ⚠️ `rappelee` manquait à la livraison (0.53.0) et c'est le cas le plus fréquent ici :
        en canicule la chaleur fait tomber l'autorisation, la coordination rappelle la machine,
        et le carnet enregistrait ça comme une décision de la tondeuse.

        ⚠️ ON ÉCRIT LES FAITS BRUTS, PAS SEULEMENT LEUR INTERPRÉTATION. Les batteries et les
        durées sont journalisées telles quelles ; `fin_motif` n'est qu'une étiquette de
        confort. Si le seuil de classement se révèle mauvais, tout se rejoue sur le journal
        sans avoir rien perdu — c'est la différence entre observer et présumer.
        """
        vide: dict[str, Any] = {
            "mower_pass_in_progress": None,
            "mower_pass_count_today": None,
            "mower_last_pass_minutes": None,
            "mower_last_pass_battery_start": None,
            "mower_last_pass_battery_end": None,
            "mower_last_pass_end_reason": None,
            "mower_passes_observed": None,
            "mower_full_pass_minutes_median": None,
            "mower_autonomous_return_battery_median": None,
            "mower_passes_per_day_median": None,
        }
        try:
            maintenant = self._current_datetime()
            aujourd_hui = self._current_date().isoformat()

            carnet = self._runtime_state.get("mower_passes")
            if not isinstance(carnet, dict):
                carnet = {"en_cours": None, "journal": []}
            journal = carnet.get("journal")
            if not isinstance(journal, list):
                journal = []

            connectee = mower_context.get("tondeuse_connectee") is True
            erreur = str(mower_context.get("tondeuse_erreur") or "").strip().lower()
            en_erreur = connectee and bool(erreur) and erreur not in _NO_ERROR_CODES
            en_tonte = connectee and bool(mower_context.get("mower_is_mowing"))
            au_garage = connectee and bool(mower_context.get("mower_is_docked"))
            batterie = _to_float_or_none(mower_context.get("mower_battery"))

            # ── Mémoire collante : cette machine SAIT-ELLE annoncer sa station ? ─────────
            # Posée ici et jamais retirée. Sans elle, `_dock_signal_tondeuse_vu` renverrait
            # toujours faux et le cliquet `idle` de la 0.70.0 serait mort-né ; avec elle
            # posée trop large, le cliquet se refermerait sur une machine incapable de le
            # rouvrir. C'est donc le signal FORT, celui-là seulement, qui l'arme.
            if connectee and bool(mower_context.get("mower_dock_signal_fort")):
                carnet["dock_signal_vu"] = True

            en_cours = carnet.get("en_cours")
            en_cours = en_cours if isinstance(en_cours, dict) else None

            # ── Cumul dans la passe en cours ────────────────────────────────────────────
            if en_cours is not None:
                ecoule = self._minutes_creditables(en_cours.get("derniere_vue"), maintenant)
                genre_precedent = en_cours.get("dernier_genre")
                if ecoule > 0.0 and genre_precedent in {"tonte", "bloquee"}:
                    cle = "minutes_bloquees" if genre_precedent == "bloquee" else "minutes_tondues"
                    en_cours[cle] = round(float(en_cours.get(cle) or 0.0) + ecoule, 2)
                if en_erreur:
                    en_cours["a_ete_bloquee"] = True
                if batterie is not None:
                    en_cours["batterie_fin"] = batterie
                # Suivi de l'autorisation à CHAQUE échantillon : c'est sa valeur au dernier
                # échantillon qui dira si la machine est rentrée d'elle-même ou a été rappelée.
                autorisee = self._tonte_autorisee_au_cycle_precedent()
                if autorisee is not None:
                    en_cours["tonte_autorisee_fin"] = autorisee
                # ⚠️ « Rappelée » suppose qu'il y ait eu une autorisation À RETIRER. Sans ce
                # drapeau, une passe lancée à la main hors fenêtre — autorisation fausse du
                # début à la fin — était classée « rappelée par la coordination » alors que
                # personne ne l'avait rappelée. Mesuré le 22/08/2026 : retour à 51 % sur un
                # travail terminé, étiqueté `rappelee`, et la médiane de retour autonome est
                # restée vide faute de cette passe.
                if autorisee is True:
                    en_cours["autorisee_vue_vraie"] = True
                en_cours["derniere_vue"] = maintenant.isoformat()
                en_cours["dernier_genre"] = (
                    "bloquee" if en_erreur else ("tonte" if en_tonte else "transit")
                )

            # ── Fin de passe : elle est rentrée ─────────────────────────────────────────
            if en_cours is not None and au_garage:
                fermee = self._cloturer_passe(en_cours, maintenant)
                # ⚠️ UNE SORTIE QUI N'A RIEN TONDU N'EST PAS UNE PASSE. L'état de la tondeuse
                # rebondit au démarrage — `starting` → `docked` 9 s → `starting` → `mowing`,
                # mesuré le 30/08/2026 — et chaque rebond ouvrait puis refermait une passe.
                # TROIS entrées sur trente au carnet — recomptées le 01/09/2026 en exécutant
                # ce prédicat sur le journal persisté ; le signalement d'origine en annonçait
                # quatre, à tort. Deux durent DIX SECONDES, toutes sont à 0,0 min tondue, et
                # toutes datent du 30/08.
                #
                # Elles ne sont pas neutres : rentrant forcément à 99-100 % de batterie, elles
                # tirent `mower_autonomous_return_battery_median` vers le haut — mesuré
                # **96,5 % publié au lieu de 85,0** — et elles gonflent le compte de passes du
                # jour (le 30/08 en comptait 8 pour 5 réelles).
                # `mower_full_pass_minutes_median`, lui, ne retient que les fins
                # `batterie_vide` : aucun fantôme ne porte ce motif, il n'a jamais été touché.
                #
                # ⚠️ On ne jette PAS les passes bloquées à 0 minute : un blocage sans tonte est
                # un fait à conserver, c'est même le plus intéressant du carnet.
                if _passe_a_retenir(fermee):
                    journal.append(fermee)
                    journal = journal[-_PASSES_JOURNAL_MAX:]
                en_cours = None

            # ── Début de passe : elle est sortie ────────────────────────────────────────
            elif en_cours is None and connectee and not au_garage:
                en_cours = {
                    "date": aujourd_hui,
                    "debut": maintenant.isoformat(),
                    "batterie_debut": batterie,
                    "batterie_fin": batterie,
                    "minutes_tondues": 0.0,
                    "minutes_bloquees": 0.0,
                    "a_ete_bloquee": bool(en_erreur),
                    "tonte_autorisee_fin": self._tonte_autorisee_au_cycle_precedent(),
                    "derniere_vue": maintenant.isoformat(),
                    "dernier_genre": (
                        "bloquee" if en_erreur else ("tonte" if en_tonte else "transit")
                    ),
                }

            carnet["en_cours"] = en_cours
            carnet["journal"] = journal
            self._runtime_state["mower_passes"] = carnet

            # ⚠️ FILTRÉ À LA LECTURE AUSSI, PAS SEULEMENT À L'ÉCRITURE. La 0.64.0 n'écartait
            # les passes fantômes qu'au moment de les inscrire : les TROIS déjà au carnet (30/08,
            # des rebonds de 10 s à 0,0 min tondue) continuaient d'alimenter tout ce qu'on
            # publie. Mesuré le 01/09/2026 sur l'installation :
            # `mower_autonomous_return_battery_median` sortait **96,5 % au lieu de 85,0** —
            # 11,5 points, parce que trois retours à 99-100 % de batterie s'ajoutaient aux cinq
            # vrais. Un carnet d'apprentissage nourri de rebonds apprend le mauvais profil.
            #
            # ⚠️ `derniere` EN FAIT PARTIE. Aujourd'hui la dernière entrée est réelle, donc rien
            # ne se voyait ; si un rebond avait clôturé en dernier, `mower_last_pass_minutes` et
            # les trois attributs voisins auraient annoncé une passe de 0,0 min à 100 %.
            #
            # Le carnet PERSISTÉ reste intact : on filtre ce qu'on publie, on n'efface pas
            # l'historique. `reset_mower_passes` est le seul outil de purge et il vide tout —
            # les 27 passes légitimes avec les 3 fantômes.
            journal_publie = [p for p in journal if isinstance(p, dict) and _passe_a_retenir(p)]

            derniere = journal_publie[-1] if journal_publie else None
            sortie = {
                "mower_pass_in_progress": en_cours is not None,
                "mower_pass_count_today": sum(
                    1 for p in journal_publie if p.get("date") == aujourd_hui
                ),
                "mower_last_pass_minutes": (derniere or {}).get("minutes_tondues"),
                "mower_last_pass_battery_start": (derniere or {}).get("batterie_debut"),
                "mower_last_pass_battery_end": (derniere or {}).get("batterie_fin"),
                "mower_last_pass_end_reason": (derniere or {}).get("fin_motif"),
                "mower_passes_observed": len(journal_publie),
            }
            sortie.update(self._profil_appris_tondeuse(journal_publie))
            return sortie
        except Exception:  # noqa: BLE001 - un carnet ne doit jamais casser un cycle
            return vide

    def _booleen_publie_au_cycle_precedent(self, cle: str) -> bool | None:
        """Un booléen tel qu'il a été PUBLIÉ au cycle précédent, ou `None`.

        `None` quand aucune décision n'a encore été calculée — une absence, pas un « non ».

        ⚠️ Cherche l'attribut PUIS `extra`. Certains champs sont des membres de
        `DecisionResult` (`tonte_autorisee`), d'autres n'existent que dans `extra`
        (`action_possible`, posé par `_build_decision_extra`). Deux lectures séparées
        finiraient par diverger ; il n'y en a qu'une.
        """
        try:
            resultat = self.brain.last_result
            if resultat is None:
                return None
            valeur = getattr(resultat, cle, None)
            if valeur is None:
                extra = getattr(resultat, "extra", None)
                if isinstance(extra, dict):
                    valeur = extra.get(cle)
            return bool(valeur) if isinstance(valeur, bool) else None
        except Exception:  # noqa: BLE001
            return None

    def _tonte_autorisee_au_cycle_precedent(self) -> bool | None:
        """L'autorisation de tondre telle qu'elle était PUBLIÉE au cycle précédent."""
        return self._booleen_publie_au_cycle_precedent("tonte_autorisee")

    def _cloturer_passe(self, passe: dict[str, Any], maintenant: datetime) -> dict[str, Any]:
        """Ferme une passe et lui attribue un motif de fin, à partir des faits bruts.

        ⚠️ L'ORDRE DES CAS EST LE COEUR DE LA MÉTHODE.
        `batterie_vide` passe avant `rappelee` : une machine à 10 % rentre de toute façon, que
        la coordination l'ait rappelée ou non — lui attribuer le rappel effacerait la cause
        réelle. À l'inverse, rentrer avec 58 % pendant que la tonte vient d'être interdite
        n'est pas une décision de la machine, et c'est ce cas-là qui manquait.
        """
        batterie_fin = _to_float_or_none(passe.get("batterie_fin"))
        autorisee_fin = passe.get("tonte_autorisee_fin")
        bloquee = bool(passe.get("a_ete_bloquee")) or float(passe.get("minutes_bloquees") or 0.0) > 0.0
        if bloquee:
            motif = "bloquee"
        elif batterie_fin is not None and batterie_fin <= _BATTERIE_RETOUR_VIDE_PCT:
            motif = "batterie_vide"
        elif autorisee_fin is False and bool(passe.get("autorisee_vue_vraie")):
            # Autorisée PUIS interdite : la coordination l'a bien rappelée.
            motif = "rappelee"
        elif batterie_fin is None:
            motif = "inconnue"
        else:
            # Charge restante ET tonte toujours autorisée : c'est SA décision.
            motif = "retour_autonome"
        return {
            "date": passe.get("date"),
            "debut": passe.get("debut"),
            "fin": maintenant.isoformat(),
            "minutes_tondues": round(float(passe.get("minutes_tondues") or 0.0), 1),
            "minutes_bloquees": round(float(passe.get("minutes_bloquees") or 0.0), 1),
            "batterie_debut": passe.get("batterie_debut"),
            "batterie_fin": batterie_fin,
            # Fait BRUT conservé à côté de l'étiquette : si le classement se révèle mauvais,
            # tout se rejoue sur le journal sans avoir rien perdu.
            "tonte_autorisee_fin": autorisee_fin,
            # Fait brut, pas une étiquette : la passe s'est déroulée sans qu'aucune
            # autorisation n'ait jamais été vraie (lancement manuel, hors fenêtre).
            "hors_coordination": autorisee_fin is False and not bool(passe.get("autorisee_vue_vraie")),
            "fin_motif": motif,
        }

    def _profil_appris_tondeuse(self, journal: list[Any]) -> dict[str, Any]:
        """Ce que le carnet a appris — ou rien du tout tant qu'il n'a pas assez vu.

        ⚠️ Publier une médiane tirée de deux passes serait pire que ne rien publier : ça
        ressemble à une mesure. En dessous du minimum, ces clés valent `None` et l'absence
        se lit telle quelle.
        """
        passes = [p for p in journal if isinstance(p, dict)]
        profil: dict[str, Any] = {
            "mower_full_pass_minutes_median": None,
            "mower_autonomous_return_battery_median": None,
            "mower_passes_per_day_median": None,
        }
        # ⚠️ PAS DE GARDE GLOBALE ICI. Il y en avait une (`len(passes) < minimum → rien`), et le
        # banc de mutation l'a montrée MORTE : chacun des trois calculs ci-dessous exige déjà
        # son propre minimum d'échantillons. Une garde qu'aucune mutation ne peut tuer ne
        # protège rien — elle donne juste l'illusion d'une protection.
        pleines = [
            float(p["minutes_tondues"])
            for p in passes
            if p.get("fin_motif") == "batterie_vide" and p.get("minutes_tondues") is not None
        ]
        if len(pleines) >= _PASSES_MIN_POUR_APPRENDRE:
            profil["mower_full_pass_minutes_median"] = round(_mediane(pleines), 1)

        autonomes = [
            float(p["batterie_fin"])
            for p in passes
            if p.get("fin_motif") == "retour_autonome" and p.get("batterie_fin") is not None
        ]
        if len(autonomes) >= _PASSES_MIN_POUR_APPRENDRE:
            profil["mower_autonomous_return_battery_median"] = round(_mediane(autonomes), 1)

        # Passes ABOUTIES par jour : une passe bloquée n'est pas un tour de jardin.
        par_jour: dict[str, int] = {}
        for p in passes:
            if p.get("fin_motif") == "bloquee":
                continue
            jour = str(p.get("date") or "")
            if jour:
                par_jour[jour] = par_jour.get(jour, 0) + 1
        if len(par_jour) >= _PASSES_MIN_POUR_APPRENDRE:
            profil["mower_passes_per_day_median"] = round(
                _mediane([float(v) for v in par_jour.values()]), 1
            )
        return profil

    def _suivre_travail_tondeuse(self, mower_context: dict[str, Any]) -> dict[str, Any]:
        """Suit UN travail de tonte de bout en bout, et dit quand il vient de se terminer.

        ⚠️ La difficulté n'est pas de lire 100, c'est de savoir que c'est NOUVEAU. Sur huit
        jours d'historique, `progression_de_la_tonte` passe à 100 en fin de travail puis y
        RESTE jusqu'au travail suivant — 51 h après celui du 25/08, 62 h après celui du 27/08.
        Un test `== 100` serait donc vrai la quasi-totalité du temps.

        On mémorise donc la tâche en cours et le fait de l'avoir vue INACHEVÉE. Le travail
        n'est « terminé » qu'au premier cycle où une tâche vue sous 100 atteint 100.

        ⚠️ La mémoire est persistée : un travail dure 4 à 5 h et traverse les recharges — et
        les redémarrages sont fréquents ici. Non persistée, elle repartirait vide au milieu du
        travail, et le passage à 100 serait lu comme un état de repos : plus aucune tonte
        déclarée. Le silence serait total et indiscernable d'un capteur muet.

        ⚠️ `None` reste une absence. Tondeuse injoignable, entité absente ou langue différente :
        on ne conclut rien, surtout pas « travail non terminé ».
        """
        vide = {
            "mower_job_completion_state": "sans_mesure",
            "mower_job_followed_id": None,
            "mower_job_seen_incomplete": None,
            "mower_job_minutes_total": None,
            "mower_job_resume_possible": None,
            "mower_job_paused_since": None,
        }
        progression = mower_context.get("mower_job_progress_pct")
        tache = mower_context.get("mower_job_id")
        if tache in (None, "") or not isinstance(progression, (int, float)) or isinstance(progression, bool):
            return vide

        tache = str(tache)
        suivi = self._runtime_state.get("mower_job_suivi")
        if not isinstance(suivi, dict):
            suivi = {}
        if suivi.get("task_id") != tache:
            # Nouvelle tâche : on ne sait rien d'elle. Si elle apparaît déjà à 100, c'est un
            # état de repos qu'on découvre, pas un travail qu'on a vu s'accomplir.
            # ⚠️ LA BASE DU JOUR EST MÉMORISÉE ICI, ET C'EST TOUT LE CORRECTIF. Sans elle, une
            # tâche née en cours de journée héritait de TOUT le compteur du jour — et la 0.66.0
            # reportait ensuite ce total sur les jours suivants. Mesuré le 03/09/2026 :
            # `mower_job_minutes_total` annonçait **337,1 min** pour une tâche dont le travail
            # propre valait ~48 min. Le plancher de 90 min était franchi en permanence, donc
            # inopérant : une coupe de bordure de 16 min l'a passé le 02/09, et la tonte du
            # 03/09 a été déclarée sur une sortie de **8,7 minutes**, à 86 % avec des minutes
            # de la veille appartenant à un travail déjà déclaré.
            # `jour` est posé ici aussi, sinon la bascule de date ci-dessous effacerait la base
            # au tout premier cycle.
            _base_jour = mower_context.get("mower_mowing_minutes_today")
            suivi = {
                "task_id": tache,
                "vu_inacheve": float(progression) < 100.0,
                "minutes_base": (
                    float(_base_jour)
                    if isinstance(_base_jour, (int, float)) and not isinstance(_base_jour, bool)
                    else 0.0
                ),
                "jour": self._current_date().isoformat(),
            }
            self._runtime_state["mower_job_suivi"] = suivi
            etat, reprise_possible, pause_depuis = self._etat_travail_tondeuse(
                suivi, mower_context
            )
            return {
                "mower_job_completion_state": etat,
                "mower_job_followed_id": tache,
                "mower_job_seen_incomplete": bool(suivi["vu_inacheve"]),
                "mower_job_minutes_total": self._cumuler_minutes_travail(suivi, mower_context),
                "mower_job_resume_possible": reprise_possible,
                "mower_job_paused_since": pause_depuis,
            }

        if float(progression) < 100.0:
            suivi["vu_inacheve"] = True
            self._runtime_state["mower_job_suivi"] = suivi
            etat, reprise_possible, pause_depuis = self._etat_travail_tondeuse(
                suivi, mower_context
            )
            return {
                "mower_job_completion_state": etat,
                "mower_job_followed_id": tache,
                "mower_job_seen_incomplete": True,
                "mower_job_minutes_total": self._cumuler_minutes_travail(suivi, mower_context),
                "mower_job_resume_possible": reprise_possible,
                "mower_job_paused_since": pause_depuis,
            }

        vu_inacheve = bool(suivi.get("vu_inacheve"))
        suivi.pop("pause_a_quai_depuis", None)
        self._runtime_state["mower_job_suivi"] = suivi
        return {
            "mower_job_completion_state": "termine" if vu_inacheve else "repos",
            "mower_job_followed_id": tache,
            "mower_job_seen_incomplete": vu_inacheve,
            "mower_job_minutes_total": self._cumuler_minutes_travail(suivi, mower_context),
            "mower_job_resume_possible": False,
            "mower_job_paused_since": None,
        }

    def _etat_travail_tondeuse(
        self, suivi: dict[str, Any], mower_context: dict[str, Any]
    ) -> tuple[str, bool, str | None]:
        """Distingue une recharge récente d'un ancien travail resté mémorisé."""
        if not suivi.get("vu_inacheve"):
            suivi.pop("pause_a_quai_depuis", None)
            return "repos", False, None

        inactive_a_quai = (
            mower_context.get("mower_is_docked") is True
            and mower_context.get("mower_is_mowing") is not True
            and mower_context.get("mower_pass_in_progress") is not True
        )
        if not inactive_a_quai:
            suivi.pop("pause_a_quai_depuis", None)
            return "en_cours", False, None

        maintenant = self._current_datetime()
        pause_depuis = self._parse_datetime_value(suivi.get("pause_a_quai_depuis"))
        if pause_depuis is None:
            pause_depuis = maintenant
            suivi["pause_a_quai_depuis"] = maintenant.isoformat()
        ecoule = max(0.0, (maintenant - pause_depuis).total_seconds() / 60.0)
        ancien = ecoule >= _MOWER_JOB_DOCKED_GRACE_MINUTES
        return (
            "repos" if ancien else "en_pause",
            ancien,
            suivi.get("pause_a_quai_depuis"),
        )

    def _cumuler_minutes_travail(
        self, suivi: dict[str, Any], mower_context: dict[str, Any]
    ) -> float | None:
        """Durée de tonte du TRAVAIL en cours, minuit compris.

        ⚠️ DÉFAUT RELEVÉ PAR LA REVUE DE LA PR #47. `mower_mowing_minutes_today` est un
        compteur de JOURNÉE : il repart à zéro à minuit. Un travail de 4 à 5 h démarré en fin
        d'après-midi atteint 100 % après minuit avec un compteur du jour à quelques dizaines de
        minutes. Le plancher de qualification le jugeait alors « trop court », **et brûlait la
        complétion** : la veille n'avait rien déclaré non plus, puisque la déclaration attend
        désormais la fin du travail. Le travail disparaissait entièrement, en silence.

        ⚠️ ET LE DÉFAUT EST **LATENT** — prémisse corrigée le 01/09/2026. La justification
        d'origine invoquait « le travail que la tondeuse a fait le 31/08 » : elle n'est PAS
        sortie ce jour-là. Le carnet persisté ne porte aucune passe les 31/08 et 01/09, et la
        dernière du 30/08 s'achève à 23:01:54 — près de minuit, jamais à cheval. Le défaut est
        établi par lecture du code et par le calendrier de la machine (elle sort volontiers le
        soir : 22:45→23:01 le 30/08, 22:30→23:44 le 22/08), pas par une perte constatée.

        On additionne donc les minutes par JOUR sur la durée du travail : ce que la journée
        courante affiche, plus ce que les journées précédentes du même travail avaient
        atteint. `task_id` étant stable à travers les recharges, l'unité est la bonne.

        ⚠️ Le compteur du jour ne fait que MONTER dans la journée : on retient donc sa
        dernière valeur vue, et on ne la bascule dans le cumul qu'au changement de date. Une
        absence de mesure ne remet rien à zéro — elle laisse le cumul en l'état.

        ⚠️ HYPOTHÈSE RENVERSÉE LE 03/09/2026 — je m'étais trompé de sens. J'avais assumé qu'une
        tâche née en cours de journée pouvait hériter du compteur du jour, en écrivant que « le
        risque penche du bon côté ». L'installation a montré l'inverse : le cumul atteignait
        **337,1 min pour ~48 min de travail réel**, le plancher de 90 min ne filtrait plus rien,
        une coupe de bordure de 16 min l'a franchi le 02/09, et la tonte du 03/09 a été déclarée
        sur une sortie de **8,7 minutes**.

        Sur-compter DÉCLARE UNE TONTE QUI N'A PAS EU LIEU : la hauteur retombe à la lame, le
        retard est remis à zéro, la prochaine tonte est repoussée — le modèle est corrompu et
        rien ne le rattrape. Sous-compter ne fait que retarder une déclaration : le retard
        continue de courir, la hauteur continue de monter, et la tonte suivante corrigera.
        Entre les deux erreurs, la seconde est la seule réparable. On retranche donc la base.

        ⚠️ COÛT ACCEPTÉ : une tâche découverte EN COURS de route (installation neuve, entité
        apparue tard) sous-comptera son propre travail et pourra être jugée trop courte. C'est
        le côté sûr, et le filet Node-RED de 23:50 reste derrière.
        """
        minutes = mower_context.get("mower_mowing_minutes_today")
        anterieur = suivi.get("minutes_anterieures")
        anterieur = float(anterieur) if isinstance(anterieur, (int, float)) and not isinstance(anterieur, bool) else 0.0
        if not isinstance(minutes, (int, float)) or isinstance(minutes, bool):
            jour_courant = suivi.get("minutes_jour")
            jour_courant = (
                float(jour_courant)
                if isinstance(jour_courant, (int, float)) and not isinstance(jour_courant, bool)
                else None
            )
            return None if jour_courant is None and anterieur <= 0.0 else anterieur + (jour_courant or 0.0)

        # Minutes déjà au compteur quand la tâche est née : elles ne sont PAS son travail.
        base = suivi.get("minutes_base")
        base = float(base) if isinstance(base, (int, float)) and not isinstance(base, bool) else 0.0

        aujourd_hui = self._current_date().isoformat()
        if suivi.get("jour") != aujourd_hui:
            # Changement de date SANS changement de tâche : la journée qui s'achève verse son
            # dernier total au cumul du travail, et le compteur du jour repart de la mesure.
            precedent = suivi.get("minutes_jour")
            if isinstance(precedent, (int, float)) and not isinstance(precedent, bool):
                anterieur += float(precedent)
            suivi["minutes_anterieures"] = anterieur
            suivi["jour"] = aujourd_hui
            # ⚠️ Le compteur de journée vient de repartir de zéro : la base de la veille n'a
            # plus de sens. L'oublier ici est ce qui rend le report de minuit encore juste.
            suivi["minutes_base"] = 0.0
            base = 0.0

        # `max(0, …)` : un compteur qui recule (remise à zéro de la tondeuse, valeur aberrante)
        # ne doit pas produire un travail négatif qui masquerait les journées déjà cumulées.
        net = max(0.0, float(minutes) - base)
        suivi["minutes_jour"] = net
        self._runtime_state["mower_job_suivi"] = suivi
        return round(anterieur + net, 1)

    def _consommer_travail_termine(self) -> None:
        """Marque la fin de travail comme TRAITÉE : une complétion ne vaut qu'une fois.

        ⚠️ DÉFAUT INTRODUIT PAR LA 0.61.0, trouvé le 01/09/2026 à 00:15 en auditant le passage
        de minuit. La fin de travail restait offerte à CHAQUE cycle tant que la tâche gardait
        100 % — c'est-à-dire, d'après huit jours d'historique, pendant 2 à 3 JOURS.

        Concrètement le lendemain matin : `mower_job_completion_state` valait encore `termine`
        et le seul rempart restant était le plancher de minutes. Dès 90 min tondues, la journée
        aurait été déclarée sur une complétion de LA VEILLE.

        Une fin de travail appartient au jour où elle a eu lieu. Dès qu'on l'a traitée —
        déclarée, déjà déclarée, ou écartée comme trop courte — on l'éteint : la tâche retombe
        au repos et il faudra une NOUVELLE tâche vue inachevée pour redéclarer.
        """
        suivi = self._runtime_state.get("mower_job_suivi")
        if isinstance(suivi, dict) and suivi.get("vu_inacheve"):
            suivi["vu_inacheve"] = False
            self._runtime_state["mower_job_suivi"] = suivi

    def _travail_termine_du_jour(self) -> float | None:
        """Lecture SEULE du cumul des travaux terminés du jour. Ne mute rien.

        ⚠️ POURQUOI ELLE EXISTE. La clé n'était renseignée que sur le cycle qui traite une
        complétion — deux ou trois fois par jour sur ~700 cycles. À l'écran l'attribut valait
        donc `None` en permanence, et la revue a eu raison de le dire : un nombre qu'on ne peut
        pas lire au moment où on se pose la question n'est pas publié.
        """
        cumul = self._runtime_state.get("mower_travaux_termines")
        if not isinstance(cumul, dict) or cumul.get("date") != self._current_date().isoformat():
            # ⚠️ `0.0`, PAS `None` — VÉRIFIÉ SUR L'INSTALLATION LE 10/09/2026, une heure après
            # la mise en service. L'attribut n'apparaissait NULLE PART sur le capteur de tonte :
            # `_attrs_from_data` (entity_base.py) filtre les valeurs `None`, et aucun travail ne
            # s'était encore terminé depuis le redémarrage. La clé était bien dans les trois
            # listes blanches, les tests de câblage verts — et personne ne voyait rien.
            #
            # La règle « une absence n'est pas un zéro » vaut pour une MESURE dont la source
            # peut se taire. Ce cumul-ci est notre propre comptabilité : quand rien n'est
            # inscrit pour aujourd'hui, « zéro minute de travail terminé » est un fait connu,
            # pas une ignorance. Le seul vrai `None` restant est celui d'une trace inerte,
            # rendue par un coordinateur dégradé.
            return 0.0
        valeur = cumul.get("minutes")
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            return float(valeur)
        return None

    def _cumuler_travail_termine_du_jour(self, minutes_travail: float) -> float:
        """Minutes des travaux **terminés** aujourd'hui, celui-ci compris.

        ⚠️ POURQUOI PAS `mower_mowing_minutes_today`. Ce compteur-là mesure du temps de lame,
        toutes tâches confondues, qu'elles aient abouti ou non. Un travail bloqué à 55 % y pèse
        ses 160 minutes ; une coupe de bordure terminée juste après hériterait donc d'un
        plancher déjà franchi et inscrirait la tonte du jour. C'est le défaut du 30/08/2026
        (déclarée à 49 % de progression) qui revenait par la porte de derrière.

        Ici, chaque travail ne verse que ses minutes PROPRES — base du jour déjà retranchée par
        `_cumuler_minutes_travail` (0.69.0) — et il ne les verse **qu'en atteignant 100 %**. La
        somme dit donc exactement ce qu'on veut savoir : combien de temps de lame a été mené à
        son terme aujourd'hui.

        ⚠️ APPELÉ UNE SEULE FOIS PAR COMPLÉTION. Tous les chemins qui suivent la branche
        `termine` appellent `_consommer_travail_termine()` : la fin de travail s'éteint dès
        qu'elle est traitée, et la même tâche ne peut donc pas re-verser ses minutes au cycle
        suivant — le rempart posé en 0.61.0, sans lequel une complétion restait offerte pendant
        deux à trois jours.

        ⚠️ PERSISTÉ, comme le suivi de travail. Sans cela un redémarrage en milieu de journée
        oublierait les travaux déjà terminés, et une soirée découpée redeviendrait indéclarable
        — précisément le défaut qu'on corrige, sur une installation qui redémarre souvent.
        """
        cumul = self._runtime_state.get("mower_travaux_termines")
        if not isinstance(cumul, dict):
            cumul = {}
        aujourd_hui = self._current_date().isoformat()
        if cumul.get("date") != aujourd_hui:
            cumul = {"date": aujourd_hui, "minutes": 0.0}
        deja = cumul.get("minutes")
        deja = float(deja) if isinstance(deja, (int, float)) and not isinstance(deja, bool) else 0.0
        # `max(0, …)` : un cumul de travail négatif n'a pas de sens et ne doit pas rogner ce
        # qui a déjà été mené au bout.
        ajout = float(minutes_travail) if minutes_travail is not None else 0.0
        cumul["minutes"] = round(deja + max(0.0, ajout), 1)
        self._runtime_state["mower_travaux_termines"] = cumul
        return float(cumul["minutes"])

    def _declarer_tonte_du_jour(self, mower_context: dict[str, Any]) -> dict[str, Any]:
        """Inscrit la tonte du jour dès que le cumul mesuré franchit le seuil.

        ⚠️ POURQUOI CE CODE EXISTE. Jusqu'ici la tonte n'était déclarée que par un flow
        Node-RED externe, à 23:50, qui resommait l'historique de Home Assistant. Deux défauts :

        1. **Le fil se débranche en silence.** Le nœud qui déclarait est resté désactivé du
           30/07 au 06/08/2026 : sept jours de retard de tonte accumulés sans que rien ne
           l'annonce. L'intégration a désormais tout ce qu'il faut pour se passer de lui.
        2. **Onze heures d'écart entre le fait et sa prise en compte.** Le 08/08/2026 la
           tondeuse a franchi le seuil vers 12 h et l'intégration a continué d'afficher
           « 2 jours de retard » jusqu'au soir. Ce n'est pas cosmétique : le retard est un
           LEVIER DE DÉCISION — `overdue_relaxed_baseline` (decision_mowing.py) ouvre une voie
           alternative vers `tonte_ok` ET contourne les blocages agronomiques. Se croire en
           retard alors qu'on vient de tondre relâche des gardes qui devaient tenir.

        Le seuil n'a pas besoin de la fin de journée : une fois 90 min cumulées, tondre
        davantage ne peut pas les dé-cumuler. La décision est disponible dès le franchissement.

        ⚠️ ET IL SE LIT SUR LA JOURNÉE DE TRAVAUX TERMINÉS, PAS SUR LE SEUL TRAVAIL COURANT
        (0.82.0). Le plancher qualifiait le travail en cours ; une journée découpée en plusieurs
        travaux courts passait donc à travers alors que la pelouse avait bien été tondue. Voir
        le commentaire au point de comparaison — et surtout pourquoi ce n'est PAS le compteur
        de minutes de la journée qui sert.

        ⚠️ UNE DÉCLARATION EST UNE ÉCRITURE. Une fausse tonte déclarée est pire qu'une tonte
        non déclarée — elle remet le compteur de retard à zéro et endort la surveillance. D'où
        CINQ gardes, dans cet ordre : interrupteur explicite ; mesure réellement présente
        (`None` = tondeuse injoignable, ce n'est PAS « zéro minute ») ; **travail réellement
        terminé** — la garde née du 30/08/2026, celle qui manquait à cette liste ; plancher
        franchi par les travaux terminés du jour ; journée pas déjà inscrite.
        """
        # Le seuil se lit DANS le try : la lecture elle-même passe par `self.memory`, donc par
        # le cerveau. Hors du try, un coordinator dégradé faisait remonter l'exception dans le
        # cycle de mise à jour au lieu de renvoyer une trace inerte.
        trace: dict[str, Any] = {
            "mower_auto_declaration_state": "desactivee",
            "mower_auto_declaration_threshold_minutes": DEFAULT_AUTO_MOWING_DECLARATION_MINUTES,
            "mower_auto_declared_today": False,
            # ⚠️ La clé est posée DÈS L'INITIALISATION de la trace, pas seulement sur le chemin
            # qui la calcule : une clé qui n'apparaît que parfois casse les consommateurs en
            # silence, et le capteur afficherait un attribut intermittent.
            "mower_travail_termine_minutes_jour": None,
        }
        try:
            seuil = self.auto_mowing_declaration_minutes
            trace["mower_auto_declaration_threshold_minutes"] = seuil
            # ⚠️ RENSEIGNÉE À CHAQUE CYCLE, pas seulement quand un travail se termine : sinon
            # l'attribut est `None` 99 % du temps et ne sert à personne.
            trace["mower_travail_termine_minutes_jour"] = self._travail_termine_du_jour()
            if not self.auto_mowing_declaration_enabled:
                return trace

            minutes = mower_context.get("mower_mowing_minutes_today")
            if not isinstance(minutes, (int, float)) or isinstance(minutes, bool):
                # Absence de mesure : tondeuse injoignable, ou non configurée. Ne rien inscrire.
                trace["mower_auto_declaration_state"] = "sans_mesure"
                return trace

            # ⚠️ LE TRAVAIL, PAS LA DURÉE. Le seuil en minutes déclarait une tonte dès 90 min
            # cumulées, quelle que soit la surface faite. Mesuré le 30/08/2026 : déclarée à
            # 14:32 avec 102,8 min tondues et le travail à **49 %** — hauteur estimée remise
            # à 5,5 cm, retard remis à 0, prochaine tonte repoussée de 3 jours, pendant que la
            # moitié de la pelouse restait haute et que la tondeuse tondait encore.
            #
            # ⚠️ ET « progression = 100 » N'EST PAS UN ÉVÉNEMENT : c'est l'état de REPOS. Relevé
            # sur 8 jours, la valeur reste à 100 entre deux travaux — 51 h après celui du 25/08,
            # 62 h après celui du 27/08. Déclarer sur `== 100` déclencherait donc tous les jours.
            # On déclare sur le PASSAGE à 100 d'une tâche qu'on a vue en dessous, jamais sur la
            # valeur seule. `task_id` est stable à travers les recharges : il recolle les deux
            # passes d'une même journée en un seul travail, ce qui est exactement l'unité voulue.
            suivi = self._suivre_travail_tondeuse(mower_context)
            trace.update(suivi)
            if suivi["mower_job_completion_state"] == "sans_mesure":
                trace["mower_auto_declaration_state"] = "sans_mesure"
                return trace
            if suivi["mower_job_completion_state"] != "termine":
                trace["mower_auto_declaration_state"] = {
                    "repos": "travail_au_repos",
                    "en_pause": "travail_en_pause",
                }.get(suivi["mower_job_completion_state"], "travail_en_cours")
                return trace

            # Plancher de durée : une COUPE DE BORDURE est aussi une tâche qui monte à 100.
            # Elle est courte, là où un vrai travail dure 4 à 5 h (mesuré les 25 et 27/08).
            # Le réglage existant garde son nom et change de sens : il ne DÉCLENCHE plus, il
            # QUALIFIE — un travail terminé ne compte que s'il a représenté au moins ce temps
            # de tonte dans la journée.
            # ⚠️ SUR LE TRAVAIL, PAS SUR LA JOURNÉE. `mower_mowing_minutes_today` repart à
            # zéro à minuit : un travail terminé à 00:30 y pèse quelques dizaines de minutes
            # et se faisait écarter comme « trop court » — complétion brûlée, veille jamais
            # déclarée, travail perdu en silence. Le cumul suit la tâche à travers minuit.
            minutes_travail = suivi.get("mower_job_minutes_total")
            if not isinstance(minutes_travail, (int, float)) or isinstance(minutes_travail, bool):
                minutes_travail = float(minutes)

            # ⚠️ LE TRAVAIL SEUL NE SUFFIT PAS — défaut mesuré le 08/09/2026. La tondeuse est
            # sortie TROIS fois ce soir-là : 15:29→16:27, 19:47→20:07, 20:44→22:11. Fenêtres
            # d'états 57,8 + 19,4 + 87,2 min ; l'intégration a compté 88,1 min pour la dernière
            # (elle crédite le temps passé en tonte cycle par cycle, départ compris), soit un
            # `mower_job_minutes_total` de 88 pour un plancher de 90. Raté de deux minutes.
            #
            # Trois `task_id` distincts, donc trois travaux : chacun pris isolément restait sous
            # le plancher. Chaque complétion a été consommée en `travail_trop_court` et la
            # journée n'a rien inscrit — pour ~165 minutes de lame réellement passées sur la
            # pelouse. Le lendemain matin, hauteur estimée montée de 5,1 à 5,3 cm et
            # `mowing_is_overdue` à `true` avec 3 jours de retard annoncés. Ce n'est pas
            # cosmétique : `overdue_relaxed_baseline` (decision_mowing.py) ouvre une voie
            # alternative vers `tonte_ok` ET contourne les blocages agronomiques. Se croire en
            # retard relâche des gardes qui devaient tenir. Et ce n'était pas un accident :
            # minutes tondues du 04 au 08/09, 188 · 135 · 149 · 0 · 164.
            #
            # ⚠️ MAIS LE COMPTEUR DE LA JOURNÉE N'EST PAS LA RÉPONSE, et le premier jet de ce
            # correctif s'y est trompé. Qualifier sur `max(travail, mower_mowing_minutes_today)`
            # rouvrait le défaut du 30/08 par une autre porte, rejoué sur le code :
            #
            #     09:00  tâche A naît            → base 0
            #     11:40  A à 55 %, journée 160   → `travail_en_cours`, puis A se bloque et
            #                                      rentre : elle n'atteindra JAMAIS 100 %
            #     18:00  coupe de bordure B      → base 160
            #     18:12  B à 100 %, journée 172  → max(12, 172) = 172 ≥ 90 → **DÉCLARÉE**
            #
            # Une bordure de douze minutes inscrivait la tonte du jour avec les minutes d'un
            # travail resté inachevé — hauteur ré-ancrée sur la lame, retard remis à zéro,
            # surveillance endormie sur une pelouse tondue à 55 %. Le compteur de la journée
            # est un cumul de temps de lame PARTAGÉ par toutes les tâches : il ne prouve rien
            # sur ce qui a été mené à son terme.
            #
            # ⚠️ CE QU'ON CUMULE DONC : les minutes des travaux **TERMINÉS** de la journée.
            # C'est la seule grandeur qui dit à la fois « il y a eu du travail » et « il a été
            # mené au bout ». Elle additionne les trois travaux du 08/09 (chacun terminé) sans
            # jamais compter les 160 minutes d'un travail abandonné. Et elle ne peut rien
            # emprunter à la veille : elle est indexée sur la date, et chaque travail n'y verse
            # que ses minutes PROPRES, base du jour déjà retranchée (0.69.0) — le chemin du
            # défaut du 03/09, où 86 % du cumul appartenait à un travail déjà déclaré, reste
            # fermé.
            minutes_qualifiantes = self._cumuler_travail_termine_du_jour(minutes_travail)
            trace["mower_travail_termine_minutes_jour"] = minutes_qualifiantes
            if minutes_qualifiantes < float(seuil):
                trace["mower_auto_declaration_state"] = "travail_trop_court"
                self._consommer_travail_termine()
                return trace

            # ⚠️ MÊME JOURNÉE des deux côtés. Le cumul est indexé sur `_current_date()` ; la
            # date est passée EXPLICITEMENT à `record_mowing`, qui retomberait sinon sur
            # `dt_util.now().date()`. Deux horloges pour un même fait, c'est une tonte
            # déclarée la veille de celle qu'on a mesurée.
            aujourd_hui = self._current_date()
            jour = aujourd_hui.isoformat()
            historique = self.history if isinstance(self.history, list) else []
            for item in historique:
                if (
                    isinstance(item, dict)
                    and item.get("type") == "tonte"
                    and item.get("date") == jour
                ):
                    trace["mower_auto_declaration_state"] = "deja_declaree"
                    trace["mower_auto_declared_today"] = True
                    self._consommer_travail_termine()
                    return trace

            # Écriture SYNCHRONE dans le cerveau, jamais `async_record_mowing` : celle-ci
            # appelle `async_request_refresh()`, or on est à l'intérieur du cycle de mise à
            # jour. La persistance est assurée par le `_async_save_state()` de fin de cycle,
            # et déclarer AVANT `compute_snapshot` fait que le retard est corrigé dès ce
            # cycle-ci, pas au suivant.
            self.brain.record_mowing(
                aujourd_hui,
                hauteur_coupe_mm=mower_context.get("tondeuse_hauteur_coupe_mm"),
            )
            _LOGGER.info(
                "Tonte du %s déclarée automatiquement : travail %s terminé à 100 %%, "
                "%.1f min de travaux terminés aujourd'hui "
                "(dont %.1f pour celui-ci ; journée mesurée %.1f, plancher %d min)",
                jour,
                # ⚠️ `suivi` vient de `_suivre_travail_tondeuse`, qui nomme la clé
                # `mower_job_followed_id`. `mower_job_id` n'y a JAMAIS existé : la ligne
                # écrivait « travail ? » depuis la 0.61.0 (commit 0d8c4e8, « la tonte se
                # déclare sur le travail terminé, plus sur une durée »).
                suivi.get("mower_job_followed_id") or "?",
                minutes_qualifiantes,
                float(minutes_travail),
                float(minutes),
                seuil,
            )
            trace["mower_auto_declaration_state"] = "declaree"
            trace["mower_auto_declared_today"] = True
            self._consommer_travail_termine()
            return trace
        except Exception:  # noqa: BLE001 - une déclaration ratée ne doit pas casser un cycle
            trace["mower_auto_declaration_state"] = "erreur"
            return trace

    def _tracer_cycle(self) -> dict[str, Any]:
        """Origine et numéro du cycle courant. Trace pure, aucune décision n'en dépend.

        `origine` vaut `capteur:<entity_id>` / `vanne:<entity_id>` quand un changement d'état a
        déclenché le rafraîchissement, `intervalle` quand c'est le cycle périodique de 2 min.
        Deux publications consécutives portant la même seconde mais des origines différentes
        signent une concurrence entre les deux chemins — l'hypothèse à confirmer ou à écarter
        pour l'objectif non reproductible.
        """
        try:
            origine = getattr(self, "_cycle_origine_demandee", None) or "intervalle"
            self._cycle_origine_demandee = None
            seq = int(getattr(self, "_cycle_sequence", 0)) + 1
            self._cycle_sequence = seq
            return {
                "cycle_origine": origine,
                "cycle_sequence": seq,
                "cycle_at": self._current_datetime().isoformat(),
            }
        except Exception:  # noqa: BLE001 - une trace ne doit jamais casser une décision
            return {"cycle_origine": "inconnue", "cycle_sequence": None, "cycle_at": None}

    def _build_sensor_health(
        self,
        *,
        temperature_source: str,
        humidite_capteur: float | None,
        vent_capteur: float | None,
        etp_capteur: float | None,
        pluie_24h_sensor: float | None,
        weather_profile: dict[str, Any],
        eto_hourly: dict[str, Any],
        temperature: float | None = None,
        humidite: float | None = None,
        vent: float | None = None,
    ) -> dict[str, Any]:
        """Voyants de santé des ENTRÉES. Extrait pour être testable directement.

        ⚠️ Chaque drapeau doit tester sa SOURCE, jamais la valeur résolue : une valeur résolue
        l'est aussi par un repli, et le voyant reste alors au vert pendant que la mesure manque.

        ⚠️ ET LES VALEURS ELLES-MÊMES SONT PUBLIÉES À CÔTÉ. Les drapeaux disent d'où vient la
        mesure, jamais ce qu'elle vaut APRÈS conversion — or c'est là que vivent les pièges :
        `wind_speed_to_kmh` et `pression_vers_hpa` transforment la valeur selon l'unité déclarée
        par l'entité, et une unité absente ou inattendue passe sans un mot avec tous les voyants
        au vert. Le WS90 publie des kPa : sans `pression_vers_hpa` il donnerait 101 hPa au lieu
        de 1010, en plein calcul FAO-56, et `eto_pressure_measured` resterait `true`.
        Trois conséquences directes, vécues le 06/09/2026 : on ne pouvait pas décomposer une ET0
        surprenante, ni vérifier qu'un changement de capteur avait bougé le nombre (les drapeaux
        ne distinguent pas le capteur A du capteur B, tous deux « configurés »), ni contrôler une
        unité. Publier la valeur RÉSOLUE — celle qui entre réellement dans le modèle — ferme
        les trois.
        """
        return {
            # ── Ce que le modèle a RÉELLEMENT utilisé ce cycle, unité dans le nom ────────────
            # À lire AVEC le drapeau voisin : le drapeau dit d'où ça vient, la valeur dit quoi.
            "temperature_utilisee_c": (
                round(float(temperature), 1) if isinstance(temperature, (int, float)) else None
            ),
            "humidite_utilisee_pct": (
                round(float(humidite), 1) if isinstance(humidite, (int, float)) else None
            ),
            "vent_utilise_kmh": (
                round(float(vent), 2) if isinstance(vent, (int, float)) else None
            ),
            # Teste la SOURCE, pas la valeur résolue (cf. le commentaire sur `humidite_capteur`).
            # `temperature_source` vaut « capteur » uniquement quand la mesure vient du capteur
            # configuré ; « weather », « meteo_forecast » et « non disponible » sont des replis.
            "temperature_valid": (
                temperature_source == "capteur"
                or self._get_conf(CONF_CAPTEUR_TEMPERATURE) is None
            ),
            # Tester le CAPTEUR, pas la valeur résolue : `pluie_24h` reprend la valeur du capteur
            # quand il en a une, et retombe sur la prévision sinon — l'expression d'origine
            # (`pluie_24h is not None or pluie_24h_sensor is None`) était donc toujours vraie et le
            # voyant ne pouvait jamais signaler un capteur pluie en panne. Même forme que etp_valid.
            "pluie_valid": pluie_24h_sensor is not None or self._get_conf(CONF_CAPTEUR_PLUIE_24H) is None,
            # ⚠️ RENDRE LA GARDE VISIBLE. « Il pleut en ce moment » a bloqué et débloqué
            # l'arrosage pendant des mois sans qu'aucune sortie ne dise sur quoi elle se
            # fondait — un garde muet est indiscernable d'un garde cassé (même leçon que
            # `mower_auto_declaration_state`). On publie donc son entrée MESURÉE, à côté du
            # `weather_condition` déjà lisible ailleurs : les deux bras deviennent comparables,
            # et la nuit du 16/08 se relit d'un coup d'œil. Placé dans `sensor_health`, qui est
            # DÉJÀ publié comme un dict : aucune liste blanche à traverser, donc aucun des
            # chemins qui cassent en silence sur ce projet.
            "pluie_mesuree_active": weather_profile.get("pluie_mesuree_active"),
            # Publiée À CÔTÉ de la précédente, volontairement : c'est en les comparant sur
            # plusieurs averses qu'on saura si la mesure directe peut remplacer la déduction.
            "pluie_actuelle_mm": weather_profile.get("pluie_actuelle_mm"),
            "pluie_actuelle_active": weather_profile.get("pluie_actuelle_active"),
            "pluie_cumul_jour_mm": weather_profile.get("pluie_cumul_jour_mm"),
            "pluie_cumul_pic_mm": weather_profile.get("pluie_cumul_pic_mm"),
            # ⚠️ Les DEUX lames récentes, côte à côte : c'est leur écart qui a expliqué le
            # blocage du 09/09 (voisin 0,1 mm, station 0,0). Sans elles à l'écran, « herbe
            # mouillée » ne dit pas de quelle pluie il parle, ni si la pelouse l'a reçue.
            "pluie_lame_voisin_mm": weather_profile.get("pluie_mesuree_lame_mm"),
            "pluie_lame_station_mm": weather_profile.get("pluie_cumul_lame_mm"),
            "pluie_gain_rejete_mm": weather_profile.get("pluie_gain_rejete_mm"),
            "pluie_mesuree_minutes_depuis_hausse": weather_profile.get(
                "pluie_mesuree_minutes_depuis_hausse"
            ),
            "etp_valid": etp_capteur is not None or self._get_conf(CONF_CAPTEUR_ETP) is None,
            "humidity_valid": (
                humidite_capteur is not None or self._get_conf(CONF_CAPTEUR_HUMIDITE) is None
            ),
            # ⚠️ LE VENT N'AVAIT AUCUN DRAPEAU — alors que c'est le levier majeur de l'ET0.
            # Mesuré sur 757 échantillons appariés : vent mesuré médiane 4,7 km/h contre vent
            # PRÉVU médiane 10,1, le prévu supérieur dans 97 % des cas. En rejouant le calcul
            # sur les entrées réelles du 29/07 : capteurs 8,9 mm, vent seul replié 12,1 (+36 %),
            # température seule repliée 8,8 (−1 %). Ce jour-là, DEUX SECONDES de repli ont posé
            # le pic d'ET0 du jour à 12,4, et le cliquet `max(etp, etp_pic_jour)` l'a figé.
            "wind_measured": vent_capteur is not None,
            "wind_valid": vent_capteur is not None or self._get_conf(CONF_CAPTEUR_VENT) is None,
            # L'entité météo elle-même : indisponible 64 min le 03/08/2026 HORS redémarrage,
            # avec tous les drapeaux au vert pendant ce temps. Sans ce voyant, une panne de la
            # source de repli est parfaitement invisible.
            "weather_profile_available": bool(weather_profile),
            # QUALITÉ DE L'ET0 HORAIRE (0.19.0) : depuis qu'elle pilote le bilan sol, savoir si
            # elle tourne sur des valeurs MESURÉES ou sur des replis n'est plus un détail. Le
            # rayonnement est le plus déterminant (repli = ciel déduit des nuages) ; le vent
            # compte aussi beaucoup (un vent PRÉVU au lieu de mesuré est ce qui donnait 9 mm/j
            # au lieu de 6). Exposé ici pour rester au même endroit que le reste de la santé
            # capteurs, donc visible sans activer les entités de diagnostic.
            "eto_radiation_measured": eto_hourly.get("radiation_source") == "capteur",
            "eto_pressure_measured": eto_hourly.get("pressure_source") == "capteur",
            "eto_hourly_available": eto_hourly.get("value") is not None,
            # ⚠️ L'ET RÉELLEMENT DÉBITÉE DU JOUR, exposée pour la première fois. C'est elle qui
            # vide la réserve, et elle n'était visible nulle part : seule `etp_mm` (estimation
            # PLEINE JOURNÉE, majorante) l'était. L'écart n'est pas anecdotique — sur 8 jours,
            # 36,7 mm débités contre 49,1 mm estimés, soit +33,8 %, 8 jours sur 8 dans le même
            # sens. Et c'est ce chiffre qui aurait montré d'un coup d'œil la marche du 29/07 :
            # +1,0 mm en 68 secondes, soit 53 mm/h, quand l'ET0 horaire réelle plafonne à 0,6.
            **self._etp_ecoulee_du_jour(),
        
        }

    def _etp_ecoulee_du_jour(self) -> dict[str, Any]:
        """ET réellement débitée aujourd'hui, lue dans le journal du bilan sol.

        Défensif par construction : ce bloc alimente `sensor_health`, qui doit rester présent
        même si le journal est absent, vide, corrompu, ou daté d'hier. Une exception ici
        priverait l'utilisateur de TOUS les voyants de santé.
        """
        vide: dict[str, Any] = {"etp_ecoulee_mm": None, "etp_jour_estime_mm": None}
        try:
            return etp_ecoulee_du_jour(self.soil_balance, today=self._current_date())
        except (AttributeError, TypeError, ValueError, IndexError):
            return vide

    def _extract_block_reason(self, snapshot: dict[str, Any]) -> str | None:
        return extract_block_reason(snapshot)

    def _build_observability_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return build_observability_payload(
            snapshot,
            history=self.history,
            today=self._current_date(),
            feedback_observation=self.memory.get("feedback_observation"),
        )

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
        await self._rafraichir_apres_action_utilisateur()

    async def async_set_date_action(self, date_action: date | None = None) -> None:
        """Définit la date de la dernière intervention de phase."""
        self.brain.set_date_action(date_action)
        await self._async_save_state()
        await self._rafraichir_apres_action_utilisateur()

    async def async_set_normal(self) -> None:
        """Réinitialise la phase active vers Normal (historique conservé)."""
        self.brain.set_normal()
        await self._async_save_state()
        await self._rafraichir_apres_action_utilisateur()

    async def async_clear_irrigation_safety_lock(self) -> None:
        """Lève le verrou après vérification physique des vannes, sans changer le mode."""
        self._ensure_irrigation_runtime_bootstrap()
        if self._watering_session_active():
            raise HomeAssistantError(
                "Impossible de lever le verrou : une zone d'arrosage est encore active."
            )
        if not self._runtime_state.get("auto_irrigation_safety_lock"):
            return
        self._runtime_state["auto_irrigation_safety_lock"] = False
        await self._async_save_state()
        await self._rafraichir_apres_action_utilisateur()

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
        await self._rafraichir_apres_action_utilisateur()

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
        await self._rafraichir_apres_action_utilisateur()

    # ⚠️ CHEMIN MIXTE : NE PAS y mettre le rafraîchissement immédiat. Relevé par la revue
    # adversariale du 10/09/2026. Cette méthode sert le service `declare_watering` (une action
    # utilisateur) MAIS elle est aussi appelée par l'exécuteur d'arrosage — fin de session, arrêt,
    # reprise — soit une quinzaine de points internes. Les brancher sur l'immédiat ferait
    # tourner un cycle complet, en ligne, à l'intérieur de la tâche d'arrosage. C'est le
    # POINT D'ENTRÉE utilisateur qui rafraîchit, pas cette méthode : voir
    # `_handle_declare_watering` (__init__.py).
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
        await self._rafraichir_apres_action_utilisateur()

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
            CONF_CAPTEUR_POINT_DE_ROSEE,
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
        # APRÈS la tentative de lancement : l'alerte lit le motif qu'elle vient de laisser.
        await self._async_verifier_alertes(snapshot)

    # ── Alertes, notifications et conseil IA (0.93.0) ───────────────────────────────────────

    async def _async_verifier_alertes(self, snapshot: dict[str, Any]) -> None:
        """Observation SEULE : rien ici n'entre dans la décision ni dans le lancement.

        ⚠️ ISOLÉE PAR UN `except` LARGE, à dessein : cette méthode tourne dans le tick qui lance
        les arrosages. Une faute dans un message ne doit jamais retenir un cycle de graines.
        """
        try:
            if not notifications.alertes_voulues(self.entry):
                return
            maintenant = self._current_datetime()
            memoire = self._runtime_state.get("alertes_gazon")
            alertes, etat = notifications.evaluer_alertes(
                memoire,
                **self._contexte_des_alertes(snapshot, maintenant=maintenant),
            )
            if etat != memoire:
                # Écrit AVANT l'envoi : un redémarrage entre les deux ne renverra rien.
                self._runtime_state["alertes_gazon"] = etat
                await self._persist_runtime_state()
            if alertes:
                try:
                    contexte = self._resume_du_gazon()
                except Exception:  # noqa: BLE001 - le message factuel doit quand même partir
                    _LOGGER.debug(
                        "Résumé du gazon indisponible pour les notifications",
                        exc_info=True,
                    )
                    contexte = []
                await notifications.async_publier(
                    self.hass,
                    self.entry,
                    alertes,
                    maintenant=maintenant,
                    contexte=contexte,
                )
        except Exception:  # noqa: BLE001 - une alerte ne doit jamais casser le tick d'arrosage
            _LOGGER.exception("Alertes du gazon non évaluées")

    def arrosage_en_cours(self) -> bool:
        """De l'eau coule ou va couler : une session, une vanne commune occupée, un cycle lancé."""
        scheduler = getattr(self, "_auto_irrigation_scheduler_task", None)
        return bool(
            self._watering_session_active()
            or self._shared_valve_busy_elsewhere()
            or (scheduler is not None and not scheduler.done())
        )

    async def _async_apply_mower_control(self, snapshot: dict[str, Any]) -> None:
        """Évalue puis, uniquement en mode actif, exécute une commande de tondeuse.

        Ce chemin ne doit jamais faire tomber le cycle principal : un service absent, une entité
        indisponible ou un volet bloqué devient un état publié et journalisé, pas une exception du
        coordinateur. Le premier cycle après chaque redémarrage reste toujours sans commande.
        """
        mode = str(self._get_conf(CONF_PILOTAGE_TONDEUSE) or DEFAULT_MOWER_CONTROL_MODE)
        cover_entity_raw = self._get_conf(CONF_ENTITE_VOLET_GARAGE_TONDEUSE)
        cover_entity = str(cover_entity_raw) if cover_entity_raw else None
        cover_state = None
        cover_position = None
        if cover_entity:
            cover = self.hass.states.get(cover_entity)
            cover_state = str(getattr(cover, "state", "unknown") or "unknown")
            cover_position = getattr(cover, "attributes", {}).get("current_position") if cover else None

        runtime = self._runtime_state.get("mower_control")
        if not isinstance(runtime, dict):
            runtime = {}
            self._runtime_state["mower_control"] = runtime
        settings = self._reglages_instance()
        decision = evaluate_mower_control(
            snapshot,
            now=self._current_datetime(),
            mode=mode,
            settings={
                "tondeuse_creneaux_depart": self._get_conf(CONF_TONDEUSE_CRENEAUX_DEPART)
                or DEFAULT_MOWER_START_WINDOW_POLICY,
                "tondeuse_pilotage_batterie_min": lire_reglage(
                    settings, "tondeuse_pilotage_batterie_min", DEFAULT_MOWER_CONTROL_MIN_BATTERY
                ),
                "tondeuse_pilotage_delai_commandes": lire_reglage(
                    settings,
                    "tondeuse_pilotage_delai_commandes",
                    DEFAULT_MOWER_CONTROL_COMMAND_COOLDOWN_MINUTES,
                ),
                "tondeuse_garage_ouvrir_avant_depart": lire_reglage(
                    settings, "tondeuse_garage_ouvrir_avant_depart", DEFAULT_MOWER_GARAGE_OPEN_BEFORE_START
                ),
                "tondeuse_garage_ouvrir_pour_retour": lire_reglage(
                    settings, "tondeuse_garage_ouvrir_pour_retour", DEFAULT_MOWER_GARAGE_OPEN_FOR_RETURN
                ),
                "tondeuse_garage_fermer_apres_retour": lire_reglage(
                    settings, "tondeuse_garage_fermer_apres_retour", DEFAULT_MOWER_GARAGE_CLOSE_AFTER_DOCK
                ),
                "tondeuse_garage_avance_ouverture": lire_reglage(
                    settings,
                    "tondeuse_garage_avance_ouverture",
                    DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES,
                ),
                "tondeuse_garage_ouverture_min": lire_reglage(
                    settings,
                    "tondeuse_garage_ouverture_min",
                    DEFAULT_MOWER_GARAGE_MIN_OPEN_POSITION,
                ),
                "tondeuse_garage_delai_fermeture": lire_reglage(
                    settings,
                    "tondeuse_garage_delai_fermeture",
                    DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES,
                ),
            },
            runtime=runtime,
            irrigation_active=self.arrosage_en_cours(),
            cover_entity=cover_entity,
            cover_state=cover_state,
            cover_position=cover_position,
            bootstrap_complete=getattr(self, "_mower_control_bootstrap_complete", False),
        )
        self._mower_control_bootstrap_complete = True
        updates = decision.pop("mower_control_runtime_updates", {})
        if isinstance(updates, Mapping):
            runtime.update(updates)
        action = decision.get("mower_control_pending_action")
        decision["mower_garage_entity"] = cover_entity
        decision["mower_garage_state"] = cover_state
        decision["mower_garage_position"] = cover_position
        decision["mower_control_last_action"] = runtime.get("last_action")
        decision["mower_control_last_action_at"] = runtime.get("last_action_at")
        decision["mower_control_last_error"] = runtime.get("last_error")

        if mode == "observation" and action:
            decision["mower_control_state"] = "observation"
            decision["mower_control_reason"] = f"Observation : {decision['mower_control_reason']}"
        elif mode == "actif" and isinstance(action, str):
            mower_entity = str(snapshot.get("tondeuse_source_entity") or "")
            domain, service, entity_id = {
                "start_mowing": ("lawn_mower", "start_mowing", mower_entity),
                "dock": ("lawn_mower", "dock", mower_entity),
                "open_cover": ("cover", "open_cover", cover_entity or ""),
                "close_cover": ("cover", "close_cover", cover_entity or ""),
            }[action]
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {"entity_id": entity_id},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - le calcul gazon doit continuer
                runtime["last_error"] = str(err) or err.__class__.__name__
                decision["mower_control_state"] = "erreur"
                decision["mower_control_reason"] = f"Commande {action} refusée par Home Assistant."
                decision["mower_control_last_error"] = runtime["last_error"]
                _LOGGER.exception("Commande tondeuse impossible : %s", action)
            else:
                instant = self._current_datetime().isoformat()
                runtime.update({"last_action": action, "last_action_at": instant, "last_error": None})
                if action == "start_mowing":
                    # Un départ réussi n'est envoyé qu'une fois. Après une reprise due, la dette
                    # est acquittée immédiatement puis le constructeur reprend ses cycles de
                    # recharge/redépart sans autre commande de l'intégration.
                    reprise = runtime.get("resume_required") is True
                    runtime["managed_start_pending"] = True
                    runtime["managed_start_requested_at"] = instant
                    # Référence au moment de la commande (0.97.25) : le pilote n'accepte ensuite
                    # qu'une vraie TRANSITION par rapport à cette référence (identifiant, progression
                    # ET état du travail) pour confirmer un vrai départ, jamais une simple valeur
                    # déjà présente avant la commande — voir mower_control.evaluate_mower_control.
                    runtime["managed_start_baseline_captured"] = True
                    runtime["managed_start_baseline_job_id"] = (
                        str(
                            snapshot.get("mower_job_followed_id")
                            or snapshot.get("mower_job_id")
                            or ""
                        )
                        or None
                    )
                    runtime["managed_start_baseline_progress"] = snapshot.get("mower_job_progress_pct")
                    runtime["managed_start_baseline_completion_state"] = (
                        str(snapshot.get("mower_job_completion_state") or "").lower() or None
                    )
                    if not reprise and runtime.get("managed_cycle_active") is not True:
                        runtime["managed_job_seen_incomplete"] = False
                        runtime["managed_job_id"] = None
                    if reprise:
                        runtime["resume_required"] = False
                        runtime["resume_reason"] = None
                        runtime["resume_requested_at"] = None
                elif action == "dock":
                    # Seul un cycle effectivement lancé par ce pilote crée une reprise due.
                    # Un travail manuel ou constructeur rappelé par sécurité n'est jamais relancé
                    # silencieusement par l'intégration.
                    if (
                        runtime.get("managed_cycle_active") is True
                        or runtime.get("managed_start_pending") is True
                    ):
                        runtime["resume_required"] = True
                        runtime["resume_reason"] = (
                            snapshot.get("mowing_block_reason_label")
                            or snapshot.get("mowing_block_reason")
                            or decision.get("mower_control_reason")
                        )
                        runtime["resume_requested_at"] = instant
                elif action == "open_cover":
                    runtime["garage_opened_at"] = None
                elif action == "close_cover":
                    runtime["garage_opened_at"] = None
                    runtime["docked_since"] = None
                decision["mower_control_pending_action"] = None
                decision["mower_control_last_action"] = action
                decision["mower_control_last_action_at"] = instant
                decision["mower_control_last_error"] = None
        decision["mower_control_cycle_state"] = (
            "reprise_attendue"
            if runtime.get("resume_required") is True
            else "depart_envoye"
            if runtime.get("managed_start_pending") is True
            else "cycle_autonome"
            if runtime.get("managed_cycle_active") is True
            else "inactif"
        )
        decision["mower_control_resume_required"] = runtime.get("resume_required") is True
        decision["mower_control_resume_reason"] = runtime.get("resume_reason")
        snapshot.update(decision)

    def _contexte_des_alertes(
        self,
        snapshot: dict[str, Any],
        *,
        maintenant: datetime | None = None,
    ) -> dict[str, Any]:
        maintenant = maintenant or self._current_datetime()
        derniere = self._runtime_state.get("last_auto_irrigation_reason")
        raison = derniere.get("reason") if isinstance(derniere, dict) else None
        execution = self._runtime_state.get("last_irrigation_execution")
        execution = execution if isinstance(execution, dict) else {}
        session_active = self._runtime_state.get("active_irrigation_session")
        session_active = session_active if isinstance(session_active, dict) else {}
        en_cours = self.arrosage_en_cours()
        try:
            vent_kmh: float | None = float(snapshot["vent"]) if snapshot.get("vent") is not None else None
        except (TypeError, ValueError):
            vent_kmh = None
        try:
            fin_fenetre: int | None = (
                int(float(snapshot["watering_window_end_minute"]))
                if snapshot.get("watering_window_end_minute") is not None
                else None
            )
        except (TypeError, ValueError):
            fin_fenetre = None
        zone = execution.get("last_failed_zone")
        plan_actif = session_active.get("plan")
        plan_actif = plan_actif if isinstance(plan_actif, dict) else {}
        zones_actives = plan_actif.get("zones")
        zones_actives = zones_actives if isinstance(zones_actives, list) else []
        reconciliation = execution.get("reconciliation")
        reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
        zones_executees = execution.get("zones_done")
        zones_executees = zones_executees if isinstance(zones_executees, list) else []
        ids_zones_executees = {
            str(item.get("zone") or item.get("entity_id"))
            for item in zones_executees
            if isinstance(item, dict) and (item.get("zone") or item.get("entity_id"))
        }
        action_tondeuse = snapshot.get("mower_control_pending_action")
        erreur_controleur = snapshot.get("mower_control_last_error")
        return {
            "maintenant": maintenant,
            "progression": self._semis_cycle_progress(snapshot),
            "en_cours": en_cours,
            "raison": raison,
            "fenetre": snapshot.get("fenetre_optimale"),
            "vent_kmh": vent_kmh,
            "vent_max_kmh": float(
                lire_reglage(self._reglages_instance(), "graines_vent_max", SEMIS_VENT_MAX_KMH)
            ),
            "fin_fenetre_minute": fin_fenetre,
            "motif_decision": snapshot.get("block_reason") or snapshot.get("seeding_block_reason"),
            "echec_lancement": self._refus_de_lancement_recent(maintenant),
            "verrou": self._auto_irrigation_safety_lock_active(),
            "erreur_verrou": execution.get("last_error"),
            "zone_verrou": self._nom_lisible(zone) if zone else None,
            "delai_graines": timedelta(minutes=float(lire_reglage(
                self._reglages_instance(),
                "graines_alerte_retard",
                notifications.DELAI_RETARD_GRAINES.total_seconds() / 60,
            ))),
            "mesures": self._mesures_des_sources(maintenant),
            "erreur_tondeuse": snapshot.get("tondeuse_erreur"),
            "libelle_erreur_tondeuse": snapshot.get("tondeuse_erreur_libelle"),
            "activite_arrosage": {
                "active_id": session_active.get("session_id") or session_active.get("run_id"),
                "source": session_active.get("source"),
                "target_mm": session_active.get("target_mm"),
                "zone_count": len(zones_actives),
                "started_at": session_active.get("started_at"),
                "completed_id": execution.get("session_id") or execution.get("run_id") or execution.get("ended_at"),
                "completion_status": execution.get("completion_status") or execution.get("status"),
                "executed_mm": reconciliation.get("executed_mm"),
                "zones_done": len(ids_zones_executees),
                "ended_at": execution.get("ended_at"),
            },
            "activite_tondeuse": {
                "operation": snapshot.get("mower_operation_state"),
                "docked": snapshot.get("mower_is_docked"),
                "mowing": snapshot.get("mower_is_mowing"),
                "returning": snapshot.get("mower_is_returning"),
                "error": (
                    erreur_controleur
                    if action_tondeuse in {"start_mowing", "dock"}
                    else None
                ),
            },
            "activite_garage": {
                "configured": bool(snapshot.get("mower_garage_entity")),
                "state": snapshot.get("mower_garage_state"),
                "error": (
                    erreur_controleur
                    if action_tondeuse in {"open_cover", "close_cover"}
                    else None
                ),
            },
            "sujets_actifs": notifications.sujets_voulus(self.entry),
        }

    def _mesures_des_sources(self, maintenant: datetime) -> list[Any]:
        """Chaque entrée qui mesure, lue telle que Home Assistant la voit en ce moment.

        Une entité absente de Home Assistant (renommée, supprimée) n'a pas d'horodatage : son
        absence est datée de la première fois qu'on la constate, en mémoire seulement.
        """
        absentes: dict[str, datetime] = getattr(self, "_mesures_absentes_depuis", None) or {}
        self._mesures_absentes_depuis = absentes
        mesures: list[Any] = []
        for source in sources_meteo.SOURCES:
            if not source.mesure:
                continue
            entity_id = self._get_conf(source.cle)
            if not isinstance(entity_id, str) or not entity_id:
                absentes.pop(source.cle, None)
                continue
            etat = self.hass.states.get(entity_id)
            if etat is None:
                depuis: datetime | None = absentes.setdefault(source.cle, maintenant)
            else:
                absentes.pop(source.cle, None)
                depuis = getattr(etat, "last_changed", None)
            mesures.append(notifications.mesure_d_une_entite(
                cle=source.cle,
                dans_une_phrase=source.dans_une_phrase,
                nom=self._nom_lisible(entity_id),
                etat=etat.state if etat is not None else None,
                dernier_changement=depuis,
                numerique=source.numerique,
                derniere_nouvelle_appareil=self._derniere_nouvelle_de_l_appareil(entity_id),
                maintenant=maintenant,
            ))
        return mesures

    def _derniere_nouvelle_de_l_appareil(self, entity_id: str) -> datetime | None:
        """La nouvelle la plus récente parmi les capteurs de l'appareil de `entity_id`.

        `last_reported` avance même quand la valeur ne change pas (relevés périodiques) ; à défaut,
        `last_updated`. `None` sans appareil connu, ou avec moins de deux capteurs à comparer.
        """
        try:
            from homeassistant.helpers import entity_registry as er

            registre = er.async_get(self.hass)
            entree = registre.async_get(entity_id)
            if entree is None or not getattr(entree, "device_id", None):
                return None
            voisines = er.async_entries_for_device(registre, entree.device_id)
        except Exception:  # noqa: BLE001 - sans registre, on ne juge que la valeur
            return None
        nouvelles: list[datetime] = []
        for voisine in voisines:
            if str(voisine.entity_id).split(".", 1)[0] not in ("sensor", "binary_sensor"):
                continue
            etat = self.hass.states.get(voisine.entity_id)
            if etat is None or str(etat.state).strip().lower() in sources_meteo.ETATS_SANS_VALEUR:
                continue
            quand = getattr(etat, "last_reported", None) or getattr(etat, "last_updated", None)
            if isinstance(quand, datetime):
                nouvelles.append(quand)
        return max(nouvelles) if len(nouvelles) >= 2 else None

    def _refus_de_lancement_recent(self, maintenant: datetime) -> str | None:
        """Le motif du dernier lancement refusé, s'il date de moins de 3 h (sinon il ne dit rien
        du cycle en retard)."""
        memoire = self.memory if isinstance(getattr(self, "memory", None), dict) else {}
        action = memoire.get("derniere_action_utilisateur")
        if not isinstance(action, dict) or str(action.get("state") or "").strip().lower() != "refuse":
            return None
        quand = self._parse_datetime_value(action.get("triggered_at"))
        if quand is None or abs((maintenant - quand).total_seconds()) > 3 * 3600:
            return None
        return str(action.get("reason") or "").strip() or None

    def _nom_lisible(self, entity_id: Any) -> str:
        etat = self.hass.states.get(str(entity_id)) if getattr(self, "hass", None) is not None else None
        nom = etat.attributes.get("friendly_name") if etat is not None else None
        return str(nom or entity_id)

    def _resume_du_gazon(self) -> list[str]:
        return notifications.resume_du_gazon(
            self._current_snapshot(),
            maintenant=self._current_datetime(),
            arrosage_auto=self.auto_irrigation_enabled,
            blocage="verrou de sécurité posé" if self._auto_irrigation_safety_lock_active() else None,
        )

    async def async_envoyer_notification(
        self,
        titre: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Envoie un message aux téléphones choisis ; sans message, l'état du gazon."""
        cibles = notifications.cibles_configurees(self.entry)
        if not cibles:
            raise HomeAssistantError(
                "Aucun appareil à prévenir : sélectionner une cible dans les options de Gazon Intelligent "
                "(Paramètres → Appareils et services → Gazon Intelligent → Configurer)."
            )
        texte = str(message or "").strip()
        if not texte:
            titre = titre or "🌱 État du gazon"
            texte = "\n".join(self._resume_du_gazon()) or "Aucune donnée disponible pour l'instant."
        entete = str(titre or "").strip() or "Gazon Intelligent"
        jointes = await notifications.async_envoyer(self.hass, cibles, entete, texte)
        if not jointes:
            raise HomeAssistantError(
                "Aucun appareil n'a pu être joint : vérifier les entités choisies dans les options."
            )
        return {"envoye_a": jointes, "titre": entete, "message": texte}

    async def async_demander_ia(self, question: str | None = None, *, notifier: bool = False) -> dict[str, Any]:
        """Pose une question à l'IA de la maison, avec l'état du gazon ; rend sa réponse."""
        entite = ia.entite_effective(self.hass, self.entry)
        instructions = ia.consigne(question, self._resume_du_gazon(), maintenant=self._current_datetime())
        try:
            reponse = await ia.async_demander(self.hass, instructions, entite=entite)
        except ia.IaIndisponible as err:
            raise HomeAssistantError(str(err)) from err
        resultat: dict[str, Any] = {
            "question": str(question or "").strip() or ia.QUESTION_PAR_DEFAUT,
            "reponse": reponse,
            "entite_ia": entite,
        }
        if notifier:
            cibles = notifications.cibles_configurees(self.entry)
            resultat["envoye_a"] = (
                await notifications.async_envoyer(self.hass, cibles, "🤖 Conseil pour le gazon", reponse)
                if cibles
                else []
            )
        return resultat

    def _marquer_origine_cycle(self, origine: str) -> None:
        """Note ce qui a demandé le prochain cycle. Purement descriptif.

        ⚠️ Défensif : les tests instancient le coordinateur par `object.__new__`, donc sans
        `__init__`. Une exception ici ferait tomber tout le cycle de décision pour une trace.
        """
        try:
            if getattr(self, "_cycle_origine_demandee", None) is None:
                self._cycle_origine_demandee = origine
        except Exception:  # noqa: BLE001 - une trace ne doit jamais casser une décision
            pass

    @callback
    def _handle_source_state_change(self, event: Event) -> None:
        # ⚠️ INSTRUMENTATION. `objectif_d_arrosage` est passé de 5,0 à 0,0 le 06/08/2026 avec
        # réserve, déficits, ETP, température, `depletion_ratio` et `block_reason` TOUS
        # identiques — 9 bascules en une heure, aucun `unavailable` dans la fenêtre. La sortie
        # n'est donc pas reconstructible depuis ce que le système publie. Deux passes
        # concurrentes (événement de capteur / intervalle de 2 min) sont la piste, mais rien
        # ne permettait de savoir LAQUELLE avait produit une publication donnée.
        # On mesure d'abord. Corriger sans mesurer a déjà produit de faux diagnostics ici.
        try:
            self._marquer_origine_cycle(
                f"capteur:{(event.data or {}).get('entity_id') or '?'}"
            )
        except Exception:  # noqa: BLE001
            pass
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
        try:
            self._marquer_origine_cycle(
                f"vanne:{(event.data or {}).get('entity_id') or '?'}"
            )
        except Exception:  # noqa: BLE001
            pass
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

    # ⚠️ CHEMIN MIXTE, même raison que `async_record_watering` : appelée depuis l'exécuteur
    # d'arrosage à chaque étape (en_attente, démarrage, fin, arrêt). Reste débouncée.
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
        return runtime_local_date_of(moment, as_local=as_local if callable(as_local) else None)

    def _parse_datetime_value(self, value: Any) -> datetime | None:
        return parse_datetime_value(value)

    def _new_runtime_id(self, prefix: str) -> str:
        return new_runtime_id(prefix, self._current_utc_datetime())

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
            # ⚠️ LISTE BLANCHE clé par clé : une clé absente d'ici n'est JAMAIS persistée et
            # disparaît à chaque redémarrage de Home Assistant. Le suivi de fiabilité de la
            # tondeuse (0.50.0) est un cumul de la JOURNÉE : sans persistance, il repartait de
            # zéro à chaque redémarrage — et les redémarrages sont fréquents sur cette install.
            # Constaté en relisant le state persisté juste après le déploiement de la 0.51.0 :
            # `mower_health` accumulait en mémoire et n'atteignait jamais le disque.
            "mower_health": self._serialize_runtime_value(
                self._runtime_state.get("mower_health")
            ),
            # Même piège, même remède : le carnet de passes s'accumule sur des SEMAINES.
            # Non persisté, il repartirait vide à chaque redémarrage et n'apprendrait
            # jamais rien — un carnet qui oublie est pire qu'un carnet absent.
            "mower_passes": self._serialize_runtime_value(
                self._runtime_state.get("mower_passes")
            ),
            # Anti-double-commande, temporisations du garage et dernière erreur du pilote.
            # Le bootstrap, lui, reste volontairement hors disque et repart faux à chaque boot.
            "mower_control": self._serialize_runtime_value(
                self._runtime_state.get("mower_control")
            ),
            # Même piège encore : sans persistance, un redémarrage efface la référence ET
            # l'horodatage de la dernière hausse. La garde « il pleut » repartirait alors
            # aveugle en pleine averse — précisément ce qu'elle vient de corriger.
            "pluie_mesuree": self._serialize_runtime_value(
                self._runtime_state.get("pluie_mesuree")
            ),
            # ⚠️ Le maximum ne doit JAMAIS repartir de la lecture courante : sans persistance,
            # une chute parasite suivie d'un redémarrage recompterait tout le compteur en pluie.
            "pluie_cumul": self._serialize_runtime_value(
                self._runtime_state.get("pluie_cumul")
            ),
            # Non persisté, un redémarrage remettrait le compteur de silence à zéro — or c'est
            # justement sur la DURÉE qu'il alerte, et les redémarrages sont fréquents ici.
            "mower_recommendation_ignored_since": self._serialize_runtime_value(
                self._runtime_state.get("mower_recommendation_ignored_since")
            ),
            # ⚠️ Un travail dure 4 à 5 h et traverse les recharges. Non persisté, ce suivi
            # repartirait vide au milieu — et le passage à 100 serait alors lu comme un état
            # de repos, donc AUCUNE tonte ne serait plus jamais déclarée après un redémarrage.
            "mower_job_suivi": self._serialize_runtime_value(
                self._runtime_state.get("mower_job_suivi")
            ),
            # ⚠️ Même piège, quatrième fois sur cette famille de clés. Non persisté, un
            # redémarrage en milieu de journée oublierait les travaux DÉJÀ terminés : une
            # soirée découpée en trois sorties redeviendrait indéclarable, c'est-à-dire
            # exactement le défaut que la 0.82.0 corrige. Et les redémarrages sont fréquents
            # ici. Sa jumelle vit dans `_restore_runtime_state` : les deux, ou aucune.
            "mower_travaux_termines": self._serialize_runtime_value(
                self._runtime_state.get("mower_travaux_termines")
            ),
            # Non persistée, un redémarrage relancerait le risque sur le niveau brut — et les
            # redémarrages sont fréquents ici.
            "stress_palier_et0": self._runtime_state.get("stress_palier_et0"),
            "stress_palier_et0_montee": self._serialize_runtime_value(
                self._runtime_state.get("stress_palier_et0_montee")
            ),
            "semis_meteo_ajustement": self._runtime_state.get("semis_meteo_ajustement"),
            "risque_amortissement": self._serialize_runtime_value(
                self._runtime_state.get("risque_amortissement")
            ),
            # Alertes déjà envoyées (0.93.0). Non persistée, un redémarrage renverrait l'alerte du
            # cycle en retard, et n'enverrait jamais son rattrapage. Jumelle dans la restauration.
            "alertes_gazon": self._serialize_runtime_value(
                self._runtime_state.get("alertes_gazon")
            ),
            "fungal_wetness": self._serialize_runtime_value(
                self._runtime_state.get("fungal_wetness")
            ),
            "persisted_watering_session": persisted_watering_session,
            "last_irrigation_execution_persisted": self._serialize_runtime_value(last_execution),
        }

    def _serialize_runtime_value(self, value: Any) -> Any:
        return serialize_runtime_value(value)

    def _deserialize_active_irrigation_session(self, payload: Any) -> dict[str, Any] | None:
        return deserialize_active_irrigation_session(payload, parser=self._parse_datetime_value)

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
            # Symétrique de la sérialisation : sans cette ligne le cumul du jour serait écrit
            # sur le disque puis ignoré au rechargement — pire qu'absent, car invisible.
            "mower_health": runtime.get("mower_health"),
            "mower_passes": runtime.get("mower_passes"),
            "mower_control": runtime.get("mower_control"),
            "pluie_mesuree": runtime.get("pluie_mesuree"),
            "pluie_cumul": runtime.get("pluie_cumul"),
            "mower_recommendation_ignored_since": runtime.get("mower_recommendation_ignored_since"),
            "mower_job_suivi": runtime.get("mower_job_suivi"),
            "mower_travaux_termines": runtime.get("mower_travaux_termines"),
            "risque_amortissement": runtime.get("risque_amortissement"),
            "stress_palier_et0": runtime.get("stress_palier_et0"),
            "stress_palier_et0_montee": runtime.get("stress_palier_et0_montee"),
            "semis_meteo_ajustement": runtime.get("semis_meteo_ajustement"),
            "alertes_gazon": runtime.get("alertes_gazon"),
            "fungal_wetness": runtime.get("fungal_wetness"),
        }

    def _get_active_irrigation_session(self) -> dict[str, Any] | None:
        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        session = self._runtime_state.get("active_irrigation_session")
        if not isinstance(session, dict):
            return None
        if self._is_finished_irrigation_session(session):
            status = (
                "completed"
                if session.get(WATERING_RECORDED_KEY)
                else "failed" if session.get("last_error") else "completed"
            )
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

    def _planned_zone_count_for_session(
        self,
        session: dict[str, Any],
        plan: WateringPlan | None = None,
    ) -> int:
        if plan is not None:
            return max(0, len(plan.zones))
        zones: set[str] = set()
        for key in ("zones_done", "zones_pending", "zones_failed"):
            for item in session.get(key) or []:
                if not isinstance(item, dict):
                    continue
                zone_id = item.get("zone") or item.get("entity_id")
                if zone_id:
                    zones.add(str(zone_id))
        plan_dict = session.get("plan")
        if isinstance(plan_dict, dict):
            raw_zones = plan_dict.get("zones")
            if isinstance(raw_zones, list):
                for item in raw_zones:
                    if not isinstance(item, dict):
                        continue
                    zone_id = item.get("zone") or item.get("entity_id")
                    if zone_id:
                        zones.add(str(zone_id))
        return len(zones)

    async def _record_irrigation_session_progress(
        self,
        session: dict[str, Any],
        *,
        plan: WateringPlan | None = None,
        watering_cause: str | None = None,
    ) -> dict[str, Any] | None:
        """Inscrit l'eau déjà exécutée avant de clôturer une reprise dégradée."""
        if session.get(WATERING_RECORDED_KEY):
            return None
        zones_done = [dict(z) for z in (session.get("zones_done") or []) if isinstance(z, dict)]
        if not zones_done:
            return None
        zones_prevues = self._planned_zone_count_for_session(session, plan)
        total_mm = self._round_runtime_mm(
            surface_mm_depuis_segments(zones_done, zones_prevues=zones_prevues)
        )
        if total_mm <= 0:
            return None
        source = str(session.get("source") or "auto_irrigation")
        cause = self._normalize_watering_cause(
            watering_cause if watering_cause is not None else session.get("watering_cause"),
            source=source,
        )
        session[WATERING_RECORDED_KEY] = True
        await self.async_record_watering(
            self._current_date(),
            objectif_mm=total_mm,
            total_mm=total_mm,
            zones=zones_done,
            source=source,
            started_at=session.get("started_at"),
            watering_cause=cause,
            mm_scope="global_surface",
            mm_interpretation="surface_uniform",
        )
        return {
            "date_action": self._current_date().isoformat(),
            "objectif_mm": total_mm,
            "objective_mm": total_mm,
            "total_mm": total_mm,
            "session_total_mm": total_mm,
            "zones": zones_done,
            "source": source,
            "watering_cause": cause,
            "mm_scope": "global_surface",
            "mm_interpretation": "surface_uniform",
        }

    async def _close_degraded_irrigation_session(
        self,
        session: dict[str, Any],
        *,
        status: str,
        error: str,
        plan: WateringPlan | None = None,
        watering_cause: str | None = None,
    ) -> None:
        # L'enregistrement de l'eau sauvegarde aussi le runtime. Le statut et l'erreur doivent
        # donc être posés AVANT cette première écriture : si HA redémarre juste après, la session
        # marquée comme enregistrée doit rester un échec, pas être restaurée comme « terminée ».
        session["status"] = status
        session["last_error"] = error
        recorded = await self._record_irrigation_session_progress(
            session,
            plan=plan,
            watering_cause=watering_cause,
        )
        self._persist_execution_snapshot(
            session,
            status=status,
            error=error,
            recorded_watering=recorded,
        )
        self._set_active_irrigation_session(None)
        await self._persist_runtime_state()

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
        # Des segments restent-ils à exécuter ? Si oui, le cycle N'EST PAS terminé, quelle que soit
        # la durée écoulée — sinon une coupure de HA plus longue que la durée planifiée (typiquement
        # pendant la pause inter-passages) clôturait le cycle et ABANDONNAIT le 2ᵉ passage (6 mm au
        # lieu de 12). L'heuristique « elapsed >= planned » ne vaut que pour un cycle sans travail
        # restant (session ancienne sans zones_pending → repli sur le comportement historique).
        return is_finished_irrigation_session(session, now_utc=self._current_utc_datetime())

    def _build_runtime_payload_for_event(self, session: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
        return build_runtime_payload_for_event(
            session,
            extra,
            serializer=self._serialize_runtime_value,
        )

    @staticmethod
    def _normalize_watering_cause(value: Any, *, source: str | None = None) -> str:
        # ⚠️ `arret_manuel` manquait à cette liste blanche : la cause promise par le service
        # `stop_irrigation` retombait sur « hydrique », et l'historique ne distinguait plus un
        # cycle interrompu d'un arrosage normal — la trace d'audit que le service était censé
        # laisser. Le piège des listes blanches, appliqué à la fonctionnalité qui le documente.
        return normalize_watering_cause(value, source=source, known_causes=WATERING_CAUSES)

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
        reduction_getter = getattr(self, "_zone_shade_reduction_pct", None)
        zones_cfg = [
            (
                entity_id,
                rate_mm_min * 60.0,
                reduction_getter(entity_id) if callable(reduction_getter) else 0.0,
            )
            for entity_id, rate_mm_min in self._iter_zones_with_rate()
        ]
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
        _donnees_publiees = getattr(self, "data", None)
        _plan_source: Mapping[str, Any] = (
            snapshot if isinstance(snapshot, Mapping) and "watering_passages" in snapshot
            else (_donnees_publiees if isinstance(_donnees_publiees, Mapping) else {})
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
        # `auto_irrigation_user_confirmed` a été RETIRÉE ici le 29/07/2026 (arbitrage retenu) :
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
        post_application_auto_ready = self._post_application_auto_ready(snapshot)
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
                "le sol est en déficit critique (%s). Vérifier l'état du robot — il est probablement "
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
            and fenetre in self._FENETRES_SANS_LANCEMENT
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
        # anti-relance (sinon une recharge normale récente le bloquerait, cf. demande utilisateur).
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
                delai_relance_h = float(
                    lire_reglage(
                        self._reglages_instance(),
                        "arrosage_delai_relance",
                        AUTO_IRRIGATION_RELAUNCH_COOLDOWN.total_seconds() / 3600,
                    )
                )
                if elapsed < delai_relance_h * 3600:
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
        else:
            # ÉTAPE 2 (arbitrage du 15/09/2026) : dans la fenêtre du matin, on ne part plus à
            # l'ouverture (03:45) mais pour FINIR 15 min avant le lever du soleil (cf.
            # `plan_morning_departure`). La nuit l'ET est quasi nulle : partir à 06:15 plutôt qu'à
            # 03:45 ne coûte rien au sol. Les exemptions vivent dans `_morning_departure`.
            depart = self._morning_departure(snapshot)
            if depart is not None and current_minutes < depart["departure_minute"]:
                return False, "waiting_sunrise_departure"

        return True, "ready"

    # Fenêtres où le lanceur refuse de partir (`window_unavailable`), hors exemptions.
    _FENETRES_SANS_LANCEMENT: frozenset[str] = frozenset({"", "unknown", "unavailable", "none", "attendre"})

    def _auto_irrigation_can_start(self, snapshot: dict[str, Any]) -> bool:
        """L'arrosage AUTOMATIQUE partira-t-il de lui-même ? Sinon, aucune heure à annoncer.

        Les refus DURABLES du lanceur, sans ceux qui ne tiennent qu'à l'heure : verrou de
        sécurité, interrupteur coupé, arrosage auto non autorisé (mode manuel, blocage), exécution
        refusée, fenêtre « attendre ». Revue du 15/09 : verrou actif, « Prochain arrosage » et la
        carte annonçaient « 06:15 → 07:19 » pendant que « Blocage arrosage auto » disait
        « Bloqué (sécurité) ».
        """
        if self._auto_irrigation_safety_lock_active() or not self.auto_irrigation_enabled:
            return False
        if not bool(snapshot.get("arrosage_auto_autorise")):
            return False
        if not bool(snapshot.get("irrigation_execution_allowed", True)):
            return False
        return str(snapshot.get("fenetre_optimale") or "").strip() not in self._FENETRES_SANS_LANCEMENT

    @staticmethod
    def _post_application_auto_ready(snapshot: dict[str, Any]) -> bool:
        """Incorporation post-application prête à partir en automatique."""
        type_arrosage = str(snapshot.get("type_arrosage") or "").strip().lower()
        post_status = str(snapshot.get("application_post_watering_status") or "").strip().lower()
        return (
            type_arrosage == "application_technique_auto"
            and post_status == "autorise"
            and bool(snapshot.get("arrosage_auto_autorise"))
        )

    def _morning_departure_exempt(self, snapshot: dict[str, Any]) -> bool:
        """Arrosages qui partent sans attendre l'heure calée sur le lever du soleil.

        - l'incorporation post-produit : le produit attend son eau ;
        - le rafraîchissement du soir : il a sa propre fenêtre ;
        - le semis : ses cycles espacés ont leurs propres créneaux ;
        - la tondeuse : un arrosage retenu par elle n'atteint le lancement que sous l'exception de
          détresse (sinon `irrigation_blocked` sort avant), et une détresse n'attend pas.
        """
        if str(snapshot.get("fenetre_optimale") or "").strip() == "soir":
            return True
        if self._post_application_auto_ready(snapshot):
            return True
        if self._semis_cycle_progress(snapshot) is not None:
            return True
        return bool(snapshot.get("watering_blocked_by_mower"))

    def _morning_departure(self, snapshot: dict[str, Any]) -> dict[str, int] | None:
        """Départ du matin calé sur le lever du soleil (étape 2), ou `None` s'il reste l'ouverture.

        SOURCE UNIQUE du lanceur, qui attend cette minute, et de l'affichage, qui l'annonce. Deux
        calculs finiraient par diverger : le capteur promettrait 06:15 pendant que les vannes
        s'ouvriraient à une autre heure. Les EXEMPTIONS sont donc ici aussi : quand seul le lanceur
        les connaissait, un semis qui part à l'ouverture se voyait annoncer un départ calé.
        """
        if self._morning_departure_exempt(snapshot):
            return None
        sunrise_minute = self._sunrise_minute_from_context(self._get_sun_context())
        if sunrise_minute is None:
            return None
        # Même résolution du plan que `_maybe_schedule_auto_irrigation`, donc même durée.
        plan = self._get_canonical_watering_plan(
            plan_arrosage_entity_id=self._plan_arrosage_entity_id(),
            snapshot=snapshot,
        )
        if plan is None:
            try:
                objectif_mm = float(snapshot.get("objectif_mm") or 0.0)
            except (TypeError, ValueError):
                objectif_mm = 0.0
            plan = self._get_canonical_watering_plan(objectif_mm=objectif_mm, snapshot=snapshot)
        if plan is None:
            return None
        return plan_morning_departure(
            window_start_minute=int(snapshot.get("watering_window_start_minute") or 0),
            sunrise_minute=sunrise_minute,
            # PAUSES COMPRISES : un cycle fractionné en deux passages dure bien plus que la somme
            # de ses zones (`total_duration_s`, pas `total_duration_min`, qui les ignore).
            duration_s=float(plan.total_duration_s),
            margin_minutes=int(
                lire_reglage(self._reglages_instance(), "arrosage_marge_avant_lever", WATERING_SUNRISE_MARGIN_MINUTES)
            ),
        )

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
            # Attendre l'heure calée sur le lever du soleil n'est pas un refus.
            "waiting_sunrise_departure",
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
            # après l'ouverture de la fenêtre. Signalé le 04/08/2026, vérifié sur les
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
        # ⚠️ OUBLIÉS AU PREMIER JET — relevé par la revue. Enregistrer ou retirer un produit est
        # une action utilisateur comme une autre, mais elle passe par `_async_refresh_all_coordinators`
        # qui, lui, doit rester débouncé : il touche les AUTRES instances, pas seulement la
        # sienne. On rafraîchit donc la sienne en plus, immédiatement.
        await self._rafraichir_apres_action_utilisateur()

    async def async_remove_product(self, product_id: str) -> None:
        self.brain.remove_product(product_id)
        if self.shared_state is not None:
            await self.shared_state.async_save()
        await self._async_save_state()
        await self._async_refresh_all_coordinators()
        # Même raison que `async_register_product` : action utilisateur, instance rafraîchie tout de suite.
        await self._rafraichir_apres_action_utilisateur()

    async def async_remove_last_application(self) -> None:
        self.brain.remove_last_application()
        await self._async_save_state()
        await self._rafraichir_apres_action_utilisateur()

    async def async_reset_mower_passes(self) -> None:
        """Repart d'un carnet de passes vierge.

        ⚠️ POURQUOI CE SERVICE EXISTE. Les motifs de fin sont une INTERPRÉTATION, et cette
        interprétation a déjà changé une fois : jusqu'en 0.53.1 un rappel par la coordination
        était enregistré comme une décision de la tondeuse. Les passes écrites sous l'ancienne
        règle ne portent pas le fait brut qui permettrait de les rejuger — elles sont donc
        invérifiables, et fausseraient les médianes sans qu'on puisse le voir.

        Vider le carnet est le seul moyen honnête de repartir : il n'alimente aucune décision,
        donc on ne perd rien d'autre qu'une observation qu'on ne sait plus lire.
        """
        self._runtime_state["mower_passes"] = {"en_cours": None, "journal": []}
        await self._async_save_state()
        await self._rafraichir_apres_action_utilisateur()

    async def async_run_zone_for_duration(
        self,
        zone_entity_id: str,
        *,
        duration_minutes: float = 5.0,
    ) -> None:
        """Ouvre une zone configurée pendant une durée bornée, sous contrôle du moteur.

        Cette voie sert notamment le bouton « 5 min » du panneau. Elle utilise le même
        exécuteur persistant que les cycles complets : la fermeture ne dépend donc plus du
        navigateur et une interruption de Home Assistant reprend le temps restant au démarrage.
        """
        zone_entity_id = str(zone_entity_id or "").strip()
        try:
            duration = float(duration_minutes)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("La durée d'arrosage de la zone est invalide.") from err
        if not 0.5 <= duration <= 180.0:
            raise HomeAssistantError("La durée d'arrosage doit être comprise entre 30 secondes et 3 heures.")

        zones = {entity_id: rate_mm_min for entity_id, rate_mm_min in self._iter_zones_with_rate()}
        rate_mm_min = zones.get(zone_entity_id)
        if rate_mm_min is None:
            raise HomeAssistantError(
                "Cette vanne n'est pas une zone active de cette instance de Gazon Intelligent."
            )

        GazonIntelligentCoordinator._ensure_irrigation_runtime_bootstrap(self)
        if self._irrigation_launch_lock is None:
            self._irrigation_launch_lock = asyncio.Lock()
        if self._irrigation_launch_lock.locked():
            raise HomeAssistantError("Un lancement d'arrosage est déjà en préparation.")

        async with self._irrigation_launch_lock:
            if self._auto_irrigation_safety_lock_active():
                raise HomeAssistantError(
                    "L'arrosage est verrouillé après une fermeture non confirmée."
                )
            if self._watering_session_active() or self._shared_valve_busy_elsewhere():
                raise HomeAssistantError("Un arrosage est déjà en cours.")
            auto_task = getattr(self, "_auto_irrigation_task", None)
            if auto_task is not None and not auto_task.done():
                raise HomeAssistantError("Un arrosage est déjà en cours.")

            duration_seconds = max(30, int(round(duration * 60.0)))
            objective_mm = float(rate_mm_min) * (duration_seconds / 60.0)
            plan = WateringPlan(
                objective_mm=objective_mm,
                plan_type="single_zone",
                passage_count=1,
                pause_between_passages_s=0,
                zones=(
                    ZonePlan(
                        zone=zone_entity_id,
                        rate_mm_h=float(rate_mm_min) * 60.0,
                        duration_s=duration_seconds,
                        mm=objective_mm,
                    ),
                ),
                source="manual_timed_zone",
            )
            session = self._build_active_irrigation_session(
                plan=plan,
                source="manual_timed_zone",
                strategy="timed_zone",
                watering_cause="hydrique",
            )
            pump_entity_id = self._get_conf(CONF_ENTITE_POMPE)
            if isinstance(pump_entity_id, str) and pump_entity_id.strip():
                session["managed_pump_entity_id"] = pump_entity_id.strip()
                session["managed_pump_started_by_integration"] = False

            await self.async_record_user_action(
                action="Arrosage temporisé d'une zone",
                state="en_attente",
                reason=f"Zone ouverte pour {duration:g} min, fermeture gérée par Home Assistant.",
                plan_type="single_zone",
                zone_count=1,
                passages=1,
            )
            self._auto_irrigation_task = self.hass.async_create_task(
                self._execute_canonical_watering_plan(
                    plan=plan,
                    source="manual_timed_zone",
                    strategy="timed_zone",
                    watering_cause="hydrique",
                    user_action_context={
                        "action": "Arrosage temporisé d'une zone",
                        "success_reason": "La zone a été refermée automatiquement.",
                        "plan_type": "single_zone",
                        "zone_count": 1,
                        "passages": 1,
                    },
                    session=session,
                ),
                "gazon_intelligent_timed_zone",
            )

        self.hass.bus.async_fire(
            "gazon_intelligent_manual_irrigation_requested",
            {
                "objectif_mm": round(objective_mm, 1),
                "zone": zone_entity_id,
                "duration_seconds": duration_seconds,
                "source": "manual_timed_zone",
            },
        )

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
        return current_objective_mm(self.result, getattr(self, "data", None))

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
        application_mode = str(application_state.get("application_irrigation_mode") or "").strip().lower()
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

        # Bornées par la même source que la décision : sans elle, ces deux refus duraient À VIE
        # après la moindre application foliaire ou de type inconnu (troisième copie de la règle).
        if application_state.get("application_inconnue_en_cours"):
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

        if application_state.get("application_foliaire_en_cours"):
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

    def _zone_shade_reduction_pct(self, entity_id: str | None) -> float:
        """Return the configured water reduction for this shaded zone."""
        if not entity_id:
            return 0.0
        settings = self._reglages_instance()
        for idx in range(1, 6):
            if entity_id != self._get_conf(f"zone_{idx}"):
                continue
            value = lire_reglage(settings, f"arrosage_reduction_ombre_zone_{idx}", 0.0)
            try:
                return max(0.0, min(50.0, float(value)))
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _get_zone_rate_mm_min(self, entity_id: str | None, rate_h: Any | None = None) -> float:
        if rate_h is None:
            for idx in range(1, 6):
                if entity_id == self._get_conf(f"zone_{idx}"):
                    rate_h = self._get_conf(f"debit_zone_{idx}")
                    break
        # `rate_h` peut être absent (zone non configurée) : une valeur inconnue vaut zéro →
        # zone neutralisée.
        return zone_rate_mm_min(entity_id, rate_h)

    def _get_zone_rate_mm_h(self, entity_id: str | None, rate_h: Any | None = None) -> float:
        if rate_h is None:
            for idx in range(1, 6):
                if entity_id == self._get_conf(f"zone_{idx}"):
                    rate_h = self._get_conf(f"debit_zone_{idx}")
                    break
        return zone_rate_mm_h(entity_id, rate_h)

    def _build_pending_zone_segments(self, plan: WateringPlan) -> list[dict[str, Any]]:
        # Durée/mm PAR PASSAGE (zone_for_passage), pas la dose pleine : sur un cycle
        # fractionné (passages > 1), stocker `zone.duration_s`/`zone.mm` par passage
        # surestimait chaque segment (2 passages → 2× la dose affichée dans zones_pending).
        # Inerte aujourd'hui (l'exécution, le mm crédité et la reprise recalculent tous via
        # zone_for_passage), mais c'était un piège : un futur code lisant ces valeurs pour
        # la reprise aurait double-dosé. On stocke donc la valeur réellement délivrée.
        return build_pending_zone_segments(plan)

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
        return build_zone_execution_record(
            zone=zone,
            passage=passage,
            order=order,
            effective_duration_s=effective_duration_s,
        )

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
        resolved_session_id = session_id or self._new_runtime_id("sess")
        resolved_run_id = run_id or self._new_runtime_id("irrig")
        return build_runtime_active_irrigation_session(
            plan=plan,
            source=source,
            strategy=strategy,
            watering_cause=self._normalize_watering_cause(watering_cause, source=source),
            run_id=resolved_run_id,
            session_id=resolved_session_id,
            now=now,
            zones_pending=self._build_pending_zone_segments(plan),
        )

    @staticmethod
    def _round_runtime_mm(value: Any) -> float:
        return round_runtime_mm(value)

    def _build_execution_plan_metrics(self, session: dict[str, Any]) -> dict[str, Any]:
        return build_execution_plan_metrics(session, rounder=self._round_runtime_mm)

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

    async def _ensure_managed_irrigation_pump(self, session: dict[str, Any]) -> None:
        """Démarre la pompe facultative et mémorise si ce cycle en est propriétaire."""
        pump_entity_id = str(session.get("managed_pump_entity_id") or "").strip()
        if not pump_entity_id:
            return
        state = self.hass.states.get(pump_entity_id)
        current_state = str(getattr(state, "state", "") or "").strip().lower()
        already_owned = bool(session.get("managed_pump_started_by_integration"))
        if current_state == "on":
            return
        if current_state in {"", "unknown", "unavailable"}:
            if not await self._wait_for_zones_available([pump_entity_id], timeout_s=30.0):
                raise HomeAssistantError("La pompe configurée ne répond pas.")
            state = self.hass.states.get(pump_entity_id)
            current_state = str(getattr(state, "state", "") or "").strip().lower()
            if current_state == "on":
                return
        if not already_owned:
            # Persisté AVANT la commande : une coupure juste après l'ouverture ne doit jamais
            # faire oublier que cette séquence devra aussi arrêter la pompe.
            session["managed_pump_started_by_integration"] = True
            await self._persist_runtime_state()
        try:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": pump_entity_id}, blocking=True
            )
        except Exception as err:
            raise HomeAssistantError(f"Echec démarrage pompe {pump_entity_id}: {err}") from err

    async def _safe_turn_off_managed_irrigation_pump(self, session: dict[str, Any]) -> bool:
        """Arrête uniquement une pompe démarrée par ce cycle, avec verrou en cas d'échec."""
        pump_entity_id = str(session.get("managed_pump_entity_id") or "").strip()
        if not pump_entity_id or not bool(session.get("managed_pump_started_by_integration")):
            return True
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                await asyncio.shield(
                    self.hass.services.async_call(
                        "switch", "turn_off", {"entity_id": pump_entity_id}, blocking=True
                    )
                )
                session["managed_pump_started_by_integration"] = False
                await self._persist_runtime_state()
                return True
            except Exception as err:  # pragma: no cover - safety path
                last_error = err
                if attempt < 2:
                    await asyncio.sleep(0.2)
        message = f"Echec arrêt pompe {pump_entity_id}: {last_error}"
        session["status"] = "failed"
        session["last_error"] = message
        session["last_update"] = self._current_utc_datetime()
        session["last_activity_at"] = session["last_update"]
        self._persist_execution_snapshot(session, status="failed", error=message)
        await self._set_irrigation_safety_lock(message, pump_entity_id)
        self._emit_irrigation_event(
            "gazon_intelligent_auto_irrigation_failed",
            self._build_runtime_payload_for_event(
                session,
                failed_zone=pump_entity_id,
                error=message,
                shutdown_uncertain=True,
            ),
        )
        return False

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
            self._build_runtime_payload_for_event(
                runtime_session,
                target_mm=plan.planned_surface_mm,
                reference_objective_mm=plan.objective_mm,
            ),
        )
        error_reason: str | None = None
        cancelled = False
        execution_completed = False
        executed_zones: list[dict[str, Any]] = list(runtime_session.get("zones_done") or [])
        # Suspend le moniteur passif de sessions pendant tout le cycle piloté (passages ET
        # pauses) : c'est ce cycle qui enregistre l'arrosage (source auto/manuel). Sans ça,
        # le moniteur passif finalise un doublon `zone_session` à chaque pause inter-passage
        # (la garde _zone_tracking_suspended était déclarée mais jamais armée → l'arrosage
        # était compté plusieurs fois, sur-créditant la réserve et le budget hebdo).
        self._zone_tracking_suspended += 1
        managed_pump_closed = True
        try:
            await GazonIntelligentCoordinator._ensure_managed_irrigation_pump(
                self, runtime_session
            )
            start_passage = max(1, int(runtime_session.get("current_passage") or 1))
            start_zone_index = max(0, int(runtime_session.get("current_zone_index") or 0))
            # Reprise après redémarrage : temps restant à appliquer à la 1ʳᵉ zone reprise
            # (calculé dans _resume_active_irrigation_session, vanne restée ouverte incluse).
            resume_remaining_s = runtime_session.pop("resume_zone_remaining_s", None)
            resume_elapsed_s = runtime_session.pop("resume_zone_elapsed_s", 0.0)
            for passage in range(start_passage, plan.passage_count + 1):
                runtime_session["status"] = "running"
                runtime_session["current_passage"] = passage
                if passage != start_passage:
                    start_zone_index = 0
                for zone_index, zone in enumerate(plan.zones[start_zone_index:], start=start_zone_index):
                    zone_segment = plan.zone_for_passage(zone_index, passage)
                    sleep_duration_s = float(zone_segment.duration_s)
                    resume_prior_s = 0.0
                    if resume_remaining_s is not None and passage == start_passage and zone_index == start_zone_index:
                        # On ne ré-arrose que le temps restant de la zone interrompue.
                        try:
                            sleep_duration_s = max(0.0, float(resume_remaining_s))
                        except (TypeError, ValueError):
                            sleep_duration_s = float(zone_segment.duration_s)
                        try:
                            resume_prior_s = max(0.0, float(resume_elapsed_s or 0.0))
                        except (TypeError, ValueError):
                            resume_prior_s = 0.0
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
                        effective_duration_s=min(
                            float(zone_segment.duration_s),
                            resume_prior_s + ouverte_s,
                        ),
                    )
                    executed_zones.append(record)
                    runtime_session["zones_done"] = executed_zones
                    runtime_session["zones_pending"] = [
                        pending
                        for pending in runtime_session.get("zones_pending", [])
                        if not is_matching_zone_segment(
                            pending,
                            passage=passage,
                            zone_index=zone_index,
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
            surface_mm = plan.planned_surface_mm
            # ⚠️ LE PLAN N'EST PAS L'EXÉCUTION. La proratisation posée sur `zones_done` quand
            # un relais retombe (`_build_zone_execution_record`) ne servait à rien ici : on
            # enregistrait quand même l'objectif PRÉVU. L'historique, le bilan du sol et le
            # budget hebdomadaire créditaient donc l'eau qui n'a pas coulé, et le système
            # sous-arrosait ensuite — exactement ce que la surveillance de vanne devait éviter.
            # On ne descend QUE s'il manque vraiment de l'eau (marge de 0,1 mm) : la voie
            # nominale garde l'objectif exact, sans bruit d'arrondi.
            surface_executee = surface_mm_depuis_segments(
                executed_zones, zones_prevues=len(plan.zones)
            )
            if surface_executee + 0.1 < surface_mm:
                _LOGGER.info(
                    "Cycle partiel : %.1f mm réellement délivrés sur %.1f mm prévus — "
                    "c'est la valeur exécutée qui est enregistrée",
                    surface_executee, surface_mm,
                )
                surface_mm = round(surface_executee, 1)
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
                "mm_scope": (
                    "surface_cycle" if semis_strategy
                    else "zone_adjusted_surface" if plan.has_zone_adjustments
                    else "global_surface"
                ),
                "mm_interpretation": (
                    "surface_cycle" if semis_strategy
                    else "zone_adjusted" if plan.has_zone_adjustments
                    else "surface_uniform"
                ),
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
            # Marqueur posé AVANT l'appel, pas après : `brain.record_watering` s'exécute avant le
            # premier `await` d'`async_record_watering`, et `_async_save_state` écrit historique et
            # session dans le même fichier. Aucune sauvegarde ne peut donc contenir le marqueur sans
            # l'eau. Posé après, un arrêt pendant cette sauvegarde réenregistrerait le cycle.
            runtime_session[WATERING_RECORDED_KEY] = True
            await self.async_record_watering(
                self._current_date(),
                objectif_mm=surface_mm,
                total_mm=surface_mm,
                zones=executed_zones,
                source=source,
                # ⚠️ Le correctif d'horodatage du 04/08/2026 n'avait été branché que sur la voie
                # de DÉTECTION (`_finalize_watering_session`). Sur cette voie-ci, celle des
                # cycles PILOTÉS par l'intégration — donc l'arrosage automatique de tous les
                # matins — l'historique ne recevait toujours que l'instant de fin, et
                # l'affichage annonçait « arrosé à 05:18 » pour un cycle parti à 03:45:13.
                # Un correctif livré mais non exécuté est pire qu'un correctif absent : on le
                # croit fait.
                started_at=runtime_session.get("started_at"),
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
            execution_completed = True
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
            managed_pump_closed = (
                await GazonIntelligentCoordinator._safe_turn_off_managed_irrigation_pump(
                    self, runtime_session
                )
            )
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
            if not cancelled and managed_pump_closed:
                if str(source or "") == "auto_irrigation":
                    # Arme le cooldown anti-relance : un cycle auto vient de se terminer.
                    self._runtime_state["last_auto_irrigation_completed_at"] = self._current_utc_datetime()
                self._set_active_irrigation_session(None)
                await self._persist_runtime_state()
                if execution_completed and user_action_context:
                    await self.async_record_user_action(
                        action=str(user_action_context.get("action")),
                        state="ok",
                        reason=str(
                            user_action_context.get("success_reason")
                            or "Arrosage terminé avec succès."
                        ),
                        plan_type=user_action_context.get("plan_type"),
                        zone_count=user_action_context.get("zone_count"),
                        passages=user_action_context.get("passages"),
                    )
            elif not cancelled and execution_completed and user_action_context:
                await self.async_record_user_action(
                    action=str(user_action_context.get("action")),
                    state="refuse",
                    reason=str(
                        runtime_session.get("last_error")
                        or "La pompe n'a pas pu être arrêtée."
                    ),
                    plan_type=user_action_context.get("plan_type"),
                    zone_count=user_action_context.get("zone_count"),
                    passages=user_action_context.get("passages"),
                )

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
            await self._close_degraded_irrigation_session(
                session,
                status="failed",
                error="Plan persistant invalide.",
            )
            return

        # Attendre que l'appareil d'arrosage (vannes) soit disponible avant toute action :
        # au boot, la vanne est restée ouverte mais l'entité HA est 'unavailable' un instant.
        if not await self._wait_for_zones_available([getattr(z, "zone", None) for z in (plan.zones or [])]):
            await self._close_degraded_irrigation_session(
                session,
                status="failed",
                error="device_unavailable_on_resume",
                plan=plan,
            )
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
                session["resume_zone_elapsed_s"] = max(0.0, target_s - remaining_s)
                session["status"] = "running"
            else:
                # La zone a reçu sa dose (voire plus) pendant l'indisponibilité → on la ferme
                # proprement et on passe à la suivante.
                try:
                    await self._safe_turn_off_zone(current_zone, session)
                except HomeAssistantError:
                    await self._close_degraded_irrigation_session(
                        session,
                        status="failed",
                        error=str(session.get("last_error") or "restart_recovery_shutdown_uncertain"),
                        plan=plan,
                    )
                    return
                record = self._build_zone_execution_record(
                    zone=plan.zone_for_passage(zone_index, passage),
                    passage=passage,
                    order=len(session.get("zones_done") or []) + 1,
                    effective_duration_s=target_s,
                )
                record["recovered_during_downtime"] = True
                session.setdefault("zones_done", []).append(record)
                session["zones_pending"] = [
                    pending
                    for pending in session.get("zones_pending", [])
                    if not is_matching_zone_segment(
                        pending,
                        passage=passage,
                        zone_index=zone_index,
                    )
                ]
                session["status"] = "recovery_required"
                session["active_zones"] = []
                session["current_zone"] = None
                session["current_zone_started_at"] = None
                session["current_zone_index"] = zone_index + 1

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
        if bool(session.get("managed_pump_started_by_integration")) and (
            self._is_finished_irrigation_session(session)
            or self._auto_irrigation_safety_lock_active()
        ):
            # Une coupure peut tomber après la dernière vanne mais avant l'arrêt de la pompe.
            # La pompe est donc traitée AVANT qu'une session terminée soit purgée.
            pump_closed = (
                await GazonIntelligentCoordinator._safe_turn_off_managed_irrigation_pump(
                    self, session
                )
            )
            if not pump_closed:
                return
        if self._is_finished_irrigation_session(session):
            status = (
                "completed"
                if session.get(WATERING_RECORDED_KEY)
                else "failed" if session.get("last_error") else "completed"
            )
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
            await self._close_degraded_irrigation_session(
                session,
                status="failed",
                error="safety_lock_active",
            )
            return
        if (
            not self.auto_irrigation_enabled
            and str(session.get("source") or "") in AUTO_IRRIGATION_AUTO_SOURCES
        ):
            # L'arrosage automatique a été COUPÉ avant ce redémarrage : reprendre le cycle
            # reviendrait à passer outre une décision explicite. La reprise ne consultait pas
            # ce drapeau — un cycle interrompu repartait donc tout seul, auto désactivé.
            # Une session MANUELLE, elle, reste légitime : l'utilisateur l'a demandée.
            await self._close_degraded_irrigation_session(
                session,
                status="cancelled",
                error="auto_irrigation_disabled",
            )
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
        raw_session = self._runtime_state.get("active_irrigation_session")
        task: asyncio.Task[Any] | None = getattr(self, "_auto_irrigation_task", None)
        task_vivante = task is not None and not task.done()
        if (
            task_vivante
            and isinstance(raw_session, dict)
            and raw_session.get(WATERING_RECORDED_KEY)
            and not raw_session.get("current_zone")
            and not raw_session.get("active_zones")
        ):
            zones_finalisees = [
                dict(z) for z in (raw_session.get("zones_done") or []) if isinstance(z, dict)
            ]
            applique_mm = self._round_runtime_mm(
                surface_mm_depuis_segments(
                    zones_finalisees,
                    zones_prevues=self._planned_zone_count_for_session(raw_session),
                )
            )
            assert task is not None
            finalization_pending = False
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=_STOP_FINALIZATION_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                finalization_pending = True
                _LOGGER.warning(
                    "Arrêt d'arrosage : la finalisation dépasse %.0f s et continue en arrière-plan",
                    _STOP_FINALIZATION_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                # `shield` empêche l'annulation de l'appelant de tuer la finalisation. Si la
                # tâche interne ne s'est pas elle-même annulée, l'annulation reçue appartient à
                # l'appel Home Assistant et doit remonter.
                if not task.cancelled():
                    raise
            except Exception:  # pragma: no cover - la tâche a déjà journalisé son échec
                _LOGGER.debug(
                    "Arrêt d'arrosage : finalisation terminée en erreur",
                    exc_info=True,
                )
            await self.async_record_user_action(
                action="stop_irrigation",
                state="ok",
                reason=f"Cycle déjà en finalisation. {applique_mm:.1f} mm déjà appliqués.",
            )
            await self._rafraichir_apres_action_utilisateur()
            return {
                "stopped": True,
                "applied_mm": applique_mm,
                "zone_count": len(zones_finalisees),
                "interrupted_zone": None,
                "finalization_pending": finalization_pending,
            }

        session = self._get_active_irrigation_session()

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

        # ⚠️ Dose SURFACE, pas cumul brut. Sommer les segments donnait la lame × le nombre
        # de zones : trois zones à 5 mm enregistraient 15 mm alors que chaque carré d'herbe
        # en avait reçu 5. Le bilan du sol se croyait crédité au triple et le système
        # sous-arrosait ensuite. Les trois autres voies disent déjà la même chose que ce
        # helper — fin de cycle normale (`plan.objective_mm`), affichage temps réel
        # (`compute_live_session_water`) et `_zone_session_surface_mm` ; seule celle-ci
        # divergeait.
        # Zones du PLAN, pas seulement celles qui ont tourné : arrêter après la première de
        # trois ne verse pas 5 mm sur la pelouse, deux tiers du gazon n'ont rien reçu. Sans ce
        # diviseur le bilan du sol était crédité au triple, et les zones restées sèches —
        # celles qui ont le plus soif — attendaient d'autant plus.
        zones_du_plan = {
            str(z.get("zone") or z.get("entity_id") or "")
            for z in (zones_faites + list(instantane.get("zones_pending") or []))
            if isinstance(z, dict) and (z.get("zone") or z.get("entity_id"))
        }
        applique_mm = self._round_runtime_mm(
            surface_mm_depuis_segments(zones_faites, zones_prevues=len(zones_du_plan))
        )

        # UNE SEULE SAUVEGARDE pour la session effacée ET l'eau déjà versée. La session est
        # effacée en mémoire, puis `async_record_watering` écrit l'historique et le runtime
        # ensemble (même `_async_save_state`, cf. C1). Enregistrer l'eau AVANT d'effacer laissait
        # sur disque une session active avec son eau : un redémarrage entre les deux reprenait les
        # zones restantes (D1). Sauvegarder la session effacée PUIS l'eau ouvrait la fenêtre
        # inverse : ni session ni eau, l'arrêt était perdu. Sans eau, la session seule.
        self._set_active_irrigation_session(None)
        self._auto_irrigation_task = None

        if applique_mm <= 0:
            await self._persist_runtime_state()
        else:
            try:
                # `source` conservé (auto_irrigation / manual…) pour que les garde-fous existants
                # comptent cette eau comme n'importe quelle autre ; c'est `watering_cause` qui
                # porte l'information « cycle interrompu ».
                await self.async_record_watering(
                    self._current_date(),
                    objectif_mm=applique_mm,
                    total_mm=applique_mm,
                    zones=zones_faites,
                    source=source,
                    # Même correctif que sur la voie pilotée : un cycle interrompu a bien eu un
                    # début, et c'est lui qui doit figurer dans l'historique.
                    started_at=instantane.get("started_at"),
                    watering_cause="arret_manuel",
                    mm_scope="global_surface",
                    mm_interpretation="surface_uniform",
                )
            except Exception:
                # L'eau n'a pas pu être écrite : sauver au moins l'arrêt. Sinon le disque garde la
                # session active et le prochain démarrage rouvrirait les zones restantes.
                await self._persist_runtime_state()
                raise

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
        await self._rafraichir_apres_action_utilisateur()
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
                if is_matching_zone_segment(s, passage=passage, zone_index=zone_index)
                and str(s.get("zone")) == str(zone)
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

    def _reglages_instance(self) -> dict[str, Any]:
        """Les réglages de la page « Gazon » pour CETTE instance, nettoyés (`reglages.nettoyer`).

        Relus dans les options à chaque appel : une écriture depuis la page s'applique au cycle
        suivant, sans recharger l'intégration (`_async_update_listener` ne recharge que si un
        capteur source change). Le nettoyage n'est refait que si le contenu brut a changé.
        """
        entry: Any = getattr(self, "entry", None)
        try:
            entry = self.hass.config_entries.async_get_entry(entry.entry_id) or entry
        except AttributeError:
            pass
        options = getattr(entry, "options", None)
        brut = options.get(CONF_REGLAGES) if isinstance(options, Mapping) else None
        cache = getattr(self, "_reglages_cache", None)
        if cache is not None and cache[0] == brut:
            return cache[1]
        propres = nettoyer_reglages(brut)
        self._reglages_cache = (dict(brut) if isinstance(brut, Mapping) else brut, propres)
        return propres

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
        await self._rafraichir_apres_action_utilisateur()
        await self.async_start_source_monitoring()
        await self.async_start_zone_monitoring()
        await self._rafraichir_apres_action_utilisateur()

    async def async_changer_entrees(self, changements: Mapping[str, Any]) -> bool:
        """Branche ou retire des entrées depuis la page « Gazon » (0.95.0). Rend vrai si
        l'intégration va se recharger.

        Même résultat que le formulaire « Configurer », dans cet ordre :
        1. les entrées météo PARTAGÉES d'abord, pour que l'autre pelouse en hérite et que le
           rechargement qui suit les voie déjà ;
        2. les options de l'entrée. Une entrée retirée l'est aussi de la configuration d'origine :
           sinon elle y reprendrait sa place (priorité options > partagé > configuration d'origine) ;
        3. `_async_update_listener` recharge l'entrée si une entrée surveillée a changé.

        ⚠️ `async_update_config` n'est PAS utilisée ici : elle relance la surveillance de ce
        coordinateur pendant que l'écriture des options déclenche son rechargement. Croisés, les
        deux laisseraient des minuteries sur un coordinateur arrêté — donc des cycles doublés.
        """
        changements = dict(changements)
        if not changements:
            return False
        hass = self.hass
        entry = hass.config_entries.async_get_entry(self.entry.entry_id) or self.entry
        partagees = {cle: valeur for cle, valeur in changements.items() if cle in SHARED_WEATHER_CONFIG_KEYS}
        shared_state = getattr(self, "shared_state", None)
        if shared_state is not None and partagees:
            await shared_state.async_update_shared_config(partagees)
        mise_a_jour: dict[str, Any] = {"options": {**entry.options, **changements}}
        a_retirer = [
            cle for cle, valeur in changements.items()
            if valeur is None and entry.data.get(cle) not in (None, "", [], {})
        ]
        if a_retirer:
            mise_a_jour["data"] = {**entry.data, **dict.fromkeys(a_retirer)}
        hass.config_entries.async_update_entry(entry, **mise_a_jour)
        recharge = self.source_config_changed()
        if partagees:
            # L'autre pelouse lit peut-être la même valeur partagée.
            for autre in list((hass.data.get(DOMAIN) or {}).values()):
                if autre is self or not isinstance(autre, GazonIntelligentCoordinator):
                    continue
                if autre.source_config_changed():
                    hass.async_create_task(hass.config_entries.async_reload(autre.entry.entry_id))
                else:
                    hass.async_create_task(autre.async_request_refresh())
        if not recharge:
            # Entrée lue à chaque cycle sans être surveillée (compteur, pluie en ce moment) :
            # un cycle tout de suite suffit.
            await self._rafraichir_apres_action_utilisateur()
        return recharge

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
