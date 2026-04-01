from __future__ import annotations

"""Logique pure d'arrosage et de recommandations utilisateur."""

import logging
from math import ceil
from datetime import date, timedelta
from typing import Any

from .const import (
    APPLICATION_TYPE_FOLIAIRE,
    APPLICATION_TYPE_SOL,
    DEFAULT_AUTO_IRRIGATION_ENABLED,
)
from .decision_models import DecisionContext
from .guidance import _confidence_assessment, compute_watering_profile, is_fertilization_window_open
from .memory import compute_application_state
from .scores import classify_stress_level
from .water import compute_advanced_context, compute_etp, compute_water_balance

_LOGGER = logging.getLogger(__name__)


def build_water_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
) -> dict[str, Any]:
    advanced_context = compute_advanced_context(
        humidite_sol=context.humidite_sol,
        vent=context.vent,
        rosee=context.rosee,
        hauteur_gazon=context.hauteur_gazon,
        retour_arrosage=context.retour_arrosage,
        pluie_source=context.pluie_source,
        type_sol=context.type_sol,
        weather_profile=context.weather_profile,
    )
    etp = compute_etp(
        temperature=context.temperature,
        pluie_24h=context.pluie_24h,
        etp_capteur=context.etp_capteur,
        weather_profile=context.weather_profile,
    )
    water_balance = compute_water_balance(
        history=context.history,
        today=context.today,
        etp=etp,
        pluie_24h=context.pluie_24h,
        pluie_demain=context.pluie_demain,
        pluie_j2=context.pluie_j2,
        type_sol=context.type_sol,
        recent_watering_mm_override=context.retour_arrosage,
        advanced_context=advanced_context,
        weather_profile=context.weather_profile,
    )
    balance_snapshot = dict(water_balance)
    balance_snapshot["bilan_hydrique_journalier_mm"] = balance_snapshot.get("bilan_hydrique_mm", 0.0)
    if context.soil_balance:
        reserve_mm = context.soil_balance.get("reserve_mm")
        if reserve_mm is not None:
            balance_snapshot["bilan_hydrique_mm"] = reserve_mm
        balance_snapshot["soil_balance"] = context.soil_balance
        balance_snapshot["bilan_hydrique_precedent_mm"] = context.soil_balance.get("previous_reserve_mm")
        balance_snapshot["pluie_jour_mm"] = context.soil_balance.get("pluie_mm")
        balance_snapshot["arrosage_jour_mm"] = context.soil_balance.get("arrosage_mm")
        balance_snapshot["etp_jour_mm"] = context.soil_balance.get("etp_mm")
        balance_snapshot["delta_jour_mm"] = context.soil_balance.get("delta_mm")
    watering_profile = compute_watering_profile(
        phase_dominante=phase_bundle["phase_dominante"],
        sous_phase=phase_bundle["sous_phase"],
        water_balance=balance_snapshot,
        today=context.today,
        pluie_24h=context.pluie_24h,
        pluie_demain=context.pluie_demain,
        humidite=context.humidite,
        temperature=context.temperature,
        etp=etp,
        type_sol=context.type_sol,
        weather_profile=context.weather_profile,
        history=context.history,
        sous_phase_age_days=phase_bundle.get("sous_phase_age_days"),
        sous_phase_progression=phase_bundle.get("sous_phase_progression"),
        hauteur_gazon=context.hauteur_gazon,
        pluie_j2=context.pluie_j2,
        pluie_3j=context.pluie_3j,
        pluie_probabilite_max_3j=context.pluie_probabilite_max_3j,
    )
    return {
        "etp": etp,
        "advanced_context": advanced_context,
        "water_balance": balance_snapshot,
        "objectif_mm": watering_profile["mm_final_recommande"],
        "objectif_mm_brut": watering_profile["deficit_brut_mm"],
        "deficit_mm_brut": watering_profile.get("deficit_mm_brut", watering_profile["deficit_brut_mm"]),
        "deficit_mm_ajuste": watering_profile.get("deficit_mm_ajuste"),
        "mm_cible": watering_profile["mm_cible"],
        "mm_final_recommande": watering_profile["mm_final_recommande"],
        "mm_final": watering_profile.get("mm_final", watering_profile["mm_final_recommande"]),
        "mm_requested": watering_profile.get("mm_requested", watering_profile["mm_cible"]),
        "mm_applied": watering_profile.get("mm_applied", watering_profile["mm_final_recommande"]),
        "mm_detected": watering_profile.get("mm_detected"),
        "type_arrosage": watering_profile["type_arrosage"],
        "arrosage_recommande": watering_profile["arrosage_recommande"],
        "arrosage_auto_autorise": watering_profile["arrosage_auto_autorise"],
        "arrosage_conseille": watering_profile["arrosage_conseille"],
        "watering_passages": watering_profile["watering_passages"],
        "watering_pause_minutes": watering_profile["watering_pause_minutes"],
        "fractionnement": watering_profile["fractionnement"],
        "niveau_confiance": watering_profile["niveau_confiance"],
        "confidence_score": watering_profile.get("confidence_score"),
        "confidence_reasons": watering_profile.get("confidence_reasons"),
        "heat_stress_level": watering_profile.get("heat_stress_level"),
        "heat_stress_phase": watering_profile.get("heat_stress_phase"),
        "raison_decision_base": watering_profile["raison_decision_base"],
        "block_reason": watering_profile.get("block_reason"),
        "recent_watering_count_7j": watering_profile["recent_watering_count_7j"],
        "recent_watering_mm_7j": watering_profile["recent_watering_mm_7j"],
        "weekly_guardrail_mm_min": watering_profile.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": watering_profile.get("weekly_guardrail_mm_max"),
        "weekly_guardrail_reason": watering_profile.get("weekly_guardrail_reason"),
        "cooldown_24h_hours": watering_profile.get("cooldown_24h_hours"),
        "pluie_probabilite_24h": watering_profile.get("pluie_probabilite_24h"),
        "mm_detected_24h": watering_profile.get("mm_detected_24h"),
        "surface_sec": watering_profile.get("surface_sec"),
        "sursemis_micro_apport_allowed": watering_profile.get("sursemis_micro_apport_allowed"),
        "sursemis_block_reason": watering_profile.get("sursemis_block_reason"),
        "sursemis_reason": watering_profile.get("sursemis_reason"),
        "sursemis_seuil_declencheur": watering_profile.get("sursemis_seuil_declencheur"),
        "sursemis_policy": watering_profile.get("sursemis_policy"),
        "sursemis_transition_ready": watering_profile.get("sursemis_transition_ready"),
        "sursemis_tonte_count": watering_profile.get("sursemis_tonte_count"),
        "soil_profile": watering_profile.get("soil_profile"),
        "soil_retention_factor": watering_profile.get("soil_retention_factor"),
        "soil_drainage_factor": watering_profile.get("soil_drainage_factor"),
        "soil_infiltration_factor": watering_profile.get("soil_infiltration_factor"),
        "soil_need_factor": watering_profile.get("soil_need_factor"),
        "watering_window_start_minute": watering_profile.get("watering_window_start_minute"),
        "watering_window_end_minute": watering_profile.get("watering_window_end_minute"),
        "watering_window_optimal_start_minute": watering_profile.get("watering_window_optimal_start_minute"),
        "watering_window_optimal_end_minute": watering_profile.get("watering_window_optimal_end_minute"),
        "watering_window_acceptable_end_minute": watering_profile.get("watering_window_acceptable_end_minute"),
        "watering_evening_start_minute": watering_profile.get("watering_evening_start_minute"),
        "watering_evening_end_minute": watering_profile.get("watering_evening_end_minute"),
        "watering_window_profile": watering_profile.get("watering_window_profile"),
        "watering_evening_allowed": watering_profile.get("watering_evening_allowed"),
        "weekly_guardrail_mm_min": watering_profile.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": watering_profile.get("weekly_guardrail_mm_max"),
        "weekly_guardrail_reason": watering_profile.get("weekly_guardrail_reason"),
        "soil_profile": watering_profile.get("soil_profile"),
        "soil_retention_factor": watering_profile.get("soil_retention_factor"),
        "soil_drainage_factor": watering_profile.get("soil_drainage_factor"),
        "soil_infiltration_factor": watering_profile.get("soil_infiltration_factor"),
        "soil_need_factor": watering_profile.get("soil_need_factor"),
    }


