from __future__ import annotations

"""Orchestrateur du moteur de décision.

Ce module garde l'API historique utilisée par le reste de l'intégration,
mais délègue la logique métier aux modules spécialisés:
- decision_phase.py
- decision_watering.py
- decision_risk.py
- decision_mowing.py
"""

from datetime import date, datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DEFAULT_AUTO_IRRIGATION_ENABLED
from .decision_models import DecisionContext, DecisionResult
from .decision_mowing import build_mowing_bundle
from .decision_phase import build_phase_bundle
from .decision_risk import build_risk_bundle
from .decision_watering import build_water_bundle, build_watering_bundle
from .guidance import compute_action_guidance as guidance_compute_action_guidance
from .guidance import compute_objectif_mm as guidance_compute_objectif_mm
from .memory import compute_memory as memory_compute_memory
from .phases import (
    compute_dominant_phase as phases_compute_dominant_phase,
    compute_phase_active as phases_compute_phase_active,
    compute_subphase as phases_compute_subphase,
)
from .water import (
    compute_advanced_context as water_compute_advanced_context,
    compute_etp as water_compute_etp,
    compute_recent_watering_mm as water_compute_recent_watering_mm,
    compute_water_balance as water_compute_water_balance,
)


def _display_date_from_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def compute_phase_active(*args, **kwargs):
    return phases_compute_phase_active(*args, **kwargs)


def compute_dominant_phase(*args, **kwargs):
    return phases_compute_dominant_phase(*args, **kwargs)


def compute_subphase(*args, **kwargs):
    today = kwargs.get("today")
    now = kwargs.get("now")
    if today is not None and now is None:
        reference_now = dt_util.now()
        kwargs["now"] = datetime.combine(today, datetime.min.time(), tzinfo=reference_now.tzinfo)
    return phases_compute_subphase(*args, **kwargs)


def compute_recent_watering_mm(*args, **kwargs):
    return water_compute_recent_watering_mm(*args, **kwargs)


def compute_advanced_context(*args, **kwargs):
    return water_compute_advanced_context(*args, **kwargs)


def compute_etp(*args, **kwargs):
    return water_compute_etp(*args, **kwargs)


def compute_water_balance(*args, **kwargs):
    return water_compute_water_balance(*args, **kwargs)


def compute_objectif_mm(*args, **kwargs):
    return guidance_compute_objectif_mm(*args, **kwargs)


def compute_action_guidance(*args, **kwargs):
    return guidance_compute_action_guidance(*args, **kwargs)


def compute_memory(*args, **kwargs):
    return memory_compute_memory(*args, **kwargs)


