from __future__ import annotations

from datetime import date, datetime, timezone
from math import ceil
from typing import Any

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None

from .seasonal_profile import get_seasonal_profile
from .const import (
    OBJECTIVE_SCOPE_GLOBAL_SURFACE,
    OBJECTIVE_SCOPE_SURFACE_CYCLE,
    WATERING_STAGE_ENRACINEMENT,
    WATERING_STAGE_GERMINATION,
    WATERING_STAGE_LEVEE,
    WATERING_STAGE_NORMAL,
    WATERING_STRATEGY_ADULT_DEEP,
    WATERING_STRATEGY_SEMIS_FREQUENT,
)
from .decision_models import normalize_watering_contract
from .watering_policy import resolve_semis_stage_program, resolve_watering_policy
from .water import compute_recent_watering_count

# Règles agronomiques soutenues par les sources:
# - arroser tôt le matin;
# - éviter les arrosages tardifs qui prolongent l'humectation nocturne;
# - pour les semis / sursemis, garder la surface humide sans saturation;
# - réduire la fréquence à mesure que l'enracinement progresse.
#
# Conventions internes de l'intégration:
# - fenêtre optimale stricte au matin;
# - fenêtre acceptable étendue jusqu'à 10h si le contexte reste favorable;
# - soirée réservée au rattrapage exceptionnel, jamais juste avant la nuit.
OPTIMAL_MORNING_START_HOUR = 4
OPTIMAL_MORNING_END_HOUR = 8
ACCEPTABLE_MORNING_END_HOUR = 10
SEMIS_WINDOW_START_HOUR = 10
SEMIS_WINDOW_END_HOUR = 17
SEMIS_DAYTIME_ACCEPTABLE_END_HOUR = 18
EVENING_START_HOUR = 18
EVENING_END_HOUR = 20
NORMAL_WEEKLY_GUARDRAIL_MM_MIN = 20.0
NORMAL_WEEKLY_GUARDRAIL_MM_MAX = 25.0
NORMAL_MIN_USEFUL_SESSION_MM = 10.0
SATURATION_BILAN_HYDRIQUE_MM = 5.0
MODE_MIN_WATERING_MM = {
    "Normal": 10.0,
    "Sursemis": 0.5,
    "Fertilisation": 3.0,
    "Biostimulant": 5.0,
    "Agent Mouillant": 5.0,
    "Scarification": 5.0,
    "Traitement": 0.0,
    "Hivernage": 0.0,
}
RAINY_WEATHER_CONDITIONS = {
    "rainy",
    "pouring",
    "lightning-rainy",
    "snowy-rainy",
}

SURSEMIS_POLICY_CONFIGS: dict[str, dict[str, float | str]] = {
    "germination_stricte": {
        "surface_bilan_max": 8.0,
        "pluie_24h_max": 1.5,
        # En germination, on laisse une marge plus large avant de bloquer.
        "pluie_demain_max": 3.0,
        "pluie_probabilite_max": 80.0,
        "mm_detected_24h_max": 0.5,
        "temperature_min": 8.0,
        "risk_level": "modere",
        "niveau_action": "a_faire",
        "fenetre_si_ok": "ce_matin",
    },
    "enracinement_prudent": {
        "surface_bilan_max": 7.0,
        "pluie_24h_max": 1.5,
        "pluie_demain_max": 1.5,
        "pluie_probabilite_max": 65.0,
        "mm_detected_24h_max": 0.25,
        "temperature_min": 8.0,
        "risk_level": "modere",
        "niveau_action": "surveiller",
        "fenetre_si_ok": "demain_matin",
    },
    "reprise_prudente": {
        "surface_bilan_max": 6.5,
        "pluie_24h_max": 1.5,
        "pluie_demain_max": 2.0,
        "pluie_probabilite_max": 70.0,
        "mm_detected_24h_max": 0.25,
        "temperature_min": 8.0,
        "risk_level": "faible",
        "niveau_action": "surveiller",
        "fenetre_si_ok": "attendre",
    },
    "reprise_transition": {
        "surface_bilan_max": 6.0,
        "pluie_24h_max": 1.5,
        "pluie_demain_max": 1.5,
        "pluie_probabilite_max": 65.0,
        "mm_detected_24h_max": 0.25,
        "temperature_min": 8.0,
        "risk_level": "faible",
        "niveau_action": "surveiller",
        "fenetre_si_ok": "attendre",
    },
}


def is_active_rain_weather(weather_profile: dict[str, Any] | None) -> bool:
    weather_profile = weather_profile or {}
    condition = str(weather_profile.get("weather_condition") or "").strip().lower()
    if condition in RAINY_WEATHER_CONDITIONS:
        return True
    precipitation_probability = weather_profile.get("weather_precipitation_probability")
    try:
        precipitation_probability = (
            float(precipitation_probability)
            if precipitation_probability is not None
            else None
        )
    except (TypeError, ValueError):
        precipitation_probability = None
    return precipitation_probability is not None and precipitation_probability >= 80.0


def _temperature_band(temperature: float | None) -> str:
    temperature = temperature if temperature is not None else 0.0
    if temperature < 10:
        return "cool"
    if temperature > 22:
        return "hot"
    return "mild"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reference_hydric_balance_mm(water_balance: dict[str, Any] | None) -> float:
    water_balance = water_balance or {}
    try:
        return float(water_balance.get("bilan_hydrique_mm") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _hydraulic_pressure(
    bilan_hydrique_mm: float,
    deficit_3j: float,
    deficit_7j: float,
) -> tuple[float, float, float]:
    """Pression hydrique = besoin court terme (déficit du jour) + tendance pondérée 3j/7j."""
    besoin_court = max(0.0, -bilan_hydrique_mm)
    besoin_tendance = (deficit_3j * 0.18) + (deficit_7j * 0.06)
    return besoin_court, besoin_tendance, besoin_court + besoin_tendance


def _parse_history_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text[:10])
        except ValueError:
            return None
        parsed = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_watering_datetime(history: list[dict[str, Any]]) -> datetime | None:
    latest: datetime | None = None
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "arrosage":
            continue
        raw_value = item.get("recorded_at") or item.get("detected_at") or item.get("date")
        parsed = _parse_history_datetime(raw_value)
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def _latest_phase_start_index(history: list[dict[str, Any]], phase_name: str) -> int | None:
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if isinstance(item, dict) and item.get("type") == phase_name:
            return index
    return None


def _count_tonte_events_since_latest_phase_start(history: list[dict[str, Any]], phase_name: str) -> int:
    start_index = _latest_phase_start_index(history, phase_name)
    if start_index is None:
        return 0
    count = 0
    for item in history[start_index + 1 :]:
        if isinstance(item, dict) and item.get("type") == "tonte":
            count += 1
    return count


def _compute_transition_sursemis_pret(
    *,
    history: list[dict[str, Any]],
    sous_phase: str,
    sous_phase_age_days: int | None,
    sous_phase_progression: float | None,
    hauteur_gazon: float | None,
    water_balance: dict[str, float],
    pluie_24h: float,
    pluie_demain: float,
    pluie_probabilite_24h: float,
    temperature: float,
) -> tuple[bool, int]:
    if sous_phase != "Reprise":
        return False, 0

    tonte_count = _count_tonte_events_since_latest_phase_start(history, "Sursemis")
    age_ok = (sous_phase_age_days or 0) >= 16
    progression_ok = (sous_phase_progression or 0.0) >= 70.0
    tonte_ok = tonte_count >= 2
    height_ok = hauteur_gazon is None or hauteur_gazon >= 6.0
    weather_ok = (
        _reference_hydric_balance_mm(water_balance) <= 2.0
        and pluie_24h < 1.0
        and pluie_demain < 1.0
        and pluie_probabilite_24h < 65.0
        and temperature >= 8.0
    )
    # Température doit être suffisante pour enracinement actif
    temp_ok = temperature >= 12.0  # En dessous, enracinement trop lent même si jours écoulés
    return age_ok and progression_ok and tonte_ok and height_ok and weather_ok and temp_ok, tonte_count


def _select_sursemis_policy(
    *,
    history: list[dict[str, Any]],
    sous_phase: str,
    sous_phase_age_days: int | None,
    sous_phase_progression: float | None,
    hauteur_gazon: float | None,
    water_balance: dict[str, float],
    pluie_24h: float,
    pluie_demain: float,
    pluie_probabilite_24h: float,
    temperature: float,
) -> tuple[str, dict[str, Any], bool, int]:
    transition_ready, tonte_count = _compute_transition_sursemis_pret(
        history=history,
        sous_phase=sous_phase,
        sous_phase_age_days=sous_phase_age_days,
        sous_phase_progression=sous_phase_progression,
        hauteur_gazon=hauteur_gazon,
        water_balance=water_balance,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_probabilite_24h=pluie_probabilite_24h,
        temperature=temperature,
    )
    if sous_phase == "Germination":
        policy_key = "germination_stricte"
    elif sous_phase == "Enracinement":
        policy_key = "enracinement_prudent"
    elif sous_phase == "Reprise":
        policy_key = "reprise_transition" if transition_ready else "reprise_prudente"
    else:
        policy_key = "enracinement_prudent"
    policy = dict(SURSEMIS_POLICY_CONFIGS[policy_key])
    policy["policy_key"] = policy_key
    policy["transition_ready"] = transition_ready
    policy["tonte_count_since_sursemis"] = tonte_count
    return policy_key, policy, transition_ready, tonte_count


def _mode_min_watering_mm(phase_dominante: str) -> float:
    return float(MODE_MIN_WATERING_MM.get(phase_dominante, 0.0))


def _apply_mode_watering_constraints(candidate_mm: float, deficit_mm_brut: float, phase_dominante: str) -> float:
    floor_mm = _mode_min_watering_mm(phase_dominante)
    return _apply_watering_floor_constraints(candidate_mm, deficit_mm_brut, floor_mm)


def _apply_watering_floor_constraints(candidate_mm: float, deficit_mm_brut: float, floor_mm: float) -> float:
    if deficit_mm_brut <= 0:
        return round(floor_mm, 1) if floor_mm > 0 else 0.0
    value = candidate_mm
    if value > 0:
        value = max(value, floor_mm)
    value = min(value, max(deficit_mm_brut, floor_mm))
    return round(max(0.0, value), 1)