def _passage_spacing_text(passages: int) -> str:
    if passages <= 1:
        return "en un passage"
    if passages == 2:
        return "en 2 passages courts espacés de 20 à 30 min"
    return f"en {passages} passages courts espacés de 20 à 30 min"


def _watering_needed_text() -> str:
    return "Éviter tout arrosage inutile."


def _watering_window_phrase(window: str, hour_of_day: int) -> str:
    if window == "ce_matin":
        return "ce matin"
    if window == "demain_matin":
        return "demain matin"
    if window == "apres_pluie":
        return "après la pluie"
    if window == "soir":
        return "ce soir"
    if window == "maintenant":
        return "maintenant" if hour_of_day >= 9 else "ce matin"
    if window == "attendre":
        return "plus tard"
    return "demain matin" if hour_of_day >= 12 else "ce matin"


def _watering_target_date(window: str, today: date) -> str | None:
    if window == "ce_matin":
        return today.isoformat()
    if window == "demain_matin":
        return (today + timedelta(days=1)).isoformat()
    if window in {"maintenant", "apres_pluie", "soir"}:
        return today.isoformat()
    return None


def _soil_fractionation_passages(
    phase_dominante: str,
    sous_phase: str,
    type_sol: str,
    objectif_mm: float,
    stress_level: str,
    temperature: float | None = None,
    humidite: float | None = None,
    etp: float | None = None,
) -> int:
    soil_profile = (type_sol or "limoneux").strip().lower()
    temperature = temperature if temperature is not None else 0.0
    humidite = humidite if humidite is not None else 0.0
    etp = etp if etp is not None else 0.0

    if objectif_mm <= 0:
        return 1

    max_mm_per_passage = 2.0
    if phase_dominante == "Sursemis":
        if sous_phase == "Germination":
            max_mm_per_passage = 1.0
        elif sous_phase == "Enracinement":
            max_mm_per_passage = 1.5
        else:
            max_mm_per_passage = 2.0
    elif phase_dominante in {"Fertilisation", "Biostimulant"}:
        max_mm_per_passage = 1.5 if soil_profile == "argileux" or stress_level == "fort" else 2.0
    elif phase_dominante == "Agent Mouillant":
        max_mm_per_passage = 1.5 if temperature >= 28 or etp >= 4 or humidite <= 45 else 2.0
    elif soil_profile == "argileux" and objectif_mm >= 2.5:
        max_mm_per_passage = 1.5

    if temperature >= 30 or etp >= 4 or humidite <= 40:
        max_mm_per_passage = min(max_mm_per_passage, 1.0 if phase_dominante == "Sursemis" else 1.5)

    if objectif_mm > 2.0:
        max_mm_per_passage = min(max_mm_per_passage, 1.5 if phase_dominante == "Sursemis" else 2.0)

    if stress_level == "fort" and objectif_mm >= 2.0:
        max_mm_per_passage = min(max_mm_per_passage, 1.5)

    max_mm_per_passage = max(0.5, max_mm_per_passage)
    passages = ceil(objectif_mm / max_mm_per_passage)
    if phase_dominante == "Sursemis" and objectif_mm > 0.5:
        passages = max(passages, 2 if objectif_mm > 1.0 else 1)
    if soil_profile == "argileux" and objectif_mm >= 2.5:
        passages = max(passages, 2)
    if stress_level == "fort" and objectif_mm >= 2.0:
        passages = max(passages, 2)
    return max(1, passages)


def _watering_style_text(
    phase_dominante: str,
    type_sol: str,
    objectif_mm: float,
    stress_level: str,
    passage_count: int | None = None,
) -> str:
    passages = passage_count or _soil_fractionation_passages(
        phase_dominante,
        "Enracinement",
        type_sol,
        objectif_mm,
        stress_level,
    )
    if passages <= 1:
        return "en un passage profond tôt le matin"
    if passages == 2:
        return "en 2 passages courts espacés de 20 à 30 min"
    return "en 3 passages courts espacés de 20 à 30 min"


def _watering_amount_text(mm: float) -> str:
    if mm <= 0:
        return "Aucun arrosage nécessaire."
    return f"{mm:.1f} mm"


def _hydric_summary_text(deficit_brut_mm: float, deficit_mm_ajuste: float, final_mm: float) -> str:
    return (
        f"Déficit: brut={deficit_brut_mm:.1f} mm, "
        f"ajusté={deficit_mm_ajuste:.1f} mm, final={final_mm:.1f} mm."
    )


def _watering_pause_minutes(passages: int) -> int:
    if passages <= 1:
        return 0
    if passages == 2:
        return 25
    return 20


