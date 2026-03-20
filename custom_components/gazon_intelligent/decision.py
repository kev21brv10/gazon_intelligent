from __future__ import annotations

"""Orchestrateur du moteur de décision.

Ce module garde l'API historique utilisée par le reste de l'intégration,
mais délègue la logique métier aux modules spécialisés:
- decision_phase.py
- decision_watering.py
- decision_risk.py
- decision_mowing.py
"""

from datetime import date
from typing import Any

from .decision_models import DecisionContext, DecisionResult
from .decision_mowing import build_mowing_bundle
from .decision_phase import build_phase_bundle
from .decision_risk import build_risk_bundle
from .decision_watering import build_water_bundle, build_watering_bundle
from .guidance import (
    compute_action_guidance,
    compute_jours_restants_for,
    compute_next_reevaluation,
    compute_objectif_mm,
    compute_tonte_statut,
)
from .memory import compute_memory
from .phases import (
    PHASE_DURATIONS_DAYS,
    PHASE_PRIORITIES,
    SIGNIFICANT_WATERING_THRESHOLD_MM,
    SUBPHASE_RULES,
    compute_dominant_phase,
    compute_phase_active,
    compute_subphase,
    is_hivernage,
    phase_duration_days,
)
from .scores import compute_internal_scores
from .water import (
    compute_advanced_context,
    compute_etp,
    compute_recent_watering_mm,
    compute_water_balance,
)


def compute_decision(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    advanced_context: dict[str, Any] | None,
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
    history: list[dict[str, Any]],
    today: date | None = None,
    hour_of_day: int | None = None,
    hauteur_min_tondeuse_cm: float | None = None,
    hauteur_max_tondeuse_cm: float | None = None,
    memory: dict[str, Any] | None = None,
) -> DecisionResult:
    """Retourne un résultat typé, compatible avec le snapshot historique."""
    today = today or date.today()
    context = DecisionContext(
        history=[item for item in history if isinstance(item, dict)],
        today=today,
        hour_of_day=hour_of_day,
        temperature=temperature,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        humidite=humidite,
        hauteur_min_tondeuse_cm=hauteur_min_tondeuse_cm,
        hauteur_max_tondeuse_cm=hauteur_max_tondeuse_cm,
        weather_profile={},
        config={},
        memory=memory,
    )
    phase_bundle = {
        "phase_dominante": phase_dominante,
        "phase_dominante_source": "historique_actif",
        "date_action": None,
        "date_fin": None,
        "phase_age_days": 0,
        "sous_phase": sous_phase,
        "sous_phase_detail": f"{phase_dominante} / {sous_phase}",
        "sous_phase_age_days": 0,
        "sous_phase_progression": 0,
        "jours_restants": jours_restants,
    }
    water_bundle = {
        "etp": etp,
        "advanced_context": advanced_context or {},
        "water_balance": water_balance,
        "objectif_mm": objectif_mm,
    }
    risk_bundle = {
        "scores": {
            "score_hydrique": score_hydrique,
            "score_stress": score_stress,
            "score_tonte": score_tonte,
        },
        "niveau_action": advanced_context.get("niveau_action") if advanced_context else "a_faire",
        "fenetre_optimale": advanced_context.get("fenetre_optimale") if advanced_context else "maintenant",
        "risque_gazon": advanced_context.get("risque_gazon") if advanced_context else "modere",
        "prochaine_reevaluation": advanced_context.get("prochaine_reevaluation") if advanced_context else "dans 24 h",
        "urgence": advanced_context.get("urgence") if advanced_context else "moyenne",
    }
    mowing_bundle = {
        "tonte_autorisee": True,
        "tonte_statut": "autorisee",
        "tonte_reason": "Fenêtre tonte acceptable.",
        "score_tonte": score_tonte,
        "score_stress": score_stress,
    }
    watering_bundle = build_watering_bundle(
        context=context,
        phase_bundle=phase_bundle,
        water_bundle=water_bundle,
        risk_bundle=risk_bundle,
        mowing_bundle=mowing_bundle,
    )
    return DecisionResult(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        action_recommandee=watering_bundle["action_recommandee"],
        action_a_eviter=watering_bundle["action_a_eviter"],
        niveau_action=risk_bundle["niveau_action"],
        fenetre_optimale=risk_bundle["fenetre_optimale"],
        risque_gazon=risk_bundle["risque_gazon"],
        objectif_arrosage=objectif_mm,
        tonte_autorisee=watering_bundle["tonte_autorisee"],
        hauteur_tonte_recommandee_cm=watering_bundle["hauteur_tonte_recommandee_cm"],
        hauteur_tonte_min_cm=watering_bundle["hauteur_tonte_min_cm"],
        hauteur_tonte_max_cm=watering_bundle["hauteur_tonte_max_cm"],
        conseil_principal=watering_bundle["conseil_principal"],
        tonte_statut=watering_bundle["tonte_statut"],
        arrosage_recommande=watering_bundle["arrosage_recommande"],
        arrosage_auto_autorise=watering_bundle["arrosage_auto_autorise"],
        type_arrosage=watering_bundle["type_arrosage"],
        arrosage_conseille=watering_bundle["arrosage_conseille"],
        watering_passages=watering_bundle["watering_passages"],
        watering_pause_minutes=watering_bundle["watering_pause_minutes"],
        phase_dominante_source=phase_bundle["phase_dominante_source"],
        sous_phase_detail=phase_bundle["sous_phase_detail"],
        sous_phase_age_days=phase_bundle["sous_phase_age_days"],
        sous_phase_progression=phase_bundle["sous_phase_progression"],
        prochaine_reevaluation=risk_bundle["prochaine_reevaluation"],
        urgence=risk_bundle["urgence"],
        raison_decision=watering_bundle["raison_decision"],
        score_hydrique=score_hydrique,
        score_stress=score_stress,
        score_tonte=score_tonte,
        decision_resume=watering_bundle["decision_resume"],
        advanced_context=advanced_context,
        water_balance=water_balance,
        phase_context=phase_bundle,
        extra={
            "jours_restants": jours_restants,
            "watering_passages": watering_bundle["watering_passages"],
            "watering_pause_minutes": watering_bundle["watering_pause_minutes"],
        },
    )