def _build_runtime_bundles(
    context: DecisionContext,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    phase_bundle = build_phase_bundle(context)
    water_bundle = build_water_bundle(context, phase_bundle)
    risk_bundle = build_risk_bundle(context, phase_bundle, water_bundle)
    mowing_bundle = build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
    watering_bundle = build_watering_bundle(context, phase_bundle, water_bundle, risk_bundle, mowing_bundle)
    return phase_bundle, water_bundle, risk_bundle, mowing_bundle, watering_bundle


def _build_legacy_context(
    *,
    history: list[dict[str, Any]],
    today: date | None,
    hour_of_day: int | None,
    temperature: float | None,
    pluie_24h: float | None,
    pluie_demain: float | None,
    pluie_j2: float | None,
    pluie_3j: float | None,
    pluie_probabilite_max_3j: float | None,
    humidite: float | None,
    hauteur_min_tondeuse_cm: float | None,
    hauteur_max_tondeuse_cm: float | None,
    memory: dict[str, Any] | None,
) -> DecisionContext:
    return DecisionContext(
        history=[item for item in history if isinstance(item, dict)],
        today=today or dt_util.now().date(),
        hour_of_day=hour_of_day,
        temperature=temperature,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
        humidite=humidite,
        hauteur_min_tondeuse_cm=hauteur_min_tondeuse_cm,
        hauteur_max_tondeuse_cm=hauteur_max_tondeuse_cm,
        weather_profile={},
        config={},
        memory=memory,
    )


def _build_legacy_runtime_bundles(
    *,
    context: DecisionContext,
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    advanced_context: dict[str, Any] | None,
    etp: float | None,
    objectif_mm: float,
    jours_restants: int,
    score_hydrique: int,
    score_stress: int,
    score_tonte: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    advanced_context = advanced_context or {}
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
        "advanced_context": advanced_context,
        "water_balance": water_balance,
        "objectif_mm": objectif_mm,
        "target_cycle_mm": objectif_mm,
        "objective_mm_source": "legacy",
    }
    risk_bundle = {
        "scores": {
            "score_hydrique": score_hydrique,
            "score_stress": score_stress,
            "score_tonte": score_tonte,
        },
        "niveau_action": advanced_context.get("niveau_action", "a_faire"),
        "fenetre_optimale": advanced_context.get("fenetre_optimale", "maintenant"),
        "risque_gazon": advanced_context.get("risque_gazon", "modere"),
        "prochaine_reevaluation": advanced_context.get("prochaine_reevaluation", "dans 24 h"),
        "urgence": advanced_context.get("urgence", "moyenne"),
        "watering_window_start_minute": advanced_context.get("watering_window_start_minute"),
        "watering_window_end_minute": advanced_context.get("watering_window_end_minute"),
        "watering_window_optimal_start_minute": advanced_context.get("watering_window_optimal_start_minute"),
        "watering_window_optimal_end_minute": advanced_context.get("watering_window_optimal_end_minute"),
        "watering_window_acceptable_end_minute": advanced_context.get("watering_window_acceptable_end_minute"),
        "watering_evening_start_minute": advanced_context.get("watering_evening_start_minute"),
        "watering_evening_end_minute": advanced_context.get("watering_evening_end_minute"),
        "watering_window_profile": advanced_context.get("watering_window_profile"),
        "watering_evening_allowed": advanced_context.get("watering_evening_allowed"),
        "heat_stress_level": advanced_context.get("heat_stress_level"),
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
    return phase_bundle, water_bundle, risk_bundle, mowing_bundle, watering_bundle


def _build_decision_extra(
    *,
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
    mowing_bundle: dict[str, Any],
    watering_bundle: dict[str, Any],
) -> dict[str, Any]:
    watering_target_date = watering_bundle.get("watering_target_date")
    next_action_display = _display_date_from_iso(str(watering_target_date) if watering_target_date else None)
    reason_blocage_tonte = (
        (mowing_bundle.get("tonte_reason") or watering_bundle.get("tonte_reason"))
        if not watering_bundle.get("tonte_autorisee", mowing_bundle.get("tonte_autorisee", True))
        else None
    )
    advanced_context = water_bundle.get("advanced_context") or {}
    water_balance = water_bundle.get("water_balance") or {}
    dose_policy = water_bundle.get("dose_policy") or {}
    mower_context = {
        key: value
        for key, value in mowing_bundle.items()
        if (key.startswith("tondeuse_") or key.startswith("mower_")) and value is not None
    }

    payload = {
        "mode": phase_bundle.get("phase_dominante"),
        "phase_active": phase_bundle.get("phase_dominante"),
        "type_sol": context.type_sol,
        "temperature": context.temperature,
        "forecast_temperature_today": context.forecast_temperature_today,
        "temperature_source": context.temperature_source,
        "temperature_reference_hydrique": context.temperature_reference_hydrique,
        "pluie_demain": context.pluie_demain,
        "date_action": phase_bundle.get("date_action"),
        "date_fin": phase_bundle.get("date_fin"),
        "phase_age_days": phase_bundle.get("phase_age_days"),
        "jours_restants": phase_bundle.get("jours_restants"),
        "etp": water_bundle.get("etp"),
        "et0_mm": water_bundle.get("et0_mm"),
        "et0_source": context.et0_source,
        "kc_gazon": water_bundle.get("kc_gazon"),
        "etc_mm": water_bundle.get("etc_mm"),
        "humidite_sol": advanced_context.get("humidite_sol"),
        "vent": advanced_context.get("vent"),
        "rosee": advanced_context.get("rosee"),
        "hauteur_gazon": advanced_context.get("hauteur_gazon"),
        "retour_arrosage": advanced_context.get("retour_arrosage"),
        "pluie_source": advanced_context.get("pluie_source"),
        "water_balance": water_balance,
        "deficit_jour": water_balance.get("deficit_jour"),
        "deficit_3j": water_balance.get("deficit_3j"),
        "deficit_7j": water_balance.get("deficit_7j"),
        "reserve_hydrique_sol_mm": water_balance.get("reserve_hydrique_sol_mm"),
        "bilan_hydrique_precedent_mm": water_balance.get("bilan_hydrique_precedent_mm"),
        "soil_balance": water_balance.get("soil_balance"),
        "pluie_efficace": water_balance.get("pluie_efficace"),
        "arrosage_recent": water_balance.get("arrosage_recent"),
        "arrosage_recent_jour": water_balance.get("arrosage_recent_jour"),
        "arrosage_recent_3j": water_balance.get("arrosage_recent_3j"),
        "arrosage_recent_7j": water_balance.get("arrosage_recent_7j"),
        "bilan_hydrique_mm": water_balance.get("bilan_hydrique_mm"),
        "bilan_hydrique_3j": water_balance.get("bilan_hydrique_3j"),
        "bilan_hydrique_7j": water_balance.get("bilan_hydrique_7j"),
        "reserve_utile_mm": water_balance.get("reserve_utile_mm"),
        "reserve_stock_mm": water_balance.get("reserve_stock_mm"),
        "reserve_stock_max_mm": water_balance.get("reserve_stock_max_mm"),
        "reserve_surplus_mm": water_balance.get("reserve_surplus_mm"),
        "reserve_actuelle_mm": water_balance.get("reserve_actuelle_mm"),
        "reserve_fill_ratio": water_balance.get("reserve_fill_ratio"),
        "reserve_available_ratio": water_balance.get("reserve_available_ratio"),
        "mad_ratio": water_balance.get("mad_ratio"),
        "mad_ratio_base": water_balance.get("mad_ratio_base"),
        "mad_ratio_effective": water_balance.get("mad_ratio_effective"),
        "mad_band": water_balance.get("mad_band"),
        "mad_reason": water_balance.get("mad_reason"),
        "mad_policy_enabled": water_balance.get("mad_policy_enabled"),
        "mad_policy_source": water_balance.get("mad_policy_source"),
        "mad_policy_inputs": water_balance.get("mad_policy_inputs"),
        "mad_policy_candidate_band": water_balance.get("mad_policy_candidate_band"),
        "mad_policy_candidate_ratio": water_balance.get("mad_policy_candidate_ratio"),
        "mad_hysteresis_state": water_balance.get("mad_hysteresis_state"),
        "mad_threshold_mm": water_balance.get("mad_threshold_mm"),
        "dose_policy": dose_policy or None,
        "dose_enabled": water_bundle.get("dose_enabled"),
        "dose_policy_enabled": dose_policy.get("enabled") if isinstance(dose_policy, dict) else None,
        "dose_policy_source": dose_policy.get("source") if isinstance(dose_policy, dict) else None,
        "dose_band": dose_policy.get("dose_band") if isinstance(dose_policy, dict) else None,
        "dose_reason": dose_policy.get("dose_reason") if isinstance(dose_policy, dict) else None,
        "dose_mm_base": dose_policy.get("dose_mm_base") if isinstance(dose_policy, dict) else None,
        "dose_mm_effective": dose_policy.get("dose_mm_effective") if isinstance(dose_policy, dict) else None,
        "dose_mm_target": dose_policy.get("dose_mm_target") if isinstance(dose_policy, dict) else None,
        "dose_mm_min": dose_policy.get("dose_mm_min") if isinstance(dose_policy, dict) else None,
        "dose_mm_max": dose_policy.get("dose_mm_max") if isinstance(dose_policy, dict) else None,
        "dose_candidate_band": dose_policy.get("candidate_band") if isinstance(dose_policy, dict) else None,
        "dose_candidate_mm": dose_policy.get("candidate_mm") if isinstance(dose_policy, dict) else None,
        "dose_candidate_reason": dose_policy.get("candidate_reason") if isinstance(dose_policy, dict) else None,
        "dose_policy_inputs": dose_policy.get("dose_inputs") if isinstance(dose_policy, dict) else None,
        "depletion_allowed_mm": water_balance.get("depletion_allowed_mm"),
        "reserve_minimale_mm": water_balance.get("reserve_minimale_mm"),
        "depletion_mm": water_balance.get("depletion_mm"),
        "depletion_ratio": water_balance.get("depletion_ratio"),
        # Réserve AFFICHÉE (descente progressive selon le soleil) — affichage seul.
        "et_elapsed_fraction": water_balance.get("et_elapsed_fraction"),
        "reserve_actuelle_affichee_mm": water_balance.get("reserve_actuelle_affichee_mm"),
        "reserve_stock_affichee_mm": water_balance.get("reserve_stock_affichee_mm"),
        "depletion_affichee_mm": water_balance.get("depletion_affichee_mm"),
        "depletion_ratio_affiche": water_balance.get("depletion_ratio_affiche"),
        "evening_cooling_likely": water_bundle.get("evening_cooling_likely"),
        "evening_cooling_debug": water_bundle.get("evening_cooling_debug"),
        "fenetre_optimale_profil": water_bundle.get("fenetre_optimale_profil"),
        "objectif_mm": watering_bundle.get("objectif_mm"),
        "target_cycle_mm": water_bundle.get("target_cycle_mm"),
        "objective_mm_source": water_bundle.get("objective_mm_source"),
        "objectif_mm_brut": water_bundle.get("objectif_mm_brut"),
        "objectif_mm_executable": watering_bundle.get("objectif_mm"),
        "deficit_brut_mm": watering_bundle.get("deficit_brut_mm"),
        "deficit_mm_ajuste": watering_bundle.get("deficit_mm_ajuste"),
        "mm_cible": watering_bundle.get("mm_cible"),
        "mm_final_recommande": watering_bundle.get("mm_final_recommande"),
        "mm_final": watering_bundle.get("mm_final"),
        "watering_strategy": watering_bundle.get("watering_strategy"),
        "objective_scope": watering_bundle.get("objective_scope"),
        "watering_stage": watering_bundle.get("watering_stage"),
        "surface_cycle_mm": watering_bundle.get("surface_cycle_mm"),
        "daily_cycles_target": watering_bundle.get("daily_cycles_target"),
        "cycle_spacing_minutes": watering_bundle.get("cycle_spacing_minutes"),
        "surface_moisture_target": watering_bundle.get("surface_moisture_target"),
        "surface_dryness_risk": watering_bundle.get("surface_dryness_risk"),
        "runoff_risk": watering_bundle.get("runoff_risk"),
        "surface_saturation_level": watering_bundle.get("surface_saturation_level"),
        "surface_saturation_limit": watering_bundle.get("surface_saturation_limit"),
        "seeding_transition_ready": watering_bundle.get("seeding_transition_ready"),
        "seeding_block_reason": watering_bundle.get("seeding_block_reason"),
        "fractionnement": watering_bundle.get("fractionnement"),
        "niveau_confiance": watering_bundle.get("niveau_confiance"),
        "confidence_score": watering_bundle.get("confidence_score"),
        "confidence_reasons": watering_bundle.get("confidence_reasons"),
        "block_reason": watering_bundle.get("block_reason"),
        "cooldown_24h_hours": watering_bundle.get("cooldown_24h_hours"),
        "mm_requested": watering_bundle.get("mm_requested"),
        "mm_applied": watering_bundle.get("mm_applied"),
        "mm_detected": watering_bundle.get("mm_detected"),
        "mm_detected_24h": watering_bundle.get("mm_detected_24h"),
        "pluie_probabilite_24h": watering_bundle.get("pluie_probabilite_24h"),
        "surface_sec": watering_bundle.get("surface_sec"),
        "use_depletion_logic": water_bundle.get("use_depletion_logic"),
        "mm_cible_depletion": water_bundle.get("mm_cible_depletion"),
        "mad_policy": water_bundle.get("mad_policy"),
        "sursemis_micro_apport_allowed": watering_bundle.get("sursemis_micro_apport_allowed"),
        "sursemis_block_reason": watering_bundle.get("sursemis_block_reason"),
        "sursemis_reason": watering_bundle.get("sursemis_reason"),
        "sursemis_seuil_declencheur": watering_bundle.get("sursemis_seuil_declencheur"),
        "watering_target_date": watering_target_date,
        "next_action_date": watering_target_date,
        "next_action_display": next_action_display,
        "raison_blocage_tonte": reason_blocage_tonte,
        "raison_blocage_code": mowing_bundle.get("raison_blocage_code"),
        "tonte_reason": reason_blocage_tonte,
        "next_mowing_date": mowing_bundle.get("next_mowing_date"),
        "next_mowing_display": mowing_bundle.get("next_mowing_display"),
        "mowing_frequency_target_per_week": mowing_bundle.get("mowing_frequency_target_per_week"),
        "mowing_frequency_label": mowing_bundle.get("mowing_frequency_label"),
        "mowing_window_state": mowing_bundle.get("mowing_window_state"),
        "mowing_window_label": mowing_bundle.get("mowing_window_label"),
        "mowing_window_reason": mowing_bundle.get("mowing_window_reason"),
        "mowing_daily_session_limit": mowing_bundle.get("mowing_daily_session_limit"),
        "mowing_daily_session_policy": mowing_bundle.get("mowing_daily_session_policy"),
        "derniere_application": watering_bundle.get("derniere_application"),
        "application_type": watering_bundle.get("application_type"),
        "application_requires_watering_after": watering_bundle.get("application_requires_watering_after"),
        "application_post_watering_mm": watering_bundle.get("application_post_watering_mm"),
        "application_irrigation_block_hours": watering_bundle.get("application_irrigation_block_hours"),
        "application_irrigation_delay_minutes": watering_bundle.get("application_irrigation_delay_minutes"),
        "application_irrigation_mode": watering_bundle.get("application_irrigation_mode"),
        "application_label_notes": watering_bundle.get("application_label_notes"),
        "application_post_watering_status": watering_bundle.get("application_post_watering_status"),
        "auto_irrigation_enabled": bool(
            context.memory.get("auto_irrigation_enabled", DEFAULT_AUTO_IRRIGATION_ENABLED)
            if context.memory
            else DEFAULT_AUTO_IRRIGATION_ENABLED
        ),
        "application_block_until": watering_bundle.get("application_block_until"),
        "application_block_active": watering_bundle.get("application_block_active"),
        "application_block_remaining_minutes": watering_bundle.get("application_block_remaining_minutes"),
        "application_post_watering_pending": watering_bundle.get("application_post_watering_pending"),
        "application_post_watering_ready_at": watering_bundle.get("application_post_watering_ready_at"),
        "application_post_watering_delay_remaining_minutes": watering_bundle.get(
            "application_post_watering_delay_remaining_minutes"
        ),
        "application_post_watering_ready": watering_bundle.get("application_post_watering_ready"),
        "application_post_watering_remaining_mm": watering_bundle.get("application_post_watering_remaining_mm"),
        "watering_blocked_by_mower": watering_bundle.get("watering_blocked_by_mower"),
        "watering_block_reason_code": watering_bundle.get("watering_block_reason_code"),
        "watering_block_reason_label": watering_bundle.get("watering_block_reason_label"),
        "mowing_blocked_by_watering": mowing_bundle.get("mowing_blocked_by_watering"),
        "mowing_blocked": mowing_bundle.get("mowing_blocked"),
        "mowing_block_reason_code": mowing_bundle.get("mowing_block_reason_code"),
        "mowing_block_reason_label": mowing_bundle.get("mowing_block_reason_label"),
        "mowing_block_reason": mowing_bundle.get("mowing_block_reason"),
        "mowing_cooldown_remaining_minutes": mowing_bundle.get("mowing_cooldown_remaining_minutes"),
        "mowing_post_application_active": mowing_bundle.get("mowing_post_application_active"),
        "mowing_is_overdue": mowing_bundle.get("mowing_is_overdue"),
        "mowing_overdue_days": mowing_bundle.get("mowing_overdue_days"),
        "mowing_overdue_factor": mowing_bundle.get("mowing_overdue_factor"),
        "gazon_hauteur_estimee_cm": mowing_bundle.get("gazon_hauteur_estimee_cm"),
        "mowing_cooldown_after_watering_minutes": context.runtime_context.get(
            "mowing_cooldown_after_watering_minutes"
        )
        if isinstance(context.runtime_context, dict)
        else None,
        "heat_stress_level": risk_bundle.get("heat_stress_level") or watering_bundle.get("heat_stress_level"),
        "heat_stress_phase": watering_bundle.get("heat_stress_phase"),
        "score_hydrique": risk_bundle.get("scores", {}).get("score_hydrique"),
        "score_stress": risk_bundle.get("scores", {}).get("score_stress"),
        "score_tonte": risk_bundle.get("scores", {}).get("score_tonte"),
        "tonte_autorisee": bool(watering_bundle.get("tonte_autorisee", True)) and bool(mowing_bundle.get("tonte_autorisee", True)),
        "gazon_permet_tonte": mowing_bundle.get("gazon_permet_tonte"),
        "machine_permet_tonte": mowing_bundle.get("machine_permet_tonte"),
        "action_possible": mowing_bundle.get("action_possible"),
        "hauteur_tonte_recommandee_cm": watering_bundle.get(
            "hauteur_tonte_recommandee_cm",
            mowing_bundle.get("hauteur_tonte_recommandee_cm"),
        ),
        "hauteur_tonte_min_cm": watering_bundle.get("hauteur_tonte_min_cm", mowing_bundle.get("hauteur_tonte_min_cm")),
        "hauteur_tonte_max_cm": watering_bundle.get("hauteur_tonte_max_cm", mowing_bundle.get("hauteur_tonte_max_cm")),
        "tonte_statut": watering_bundle.get("tonte_statut", mowing_bundle.get("tonte_statut")),
        "arrosage_auto_autorise": watering_bundle.get("arrosage_auto_autorise"),
        "arrosage_recommande": watering_bundle.get("arrosage_recommande"),
        "watering_cause": watering_bundle.get("watering_cause"),
        "type_arrosage": watering_bundle.get("type_arrosage"),
        "arrosage_conseille": watering_bundle.get("arrosage_conseille"),
        "irrigation_need_mm": watering_bundle.get("irrigation_need_mm"),
        "irrigation_agronomic_recommendation": watering_bundle.get("irrigation_agronomic_recommendation"),
        "irrigation_blocked": watering_bundle.get("irrigation_blocked"),
        "irrigation_execution_allowed": watering_bundle.get("irrigation_execution_allowed"),
        # LOT B — urgence hydrique malgré blocage
        "irrigation_blocked_but_critical": watering_bundle.get("irrigation_blocked_but_critical"),
        "critical_deficit_mm": watering_bundle.get("critical_deficit_mm"),
        "critical_irrigation_reason": watering_bundle.get("critical_irrigation_reason"),
        "raison_decision": watering_bundle.get("raison_decision"),
        "conseil_principal": watering_bundle.get("conseil_principal"),
        "action_recommandee": watering_bundle.get("action_recommandee"),
        "action_a_eviter": watering_bundle.get("action_a_eviter"),
        "niveau_action": watering_bundle.get("niveau_action", risk_bundle.get("niveau_action")),
        "fenetre_optimale": watering_bundle.get("fenetre_optimale", risk_bundle.get("fenetre_optimale")),
        "risque_gazon": watering_bundle.get("risque_gazon", risk_bundle.get("risque_gazon")),
        "urgence": watering_bundle.get("urgence", risk_bundle.get("urgence")),
        "prochaine_reevaluation": watering_bundle.get("prochaine_reevaluation", risk_bundle.get("prochaine_reevaluation")),
        "decision_resume": watering_bundle.get("decision_resume"),
        "weekly_guardrail_mm_min": watering_bundle.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": watering_bundle.get("weekly_guardrail_mm_max"),
        "weekly_guardrail_reason": watering_bundle.get("weekly_guardrail_reason"),
        "season_label": watering_bundle.get("season_label"),
        "season_phase": watering_bundle.get("season_phase"),
        "month_profile": watering_bundle.get("month_profile"),
        "watering_bias": watering_bundle.get("watering_bias"),
        "mowing_bias": watering_bundle.get("mowing_bias"),
        "intervention_bias": watering_bundle.get("intervention_bias"),
        "risk_bias": watering_bundle.get("risk_bias"),
        "soil_profile": watering_bundle.get("soil_profile"),
        "soil_retention_factor": watering_bundle.get("soil_retention_factor"),
        "soil_drainage_factor": watering_bundle.get("soil_drainage_factor"),
        "soil_infiltration_factor": watering_bundle.get("soil_infiltration_factor"),
        "soil_need_factor": watering_bundle.get("soil_need_factor"),
        "watering_window_start_minute": risk_bundle.get("watering_window_start_minute"),
        "watering_window_end_minute": risk_bundle.get("watering_window_end_minute"),
        "watering_window_optimal_start_minute": risk_bundle.get("watering_window_optimal_start_minute"),
        "watering_window_optimal_end_minute": risk_bundle.get("watering_window_optimal_end_minute"),
        "watering_window_acceptable_end_minute": risk_bundle.get("watering_window_acceptable_end_minute"),
        "watering_evening_start_minute": risk_bundle.get("watering_evening_start_minute"),
        "watering_evening_end_minute": risk_bundle.get("watering_evening_end_minute"),
        "watering_window_profile": risk_bundle.get("watering_window_profile"),
        "watering_evening_allowed": risk_bundle.get("watering_evening_allowed"),
    }
    payload.update(mower_context)
    return payload


def _build_decision_result_from_bundles(
    *,
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
    mowing_bundle: dict[str, Any],
    watering_bundle: dict[str, Any],
    ) -> DecisionResult:
    return DecisionResult(
        phase_dominante=phase_bundle["phase_dominante"],
        sous_phase=phase_bundle["sous_phase"],
        action_recommandee=watering_bundle["action_recommandee"],
        action_a_eviter=watering_bundle["action_a_eviter"],
        niveau_action=watering_bundle.get("niveau_action", risk_bundle["niveau_action"]),
        fenetre_optimale=watering_bundle.get("fenetre_optimale", risk_bundle["fenetre_optimale"]),
        risque_gazon=watering_bundle.get("risque_gazon", risk_bundle["risque_gazon"]),
        objectif_arrosage=watering_bundle["objectif_mm"],
        tonte_autorisee=bool(watering_bundle.get("tonte_autorisee", True)) and bool(mowing_bundle.get("tonte_autorisee", True)),
        hauteur_tonte_recommandee_cm=watering_bundle.get(
            "hauteur_tonte_recommandee_cm",
            mowing_bundle.get("hauteur_tonte_recommandee_cm"),
        ),
        hauteur_tonte_min_cm=watering_bundle.get("hauteur_tonte_min_cm", mowing_bundle.get("hauteur_tonte_min_cm")),
        hauteur_tonte_max_cm=watering_bundle.get("hauteur_tonte_max_cm", mowing_bundle.get("hauteur_tonte_max_cm")),
        conseil_principal=watering_bundle["conseil_principal"],
        tonte_statut=watering_bundle.get("tonte_statut", mowing_bundle.get("tonte_statut", "autorisee")),
        arrosage_recommande=watering_bundle["arrosage_recommande"],
        arrosage_auto_autorise=watering_bundle["arrosage_auto_autorise"],
        watering_cause=watering_bundle.get("watering_cause", "hydrique"),
        type_arrosage=watering_bundle["type_arrosage"],
        arrosage_conseille=watering_bundle["arrosage_conseille"],
        deficit_brut_mm=watering_bundle.get("deficit_brut_mm"),
        deficit_mm_ajuste=watering_bundle.get("deficit_mm_ajuste", watering_bundle["objectif_mm"]),
        mm_cible=watering_bundle.get("mm_cible"),
        mm_final_recommande=watering_bundle.get("mm_final_recommande"),
        mm_final=watering_bundle.get("mm_final", watering_bundle["objectif_mm"]),
        watering_passages=watering_bundle["watering_passages"],
        watering_pause_minutes=watering_bundle["watering_pause_minutes"],
        watering_strategy=watering_bundle.get("watering_strategy"),
        objective_scope=watering_bundle.get("objective_scope"),
        watering_stage=watering_bundle.get("watering_stage"),
        surface_cycle_mm=watering_bundle.get("surface_cycle_mm"),
        daily_cycles_target=watering_bundle.get("daily_cycles_target"),
        cycle_spacing_minutes=watering_bundle.get("cycle_spacing_minutes"),
        surface_moisture_target=watering_bundle.get("surface_moisture_target"),
        surface_dryness_risk=watering_bundle.get("surface_dryness_risk"),
        runoff_risk=watering_bundle.get("runoff_risk"),
        surface_saturation_level=watering_bundle.get("surface_saturation_level"),
        surface_saturation_limit=watering_bundle.get("surface_saturation_limit"),
        seeding_transition_ready=watering_bundle.get("seeding_transition_ready"),
        seeding_block_reason=watering_bundle.get("seeding_block_reason"),
        fractionnement=watering_bundle.get("fractionnement"),
        niveau_confiance=watering_bundle.get("niveau_confiance"),
        heat_stress_level=risk_bundle.get("heat_stress_level") or watering_bundle.get("heat_stress_level"),
        phase_dominante_source=phase_bundle["phase_dominante_source"],
        sous_phase_detail=phase_bundle["sous_phase_detail"],
        sous_phase_age_days=phase_bundle["sous_phase_age_days"],
        sous_phase_progression=phase_bundle["sous_phase_progression"],
        prochaine_reevaluation=watering_bundle.get("prochaine_reevaluation", risk_bundle["prochaine_reevaluation"]),
        urgence=watering_bundle.get("urgence", risk_bundle["urgence"]),
        raison_decision=watering_bundle["raison_decision"],
        score_hydrique=risk_bundle["scores"]["score_hydrique"],
        score_stress=risk_bundle["scores"]["score_stress"],
        score_tonte=risk_bundle["scores"]["score_tonte"],
        decision_resume=watering_bundle["decision_resume"],
        advanced_context=water_bundle.get("advanced_context"),
        water_balance=water_bundle.get("water_balance"),
        phase_context=phase_bundle,
        extra=_build_decision_extra(
            context=context,
            phase_bundle=phase_bundle,
            water_bundle=water_bundle,
            risk_bundle=risk_bundle,
            mowing_bundle=mowing_bundle,
            watering_bundle=watering_bundle,
        ),
    )


def _build_decision_result(
    *,
    context: DecisionContext,
    runtime_bundles: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]] | None = None,
) -> DecisionResult:
    phase_bundle, water_bundle, risk_bundle, mowing_bundle, watering_bundle = runtime_bundles or _build_runtime_bundles(context)
    return _build_decision_result_from_bundles(
        context=context,
        phase_bundle=phase_bundle,
        water_bundle=water_bundle,
        risk_bundle=risk_bundle,
        mowing_bundle=mowing_bundle,
        watering_bundle=watering_bundle,
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
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
) -> DecisionResult:
    """Façade legacy: adapte des calculs déjà préparés vers le résultat canonique."""
    context = _build_legacy_context(
        history=history,
        today=today,
        hour_of_day=hour_of_day,
        temperature=temperature,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
        humidite=humidite,
        hauteur_min_tondeuse_cm=hauteur_min_tondeuse_cm,
        hauteur_max_tondeuse_cm=hauteur_max_tondeuse_cm,
        memory=memory,
    )
    runtime_bundles = _build_legacy_runtime_bundles(
        context=context,
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        water_balance=water_balance,
        advanced_context=advanced_context,
        etp=etp,
        objectif_mm=objectif_mm,
        jours_restants=jours_restants,
        score_hydrique=score_hydrique,
        score_stress=score_stress,
        score_tonte=score_tonte,
    )
    return _build_decision_result(context=context, runtime_bundles=runtime_bundles)

def build_decision_snapshot(
    history: list[dict[str, Any]],
    today: date | None = None,
    hour_of_day: int | None = None,
    temperature: float | None = None,
    forecast_temperature_today: float | None = None,
    temperature_source: str | None = None,
    temperature_reference_hydrique: float | None = None,
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
    sun_context: dict[str, Any] | None = None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
    et0_source: str | None = None,
) -> dict[str, Any]:
    """Construit le snapshot historique complet utilisé par les entités HA."""
    context = DecisionContext.from_legacy_args(
        history=history,
        today=today,
        hour_of_day=hour_of_day,
        temperature=temperature,
        forecast_temperature_today=forecast_temperature_today,
        temperature_source=temperature_source,
        temperature_reference_hydrique=temperature_reference_hydrique,
        et0_source=et0_source,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
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
        sun_context=sun_context,
    )
    return build_decision_result(context).to_snapshot()


def build_decision_result(context: DecisionContext) -> DecisionResult:
    """Voie canonique de construction du résultat de décision."""
    return _build_decision_result(context=context)
