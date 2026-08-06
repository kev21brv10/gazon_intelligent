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
    DEFAULT_EVENING_COOLING_ENABLED,
    OBJECTIVE_SCOPE_GLOBAL_SURFACE,
    OBJECTIVE_SCOPE_SURFACE_CYCLE,
    WATERING_STAGE_LEVEE,
    WATERING_STAGE_NORMAL,
    WATERING_STRATEGY_ADULT_DEEP,
    WATERING_STRATEGY_SEMIS_FREQUENT,
)
from .decision_models import DecisionContext, normalize_watering_contract
from .decision_risk import compute_fungal_risk
from .guidance import (
    _confidence_assessment,
    _reference_hydric_balance_mm,
    compute_watering_profile,
    is_fertilization_window_open,
)
from .memory import compute_application_state
from .scores import classify_stress_level
from .water import (
    compute_advanced_context,
    compute_etp,
    compute_water_balance,
    estimate_days_until_watering,
)
from .watering_policy import get_watering_policy

_LOGGER = logging.getLogger(__name__)
# Arrosage post-application (incorporation du produit) : le but est d'incorporer, pas de combler
# un déficit hydrique. L'agent mouillant réduit lui-même le ruissellement, donc le fractionnement
# anti-ruissellement agressif (jusqu'à 3 passages, pause 25 min) est inadapté ici. On plafonne à
# 2 passages avec une pause courte de 5 min — d'autant que les zones s'enchaînent déjà une par une.
POST_APPLICATION_MAX_PASSAGES = 2
POST_APPLICATION_PAUSE_MINUTES = 5
# La logique de dépletion (recharge profonde par épuisement de la réserve utile) est
# active UNIQUEMENT en phase Normal (pelouse établie), dans _profile_for_normal
# (guidance.py) : arrosage déclenché au seuil MAD, recharge vers la réserve utile,
# borné par le garde-fou hebdomadaire. Elle reste exclue des autres phases — en
# Sursemis elle surestimait (recharge profonde inadaptée au semis), d'où la stratégie
# de surface dédiée dans _profile_for_sursemis.
# Le champ legacy ci-dessous (objective_from_depletion_mm) reste exposé pour
# l'observabilité ; l'objectif réel vient de watering_profile["mm_final_recommande"].

_MOWER_WATERING_BLOCK_LABELS = {
    "mower_mowing": "Arrosage bloqué: tondeuse en cours de tonte.",
    "mower_returning": "Arrosage bloqué: tondeuse en retour vers sa station.",
    "mower_not_stowed": "Arrosage bloqué: tondeuse non rangée.",
    "mower_unreliable": "Arrosage bloqué: coordination tondeuse indisponible.",
    "ambiguous": "Tondeuse ambiguë: plusieurs robots détectés, configuration requise.",
    "missing": "Tondeuse absente: aucune tondeuse détectée.",
    "configured_missing": "Tondeuse configurée introuvable.",
}


def compute_kc_gazon(phase_dominante: str, sous_phase: str | None = None, days_since_mowing: int | None = None) -> float:
    phase = str(phase_dominante or "").strip()
    sous_phase = str(sous_phase or "").strip()
    if phase == "Normal":
        kc = 0.8
    elif phase == "Sursemis":
        if sous_phase == "Germination":
            kc = 1.0
        else:
            kc = 0.95
    elif phase == "Hivernage":
        kc = 0.55
    elif phase == "Scarification":
        kc = 0.85
    elif phase in {"Traitement", "Fertilisation", "Biostimulant", "Agent Mouillant"}:
        kc = 0.8
    else:
        kc = 0.75
    # Ajustement post-tonte : restauration feuillage = besoin hydrique accru
    if days_since_mowing is not None and phase not in {"Hivernage", "Traitement"}:
        if days_since_mowing <= 7:
            kc = round(min(kc * 1.15, 1.1), 2)
        elif days_since_mowing <= 14:
            kc = round(min(kc * 1.05, 1.05), 2)
    return kc