def build_decision_snapshot(
    history: list[dict[str, Any]],
    today: date | None = None,
    hour_of_day: int | None = None,
    temperature: float | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    humidite: float | None = None,
    type_sol: str = "limoneux",
    etp_capteur: float | None = None,
    humidite_sol: float | None = None,
    vent: float | None = None,
    rosee: float | None = None,
    hauteur_gazon: float | None = None,
    retour_arrosage: float | None = None,
    pluie_source: str = "capteur_pluie_24h",
    weather_profile: dict[str, Any] | None = None,
    soil_balance: dict[str, Any] | None = None,
    hauteur_min_tondeuse_cm: float | None = None,
    hauteur_max_tondeuse_cm: float | None = None,
    memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construit le snapshot historique complet utilisé par les entités HA."""
    context = DecisionContext.from_legacy_args(
        history=history,
        today=today,
        hour_of_day=hour_of_day,
        temperature=temperature,
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
        pluie_source=pluie_source,
        weather_profile=weather_profile,
        soil_balance=soil_balance,
        hauteur_min_tondeuse_cm=hauteur_min_tondeuse_cm,
        hauteur_max_tondeuse_cm=hauteur_max_tondeuse_cm,
        memory=memory,
    )
    phase_bundle = build_phase_bundle(context)
    water_bundle = build_water_bundle(context, phase_bundle)
    risk_bundle = build_risk_bundle(context, phase_bundle, water_bundle)
    mowing_bundle = build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
    watering_bundle = build_watering_bundle(context, phase_bundle, water_bundle, risk_bundle, mowing_bundle)

    result = DecisionResult(
        phase_dominante=phase_bundle["phase_dominante"],
        sous_phase=phase_bundle["sous_phase"],
        action_recommandee=watering_bundle["action_recommandee"],
        action_a_eviter=watering_bundle["action_a_eviter"],
        niveau_action=risk_bundle["niveau_action"],
        fenetre_optimale=risk_bundle["fenetre_optimale"],
        risque_gazon=risk_bundle["risque_gazon"],
        objectif_arrosage=watering_bundle["objectif_mm"],
        tonte_autorisee=mowing_bundle["tonte_autorisee"],
        conseil_principal=watering_bundle["conseil_principal"],
        tonte_statut=mowing_bundle["tonte_statut"],
        arrosage_recommande=watering_bundle["arrosage_recommande"],
        arrosage_auto_autorise=watering_bundle["arrosage_auto_autorise"],
        type_arrosage=watering_bundle["type_arrosage"],
        arrosage_conseille=watering_bundle["arrosage_conseille"],
        watering_passages=watering_bundle["watering_passages"],
        watering_pause_minutes=watering_bundle["watering_pause_minutes"],
        phase_dominante_source=phase_bundle["phase_dominante_source"],
        sous_phase_detail=phase_bundle["sous_phase_detail"],
        sous_phase_age_days=phase_bundle["sous_phase_age_days"],
        sous_phase_progression=phase_bundle["sous_phase_progression"],
        prochaine_reevaluation=risk_bundle["prochaine_reevaluation"],
        urgence=risk_bundle["urgence"],
        raison_decision=watering_bundle["raison_decision"],
        score_hydrique=risk_bundle["scores"]["score_hydrique"],
        score_stress=risk_bundle["scores"]["score_stress"],
        score_tonte=risk_bundle["scores"]["score_tonte"],
        decision_resume=watering_bundle["decision_resume"],
        advanced_context=water_bundle["advanced_context"],
        water_balance=water_bundle["water_balance"],
        phase_context=phase_bundle,
        extra={
            "mode": phase_bundle["phase_dominante"],
            "phase_active": phase_bundle["phase_dominante"],
            "date_action": phase_bundle["date_action"],
            "date_fin": phase_bundle["date_fin"],
            "phase_age_days": phase_bundle["phase_age_days"],
            "jours_restants": phase_bundle["jours_restants"],
            "etp": water_bundle["etp"],
            "humidite_sol": water_bundle["advanced_context"]["humidite_sol"],
            "vent": water_bundle["advanced_context"]["vent"],
            "rosee": water_bundle["advanced_context"]["rosee"],
            "hauteur_gazon": water_bundle["advanced_context"]["hauteur_gazon"],
            "retour_arrosage": water_bundle["advanced_context"]["retour_arrosage"],
            "pluie_source": water_bundle["advanced_context"]["pluie_source"],
            "water_balance": water_bundle["water_balance"],
            "deficit_jour": water_bundle["water_balance"]["deficit_jour"],
            "deficit_3j": water_bundle["water_balance"]["deficit_3j"],
            "deficit_7j": water_bundle["water_balance"]["deficit_7j"],
            "bilan_hydrique_journalier_mm": water_bundle["water_balance"].get("bilan_hydrique_journalier_mm"),
            "bilan_hydrique_precedent_mm": water_bundle["water_balance"].get("bilan_hydrique_precedent_mm"),
            "soil_balance": water_bundle["water_balance"].get("soil_balance"),
            "pluie_efficace": water_bundle["water_balance"]["pluie_efficace"],
            "arrosage_recent": water_bundle["water_balance"]["arrosage_recent"],
            "arrosage_recent_jour": water_bundle["water_balance"]["arrosage_recent_jour"],
            "arrosage_recent_3j": water_bundle["water_balance"]["arrosage_recent_3j"],
            "arrosage_recent_7j": water_bundle["water_balance"]["arrosage_recent_7j"],
            "bilan_hydrique_mm": water_bundle["water_balance"]["bilan_hydrique_mm"],
            "bilan_hydrique_3j": water_bundle["water_balance"]["bilan_hydrique_3j"],
            "bilan_hydrique_7j": water_bundle["water_balance"]["bilan_hydrique_7j"],
            "objectif_mm": watering_bundle["objectif_mm"],
            "objectif_mm_brut": water_bundle["objectif_mm"],
            "score_hydrique": risk_bundle["scores"]["score_hydrique"],
            "score_stress": risk_bundle["scores"]["score_stress"],
            "score_tonte": risk_bundle["scores"]["score_tonte"],
            "tonte_autorisee": mowing_bundle["tonte_autorisee"],
            "hauteur_tonte_recommandee_cm": mowing_bundle["hauteur_tonte_recommandee_cm"],
            "hauteur_tonte_min_cm": mowing_bundle["hauteur_tonte_min_cm"],
            "hauteur_tonte_max_cm": mowing_bundle["hauteur_tonte_max_cm"],
            "tonte_statut": mowing_bundle["tonte_statut"],
            "arrosage_auto_autorise": watering_bundle["arrosage_auto_autorise"],
            "arrosage_recommande": watering_bundle["arrosage_recommande"],
            "type_arrosage": watering_bundle["type_arrosage"],
            "arrosage_conseille": watering_bundle["arrosage_conseille"],
            "raison_decision": watering_bundle["raison_decision"],
            "conseil_principal": watering_bundle["conseil_principal"],
            "action_recommandee": watering_bundle["action_recommandee"],
            "action_a_eviter": watering_bundle["action_a_eviter"],
            "niveau_action": risk_bundle["niveau_action"],
            "fenetre_optimale": risk_bundle["fenetre_optimale"],
            "risque_gazon": risk_bundle["risque_gazon"],
            "urgence": risk_bundle["urgence"],
            "prochaine_reevaluation": risk_bundle["prochaine_reevaluation"],
            "decision_resume": watering_bundle["decision_resume"],
        },
    )
    return result.to_snapshot()


def build_decision_result(context: DecisionContext) -> DecisionResult:
    """Construit un résultat typé à partir d'un contexte déjà normalisé."""
    phase_bundle = build_phase_bundle(context)
    water_bundle = build_water_bundle(context, phase_bundle)
    risk_bundle = build_risk_bundle(context, phase_bundle, water_bundle)
    mowing_bundle = build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
    watering_bundle = build_watering_bundle(context, phase_bundle, water_bundle, risk_bundle, mowing_bundle)
    return DecisionResult(
        phase_dominante=phase_bundle["phase_dominante"],
        sous_phase=phase_bundle["sous_phase"],
        action_recommandee=watering_bundle["action_recommandee"],
        action_a_eviter=watering_bundle["action_a_eviter"],
        niveau_action=risk_bundle["niveau_action"],
        fenetre_optimale=risk_bundle["fenetre_optimale"],
        risque_gazon=risk_bundle["risque_gazon"],
        objectif_arrosage=watering_bundle["objectif_mm"],
        tonte_autorisee=mowing_bundle["tonte_autorisee"],
        hauteur_tonte_recommandee_cm=mowing_bundle["hauteur_tonte_recommandee_cm"],
        hauteur_tonte_min_cm=mowing_bundle["hauteur_tonte_min_cm"],
        hauteur_tonte_max_cm=mowing_bundle["hauteur_tonte_max_cm"],
        conseil_principal=watering_bundle["conseil_principal"],
        tonte_statut=mowing_bundle["tonte_statut"],
        arrosage_recommande=watering_bundle["arrosage_recommande"],
        arrosage_auto_autorise=watering_bundle["arrosage_auto_autorise"],
        type_arrosage=watering_bundle["type_arrosage"],
        arrosage_conseille=watering_bundle["arrosage_conseille"],
        phase_dominante_source=phase_bundle["phase_dominante_source"],
        sous_phase_detail=phase_bundle["sous_phase_detail"],
        sous_phase_age_days=phase_bundle["sous_phase_age_days"],
        sous_phase_progression=phase_bundle["sous_phase_progression"],
        prochaine_reevaluation=risk_bundle["prochaine_reevaluation"],
        urgence=risk_bundle["urgence"],
        raison_decision=watering_bundle["raison_decision"],
        score_hydrique=risk_bundle["scores"]["score_hydrique"],
        score_stress=risk_bundle["scores"]["score_stress"],
        score_tonte=risk_bundle["scores"]["score_tonte"],
        decision_resume=watering_bundle["decision_resume"],
        advanced_context=water_bundle["advanced_context"],
        water_balance=water_bundle["water_balance"],
        phase_context=phase_bundle,
        extra={
            "objectif_mm_brut": water_bundle["objectif_mm"],
            "objectif_mm_executable": watering_bundle["objectif_mm"],
        },
    )
