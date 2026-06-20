from __future__ import annotations

"""Logique pure de risque et de fenêtre optimale."""

from typing import Any

from .decision_models import DecisionContext
from .guidance import _reference_hydric_balance_mm, compute_action_guidance, compute_next_reevaluation
from .scores import compute_internal_scores

_URGENCE_LEVELS: dict[str, int] = {
    "faible": 0,
    "moyenne": 1,
    "haute": 2,
}


def _normalize_urgence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _URGENCE_LEVELS:
        return text
    return "faible"


def _phase_bundle_defaults(phase_bundle: dict[str, Any]) -> tuple[str, str]:
    return (
        str(phase_bundle.get("phase_dominante") or "Normal"),
        str(phase_bundle.get("sous_phase") or "Normal"),
    )


def _water_bundle_defaults(water_bundle: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float | None, float]:
    water_balance = water_bundle.get("water_balance")
    if not isinstance(water_balance, dict):
        water_balance = {}
    advanced_context = water_bundle.get("advanced_context")
    if not isinstance(advanced_context, dict):
        advanced_context = {}
    etp = water_bundle.get("etp")
    objectif_mm = float(water_bundle.get("objectif_mm") or 0.0)
    return water_balance, advanced_context, etp, objectif_mm


def build_risk_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Compose le risque final à partir de la guidance hydrique et d'une urgence synthétique."""
    phase_dominante, sous_phase = _phase_bundle_defaults(phase_bundle)
    water_balance, advanced_context, etp, objectif_mm = _water_bundle_defaults(water_bundle)
    scores = compute_internal_scores(
        history=context.history,
        today=context.today,
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        water_balance=water_balance,
        advanced_context=advanced_context,
        pluie_24h=context.pluie_24h,
        pluie_demain=context.pluie_demain,
        pluie_j2=context.pluie_j2,
        pluie_3j=context.pluie_3j,
        pluie_probabilite_max_3j=context.pluie_probabilite_max_3j,
        humidite=context.humidite,
        temperature=context.temperature,
        etp=etp,
    )
    action_guidance = compute_action_guidance(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        water_balance=water_balance,
        advanced_context=advanced_context,
        pluie_24h=context.pluie_24h,
        pluie_demain=context.pluie_demain,
        pluie_j2=context.pluie_j2,
        pluie_3j=context.pluie_3j,
        pluie_probabilite_max_3j=context.pluie_probabilite_max_3j,
        humidite=context.humidite,
        temperature=context.temperature,
        etp=etp,
        objectif_mm=objectif_mm,
        hour_of_day=context.hour_of_day,
        history=context.history,
        sous_phase_age_days=phase_bundle.get("sous_phase_age_days"),
        sous_phase_progression=phase_bundle.get("sous_phase_progression"),
        hauteur_gazon=advanced_context.get("hauteur_gazon"),
    )
    prochaine_reevaluation = compute_next_reevaluation(
        phase_dominante=phase_dominante,
        niveau_action=action_guidance.get("niveau_action", "a_faire"),
        fenetre_optimale=action_guidance.get("fenetre_optimale", "attendre"),
        risque_gazon=action_guidance.get("risque_gazon", "faible"),
        pluie_demain=context.pluie_demain,
        pluie_j2=context.pluie_j2,
        pluie_3j=context.pluie_3j,
        pluie_probabilite_max_3j=context.pluie_probabilite_max_3j,
    )
    urgence = _decision_urgence(
        phase_dominante,
        objectif_mm > 0,
        action_guidance.get("niveau_action", "a_faire"),
        action_guidance.get("risque_gazon", "faible"),
        _reference_hydric_balance_mm(water_balance),
        context.pluie_demain,
        context.pluie_j2,
        context.pluie_3j,
        context.pluie_probabilite_max_3j,
    )
    return {
        "scores": scores,
        "action_guidance": action_guidance,
        "niveau_action": action_guidance["niveau_action"],
        "fenetre_optimale": action_guidance["fenetre_optimale"],
        "risque_gazon": action_guidance["risque_gazon"],
        "watering_window_start_minute": action_guidance.get("watering_window_start_minute"),
        "watering_window_end_minute": action_guidance.get("watering_window_end_minute"),
        "watering_window_optimal_start_minute": action_guidance.get("watering_window_optimal_start_minute"),
        "watering_window_optimal_end_minute": action_guidance.get("watering_window_optimal_end_minute"),
        "watering_window_acceptable_end_minute": action_guidance.get("watering_window_acceptable_end_minute"),
        "watering_evening_start_minute": action_guidance.get("watering_evening_start_minute"),
        "watering_evening_end_minute": action_guidance.get("watering_evening_end_minute"),
        "watering_window_profile": action_guidance.get("watering_window_profile"),
        "watering_evening_allowed": action_guidance.get("watering_evening_allowed"),
        "heat_stress_level": action_guidance.get("heat_stress_level"),
        "heat_stress_phase": action_guidance.get("heat_stress_phase"),
        "prochaine_reevaluation": prochaine_reevaluation,
        "urgence": urgence,
    }