def _application_payload(application_state: dict[str, Any]) -> dict[str, Any]:
    summary = application_state.get("derniere_application")
    if not isinstance(summary, dict):
        summary = {}
    return {
        "derniere_application": summary or None,
        "application_type": application_state.get("application_type"),
        "application_requires_watering_after": bool(
            application_state.get("application_requires_watering_after", False)
        ),
        "application_post_watering_mm": float(application_state.get("application_post_watering_mm") or 0.0),
        "application_irrigation_block_hours": float(
            application_state.get("application_irrigation_block_hours") or 0.0
        ),
        "application_irrigation_delay_minutes": float(
            application_state.get("application_irrigation_delay_minutes") or 0.0
        ),
        "application_irrigation_mode": application_state.get("application_irrigation_mode"),
        "application_label_notes": application_state.get("application_label_notes"),
        "application_block_until": application_state.get("application_block_until"),
        "application_block_active": bool(application_state.get("application_block_active", False)),
        "application_block_remaining_minutes": float(
            application_state.get("application_block_remaining_minutes") or 0.0
        ),
        "application_post_watering_pending": bool(
            application_state.get("application_post_watering_pending", False)
        ),
        "application_post_watering_ready_at": application_state.get("application_post_watering_ready_at"),
        "application_post_watering_delay_remaining_minutes": float(
            application_state.get("application_post_watering_delay_remaining_minutes") or 0.0
        ),
        "application_post_watering_ready": bool(
            application_state.get("application_post_watering_ready", False)
        ),
        "application_post_watering_remaining_mm": float(
            application_state.get("application_post_watering_remaining_mm") or 0.0
        ),
    }