def _scarification_soil_humidity_state(
    *,
    saturation_block: bool,
    humidite: float,
) -> str:
    if saturation_block or humidite >= 85:
        return "trop_humide"
    return "legerement_humide"


def _sursemis_micro_apport_decision(
    *,
    policy: dict[str, Any],
    sous_phase: str | None,
    transition_ready: bool,
    pluie_24h: float,
    pluie_demain: float,
    pluie_probabilite_24h: float,
    bilan_hydrique_mm: float,
    mm_detected_24h: float,
    temperature: float,
    humidite: float,
    humidite_sol: float | None,
    reserve_stock_mm: float | None,
    reserve_actuelle_mm: float | None,
    vent: float | None,
    soil_profile: str,
) -> dict[str, Any]:
    policy_key = str(policy.get("policy_key") or "enracinement_prudent")
    watering_stage, stage_program = resolve_semis_stage_program(sous_phase, transition_ready=transition_ready)
    surface_bilan_max = float(policy.get("surface_bilan_max") or 2.0)
    pluie_24h_max = float(policy.get("pluie_24h_max") or 1.0)
    pluie_demain_max = float(policy.get("pluie_demain_max") or 1.0)
    pluie_probabilite_max = float(policy.get("pluie_probabilite_max") or 70.0)
    temperature_min = float(policy.get("temperature_min") or 8.0)
    saturation_level = (
        humidite_sol
        if humidite_sol is not None
        else bilan_hydrique_mm
    )
    recent_watering_relief = min(max(mm_detected_24h, 0.0), 3.0)
    saturation_limit = 85.0 if humidite_sol is not None else surface_bilan_max + recent_watering_relief
    surface_sec = (
        pluie_24h <= pluie_24h_max
        and pluie_demain <= pluie_demain_max
        and pluie_probabilite_24h < pluie_probabilite_max
        and saturation_level < saturation_limit
        and temperature > temperature_min
    )
    seuil_declencheur = (
        f"policy={policy_key}, pluie_24h<={pluie_24h_max:.1f}, pluie_demain<={pluie_demain_max:.1f}, "
        f"pluie_probabilite_24h<{pluie_probabilite_max:.0f}%, saturation<{saturation_limit:.1f}, "
        f"temperature>{temperature_min:.1f}"
    )
    allowed = surface_sec
    block_reason = None
    reason = (
        "cycle de surface autorisé, humidité à maintenir."
        if allowed
        else "pluie récente ou prévue, stratégie semis_frequent reportée."
    )
    # Guard germination basse température
    WATERING_STAGE_GERMINATION_KEY = "Germination"
    WATERING_STAGE_LEVEE_KEY = "Levée"
    if sous_phase in {WATERING_STAGE_GERMINATION_KEY, WATERING_STAGE_LEVEE_KEY} and temperature <= 8.0:
        allowed = False
        block_reason = "temperature_trop_basse_germination"
        reason = "Germination bloquée: température trop basse pour la levée."
    if not allowed:
        block_reason = "pluie_prevue_suffisante"
        if temperature <= temperature_min:
            block_reason = "temperature_trop_basse"
            reason = "température trop basse, cycle de surface reporté."
        elif saturation_level >= saturation_limit:
            block_reason = "sol_deja_humide"
            reason = "sol déjà trop humide pour un micro-cycle de surface."
        elif pluie_probabilite_24h >= pluie_probabilite_max:
            block_reason = "pluie_probabilite_elevee"
            reason = "pluie probable à court terme, cycle de surface reporté."
        elif pluie_24h >= pluie_24h_max or pluie_demain >= pluie_demain_max:
            block_reason = "pluie_prevue_suffisante"
            reason = "pluie récente ou prévue, stratégie semis_frequent reportée."

    cycle_mm = stage_program.surface_cycle_mm_optimal
    daily_cycles_target = max(stage_program.daily_cycles_min, min(stage_program.daily_cycles_max, stage_program.daily_cycles_min))
    cycle_spacing_minutes = stage_program.cycle_spacing_minutes_max
    if temperature >= 28.0 or (vent or 0.0) >= 15.0 or humidite <= 45.0:
        cycle_mm = min(stage_program.surface_cycle_mm_max, cycle_mm + 0.5)
        daily_cycles_target = min(stage_program.daily_cycles_max, daily_cycles_target + 1)
        cycle_spacing_minutes = stage_program.cycle_spacing_minutes_min
    elif humidite >= 70.0 or pluie_24h > 0.5 or pluie_demain > 0.5:
        cycle_mm = max(stage_program.surface_cycle_mm_min, cycle_mm - 0.5)
        daily_cycles_target = max(stage_program.daily_cycles_min, daily_cycles_target - 1)
        cycle_spacing_minutes = stage_program.cycle_spacing_minutes_max
    elif temperature <= 14.0:
        cycle_mm = max(stage_program.surface_cycle_mm_min, cycle_mm - 0.5)
        cycle_spacing_minutes = max(stage_program.cycle_spacing_minutes_min, stage_program.cycle_spacing_minutes_min)
    cycle_mm = round(_clamp(cycle_mm, stage_program.surface_cycle_mm_min, stage_program.surface_cycle_mm_max), 1)
    runoff_risk = stage_program.runoff_risk
    if soil_profile == "argileux" and cycle_mm >= 2.5:
        runoff_risk = "eleve"
    elif humidite >= 75.0 or pluie_24h >= 0.5:
        runoff_risk = "modere"
    dryness_risk = stage_program.surface_dryness_risk
    if temperature >= 30.0 or (vent or 0.0) >= 20.0 or humidite <= 35.0:
        dryness_risk = "eleve"
    elif temperature >= 26.0 or (vent or 0.0) >= 12.0 or humidite <= 45.0:
        dryness_risk = "modere"

    return {
        "allowed": not bool(block_reason),
        "surface_sec": surface_sec,
        "seuil_declencheur": seuil_declencheur,
        "block_reason": block_reason,
        "reason": reason,
        "pluie_probabilite_24h": round(pluie_probabilite_24h, 1),
        "mm_detected_24h": round(mm_detected_24h, 1),
        "policy_key": policy_key,
        "watering_stage": watering_stage,
        "watering_strategy": WATERING_STRATEGY_SEMIS_FREQUENT,
        "objective_scope": OBJECTIVE_SCOPE_SURFACE_CYCLE,
        "surface_cycle_mm_min": round(stage_program.surface_cycle_mm_min, 1),
        "surface_cycle_mm_max": round(stage_program.surface_cycle_mm_max, 1),
        "surface_cycle_mm": cycle_mm,
        "daily_cycles_target": daily_cycles_target,
        "cycle_spacing_minutes": cycle_spacing_minutes,
        "surface_moisture_target": stage_program.surface_moisture_target,
        "surface_dryness_risk": dryness_risk,
        "runoff_risk": runoff_risk,
        "transition_ready": transition_ready,
        "surface_saturation_level": round(float(saturation_level), 1),
        "surface_saturation_limit": round(float(saturation_limit), 1),
    }


def _policy_weather_inputs(
    *,
    pluie_proche: bool = False,
    pluie_compensatrice: bool = False,
    temperature: float | None = None,
    soil_humidity_state: str | None = None,
    prolonged_drought: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "heavy_rain_expected": pluie_proche,
        "rain_compensating": pluie_compensatrice,
    }
    if temperature is not None:
        payload["temperature_c"] = temperature
    if soil_humidity_state is not None:
        payload["soil_humidity_state"] = soil_humidity_state
    if prolonged_drought:
        payload["prolonged_drought"] = True
    return payload


def _resolve_phase_policy(
    *,
    phase_dominante: str,
    sous_phase: str,
    pluie_proche: bool = False,
    pluie_compensatrice: bool = False,
    temperature: float | None = None,
    humidite: float | None = None,
    saturation_block: bool = False,
    application_type: str | None = None,
    prolonged_drought: bool = False,
) -> Any:
    soil_humidity_state = None
    if phase_dominante == "Scarification":
        soil_humidity_state = _scarification_soil_humidity_state(
            saturation_block=saturation_block,
            humidite=humidite or 0.0,
        )
    return resolve_watering_policy(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        application_type=application_type,
        weather=_policy_weather_inputs(
            pluie_proche=pluie_proche,
            pluie_compensatrice=pluie_compensatrice,
            temperature=temperature,
            soil_humidity_state=soil_humidity_state,
            prolonged_drought=prolonged_drought,
        ),
    )


def _normalize_public_block_reason(policy_reason: str | None) -> str | None:
    if policy_reason == "blocked_by_default":
        return "mode_bloque"
    if policy_reason == "heavy_rain_expected":
        return "pluie_prevue_suffisante"
    if policy_reason == "rain_compensating":
        return "pluie_prevue_suffisante"
    if policy_reason == "temperature_below_minimum":
        return "temperature_trop_basse"
    if policy_reason == "soil_humidity_state_mismatch":
        return "sol_non_adapte"
    return policy_reason


def _build_fractionnement_payload(
    *,
    passages: int,
    pause_minutes: int,
    mm_final: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "enabled": passages > 1,
        "passages": passages,
        "pause_minutes": pause_minutes,
        "max_mm_per_passage": round(mm_final / passages, 1) if passages > 0 and mm_final > 0 else 0.0,
        "reason": reason,
    }


