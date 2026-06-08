from __future__ import annotations

"""Logique pure liée à la tonte."""

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from .const import (
    DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
)
from .decision_models import DecisionContext
from .guidance import compute_tonte_statut, is_active_rain_weather
from .memory import compute_application_state
from .scores import classify_stress_level
from .water import _watering_item_matches_zones

_MOWER_STEP_CM = 0.5
_MOWING_BLOCK_PRIORITIES = {
    "post_application_active": 1,
    "watering_in_progress": 2,
    "watering_cooldown": 3,
    "mowing_spacing": 4,
    "mowing_night": 5,
    "phase": 10,
    "pluie_active": 20,
    "vent_fort": 21,
    "hauteur_trop_faible": 30,
    "regle_tiers_impossible": 31,
    "regle_tiers": 32,
    "rosee": 40,
    "humidite_elevee": 50,
    "pluie_recente": 51,
    "pluie_proche": 52,
    "pluie_annoncee": 53,
    "sol_humide_post_arrosage": 54,
    "stress_thermique": 60,
    "conditions_defavorables": 70,
}
_MOWING_FREQUENCY_BY_MONTH = {
    1: (0.0, "0 / semaine"),
    2: (0.0, "0 / semaine"),
    3: (2.5, "2 à 3 / semaine"),
    4: (2.5, "2 à 3 / semaine"),
    5: (5.0, "4 à 6 / semaine"),
    6: (5.0, "4 à 6 / semaine"),
    7: (3.0, "2 à 4 / semaine"),
    8: (3.0, "2 à 4 / semaine"),
    9: (5.0, "4 à 6 / semaine"),
    10: (5.0, "4 à 6 / semaine"),
    11: (1.5, "1 à 2 / semaine"),
    12: (0.0, "0 / semaine"),
}
_MOWING_WINDOW_LABELS = {
    "ideal": "Fenêtre idéale",
    "acceptable": "Fenêtre acceptable",
    "discouraged": "À éviter",
    "blocked": "Bloqué",
}
_MOWING_WINDOW_IDEAL_START = 10
_MOWING_WINDOW_IDEAL_END = 12
_MOWING_WINDOW_ACCEPTABLE_START = 17
_MOWING_WINDOW_ACCEPTABLE_END = 19
_MOWING_WINDOW_NIGHT_END = 22
_MOWING_WINDOW_DISCOURAGED_WIND = 20
_MOWING_WINDOW_BLOCK_WIND = 40
_MOWING_WINDOW_DISCOURAGED_TEMP_MIN = 25
_MOWING_WINDOW_BLOCK_TEMP_MIN = 30
_MOWING_WINDOW_BLOCK_HUMIDITY = 90
_MOWING_BUNDLE_CORE_KEYS = (
    "tonte_autorisee",
    "tonte_statut",
    "tonte_reason",
    "raison_blocage_code",
    "next_mowing_date",
    "next_mowing_display",
    "score_tonte",
    "score_stress",
    "hauteur_tonte_recommandee_cm",
    "hauteur_tonte_min_cm",
    "hauteur_tonte_max_cm",
    "mowing_blocked_by_watering",
    "mowing_blocked",
    "mowing_block_reason_code",
    "mowing_block_reason_label",
    "mowing_cooldown_remaining_minutes",
    "mowing_post_application_active",
    "mowing_is_overdue",
    "mowing_overdue_days",
    "mowing_overdue_factor",
    "gazon_hauteur_estimee_cm",
    "mowing_watering_coordination",
    "mowing_watering_coordination_msg",
)
_OVERDUE_SOFT_OVERRIDE_CODES = {"conditions_defavorables", "stress_thermique"}


def _mowing_height_settings(context: DecisionContext) -> tuple[float, float, float]:
    """Retourne les bornes et le pas de la tondeuse, avec valeurs sûres par défaut."""
    min_height = context.hauteur_min_tondeuse_cm
    max_height = context.hauteur_max_tondeuse_cm
    try:
        min_height = float(min_height) if min_height is not None else DEFAULT_HAUTEUR_MIN_TONDEUSE_CM
    except (TypeError, ValueError):
        min_height = DEFAULT_HAUTEUR_MIN_TONDEUSE_CM
    try:
        max_height = float(max_height) if max_height is not None else DEFAULT_HAUTEUR_MAX_TONDEUSE_CM
    except (TypeError, ValueError):
        max_height = DEFAULT_HAUTEUR_MAX_TONDEUSE_CM

    if min_height > max_height:
        min_height, max_height = max_height, min_height
    min_height = _round_to_step(min_height)
    max_height = _round_to_step(max_height)
    if min_height > max_height:
        min_height, max_height = max_height, min_height
    return min_height, max_height, _MOWER_STEP_CM


def _round_to_step(value: float) -> float:
    """Arrondit à 0,5 cm près."""
    return round(round(value / _MOWER_STEP_CM) * _MOWER_STEP_CM, 2)


def _seasonal_base_height(month: int) -> float:
    """Retourne une hauteur de coupe prudente selon la saison."""
    if month in {1, 2, 11, 12}:
        return 5.0
    if month in {3, 4}:
        return 5.8
    if month in {5, 6}:
        return 5.0
    if month in {7, 8}:
        return 6.2
    if month in {9, 10}:
        return 5.0
    return 5.5


def _seasonal_mowing_frequency(month: int) -> tuple[float, str]:
    return _MOWING_FREQUENCY_BY_MONTH.get(month, (3.0, "2 à 4 / semaine"))


def _phase_adjusted_mowing_frequency(
    phase_bundle: dict[str, Any],
    month: int,
) -> tuple[float, str]:
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")
    if phase_dominante != "Sursemis":
        return _seasonal_mowing_frequency(month)
    if sous_phase in {"Germination", "Enracinement"}:
        return 0.0, "0 / semaine"
    if sous_phase == "Reprise":
        return 1.0, "1 / semaine"
    if sous_phase == "Stabilisation":
        return 2.0, "2 / semaine"
    return 1.0, "1 / semaine"


_SURSEMIS_MOWING_BLOCKED_SUBPHASES = {"Germination", "Enracinement"}


def _mowing_window_label(state: str) -> str:
    return _MOWING_WINDOW_LABELS.get(str(state or "").strip().lower(), "À éviter")


def _round_up_to_step(value: float, minimum: float, step: float) -> float:
    """Arrondit vers le haut en respectant un pas donné."""
    if step <= 0:
        return round(value, 2)
    if value <= minimum:
        return round(minimum, 2)
    steps = math.ceil((value - minimum) / step - 1e-9)
    return round(minimum + (steps * step), 2)


def _round_down_to_step(value: float, minimum: float, step: float) -> float:
    """Arrondit vers le bas en respectant un pas donné."""
    if step <= 0:
        return round(value, 2)
    if value <= minimum:
        return round(minimum, 2)
    steps = math.floor((value - minimum) / step + 1e-9)
    return round(minimum + (steps * step), 2)


def _previous_recommended_height(context: DecisionContext) -> float | None:
    """Retourne la dernière hauteur recommandée persistée si elle existe."""
    memory = context.memory or {}
    value = memory.get("hauteur_tonte_recommandee_cm")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _last_sursemis_age_days(context: DecisionContext) -> int | None:
    """Estime l'âge du dernier sursemis pour piloter la reprise progressive."""
    for item in reversed(context.history):
        if item.get("type") != "Sursemis":
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            return max((context.today - date.fromisoformat(str(raw_date))).days, 0)
        except ValueError:
            continue
    return None