def build_watering_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
    mowing_bundle: dict[str, Any],
) -> dict[str, Any]:
    phase_dominante = phase_bundle["phase_dominante"]
    sous_phase = phase_bundle["sous_phase"]
    water_balance = water_bundle["water_balance"]
    advanced_context = water_bundle["advanced_context"]
    objectif_mm_brut = water_bundle.get("objectif_mm_brut", water_bundle["objectif_mm"])
    objectif_mm = water_bundle["objectif_mm"]
    deficit_mm_brut = water_bundle.get("deficit_mm_brut", objectif_mm_brut)
    deficit_mm_ajuste = water_bundle.get("deficit_mm_ajuste", objectif_mm_brut)
    mm_cible = water_bundle.get("mm_cible", objectif_mm)
    mm_final_recommande = water_bundle.get("mm_final_recommande", objectif_mm)
    mm_final = water_bundle.get("mm_final", mm_final_recommande)
    fractionnement = water_bundle.get("fractionnement") or {
        "enabled": False,
        "passages": 1,
        "pause_minutes": 0,
        "max_mm_per_passage": 0.0,
        "reason": "unknown",
    }
    niveau_confiance = water_bundle.get("niveau_confiance")
    heat_stress_level = water_bundle.get("heat_stress_level") or risk_bundle.get("heat_stress_level")
    heat_stress_phase = water_bundle.get("heat_stress_phase") or risk_bundle.get("heat_stress_phase") or "normal"
    watering_window_start_minute = water_bundle.get("watering_window_start_minute") or risk_bundle.get(
        "watering_window_start_minute"
    )
    watering_window_end_minute = water_bundle.get("watering_window_end_minute") or risk_bundle.get(
        "watering_window_end_minute"
    )
    watering_window_optimal_start_minute = water_bundle.get("watering_window_optimal_start_minute") or risk_bundle.get(
        "watering_window_optimal_start_minute"
    )
    watering_window_optimal_end_minute = water_bundle.get("watering_window_optimal_end_minute") or risk_bundle.get(
        "watering_window_optimal_end_minute"
    )
    watering_window_acceptable_end_minute = water_bundle.get(
        "watering_window_acceptable_end_minute"
    ) or risk_bundle.get("watering_window_acceptable_end_minute")
    niveau_action = risk_bundle["niveau_action"]
    fenetre_optimale = risk_bundle["fenetre_optimale"]
    risque_gazon = risk_bundle["risque_gazon"]
    prochaine_reevaluation = risk_bundle["prochaine_reevaluation"]
    score_tonte = mowing_bundle["score_tonte"]
    score_stress = mowing_bundle["score_stress"]
    tonte_ok = mowing_bundle["tonte_autorisee"]
    tonte_reason = mowing_bundle["tonte_reason"]

    now_hour = context.hour_of_day if context.hour_of_day is not None else 0
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    bilan_hydrique_3j = water_balance.get("bilan_hydrique_3j", 0.0)
    bilan_hydrique_7j = water_balance.get("bilan_hydrique_7j", 0.0)
    pluie_efficace = water_balance.get("pluie_efficace", 0.0)
    pluie_24h = context.pluie_24h or 0.0
    pluie_demain = context.pluie_demain or 0.0
    pluie_j2 = context.pluie_j2 or 0.0
    pluie_3j = context.pluie_3j or 0.0
    pluie_probabilite_max_3j = context.pluie_probabilite_max_3j or 0.0
    humidite = context.humidite or 0.0
    temperature = context.temperature or 0.0
    etp = water_bundle["etp"] or 0.0
    stress_level = classify_stress_level(
        score_hydrique=int(risk_bundle["scores"]["score_hydrique"]),
        score_stress=int(score_stress),
        water_balance=water_balance,
        temperature=temperature,
        etp=etp,
    )
    fenetre_texte = _watering_window_phrase(fenetre_optimale, now_hour)
    watering_target_date = _watering_target_date(fenetre_optimale, context.today)
    fertilization_allowed = is_fertilization_window_open(
        today=context.today,
        temperature=temperature,
        humidite=humidite,
        etp=etp,
        water_balance=water_balance,
    )
    soil_style = context.type_sol

    pluie_significative = pluie_24h >= 4 or pluie_demain >= 4
    pluie_compensatrice = objectif_mm > 0 and pluie_demain >= max(2.0, objectif_mm * 0.8)
    pluie_proche = (
        pluie_24h >= 4.0
        or pluie_demain >= 4.0
        or pluie_j2 >= 4.0
        or pluie_3j >= 6.0
        or pluie_probabilite_max_3j >= 80.0
    )
    stress_thermique = temperature >= 30 and etp >= 4
    humidite_haute = humidite >= 85
    application_state = compute_application_state(context.history)
    application_payload = _application_payload(application_state)
    application_type = application_state.get("application_type")
    application_mode = str(application_state.get("application_irrigation_mode") or "").strip().lower()
    application_block_active = bool(application_state.get("application_block_active"))
    application_block_remaining_minutes = float(
        application_state.get("application_block_remaining_minutes") or 0.0
    )
    application_post_watering_pending = bool(application_state.get("application_post_watering_pending"))
    application_post_watering_ready = bool(application_state.get("application_post_watering_ready"))
    application_post_watering_delay_remaining_minutes = float(
        application_state.get("application_post_watering_delay_remaining_minutes") or 0.0
    )
    application_post_watering_remaining_mm = float(
        application_state.get("application_post_watering_remaining_mm") or 0.0
    )
    application_requires_watering_after = bool(
        application_state.get("application_requires_watering_after", False)
    )
    application_label = "Application"
    application_summary = application_state.get("derniere_application")
    auto_irrigation_enabled = bool(
        context.memory.get("auto_irrigation_enabled", DEFAULT_AUTO_IRRIGATION_ENABLED)
        if context.memory
        else DEFAULT_AUTO_IRRIGATION_ENABLED
    )
    if isinstance(application_summary, dict):
        application_label = str(
            application_summary.get("libelle")
            or application_summary.get("produit")
            or application_summary.get("type")
            or application_label
        )
    application_block_until = application_state.get("application_block_until")
    application_post_watering_ready_at = application_state.get("application_post_watering_ready_at")
    besoin_eau = (
        bilan_hydrique_mm <= -0.2
        or deficit_3j > 0.8
        or deficit_7j > 1.5
    )
    recommande = objectif_mm > 0 and besoin_eau
    auto_ok = auto_irrigation_enabled and phase_dominante in {
        "Normal",
        "Fertilisation",
        "Biostimulant",
        "Agent Mouillant",
        "Scarification",
    }
    block_reason_value = water_bundle.get("block_reason")
    watering_passages = 1
    watering_pause_minutes = 0

    if phase_dominante == "Hivernage":
        objectif_mm = 0.0
        return {
            "objectif_mm": 0.0,
            "objectif_mm_brut": objectif_mm_brut,
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": "N'arrose pas et limite les interventions.",
            "action_recommandee": "Surveille uniquement.",
            "action_a_eviter": "Arroser fréquemment.",
            "raison_decision": (
                f"Hivernage actif: repos végétatif. "
                f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, 0.0)}"
            ),
            "decision_resume": {
                "faire": False,
                "action": "aucune_action",
                "moment": "attendre",
                "objectif_mm": objectif_mm,
                "type_arrosage": "bloque",
                "niveau_action": niveau_action,
                "risque_gazon": risque_gazon,
            },
            "watering_passages": watering_passages,
            "watering_pause_minutes": watering_pause_minutes,
            "watering_target_date": watering_target_date,
            **application_payload,
        }

    application_type_known = application_type in {APPLICATION_TYPE_SOL, APPLICATION_TYPE_FOLIAIRE}

    if application_summary and not application_type_known:
        objectif_mm = 0.0
        return {
            "objectif_mm": 0.0,
            "objectif_mm_brut": objectif_mm_brut,
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": (
                f"{application_label}: type d'application inconnu, aucun arrosage automatique ne doit être lancé."
            ),
            "action_recommandee": "Vérifie l'étiquette ou renseigne le type d'application avant d'arroser.",
            "action_a_eviter": "Lancer un arrosage sans type d'application confirmé.",
            "raison_decision": (
                "Type d'application inconnu: sécurité renforcée, aucun arrosage automatique. "
                f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, 0.0)}"
            ),
            "decision_resume": {
                "faire": False,
                "action": "aucune_action",
                "moment": "attendre",
                "objectif_mm": 0.0,
                "type_arrosage": "bloque",
                "niveau_action": "surveiller",
                "risque_gazon": risque_gazon,
            },
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": risque_gazon,
            "prochaine_reevaluation": prochaine_reevaluation,
            "watering_passages": watering_passages,
            "watering_pause_minutes": watering_pause_minutes,
            "watering_target_date": watering_target_date,
            **application_payload,
        }

    if application_block_active:
        objectif_mm = 0.0
        return {
            "objectif_mm": 0.0,
            "objectif_mm_brut": objectif_mm_brut,
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": f"{application_label}: l'arrosage est bloqué jusqu'à la fin de la fenêtre de protection.",
            "action_recommandee": "Attends la fin du bloc applicatif avant d'arroser.",
            "action_a_eviter": "Arroser pendant la fenêtre de protection.",
            "raison_decision": (
                f"Bloc applicatif actif jusqu'au {application_block_until or 'prochain créneau autorisé'}. "
                f"Temps restant={application_block_remaining_minutes:.0f} min. "
                f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, 0.0)}"
            ),
            "decision_resume": {
                "faire": False,
                "action": "aucune_action",
                "moment": "attendre",
                "objectif_mm": 0.0,
                "type_arrosage": "bloque",
                "niveau_action": "surveiller",
                "risque_gazon": risque_gazon,
            },
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": risque_gazon,
            "prochaine_reevaluation": prochaine_reevaluation,
            "watering_passages": watering_passages,
            "watering_pause_minutes": watering_pause_minutes,
            "watering_target_date": watering_target_date,
            **application_payload,
        }

    if application_summary and application_type == APPLICATION_TYPE_FOLIAIRE:
        objectif_mm = 0.0
        return {
            "objectif_mm": 0.0,
            "objectif_mm_brut": objectif_mm_brut,
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": (
                f"{application_label}: traitement foliaire sans arrosage automatique pendant la fenêtre de protection."
            ),
            "action_recommandee": "Attends la fin de la protection avant toute irrigation.",
            "action_a_eviter": "Arroser une application foliaire trop tôt.",
            "raison_decision": (
                f"Application foliaire: arrosage automatique interdit, "
                f"bloc restant={application_block_remaining_minutes:.0f} min, "
                f"mode={application_mode or 'suggestion'}. "
                f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, 0.0)}"
            ),
            "decision_resume": {
                "faire": False,
                "action": "aucune_action",
                "moment": "attendre",
                "objectif_mm": 0.0,
                "type_arrosage": "bloque",
                "niveau_action": "surveiller",
                "risque_gazon": risque_gazon,
            },
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": risque_gazon,
            "prochaine_reevaluation": prochaine_reevaluation,
            "watering_passages": watering_passages,
            "watering_pause_minutes": watering_pause_minutes,
            "watering_target_date": watering_target_date,
            **application_payload,
        }

    if application_requires_watering_after and application_type == APPLICATION_TYPE_SOL and application_post_watering_pending:
        if not application_post_watering_ready:
            return {
                "objectif_mm": 0.0,
                "objectif_mm_brut": objectif_mm_brut,
                "tonte_autorisee": tonte_ok,
                "tonte_statut": mowing_bundle["tonte_statut"],
                "arrosage_auto_autorise": False,
                "arrosage_recommande": False,
                "type_arrosage": "personnalise",
                "arrosage_conseille": "personnalise",
                "conseil_principal": (
                    f"{application_label}: attendre encore {application_post_watering_delay_remaining_minutes:.0f} min "
                    "avant l'arrosage technique."
                ),
                "action_recommandee": "Attends la fin du délai applicatif avant d'arroser.",
                "action_a_eviter": "Arroser avant la fin du délai d'incorporation.",
                "raison_decision": (
                    f"Application technique différée: délai restant {application_post_watering_delay_remaining_minutes:.0f} min, "
                    f"mode={application_mode or 'auto'}. "
                    f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, 0.0)}"
                ),
                "decision_resume": {
                    "faire": False,
                    "action": "aucune_action",
                    "moment": "attendre",
                    "objectif_mm": 0.0,
                    "type_arrosage": "personnalise",
                    "niveau_action": niveau_action,
                    "risque_gazon": risque_gazon,
                },
                "watering_passages": watering_passages,
                "watering_pause_minutes": watering_pause_minutes,
                "watering_target_date": watering_target_date,
                **application_payload,
            }

        objectif_mm = round(max(0.5, application_post_watering_remaining_mm or 0.0), 1)
        passages = _soil_fractionation_passages(
            phase_dominante,
            sous_phase,
            soil_style,
            objectif_mm,
            stress_level,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
        )
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        if application_mode == "suggestion":
            return {
                "objectif_mm": 0.0,
                "objectif_mm_brut": objectif_mm_brut,
                "tonte_autorisee": tonte_ok,
                "tonte_statut": mowing_bundle["tonte_statut"],
                "arrosage_auto_autorise": False,
                "arrosage_recommande": False,
                "type_arrosage": "personnalise",
                "arrosage_conseille": "personnalise",
                "conseil_principal": f"{application_label}: arrosage technique suggéré, sans lancement automatique.",
                "action_recommandee": (
                    f"Suggestion d'arrosage technique: {objectif_mm:.1f} mm {style_text} "
                    "si l'étiquette du produit l'autorise."
                ),
                "action_a_eviter": "Lancer un arrosage automatique non confirmé.",
                "raison_decision": (
                    f"Application technique en suggestion uniquement: {application_label}, "
                    f"mode=suggestion. "
                    f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, 0.0)}"
                ),
                "decision_resume": {
                    "faire": False,
                    "action": "aucune_action",
                    "moment": "attendre",
                    "objectif_mm": 0.0,
                    "type_arrosage": "personnalise",
                    "niveau_action": niveau_action,
                    "risque_gazon": risque_gazon,
                },
                "watering_passages": watering_passages,
                "watering_pause_minutes": watering_pause_minutes,
                "watering_target_date": watering_target_date,
                **application_payload,
            }

        if application_mode == "manuel":
            conseil_principal = (
                f"{application_label}: arrosage manuel immédiat pour activer ou incorporer le produit."
            )
        else:
            conseil_principal = f"{application_label}: arrose maintenant pour activer/incorporer le produit."
        if application_mode == "manuel":
            action_recommandee = (
                f"Arrosage manuel immédiat requis: applique {objectif_mm:.1f} mm {style_text}."
            )
        else:
            action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text} en arrosage technique."
        action_a_eviter = "Arroser en excès ou trop tard."
        auto_autorise = application_mode in {"", "auto"}
        return {
            "objectif_mm": objectif_mm,
            "objectif_mm_brut": objectif_mm_brut,
            "tonte_autorisee": tonte_ok,
            "tonte_statut": mowing_bundle["tonte_statut"],
            "arrosage_auto_autorise": auto_autorise,
            "arrosage_recommande": True,
            "type_arrosage": "application_technique",
            "arrosage_conseille": "application_technique",
            "conseil_principal": conseil_principal,
            "action_recommandee": action_recommandee,
            "action_a_eviter": action_a_eviter,
            "raison_decision": (
                f"Application technique en attente: {application_label}, "
                f"mm restant={application_post_watering_remaining_mm:.1f}, "
                f"fenêtre={fenetre_texte}, bilan={bilan_hydrique_mm:.1f} mm, mode={application_mode or 'auto'}. "
                f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, objectif_mm)}"
            ),
            "decision_resume": {
                "faire": True,
                "action": "arrosage",
                "moment": fenetre_optimale,
                "objectif_mm": objectif_mm,
                "type_arrosage": "application_technique",
                "niveau_action": niveau_action,
                "risque_gazon": risque_gazon,
            },
            "watering_passages": passages,
            "watering_pause_minutes": _watering_pause_minutes(passages),
            "watering_target_date": watering_target_date,
            **application_payload,
        }

    if phase_dominante == "Traitement":
        objectif_mm = 0.0
        return {
            "objectif_mm": 0.0,
            "objectif_mm_brut": objectif_mm_brut,
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": f"Laisser agir le traitement encore {phase_bundle['jours_restants']} jour(s).",
            "action_recommandee": "Surveiller l'état du gazon sans intervention hydrique.",
            "action_a_eviter": "Tondre ou arroser.",
            "raison_decision": (
                f"Traitement actif: tonte et arrosage bloqués. "
                f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, 0.0)}"
            ),
            "decision_resume": {
                "faire": False,
                "action": "aucune_action",
                "moment": "attendre",
                "objectif_mm": objectif_mm,
                "type_arrosage": "bloque",
                "niveau_action": niveau_action,
                "risque_gazon": risque_gazon,
            },
            "watering_passages": watering_passages,
            "watering_pause_minutes": watering_pause_minutes,
            "watering_target_date": watering_target_date,
            **application_payload,
        }

    if phase_dominante in {"Fertilisation", "Biostimulant"} and not fertilization_allowed:
        objectif_mm = 0.0
        return {
            "objectif_mm": 0.0,
            "objectif_mm_brut": objectif_mm_brut,
            "tonte_autorisee": tonte_ok,
            "tonte_statut": mowing_bundle["tonte_statut"],
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": (
                f"{phase_dominante}: reporte l'application, la fenêtre est trop chaude ou trop sèche."
            ),
            "action_recommandee": "Attends un créneau plus frais et moins stressant.",
            "action_a_eviter": "Fertiliser sous chaleur ou stress hydrique.",
            "raison_decision": (
                f"{phase_dominante} bloqué: bilan={bilan_hydrique_mm:.1f} mm, "
                f"stress={stress_level}, température={temperature:.1f}°C, ETP={etp:.1f} mm. "
                f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, 0.0)}"
            ),
            "decision_resume": {
                "faire": False,
                "action": "aucune_action",
                "moment": "attendre",
                "objectif_mm": 0.0,
                "type_arrosage": "bloque",
                "niveau_action": "surveiller",
                "risque_gazon": risque_gazon,
            },
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": risque_gazon,
            "prochaine_reevaluation": prochaine_reevaluation,
            "watering_passages": watering_passages,
            "watering_pause_minutes": watering_pause_minutes,
            "watering_target_date": watering_target_date,
        }

    if phase_dominante == "Sursemis":
        sursemis_allowed = bool(water_bundle.get("sursemis_micro_apport_allowed"))
        surface_sec = bool(water_bundle.get("surface_sec"))
        pluie_probabilite_24h = float(water_bundle.get("pluie_probabilite_24h") or 0.0)
        mm_detected_24h = float(water_bundle.get("mm_detected_24h") or 0.0)
        sursemis_reason = str(water_bundle.get("sursemis_reason") or "")
        sursemis_thresholds = str(water_bundle.get("sursemis_seuil_declencheur") or "")
        sursemis_block_reason = water_bundle.get("sursemis_block_reason")

        if sursemis_allowed and objectif_mm > 0:
            objectif_mm = 0.5
            arrosage_recommande = True
            arrosage_auto_autorise = False
            type_arrosage = "manuel_frequent"
            arrosage_conseille = "personnalise"
            conseil_principal = f"Arrose {fenetre_texte} en un passage (micro-apport de 0.5 mm)."
            action_recommandee = "Appliquer 0.5 mm en un passage."
            action_a_eviter = "Répéter un micro-arrosage ou arroser plus fort."
        else:
            objectif_mm = 0.0
            arrosage_recommande = False
            arrosage_auto_autorise = False
            type_arrosage = "personnalise"
            arrosage_conseille = "personnalise"
            conseil_principal = sursemis_reason or "Sursemis: micro-apport non nécessaire."
            action_recommandee = "Surveille l'humidité et réévalue au prochain créneau."
            action_a_eviter = "Multiplier les petits cycles."
        watering_passages = 1
        watering_pause_minutes = 0
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=context.weather_profile,
            soil_profile=soil_style,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=sursemis_block_reason,
            mm_final=objectif_mm,
        )
        raison_decision_sursemis = (
            f"Sursemis / {sous_phase}: micro-apport 0.5 mm conditionné par pluie, humidité et température. "
            f"pluie_24h={pluie_24h:.1f} mm, pluie_demain={pluie_demain:.1f} mm, "
            f"pluie_probabilite_24h={pluie_probabilite_24h:.1f}%, bilan_hydrique_mm={bilan_hydrique_mm:.1f} mm, "
            f"mm_detected_24h={mm_detected_24h:.1f} mm, temperature={temperature:.1f}°C, "
            f"surface_sec={surface_sec}. "
            f"{sursemis_reason} "
            f"Seuil={sursemis_thresholds}. "
            f"{_hydric_summary_text(objectif_mm_brut, deficit_mm_ajuste, objectif_mm)}"
        )
        return {
            "objectif_mm": objectif_mm,
            "objectif_mm_brut": objectif_mm_brut,
            "deficit_brut_mm": deficit_mm_brut,
            "deficit_mm_brut": deficit_mm_brut,
            "deficit_mm_ajuste": deficit_mm_ajuste,
            "mm_cible": objectif_mm,
            "mm_final_recommande": objectif_mm,
            "mm_final": objectif_mm,
            "mm_requested": objectif_mm,
            "mm_applied": objectif_mm,
            "mm_detected": water_bundle.get("mm_detected"),
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": objectif_mm > 0,
            "type_arrosage": type_arrosage,
            "arrosage_conseille": arrosage_conseille,
            "conseil_principal": conseil_principal,
            "action_recommandee": action_recommandee,
            "action_a_eviter": action_a_eviter,
            "raison_decision": raison_decision_sursemis,
            "niveau_confiance": niveau_confiance,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "heat_stress_level": heat_stress_level,
            "heat_stress_phase": heat_stress_phase,
            "weekly_guardrail_mm_min": water_bundle.get("weekly_guardrail_mm_min"),
            "weekly_guardrail_mm_max": water_bundle.get("weekly_guardrail_mm_max"),
            "weekly_guardrail_reason": water_bundle.get("weekly_guardrail_reason"),
            "soil_profile": water_bundle.get("soil_profile"),
            "soil_retention_factor": water_bundle.get("soil_retention_factor"),
            "soil_drainage_factor": water_bundle.get("soil_drainage_factor"),
            "soil_infiltration_factor": water_bundle.get("soil_infiltration_factor"),
            "soil_need_factor": water_bundle.get("soil_need_factor"),
            "decision_resume": {
                "faire": objectif_mm > 0,
                "action": "arrosage" if objectif_mm > 0 else "aucune_action",
                "moment": fenetre_optimale if objectif_mm > 0 else "attendre",
                "objectif_mm": objectif_mm,
                "type_arrosage": type_arrosage,
                "niveau_action": "a_faire" if objectif_mm > 0 else "surveiller",
                "risque_gazon": risque_gazon,
            },
            "niveau_action": "a_faire" if objectif_mm > 0 else "surveiller",
            "fenetre_optimale": fenetre_optimale if objectif_mm > 0 else "attendre",
            "risque_gazon": risque_gazon,
            "prochaine_reevaluation": prochaine_reevaluation,
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "watering_passages": watering_passages,
            "watering_pause_minutes": watering_pause_minutes,
            "watering_target_date": watering_target_date,
            "surface_sec": surface_sec,
            "pluie_probabilite_24h": pluie_probabilite_24h,
            "mm_detected_24h": mm_detected_24h,
            "sursemis_micro_apport_allowed": sursemis_allowed,
            "sursemis_block_reason": sursemis_block_reason,
            "sursemis_reason": sursemis_reason,
            "sursemis_seuil_declencheur": sursemis_thresholds,
            "fractionnement": {
                "enabled": False,
                "passages": watering_passages,
                "pause_minutes": watering_pause_minutes,
                "max_mm_per_passage": round(objectif_mm / watering_passages, 1) if objectif_mm > 0 else 0.0,
                "reason": "sursemis_micro_apport_0_5_mm" if objectif_mm > 0 else "sursemis_aucune_action",
            },
            **application_payload,
        }

    if not recommande:
        watering_blocked = (
            pluie_compensatrice
            or pluie_proche
            or humidite_haute
            or pluie_significative
            or block_reason_value in {"cooldown_24h", "sol_deja_humide"}
        )
        conseil_principal = f"Phase {phase_dominante}: n'arrose pas pour l'instant."
        action_recommandee = "Surveille les capteurs et l'évolution météo."
        action_a_eviter = "Éviter tout arrosage inutile."
        objectif_mm = 0.0
        type_arrosage = "bloque" if watering_blocked else "personnalise"
        arrosage_recommande = False
        arrosage_auto_autorise = False
        arrosage_conseille = "personnalise"
    elif phase_dominante == "Fertilisation":
        passages = _soil_fractionation_passages(
            phase_dominante,
            sous_phase,
            soil_style,
            objectif_mm,
            stress_level,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
        )
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = "Fertilisation active: arrose légèrement, de préférence le matin."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text} pour activer l'apport."
        action_a_eviter = "Tondre sur sol humide."
        type_arrosage = "auto"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "auto" if phase_dominante == "Normal" else "personnalise"
        watering_passages = passages
        watering_pause_minutes = _watering_pause_minutes(passages)
    elif phase_dominante == "Scarification":
        passages = _soil_fractionation_passages(
            phase_dominante,
            sous_phase,
            soil_style,
            objectif_mm,
            stress_level,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
        )
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = "Scarification: garde une humidité stable sans détremper."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
        action_a_eviter = "Saturer le sol."
        type_arrosage = "auto"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "personnalise"
        watering_passages = passages
        watering_pause_minutes = _watering_pause_minutes(passages)
    elif phase_dominante == "Agent Mouillant":
        passages = _soil_fractionation_passages(
            phase_dominante,
            sous_phase,
            soil_style,
            objectif_mm,
            stress_level,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
        )
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = "Agent mouillant: fais pénétrer l'eau plus en profondeur."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
        action_a_eviter = "Arroser trop vite."
        type_arrosage = "auto"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "personnalise"
        watering_passages = passages
        watering_pause_minutes = _watering_pause_minutes(passages)
    elif phase_dominante == "Biostimulant":
        passages = _soil_fractionation_passages(
            phase_dominante,
            sous_phase,
            soil_style,
            objectif_mm,
            stress_level,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
        )
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = "Biostimulant: garde un niveau hydrique modéré."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
        action_a_eviter = "Détremper le sol."
        type_arrosage = "auto"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "personnalise"
        watering_passages = passages
        watering_pause_minutes = _watering_pause_minutes(passages)
    else:
        passages = _soil_fractionation_passages(
            phase_dominante,
            sous_phase,
            soil_style,
            objectif_mm,
            stress_level,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
        )
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = f"Phase {phase_dominante}: arrose de façon maîtrisée {fenetre_texte}."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text} en tenant compte de l'humidité actuelle."
        action_a_eviter = "Arroser en pleine journée."
        type_arrosage = "auto" if auto_ok else "personnalise"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "auto" if phase_dominante == "Normal" else "personnalise"
        watering_passages = passages
        watering_pause_minutes = _watering_pause_minutes(passages)

    if phase_dominante == "Normal":
        if not recommande:
            if pluie_demain >= 2:
                conseil_principal = "N'arrose pas aujourd'hui: la pluie prévue couvre le besoin court terme."
                action_recommandee = "Laisse la pluie agir puis réévalue demain."
                action_a_eviter = "Cumuler pluie et arrosage."
            else:
                conseil_principal = "N'arrose pas pour le moment."
                action_recommandee = "Réévalue au prochain cycle météo."
                action_a_eviter = "Éviter tout arrosage inutile."
        else:
            if pluie_compensatrice:
                reduction_mm = round(objectif_mm * 0.4, 1)
                conseil_principal = "Réduis ou reporte l'arrosage: la pluie de demain peut compenser une grande partie du déficit."
                if reduction_mm >= 0.5:
                    action_recommandee = f"Réduis l'apport à {reduction_mm:.1f} mm maximum."
                else:
                    action_recommandee = _watering_needed_text()
                action_a_eviter = "Lancer un cycle complet avant la pluie."
            elif pluie_demain > 0 or pluie_j2 > 0 or pluie_3j > 0:
                reduction_mm = round(objectif_mm * 0.8, 1)
                conseil_principal = "Réduis l'arrosage: la pluie annoncée peut déjà compenser une partie du besoin."
                action_recommandee = f"Réduis l'apport à {reduction_mm:.1f} mm maximum."
                action_a_eviter = "Lancer un cycle complet sans tenir compte de la pluie annoncée."
            elif stress_thermique:
                passages = _soil_fractionation_passages(
                    phase_dominante,
                    sous_phase,
                    soil_style,
                    objectif_mm,
                    stress_level,
                    temperature=temperature,
                    humidite=humidite,
                    etp=etp,
                )
                style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
                conseil_principal = f"Arrose {fenetre_texte} en privilégiant la recharge de la réserve."
                action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
                action_a_eviter = "Arroser entre 11h et 18h."
            elif humidite_haute:
                conseil_principal = "Attends un léger ressuyage avant d'arroser."
                action_recommandee = "Reporte l'arrosage au prochain créneau sec."
                action_a_eviter = "Arroser immédiatement sur pelouse saturée."
            else:
                passages = _soil_fractionation_passages(
                    phase_dominante,
                    sous_phase,
                    soil_style,
                    objectif_mm,
                    stress_level,
                    temperature=temperature,
                    humidite=humidite,
                    etp=etp,
                )
                style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
                conseil_principal = f"Arrose {fenetre_texte}: recharge la réserve sans micro-apports."
                action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
                action_a_eviter = "Arroser en pleine journée ou multiplier les petits cycles."

    if objectif_mm > 0:
        watering_passages = _soil_fractionation_passages(
            phase_dominante,
            sous_phase,
            soil_style,
            objectif_mm,
            stress_level,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
        )
        watering_pause_minutes = _watering_pause_minutes(watering_passages)
    else:
        watering_passages = 1
        watering_pause_minutes = 0

    decision_resume = {
        "faire": arrosage_recommande,
        "action": "arrosage" if arrosage_recommande else "aucune_action",
        "moment": fenetre_optimale,
        "objectif_mm": objectif_mm,
        "type_arrosage": type_arrosage,
        "niveau_action": niveau_action,
        "risque_gazon": risque_gazon,
    }

    weekly_guardrail_min = float(water_bundle.get("weekly_guardrail_mm_min") or 20.0)
    weekly_guardrail_max = float(water_bundle.get("weekly_guardrail_mm_max") or 25.0)
    heat_stress_phase_value = water_bundle.get("heat_stress_phase")
    soil_profile_value = water_bundle.get("soil_profile")
    confidence_score_value = water_bundle.get("confidence_score")
    block_reason_value = water_bundle.get("block_reason")
    cooldown_24h_hours_value = water_bundle.get("cooldown_24h_hours")

    raison_parts = [
        f"Mode {phase_dominante} / {sous_phase} en cours ({phase_bundle['jours_restants']} jour(s) restants).",
        f"Bilan hydrique={bilan_hydrique_mm:.1f} mm, tendance 3j={bilan_hydrique_3j:.1f} mm, 7j={bilan_hydrique_7j:.1f} mm.",
        f"Pluie efficace={pluie_efficace:.1f} mm.",
        (
            "Fenêtre cible: matin prioritaire 04:00-08:00, acceptable jusqu'à 10:00, "
            "soir uniquement en rattrapage exceptionnel, journée interdite."
        ),
        (
            f"Déficit: brut={deficit_mm_brut:.1f} mm, ajusté={deficit_mm_ajuste:.1f} mm, "
            f"cible={mm_cible:.1f} mm, final={mm_final:.1f} mm."
        ),
        (
            f"Historique 7j: {water_bundle.get('recent_watering_count_7j', 0)} arrosage(s), "
            f"{water_bundle.get('recent_watering_mm_7j', 0.0):.1f} mm."
        ),
    ]
    if phase_dominante == "Normal":
        raison_parts.append(
            "Mode Normal: arrosage profond et rare, seuil utile minimal 10 mm, "
            f"garde-fou hebdomadaire dynamique {weekly_guardrail_min:.1f} à {weekly_guardrail_max:.1f} mm sur 7 jours glissants."
        )
    elif phase_dominante == "Sursemis":
        raison_parts.append("Sursemis: micro-apports légers et fréquents, jamais d'auto standard.")
    if heat_stress_level != "normal":
        raison_parts.append(f"Stress thermique={heat_stress_level}; matin renforcé, soirée plus restrictive.")
    if heat_stress_phase_value not in (None, "normal"):
        raison_parts.append(f"Phase canicule={heat_stress_phase_value}")
    if pluie_compensatrice or pluie_proche:
        raison_parts.append("pluie prévue suffisante: arrosage reporté ou bloqué.")
    if humidite_haute:
        raison_parts.append("humidité élevée: sol trop chargé pour un arrosage immédiat.")
    if pluie_significative:
        raison_parts.append("risque d'humidité élevé")
    if stress_thermique:
        raison_parts.append("stress thermique")
    if humidite_haute:
        raison_parts.append("humidité air élevée")
    if advanced_context.get("humidite_sol") is not None:
        raison_parts.append(f"humidite_sol={advanced_context['humidite_sol']}")
    if advanced_context.get("vent") is not None:
        raison_parts.append(f"vent={advanced_context['vent']}")
    if advanced_context.get("rosee") is not None and advanced_context.get("rosee") > 0:
        raison_parts.append("rosée présente")
    if advanced_context.get("hauteur_gazon") is not None:
        raison_parts.append(f"hauteur_gazon={advanced_context['hauteur_gazon']}")
    if advanced_context.get("retour_arrosage") is not None:
        raison_parts.append(f"retour_arrosage={advanced_context['retour_arrosage']}")
    if soil_profile_value is not None:
        raison_parts.append(
            "Sol="
            f"{soil_profile_value} (rétention={water_bundle.get('soil_retention_factor')}, "
            f"drainage={water_bundle.get('soil_drainage_factor')}, infiltration={water_bundle.get('soil_infiltration_factor')})."
        )
    if confidence_score_value is not None:
        raison_parts.append(
            f"Confiance={water_bundle.get('niveau_confiance')} ({confidence_score_value}/100)."
        )
    if block_reason_value == "cooldown_24h":
        raison_parts.append("Cooldown 24h: aucun arrosage normal dans les 24 dernières heures.")
        raison_parts.append("Motif exact: cooldown_24h.")
    elif block_reason_value == "sol_deja_humide":
        raison_parts.append("Sol déjà humide: bilan hydrique au-dessus du seuil de saturation.")
        raison_parts.append("Motif exact: sol_deja_humide.")
    elif block_reason_value:
        raison_parts.append(f"Motif exact: {block_reason_value}.")
    if cooldown_24h_hours_value is not None:
        raison_parts.append(f"Cooldown mesuré={float(cooldown_24h_hours_value):.1f} h.")
    raison_parts.append(tonte_reason)

    confidence_score = water_bundle.get("confidence_score")
    observability_payload = {
        "phase": phase_dominante,
        "sous_phase": sous_phase,
        "type_arrosage": type_arrosage,
        "deficit_brut_mm": round(deficit_mm_brut, 1),
        "deficit_mm_ajuste": round(deficit_mm_ajuste, 1),
        "mm_cible": round(mm_cible, 1),
        "mm_final": round(mm_final, 1),
        "mm_requested": round(mm_cible, 1),
        "mm_applied": round(mm_final, 1),
        "mm_detected": round(water_balance.get("arrosage_recent_jour", 0.0), 1),
        "heat_stress_level": heat_stress_level,
        "heat_stress_phase": heat_stress_phase,
        "confidence_level": niveau_confiance,
        "confidence_score": confidence_score,
        "block_reason": water_bundle.get("block_reason"),
        "cooldown_24h_hours": cooldown_24h_hours_value,
        "weekly_guardrail_mm_min": water_bundle.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": water_bundle.get("weekly_guardrail_mm_max"),
        "soil_profile": water_bundle.get("soil_profile"),
        "soil_retention_factor": water_bundle.get("soil_retention_factor"),
        "soil_drainage_factor": water_bundle.get("soil_drainage_factor"),
        "soil_infiltration_factor": water_bundle.get("soil_infiltration_factor"),
    }
    feedback_observation = context.memory.get("feedback_observation") if isinstance(context.memory, dict) else None
    if feedback_observation:
        observability_payload["feedback_observation"] = feedback_observation
    _LOGGER.debug("Gazon Intelligent V2 watering observability: %s", observability_payload)

    return {
        "objectif_mm": objectif_mm,
        "objectif_mm_brut": objectif_mm_brut,
        "deficit_brut_mm": deficit_mm_brut,
        "deficit_mm_brut": deficit_mm_brut,
        "deficit_mm_ajuste": deficit_mm_ajuste,
        "mm_cible": mm_cible,
        "mm_final_recommande": mm_final_recommande,
        "mm_final": mm_final,
        "mm_requested": water_bundle.get("mm_requested"),
        "mm_applied": water_bundle.get("mm_applied"),
        "mm_detected": water_bundle.get("mm_detected"),
        "conseil_principal": conseil_principal,
        "action_recommandee": action_recommandee,
        "action_a_eviter": action_a_eviter,
        "arrosage_recommande": arrosage_recommande,
        "arrosage_auto_autorise": arrosage_auto_autorise,
        "type_arrosage": type_arrosage,
        "arrosage_conseille": arrosage_conseille,
        "fractionnement": fractionnement,
        "niveau_confiance": niveau_confiance,
        "confidence_score": water_bundle.get("confidence_score"),
        "confidence_reasons": water_bundle.get("confidence_reasons"),
        "heat_stress_level": heat_stress_level,
        "heat_stress_phase": water_bundle.get("heat_stress_phase"),
        "decision_resume": decision_resume,
        "block_reason": water_bundle.get("block_reason"),
        "raison_decision": " ".join(raison_parts),
        "niveau_action": niveau_action,
        "fenetre_optimale": fenetre_optimale,
        "risque_gazon": risque_gazon,
        "prochaine_reevaluation": prochaine_reevaluation,
        "tonte_autorisee": mowing_bundle["tonte_autorisee"],
        "tonte_statut": mowing_bundle["tonte_statut"],
        "watering_passages": watering_passages,
        "watering_pause_minutes": watering_pause_minutes,
        "watering_target_date": watering_target_date,
        "weekly_guardrail_mm_min": water_bundle.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": water_bundle.get("weekly_guardrail_mm_max"),
        "weekly_guardrail_reason": water_bundle.get("weekly_guardrail_reason"),
        "soil_profile": water_bundle.get("soil_profile"),
        "soil_retention_factor": water_bundle.get("soil_retention_factor"),
        "soil_drainage_factor": water_bundle.get("soil_drainage_factor"),
        "soil_infiltration_factor": water_bundle.get("soil_infiltration_factor"),
        "soil_need_factor": water_bundle.get("soil_need_factor"),
        "watering_window_start_minute": watering_window_start_minute,
        "watering_window_end_minute": watering_window_end_minute,
        "watering_window_optimal_start_minute": watering_window_optimal_start_minute,
        "watering_window_optimal_end_minute": watering_window_optimal_end_minute,
        "watering_window_acceptable_end_minute": watering_window_acceptable_end_minute,
        **application_payload,
    }