def _build_profile_payload(
    *,
    deficit_mm_brut: float,
    deficit_mm_ajuste: float,
    mm_cible: float,
    mm_final: float,
    mm_detected: float,
    type_arrosage: str,
    arrosage_recommande: bool,
    arrosage_auto_autorise: bool,
    arrosage_conseille: str,
    passages: int,
    pause_minutes: int,
    fractionnement_reason: str,
    niveau_confiance: str,
    confidence_score: int | None,
    confidence_reasons: list[str],
    raison_decision_base: str,
    block_reason: str | None,
    fenetre_optimale: str,
    niveau_action: str,
    risque_gazon: str,
    heat_stress_level: str,
    heat_stress_phase: str,
    morning_start_minute: int,
    acceptable_end_minute: int,
    morning_end_minute: int,
    temperature_band: str,
    evening_allowed: bool,
    recent_watering_count: int,
    recent_watering_mm_7j: float,
    guardrail_min_mm: float,
    guardrail_max_mm: float,
    guardrail_reason: str,
    watering_strategy: str = WATERING_STRATEGY_ADULT_DEEP,
    objective_scope: str = OBJECTIVE_SCOPE_GLOBAL_SURFACE,
    watering_stage: str = WATERING_STAGE_NORMAL,
    surface_cycle_mm: float | None = None,
    daily_cycles_target: int | None = None,
    cycle_spacing_minutes: int | None = None,
    surface_moisture_target: str | None = None,
    surface_dryness_risk: str | None = None,
    runoff_risk: str | None = None,
    surface_saturation_level: float | None = None,
    surface_saturation_limit: float | None = None,
    seeding_transition_ready: bool | None = None,
    seeding_block_reason: str | None = None,
    seasonal_profile: dict[str, Any] | None = None,
    cooldown_24h_hours: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    type_arrosage, arrosage_conseille = normalize_watering_contract(type_arrosage, arrosage_conseille)
    payload = {
        "deficit_brut_mm": round(deficit_mm_brut, 1),
        "deficit_mm_brut": round(deficit_mm_brut, 1),
        "deficit_mm_ajuste": round(deficit_mm_ajuste, 1),
        "mm_cible": round(mm_cible, 1),
        "mm_final_recommande": round(mm_final, 1),
        "mm_final": round(mm_final, 1),
        "mm_requested": round(mm_cible, 1),
        "mm_applied": round(mm_final, 1),
        "mm_detected": round(mm_detected, 1),
        "type_arrosage": type_arrosage,
        "arrosage_recommande": arrosage_recommande,
        "arrosage_auto_autorise": arrosage_auto_autorise,
        "arrosage_conseille": arrosage_conseille,
        "watering_passages": passages,
        "watering_pause_minutes": pause_minutes,
        "fractionnement": _build_fractionnement_payload(
            passages=passages,
            pause_minutes=pause_minutes,
            mm_final=mm_final,
            reason=fractionnement_reason,
        ),
        "niveau_confiance": niveau_confiance,
        "confidence_score": confidence_score,
        "confidence_reasons": confidence_reasons,
        "raison_decision_base": raison_decision_base,
        "block_reason": block_reason,
        "fenetre_optimale": fenetre_optimale,
        "niveau_action": niveau_action,
        "risque_gazon": risque_gazon,
        "heat_stress_level": heat_stress_level,
        "heat_stress_phase": heat_stress_phase,
        "watering_window_start_minute": morning_start_minute,
        "watering_window_end_minute": acceptable_end_minute,
        "watering_window_optimal_start_minute": morning_start_minute,
        "watering_window_optimal_end_minute": morning_end_minute,
        "watering_window_acceptable_end_minute": acceptable_end_minute,
        "watering_evening_start_minute": EVENING_START_HOUR * 60,
        "watering_evening_end_minute": EVENING_END_HOUR * 60,
        "watering_window_profile": temperature_band,
        "watering_evening_allowed": evening_allowed,
        "recent_watering_count_7j": recent_watering_count,
        "recent_watering_mm_7j": recent_watering_mm_7j,
        "weekly_guardrail_mm_min": guardrail_min_mm,
        "weekly_guardrail_mm_max": guardrail_max_mm,
        "weekly_guardrail_reason": guardrail_reason,
        "watering_strategy": watering_strategy,
        "objective_scope": objective_scope,
        "watering_stage": watering_stage,
        "surface_cycle_mm": round(surface_cycle_mm, 1) if surface_cycle_mm is not None else None,
        "daily_cycles_target": daily_cycles_target,
        "cycle_spacing_minutes": cycle_spacing_minutes,
        "surface_moisture_target": surface_moisture_target,
        "surface_dryness_risk": surface_dryness_risk,
        "runoff_risk": runoff_risk,
        "surface_saturation_level": round(surface_saturation_level, 1) if surface_saturation_level is not None else None,
        "surface_saturation_limit": round(surface_saturation_limit, 1) if surface_saturation_limit is not None else None,
        "seeding_transition_ready": seeding_transition_ready,
        "seeding_block_reason": seeding_block_reason,
        "cooldown_24h_hours": round(cooldown_24h_hours, 1) if cooldown_24h_hours is not None else None,
    }
    if seasonal_profile:
        payload.update(seasonal_profile)
    if extra:
        payload.update(extra)
    return payload


def _current_datetime() -> datetime:
    if dt_util is not None:
        now_getter = getattr(dt_util, "now", None)
        if callable(now_getter):
            current = now_getter()
            if isinstance(current, datetime):
                return current
    return datetime.now().astimezone()


def _current_date() -> date:
    return _current_datetime().date()


def _rain_signals(
    *,
    objective_reference_mm: float,
    pluie_24h: float,
    pluie_demain: float,
    pluie_j2: float,
    pluie_3j: float,
    pluie_probabilite_max_3j: float,
) -> tuple[bool, bool]:
    # Confiance J+1 = 70%, J+2 = 45%, J+3 = 30%
    pluie_demain_effective = pluie_demain * 0.70
    pluie_j2_effective = pluie_j2 * 0.45
    pluie_3j_effective = pluie_3j * 0.30
    pluie_compensatrice = (
        pluie_demain_effective >= max(2.0, objective_reference_mm * 0.8)
        or pluie_j2_effective >= max(2.0, objective_reference_mm * 0.8)
        or pluie_3j_effective >= max(4.0, objective_reference_mm * 1.2)
        or pluie_probabilite_max_3j >= 80.0
    )
    pluie_proche = (
        pluie_24h >= 4.0
        or pluie_demain_effective >= 4.0
        or pluie_j2_effective >= 4.0
        or pluie_3j_effective >= 6.0
        or pluie_probabilite_max_3j >= 80.0
    )
    return pluie_compensatrice, pluie_proche


def _morning_window_bounds(phase_dominante: str, temperature: float | None) -> tuple[int, int, int, str]:
    """Retourne une fenêtre matinale explicite: optimale 4-8h, acceptable jusqu'à 10h."""
    band = _temperature_band(temperature)
    optimal_start = OPTIMAL_MORNING_START_HOUR * 60
    optimal_end = OPTIMAL_MORNING_END_HOUR * 60
    acceptable_end = ACCEPTABLE_MORNING_END_HOUR * 60
    if phase_dominante == "Sursemis" and band == "hot":
        acceptable_end = ACCEPTABLE_MORNING_END_HOUR * 60
    return optimal_start, optimal_end, acceptable_end, band


def _semis_window_bounds(
    *,
    temperature: float | None,
    humidite: float | None,
    vent: float | None,
    pluie_24h: float,
    pluie_demain: float,
) -> tuple[int, int, int, str]:
    """Retourne une fenêtre semis qui autorise les micro-cycles de journée sans relâcher les garde-fous."""
    optimal_start = SEMIS_WINDOW_START_HOUR * 60
    optimal_end = SEMIS_WINDOW_END_HOUR * 60
    acceptable_end = SEMIS_WINDOW_END_HOUR * 60
    band = _temperature_band(temperature)

    vent_value = float(vent or 0.0)
    humidite_value = float(humidite or 0.0)

    if pluie_24h >= 0.5 or pluie_demain >= 0.5 or humidite_value >= 70.0:
        acceptable_end = min(acceptable_end, 16 * 60)
    elif temperature is not None and temperature >= 30.0:
        acceptable_end = min(acceptable_end, 16 * 60)
    elif temperature is not None and temperature >= 26.0:
        acceptable_end = min(acceptable_end, 17 * 60)

    if vent_value >= 18.0:
        acceptable_end = min(acceptable_end, 16 * 60)
    elif vent_value >= 12.0:
        acceptable_end = min(acceptable_end, 17 * 60)

    if humidite_value <= 35.0:
        acceptable_end = min(acceptable_end, 17 * 60)

    return optimal_start, optimal_end, acceptable_end, band


def _heat_stress_level(
    temperature: float | None,
    etp: float | None,
    humidite: float | None,
    weather_profile: dict[str, Any] | None,
    deficit_mm_brut: float,
) -> str:
    weather_profile = weather_profile or {}
    temperature = temperature if temperature is not None else _to_float(weather_profile.get("weather_temperature"))
    etp = etp if etp is not None else 0.0
    humidite = humidite if humidite is not None else _to_float(weather_profile.get("weather_humidity"))
    vent = _to_float(weather_profile.get("weather_wind_speed"))
    pluie_24h = _to_float(weather_profile.get("weather_precipitation")) or 0.0
    pluie_prob = _to_float(weather_profile.get("weather_precipitation_probability")) or 0.0

    score = 0
    temperature = temperature if temperature is not None else 0.0
    if temperature >= 38:
        score += 4
    elif temperature >= 34:
        score += 3
    elif temperature >= 30:
        score += 2
    elif temperature >= 27:
        score += 1

    if etp >= 5:
        score += 3
    elif etp >= 4:
        score += 2
    elif etp >= 3:
        score += 1

    if humidite is not None:
        if humidite <= 30:
            score += 2
        elif humidite <= 40:
            score += 1

    if vent is not None:
        if vent >= 25:
            score += 2
        elif vent >= 15:
            score += 1

    if pluie_24h <= 0 and pluie_prob <= 20:
        score += 1
    if deficit_mm_brut >= 8:
        score += 1

    if score >= 7:
        return "extreme"
    if score >= 5:
        return "canicule"
    if score >= 3:
        return "vigilance"
    return "normal"


def _evening_window_allowed(
    temperature: float | None,
    humidite: float | None,
    water_balance: dict[str, float],
    objectif_mm: float,
    heat_stress_level: str = "normal",
    fungal_risk_level: str | None = None,
) -> bool:
    # Bloquer fenêtre soir avril-septembre sauf déficit critique
    today = _current_date()
    month = today.month
    if month in {4, 5, 6, 7, 8, 9}:
        CRITICAL_THRESHOLD = -3.0
        bilan = _reference_hydric_balance_mm(water_balance)
        if bilan > CRITICAL_THRESHOLD:
            return False  # Pas de soir en saison de végétation sauf urgence
    temperature = temperature if temperature is not None else 0.0
    humidite = humidite if humidite is not None else 0.0
    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)

    # Blocage supplémentaire si risque fongique élevé
    if fungal_risk_level in {"moderate", "high"}:
        return False
    if heat_stress_level == "extreme":
        return False
    if temperature < 24:
        return False
    if humidite > 65:
        return False
    if arrosage_recent > 0.25:
        return False
    if bilan_hydrique_mm >= -0.3 and deficit_3j <= 0.8:
        return False
    return objectif_mm > 0