def _parse_history_timestamp(item: dict[str, Any], today: date) -> datetime:
    """Retourne le meilleur horodatage disponible pour une entrée d'historique."""
    candidates = (
        item.get("ended_at"),
        item.get("started_at"),
        item.get("recorded_at"),
        item.get("detected_at_utc"),
        item.get("detected_at"),
        item.get("triggered_at"),
        item.get("last_watering_when"),
        item.get("declared_at"),
    )
    for raw in candidates:
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    raw_date = item.get("date_action") or item.get("date")
    if raw_date:
        try:
            parsed_date = date.fromisoformat(str(raw_date))
        except ValueError:
            parsed_date = today
    else:
        parsed_date = today
    return datetime.combine(parsed_date, time(6, 0), tzinfo=timezone.utc)


def _configured_zone_ids(context: DecisionContext) -> tuple[str, ...]:
    config = context.config if isinstance(context.config, dict) else {}
    raw_zone_ids = config.get("configured_zone_ids")
    if not isinstance(raw_zone_ids, (list, tuple, set)):
        return ()
    return tuple(
        str(zone_id).strip()
        for zone_id in raw_zone_ids
        if str(zone_id).strip()
    )


def _latest_watering_timestamp(context: DecisionContext) -> datetime:
    """Retourne l'horodatage du dernier arrosage détecté ou la date du jour."""
    allowed_zone_ids = _configured_zone_ids(context)
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    last_execution = runtime_context.get("last_irrigation_execution")
    if isinstance(last_execution, dict) and _watering_item_matches_zones(last_execution, allowed_zone_ids):
        parsed = _parse_history_timestamp(last_execution, context.today)
        if parsed:
            return parsed
    for item in reversed(context.history):
        if item.get("type") != "arrosage" or not _watering_item_matches_zones(item, allowed_zone_ids):
            continue
        return _parse_history_timestamp(item, context.today)
    return datetime.combine(context.today, time(6, 0), tzinfo=timezone.utc)


def _active_irrigation_session(context: DecisionContext) -> dict[str, Any] | None:
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    session = runtime_context.get("active_irrigation_session")
    if not isinstance(session, dict):
        return None
    if session.get("status") in {"completed", "cancelled", "failed"}:
        return None
    return session