def build_water_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
) -> dict[str, Any]:
    application_state = compute_application_state(context.history, today=context.today)
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
        temperature_reference_hydrique=context.temperature_reference_hydrique,
        weather_profile=context.weather_profile,
        humidite=context.humidite,
        vent=context.vent,
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
        soil_balance=context.soil_balance,
        phase_dominante=phase_bundle["phase_dominante"],
    )
    # Calcule jours depuis dernière tonte depuis mémoire ou historique
    days_since_mowing = None
    memory = getattr(context, 'memory', {}) or {}
    derniere_tonte = memory.get("derniere_tonte") if isinstance(memory, dict) else None
    if derniere_tonte:
        try:
            from datetime import date as _date
            tonte_date = _date.fromisoformat(str(derniere_tonte)[:10])
            days_since_mowing = (context.today - tonte_date).days
        except (ValueError, TypeError):
            pass
    kc_gazon = compute_kc_gazon(phase_bundle["phase_dominante"], phase_bundle["sous_phase"], days_since_mowing)
    et0_mm = float(water_balance.get("et0_mm") or etp or 0.0)
    etc_mm = round(max(0.0, et0_mm * kc_gazon), 1)
    reserve_utile_mm = float(water_balance.get("reserve_utile_mm") or 0.0)
    reserve_actuelle_mm = float(water_balance.get("reserve_actuelle_mm") or 0.0)
    mm_cible_depletion = round(max(0.0, reserve_utile_mm - reserve_actuelle_mm), 1)
    # Estimation indicative du prochain jour d'arrosage (AFFICHAGE seul, n'entre dans aucune
    # décision) : nb de jours avant que la réserve atteigne le seuil MAD, au rythme ~ETc/jour.
    jours_avant_arrosage_estime = estimate_days_until_watering(
        reserve_actuelle_mm,
        water_balance.get("reserve_minimale_mm"),
        etc_mm,
    )
    # PLANCHER À DEMAIN QUAND ON A DÉJÀ ARROSÉ AUJOURD'HUI. `estimate_days_until_watering` ne
    # raisonne que sur la réserve : elle répond « quand le sol aura-t-il soif », pas « quand
    # aurai-je le droit ». Son `0` signifie « la projection d'aube franchit le seuil », or l'aube
    # d'aujourd'hui est passée — le prochain déclenchement possible est celui de demain.
    # Sans ce plancher, deux attributs publics se contredisaient le jour même d'un arrosage :
    # `block_reason_label` annonçait « Cooldown 24 h » pendant que `date_prochain_arrosage_estime`
    # affichait AUJOURD'HUI (constaté le 29/07/2026, réserve 10,9 mm après l'arrosage de 06:36).
    balance_snapshot = dict(water_balance)
    # ETc (= ET0 × Kc) exposée au bilan : la PROJECTION de déclenchement à l'aube en a besoin.
    # Le sol perd son eau au rythme de l'HERBE, et le ledger débite déjà l'ETc ; projeter avec
    # l'ET0 brute mélangeait les unités et gonflait la soif prévue de ~25 % (cf. _profile_for_normal).
    balance_snapshot["etc_mm"] = etc_mm
    balance_snapshot["kc_gazon"] = kc_gazon
    if context.soil_balance:
        reserve_mm = context.soil_balance.get("reserve_mm")
        if reserve_mm is not None:
            balance_snapshot["reserve_hydrique_sol_mm"] = reserve_mm
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
        application_type=application_state.get("application_type"),
        forecast_temperature_today=context.forecast_temperature_today,
        evening_cooling_enabled=bool(
            memory.get("evening_cooling_enabled", DEFAULT_EVENING_COOLING_ENABLED)
        ),
        # Le risque fongique est recalculé ici plutôt que repris du bundle « risque » : celui-ci
        # est construit APRÈS le bundle « eau » dans le pipeline, il n'existe donc pas encore.
        # `compute_fungal_risk` ne dépend que d'entrées primitives, le calcul est sans effet de bord.
        fungal_risk_level=compute_fungal_risk(
            temperature=context.temperature,
            humidite=context.humidite,
            rosee=context.rosee,
            pluie_24h=context.pluie_24h,
            pluie_demain=context.pluie_demain,
            hour_of_day=context.hour_of_day if context.hour_of_day is not None else 12,
        ).get("fungal_risk_level"),
    )
    # PLANCHER À DEMAIN — déplacé ici parce qu'il a besoin de la FENÊTRE, publiée par le profil.
    # `estimate_days_until_watering` ne raisonne que sur la réserve : elle répond « quand le sol
    # aura-t-il soif », pas « quand aurai-je le droit ». Son `0` signifie « la projection d'aube
    # franchit le seuil » — or si l'aube est passée, le prochain déclenchement possible est demain.
    #
    # Il ne se déclenchait que si on avait DÉJÀ ARROSÉ aujourd'hui. Or le cas qui compte est
    # l'inverse : la fenêtre du matin s'est écoulée SANS arrosage (retenu par un garde-fou, ou
    # conditions défavorables). L'entité annonçait alors « prochain arrosage : aujourd'hui »
    # à 15 h, pour une fenêtre fermée depuis cinq heures.
    #
    # ⚠️ La borne vient du profil, jamais d'un littéral : elle bouge avec la saison et la phase.
    _fin_fenetre_min = watering_profile.get("watering_window_acceptable_end_minute")
    _minute_courante = (
        context.hour_of_day * 60.0 if context.hour_of_day is not None else None
    )
    _fenetre_du_matin_ecoulee = (
        _fin_fenetre_min is not None
        and _minute_courante is not None
        and _minute_courante >= float(_fin_fenetre_min)
    )
    if jours_avant_arrosage_estime is not None and jours_avant_arrosage_estime <= 0 and (
        float(water_balance.get("arrosage_recent_jour") or 0.0) > 0.0
        or _fenetre_du_matin_ecoulee
    ):
        jours_avant_arrosage_estime = 1
    date_prochain_arrosage_estime = (
        (context.today + timedelta(days=jours_avant_arrosage_estime)).isoformat()
        if jours_avant_arrosage_estime is not None
        else None
    )

    hydric_observability = {
        "weekly_guardrail_mm_min": watering_profile.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": watering_profile.get("weekly_guardrail_mm_max"),
        "weekly_guardrail_reason": watering_profile.get("weekly_guardrail_reason"),
        "season_label": watering_profile.get("season_label"),
        "season_phase": watering_profile.get("season_phase"),
        "month_profile": watering_profile.get("month_profile"),
        "watering_bias": watering_profile.get("watering_bias"),
        "mowing_bias": watering_profile.get("mowing_bias"),
        "intervention_bias": watering_profile.get("intervention_bias"),
        "risk_bias": watering_profile.get("risk_bias"),
        "soil_profile": watering_profile.get("soil_profile"),
        "soil_retention_factor": watering_profile.get("soil_retention_factor"),
        "soil_drainage_factor": watering_profile.get("soil_drainage_factor"),
        "soil_infiltration_factor": watering_profile.get("soil_infiltration_factor"),
        "soil_need_factor": watering_profile.get("soil_need_factor"),
    }
    return {
        "etp": etp,
        "et0_mm": round(max(0.0, et0_mm), 1),
        "et0_source": context.et0_source,
        "kc_gazon": round(min(max(kc_gazon, 0.4), 1.1), 2),
        "etc_mm": etc_mm,
        "jours_avant_arrosage_estime": jours_avant_arrosage_estime,
        "date_prochain_arrosage_estime": date_prochain_arrosage_estime,
        "use_depletion_logic": (
            phase_bundle["phase_dominante"] == "Normal"
            and bool(balance_snapshot.get("reserve_from_soil_ledger"))
        ),  # dépletion active en Normal + réserve sol interne ; sinon repli déficit
        "mm_cible_depletion": mm_cible_depletion,
        "objective_from_depletion_mm": mm_cible_depletion,
        "advanced_context": advanced_context,
        "application_state": application_state,
        "water_balance": balance_snapshot,
        "objectif_mm": watering_profile["mm_final_recommande"],
        # Besoin du sol, insensible aux blocages — voir `besoin_mm` dans guidance.py.
        "besoin_mm": watering_profile.get("besoin_mm"),
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
        "fenetre_optimale": watering_profile.get("fenetre_optimale"),
        "fenetre_optimale_profil": watering_profile.get("fenetre_optimale_profil"),
        "evening_cooling": watering_profile.get("evening_cooling"),
        "evening_cooling_likely": watering_profile.get("evening_cooling_likely"),
        # ⚠️ `water_bundle` recopie les clés du profil UNE PAR UNE (pas de `**watering_profile`) :
        # une clé ajoutée dans `_profile_for_normal` sans être listée ici n'atteint jamais les
        # capteurs, en silence. C'est ce qui est arrivé à `survie_canicule_active` au premier essai.
        "survie_canicule_active": watering_profile.get("survie_canicule_active"),
        "evening_cooling_debug": watering_profile.get("evening_cooling_debug"),
        "block_reason": watering_profile.get("block_reason"),
        "recent_watering_count_7j": watering_profile["recent_watering_count_7j"],
        "recent_watering_mm_7j": watering_profile["recent_watering_mm_7j"],
        "weekly_guardrail_mm_min": watering_profile.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": watering_profile.get("weekly_guardrail_mm_max"),
        "weekly_guardrail_reason": watering_profile.get("weekly_guardrail_reason"),
        "season_label": watering_profile.get("season_label"),
        "season_phase": watering_profile.get("season_phase"),
        "month_profile": watering_profile.get("month_profile"),
        "watering_bias": watering_profile.get("watering_bias"),
        "mowing_bias": watering_profile.get("mowing_bias"),
        "intervention_bias": watering_profile.get("intervention_bias"),
        "risk_bias": watering_profile.get("risk_bias"),
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
        "watering_strategy": watering_profile.get("watering_strategy") or WATERING_STRATEGY_ADULT_DEEP,
        "objective_scope": watering_profile.get("objective_scope") or OBJECTIVE_SCOPE_GLOBAL_SURFACE,
        "watering_stage": watering_profile.get("watering_stage") or WATERING_STAGE_NORMAL,
        "surface_cycle_mm": watering_profile.get("surface_cycle_mm"),
        "daily_cycles_target": watering_profile.get("daily_cycles_target"),
        "cycle_spacing_minutes": watering_profile.get("cycle_spacing_minutes"),
        "surface_moisture_target": watering_profile.get("surface_moisture_target"),
        "surface_dryness_risk": watering_profile.get("surface_dryness_risk"),
        "runoff_risk": watering_profile.get("runoff_risk"),
        "surface_saturation_level": watering_profile.get("surface_saturation_level"),
        "surface_saturation_limit": watering_profile.get("surface_saturation_limit"),
        "seeding_transition_ready": watering_profile.get("seeding_transition_ready"),
        "seeding_block_reason": watering_profile.get("seeding_block_reason"),
        "watering_window_start_minute": watering_profile.get("watering_window_start_minute"),
        "watering_window_end_minute": watering_profile.get("watering_window_end_minute"),
        "watering_window_optimal_start_minute": watering_profile.get("watering_window_optimal_start_minute"),
        "watering_window_optimal_end_minute": watering_profile.get("watering_window_optimal_end_minute"),
        "watering_window_acceptable_end_minute": watering_profile.get("watering_window_acceptable_end_minute"),
        "watering_evening_start_minute": watering_profile.get("watering_evening_start_minute"),
        "watering_evening_end_minute": watering_profile.get("watering_evening_end_minute"),
        "watering_window_profile": watering_profile.get("watering_window_profile"),
        "watering_evening_allowed": watering_profile.get("watering_evening_allowed"),
        **hydric_observability,
    }


def _watering_needed_text() -> str:
    return "Éviter tout arrosage inutile."


def _watering_window_phrase(window: str, hour_of_day: float) -> str:
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
    return min(3, max(1, passages))


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
        "application_post_watering_status": application_state.get("application_post_watering_status"),
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


def _decision_resume_payload(
    *,
    faire: bool,
    action: str,
    moment: str,
    objectif_mm: float,
    type_arrosage: str,
    niveau_action: str,
    risque_gazon: str,
) -> dict[str, Any]:
    return {
        "faire": faire,
        "action": action,
        "moment": moment,
        "objectif_mm": objectif_mm,
        "type_arrosage": type_arrosage,
        "niveau_action": niveau_action,
        "risque_gazon": risque_gazon,
    }