def _season_label(today: date) -> str:
    return str(get_seasonal_profile(today).get("season") or "shoulder")


def _seasonal_profile_payload(today: date) -> dict[str, Any]:
    profile = get_seasonal_profile(today)
    return {
        "season_label": profile.get("season"),
        "season_phase": profile.get("season_phase"),
        "month_profile": profile.get("month_profile"),
        "watering_bias": profile.get("watering_bias"),
        "mowing_bias": profile.get("mowing_bias"),
        "intervention_bias": profile.get("intervention_bias"),
        "risk_bias": profile.get("risk_bias"),
    }


def _heat_stress_phase(
    heat_stress_level: str,
    temperature: float | None,
    etp: float | None,
    pluie_demain: float,
    pluie_3j: float,
    recent_watering_count: int,
    recent_watering_mm_7j: float,
) -> str:
    if heat_stress_level == "normal":
        return "normal"
    if pluie_demain >= 4.0 or pluie_3j >= 6.0:
        return "sortie_de_canicule"
    if heat_stress_level == "extreme":
        if temperature is not None and temperature >= 34 and (etp or 0.0) >= 5.0:
            if recent_watering_count <= 1 or recent_watering_mm_7j < 6.0:
                return "canicule_prolongee"
        return "canicule_courte"
    if heat_stress_level == "canicule":
        if temperature is not None and temperature >= 31 and (etp or 0.0) >= 4.0:
            if recent_watering_count <= 2 and recent_watering_mm_7j < 10.0:
                return "canicule_prolongee"
        return "canicule_courte"
    if temperature is not None and temperature >= 30 and (etp or 0.0) >= 4.0:
        return "canicule_courte"
    return "normal"


def _dynamic_weekly_guardrail(
    today: date,
    phase_dominante: str,
    heat_stress_phase: str,
    soil_profile: str,
) -> tuple[float, float, str]:
    seasonal_profile = get_seasonal_profile(today)
    season = str(seasonal_profile.get("season") or "shoulder")
    season_phase = str(seasonal_profile.get("season_phase") or "normal")
    month_profile = str(seasonal_profile.get("month_profile") or "stable")
    minimum = float(seasonal_profile.get("weekly_budget_min_mm") or 19.0)
    maximum = float(seasonal_profile.get("weekly_budget_max_mm") or 24.0)

    if soil_profile == "sableux":
        minimum += 1.0
        maximum += 1.0
    elif soil_profile == "argileux":
        minimum -= 1.0
        maximum -= 0.5

    if phase_dominante == "Sursemis":
        minimum = max(0.5, minimum - 8.0)
        maximum = max(minimum + 1.0, maximum - 8.0)
    elif phase_dominante in {"Fertilisation", "Biostimulant"}:
        maximum = min(22.0, maximum)

    if heat_stress_phase == "canicule_prolongee":
        minimum += 2.0
        maximum += 3.0
    elif heat_stress_phase == "canicule_courte":
        minimum += 1.0
        maximum += 1.5
    elif heat_stress_phase == "sortie_de_canicule":
        minimum = max(15.0, minimum - 1.0)
        maximum = max(minimum + 4.0, maximum - 0.5)

    minimum = round(_clamp(minimum, 12.0, 28.0), 1)
    maximum = round(_clamp(maximum, minimum + 4.0, 28.0), 1)
    return (
        minimum,
        maximum,
        (
            f"saison={season}; phase_saison={season_phase}; mois={month_profile}; "
            f"sol={soil_profile}; phase={heat_stress_phase}"
        ),
    )


def _confidence_assessment(
    *,
    phase_dominante: str,
    temperature: float | None,
    humidite: float | None,
    etp: float | None,
    weather_profile: dict[str, Any] | None,
    soil_profile: str,
    heat_stress_level: str,
    heat_stress_phase: str,
    block_reason: str | None,
    mm_final: float,
) -> tuple[int, str, list[str]]:
    score = 100
    reasons: list[str] = []

    if temperature is None:
        score -= 12
        reasons.append("température manquante")
    if etp is None:
        score -= 12
        reasons.append("ETP manquante")
    if humidite is None:
        score -= 8
        reasons.append("humidité manquante")

    weather_profile = weather_profile or {}
    if not weather_profile:
        score -= 6
        reasons.append("météo partielle")
    if weather_profile.get("weather_condition") is None:
        score -= 2
    if weather_profile.get("weather_precipitation_probability") is None:
        score -= 3

    if heat_stress_level in {"canicule", "extreme"}:
        score -= 4
        reasons.append(f"stress thermique={heat_stress_level}")
    if heat_stress_phase in {"canicule_prolongee", "sortie_de_canicule"}:
        score -= 3
        reasons.append(f"phase thermique={heat_stress_phase}")

    if soil_profile not in {"sableux", "limoneux", "argileux"}:
        score -= 4
        reasons.append("type de sol incertain")

    if phase_dominante in {"Traitement", "Hivernage"}:
        score += 0
    elif phase_dominante == "Sursemis":
        score -= 2
        reasons.append("sursemis: besoin plus variable")

    if block_reason in {"pluie_active", "mode_bloque"}:
        score += 0
    elif block_reason is not None:
        score -= 2
        reasons.append(f"blocage={block_reason}")

    if mm_final <= 0:
        score -= 3

    score = int(max(0.0, min(score, 100.0)))
    if score >= 75:
        level = "high"
    elif score >= 45:
        level = "medium"
    else:
        level = "low"
    return score, level, reasons


def _risk_rank(level: str) -> int:
    return {"faible": 0, "modere": 1, "eleve": 2}.get(level, 0)


def _risk_from_rank(rank: int) -> str:
    return {0: "faible", 1: "modere", 2: "eleve"}.get(max(0, min(rank, 2)), "faible")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _build_guidance_window_payload(
    *,
    risque_gazon: str,
    niveau_action: str,
    fenetre_optimale: str,
    heat_stress_level: str,
    heat_stress_phase: str,
    optimal_start_minute: int,
    acceptable_end_minute: int,
    optimal_end_minute: int,
    temperature_band: str,
    evening_allowed: bool,
) -> dict[str, Any]:
    return {
        "niveau_action": niveau_action,
        "fenetre_optimale": fenetre_optimale,
        "risque_gazon": risque_gazon,
        "heat_stress_level": heat_stress_level,
        "watering_window_start_minute": optimal_start_minute,
        "watering_window_end_minute": acceptable_end_minute,
        "watering_window_optimal_start_minute": optimal_start_minute,
        "watering_window_optimal_end_minute": optimal_end_minute,
        "watering_window_acceptable_end_minute": acceptable_end_minute,
        "watering_evening_start_minute": EVENING_START_HOUR * 60,
        "watering_evening_end_minute": EVENING_END_HOUR * 60,
        "watering_window_profile": temperature_band,
        "watering_evening_allowed": evening_allowed,
        "heat_stress_phase": heat_stress_phase,
    }


