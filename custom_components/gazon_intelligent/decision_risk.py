from __future__ import annotations

"""Logique pure de risque et de fenêtre optimale."""

from typing import Any

from .decision_models import DecisionContext
from .guidance import _reference_hydric_balance_mm, compute_action_guidance, compute_next_reevaluation
from .scores import compute_internal_scores


def build_risk_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> dict[str, Any]:
    scores = compute_internal_scores(
        history=context.history,
        today=context.today,
        phase_dominante=phase_bundle["phase_dominante"],
        sous_phase=phase_bundle["sous_phase"],
        water_balance=water_bundle["water_balance"],
        advanced_context=water_bundle["advanced_context"],
        pluie_24h=context.pluie_24h,
        pluie_demain=context.pluie_demain,
        pluie_j2=context.pluie_j2,
        pluie_3j=context.pluie_3j,
        pluie_probabilite_max_3j=context.pluie_probabilite_max_3j,
        humidite=context.humidite,
        temperature=context.temperature,
        etp=water_bundle["etp"],
    )
    action_guidance = compute_action_guidance(
        phase_dominante=phase_bundle["phase_dominante"],
        sous_phase=phase_bundle["sous_phase"],
        water_balance=water_bundle["water_balance"],
        advanced_context=water_bundle["advanced_context"],
        pluie_24h=context.pluie_24h,
        pluie_demain=context.pluie_demain,
        pluie_j2=context.pluie_j2,
        pluie_3j=context.pluie_3j,
        pluie_probabilite_max_3j=context.pluie_probabilite_max_3j,
        humidite=context.humidite,
        temperature=context.temperature,
        etp=water_bundle["etp"],
        objectif_mm=water_bundle["objectif_mm"],
        hour_of_day=context.hour_of_day,
        history=context.history,
        sous_phase_age_days=phase_bundle.get("sous_phase_age_days"),
        sous_phase_progression=phase_bundle.get("sous_phase_progression"),
        hauteur_gazon=water_bundle["advanced_context"].get("hauteur_gazon"),
    )
    prochaine_reevaluation = compute_next_reevaluation(
        phase_dominante=phase_bundle["phase_dominante"],
        niveau_action=action_guidance["niveau_action"],
        fenetre_optimale=action_guidance["fenetre_optimale"],
        risque_gazon=action_guidance["risque_gazon"],
        pluie_demain=context.pluie_demain,
        pluie_j2=context.pluie_j2,
        pluie_3j=context.pluie_3j,
        pluie_probabilite_max_3j=context.pluie_probabilite_max_3j,
    )
    urgence = _decision_urgence(
        phase_bundle["phase_dominante"],
        water_bundle["objectif_mm"] > 0,
        action_guidance["niveau_action"],
        action_guidance["risque_gazon"],
        _reference_hydric_balance_mm(water_bundle["water_balance"]),
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
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0
    if phase_dominante in {"Traitement", "Hivernage"}:
        return "faible"
    if not arrosage_recommande:
        if pluie_demain >= 2.0 or pluie_j2 >= 2.0 or pluie_3j >= 4.0 or pluie_probabilite_max_3j >= 80.0 or bilan_hydrique_mm >= 0.0:
            return "faible"
        return "moyenne" if niveau_action == "surveiller" or bilan_hydrique_mm < 0 else "faible"
    if bilan_hydrique_mm <= -2.5 or niveau_action == "critique" or risque_gazon == "eleve":
        return "haute"
    if phase_dominante == "Sursemis" and (bilan_hydrique_mm <= -1.0 or niveau_action == "a_faire"):
        return "moyenne"
    if niveau_action in {"a_faire", "surveiller"} or bilan_hydrique_mm <= -0.5:
        return "moyenne"
    return "faible"