def _decision_urgence(
    phase_dominante: str,
    arrosage_recommande: bool,
    niveau_action: str,
    risque_gazon: str,
    bilan_hydrique_mm: float,
    pluie_demain: float | None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
) -> str:
    niveau_action = str(niveau_action or "").strip().lower()
    risque_gazon = str(risque_gazon or "").strip().lower()
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0
    if phase_dominante in {"Traitement", "Hivernage"}:
        return _normalize_urgence("faible")
    if not arrosage_recommande:
        if pluie_demain >= 2.0 or pluie_j2 >= 2.0 or pluie_3j >= 4.0 or pluie_probabilite_max_3j >= 80.0 or bilan_hydrique_mm >= 0.0:
            return _normalize_urgence("faible")
        return _normalize_urgence("moyenne" if niveau_action == "surveiller" or bilan_hydrique_mm < 0 else "faible")
    if bilan_hydrique_mm <= -2.5 or niveau_action == "critique" or risque_gazon == "eleve":
        return _normalize_urgence("haute")
    if phase_dominante == "Sursemis" and (bilan_hydrique_mm <= -1.0 or niveau_action == "a_faire"):
        return _normalize_urgence("moyenne")
    if niveau_action in {"a_faire", "surveiller"} or bilan_hydrique_mm <= -0.5:
        return _normalize_urgence("moyenne")
    return _normalize_urgence("faible")


def compute_fungal_risk(
    *,
    temperature: float | None,
    humidite: float | None,
    rosee: float | None,
    pluie_24h: float | None,
    pluie_demain: float | None,
    hour_of_day: int = 12,
) -> dict[str, Any]:
    """Évalue le risque fongique simplifié (oïdium, rouille, septoriose).

    Conditions favorables aux maladies :
    - Température 12-24°C (optimum 15-22°C)
    - Humidité air >= 85%
    - Rosée présente ou pluie récente
    - Période nocturne ou tôt le matin
    """
    t = float(temperature or 0.0)
    h = float(humidite or 0.0)
    r = float(rosee or 0.0)
    p24 = float(pluie_24h or 0.0)
    p_demain = float(pluie_demain or 0.0)

    score = 0
    reasons = []

    # Température favorable
    if 12.0 <= t <= 24.0:
        score += 2
        reasons.append(f"température favorable ({t:.0f}°C)")
    elif 10.0 <= t < 12.0 or 24.0 < t <= 26.0:
        score += 1

    # Humidité élevée
    if h >= 90.0:
        score += 3
        reasons.append(f"humidité très élevée ({h:.0f}%)")
    elif h >= 85.0:
        score += 2
        reasons.append(f"humidité élevée ({h:.0f}%)")
    elif h >= 75.0:
        score += 1

    # Rosée ou pluie récente
    if r > 0.5:
        score += 2
        reasons.append("rosée présente")
    elif r > 0:
        score += 1
    if p24 >= 2.0:
        score += 1
        reasons.append(f"pluie récente ({p24:.0f} mm)")

    # Période à risque (nuit/matin)
    if hour_of_day <= 8 or hour_of_day >= 20:
        score += 1
        reasons.append("période nocturne ou matinale")

    # Pluie demain = humectation prolongée attendue
    if p_demain >= 3.0:
        score += 1

    if score >= 7:
        level = "high"
    elif score >= 4:
        level = "moderate"
    elif score >= 2:
        level = "low"
    else:
        level = "none"

    return {
        "fungal_risk_level": level,
        "fungal_risk_score": score,
        "fungal_risk_reasons": reasons,
        "fungal_risk_evening_block": level in {"moderate", "high"},
        "fungal_risk_reduce_watering": level == "high",
    }