def _build_watering_bundle_base(
    *,
    water_bundle: dict[str, Any],
    phase_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
    mowing_bundle: dict[str, Any],
    mower_context: dict[str, Any],
    application_payload: dict[str, Any],
    watering_target_date: str | None,
) -> dict[str, Any]:
    return {
        "objectif_mm": float(water_bundle.get("objectif_mm") or 0.0),
        "objectif_mm_brut": float(water_bundle.get("objectif_mm_brut") or 0.0),
        "deficit_brut_mm": float(water_bundle.get("deficit_brut_mm") or water_bundle.get("objectif_mm_brut") or 0.0),
        "deficit_mm_brut": float(water_bundle.get("deficit_mm_brut") or water_bundle.get("objectif_mm_brut") or 0.0),
        # Même piège qu'en aval : zéro est une valeur LÉGITIME du déficit ajusté (pluie annoncée),
        # pas une absence. Le `or` publiait le déficit brut à sa place dans l'attribut public.
        "deficit_mm_ajuste": float(
            water_bundle["deficit_mm_ajuste"]
            if water_bundle.get("deficit_mm_ajuste") is not None
            else (water_bundle.get("objectif_mm_brut") or 0.0)
        ),
        "mm_cible": float(water_bundle.get("mm_cible") or 0.0),
        "mm_final_recommande": float(water_bundle.get("mm_final_recommande") or water_bundle.get("objectif_mm") or 0.0),
        # ⚠️ Ce bloc RECOPIE le bundle clé par clé : toute clé oubliée ici se perd en
        # silence, quel que soit le soin mis en amont. `besoin_mm` s'y était perdu —
        # le calcul était juste, le snapshot ne le portait pas.
        "besoin_mm": (
            float(water_bundle["besoin_mm"])
            if water_bundle.get("besoin_mm") is not None
            else None
        ),
        "mm_final": float(water_bundle.get("mm_final") or water_bundle.get("mm_final_recommande") or 0.0),
        "mm_requested": water_bundle.get("mm_requested"),
        "mm_applied": water_bundle.get("mm_applied"),
        "mm_detected": water_bundle.get("mm_detected"),
        # Bilan hydrique de référence. `_apply_irrigation_execution_contract` s'en sert pour lever
        # le drapeau « bloqué ALORS QUE le déficit est critique » : il le cherchait dans le payload
        # sans que rien ne l'y place jamais, si bien qu'il lisait 0.0 et que l'alerte ne se
        # déclenchait jamais en production, quel que soit le déficit réel.
        "bilan_hydrique_mm": _reference_hydric_balance_mm(water_bundle.get("water_balance") or {}),
        "conseil_principal": None,
        "action_recommandee": None,
        "action_a_eviter": None,
        "arrosage_recommande": False,
        "arrosage_auto_autorise": False,
        "watering_cause": "rafraichissement_soir" if water_bundle.get("evening_cooling") else "hydrique",
        "type_arrosage": "aucune_action",
        "arrosage_conseille": "aucune_action",
        "fractionnement": water_bundle.get("fractionnement"),
        "niveau_confiance": water_bundle.get("niveau_confiance"),
        "confidence_score": water_bundle.get("confidence_score"),
        "confidence_reasons": water_bundle.get("confidence_reasons"),
        "heat_stress_level": water_bundle.get("heat_stress_level") or risk_bundle.get("heat_stress_level"),
        "heat_stress_phase": water_bundle.get("heat_stress_phase") or risk_bundle.get("heat_stress_phase") or "normal",
        "decision_resume": None,
        "block_reason": water_bundle.get("block_reason"),
        "raison_decision": None,
        "niveau_action": risk_bundle["niveau_action"],
        # Le profil d'arrosage fait foi pour « soir » DANS LES DEUX SENS.
        # Lui seul reçoit le coucher du soleil et applique les garde-fous de séchage
        # (cf. _profile_for_normal : « LE SOIR = UNIQUEMENT LE RAFRAÎCHISSEMENT (3 mm), JAMAIS UNE
        # RECHARGE »). Le risk bundle, lui, ne teste que `evening_allowed` + l'heure.
        # L'ancienne écriture ne laissait le profil qu'AJOUTER « soir », jamais le RETIRER : quand
        # il renvoyait délibérément une fenêtre du matin (cooling inactif — switch éteint,
        # température < seuil, pluie — donc recharge complète reportée au frais), le « soir » du
        # risk bundle reprenait le dessus. Constaté en réel (24/07/2026) : 11 mm de recharge
        # planifiés à 21h11 pour un cycle de 2h13, soit une fin ~1h45 APRÈS le coucher du soleil,
        # gazon trempé toute la nuit — exactement le risque fongique que le profil écartait.
        "fenetre_optimale": _resolve_optimal_window(
            water_bundle.get("fenetre_optimale"), risk_bundle["fenetre_optimale"]
        ),
        "risque_gazon": risk_bundle["risque_gazon"],
        "risque_gazon_raisons": risk_bundle.get("risque_gazon_raisons") or [],
        "prochaine_reevaluation": risk_bundle["prochaine_reevaluation"],
        "tonte_autorisee": mowing_bundle["tonte_autorisee"],
        "tonte_statut": mowing_bundle["tonte_statut"],
        "watering_passages": 1,
        "watering_pause_minutes": 0,
        "watering_target_date": watering_target_date,
        "weekly_guardrail_mm_min": water_bundle.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": water_bundle.get("weekly_guardrail_mm_max"),
        "weekly_guardrail_reason": water_bundle.get("weekly_guardrail_reason"),
        "watering_strategy": water_bundle.get("watering_strategy") or WATERING_STRATEGY_ADULT_DEEP,
        "objective_scope": water_bundle.get("objective_scope") or OBJECTIVE_SCOPE_GLOBAL_SURFACE,
        "watering_stage": water_bundle.get("watering_stage") or WATERING_STAGE_NORMAL,
        "surface_cycle_mm": water_bundle.get("surface_cycle_mm"),
        "daily_cycles_target": water_bundle.get("daily_cycles_target"),
        "cycle_spacing_minutes": water_bundle.get("cycle_spacing_minutes"),
        "surface_moisture_target": water_bundle.get("surface_moisture_target"),
        "surface_dryness_risk": water_bundle.get("surface_dryness_risk"),
        "runoff_risk": water_bundle.get("runoff_risk"),
        "seeding_transition_ready": water_bundle.get("seeding_transition_ready"),
        "seeding_block_reason": water_bundle.get("seeding_block_reason"),
        "season_label": water_bundle.get("season_label"),
        "season_phase": water_bundle.get("season_phase"),
        "month_profile": water_bundle.get("month_profile"),
        "watering_bias": water_bundle.get("watering_bias"),
        "mowing_bias": water_bundle.get("mowing_bias"),
        "intervention_bias": water_bundle.get("intervention_bias"),
        "risk_bias": water_bundle.get("risk_bias"),
        "soil_profile": water_bundle.get("soil_profile"),
        "soil_retention_factor": water_bundle.get("soil_retention_factor"),
        "soil_drainage_factor": water_bundle.get("soil_drainage_factor"),
        "soil_infiltration_factor": water_bundle.get("soil_infiltration_factor"),
        "soil_need_factor": water_bundle.get("soil_need_factor"),
        "watering_window_start_minute": water_bundle.get("watering_window_start_minute") or risk_bundle.get(
            "watering_window_start_minute"
        ),
        "watering_window_end_minute": water_bundle.get("watering_window_end_minute") or risk_bundle.get(
            "watering_window_end_minute"
        ),
        "watering_window_optimal_start_minute": water_bundle.get("watering_window_optimal_start_minute")
        or risk_bundle.get("watering_window_optimal_start_minute"),
        "watering_window_optimal_end_minute": water_bundle.get("watering_window_optimal_end_minute")
        or risk_bundle.get("watering_window_optimal_end_minute"),
        "watering_window_acceptable_end_minute": water_bundle.get("watering_window_acceptable_end_minute")
        or risk_bundle.get("watering_window_acceptable_end_minute"),
        "watering_evening_start_minute": water_bundle.get("watering_evening_start_minute")
        or risk_bundle.get("watering_evening_start_minute"),
        "watering_evening_end_minute": water_bundle.get("watering_evening_end_minute")
        or risk_bundle.get("watering_evening_end_minute"),
        "watering_window_profile": water_bundle.get("watering_window_profile") or risk_bundle.get(
            "watering_window_profile"
        ),
        "watering_evening_allowed": water_bundle.get("watering_evening_allowed") or risk_bundle.get(
            "watering_evening_allowed"
        ),
        "_mower_coordination_context": dict(mower_context or {}),
        **application_payload,
    }


def _reset_semis_fields_for_non_sursemis(bundle: dict[str, Any]) -> None:
    bundle.update(
        {
            "watering_strategy": WATERING_STRATEGY_ADULT_DEEP,
            "objective_scope": OBJECTIVE_SCOPE_GLOBAL_SURFACE,
            "watering_stage": WATERING_STAGE_NORMAL,
            "surface_cycle_mm": None,
            "daily_cycles_target": None,
            "cycle_spacing_minutes": None,
            "surface_moisture_target": None,
            "surface_dryness_risk": None,
            "runoff_risk": None,
            "surface_saturation_level": None,
            "surface_saturation_limit": None,
            "seeding_transition_ready": None,
            "seeding_block_reason": None,
            "sursemis_micro_apport_allowed": None,
            "sursemis_block_reason": None,
            "sursemis_reason": None,
            "sursemis_seuil_declencheur": None,
            "sursemis_policy": None,
            "sursemis_transition_ready": None,
            "sursemis_tonte_count": None,
        }
    )


def _mower_watering_block_reason(mower_context: dict[str, Any]) -> str | None:
    if not mower_context or mower_context.get("mower_coordination_enabled") is not True:
        return None
    if mower_context.get("mower_is_mowing") is True:
        return "mower_mowing"
    if mower_context.get("mower_is_returning") is True:
        return "mower_returning"
    reason_code = str(mower_context.get("mower_reason_code") or "").strip().lower()
    if reason_code in {"ambiguous", "missing", "configured_missing"}:
        return reason_code
    if mower_context.get("mower_coordination_ready") is not True:
        return "mower_unreliable"
    if mower_context.get("mower_is_safe_for_watering") is not True:
        return "mower_not_stowed"
    return None


def _apply_irrigation_execution_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Enrichit le payload avec des flags d'urgence hydrique même en cas de blocage."""
    irrigation_blocked = bool(
        payload.get("watering_blocked_by_mower")
        or str(payload.get("type_arrosage") or "") == "bloque"
        or not bool(payload.get("irrigation_execution_allowed", True))
    )
    bilan_mm = 0.0
    water_balance = payload.get("water_balance")
    if isinstance(water_balance, dict):
        bilan_mm = float(water_balance.get("bilan_hydrique_mm") or 0.0)
    if bilan_mm == 0.0:
        bilan_mm = float(payload.get("bilan_hydrique_mm") or 0.0)
    CRITICAL_DEFICIT_MM = -2.5
    critical = irrigation_blocked and bilan_mm <= CRITICAL_DEFICIT_MM
    block_reason = payload.get("block_reason") or payload.get("watering_block_reason_code") or "inconnu"
    payload["irrigation_blocked_but_critical"] = critical
    payload["critical_deficit_mm"] = round(bilan_mm, 1) if critical else None
    payload["critical_irrigation_reason"] = (
        f"Déficit critique {bilan_mm:.1f} mm malgré blocage ({block_reason})"
        if critical else None
    )
    return payload