def compute_watering_profile(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    today: date | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
    humidite: float | None = None,
    temperature: float | None = None,
    etp: float | None = None,
    type_sol: str = "limoneux",
    weather_profile: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    sous_phase_age_days: int | None = None,
    sous_phase_progression: float | None = None,
    hauteur_gazon: float | None = None,
    transition_ready: bool = False,
    application_type: str | None = None,
) -> dict[str, Any]:
    today = today or _current_date()
    weather_profile = weather_profile or {}
    history = [item for item in (history or []) if isinstance(item, dict)]
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0
    pluie_24h = pluie_24h or 0.0
    pluie_probabilite_24h = _to_float(weather_profile.get("weather_precipitation_probability"))
    pluie_probabilite_24h = pluie_probabilite_24h if pluie_probabilite_24h is not None else 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    vent = _to_float(weather_profile.get("weather_wind_speed"))
    soil_profile = (type_sol or "limoneux").strip().lower()
    recent_watering_count = compute_recent_watering_count(history, today=today, days=7) if history else 0
    latest_watering_dt = _latest_watering_datetime(history) if history else None
    now = _current_datetime()
    cooldown_24h_hours: float | None = None
    cooldown_24h_active = False
    if phase_dominante == "Normal" and latest_watering_dt is not None:
        delta_hours = (now - latest_watering_dt.astimezone(now.tzinfo)).total_seconds() / 3600.0
        if delta_hours >= 0:
            cooldown_24h_hours = delta_hours
            cooldown_24h_active = delta_hours < 24.0

    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    recent_watering_mm_7j = float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0)
    deficit_mm_brut = max(0.0, max(deficit_jour, deficit_3j, deficit_7j))
    pluie_support = max(
        0.0,
        (pluie_24h * 0.35)
        + (pluie_demain * 0.35)
        + (pluie_j2 * 0.2)
        + (pluie_3j * 0.1),
    )
    historique_support = min(recent_watering_mm_7j * 0.2, deficit_mm_brut * 0.5)
    humidite_penalty = 0.0
    if humidite >= 85:
        humidite_penalty = deficit_mm_brut * 0.2
    elif humidite >= 75:
        humidite_penalty = deficit_mm_brut * 0.1
    deficit_mm_ajuste = max(0.0, deficit_mm_brut - pluie_support - historique_support - humidite_penalty)
    heat_stress_level = _heat_stress_level(
        temperature=temperature,
        etp=etp,
        humidite=humidite,
        weather_profile=weather_profile,
        deficit_mm_brut=deficit_mm_brut,
    )
    heat_stress_phase = _heat_stress_phase(
        heat_stress_level=heat_stress_level,
        temperature=temperature,
        etp=etp,
        pluie_demain=pluie_demain,
        pluie_3j=pluie_3j,
        recent_watering_count=recent_watering_count,
        recent_watering_mm_7j=recent_watering_mm_7j,
    )
    guardrail_min_mm, guardrail_max_mm, guardrail_reason = _dynamic_weekly_guardrail(
        today=today,
        phase_dominante=phase_dominante,
        heat_stress_phase=heat_stress_phase,
        soil_profile=soil_profile,
    )
    seasonal_profile_payload = _seasonal_profile_payload(today)
    optimal_start_minute, optimal_end_minute, acceptable_end_minute, temperature_band = _morning_window_bounds(
        phase_dominante=phase_dominante,
        temperature=temperature,
    )
    if phase_dominante == "Hivernage" or is_active_rain_weather(weather_profile):
        if phase_dominante == "Hivernage":
            resolved_policy = _resolve_phase_policy(
                phase_dominante=phase_dominante,
                sous_phase=sous_phase,
                prolonged_drought=False,
            )
            block_reason = _normalize_public_block_reason(resolved_policy.blocking.reason) or "mode_bloque"
        else:
            block_reason = "pluie_active"
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=0.0,
        )
        return _build_profile_payload(
            deficit_mm_brut=0.0,
            deficit_mm_ajuste=0.0,
            mm_cible=0.0,
            mm_final=0.0,
            mm_detected=recent_watering_mm_7j,
            type_arrosage="bloque",
            arrosage_recommande=False,
            arrosage_auto_autorise=False,
            arrosage_conseille="personnalise",
            passages=1,
            pause_minutes=0,
            fractionnement_reason=block_reason,
            niveau_confiance=confidence_level,
            confidence_score=confidence_score,
            confidence_reasons=confidence_reasons,
            raison_decision_base=f"Phase {phase_dominante}: arrosage bloqué.",
            block_reason=block_reason,
            fenetre_optimale="attendre",
            niveau_action="surveiller",
            risque_gazon="faible",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            morning_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            morning_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=False,
            recent_watering_count=recent_watering_count,
            recent_watering_mm_7j=recent_watering_mm_7j,
            guardrail_min_mm=guardrail_min_mm,
            guardrail_max_mm=guardrail_max_mm,
            guardrail_reason=guardrail_reason,
            seasonal_profile=seasonal_profile_payload,
            cooldown_24h_hours=cooldown_24h_hours,
        )

    besoin_court, besoin_tendance, pression_hydrique = _hydraulic_pressure(
        bilan_hydrique_mm, deficit_3j, deficit_7j
    )
    pluie_compensatrice, pluie_proche = _rain_signals(
        objective_reference_mm=deficit_mm_brut,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
    )
    morning_start_minute = optimal_start_minute
    morning_end_minute = optimal_end_minute
    now_hour = now.hour
    now_minutes = now.hour * 60 + now.minute
    saturation_block = phase_dominante != "Sursemis" and bilan_hydrique_mm > SATURATION_BILAN_HYDRIQUE_MM
    evening_allowed = _evening_window_allowed(
        temperature=temperature,
        humidite=humidite,
        water_balance=water_balance,
        objectif_mm=deficit_mm_brut,
        heat_stress_level=heat_stress_level,
    )
    if phase_dominante == "Sursemis":
        optimal_start_minute, optimal_end_minute, acceptable_end_minute, temperature_band = _semis_window_bounds(
            temperature=temperature,
            humidite=humidite,
            vent=vent,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
        )
        resolved_policy = _resolve_phase_policy(
            phase_dominante=phase_dominante,
            sous_phase=sous_phase,
        )
        policy_key, sursemis_policy, transition_ready, tonte_count = _select_sursemis_policy(
            history=history,
            sous_phase=sous_phase,
            sous_phase_age_days=sous_phase_age_days,
            sous_phase_progression=sous_phase_progression,
            hauteur_gazon=hauteur_gazon,
            water_balance=water_balance,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            pluie_probabilite_24h=pluie_probabilite_24h,
            temperature=temperature,
        )
        sursemis_state = _sursemis_micro_apport_decision(
            policy=sursemis_policy,
            sous_phase=sous_phase,
            transition_ready=transition_ready,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            pluie_probabilite_24h=pluie_probabilite_24h,
            bilan_hydrique_mm=_reference_hydric_balance_mm(water_balance),
            mm_detected_24h=float(water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
            temperature=temperature,
            humidite=humidite,
            humidite_sol=(
                _to_float(water_balance.get("humidite_sol"))
                if water_balance.get("humidite_sol") is not None
                else None
            ),
            reserve_stock_mm=_to_float(water_balance.get("reserve_stock_mm")),
            reserve_actuelle_mm=_to_float(water_balance.get("reserve_actuelle_mm")),
            vent=vent,
            soil_profile=soil_profile,
        )
        mm_cible = float(sursemis_state.get("surface_cycle_mm") or 0.0) if sursemis_state["allowed"] else 0.0
        block_reason = sursemis_state["block_reason"]
        mm_final = mm_cible
        watering_strategy = str(sursemis_state.get("watering_strategy") or WATERING_STRATEGY_SEMIS_FREQUENT)
        objective_scope = str(sursemis_state.get("objective_scope") or OBJECTIVE_SCOPE_SURFACE_CYCLE)
        watering_stage = str(sursemis_state.get("watering_stage") or WATERING_STAGE_LEVEE)
        surface_cycle_mm = float(sursemis_state.get("surface_cycle_mm") or mm_cible or 0.0)
        daily_cycles_target = int(sursemis_state.get("daily_cycles_target") or 1)
        cycle_spacing_minutes = int(sursemis_state.get("cycle_spacing_minutes") or 0)
        type_arrosage = "manuel_frequent" if mm_final > 0 else ("bloque" if block_reason else "aucune_action")
        arrosage_auto = False
        passages = 1
        pause_minutes = 0
        if policy_key == "reprise_transition":
            if not sursemis_state["allowed"]:
                fenetre_optimale = "attendre"
            elif now_minutes < optimal_start_minute:
                fenetre_optimale = "ce_matin"
            elif now_minutes < acceptable_end_minute and (vent is None or vent < 15):
                fenetre_optimale = "maintenant"
            else:
                fenetre_optimale = "attendre"
            niveau_action = "surveiller"
            risque_gazon = "modere" if transition_ready else "faible"
        elif policy_key == "germination_stricte":
            fenetre_optimale = "apres_pluie" if pluie_compensatrice or pluie_proche else (
                "ce_matin"
                if now_minutes < optimal_start_minute
                else "maintenant"
                if now_minutes < acceptable_end_minute and (vent is None or vent < 15)
                else "demain_matin"
            )
            niveau_action = "critique" if bilan_hydrique_mm <= -1.0 or pression_hydrique >= 1.8 else "a_faire"
            risque_gazon = "eleve" if bilan_hydrique_mm <= -1.0 or pression_hydrique >= 2.0 else "modere"
        else:
            fenetre_optimale = "apres_pluie" if pluie_compensatrice or pluie_proche else (
                "ce_matin"
                if now_minutes < optimal_start_minute
                else "maintenant"
                if now_minutes < acceptable_end_minute and (vent is None or vent < 15)
                else "demain_matin"
            )
            niveau_action = "critique" if pression_hydrique >= 2.2 or bilan_hydrique_mm <= -1.5 else "a_faire"
            risque_gazon = "eleve" if bilan_hydrique_mm <= -1.5 or pression_hydrique >= 2.5 else "modere"
        if heat_stress_level in {"canicule", "extreme"}:
            risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
        if vent is not None and vent >= 20:
            risque_gazon = "eleve"
        if hauteur_gazon is not None and hauteur_gazon >= 12:
            risque_gazon = "eleve"
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=mm_final,
        )
        return _build_profile_payload(
            deficit_mm_brut=deficit_mm_brut,
            deficit_mm_ajuste=deficit_mm_ajuste,
            mm_cible=mm_cible,
            mm_final=mm_final,
            mm_detected=recent_watering_mm_7j,
            type_arrosage=type_arrosage,
            arrosage_recommande=mm_final > 0,
            arrosage_auto_autorise=False,
            arrosage_conseille="personnalise",
            passages=passages,
            pause_minutes=pause_minutes,
            fractionnement_reason="semis_surface_cycle" if mm_final > 0 else "sursemis_aucune_action",
            niveau_confiance=confidence_level,
            confidence_score=confidence_score,
            confidence_reasons=confidence_reasons,
            raison_decision_base=(
                f"Sursemis / {sous_phase}: stratégie semis_frequent en cycle de surface, "
                f"{daily_cycles_target} cycle(s)/jour cible(s), {cycle_spacing_minutes} min entre cycles."
            ),
            block_reason=block_reason,
            fenetre_optimale=fenetre_optimale,
            niveau_action=niveau_action,
            risque_gazon=risque_gazon,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            morning_start_minute=morning_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            morning_end_minute=morning_end_minute,
            temperature_band=temperature_band,
            evening_allowed=False,
            recent_watering_count=recent_watering_count,
            recent_watering_mm_7j=recent_watering_mm_7j,
            guardrail_min_mm=guardrail_min_mm,
            guardrail_max_mm=guardrail_max_mm,
            guardrail_reason=guardrail_reason,
            watering_strategy=watering_strategy,
            objective_scope=objective_scope,
            watering_stage=watering_stage,
            surface_cycle_mm=surface_cycle_mm,
            daily_cycles_target=daily_cycles_target,
            cycle_spacing_minutes=cycle_spacing_minutes,
            surface_moisture_target=str(sursemis_state.get("surface_moisture_target") or ""),
            surface_dryness_risk=str(sursemis_state.get("surface_dryness_risk") or ""),
            runoff_risk=str(sursemis_state.get("runoff_risk") or ""),
            surface_saturation_level=sursemis_state.get("surface_saturation_level"),
            surface_saturation_limit=sursemis_state.get("surface_saturation_limit"),
            seeding_transition_ready=transition_ready,
            seeding_block_reason=block_reason,
            seasonal_profile=seasonal_profile_payload,
            cooldown_24h_hours=cooldown_24h_hours,
            extra={
                "mm_detected_24h": sursemis_state["mm_detected_24h"],
                "pluie_probabilite_24h": sursemis_state["pluie_probabilite_24h"],
                "surface_sec": sursemis_state["surface_sec"],
                "sursemis_micro_apport_allowed": sursemis_state["allowed"],
                "sursemis_block_reason": block_reason,
                "sursemis_reason": sursemis_state["reason"],
                "sursemis_seuil_declencheur": sursemis_state["seuil_declencheur"],
                "sursemis_policy": policy_key,
                "sursemis_policy_mode": resolved_policy.selected_mode,
                "sursemis_override_behavior": resolved_policy.override_behavior,
                "sursemis_execution_preferred": (
                    resolved_policy.policy.execution.preferred if resolved_policy.policy.execution is not None else None
                ),
                "sursemis_daily_min_mm_per_cycle": (
                    resolved_policy.policy.daily_program.min_mm_per_cycle
                    if resolved_policy.policy.daily_program is not None
                    else None
                ),
                "sursemis_daily_max_mm_per_cycle": (
                    resolved_policy.policy.daily_program.max_mm_per_cycle
                    if resolved_policy.policy.daily_program is not None
                    else None
                ),
                "sursemis_daily_min_cycles": (
                    resolved_policy.policy.daily_program.min_cycles_per_day
                    if resolved_policy.policy.daily_program is not None
                    else None
                ),
                "sursemis_daily_max_cycles": (
                    resolved_policy.policy.daily_program.max_cycles_per_day
                    if resolved_policy.policy.daily_program is not None
                    else None
                ),
                "sursemis_transition_ready": transition_ready,
                "sursemis_tonte_count": tonte_count,
                "watering_strategy": watering_strategy,
                "objective_scope": objective_scope,
                "watering_stage": watering_stage,
                "surface_cycle_mm": surface_cycle_mm,
                "daily_cycles_target": daily_cycles_target,
                "cycle_spacing_minutes": cycle_spacing_minutes,
                "surface_moisture_target": sursemis_state.get("surface_moisture_target"),
                "surface_dryness_risk": sursemis_state.get("surface_dryness_risk"),
                "runoff_risk": sursemis_state.get("runoff_risk"),
                "surface_saturation_level": sursemis_state.get("surface_saturation_level"),
                "surface_saturation_limit": sursemis_state.get("surface_saturation_limit"),
                "seeding_transition_ready": transition_ready,
                "seeding_block_reason": block_reason,
            },
        )

    if phase_dominante == "Traitement":
        resolved_policy = _resolve_phase_policy(
            phase_dominante=phase_dominante,
            sous_phase=sous_phase,
            application_type=application_type,
            pluie_proche=pluie_proche,
            pluie_compensatrice=pluie_compensatrice,
        )
        target_range = resolved_policy.target_range
        minimum = target_range.min_mm if target_range is not None else 0.0
        maximum = target_range.max_mm if target_range is not None else 0.0
        mm_cible = 0.0
        block_reason = None
        if resolved_policy.blocking.is_blocked:
            block_reason = _normalize_public_block_reason(resolved_policy.blocking.reason)
        elif resolved_policy.override_behavior == "block_watering":
            block_reason = "application_foliaire"
        else:
            mm_cible = _clamp((besoin_court * 0.4) + (besoin_tendance * 0.08), minimum, maximum)
            mm_cible = _apply_watering_floor_constraints(mm_cible, deficit_mm_brut, minimum)
        mm_final = 0.0 if block_reason else mm_cible
        passages = 1 if mm_final <= 4.0 else 2
        pause_minutes = 25 if passages > 1 else 0
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=mm_final,
        )
        return _build_profile_payload(
            deficit_mm_brut=deficit_mm_brut,
            deficit_mm_ajuste=deficit_mm_ajuste,
            mm_cible=mm_cible,
            mm_final=mm_final,
            mm_detected=float(water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
            type_arrosage=(
                "bloque"
                if block_reason in {"application_type_required", "unsupported_application_type", "application_foliaire"}
                else "auto" if mm_final > 0 else "aucune_action"
            ),
            arrosage_recommande=mm_final > 0 and block_reason is None,
            arrosage_auto_autorise=mm_final > 0 and block_reason is None,
            arrosage_conseille="personnalise" if block_reason else "auto" if mm_final > 0 else "aucune_action",
            passages=passages,
            pause_minutes=pause_minutes,
            fractionnement_reason="managed_fractionation" if passages > 1 else "single_pass",
            niveau_confiance=confidence_level,
            confidence_score=confidence_score,
            confidence_reasons=confidence_reasons,
            raison_decision_base=f"Traitement ({application_type or 'inconnu'}): application dépendante du produit.",
            block_reason=block_reason,
            fenetre_optimale="ce_matin" if mm_final > 0 else "attendre",
            niveau_action="a_faire" if mm_final > 0 else "surveiller",
            risque_gazon="faible" if mm_final > 0 else "modere",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            morning_start_minute=morning_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            morning_end_minute=morning_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
            recent_watering_count=recent_watering_count,
            recent_watering_mm_7j=float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0),
            guardrail_min_mm=guardrail_min_mm,
            guardrail_max_mm=guardrail_max_mm,
            guardrail_reason=guardrail_reason,
            seasonal_profile=seasonal_profile_payload,
            extra={"application_type": application_type},
        )

    if phase_dominante == "Normal":
        resolved_policy = _resolve_phase_policy(
            phase_dominante=phase_dominante,
            sous_phase=sous_phase,
            pluie_proche=pluie_proche,
            pluie_compensatrice=pluie_compensatrice,
        )
        normal_weekly_range = resolved_policy.target_range
        normal_execution = resolved_policy.policy.execution
        weekly_min_mm = normal_weekly_range.min_mm if normal_weekly_range is not None else guardrail_min_mm
        weekly_max_mm = normal_weekly_range.max_mm if normal_weekly_range is not None else guardrail_max_mm
        min_session_mm = normal_execution.min_session_mm if normal_execution is not None else NORMAL_MIN_USEFUL_SESSION_MM
        max_session_mm = normal_execution.max_session_mm if normal_execution is not None else None
        rain_adjustment = min(pluie_support * 0.7, 5.0)
        guardrail_min_effective = round(
            _clamp(max(min_session_mm, guardrail_min_mm - rain_adjustment), weekly_min_mm, weekly_max_mm),
            1,
        )
        guardrail_max_effective = round(
            _clamp(
                max(guardrail_min_effective + 4.0, guardrail_max_mm - rain_adjustment),
                guardrail_min_effective + 4.0,
                weekly_max_mm,
            ),
            1,
        )
        useful_threshold = max(min_session_mm, guardrail_min_effective * 0.5)
        block_reason = None
        if pluie_compensatrice or pluie_proche:
            block_reason = "pluie_prevue_suffisante"
        elif cooldown_24h_active:
            block_reason = "cooldown_24h"
        elif saturation_block:
            block_reason = "sol_deja_humide"
        elif humidite >= 85 or bilan_hydrique_mm > 0.5:
            block_reason = "humidite_excessive"
        elif (
            recent_watering_count >= 3
            and recent_watering_mm_7j >= guardrail_min_mm
            and deficit_mm_ajuste < guardrail_min_mm
        ):
            block_reason = "garde_fou_hebdomadaire"
        if deficit_mm_ajuste < useful_threshold:
            mm_cible = 0.0
        else:
            upper_bound = min(guardrail_max_effective, deficit_mm_brut)
            if upper_bound <= guardrail_min_effective:
                mm_cible = upper_bound
            else:
                mm_cible = _clamp(
                    max(deficit_mm_ajuste, guardrail_min_effective),
                    guardrail_min_effective,
                    upper_bound,
                )
        if block_reason is not None:
            mm_cible = 0.0
        else:
            mm_cible = _apply_watering_floor_constraints(mm_cible, deficit_mm_brut, min_session_mm)
        mm_final = mm_cible
        if not block_reason and mm_final > 0:
            _reserve_max = float(water_balance.get("reserve_stock_max_mm") or 0.0)
            _reserve_cur = float(water_balance.get("reserve_stock_mm") or 0.0)
            _depletion_r = float(water_balance.get("depletion_ratio") or 0.0)
            _mad = float(water_balance.get("mad_ratio") or 0.5)
            if _reserve_max > 0 and _depletion_r < _mad:
                _fill_cap = max(0.0, _reserve_max - _reserve_cur)
                mm_cible = round(min(mm_cible, _fill_cap), 1)
                mm_final = mm_cible
        passages = 1
        if max_session_mm is not None and mm_final > max_session_mm:
            passages = max(passages, int(ceil(mm_final / max_session_mm)))
        elif mm_final > 12.0:
            passages = 2
        if recent_watering_count >= 2 and recent_watering_mm_7j >= guardrail_max_mm:
            passages = max(passages, 2)
        pause_minutes = 25 if passages > 1 else 0
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=mm_final,
        )
        return _build_profile_payload(
            deficit_mm_brut=deficit_mm_brut,
            deficit_mm_ajuste=deficit_mm_ajuste,
            mm_cible=mm_cible,
            mm_final=mm_final,
            mm_detected=float(water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
            type_arrosage="bloque" if block_reason is not None else ("auto" if mm_final > 0 else "aucune_action"),
            arrosage_recommande=mm_final > 0 and block_reason is None,
            arrosage_auto_autorise=mm_final > 0 and block_reason is None,
            arrosage_conseille="personnalise" if block_reason is not None else "aucune_action" if mm_final <= 0 else "auto",
            passages=passages,
            pause_minutes=pause_minutes,
            fractionnement_reason="deep_watering_fractionation" if passages > 1 else "single_pass_deep_watering",
            niveau_confiance=confidence_level,
            confidence_score=confidence_score,
            confidence_reasons=confidence_reasons,
            raison_decision_base="Mode Normal: arrosage profond uniquement si le déficit est utile.",
            block_reason=block_reason,
            fenetre_optimale="maintenant" if morning_start_minute <= now_minutes < acceptable_end_minute else "ce_matin",
            niveau_action="a_faire" if mm_final > 0 else "surveiller",
            risque_gazon="modere" if deficit_mm_brut >= 5 else "faible",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            morning_start_minute=morning_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            morning_end_minute=morning_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
            recent_watering_count=recent_watering_count,
            recent_watering_mm_7j=recent_watering_mm_7j,
            guardrail_min_mm=guardrail_min_effective,
            guardrail_max_mm=guardrail_max_effective,
            guardrail_reason=f"{guardrail_reason}; pluie_support={pluie_support:.1f}",
            seasonal_profile=seasonal_profile_payload,
            cooldown_24h_hours=cooldown_24h_hours,
        )

    if phase_dominante in {"Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"}:
        resolved_policy = _resolve_phase_policy(
            phase_dominante=phase_dominante,
            sous_phase=sous_phase,
            pluie_proche=pluie_proche,
            pluie_compensatrice=pluie_compensatrice,
            temperature=temperature,
            humidite=humidite,
            saturation_block=saturation_block,
        )
        minimum = resolved_policy.target_range.min_mm if resolved_policy.target_range is not None else 0.0
        maximum = resolved_policy.target_range.max_mm if resolved_policy.target_range is not None else 0.0
        if phase_dominante == "Fertilisation":
            mm_cible = _clamp((besoin_court * 0.4) + (besoin_tendance * 0.08), minimum, maximum)
        elif phase_dominante == "Biostimulant":
            mm_cible = _clamp((besoin_court * 0.5) + (besoin_tendance * 0.08), minimum, maximum)
        elif phase_dominante == "Agent Mouillant":
            mm_cible = _clamp((besoin_court * 0.55) + (besoin_tendance * 0.1), minimum, maximum)
        else:
            mm_cible = _clamp((besoin_court * 0.6) + (besoin_tendance * 0.1), minimum, maximum)
        block_reason = None
        if resolved_policy is not None and resolved_policy.blocking.is_blocked:
            block_reason = _normalize_public_block_reason(resolved_policy.blocking.reason)
        elif pluie_compensatrice or pluie_proche:
            block_reason = "pluie_prevue_suffisante"
        elif saturation_block:
            block_reason = "sol_deja_humide"
        elif humidite >= 85:
            block_reason = "humidite_elevee"
        if block_reason is None:
            if resolved_policy is not None and resolved_policy.target_range is not None:
                mm_cible = _apply_watering_floor_constraints(
                    mm_cible,
                    deficit_mm_brut,
                    resolved_policy.target_range.min_mm,
                )
            else:
                mm_cible = _apply_mode_watering_constraints(mm_cible, deficit_mm_brut, phase_dominante)
        mm_final = 0.0 if block_reason else mm_cible
        if (
            resolved_policy is not None
            and resolved_policy.policy.execution is not None
            and resolved_policy.policy.execution.preferred == "single_pass"
        ):
            passages = 1
        else:
            passages = 1 if mm_final <= 4.0 else 2
        pause_minutes = 25 if passages > 1 else 0
        fenetre_optimale = "soir" if evening_allowed and temperature >= 24 and now_hour < EVENING_END_HOUR else "ce_matin"
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=mm_final,
        )
        return _build_profile_payload(
            deficit_mm_brut=deficit_mm_brut,
            deficit_mm_ajuste=deficit_mm_ajuste,
            mm_cible=mm_cible,
            mm_final=mm_final,
            mm_detected=float(water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
            type_arrosage="auto" if mm_final > 0 else "aucune_action",
            arrosage_recommande=mm_final > 0,
            arrosage_auto_autorise=mm_final > 0,
            arrosage_conseille="auto" if phase_dominante == "Fertilisation" else "personnalise",
            passages=passages,
            pause_minutes=pause_minutes,
            fractionnement_reason="managed_fractionation" if passages > 1 else "single_pass",
            niveau_confiance=confidence_level,
            confidence_score=confidence_score,
            confidence_reasons=confidence_reasons,
            raison_decision_base=f"{phase_dominante}: arrosage léger adapté.",
            block_reason=block_reason,
            fenetre_optimale=fenetre_optimale if mm_final > 0 else "attendre",
            niveau_action="a_faire" if mm_final > 0 else "surveiller",
            risque_gazon="faible" if mm_final > 0 else "modere",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            morning_start_minute=morning_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            morning_end_minute=morning_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
            recent_watering_count=recent_watering_count,
            recent_watering_mm_7j=float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0),
            guardrail_min_mm=guardrail_min_mm,
            guardrail_max_mm=guardrail_max_mm,
            guardrail_reason=guardrail_reason,
            seasonal_profile=seasonal_profile_payload,
            cooldown_24h_hours=cooldown_24h_hours,
        )

    mm_cible = _clamp(max(deficit_mm_ajuste, 5.0), 5.0, 20.0)
    block_reason = None
    if pluie_compensatrice or pluie_proche:
        block_reason = "pluie_prevue_suffisante"
    elif saturation_block:
        block_reason = "sol_deja_humide"
    elif humidite >= 85:
        block_reason = "humidite_elevee"
    if block_reason is None:
        mm_cible = _apply_mode_watering_constraints(mm_cible, deficit_mm_brut, phase_dominante)
    mm_final = 0.0 if block_reason else mm_cible
    passages = 1 if mm_final <= 12.0 else 2
    pause_minutes = 25 if passages > 1 else 0
    confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
        phase_dominante=phase_dominante,
        temperature=temperature,
        humidite=humidite,
        etp=etp,
        weather_profile=weather_profile,
        soil_profile=soil_profile,
        heat_stress_level=heat_stress_level,
        heat_stress_phase=heat_stress_phase,
        block_reason=block_reason,
        mm_final=mm_final,
    )
    return _build_profile_payload(
        deficit_mm_brut=deficit_mm_brut,
        deficit_mm_ajuste=deficit_mm_ajuste,
        mm_cible=mm_cible,
        mm_final=mm_final,
        mm_detected=float(water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
        type_arrosage="aucune_action" if mm_final <= 0 else "auto",
        arrosage_recommande=mm_final > 0,
        arrosage_auto_autorise=mm_final > 0,
        arrosage_conseille="personnalise",
        passages=passages,
        pause_minutes=pause_minutes,
        fractionnement_reason="generic_deep_watering" if passages > 1 else "single_pass",
        niveau_confiance=confidence_level,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        raison_decision_base=f"Phase {phase_dominante}: arrosage maîtrisé.",
        block_reason=block_reason,
        fenetre_optimale="soir"
        if evening_allowed and temperature >= 24 and now_hour < EVENING_END_HOUR
        else ("ce_matin" if mm_final > 0 else "attendre"),
        niveau_action="a_faire" if mm_final > 0 else "surveiller",
        risque_gazon="faible",
        heat_stress_level=heat_stress_level,
        heat_stress_phase=heat_stress_phase,
        morning_start_minute=morning_start_minute,
        acceptable_end_minute=acceptable_end_minute,
        morning_end_minute=morning_end_minute,
        temperature_band=temperature_band,
        evening_allowed=evening_allowed,
        recent_watering_count=recent_watering_count,
        recent_watering_mm_7j=float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0),
        guardrail_min_mm=guardrail_min_mm,
        guardrail_max_mm=guardrail_max_mm,
        guardrail_reason=guardrail_reason,
        seasonal_profile=seasonal_profile_payload,
    )


