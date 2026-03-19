from __future__ import annotations

"""Logique pure liée à la tonte."""

import math
from typing import Any

from .const import (
    DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
    DEFAULT_PAS_HAUTEUR_TONDEUSE_CM,
)
from .decision_models import DecisionContext
from .guidance import compute_tonte_statut
from .scores import classify_stress_level


def _mowing_height_settings(context: DecisionContext) -> tuple[float, float, float]:
    """Retourne les bornes et le pas de la tondeuse, avec valeurs sûres par défaut."""
    min_height = context.hauteur_min_tondeuse_cm
    max_height = context.hauteur_max_tondeuse_cm
    step = context.pas_hauteur_tondeuse_cm
    try:
        min_height = float(min_height) if min_height is not None else DEFAULT_HAUTEUR_MIN_TONDEUSE_CM
    except (TypeError, ValueError):
        min_height = DEFAULT_HAUTEUR_MIN_TONDEUSE_CM
    try:
        max_height = float(max_height) if max_height is not None else DEFAULT_HAUTEUR_MAX_TONDEUSE_CM
    except (TypeError, ValueError):
        max_height = DEFAULT_HAUTEUR_MAX_TONDEUSE_CM
    try:
        step = float(step) if step is not None else DEFAULT_PAS_HAUTEUR_TONDEUSE_CM
    except (TypeError, ValueError):
        step = DEFAULT_PAS_HAUTEUR_TONDEUSE_CM

    if min_height > max_height:
        min_height, max_height = max_height, min_height
    if step <= 0:
        step = DEFAULT_PAS_HAUTEUR_TONDEUSE_CM
    return min_height, max_height, step


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


def _theoretical_mowing_height(
    context: DecisionContext,
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> float:
    """Estime une hauteur de coupe prudente selon la saison et le stress."""
    temperature = context.temperature or 0.0
    humidite = context.humidite or 0.0
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

    target = 6.5
    month = context.today.month
    if month in {6, 7, 8} or temperature >= 28 or humidite <= 45 or stress_level != "leger":
        target = 7.5
    if month in {7, 8} and (temperature >= 32 or stress_level == "fort"):
        target = 8.5
    return target


def _recommended_mowing_height(
    context: DecisionContext,
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> dict[str, float | None]:
    """Calcule une hauteur de coupe prudente et compatible avec la machine."""
    min_height, max_height, step = _mowing_height_settings(context)
    theoretical_height = _theoretical_mowing_height(context, water_bundle, risk_bundle)
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

    return {
        "hauteur_tonte_recommandee_cm": round(recommended_height, 2),
        "hauteur_tonte_min_cm": round(min_height, 2),
        "hauteur_tonte_max_cm": round(max_height, 2),
        "pas_hauteur_tondeuse_cm": round(step, 2),
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

    height_recommendation = _recommended_mowing_height(context, water_bundle, risk_bundle)
    target_height = float(height_recommendation["hauteur_tonte_recommandee_cm"] or 0.0)
    current_height = water_bundle["advanced_context"].get("hauteur_gazon")
    height_rule_blocked = False

    if not tonte_ok:
        humidite = context.humidite or 0.0
        pluie_24h = context.pluie_24h or 0.0
        pluie_demain = context.pluie_demain or 0.0
        temperature = context.temperature or 0.0
        etp = water_bundle["etp"] or 0.0
        rosee = water_bundle["advanced_context"].get("rosee")
        arrosage_recent = water_bundle["water_balance"].get("arrosage_recent", 0.0)
        if humidite >= 85:
            reason = "Humidité trop élevée: pelouse humide."
        elif pluie_24h >= 3:
            reason = "Pluie récente: sol encore humide."
        elif pluie_demain >= 2 and humidite >= 70:
            reason = "Pluie proche: mieux vaut attendre."
        elif arrosage_recent > 0:
            reason = "Arrosage récent: attendre un ressuyage."
        elif rosee is not None and rosee > 0:
            reason = "Rosée présente: attendre le ressuyage du feuillage."
        elif temperature >= 30 and etp >= 4:
            reason = "Stress thermique élevé: limiter la tonte."
        else:
            reason = "Conditions défavorables à la tonte."
    else:
        reason = "Fenêtre tonte acceptable."

    rosee = water_bundle["advanced_context"].get("rosee")
    if tonte_ok and rosee is not None and rosee > 0:
        tonte_ok = False
        reason = "Rosée présente: attendre le ressuyage du feuillage."

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
            elif target_height < min_height_after_cut:
                tonte_ok = False
                height_rule_blocked = True
                if effective_max < min_height_after_cut:
                    reason = (
                        f"Règle du tiers impossible avec cette tondeuse: il faudrait au moins {min_height_after_cut:.1f} cm, "
                        f"mais la machine plafonne à {effective_max:.1f} cm."
                    )
                else:
                    reason = (
                        f"Règle du tiers: conserve au moins {min_height_after_cut:.1f} cm sur une hauteur actuelle de {current_height:.1f} cm."
                    )
        except (TypeError, ValueError):
            current_height = None

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
        "score_tonte": score_tonte,
        "score_stress": score_stress,
        **height_recommendation,
    }