def _payload_has_watering_intent(payload: dict[str, Any]) -> bool:
    objectif_mm = float(payload.get("objectif_mm") or 0.0)
    type_arrosage = str(payload.get("type_arrosage") or "").strip().lower()
    if payload.get("arrosage_recommande") is True:
        return True
    if payload.get("arrosage_auto_autorise") is True:
        return True
    if objectif_mm > 0 and type_arrosage not in {"", "aucune_action"}:
        return True
    return False


def _apply_mower_coordination_block(payload: dict[str, Any]) -> dict[str, Any]:
    mower_context = payload.get("_mower_coordination_context")
    if not isinstance(mower_context, dict):
        return payload

    for key, value in mower_context.items():
        if key.startswith("mower_") and key not in payload and value is not None:
            payload[key] = value

    block_reason = _mower_watering_block_reason(mower_context)
    if not block_reason or not _payload_has_watering_intent(payload):
        payload.setdefault("watering_blocked_by_mower", False)
        payload.setdefault("watering_block_reason_code", None)
        payload.setdefault("watering_block_reason_label", None)
        return payload

    label = _MOWER_WATERING_BLOCK_LABELS[block_reason]
    payload["watering_blocked_by_mower"] = True
    payload["watering_block_reason_code"] = block_reason
    payload["watering_block_reason_label"] = label
    payload["block_reason"] = block_reason
    payload["arrosage_auto_autorise"] = False
    payload["fenetre_optimale"] = "attendre"
    payload["type_arrosage"] = "bloque"
    if payload.get("arrosage_recommande"):
        payload["arrosage_conseille"] = "personnalise"
    if payload.get("niveau_action") in (None, "aucune_action"):
        payload["niveau_action"] = "surveiller"
    if not payload.get("conseil_principal"):
        payload["conseil_principal"] = label
    if not payload.get("action_recommandee"):
        payload["action_recommandee"] = "Attends que la tondeuse soit réellement rangée avant d'arroser."
    if not payload.get("action_a_eviter"):
        payload["action_a_eviter"] = "Lancer un arrosage pendant que la tondeuse est dehors."

    raison = str(payload.get("raison_decision") or "").strip()
    if raison:
        payload["raison_decision"] = f"{label} {raison}"
    else:
        payload["raison_decision"] = label

    decision_resume = payload.get("decision_resume")
    if isinstance(decision_resume, dict):
        payload["decision_resume"] = {
            **decision_resume,
            "faire": False,
            "action": "aucune_action",
            "moment": "attendre",
            "type_arrosage": "bloque",
        }
    return payload


def _resolve_optimal_window(profil: Any, risk: Any) -> Any:
    """Fenêtre retenue entre le profil d'arrosage et le risk bundle.

    Le PROFIL fait autorité sur « soir », dans les deux sens : lui seul connaît le coucher du
    soleil et applique les garde-fous de séchage. Le risk bundle ne teste que `evening_allowed`
    et l'heure ; s'il propose « soir » alors que le profil a écarté cette fenêtre, on suit le
    profil (la recharge complète est reportée au frais du matin, cf. _profile_for_normal).
    """
    if profil == "soir":
        return "soir"
    if risk == "soir" and profil:
        return profil
    return risk


def _bundle_with(base_bundle: dict[str, Any], **updates: Any) -> dict[str, Any]:
    payload = dict(base_bundle)
    payload.update(updates)
    payload = _apply_mower_coordination_block(payload)
    payload["type_arrosage"], payload["arrosage_conseille"] = normalize_watering_contract(
        payload.get("type_arrosage"),
        payload.get("arrosage_conseille"),
    )
    payload.pop("_mower_coordination_context", None)
    payload = _apply_irrigation_execution_contract(payload)
    return payload


def _resolve_hivernage_override(state: dict[str, Any]) -> dict[str, Any] | None:
    if state["phase_dominante"] != "Hivernage":
        return None
    return _bundle_with(
        state["base_bundle"],
        objectif_mm=0.0,
        watering_cause="post_application",
        tonte_autorisee=False,
        tonte_statut="interdite",
        arrosage_auto_autorise=False,
        arrosage_recommande=False,
        type_arrosage="bloque",
        arrosage_conseille="personnalise",
        conseil_principal="N'arrose pas et limite les interventions.",
        action_recommandee="Surveille uniquement.",
        action_a_eviter="Arroser fréquemment.",
        raison_decision=(
            f"Hivernage actif: repos végétatif. "
            f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
        ),
        decision_resume=_decision_resume_payload(
            faire=False,
            action="aucune_action",
            moment="attendre",
            objectif_mm=0.0,
            type_arrosage="bloque",
            niveau_action=state["niveau_action"],
            risque_gazon=state["risque_gazon"],
        ),
    )


def _resolve_unknown_application_override(state: dict[str, Any]) -> dict[str, Any] | None:
    if not state["application_summary"] or state["application_type_known"]:
        return None
    return _bundle_with(
        state["base_bundle"],
        objectif_mm=0.0,
        watering_cause="post_application",
        tonte_autorisee=False,
        tonte_statut="interdite",
        arrosage_auto_autorise=False,
        arrosage_recommande=False,
        type_arrosage="bloque",
        arrosage_conseille="personnalise",
        conseil_principal=(
            f"{state['application_label']}: type d'application inconnu, aucun arrosage automatique ne doit être lancé."
        ),
        action_recommandee="Vérifie l'étiquette ou renseigne le type d'application avant d'arroser.",
        action_a_eviter="Lancer un arrosage sans type d'application confirmé.",
        raison_decision=(
            "Type d'application inconnu: sécurité renforcée, aucun arrosage automatique. "
            f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
        ),
        decision_resume=_decision_resume_payload(
            faire=False,
            action="aucune_action",
            moment="attendre",
            objectif_mm=0.0,
            type_arrosage="bloque",
            niveau_action="surveiller",
            risque_gazon=state["risque_gazon"],
        ),
        niveau_action="surveiller",
        fenetre_optimale="attendre",
    )


def _resolve_application_block_override(state: dict[str, Any]) -> dict[str, Any] | None:
    if not state["application_block_active"]:
        return None
    return _bundle_with(
        state["base_bundle"],
        objectif_mm=0.0,
        watering_cause="post_application",
        tonte_autorisee=False,
        tonte_statut="interdite",
        arrosage_auto_autorise=False,
        arrosage_recommande=False,
        type_arrosage="bloque",
        arrosage_conseille="personnalise",
        conseil_principal=f"{state['application_label']}: l'arrosage est bloqué jusqu'à la fin de la fenêtre de protection.",
        action_recommandee="Attends la fin du bloc applicatif avant d'arroser.",
        action_a_eviter="Arroser pendant la fenêtre de protection.",
        raison_decision=(
            f"Bloc applicatif actif jusqu'au {state['application_block_until'] or 'prochain créneau autorisé'}. "
            f"Temps restant={state['application_block_remaining_minutes']:.0f} min. "
            f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
        ),
        decision_resume=_decision_resume_payload(
            faire=False,
            action="aucune_action",
            moment="attendre",
            objectif_mm=0.0,
            type_arrosage="bloque",
            niveau_action="surveiller",
            risque_gazon=state["risque_gazon"],
        ),
        niveau_action="surveiller",
        fenetre_optimale="attendre",
    )


def _resolve_foliar_application_override(state: dict[str, Any]) -> dict[str, Any] | None:
    if not state["application_summary"] or state["application_type"] != APPLICATION_TYPE_FOLIAIRE:
        return None
    return _bundle_with(
        state["base_bundle"],
        objectif_mm=0.0,
        tonte_autorisee=False,
        tonte_statut="interdite",
        arrosage_auto_autorise=False,
        arrosage_recommande=False,
        type_arrosage="bloque",
        arrosage_conseille="personnalise",
        conseil_principal=(
            f"{state['application_label']}: traitement foliaire sans arrosage automatique pendant la fenêtre de protection."
        ),
        action_recommandee="Attends la fin de la protection avant toute irrigation.",
        action_a_eviter="Arroser une application foliaire trop tôt.",
        raison_decision=(
            f"Application foliaire: arrosage automatique interdit, "
            f"bloc restant={state['application_block_remaining_minutes']:.0f} min, "
            f"mode={state['application_mode'] or 'suggestion'}. "
            f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
        ),
        decision_resume=_decision_resume_payload(
            faire=False,
            action="aucune_action",
            moment="attendre",
            objectif_mm=0.0,
            type_arrosage="bloque",
            niveau_action="surveiller",
            risque_gazon=state["risque_gazon"],
        ),
        niveau_action="surveiller",
        fenetre_optimale="attendre",
    )