def compute_objectif_mm(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    today: date | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
    humidite: float | None = None,
    temperature: float | None = None,
    etp: float | None = None,
    type_sol: str = "limoneux",
    weather_profile: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> float:
    return float(
        compute_watering_profile(
            phase_dominante=phase_dominante,
            sous_phase=sous_phase,
            water_balance=water_balance,
            today=today,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            pluie_j2=pluie_j2,
            pluie_3j=pluie_3j,
            pluie_probabilite_max_3j=pluie_probabilite_max_3j,
            humidite=humidite,
            temperature=temperature,
            etp=etp,
            type_sol=type_sol,
            weather_profile=weather_profile,
            history=history,
        )["mm_final_recommande"]
    )


def is_fertilization_window_open(
    today: date,
    temperature: float | None,
    humidite: float | None,
    etp: float | None,
    water_balance: dict[str, float] | None = None,
) -> bool:
    """Indique si la fertilisation peut raisonnablement être activée."""
    water_balance = water_balance or {}
    temperature = temperature or 0.0
    humidite = humidite or 0.0
    etp = etp or 0.0
    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
    mois = today.month

    if mois in {12, 1, 2}:
        return False
    if temperature >= 31 or etp >= 4.5 or humidite <= 35:
        return False
    if bilan_hydrique_mm <= -2.0:
        return False
    if mois in {6, 7, 8}:
        return temperature < 27 and etp < 4.0 and humidite >= 40 and bilan_hydrique_mm >= -1.0
    return mois in {3, 4, 5, 9, 10, 11}


def compute_jours_restants_for(
    phase_dominante: str,
    date_fin: date | None,
    today: date | None = None,
) -> int:
    today = today or _current_date()
    if phase_dominante == "Hivernage":
        return 999
    if not date_fin:
        return 0
    return max((date_fin - today).days, 0)


def compute_action_guidance(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    advanced_context: dict[str, Any] | None,
    pluie_24h: float | None,
    pluie_demain: float | None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
    humidite: float | None = None,
    temperature: float | None = None,
    etp: float | None = None,
    objectif_mm: float = 0.0,
    hour_of_day: int | None = None,
    history: list[dict[str, Any]] | None = None,
    sous_phase_age_days: int | None = None,
    sous_phase_progression: float | None = None,
    hauteur_gazon: float | None = None,
) -> dict[str, Any]:
    advanced_context = advanced_context or {}
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    besoin_court, besoin_tendance, pression_hydrique = _hydraulic_pressure(
        bilan_hydrique_mm, deficit_3j, deficit_7j
    )
    pluie_compensatrice, pluie_proche = _rain_signals(
        objective_reference_mm=objectif_mm if objectif_mm > 0 else max(0.0, max(-bilan_hydrique_mm, deficit_3j, deficit_7j)),
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
    )
    now = _current_datetime()
    now_hour = hour_of_day if hour_of_day is not None else now.hour
    now_minutes = now_hour * 60 + int(now.minute if hour_of_day is None else 0)
    vent = _to_float(advanced_context.get("vent"))
    rosee = _to_float(advanced_context.get("rosee"))
    hauteur_gazon = _to_float(advanced_context.get("hauteur_gazon"))
    optimal_start_minute, optimal_end_minute, acceptable_end_minute, temperature_band = _morning_window_bounds(
        phase_dominante=phase_dominante,
        temperature=temperature,
    )
    heat_stress_level = _heat_stress_level(
        temperature=temperature,
        etp=etp,
        humidite=humidite,
        weather_profile={
            "weather_wind_speed": vent,
            "weather_precipitation": pluie_24h,
            "weather_precipitation_probability": pluie_probabilite_max_3j,
        },
        deficit_mm_brut=max(0.0, max(-bilan_hydrique_mm, deficit_3j, deficit_7j)),
    )
    recent_watering_mm_7j = float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0)
    heat_stress_phase = _heat_stress_phase(
        heat_stress_level=heat_stress_level,
        temperature=temperature,
        etp=etp,
        pluie_demain=pluie_demain,
        pluie_3j=pluie_3j,
        recent_watering_count=int(water_balance.get("arrosage_recent_count_7j", 0) or 0),
        recent_watering_mm_7j=recent_watering_mm_7j,
    )
    evening_allowed = _evening_window_allowed(
        temperature=temperature,
        humidite=humidite,
        water_balance=water_balance,
        objectif_mm=objectif_mm,
        heat_stress_level=heat_stress_level,
    )

    if phase_dominante in {"Traitement", "Hivernage"}:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="surveiller",
            fenetre_optimale="attendre",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if is_active_rain_weather(advanced_context):
        return _build_guidance_window_payload(
            risque_gazon="modere" if phase_dominante == "Sursemis" else "faible",
            niveau_action="surveiller" if phase_dominante != "Normal" else "aucune_action",
            fenetre_optimale="apres_pluie",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if objectif_mm <= 0:
        return _build_guidance_window_payload(
            risque_gazon="faible" if phase_dominante == "Normal" else "modere",
            niveau_action="aucune_action" if phase_dominante == "Normal" else "surveiller",
            fenetre_optimale="apres_pluie" if pluie_proche else "attendre",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if phase_dominante == "Sursemis":
        optimal_start_minute, optimal_end_minute, acceptable_end_minute, temperature_band = _semis_window_bounds(
            temperature=temperature,
            humidite=humidite,
            vent=vent,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
        )
        policy_key, _, transition_ready, tonte_count = _select_sursemis_policy(
            history=[item for item in (history or []) if isinstance(item, dict)],
            sous_phase=sous_phase,
            sous_phase_age_days=sous_phase_age_days,
            sous_phase_progression=sous_phase_progression,
            hauteur_gazon=hauteur_gazon,
            water_balance=water_balance,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            pluie_probabilite_24h=pluie_probabilite_max_3j,
            temperature=temperature,
        )
        if policy_key == "germination_stricte":
            niveau_action = "critique" if pression_hydrique >= 1.8 or bilan_hydrique_mm <= -1.0 else "a_faire"
        elif policy_key == "reprise_transition":
            niveau_action = "surveiller" if transition_ready else "a_faire"
        else:
            niveau_action = "critique" if pression_hydrique >= 2.2 or bilan_hydrique_mm <= -1.5 else "a_faire"
        if pluie_compensatrice or pluie_proche:
            fenetre_optimale = "apres_pluie"
        elif policy_key == "reprise_transition":
            if transition_ready and (now_minutes >= acceptable_end_minute or pression_hydrique < 1.0):
                fenetre_optimale = "attendre"
            elif now_minutes < optimal_start_minute:
                fenetre_optimale = "ce_matin"
            elif now_minutes < acceptable_end_minute and (vent is None or vent < 15):
                fenetre_optimale = "maintenant"
            else:
                fenetre_optimale = "attendre"
        elif now_minutes < optimal_start_minute:
            fenetre_optimale = "ce_matin"
        elif now_minutes < acceptable_end_minute and (vent is None or vent < 15):
            fenetre_optimale = "maintenant"
        else:
            fenetre_optimale = "demain_matin"
        if policy_key == "germination_stricte":
            risque_gazon = "eleve" if bilan_hydrique_mm <= -1.0 or pression_hydrique >= 2.0 else "modere"
        elif policy_key == "reprise_transition" and transition_ready:
            risque_gazon = "modere" if pression_hydrique < 2.0 else "eleve"
        else:
            risque_gazon = "eleve" if bilan_hydrique_mm <= -1.5 or pression_hydrique >= 2.5 else "modere"
        if heat_stress_level in {"canicule", "extreme"}:
            risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
        if vent is not None and vent >= 20:
            risque_gazon = "eleve"
        if hauteur_gazon is not None and hauteur_gazon >= 12:
            risque_gazon = "eleve"
        return _build_guidance_window_payload(
            risque_gazon=risque_gazon,
            niveau_action=niveau_action,
            fenetre_optimale=fenetre_optimale,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if evening_allowed and EVENING_START_HOUR <= now_hour < EVENING_END_HOUR:
        return _build_guidance_window_payload(
            risque_gazon="modere" if heat_stress_level in {"canicule", "extreme"} else "faible",
            niveau_action="a_faire",
            fenetre_optimale="soir",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if pluie_compensatrice:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="surveiller",
            fenetre_optimale="apres_pluie",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if humidite >= 85 and bilan_hydrique_mm >= -0.5:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="surveiller",
            fenetre_optimale="attendre",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if bilan_hydrique_mm <= -4.0:
        return _build_guidance_window_payload(
            risque_gazon="eleve",
            niveau_action="critique",
            fenetre_optimale="demain_matin" if now_minutes >= acceptable_end_minute else "maintenant",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if bilan_hydrique_mm <= -0.8 or pression_hydrique >= 1.5:
        if now_minutes < optimal_start_minute:
            return _build_guidance_window_payload(
                risque_gazon="modere",
                niveau_action="a_faire",
                fenetre_optimale="ce_matin",
                heat_stress_level=heat_stress_level,
                heat_stress_phase=heat_stress_phase,
                optimal_start_minute=optimal_start_minute,
                acceptable_end_minute=acceptable_end_minute,
                optimal_end_minute=optimal_end_minute,
                temperature_band=temperature_band,
                evening_allowed=evening_allowed,
            )
        if now_minutes < acceptable_end_minute:
            return _build_guidance_window_payload(
                risque_gazon="modere",
                niveau_action="a_faire",
                fenetre_optimale="maintenant",
                heat_stress_level=heat_stress_level,
                heat_stress_phase=heat_stress_phase,
                optimal_start_minute=optimal_start_minute,
                acceptable_end_minute=acceptable_end_minute,
                optimal_end_minute=optimal_end_minute,
                temperature_band=temperature_band,
                evening_allowed=evening_allowed,
            )
        return _build_guidance_window_payload(
            risque_gazon="modere",
            niveau_action="a_faire",
            fenetre_optimale="demain_matin",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if now_minutes < optimal_start_minute:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="a_faire",
            fenetre_optimale="ce_matin",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )
    if now_minutes < acceptable_end_minute:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="a_faire",
            fenetre_optimale="maintenant",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    risque_gazon = "faible"
    if bilan_hydrique_mm <= -2.5:
        risque_gazon = "eleve"
    elif bilan_hydrique_mm <= -0.8 or pression_hydrique >= 1.2:
        risque_gazon = "modere"
    if vent is not None and vent >= 20:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
    if hauteur_gazon is not None and hauteur_gazon >= 12:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
    if heat_stress_level == "extreme":
        risque_gazon = "eleve"
    elif heat_stress_level in {"canicule", "vigilance"}:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
    if heat_stress_phase == "canicule_prolongee":
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))

    return _build_guidance_window_payload(
        risque_gazon=risque_gazon,
        niveau_action="a_faire",
        fenetre_optimale="demain_matin",
        heat_stress_level=heat_stress_level,
        heat_stress_phase=heat_stress_phase,
        optimal_start_minute=optimal_start_minute,
        acceptable_end_minute=acceptable_end_minute,
        optimal_end_minute=optimal_end_minute,
        temperature_band=temperature_band,
        evening_allowed=evening_allowed,
    )


def compute_next_reevaluation(
    phase_dominante: str,
    niveau_action: str,
    fenetre_optimale: str,
    risque_gazon: str,
    pluie_demain: float | None = None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
) -> str:
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0

    if fenetre_optimale == "apres_pluie" and (
        pluie_demain > 0 or pluie_j2 > 0 or pluie_3j > 0 or pluie_probabilite_max_3j > 0
    ):
        return "apres_pluie"
    if fenetre_optimale == "ce_matin":
        return "dans quelques heures"
    if phase_dominante in {"Traitement", "Hivernage"}:
        return "dans 24 h"
    if phase_dominante == "Sursemis":
        return "dans 24 h"
    if niveau_action == "critique":
        return "dans 12 h"
    if niveau_action == "a_faire":
        return "dans 24 h"
    if niveau_action == "surveiller":
        return "dans 48 h"
    return "dans 48 h"


def compute_tonte_statut(
    phase_dominante: str,
    tonte_autorisee: bool,
    score_tonte: int,
    risque_gazon: str,
) -> str:
    if not tonte_autorisee:
        if phase_dominante in {"Sursemis", "Traitement", "Hivernage"}:
            return "interdite"
        if score_tonte >= 70 or risque_gazon == "eleve":
            return "deconseillee"
        return "a_surveiller"

    if score_tonte >= 45 or risque_gazon == "modere":
        return "autorisee_avec_precaution"
    return "autorisee"