def _mowing_cooldown_state(context: DecisionContext) -> tuple[bool, int]:
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    raw_minutes = runtime_context.get("mowing_cooldown_after_watering_minutes", 0)
    try:
        cooldown_minutes = max(0, int(float(raw_minutes)))
    except (TypeError, ValueError):
        cooldown_minutes = 0
    if cooldown_minutes <= 0:
        return False, 0

    latest_watering = _latest_watering_timestamp(context)
    reference_hour = context.hour_of_day if context.hour_of_day is not None else 6
    now_dt = datetime.combine(context.today, time(reference_hour % 24, 0), tzinfo=timezone.utc)
    elapsed_minutes = max(0, int((now_dt - latest_watering).total_seconds() // 60))
    remaining_minutes = max(0, cooldown_minutes - elapsed_minutes)
    return remaining_minutes > 0, remaining_minutes


def _has_recent_watering_history(context: DecisionContext) -> bool:
    allowed_zone_ids = _configured_zone_ids(context)
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    last_execution = runtime_context.get("last_irrigation_execution")
    if isinstance(last_execution, dict) and _watering_item_matches_zones(last_execution, allowed_zone_ids):
        return True
    return any(
        isinstance(item, dict)
        and item.get("type") == "arrosage"
        and _watering_item_matches_zones(item, allowed_zone_ids)
        for item in context.history
    )


def _upcoming_watering_coordination(
    context: DecisionContext,
    water_bundle: dict[str, Any],
) -> tuple[str, str | None]:
    """Retourne (niveau, message) si un arrosage est prévu et pas encore fait.

    niveau : "block" (< 30 min), "discourage" (< 2 h), ou "none".
    Message None si aucune action recommandée.
    """
    if not water_bundle.get("arrosage_recommande", False):
        return "none", None
    if _has_recent_watering_history(context):
        return "none", None
    start_minute = water_bundle.get("watering_window_start_minute")
    if start_minute is None:
        return "none", None
    current_minute = (context.hour_of_day or 0) * 60
    minutes_until = int(start_minute) - current_minute
    if minutes_until <= 0:
        # La fenêtre a déjà démarré ou est passée — arrosage peut survenir à tout moment
        return "discourage", "Arrosage recommandé ce matin — arrose avant de tondre si possible."
    if minutes_until <= 30:
        return "block", (
            f"Arrosage imminent dans ~{minutes_until} min: "
            "inutile de tondre maintenant, attends la fin de l'arrosage."
        )
    if minutes_until <= 120:
        h, m = divmod(minutes_until, 60)
        time_str = f"{h}h{m:02d}" if h > 0 else f"{m} min"
        return "discourage", f"Arrosage prévu dans ~{time_str} — tonds avant ou patiente après."
    return "none", None


def _watering_related_mowing_block(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> tuple[bool, str | None, str | None]:
    if not _has_recent_watering_history(context):
        return False, None, None

    latest_watering = _latest_watering_timestamp(context)
    reference_hour = context.hour_of_day if context.hour_of_day is not None else 6
    now_dt = datetime.combine(context.today, time(reference_hour % 24, 0), tzinfo=timezone.utc)
    elapsed_minutes = max(0, int((now_dt - latest_watering).total_seconds() // 60))
    ressuyage_hours = _estimate_mowing_ressuyage_hours(context, phase_bundle, water_bundle)
    ressuyage_minutes = int(ressuyage_hours * 60)
    if elapsed_minutes < ressuyage_minutes:
        remaining_h = max(1, (ressuyage_minutes - elapsed_minutes) // 60)
        return True, "recent_watering", f"Arrosage récent: attendre encore ~{remaining_h}h avant de tondre."

    humidite_sol = water_bundle["advanced_context"].get("humidite_sol")
    if humidite_sol is None:
        humidite_sol = context.humidite_sol
    if humidite_sol is not None:
        try:
            humidite_sol_value = float(humidite_sol)
        except (TypeError, ValueError):
            humidite_sol_value = None
        if humidite_sol_value is not None and humidite_sol_value >= 70:
            return True, "soil_wet", "Sol humide: attendre le ressuyage."

    if float(context.humidite or 0.0) >= _MOWING_WINDOW_BLOCK_HUMIDITY:
        return True, "soil_wet", "Sol humide: attendre le ressuyage."

    return False, None, None


def _resolve_mowing_window(
    context: DecisionContext,
    *,
    weather_profile: dict[str, Any],
) -> tuple[str, str | None]:
    hour = context.hour_of_day
    if hour is None:
        return "blocked", "Heure de tonte inconnue."

    temperature = float(context.temperature or 0.0)
    vent = float(context.vent or 0.0)
    rosee = context.rosee
    month = context.today.month

    if is_active_rain_weather(weather_profile):
        return "blocked", "Pluie en cours ou imminente."
    if rosee is not None and float(rosee) > 0:
        return "blocked", "Rosée présente: attendre le ressuyage du feuillage."
    if temperature < 8:
        return "blocked", "Température trop basse pour tondre."
    if temperature > _MOWING_WINDOW_BLOCK_TEMP_MIN:
        return "blocked", "Température trop élevée pour tondre."
    if vent > _MOWING_WINDOW_BLOCK_WIND:
        return "blocked", "Vent trop fort pour tondre."
    if vent >= _MOWING_WINDOW_DISCOURAGED_WIND:
        return "discouraged", "Vent soutenu: à éviter."
    if _MOWING_WINDOW_DISCOURAGED_TEMP_MIN <= temperature <= _MOWING_WINDOW_BLOCK_TEMP_MIN:
        return "discouraged", "Température élevée: à éviter."
    if hour < _MOWING_WINDOW_IDEAL_START:
        return "blocked", "Matin trop tôt: attendre le ressuyage."
    if _MOWING_WINDOW_IDEAL_START <= hour < _MOWING_WINDOW_IDEAL_END:
        return "ideal", "Fenêtre idéale du matin."
    if _MOWING_WINDOW_ACCEPTABLE_START <= hour < _MOWING_WINDOW_ACCEPTABLE_END:
        if month in {7, 8} and temperature >= 28:
            return "discouraged", "Fin de journée chaude: à éviter."
        return "acceptable", "Fenêtre acceptable de fin de journée."
    if _MOWING_WINDOW_IDEAL_END <= hour < _MOWING_WINDOW_ACCEPTABLE_START:
        if month in {7, 8} and temperature >= 28:
            return "discouraged", "Plein après-midi en été: à éviter."
        return "discouraged", "Créneau intermédiaire: à éviter."
    if _MOWING_WINDOW_ACCEPTABLE_END <= hour < _MOWING_WINDOW_NIGHT_END:
        return "discouraged", "Fin de journée tardive: à éviter."
    return "blocked", "Nuit: attendre le lever du soleil."


def _soil_is_wet(advanced_context: dict[str, Any], context: DecisionContext) -> bool:
    humidite_sol = advanced_context.get("humidite_sol")
    if humidite_sol is None:
        humidite_sol = context.humidite_sol
    if humidite_sol is None:
        return False
    try:
        return float(humidite_sol) >= 70
    except (TypeError, ValueError):
        return False


def _post_application_mowing_block(context: DecisionContext) -> tuple[bool, str | None, str | None]:
    application_state = compute_application_state(context.history)
    status = str(application_state.get("application_post_watering_status") or "").strip().lower()
    if status not in {"bloque", "en_attente", "autorise"}:
        return False, None, None
    return True, "post_application_active", "Post-produit actif: attends la fin du post-arrosage."


def _machine_unavailable_detail(
    mower_context: dict[str, Any],
) -> tuple[str, str] | None:
    mower_operation_state = str(mower_context.get("mower_operation_state") or "").strip().lower()
    mower_reason_code = str(mower_context.get("mower_reason_code") or "").strip().lower()
    mower_is_mowing = bool(mower_context.get("mower_is_mowing")) or mower_operation_state in {"tonte", "mowing"}
    mower_is_returning = bool(mower_context.get("mower_is_returning")) or mower_operation_state in {"transit", "retour", "retour_station"}
    mower_is_ready = mower_context.get("mower_coordination_ready") is not False and mower_context.get("tondeuse_prete") is not False
    mower_is_connected = mower_context.get("tondeuse_connectee") is not False
    mower_is_charging = bool(mower_context.get("tondeuse_en_charge"))

    if not mower_is_connected:
        return "offline", "Robot hors ligne: attendre qu'elle redevienne joignable."
    if mower_is_charging:
        return "charging", "Robot en charge: attendre qu'elle soit prête."
    if mower_is_mowing or mower_reason_code == "mower_mowing":
        return "mowing", "Robot déjà en tonte: attendre la fin du cycle en cours."
    if mower_is_returning or mower_reason_code == "mower_returning":
        return "returning", "Robot en retour station: attendre qu'elle soit prête."
    if mower_reason_code == "mower_starting":
        return "starting", "Robot en démarrage: attendre qu'elle soit prête."
    if mower_reason_code == "mower_zoning":
        return "zoning", "Robot en changement de zone: attendre qu'elle soit prête."
    if mower_reason_code == "mower_searching_zone":
        return "searching_zone", "Robot en recherche de zone: attendre qu'elle soit prête."
    if mower_reason_code == "mower_escaped_digital_fence":
        return "escaped_digital_fence", "Robot hors périmètre: intervention requise."
    if mower_reason_code == "mower_rain_delayed":
        return "rain_delayed", "Robot en pause pluie: attendre qu'elle soit prête."
    if mower_reason_code == "mower_unreliable":
        return "unreliable", "Robot instable: vérifie sa disponibilité avant de reprendre."
    if not mower_is_ready:
        return "not_ready", "Robot indisponible: attendre qu'elle soit prête."
    return None


def _resolve_mowing_block(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> tuple[bool, str | None, str | None, str | None, str | None]:
    """Résout le blocage réel prioritaire, indépendant de la fenêtre métier."""
    post_application_active, post_application_code, post_application_label = _post_application_mowing_block(context)
    if post_application_active:
        return True, post_application_code, post_application_label, None, None

    mower_context = context.mower_context if isinstance(context.mower_context, dict) else {}
    if mower_context:
        machine_detail = _machine_unavailable_detail(mower_context)
        if machine_detail is not None:
            detail_code, detail_label = machine_detail
            return True, "machine_unavailable", "Robot indisponible: attendre qu'elle soit prête.", detail_code, detail_label

    temperature = float(context.temperature or 0.0)
    if temperature < 8 or temperature > _MOWING_WINDOW_BLOCK_TEMP_MIN:
        return True, "temp_extreme", "Température extrême: attendre une fenêtre plus clémente.", None, None

    advanced_context = water_bundle.get("advanced_context")
    if not isinstance(advanced_context, dict):
        advanced_context = {}
    rosee = advanced_context.get("rosee")
    pluie_24h = float(context.pluie_24h or 0.0)
    if rosee is not None:
        try:
            if float(rosee) > 0:
                return True, "wet_grass", "Herbe mouillée: attendre le ressuyage.", None, None
        except (TypeError, ValueError):
            pass

    if is_active_rain_weather(context.weather_profile):
        return True, "wet_grass", "Herbe mouillée: pluie en cours ou récente.", None, None
    if _soil_is_wet(advanced_context, context):
        return True, "soil_wet", "Sol humide: attendre le ressuyage.", None, None

    watering_block_active, watering_block_reason_code, watering_block_reason_label = _watering_related_mowing_block(
        context,
        phase_bundle,
        water_bundle,
    )
    if watering_block_active:
        return True, watering_block_reason_code, watering_block_reason_label, None, None

    return False, None, None, None, None


def _default_projection_anchor(context: DecisionContext) -> datetime:
    """Ancre technique minimale utilisée quand aucune source métier plus précise n'existe."""
    return datetime.combine(context.today, time(6, 0), tzinfo=timezone.utc)


def _estimate_mowing_ressuyage_hours(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> float:
    """Estime le délai de ressuyage nécessaire avant une tonte sûre."""
    soil_profile = str(water_bundle.get("soil_profile") or context.type_sol or "").strip().lower()
    if soil_profile == "sableux":
        hours = 1.0
    elif soil_profile == "argileux":
        hours = 4.0
    else:
        hours = 2.0

    humidite = float(context.humidite or 0.0)
    temperature = float(context.temperature or 0.0)
    pluie_24h = float(context.pluie_24h or 0.0)
    pluie_demain = float(context.pluie_demain or 0.0)
    rosee = water_bundle["advanced_context"].get("rosee")
    arrosage_recent_jour = float(water_bundle["water_balance"].get("arrosage_recent_jour") or 0.0)

    if humidite >= 85 or (rosee is not None and float(rosee) > 0):
        hours += 2.0
    elif humidite >= 70:
        hours += 1.0

    if pluie_24h >= 5.0 or arrosage_recent_jour > 2.0:
        hours += 2.0
    elif pluie_24h >= 2.0 or arrosage_recent_jour > 0.5:
        hours += 1.0

    if pluie_demain >= 2.0:
        hours += 0.5

    if temperature >= 28 and humidite <= 55:
        hours -= 0.5

    if phase_bundle["phase_dominante"] == "Sursemis":
        hours += 1.0

    return max(0.5, min(hours, 10.0))


def _mowing_projection_forecast_offset_days(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
) -> tuple[int, list[str]]:
    """Décale la projection si la fenêtre sèche des prochains jours reste mauvaise."""
    offsets: list[int] = [0]
    reasons: list[str] = []

    pluie_demain = float(context.pluie_demain or 0.0)
    pluie_j2 = float(context.pluie_j2 or 0.0)
    pluie_3j = float(context.pluie_3j or 0.0)
    pluie_probabilite_max_3j = float(context.pluie_probabilite_max_3j or 0.0)
    humidite = float(context.humidite or 0.0)
    rosee = context.rosee
    weather_profile = context.weather_profile if isinstance(context.weather_profile, dict) else {}
    precip_probability = float(
        weather_profile.get("weather_precipitation_probability")
        or pluie_probabilite_max_3j
        or 0.0
    )
    cloud_coverage = float(weather_profile.get("weather_cloud_coverage") or 0.0)
    wind = float(context.vent or weather_profile.get("weather_wind_speed") or 0.0)
    temperature = float(context.temperature or 0.0)
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")

    if pluie_demain >= 2.0 or precip_probability >= 85.0:
        offsets.append(1)
        reasons.append("meteo_j1_humide")
    elif pluie_demain >= 1.0 or precip_probability >= 70.0:
        offsets.append(1)
        reasons.append("meteo_j1_incertaine")

    if pluie_j2 >= 2.0:
        offsets.append(2)
        reasons.append("meteo_j2_humide")
    elif pluie_j2 >= 1.0 and precip_probability >= 75.0:
        offsets.append(2)
        reasons.append("meteo_j2_incertaine")

    if pluie_3j >= 6.0:
        offsets.append(3)
        reasons.append("meteo_3j_tres_humide")
    elif pluie_3j >= 3.0 and precip_probability >= 80.0:
        offsets.append(3)
        reasons.append("meteo_3j_humide")

    if humidite >= 88.0 or (rosee is not None and float(rosee) > 0):
        offsets.append(1)
        reasons.append("ressuyage_lent")

    if cloud_coverage >= 90.0 and wind <= 8.0 and temperature <= 16.0:
        offsets.append(1)
        reasons.append("sechage_faible")

    if phase_dominante == "Sursemis" and sous_phase in {"Germination", "Enracinement"}:
        offsets.append(1)
        reasons.append(f"sous_phase={sous_phase.lower()}")
    elif phase_dominante in {"Traitement", "Hivernage"}:
        offsets.append(1)
        reasons.append(f"phase={phase_dominante.lower()}")

    return max(offsets), reasons


def _mowing_projection_application_offset_hours(context: DecisionContext) -> tuple[float, list[str]]:
    """Ajoute une prudence si une application récente peut encore gêner la tonte."""
    application_state = compute_application_state(context.history)
    raw_date = application_state.get("date_action") or application_state.get("date")
    if not raw_date:
        return 0.0, []

    try:
        application_date = date.fromisoformat(str(raw_date))
    except ValueError:
        return 0.0, []

    age_days = max((context.today - application_date).days, 0)
    if age_days > 3:
        return 0.0, []

    application_type = str(application_state.get("application_type") or "").strip().lower()
    requires_watering = bool(application_state.get("application_requires_watering_after"))
    post_status = str(application_state.get("application_post_watering_status") or "").strip().lower()

    hours = 0.0
    reasons: list[str] = []

    if requires_watering or post_status in {"termine", "en_attente", "bloque"}:
        hours = max(hours, 18.0)
        reasons.append("post_application_recent")

    if application_type in {"sol", "foliaire"} and age_days <= 1:
        hours = max(hours, 12.0)
        reasons.append(f"application_{application_type}")

    if age_days == 0:
        hours += 6.0
        reasons.append("application_j0")

    return hours, reasons


def _last_mowing_date(context: DecisionContext) -> date | None:
    """Retourne la date de la dernière tonte déclarée dans l'historique."""
    history = context.history if isinstance(context.history, list) else []
    latest: date | None = None
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "tonte":
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            mowing_date = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        if latest is None or mowing_date > latest:
            latest = mowing_date
    return latest


def _mowing_overdue_state(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
) -> tuple[bool, float, int]:
    """Retourne (is_overdue, overdue_factor, days_since_last_mowing).

    is_overdue est vrai si le délai depuis la dernière tonte dépasse 1,5× l'intervalle
    cible calculé depuis la fréquence saisonnière/phase.
    Retourne (False, 0.0, 0) si la fréquence cible est nulle ou pas de tonte connue.
    """
    frequency, _ = _phase_adjusted_mowing_frequency(phase_bundle, context.today.month)
    if frequency <= 0:
        return False, 0.0, 0
    last_mowing = _last_mowing_date(context)
    if last_mowing is None:
        return False, 0.0, 0
    interval_days = 7.0 / frequency
    days_since = max((context.today - last_mowing).days, 0)
    overdue_factor = days_since / interval_days
    return overdue_factor >= 1.5, round(overdue_factor, 2), days_since


_GROWTH_RATE_BY_MONTH: dict[int, float] = {
    1: 0.0, 2: 0.0,
    3: 0.3, 4: 0.4,
    5: 0.5, 6: 0.5,
    7: 0.4, 8: 0.35,
    9: 0.35, 10: 0.25,
    11: 0.05, 12: 0.0,
}


def _growth_rate_cm_per_day(phase_bundle: dict[str, Any], month: int) -> float:
    """Vitesse de croissance journalière estimée selon la phase et le mois."""
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")
    if phase_dominante == "Sursemis":
        if sous_phase in {"Germination", "Enracinement"}:
            return 0.0
        if sous_phase == "Reprise":
            return 0.2
    return _GROWTH_RATE_BY_MONTH.get(month, 0.3)


def _estimated_grass_height_cm(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
) -> float | None:
    """Estime la hauteur actuelle du gazon depuis la date de dernière tonte.

    Retourne None si la hauteur de coupe ou la date de dernière tonte est inconnue.
    Ne remplace pas un capteur physique — utilisé comme fallback uniquement.
    """
    mower_context = context.mower_context if isinstance(context.mower_context, dict) else {}
    cutting_height_mm = mower_context.get("tondeuse_hauteur_coupe_mm")
    if cutting_height_mm is None:
        return None
    try:
        cutting_height_cm = float(cutting_height_mm) / 10.0
    except (TypeError, ValueError):
        return None
    if cutting_height_cm <= 0:
        return None
    last_mowing = _last_mowing_date(context)
    if last_mowing is None:
        return None
    days_since = max((context.today - last_mowing).days, 0)
    growth_rate = _growth_rate_cm_per_day(phase_bundle, context.today.month)
    return round(cutting_height_cm + days_since * growth_rate, 1)


def _mowing_spacing_min_days(
    phase_bundle: dict[str, Any],
) -> int:
    """Espacement minimal entre deux tontes selon la phase métier."""
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")
    if phase_dominante == "Sursemis":
        if sous_phase == "Reprise":
            return 6
        if sous_phase == "Stabilisation":
            return 3
    return 2


def _project_next_mowing_date(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    tonte_ok: bool,
    reason_code: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Projette la prochaine date de tonte autorisable."""
    if tonte_ok:
        today_iso = context.today.isoformat()
        return today_iso, context.today.strftime("%d/%m/%Y"), None

    anchor: datetime | None = None
    reason_hint: str | None = None

    if reason_code in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
        phase_dominante = str(phase_bundle.get("phase_dominante") or "")
        sous_phase = str(phase_bundle.get("sous_phase") or "")
        phase_start = phase_bundle.get("date_action")
        if phase_dominante == "Sursemis" and sous_phase in {"Germination", "Enracinement"} and phase_start:
            try:
                reprise_start_date = date.fromisoformat(str(phase_start)) + timedelta(days=25)
                return (
                    reprise_start_date.isoformat(),
                    reprise_start_date.strftime("%d/%m/%Y"),
                    f"sous_phase={sous_phase.lower()}",
                )
            except ValueError:
                anchor = None
        else:
            phase_end = phase_bundle.get("date_fin")
            if phase_end:
                try:
                    phase_end_dt = datetime.combine(
                        date.fromisoformat(str(phase_end)),
                        time(6, 0),
                        tzinfo=timezone.utc,
                    )
                    anchor = phase_end_dt
                    reason_hint = f"phase={phase_bundle['phase_dominante']}"
                except ValueError:
                    anchor = None
    elif reason_code == "mowing_night":
        projected_date = context.today
        if context.hour_of_day is not None and context.hour_of_day >= 22:
            projected_date = context.today + timedelta(days=1)
        return projected_date.isoformat(), projected_date.strftime("%d/%m/%Y"), "nuit"
    elif reason_code == "mowing_spacing":
        last_mowing = _last_mowing_date(context)
        spacing_days = _mowing_spacing_min_days(phase_bundle)
        if last_mowing is not None:
            projected_date = max(context.today, last_mowing + timedelta(days=spacing_days))
            return (
                projected_date.isoformat(),
                projected_date.strftime("%d/%m/%Y"),
                f"espacement={spacing_days}j",
            )
        anchor = _default_projection_anchor(context)
    elif reason_code in {
        "watering_in_progress",
        "watering_cooldown",
        "post_application_active",
        "pluie_en_cours",
        "pluie_annoncee",
        "pluie_proche",
        "pluie_recente",
        "sol_humide_post_arrosage",
        "humidite_elevee",
    }:
        anchor = _latest_watering_timestamp(context)
    elif reason_code == "rosee_persistante":
        anchor = _default_projection_anchor(context)
    elif reason_code == "wet_grass":
        anchor = _default_projection_anchor(context)
    elif reason_code == "stress_thermique":
        anchor = _default_projection_anchor(context) + timedelta(hours=24)
    elif reason_code in {"hauteur_trop_faible", "regle_tiers", "regle_tiers_impossible"}:
        return None, None, "croissance"
    else:
        anchor = _default_projection_anchor(context)

    ressuyage_hours = _estimate_mowing_ressuyage_hours(context, phase_bundle, water_bundle)
    application_offset_hours, application_reasons = _mowing_projection_application_offset_hours(context)
    projected = (anchor or _default_projection_anchor(context)) + timedelta(
        hours=ressuyage_hours + application_offset_hours
    )

    if projected.hour >= 18:
        projected += timedelta(days=1)
        projected = projected.replace(hour=6, minute=0, second=0, microsecond=0)

    # `wet_grass` means "wait for the grass to dry", not "weather is bad for several days".
    # Keep the public projection short and let future refreshes re-evaluate if humidity persists.
    if reason_code == "wet_grass":
        projected_date = projected.date()
        if projected_date < context.today:
            projected_date = context.today
        max_short_projection = context.today + timedelta(days=1)
        if projected_date > max_short_projection:
            projected_date = max_short_projection
        return projected_date.isoformat(), projected_date.strftime("%d/%m/%Y"), None

    forecast_offset_days, forecast_reasons = _mowing_projection_forecast_offset_days(context, phase_bundle)
    if forecast_offset_days > 0:
        projected += timedelta(days=forecast_offset_days)
        projected = projected.replace(hour=6, minute=0, second=0, microsecond=0)

    projected_date = projected.date()
    if projected_date < context.today:
        projected_date = context.today

    return projected_date.isoformat(), projected_date.strftime("%d/%m/%Y"), None


def _post_sursemis_bonus(age_days: int | None) -> float:
    """Donne un léger bonus de hauteur pendant la reprise post-sursemis."""
    if age_days is None:
        return 0.0
    if age_days <= 7:
        return 1.0
    if age_days <= 14:
        return 0.8
    if age_days <= 21:
        return 0.5
    if age_days <= 28:
        return 0.3
    if age_days <= 35:
        return 0.1
    if age_days <= 45:
        return 0.3
    if age_days <= 52:
        return 0.2
    if age_days <= 59:
        return 0.1
    return 0.0


def _theoretical_mowing_height(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> float:
    """Estime une hauteur de coupe prudente selon la saison et le stress."""
    temperature = context.temperature or 0.0
    humidite = context.humidite or 0.0
    pluie_24h = context.pluie_24h or 0.0
    pluie_demain = context.pluie_demain or 0.0
    pluie_j2 = context.pluie_j2 or 0.0
    pluie_3j = context.pluie_3j or 0.0
    pluie_probabilite_max_3j = context.pluie_probabilite_max_3j or 0.0
    rosee = water_bundle["advanced_context"].get("rosee")
    etp = water_bundle["etp"] or 0.0
    water_balance = water_bundle["water_balance"]
    score_hydrique = int(risk_bundle["scores"]["score_hydrique"])
    score_stress = int(risk_bundle["scores"]["score_stress"])
    stress_level = classify_stress_level(
        score_hydrique=score_hydrique,
        score_stress=score_stress,
        water_balance=water_balance,
        temperature=temperature,
        etp=etp,
    )

    month = context.today.month
    target = _seasonal_base_height(month)

    if phase_bundle["phase_dominante"] == "Normal":
        if month in {4, 5, 6, 9} and stress_level == "leger":
            if 15 <= temperature <= 24 and humidite >= 50 and pluie_24h < 1 and pluie_demain < 1 and not rosee:
                target -= 0.5
        elif month == 3 and temperature <= 16 and stress_level == "leger":
            target += 0.2
    else:
        target += 0.3

    if month in {1, 2, 11, 12} or temperature <= 8:
        target += 0.5
    if temperature >= 32 or stress_level == "fort":
        target += 1.0
    elif temperature >= 28 or stress_level == "modere":
        target += 0.5
    elif temperature >= 24:
        target += 0.2

    if humidite <= 40:
        target += 0.3
    if rosee is not None and rosee > 0:
        target += 0.4
    if pluie_24h >= 2:
        target += 0.2
    if pluie_demain >= 2:
        target += 0.2
    if pluie_j2 >= 2:
        target += 0.1
    if pluie_3j >= 4:
        target += 0.1
    if pluie_probabilite_max_3j >= 80:
        target += 0.1

    if phase_bundle["phase_dominante"] == "Sursemis":
        if phase_bundle["sous_phase"] == "Germination":
            target = max(target, 7.6)
        elif phase_bundle["sous_phase"] == "Enracinement":
            target = max(target, 7.0)
        else:
            target = max(target, 6.6)
    else:
        post_sursemis_age = _last_sursemis_age_days(context)
        if post_sursemis_age is not None and post_sursemis_age <= 35:
            target += _post_sursemis_bonus(post_sursemis_age)

    return target


def _select_mowing_block_reason(
    *,
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    weather_profile: dict[str, Any],
    humidite: float,
    pluie_demain: float,
    pluie_j2: float,
    pluie_3j: float,
    pluie_probabilite_max_3j: float,
    arrosage_recent_jour: float,
    rosee: Any,
    temperature: float,
    etp: float,
    score_tonte: int,
    score_stress: int,
    current_height: float | None,
    target_height: float,
    effective_max: float,
) -> tuple[str | None, str | None, bool]:
    """Résout une cause de blocage unique selon une priorité métier explicite."""
    phase_dominante = str(phase_bundle["phase_dominante"])
    min_height_after_cut = None if current_height is None else current_height * (2.0 / 3.0)
    last_mowing = _last_mowing_date(context)
    spacing_days = _mowing_spacing_min_days(phase_bundle)

    if phase_dominante == "Sursemis":
        if phase_bundle["sous_phase"] in _SURSEMIS_MOWING_BLOCKED_SUBPHASES:
            return (
                f"Sursemis / {phase_bundle['sous_phase']}: tonte interdite pendant l'installation du gazon.",
                "phase_sursemis",
                False,
            )
    if phase_dominante in {"Traitement", "Hivernage"}:
        return f"Phase {phase_dominante}: mieux vaut différer la tonte.", f"phase_{phase_dominante.lower()}", False

    candidates: list[tuple[int, str, str, bool]] = []

    sun_context = context.sun_context if isinstance(context.sun_context, dict) else {}
    sun_state = str(sun_context.get("sun_state") or "").strip().lower()
    sun_above_horizon = sun_context.get("sun_above_horizon")
    sun_below_horizon = sun_context.get("sun_below_horizon")
    if sun_below_horizon is True or sun_state == "below_horizon":
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["mowing_night"],
                "mowing_night",
                "Nuit: attendre le lever du soleil.",
                False,
            )
        )
    elif sun_above_horizon is None and context.hour_of_day is not None and (
        context.hour_of_day < 7 or context.hour_of_day >= 22
    ):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["mowing_night"],
                "mowing_night",
                "Nuit: attendre le lever du soleil.",
                False,
            )
        )

    if last_mowing is not None:
        days_since_last_mowing = max((context.today - last_mowing).days, 0)
        if days_since_last_mowing < spacing_days:
            next_allowed = last_mowing + timedelta(days=spacing_days)
            candidates.append(
                (
                    _MOWING_BLOCK_PRIORITIES["mowing_spacing"],
                    "mowing_spacing",
                    f"Dernière tonte récente: laisse un jour de repos au gazon avant le {next_allowed.strftime('%d/%m/%Y')}.",
                    False,
                )
            )

    if phase_dominante in {"Traitement", "Hivernage"} or (
        phase_dominante == "Sursemis" and phase_bundle.get("sous_phase") in _SURSEMIS_MOWING_BLOCKED_SUBPHASES
    ):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["phase"],
                f"phase_{phase_dominante.lower()}",
                (
                    f"Sursemis / {phase_bundle['sous_phase']}: tonte interdite pendant l'installation du gazon."
                    if phase_dominante == "Sursemis"
                    else f"Phase {phase_dominante}: mieux vaut différer la tonte."
                ),
                False,
            )
        )

    if is_active_rain_weather(weather_profile):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["pluie_active"],
                "pluie_en_cours",
                "Pluie en cours ou imminente: attendre le ressuyage du gazon.",
                False,
            )
        )

    if float(context.vent or 0.0) > _MOWING_WINDOW_BLOCK_WIND:
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["vent_fort"],
                "vent_fort",
                "Vent fort: tonte interdite.",
                False,
            )
        )

    if current_height is not None:
        if current_height <= target_height:
            candidates.append(
                (
                    _MOWING_BLOCK_PRIORITIES["hauteur_trop_faible"],
                    "hauteur_trop_faible",
                    f"Hauteur actuelle trop faible: vise au moins {target_height:.1f} cm avant de tondre.",
                    True,
                )
            )
        elif min_height_after_cut is not None and target_height < min_height_after_cut:
            if effective_max < min_height_after_cut:
                candidates.append(
                    (
                        _MOWING_BLOCK_PRIORITIES["regle_tiers_impossible"],
                        "regle_tiers_impossible",
                        (
                            f"Règle du tiers impossible avec cette tondeuse: il faudrait au moins {min_height_after_cut:.1f} cm, "
                            f"mais la machine plafonne à {effective_max:.1f} cm."
                        ),
                        True,
                    )
                )
            else:
                candidates.append(
                    (
                        _MOWING_BLOCK_PRIORITIES["regle_tiers"],
                        "regle_tiers",
                        (
                            f"Règle du tiers: conserve au moins {min_height_after_cut:.1f} cm sur une hauteur actuelle de {current_height:.1f} cm."
                        ),
                        True,
                    )
                )

    if rosee is not None and float(rosee) > 0:
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["rosee"],
                "rosee_persistante",
                "Rosée présente: attendre le ressuyage du feuillage.",
                False,
            )
        )

    advanced_context = water_bundle.get("advanced_context")
    if not isinstance(advanced_context, dict):
        advanced_context = {}
    if _soil_is_wet(advanced_context, context):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["humidite_elevee"],
                "soil_wet",
                "Sol humide: attendre le ressuyage.",
                False,
            )
        )

    if arrosage_recent_jour > 0.5:
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["sol_humide_post_arrosage"],
                "recent_watering",
                "Arrosage récent: attendre 24 h avant de tondre.",
                False,
            )
        )

    if score_stress >= 70 or (temperature >= 30 and etp >= 4):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["stress_thermique"],
                "stress_thermique",
                "Stress thermique élevé: limiter la tonte.",
                False,
            )
        )
    elif score_tonte >= 65:
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["conditions_defavorables"],
                "conditions_defavorables",
                "Conditions défavorables à la tonte.",
                False,
            )
        )

    if not candidates:
        return None, None, False

    _priority, reason_code, reason, height_rule_blocked = min(candidates, key=lambda item: item[0])
    return reason, reason_code, height_rule_blocked


def _compute_mowing_status(
    *,
    phase_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
    tonte_ok: bool,
    height_rule_blocked: bool,
    score_tonte: int,
) -> str:
    tonte_statut = compute_tonte_statut(
        phase_dominante=phase_bundle["phase_dominante"],
        tonte_autorisee=tonte_ok,
        score_tonte=score_tonte,
        risque_gazon=risk_bundle["risque_gazon"],
    )
    if height_rule_blocked and tonte_statut != "interdite":
        return "deconseillee"
    return tonte_statut


def _mowing_daily_session_policy(
    phase_bundle: dict[str, Any],
) -> tuple[int, str]:
    """Retourne la politique métier de sessions de tonte par jour."""
    phase_dominante = str(phase_bundle.get("phase_dominante") or "").strip()
    if phase_dominante in {"Sursemis", "Traitement", "Scarification", "Hivernage"}:
        return 1, "phase_sensitive"
    return 2, "standard"


def _build_mowing_bundle_payload(
    *,
    tonte_ok: bool,
    tonte_statut: str,
    reason: str,
    reason_code: str | None,
    next_mowing_date: str | None,
    next_mowing_display: str | None,
    score_tonte: int,
    score_stress: int,
    height_recommendation: dict[str, float | None],
    mowing_frequency_target_per_week: float,
    mowing_frequency_label: str,
    mowing_window_state: str,
    mowing_window_label: str,
    mowing_window_reason: str | None,
    mowing_daily_session_limit: int,
    mowing_daily_session_policy: str,
) -> dict[str, Any]:
    bundle = {
        "tonte_autorisee": tonte_ok,
        "tonte_statut": tonte_statut,
        "tonte_reason": reason,
        "raison_blocage_code": reason_code,
        "next_mowing_date": next_mowing_date,
        "next_mowing_display": next_mowing_display,
        "score_tonte": score_tonte,
        "score_stress": score_stress,
        "mowing_frequency_target_per_week": mowing_frequency_target_per_week,
        "mowing_frequency_label": mowing_frequency_label,
        "mowing_window_state": mowing_window_state,
        "mowing_window_label": mowing_window_label,
        "mowing_window_reason": mowing_window_reason,
        "mowing_daily_session_limit": mowing_daily_session_limit,
        "mowing_daily_session_policy": mowing_daily_session_policy,
        "mowing_resume_requires_full_battery": True,
        "mowing_blocked_by_watering": False,
        "mowing_blocked": False,
        "mowing_block_reason_code": None,
        "mowing_block_reason_label": None,
        "mowing_block_reason": None,
        "mowing_cooldown_remaining_minutes": 0,
        "mowing_post_application_active": False,
        **height_recommendation,
    }
    return bundle


def _recommended_mowing_height(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> dict[str, float | None]:
    """Calcule une hauteur de coupe prudente et compatible avec la machine."""
    min_height, max_height, step = _mowing_height_settings(context)
    theoretical_height = _theoretical_mowing_height(context, phase_bundle, water_bundle, risk_bundle)
    current_height = water_bundle["advanced_context"].get("hauteur_gazon")
    if current_height is None:
        current_height = _estimated_grass_height_cm(context, phase_bundle)
    third_floor = None
    robot_min_height = 4.0
    robot_max_height = 6.5

    if current_height is not None:
        try:
            current_height = float(current_height)
            third_floor = current_height * (2.0 / 3.0)
            theoretical_height = max(theoretical_height, third_floor)
        except (TypeError, ValueError):
            current_height = None
            third_floor = None

    effective_max = _round_down_to_step(max_height, min_height, step)
    recommended_height = _round_up_to_step(theoretical_height, min_height, step)
    allowed_min = max(min_height, robot_min_height)
    allowed_max = min(effective_max, robot_max_height)
    if allowed_max < allowed_min:
        allowed_min = min_height
        allowed_max = effective_max
    recommended_height = max(allowed_min, min(recommended_height, allowed_max))

    previous_height = _previous_recommended_height(context)
    if previous_height is not None:
        previous_height = max(allowed_min, min(previous_height, allowed_max))
        previous_height = _round_to_step(previous_height)
        diff = recommended_height - previous_height
        if abs(diff) < step:
            recommended_height = previous_height
        else:
            direction = step if diff > 0 else -step
            recommended_height = _round_to_step(previous_height + direction)
            recommended_height = max(allowed_min, min(recommended_height, allowed_max))

    return {
        "hauteur_tonte_recommandee_cm": round(recommended_height, 2),
        "hauteur_tonte_min_cm": round(min_height, 2),
        "hauteur_tonte_max_cm": round(max_height, 2),
        "_hauteur_tonte_effective_max_cm": round(effective_max, 2),
        "_hauteur_tonte_3e_cm": round(third_floor, 2) if third_floor is not None else None,
        "_hauteur_tonte_theorique_cm": round(theoretical_height, 2),
        "_hauteur_tonte_actuelle_cm": round(float(current_height), 2) if current_height is not None else None,
    }


def build_mowing_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> dict[str, Any]:
    score_tonte = int(risk_bundle["scores"]["score_tonte"])
    score_stress = int(risk_bundle["scores"]["score_stress"])
    stress_level = classify_stress_level(
        score_hydrique=int(risk_bundle["scores"]["score_hydrique"]),
        score_stress=score_stress,
        water_balance=water_bundle["water_balance"],
        temperature=context.temperature,
        etp=water_bundle["etp"],
    )
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")
    if phase_dominante == "Sursemis" and sous_phase in {"Reprise", "Stabilisation"}:
        baseline_tonte_ok = score_tonte < 65 and score_stress < 75
    else:
        baseline_tonte_ok = score_tonte < 55 and score_stress < 70

    mowing_frequency_target_per_week, mowing_frequency_label = _phase_adjusted_mowing_frequency(
        phase_bundle,
        context.today.month,
    )
    height_recommendation = _recommended_mowing_height(context, phase_bundle, water_bundle, risk_bundle)
    target_height = float(height_recommendation["hauteur_tonte_recommandee_cm"] or 0.0)
    current_height = water_bundle["advanced_context"].get("hauteur_gazon")
    height_rule_blocked = False
    try:
        current_height_float = float(current_height) if current_height is not None else None
    except (TypeError, ValueError):
        current_height_float = None
    effective_max = float(height_recommendation["_hauteur_tonte_effective_max_cm"] or 0.0)

    post_application_active, post_application_code, post_application_label = _post_application_mowing_block(context)
    active_session = _active_irrigation_session(context)
    watering_in_progress = active_session is not None
    cooldown_active, cooldown_remaining_minutes = _mowing_cooldown_state(context)
    mowing_window_state, mowing_window_reason = _resolve_mowing_window(
        context,
        weather_profile=context.weather_profile,
    )
    mowing_blocked, mowing_block_reason_code, mowing_block_reason_label, mowing_machine_unavailable_detail, mowing_machine_unavailable_label = _resolve_mowing_block(
        context,
        phase_bundle,
        water_bundle,
    )
    if mowing_blocked:
        mowing_window_state = "blocked"
        mowing_window_reason = mowing_block_reason_label
    mowing_window_label = _mowing_window_label(mowing_window_state)
    mowing_window_blocked_by_schedule = mowing_window_state == "blocked" and not mowing_blocked

    reason, reason_code, height_rule_blocked = _select_mowing_block_reason(
        context=context,
        phase_bundle=phase_bundle,
        water_bundle=water_bundle,
        weather_profile=context.weather_profile,
        humidite=float(context.humidite or 0.0),
        pluie_demain=float(context.pluie_demain or 0.0),
        pluie_j2=float(context.pluie_j2 or 0.0),
        pluie_3j=float(context.pluie_3j or 0.0),
        pluie_probabilite_max_3j=float(context.pluie_probabilite_max_3j or 0.0),
        arrosage_recent_jour=float(water_bundle["water_balance"].get("arrosage_recent_jour") or 0.0),
        rosee=water_bundle["advanced_context"].get("rosee"),
        temperature=float(context.temperature or 0.0),
        etp=float(water_bundle.get("etp") or 0.0),
        score_tonte=score_tonte,
        score_stress=score_stress,
        current_height=current_height_float,
        target_height=target_height,
        effective_max=effective_max,
    )
    selected_reason = reason
    selected_reason_code = reason_code

    mowing_window_blocked = mowing_window_state == "blocked"
    mowing_blocked_by_watering = False
    if post_application_active:
        reason = post_application_label
        reason_code = post_application_code
        mowing_blocked = True
        mowing_blocked_by_watering = True
        mowing_block_reason_code = post_application_code
        mowing_block_reason_label = post_application_label
        mowing_block_reason = "recent_watering"
        height_rule_blocked = False
    elif watering_in_progress:
        reason = "Arrosage en cours: attends la fin du cycle avant de tondre."
        reason_code = "watering_in_progress"
        mowing_blocked = True
        mowing_blocked_by_watering = True
        mowing_block_reason_code = reason_code
        mowing_block_reason_label = reason
        mowing_block_reason = "recent_watering"
        height_rule_blocked = False
    elif cooldown_active:
        reason = (
            f"Arrosage récent: attends encore {cooldown_remaining_minutes} min avant de reprendre la tonte."
        )
        reason_code = "watering_cooldown"
        mowing_blocked = True
        mowing_blocked_by_watering = True
        mowing_block_reason_code = reason_code
        mowing_block_reason_label = reason
        mowing_block_reason = "recent_watering"
        height_rule_blocked = False
    elif mowing_blocked and mowing_block_reason_code:
        mowing_blocked_by_watering = mowing_block_reason_code in {"recent_watering", "soil_wet", "wet_grass"}
        mowing_block_reason = mowing_block_reason_code
        if reason_code not in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
            reason = mowing_block_reason_label or reason
            reason_code = mowing_block_reason_code
        height_rule_blocked = False
    else:
        mowing_block_reason = None

    if selected_reason_code in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
        reason = selected_reason
        reason_code = selected_reason_code
        mowing_blocked = True
        mowing_blocked_by_watering = False
        mowing_block_reason_code = selected_reason_code
        mowing_block_reason_label = selected_reason
        mowing_block_reason = selected_reason_code
        height_rule_blocked = False

    if reason_code and mowing_block_reason_code is None and not mowing_blocked:
        mowing_block_reason_code = reason_code
        mowing_block_reason_label = reason

    if mowing_window_blocked_by_schedule:
        window_msg = mowing_window_reason or "Fenêtre de tonte bloquée."
        if reason_code is None:
            reason_code = "mowing_window_blocked"
            reason = window_msg
            if mowing_block_reason_code is None:
                mowing_block_reason_code = reason_code
                mowing_block_reason_label = reason
        else:
            reason = f"{reason} Fenêtre horaire: {window_msg}"

    agronomic_block_codes = {
        "mowing_night",
        "mowing_spacing",
        "phase_sursemis",
        "phase_traitement",
        "phase_hivernage",
        "hauteur_trop_faible",
        "regle_tiers",
        "regle_tiers_impossible",
        "stress_thermique",
        "conditions_defavorables",
        "wet_grass",
        "rosee_persistante",
        "soil_wet",
        "pluie_en_cours",
        "recent_watering",
        "post_application_active",
        "watering_in_progress",
        "watering_cooldown",
    }
    soil_wet_is_permssive = reason_code == "soil_wet" and _has_recent_watering_history(context)

    mowing_is_overdue, overdue_factor, overdue_days = _mowing_overdue_state(context, phase_bundle)
    overdue_relaxed_baseline = False
    if mowing_is_overdue and reason_code in _OVERDUE_SOFT_OVERRIDE_CODES:
        extended_threshold = 65 if overdue_factor < 2.0 else 70
        overdue_relaxed_baseline = score_tonte < extended_threshold and score_stress < 70

    tonte_ok = (baseline_tonte_ok or overdue_relaxed_baseline) and not mowing_window_blocked_by_schedule and (
        reason_code not in agronomic_block_codes or soil_wet_is_permssive or overdue_relaxed_baseline
    )
    if reason is None:
        if mowing_window_state == "discouraged" and mowing_window_reason:
            reason = f"Tonte possible. Créneau déconseillé: {mowing_window_reason}"
        else:
            reason = "Fenêtre tonte acceptable."

    next_mowing_date, next_mowing_display, next_mowing_reason_hint = _project_next_mowing_date(
        context,
        phase_bundle,
        water_bundle,
        tonte_ok,
        reason_code,
    )

    if mowing_is_overdue and mowing_frequency_target_per_week > 0:
        interval_days_display = round(7.0 / mowing_frequency_target_per_week, 1)
        overdue_prefix = (
            f"Retard de tonte: {overdue_days} j depuis la dernière"
            f" (intervalle cible: {interval_days_display:.1f} j). "
        )
        if tonte_ok:
            reason = overdue_prefix + "Tonte recommandée."
        else:
            base = reason or ""
            if next_mowing_display:
                base = f"{base} Prochaine tonte estimée le {next_mowing_display}."
            reason = overdue_prefix + base.lstrip()
    else:
        if not tonte_ok and next_mowing_display:
            reason = f"{reason} Prochaine tonte estimée le {next_mowing_display}."

    watering_coord_level, watering_coord_msg = _upcoming_watering_coordination(context, water_bundle)
    if watering_coord_level == "block" and not mowing_blocked and not post_application_active and not watering_in_progress and not cooldown_active:
        tonte_ok = False
        reason = watering_coord_msg or reason
        reason_code = "upcoming_watering"
        mowing_block_reason_code = reason_code
        mowing_block_reason_label = watering_coord_msg
        mowing_block_reason = "recent_watering"
    elif watering_coord_msg and tonte_ok:
        reason = f"{reason} {watering_coord_msg}"

    tonte_statut = _compute_mowing_status(
        phase_bundle=phase_bundle,
        risk_bundle=risk_bundle,
        tonte_ok=tonte_ok,
        height_rule_blocked=height_rule_blocked,
        score_tonte=score_tonte,
    )
    if reason_code == "mowing_night":
        tonte_statut = "interdite"

    mowing_daily_session_limit, mowing_daily_session_policy = _mowing_daily_session_policy(
        phase_bundle
    )

    bundle = _build_mowing_bundle_payload(
        tonte_ok=tonte_ok,
        tonte_statut=tonte_statut,
        reason=reason,
        reason_code=reason_code,
        next_mowing_date=next_mowing_date,
        next_mowing_display=next_mowing_display,
        score_tonte=score_tonte,
        score_stress=score_stress,
        height_recommendation=height_recommendation,
        mowing_frequency_target_per_week=mowing_frequency_target_per_week,
        mowing_frequency_label=mowing_frequency_label,
        mowing_window_state=mowing_window_state,
        mowing_window_label=mowing_window_label,
        mowing_window_reason=mowing_window_reason,
        mowing_daily_session_limit=mowing_daily_session_limit,
        mowing_daily_session_policy=mowing_daily_session_policy,
    )
    bundle["mowing_blocked"] = bool(mowing_blocked)
    bundle["mowing_blocked_by_watering"] = mowing_blocked_by_watering
    bundle["mowing_block_reason_code"] = mowing_block_reason_code
    bundle["mowing_block_reason_label"] = mowing_block_reason_label
    bundle["mowing_block_reason"] = mowing_block_reason
    bundle["mowing_machine_unavailable_detail"] = mowing_machine_unavailable_detail
    bundle["mowing_machine_unavailable_label"] = mowing_machine_unavailable_label
    bundle["mowing_cooldown_remaining_minutes"] = cooldown_remaining_minutes
    bundle["mowing_post_application_active"] = post_application_active
    bundle["mowing_is_overdue"] = mowing_is_overdue
    bundle["mowing_overdue_days"] = overdue_days
    bundle["mowing_overdue_factor"] = overdue_factor
    bundle["gazon_hauteur_estimee_cm"] = _estimated_grass_height_cm(context, phase_bundle)
    bundle["mowing_watering_coordination"] = watering_coord_level
    bundle["mowing_watering_coordination_msg"] = watering_coord_msg
    mower_context = context.mower_context if isinstance(context.mower_context, dict) else {}
    if mower_context:
        bundle.update(
            {
                key: value
                for key, value in mower_context.items()
                if (key.startswith("tondeuse_") or key.startswith("mower_")) and value is not None
            }
        )
    mower_coordination_ready = bundle.get("mower_coordination_ready", True)
    machine_permet_tonte = bool(bundle.get("tondeuse_prete", False)) and mower_coordination_ready is not False
    bundle["gazon_permet_tonte"] = bool(bundle.get("tonte_autorisee", False))
    bundle["machine_permet_tonte"] = machine_permet_tonte
    bundle["action_possible"] = bool(bundle["gazon_permet_tonte"] and machine_permet_tonte and not bundle.get("mowing_blocked", False))
    return bundle