def _resolve_pending_sol_application_override(state: dict[str, Any]) -> dict[str, Any] | None:
    if not (
        state["application_requires_watering_after"]
        and state["application_type"] == APPLICATION_TYPE_SOL
        and state["application_post_watering_pending"]
    ):
        return None

    # « Pas prêt » recouvre deux causes distinctes ici (le bloc de protection est
    # déjà capté en amont par _resolve_application_block_override) : soit un délai
    # d'incorporation encore en cours (> 0), soit un mode qui n'autorise pas le
    # lancement auto (« suggestion »). On ne parle d'« attendre » QUE s'il reste un
    # vrai délai ; sinon (délai écoulé + mode suggestion) on laisse la branche
    # suggestion ci-dessous rendre le bon message, au lieu d'un « attendre 0 min ».
    if (
        not state["application_post_watering_ready"]
        and state["application_post_watering_delay_remaining_minutes"] > 0
    ):
        return _bundle_with(
            state["base_bundle"],
            objectif_mm=0.0,
            watering_cause="post_application",
            arrosage_auto_autorise=False,
            arrosage_recommande=False,
            type_arrosage="personnalise",
            arrosage_conseille="personnalise",
            conseil_principal=(
                f"{state['application_label']}: attendre encore {state['application_post_watering_delay_remaining_minutes']:.0f} min "
                "avant l'arrosage technique."
            ),
            action_recommandee="Attends la fin du délai applicatif avant d'arroser.",
            action_a_eviter="Arroser avant la fin du délai d'incorporation.",
            raison_decision=(
                f"Application technique différée: délai restant {state['application_post_watering_delay_remaining_minutes']:.0f} min, "
                f"mode={state['application_mode'] or 'auto'}. "
                f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
            ),
            decision_resume=_decision_resume_payload(
                faire=False,
                action="aucune_action",
                moment="attendre",
                objectif_mm=0.0,
                type_arrosage="personnalise",
                niveau_action=state["niveau_action"],
                risque_gazon=state["risque_gazon"],
            ),
        )

    objectif_mm = round(max(0.5, state["application_post_watering_remaining_mm"] or 0.0), 1)
    passages = min(
        POST_APPLICATION_MAX_PASSAGES,
        _soil_fractionation_passages(
            state["phase_dominante"],
            state["sous_phase"],
            state["soil_style"],
            objectif_mm,
            state["stress_level"],
            temperature=state["temperature"],
            humidite=state["humidite"],
            etp=state["etp"],
        ),
    )
    style_text = _watering_style_text(
        state["phase_dominante"], state["soil_style"], objectif_mm, state["stress_level"], passages
    )

    if state["application_mode"] == "suggestion":
        return _bundle_with(
            state["base_bundle"],
            objectif_mm=0.0,
            fenetre_optimale="maintenant",
            watering_cause="post_application",
            arrosage_auto_autorise=False,
            arrosage_recommande=False,
            type_arrosage="personnalise",
            arrosage_conseille="personnalise",
            conseil_principal=f"{state['application_label']}: arrosage technique suggéré, sans lancement automatique.",
            action_recommandee=(
                f"Suggestion d'arrosage technique: {objectif_mm:.1f} mm {style_text} "
                "si l'étiquette du produit l'autorise."
            ),
            action_a_eviter="Lancer un arrosage automatique non confirmé.",
            raison_decision=(
                f"Application technique en suggestion uniquement: {state['application_label']}, "
                f"mode=suggestion. "
                f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
            ),
            decision_resume=_decision_resume_payload(
                faire=False,
                action="aucune_action",
                moment="attendre",
                objectif_mm=0.0,
                type_arrosage="personnalise",
                niveau_action=state["niveau_action"],
                risque_gazon=state["risque_gazon"],
            ),
        )

    conseil_principal = (
        f"{state['application_label']}: arrosage manuel immédiat pour activer ou incorporer le produit."
        if state["application_mode"] == "manuel"
        else f"{state['application_label']}: arrose maintenant pour activer/incorporer le produit."
    )
    action_recommandee = (
        f"Arrosage manuel immédiat requis: applique {objectif_mm:.1f} mm {style_text}."
        if state["application_mode"] == "manuel"
        else f"Applique {objectif_mm:.1f} mm {style_text} en arrosage technique."
    )
    auto_autorise = state["application_mode"] in {"", "auto"}
    return _bundle_with(
        state["base_bundle"],
        objectif_mm=objectif_mm,
        mm_cible=objectif_mm,
        mm_final_recommande=objectif_mm,
        mm_final=objectif_mm,
        mm_requested=objectif_mm,
        mm_applied=objectif_mm,
        fenetre_optimale="maintenant",
        watering_target_date=state["context"].today.isoformat(),
        watering_cause="post_application",
        arrosage_auto_autorise=auto_autorise,
        arrosage_recommande=True,
        type_arrosage="application_technique_auto" if auto_autorise else "application_technique",
        arrosage_conseille="application_technique",
        conseil_principal=conseil_principal,
        action_recommandee=action_recommandee,
        action_a_eviter="Arroser en excès ou trop tard.",
        raison_decision=(
            f"Application technique en attente: {state['application_label']}, "
            f"mm restant={state['application_post_watering_remaining_mm']:.1f}, "
            f"fenêtre={state['fenetre_texte']}, bilan={state['bilan_hydrique_mm']:.1f} mm, mode={state['application_mode'] or 'auto'}. "
            f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], objectif_mm)}"
        ),
        decision_resume=_decision_resume_payload(
            faire=True,
            action="arrosage",
            moment="maintenant",
            objectif_mm=objectif_mm,
            type_arrosage="application_technique_auto" if auto_autorise else "application_technique",
            niveau_action=state["niveau_action"],
            risque_gazon=state["risque_gazon"],
        ),
        watering_passages=passages,
        watering_pause_minutes=POST_APPLICATION_PAUSE_MINUTES if passages > 1 else 0,
    )


def _resolve_traitement_override(state: dict[str, Any]) -> dict[str, Any] | None:
    if state["phase_dominante"] != "Traitement":
        return None
    return _bundle_with(
        state["base_bundle"],
        objectif_mm=0.0,
        tonte_autorisee=False,
        tonte_statut="interdite",
        arrosage_auto_autorise=False,
        arrosage_recommande=False,
        type_arrosage="bloque",
        arrosage_conseille="personnalise",
        conseil_principal=f"Laisser agir le traitement encore {state['phase_bundle']['jours_restants']} jour(s).",
        action_recommandee="Surveiller l'état du gazon sans intervention hydrique.",
        action_a_eviter="Tondre ou arroser.",
        raison_decision=(
            f"Traitement actif: tonte et arrosage bloqués. "
            f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
        ),
        decision_resume=_decision_resume_payload(
            faire=False,
            action="aucune_action",
            moment="attendre",
            objectif_mm=0.0,
            type_arrosage="bloque",
            niveau_action=state["niveau_action"],
            risque_gazon=state["risque_gazon"],
        ),
    )


def _resolve_fertilization_window_override(state: dict[str, Any]) -> dict[str, Any] | None:
    if state["phase_dominante"] not in {"Fertilisation", "Biostimulant"} or state["fertilization_allowed"]:
        return None
    return _bundle_with(
        state["base_bundle"],
        objectif_mm=0.0,
        arrosage_auto_autorise=False,
        arrosage_recommande=False,
        type_arrosage="bloque",
        arrosage_conseille="personnalise",
        conseil_principal=(
            f"{state['phase_dominante']}: reporte l'application, la fenêtre est trop chaude ou trop sèche."
        ),
        action_recommandee="Attends un créneau plus frais et moins stressant.",
        action_a_eviter="Fertiliser sous chaleur ou stress hydrique.",
        raison_decision=(
            f"{state['phase_dominante']} bloqué: bilan={state['bilan_hydrique_mm']:.1f} mm, "
            f"stress={state['stress_level']}, température={state['temperature']:.1f}°C, ETP={state['etp']:.1f} mm. "
            f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
        ),
        decision_resume=_decision_resume_payload(
            faire=False,
            action="aucune_action",
            moment="attendre",
            objectif_mm=0.0,
            type_arrosage="bloque",
            niveau_action="surveiller",
            risque_gazon=state["risque_gazon"],
        ),
        niveau_action="surveiller",
        fenetre_optimale="attendre",
    )


