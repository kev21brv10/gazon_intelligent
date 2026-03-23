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
from .scores import classify_stress_level

_MOWER_STEP_CM = 0.5


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
    if month in {1, 2}:
        return 7.4
    if month == 3:
        return 6.8
    if month in {4, 5}:
        return 6.1
    if month == 6:
        return 6.5
    if month in {7, 8}:
        return 7.8
    if month == 9:
        return 6.6
    if month == 10:
        return 6.9
    return 7.2


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


def _latest_watering_timestamp(context: DecisionContext) -> datetime:
    """Retourne l'horodatage du dernier arrosage détecté ou la date du jour."""
    for item in reversed(context.history):
        if item.get("type") != "arrosage":
            continue
        return _parse_history_timestamp(item, context.today)
    return datetime.combine(context.today, time(6, 0), tzinfo=timezone.utc)


def _estimate_mowing_ressuyage_hours(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> float:
    """Estime le délai de ressuyage nécessaire avant une tonte sûre."""
    soil_profile = str(water_bundle.get("soil_profile") or context.type_sol or "").strip().lower()
    if soil_profile == "sableux":
        hours = 8.0
    elif soil_profile == "argileux":
        hours = 18.0
    else:
        hours = 12.0

    humidite = float(context.humidite or 0.0)
    temperature = float(context.temperature or 0.0)
    pluie_24h = float(context.pluie_24h or 0.0)
    pluie_demain = float(context.pluie_demain or 0.0)
    pluie_3j = float(context.pluie_3j or 0.0)
    etp = float(water_bundle.get("etp") or 0.0)
    rosee = water_bundle["advanced_context"].get("rosee")
    arrosage_recent_jour = float(water_bundle["water_balance"].get("arrosage_recent_jour") or 0.0)
    arrosage_recent_3j = float(water_bundle["water_balance"].get("arrosage_recent_3j") or 0.0)

    if humidite >= 90 or (rosee is not None and float(rosee) > 0):
        hours += 6.0
    elif humidite >= 80:
        hours += 4.0
    elif humidite >= 70:
        hours += 2.0

    if pluie_24h >= 2.0 or arrosage_recent_jour > 0.5:
        hours += 4.0
    if pluie_demain >= 2.0:
        hours += 2.0
    if pluie_3j >= 4.0 or arrosage_recent_3j > 2.0:
        hours += 2.0

    if temperature >= 30 and humidite <= 60 and etp >= 4.0:
        hours -= 3.0
    elif temperature >= 26 and humidite <= 55:
        hours -= 1.5

    if phase_bundle["phase_dominante"] == "Sursemis":
        hours += 2.0
    elif phase_bundle["phase_dominante"] in {"Traitement", "Hivernage"}:
        hours += 1.0

    return max(6.0, min(hours, 48.0))


def _project_next_mowing_date(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    tonte_ok: bool,
) -> tuple[str | None, str | None, str | None]:
    """Projette la prochaine date de tonte autorisable."""
    if tonte_ok:
        today_iso = context.today.isoformat()
        return today_iso, context.today.strftime("%d/%m/%Y"), None

    anchor = _latest_watering_timestamp(context)
    ressuyage_hours = _estimate_mowing_ressuyage_hours(context, phase_bundle, water_bundle)
    projected = anchor + timedelta(hours=ressuyage_hours)
    reason_hint: str | None = None

    phase_end = phase_bundle.get("date_fin")
    if phase_bundle["phase_dominante"] in {"Sursemis", "Traitement", "Hivernage"} and phase_end:
        try:
            phase_end_dt = datetime.combine(date.fromisoformat(str(phase_end)), time(6, 0), tzinfo=timezone.utc)
            projected = max(projected, phase_end_dt)
            reason_hint = f"phase={phase_bundle['phase_dominante']}"
        except ValueError:
            pass

    projected_date = projected.date()
    return projected_date.isoformat(), projected_date.strftime("%d/%m/%Y"), reason_hint


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
            target = max(target, target + _post_sursemis_bonus(post_sursemis_age))

    return target


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
    third_floor = None

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
    recommended_height = max(min_height, min(recommended_height, effective_max))

    previous_height = _previous_recommended_height(context)
    if previous_height is not None:
        previous_height = max(min_height, min(previous_height, effective_max))
        previous_height = _round_to_step(previous_height)
        diff = recommended_height - previous_height
        if abs(diff) < step:
            recommended_height = previous_height
        else:
            direction = step if diff > 0 else -step
            recommended_height = _round_to_step(previous_height + direction)
            recommended_height = max(min_height, min(recommended_height, effective_max))

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
    tonte_ok = score_tonte < 45 and score_stress < 70
    if phase_bundle["phase_dominante"] in {"Sursemis", "Traitement", "Hivernage"}:
        tonte_ok = False

    if is_active_rain_weather(context.weather_profile):
        tonte_ok = False

    height_recommendation = _recommended_mowing_height(context, phase_bundle, water_bundle, risk_bundle)
    target_height = float(height_recommendation["hauteur_tonte_recommandee_cm"] or 0.0)
    current_height = water_bundle["advanced_context"].get("hauteur_gazon")
    height_rule_blocked = False
    reason_code: str | None = None

    if phase_bundle["phase_dominante"] in {"Sursemis", "Traitement", "Hivernage"}:
        reason_code = f"phase_{phase_bundle['phase_dominante'].lower()}"

    if not tonte_ok:
        humidite = context.humidite or 0.0
        pluie_24h = context.pluie_24h or 0.0
        pluie_demain = context.pluie_demain or 0.0
        pluie_j2 = context.pluie_j2 or 0.0
        pluie_3j = context.pluie_3j or 0.0
        pluie_probabilite_max_3j = context.pluie_probabilite_max_3j or 0.0
        temperature = context.temperature or 0.0
        etp = water_bundle["etp"] or 0.0
        rosee = water_bundle["advanced_context"].get("rosee")
        arrosage_recent = water_bundle["water_balance"].get("arrosage_recent", 0.0)
        if humidite >= 85:
            reason = "Humidité trop élevée: pelouse humide."
            reason_code = "humidite_elevee"
        elif pluie_24h >= 3:
            reason = "Pluie récente: sol encore humide."
            reason_code = "pluie_recente"
        elif pluie_demain >= 2 and humidite >= 70:
            reason = "Pluie proche: mieux vaut attendre."
            reason_code = "pluie_proche"
        elif pluie_j2 >= 2 or pluie_3j >= 4 or pluie_probabilite_max_3j >= 80:
            reason = "Pluie annoncée: mieux vaut attendre le ressuyage."
            reason_code = "pluie_annoncee"
        elif arrosage_recent > 0:
            reason = "Arrosage récent: attendre un ressuyage."
            reason_code = "sol_humide_post_arrosage"
        elif rosee is not None and rosee > 0:
            reason = "Rosée présente: attendre le ressuyage du feuillage."
            reason_code = "rosee_persistante"
        elif temperature >= 30 and etp >= 4:
            reason = "Stress thermique élevé: limiter la tonte."
            reason_code = "stress_thermique"
        else:
            reason = "Conditions défavorables à la tonte."
            reason_code = reason_code or "conditions_defavorables"
    else:
        reason = "Fenêtre tonte acceptable."
        reason_code = None

    rosee = water_bundle["advanced_context"].get("rosee")
    if tonte_ok and rosee is not None and rosee > 0:
        tonte_ok = False
        reason = "Rosée présente: attendre le ressuyage du feuillage."
        reason_code = "rosee_persistante"

    if not tonte_ok and is_active_rain_weather(context.weather_profile):
        reason = "Pluie en cours ou imminente: attendre le ressuyage du gazon."
        reason_code = "pluie_en_cours"

    if current_height is not None:
        try:
            current_height = float(current_height)
            min_height_after_cut = current_height * (2.0 / 3.0)
            effective_max = float(height_recommendation["_hauteur_tonte_effective_max_cm"] or 0.0)
            if current_height <= target_height:
                tonte_ok = False
                height_rule_blocked = True
                reason = (
                    f"Hauteur actuelle trop faible: vise au moins {target_height:.1f} cm avant de tondre."
                )
                reason_code = "hauteur_trop_faible"
            elif target_height < min_height_after_cut:
                tonte_ok = False
                height_rule_blocked = True
                if effective_max < min_height_after_cut:
                    reason = (
                        f"Règle du tiers impossible avec cette tondeuse: il faudrait au moins {min_height_after_cut:.1f} cm, "
                        f"mais la machine plafonne à {effective_max:.1f} cm."
                    )
                    reason_code = "regle_tiers_impossible"
                else:
                    reason = (
                        f"Règle du tiers: conserve au moins {min_height_after_cut:.1f} cm sur une hauteur actuelle de {current_height:.1f} cm."
                    )
                    reason_code = "regle_tiers"
        except (TypeError, ValueError):
            current_height = None

    if is_active_rain_weather(context.weather_profile):
        tonte_ok = False
        reason = "Pluie en cours ou imminente: attendre le ressuyage du gazon."
        reason_code = "pluie_en_cours"

    next_mowing_date, next_mowing_display, next_mowing_reason_hint = _project_next_mowing_date(
        context,
        phase_bundle,
        water_bundle,
        tonte_ok,
    )

    if not tonte_ok and next_mowing_display:
        reason = f"{reason} Prochaine tonte estimée le {next_mowing_display}."
        if next_mowing_reason_hint:
            reason = f"{reason} ({next_mowing_reason_hint})"

    tonte_statut = compute_tonte_statut(
        phase_dominante=phase_bundle["phase_dominante"],
        tonte_autorisee=tonte_ok,
        score_tonte=score_tonte,
        risque_gazon=risk_bundle["risque_gazon"],
    )
    if height_rule_blocked and tonte_statut != "interdite":
        tonte_statut = "deconseillee"

    return {
        "tonte_autorisee": tonte_ok,
        "tonte_statut": tonte_statut,
        "tonte_reason": reason,
        "raison_blocage_code": reason_code,
        "next_mowing_date": next_mowing_date,
        "next_mowing_display": next_mowing_display,
        "score_tonte": score_tonte,
        "score_stress": score_stress,
        **height_recommendation,
    }