def _resolve_sursemis_override(state: dict[str, Any]) -> dict[str, Any] | None:
    if state["phase_dominante"] != "Sursemis":
        return None
    sursemis_allowed = bool(state["water_bundle"].get("sursemis_micro_apport_allowed"))
    surface_sec = bool(state["water_bundle"].get("surface_sec"))
    pluie_probabilite_24h = float(state["water_bundle"].get("pluie_probabilite_24h") or 0.0)
    mm_detected_24h = float(state["water_bundle"].get("mm_detected_24h") or 0.0)
    sursemis_reason = str(state["water_bundle"].get("sursemis_reason") or "")
    sursemis_thresholds = str(state["water_bundle"].get("sursemis_seuil_declencheur") or "")
    sursemis_block_reason = state["water_bundle"].get("sursemis_block_reason")
    watering_strategy = str(
        state["water_bundle"].get("watering_strategy") or WATERING_STRATEGY_SEMIS_FREQUENT
    )
    objective_scope = str(
        state["water_bundle"].get("objective_scope") or OBJECTIVE_SCOPE_SURFACE_CYCLE
    )
    watering_stage = str(state["water_bundle"].get("watering_stage") or WATERING_STAGE_LEVEE)
    surface_cycle_mm = float(state["water_bundle"].get("surface_cycle_mm") or 0.0)
    daily_cycles_target = int(state["water_bundle"].get("daily_cycles_target") or 1)
    cycle_spacing_minutes = int(state["water_bundle"].get("cycle_spacing_minutes") or 0)
    surface_moisture_target = str(state["water_bundle"].get("surface_moisture_target") or "")
    surface_dryness_risk = str(state["water_bundle"].get("surface_dryness_risk") or "")
    runoff_risk = str(state["water_bundle"].get("runoff_risk") or "")
    transition_ready = bool(state["water_bundle"].get("seeding_transition_ready") or False)
    runtime_context = getattr(state["context"], "runtime_context", {}) or {}
    semis_followup_state = str(runtime_context.get("semis_followup_state") or "").strip()
    semis_cycles_remaining_today_raw = runtime_context.get("semis_cycles_remaining_today")
    semis_cycles_remaining_today = (
        int(semis_cycles_remaining_today_raw)
        if semis_cycles_remaining_today_raw not in (None, "")
        else None
    )
    semis_followup_due_display = str(runtime_context.get("semis_followup_due_display") or "").strip()
    semis_followup_due_at = runtime_context.get("semis_followup_due_at")

    if semis_followup_state == "complete":
        return _bundle_with(
            state["base_bundle"],
            objectif_mm=0.0,
            mm_cible=0.0,
            mm_final_recommande=0.0,
            mm_final=0.0,
            mm_requested=0.0,
            mm_applied=0.0,
            tonte_autorisee=False,
            tonte_statut="interdite",
            arrosage_auto_autorise=False,
            arrosage_recommande=False,
            type_arrosage="aucune_action",
            arrosage_conseille="personnalise",
            conseil_principal=(
                f"Sursemis {watering_stage}: stratégie semis_frequent déjà satisfaite pour aujourd'hui."
            ),
            action_recommandee="Aucun cycle supplémentaire aujourd'hui.",
            action_a_eviter="Lancer un cycle supplémentaire inutilement.",
            raison_decision=(
                f"Sursemis / {state['sous_phase']}: objectif de cycles quotidiens atteint. "
                f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
            ),
            niveau_confiance="info",
            confidence_score=100,
            confidence_reasons=["objectif de cycles quotidiens atteint"],
            decision_resume=_decision_resume_payload(
                faire=False,
                action="aucune_action",
                moment="attendre",
                objectif_mm=0.0,
                type_arrosage="aucune_action",
                niveau_action="surveiller",
                risque_gazon=state["risque_gazon"],
            ),
            niveau_action="surveiller",
            fenetre_optimale="attendre",
            watering_passages=1,
            watering_pause_minutes=0,
            surface_sec=surface_sec,
            pluie_probabilite_24h=pluie_probabilite_24h,
            mm_detected_24h=mm_detected_24h,
            sursemis_micro_apport_allowed=sursemis_allowed,
            sursemis_block_reason="semis_cycle_daily_target_reached",
            sursemis_reason=sursemis_reason,
            sursemis_seuil_declencheur=sursemis_thresholds,
            watering_strategy=watering_strategy,
            objective_scope=objective_scope,
            watering_stage=watering_stage,
            surface_cycle_mm=surface_cycle_mm,
            daily_cycles_target=daily_cycles_target,
            cycle_spacing_minutes=cycle_spacing_minutes,
            surface_moisture_target=surface_moisture_target,
            surface_dryness_risk=surface_dryness_risk,
            runoff_risk=runoff_risk,
            seeding_transition_ready=transition_ready,
            seeding_block_reason="semis_cycle_daily_target_reached",
            semis_followup_state=semis_followup_state or "complete",
            semis_followup_due_display=semis_followup_due_display or None,
            semis_followup_due_at=semis_followup_due_at,
            semis_cycles_completed_today=daily_cycles_target,
            semis_cycles_remaining_today=0,
            fractionnement={
                "enabled": False,
                "passages": 1,
                "pause_minutes": 0,
                "max_mm_per_passage": 0.0,
                "reason": "semis_cycle_daily_target_reached",
            },
        )

    if semis_followup_state == "waiting" and (semis_cycles_remaining_today or 0) > 0:
        return _bundle_with(
            state["base_bundle"],
            objectif_mm=0.0,
            mm_cible=0.0,
            mm_final_recommande=0.0,
            mm_final=0.0,
            mm_requested=0.0,
            mm_applied=0.0,
            tonte_autorisee=False,
            tonte_statut="interdite",
            arrosage_auto_autorise=False,
            arrosage_recommande=False,
            type_arrosage="bloque",
            arrosage_conseille="personnalise",
            conseil_principal=(
                f"Sursemis {watering_stage}: prochain cycle déjà programmé, attends l'échéance."
            ),
            action_recommandee=(
                f"Prochain cycle semis_frequent à {semis_followup_due_display or 'bientôt'}."
            ),
            action_a_eviter="Déclencher un nouveau cycle avant l'échéance.",
            raison_decision=(
                f"Sursemis / {state['sous_phase']}: cycle suivant déjà planifié. "
                f"Prochain créneau={semis_followup_due_display or 'bientôt'}. "
                f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], 0.0)}"
            ),
            niveau_confiance="info",
            confidence_score=100,
            confidence_reasons=["cycle suivant déjà planifié"],
            decision_resume=_decision_resume_payload(
                faire=False,
                action="aucune_action",
                moment="attendre",
                objectif_mm=0.0,
                type_arrosage="bloque",
                niveau_action="surveiller",
                risque_gazon=state["risque_gazon"],
            ),
            niveau_action="surveiller",
            fenetre_optimale="attendre",
            watering_passages=1,
            watering_pause_minutes=0,
            surface_sec=surface_sec,
            pluie_probabilite_24h=pluie_probabilite_24h,
            mm_detected_24h=mm_detected_24h,
            sursemis_micro_apport_allowed=sursemis_allowed,
            sursemis_block_reason="semis_cycle_pending",
            sursemis_reason=sursemis_reason,
            sursemis_seuil_declencheur=sursemis_thresholds,
            watering_strategy=watering_strategy,
            objective_scope=objective_scope,
            watering_stage=watering_stage,
            surface_cycle_mm=surface_cycle_mm,
            daily_cycles_target=daily_cycles_target,
            cycle_spacing_minutes=cycle_spacing_minutes,
            surface_moisture_target=surface_moisture_target,
            surface_dryness_risk=surface_dryness_risk,
            runoff_risk=runoff_risk,
            seeding_transition_ready=transition_ready,
            seeding_block_reason="semis_cycle_pending",
            semis_followup_state=semis_followup_state or "waiting",
            semis_followup_due_display=semis_followup_due_display or None,
            semis_followup_due_at=semis_followup_due_at,
            # `semis_cycles_remaining_today` est forcément un entier NON NUL ici : on n'entre dans
            # cette branche que si `(semis_cycles_remaining_today or 0) > 0` (cf. la condition du
            # `if` plus haut). Le vérificateur de types ne sait pas affiner à travers ce motif, d'où
            # la reformulation — même valeur, garde rendue lisible.
            semis_cycles_completed_today=max(0, daily_cycles_target - (semis_cycles_remaining_today or 0)),
            semis_cycles_remaining_today=semis_cycles_remaining_today,
            fractionnement={
                "enabled": False,
                "passages": 1,
                "pause_minutes": 0,
                "max_mm_per_passage": 0.0,
                "reason": "semis_cycle_pending",
            },
        )

    if sursemis_allowed and surface_cycle_mm > 0:
        objectif_mm = surface_cycle_mm
        type_arrosage = "manuel_frequent"
        conseil_principal = (
            f"Sursemis {watering_stage}: maintiens la surface humide avec une stratégie {watering_strategy}."
        )
        action_recommandee = (
            f"Appliquer {surface_cycle_mm:.1f} mm en cycle de surface, "
            f"avec objectif {daily_cycles_target} cycle(s)/jour et {cycle_spacing_minutes} min entre cycles."
        )
        action_a_eviter = "Lancer un gros cycle profond ou saturer le sol."
    else:
        objectif_mm = 0.0
        type_arrosage = "bloque" if sursemis_block_reason else "aucune_action"
        conseil_principal = sursemis_reason or "Sursemis: cycle de surface reporté."
        action_recommandee = "Surveille l'humidité et réévalue au prochain créneau."
        action_a_eviter = "Multiplier les petits cycles."

    confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
        phase_dominante=state["phase_dominante"],
        temperature=state["temperature"],
        humidite=state["humidite"],
        etp=state["etp"],
        weather_profile=state["context"].weather_profile,
        soil_profile=state["soil_style"],
        heat_stress_level=state["heat_stress_level"],
        heat_stress_phase=state["heat_stress_phase"],
        block_reason=sursemis_block_reason,
        mm_final=objectif_mm,
    )
    raison_decision_sursemis = (
        f"Sursemis / {state['sous_phase']}: stratégie semis_frequent en cycle de surface. "
        f"Surface cycle={surface_cycle_mm:.1f} mm, "
        f"objectif={daily_cycles_target} cycle(s)/jour, "
        f"espacement={cycle_spacing_minutes} min. "
        f"pluie_24h={state['pluie_24h']:.1f} mm, pluie_demain={state['pluie_demain']:.1f} mm, "
        f"pluie_probabilite_24h={pluie_probabilite_24h:.1f}%, bilan_hydrique_mm={state['bilan_hydrique_mm']:.1f} mm, "
        f"mm_detected_24h={mm_detected_24h:.1f} mm, temperature={state['temperature']:.1f}°C, "
        f"surface_sec={surface_sec}. "
        f"{sursemis_reason} "
        f"Seuil={sursemis_thresholds}. "
        f"{_hydric_summary_text(state['objectif_mm_brut'], state['deficit_mm_ajuste'], objectif_mm)}"
    )
    return _bundle_with(
        state["base_bundle"],
        objectif_mm=objectif_mm,
        mm_cible=objectif_mm,
        mm_final_recommande=objectif_mm,
        mm_final=objectif_mm,
        mm_requested=objectif_mm,
        mm_applied=objectif_mm,
        tonte_autorisee=False,
        tonte_statut="interdite",
        arrosage_auto_autorise=False,
        arrosage_recommande=objectif_mm > 0,
        type_arrosage=type_arrosage,
        arrosage_conseille="personnalise",
        conseil_principal=conseil_principal,
        action_recommandee=action_recommandee,
        action_a_eviter=action_a_eviter,
        raison_decision=raison_decision_sursemis,
        niveau_confiance=confidence_level,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        decision_resume=_decision_resume_payload(
            faire=objectif_mm > 0,
            action="arrosage" if objectif_mm > 0 else "aucune_action",
            moment=state["fenetre_optimale"] if objectif_mm > 0 else "attendre",
            objectif_mm=objectif_mm,
            type_arrosage=type_arrosage,
            niveau_action="a_faire" if objectif_mm > 0 else "surveiller",
            risque_gazon=state["risque_gazon"],
        ),
        niveau_action="a_faire" if objectif_mm > 0 else "surveiller",
        fenetre_optimale=state["fenetre_optimale"] if objectif_mm > 0 else "attendre",
        watering_passages=1,
        watering_pause_minutes=0,
        surface_sec=surface_sec,
        pluie_probabilite_24h=pluie_probabilite_24h,
        mm_detected_24h=mm_detected_24h,
        sursemis_micro_apport_allowed=sursemis_allowed,
        sursemis_block_reason=sursemis_block_reason,
        sursemis_reason=sursemis_reason,
        sursemis_seuil_declencheur=sursemis_thresholds,
        watering_strategy=watering_strategy,
        objective_scope=objective_scope,
        watering_stage=watering_stage,
        surface_cycle_mm=surface_cycle_mm,
        daily_cycles_target=daily_cycles_target,
        cycle_spacing_minutes=cycle_spacing_minutes,
        surface_moisture_target=surface_moisture_target,
        surface_dryness_risk=surface_dryness_risk,
        runoff_risk=runoff_risk,
        surface_saturation_level=state["water_bundle"].get("surface_saturation_level"),
        surface_saturation_limit=state["water_bundle"].get("surface_saturation_limit"),
        seeding_transition_ready=transition_ready,
        seeding_block_reason=sursemis_block_reason,
        fractionnement={
            "enabled": False,
            "passages": 1,
            "pause_minutes": 0,
            "max_mm_per_passage": round(objectif_mm, 1) if objectif_mm > 0 else 0.0,
            "reason": "semis_surface_cycle" if objectif_mm > 0 else "sursemis_aucune_action",
        },
    )


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
    # Le profil fait foi pour « soir » DANS LES DEUX SENS (cf. _resolve_optimal_window) : sans le
    # pont, le risk bundle (qui n'a pas le coucher du soleil) masquerait le cooling ; sans le sens
    # inverse, il imposerait « soir » à une recharge complète que le profil avait justement
    # reportée au matin. Deuxième copie de l'arbitrage — les deux doivent rester alignées.
    fenetre_optimale = _resolve_optimal_window(
        water_bundle.get("fenetre_optimale"), risk_bundle["fenetre_optimale"]
    )
    risque_gazon = risk_bundle["risque_gazon"]
    prochaine_reevaluation = risk_bundle["prochaine_reevaluation"]
    score_stress = mowing_bundle["score_stress"]
    tonte_reason = mowing_bundle["tonte_reason"]

    now_hour = context.hour_of_day if context.hour_of_day is not None else 0
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
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
    application_state = water_bundle.get("application_state") or compute_application_state(context.history, today=context.today)
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
    besoin_eau = (
        bilan_hydrique_mm <= -0.2
        or deficit_3j > 0.8
        or deficit_7j > 1.5
    )
    # Le rafraîchissement du soir est EXEMPTÉ du garde « besoin d'eau ». Son objet est de faire
    # baisser la température du gazon, pas de recharger la réserve : guidance.py l'autorise donc
    # explicitement réserve saine (découplage introduit en 0.14.0). Sans cette exemption, exiger
    # `besoin_eau` le ré-accouplait au déficit et ramenait les 3 mm de cooling à 0 précisément
    # dans le cas prévu — canicule après une semaine bien arrosée.
    recommande = objectif_mm > 0 and (besoin_eau or bool(water_bundle.get("evening_cooling")))
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
    base_bundle = _build_watering_bundle_base(
        water_bundle=water_bundle,
        phase_bundle=phase_bundle,
        risk_bundle=risk_bundle,
        mowing_bundle=mowing_bundle,
        mower_context=context.mower_context if isinstance(context.mower_context, dict) else {},
        application_payload=application_payload,
        watering_target_date=watering_target_date,
    )
    if phase_dominante != "Sursemis":
        _reset_semis_fields_for_non_sursemis(base_bundle)

    application_type_known = application_type in {APPLICATION_TYPE_SOL, APPLICATION_TYPE_FOLIAIRE}
    priority_state = {
        "base_bundle": base_bundle,
        "context": context,
        "phase_bundle": phase_bundle,
        "water_bundle": water_bundle,
        "phase_dominante": phase_dominante,
        "sous_phase": sous_phase,
        "soil_style": soil_style,
        "temperature": temperature,
        "humidite": humidite,
        "etp": etp,
        "stress_level": stress_level,
        "fenetre_optimale": fenetre_optimale,
        # Autorisation du soir : on prend la valeur du profil (qui reçoit le coucher du soleil
        # et fait le vrai test) si elle existe, sinon le risk bundle. Sans ça, le coordinateur
        # voyait False (risk bundle sans coucher) et bloquait le lancement du cooling.
        "watering_evening_allowed": bool(
            water_bundle.get("watering_evening_allowed")
            or risk_bundle.get("watering_evening_allowed")
        ),
        "fenetre_texte": fenetre_texte,
        "niveau_action": niveau_action,
        "risque_gazon": risque_gazon,
        "prochaine_reevaluation": prochaine_reevaluation,
        "objectif_mm": objectif_mm,
        "objectif_mm_brut": objectif_mm_brut,
        "deficit_mm_ajuste": deficit_mm_ajuste,
        "bilan_hydrique_mm": bilan_hydrique_mm,
        "pluie_24h": pluie_24h,
        "pluie_demain": pluie_demain,
        "heat_stress_level": heat_stress_level,
        "heat_stress_phase": heat_stress_phase,
        "application_summary": application_summary,
        "application_type_known": application_type_known,
        "application_label": application_label,
        "application_type": application_type,
        "application_mode": application_mode,
        "application_block_active": application_block_active,
        "application_block_remaining_minutes": application_block_remaining_minutes,
        "application_block_until": application_block_until,
        "application_requires_watering_after": application_requires_watering_after,
        "application_post_watering_pending": application_post_watering_pending,
        "application_post_watering_ready": application_post_watering_ready,
        "application_post_watering_delay_remaining_minutes": application_post_watering_delay_remaining_minutes,
        "application_post_watering_remaining_mm": application_post_watering_remaining_mm,
        "fertilization_allowed": fertilization_allowed,
    }
    for resolver in (
        _resolve_hivernage_override,
        _resolve_unknown_application_override,
        _resolve_application_block_override,
        _resolve_foliar_application_override,
        _resolve_pending_sol_application_override,
        _resolve_traitement_override,
        _resolve_fertilization_window_override,
        _resolve_sursemis_override,
    ):
        resolved = resolver(priority_state)
        if resolved is not None:
            return resolved

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
        type_arrosage = "bloque" if watering_blocked else "aucune_action"
        arrosage_recommande = False
        arrosage_auto_autorise = False
        arrosage_conseille = "personnalise" if watering_blocked else "aucune_action"
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
        type_arrosage = "auto" if auto_ok else "personnalise"
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
        type_arrosage = "auto" if auto_ok else "personnalise"
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
        type_arrosage = "auto" if auto_ok else "personnalise"
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
        type_arrosage = "auto" if auto_ok else "personnalise"
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

    rain_floor_block_reason: str | None = None
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
            normal_execution = get_watering_policy(phase_dominante).execution
            min_session_mm = (
                normal_execution.min_session_mm
                if normal_execution is not None and normal_execution.min_session_mm is not None
                else 5.0
            )
            # ⚠️ UNE PRÉVISION NE DÉCIDE PLUS POUR UN SOL QUI A DÉJÀ SOIF — même règle qu'en
            # amont (0.37.0), appliquée ici au SECOND étage, qui échappait au garde précédent.
            # Deux mécanismes distincts vivent dans ce bloc :
            #   · une RÉDUCTION de la dose (−60 % ou −20 %) ;
            #   · un BLOCAGE, quand la dose réduite passe sous la session minimale — il pose
            #     `rain_floor_block_reason = "pluie_prevue_suffisante"`, exactement le motif que
            #     la 0.37.0 croyait avoir neutralisé. Il ne venait pas d'ici, donc il subsistait.
            # Mesuré le 02/08/2026 à 22 h 40 : le profil calculait 12,0 mm (`besoin_mm: 12`,
            # `mm_final: 12` jusque dans `evening_cooling_debug`) et l'entité publiait **9,6** —
            # soit 12 × 0,8, la réduction déclenchée par 2,9 mm annoncés. Sur un sol à ZÉRO.
            # Arbitrage de Kévin : « la pluie prévue n'est jamais sûre, je préfère arroser ».
            # Contrepartie assumée : si la pluie tombe pour de vrai, on aura versé un peu trop —
            # l'excédent draine sous les racines. Le sol reste borné par sa capacité, jamais
            # au-delà. Seuil retenu : le MAD, le même que le déclenchement.
            try:
                _depletion_ratio_sol = float(water_balance.get("depletion_ratio") or 0.0)
            except (TypeError, ValueError):
                _depletion_ratio_sol = 0.0
            try:
                _mad_ratio_sol = float(water_balance.get("mad_ratio") or 0.5)
            except (TypeError, ValueError):
                _mad_ratio_sol = 0.5
            _sol_reclame_de_l_eau = _depletion_ratio_sol >= _mad_ratio_sol

            if pluie_compensatrice and not _sol_reclame_de_l_eau:
                reduction_mm = round(objectif_mm * 0.4, 1)
                conseil_principal = "Réduis ou reporte l'arrosage: la pluie de demain peut compenser une grande partie du déficit."
                if reduction_mm >= min_session_mm:
                    objectif_mm = min(objectif_mm, reduction_mm)
                    action_recommandee = f"Réduis l'apport à {reduction_mm:.1f} mm maximum."
                else:
                    objectif_mm = 0.0
                    arrosage_recommande = False
                    arrosage_auto_autorise = False
                    type_arrosage = "bloque"
                    arrosage_conseille = "personnalise"
                    rain_floor_block_reason = "pluie_prevue_suffisante"
                    action_recommandee = _watering_needed_text()
                mm_final = min(mm_final, objectif_mm)
                mm_final_recommande = min(mm_final_recommande, objectif_mm)
                action_a_eviter = "Lancer un cycle complet avant la pluie."
            elif (pluie_demain >= 2.0 or pluie_j2 >= 4.0 or pluie_3j >= 4.0) and not _sol_reclame_de_l_eau:
                # On ne réduit l'arrosage que pour une pluie prévue SIGNIFICATIVE. Une
                # averse de trace (ex. 0,8 mm à J+2) ne doit pas réduire/annuler l'arrosage
                # d'un sol sec : sinon, quand l'objectif réduit passe sous la dose mini, on
                # bloquait tout à tort (« pluie prévue suffisante ») en pleine canicule.
                reduction_mm = round(objectif_mm * 0.8, 1)
                conseil_principal = "Réduis l'arrosage: la pluie annoncée peut déjà compenser une partie du besoin."
                if reduction_mm >= min_session_mm:
                    objectif_mm = min(objectif_mm, reduction_mm)
                    action_recommandee = f"Réduis l'apport à {reduction_mm:.1f} mm maximum."
                else:
                    objectif_mm = 0.0
                    arrosage_recommande = False
                    arrosage_auto_autorise = False
                    type_arrosage = "bloque"
                    arrosage_conseille = "personnalise"
                    rain_floor_block_reason = "pluie_prevue_suffisante"
                    action_recommandee = _watering_needed_text()
                mm_final = min(mm_final, objectif_mm)
                mm_final_recommande = min(mm_final_recommande, objectif_mm)
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
        if water_bundle.get("evening_cooling"):
            # Rafraîchissement du soir : dose légère (~3 mm) pour un relief RAPIDE → un SEUL passage,
            # sans pause. Pas de fractionnement anti-ruissellement (inutile pour si peu d'eau), sinon
            # le cooling s'étalerait sur ~1 h au lieu de finir vite après le coucher.
            watering_passages = 1
            watering_pause_minutes = 0
        elif phase_dominante == "Normal":
            # Phase Normal = arrosage profond adulte : les passages sont déjà calibrés par
            # guidance.py pour les grands volumes (anti-ruissellement adapté, pas la logique
            # petites-doses de _soil_fractionation_passages qui plafonne à 1.5 mm/passage en
            # canicule et donne 3 passages de 4 mm → le sol re-sèche entre les passages).
            watering_passages = max(1, int(water_bundle.get("watering_passages") or 1))
            watering_pause_minutes = 25 if watering_passages > 1 else 0
        else:
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

    decision_resume = _decision_resume_payload(
        faire=arrosage_recommande,
        action="arrosage" if arrosage_recommande else "aucune_action",
        moment=fenetre_optimale,
        objectif_mm=objectif_mm,
        type_arrosage=type_arrosage,
        niveau_action=niveau_action,
        risque_gazon=risque_gazon,
    )

    weekly_guardrail_min = float(water_bundle.get("weekly_guardrail_mm_min") or 20.0)
    weekly_guardrail_max = float(water_bundle.get("weekly_guardrail_mm_max") or 25.0)
    heat_stress_phase_value = water_bundle.get("heat_stress_phase")
    soil_profile_value = water_bundle.get("soil_profile")
    confidence_score_value = water_bundle.get("confidence_score")
    block_reason_value = rain_floor_block_reason or water_bundle.get("block_reason")
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
            "Mode Normal: arrosage profond et rare, déclenché sur déficit utile, "
            f"garde-fou hebdomadaire dynamique {weekly_guardrail_min:.1f} à {weekly_guardrail_max:.1f} mm sur 7 jours glissants."
        )
    elif phase_dominante == "Sursemis":
        raison_parts.append("Sursemis: micro-apports légers et fréquents, jamais d'auto standard.")
    if heat_stress_level != "normal":
        raison_parts.append(f"Stress hydrique={heat_stress_level}; matin renforcé, soirée plus restrictive.")
    if heat_stress_phase_value not in (None, "normal"):
        # Durée de l'épisode de stress (distinct du niveau ci-dessus). Libellé honnête : la clé
        # interne "stress_court/prolonge" décrit surtout la DURÉE, pas une vraie canicule.
        _duree_stress = {
            "stress_court": "courte",
            "stress_prolonge": "prolongée",
            "sortie_de_stress": "en sortie",
        }.get(str(heat_stress_phase_value), str(heat_stress_phase_value))
        raison_parts.append(f"Durée du stress: {_duree_stress}")
    reserve_available_ratio = float(water_balance.get("reserve_available_ratio") or 0.0)
    if arrosage_recommande and reserve_available_ratio >= 1.0:
        raison_parts.append(
            "Réserve utile pleine mais ETP élevée: arrosage anticipatif pour couvrir les pertes à venir."
        )
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
    elif block_reason_value == "temperature_trop_basse":
        raison_parts.append("Température trop basse: l'arrosage est différé.")
        raison_parts.append("Motif exact: temperature_trop_basse.")
    elif block_reason_value == "pluie_prevue_suffisante":
        raison_parts.append("Pluie prévue suffisante: l'arrosage est reporté.")
        raison_parts.append("Motif exact: pluie_prevue_suffisante.")
    elif block_reason_value == "sol_non_adapte":
        raison_parts.append("Sol non adapté: l'état du sol ne permet pas un arrosage cohérent.")
        raison_parts.append("Motif exact: sol_non_adapte.")
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
        "block_reason": rain_floor_block_reason or water_bundle.get("block_reason"),
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

    return _bundle_with(
        base_bundle,
        objectif_mm=objectif_mm,
        objectif_mm_brut=objectif_mm_brut,
        deficit_brut_mm=deficit_mm_brut,
        deficit_mm_brut=deficit_mm_brut,
        deficit_mm_ajuste=deficit_mm_ajuste,
        mm_cible=mm_cible,
        mm_final_recommande=mm_final_recommande,
        mm_final=mm_final,
        mm_requested=water_bundle.get("mm_requested", mm_cible),
        mm_applied=round(mm_final, 1),
        mm_detected=water_bundle.get("mm_detected"),
        conseil_principal=conseil_principal,
        action_recommandee=action_recommandee,
        action_a_eviter=action_a_eviter,
        arrosage_recommande=arrosage_recommande,
        arrosage_auto_autorise=arrosage_auto_autorise,
        type_arrosage=type_arrosage,
        arrosage_conseille=arrosage_conseille,
        fractionnement=fractionnement,
        niveau_confiance=niveau_confiance,
        confidence_score=water_bundle.get("confidence_score"),
        confidence_reasons=water_bundle.get("confidence_reasons"),
        heat_stress_level=heat_stress_level,
        heat_stress_phase=water_bundle.get("heat_stress_phase"),
        decision_resume=decision_resume,
        block_reason=rain_floor_block_reason or water_bundle.get("block_reason"),
        raison_decision=" ".join(raison_parts),
        niveau_action=niveau_action,
        fenetre_optimale=fenetre_optimale,
        risque_gazon=risque_gazon,
        prochaine_reevaluation=prochaine_reevaluation,
        tonte_autorisee=mowing_bundle["tonte_autorisee"],
        tonte_statut=mowing_bundle["tonte_statut"],
        watering_passages=watering_passages,
        watering_pause_minutes=watering_pause_minutes,
        watering_target_date=watering_target_date,
        watering_window_start_minute=watering_window_start_minute,
        watering_window_end_minute=watering_window_end_minute,
        watering_window_optimal_start_minute=watering_window_optimal_start_minute,
        watering_window_optimal_end_minute=watering_window_optimal_end_minute,
        watering_window_acceptable_end_minute=watering_window_acceptable_end_minute,
    )
