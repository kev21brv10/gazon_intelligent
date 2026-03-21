from __future__ import annotations

"""Logique pure d'arrosage et de recommandations utilisateur."""

from math import ceil
from datetime import date, timedelta
from typing import Any

from .const import (
    APPLICATION_TYPE_FOLIAIRE,
    APPLICATION_TYPE_SOL,
    DEFAULT_AUTO_IRRIGATION_ENABLED,
)
from .decision_models import DecisionContext
from .guidance import compute_objectif_mm, is_fertilization_window_open
from .memory import compute_application_state
from .scores import classify_stress_level
from .water import compute_advanced_context, compute_etp, compute_water_balance


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
    objective_mm = compute_objectif_mm(
        phase_dominante=phase_bundle["phase_dominante"],
        sous_phase=phase_bundle["sous_phase"],
        water_balance=balance_snapshot,
        today=context.today,
        pluie_demain=context.pluie_demain,
        humidite=context.humidite,
        temperature=context.temperature,
        etp=etp,
        type_sol=context.type_sol,
    )
    return {
        "etp": etp,
        "advanced_context": advanced_context,
        "water_balance": balance_snapshot,
        "objectif_mm": objective_mm,
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
    soil_profile = (type_sol or "limoneux").strip().lower()
    if passages <= 1:
        if soil_profile == "sableux":
            return "en un passage profond tôt le matin"
        return "en un passage profond tôt le matin"
    if passages == 2:
        return "en 2 passages courts espacés de 20 à 30 min"
    return "en 3 passages courts espacés de 20 à 30 min"


def _watering_amount_text(mm: float) -> str:
    if mm <= 0:
        return "Aucun arrosage nécessaire."
    return f"{mm:.1f} mm"


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
    objectif_mm_brut = water_bundle["objectif_mm"]
    objectif_mm = objectif_mm_brut
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
            "raison_decision": "Hivernage actif: repos végétatif.",
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
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
            "raison_decision": "Type d'application inconnu: sécurité renforcée, aucun arrosage automatique.",
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
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
                f"Temps restant={application_block_remaining_minutes:.0f} min."
            ),
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
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
                f"mode={application_mode or 'suggestion'}."
            ),
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
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
                    f"mode={application_mode or 'auto'}."
                ),
                "decision_resume": {
                    "faire": False,
                    "action": "surveillance",
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
                    f"mode=suggestion."
                ),
                "decision_resume": {
                    "faire": False,
                    "action": "surveillance",
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
                f"fenêtre={fenetre_texte}, bilan={bilan_hydrique_mm:.1f} mm, mode={application_mode or 'auto'}."
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
            "raison_decision": "Traitement actif: tonte et arrosage bloqués.",
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
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
                f"stress={stress_level}, température={temperature:.1f}°C, ETP={etp:.1f} mm."
            ),
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
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
        passage_spacing = _passage_spacing_text(passages)
        if objectif_mm <= 0:
            conseil_principal = "Aucun arrosage nécessaire pour le sursemis."
            action_recommandee = "Surveille l'humidité et réévalue au prochain créneau."
            action_a_eviter = _watering_needed_text()
            return {
                "objectif_mm": 0.0,
                "objectif_mm_brut": objectif_mm_brut,
                "tonte_autorisee": False,
                "tonte_statut": "interdite",
                "arrosage_auto_autorise": False,
                "arrosage_recommande": False,
                "type_arrosage": "personnalise",
                "arrosage_conseille": "personnalise",
                "conseil_principal": conseil_principal,
                "action_recommandee": action_recommandee,
                "action_a_eviter": action_a_eviter,
                "raison_decision": (
                    f"Sursemis / {sous_phase}: objectif nul, bilan={bilan_hydrique_mm:.1f} mm, "
                    f"tendance 3j={bilan_hydrique_3j:.1f} mm, 7j={bilan_hydrique_7j:.1f} mm."
                ),
                "decision_resume": {
                    "faire": False,
                    "action": "surveillance",
                    "moment": "attendre",
                    "objectif_mm": objectif_mm,
                    "type_arrosage": "personnalise",
                    "niveau_action": "surveiller",
                    "risque_gazon": risque_gazon,
                },
                "niveau_action": "surveiller",
                "fenetre_optimale": "attendre",
                "risque_gazon": risque_gazon,
                "prochaine_reevaluation": prochaine_reevaluation,
                "tonte_autorisee": False,
                "tonte_statut": "interdite",
                "watering_passages": watering_passages,
                "watering_pause_minutes": watering_pause_minutes,
                "watering_target_date": watering_target_date,
                **application_payload,
            }
        if pluie_demain >= 2 and bilan_hydrique_mm >= -0.5:
            conseil_principal = "Réduis ou reporte l'arrosage: la pluie de demain peut compenser une grande partie du déficit."
            reduction_mm = round(objectif_mm * 0.4, 1)
            if reduction_mm >= 0.5:
                objectif_mm = reduction_mm
                action_recommandee = f"Réduis l'apport à {objectif_mm:.1f} mm maximum."
            else:
                objectif_mm = 0.0
                arrosage_recommande = False
                arrosage_auto_autorise = False
                type_arrosage = "personnalise"
                arrosage_conseille = "personnalise"
                action_recommandee = _watering_needed_text()
            action_a_eviter = "Lancer un cycle complet avant la pluie."
        elif humidite_haute:
            conseil_principal = "Attends un léger ressuyage avant d'arroser."
            objectif_mm = 0.0
            arrosage_recommande = False
            arrosage_auto_autorise = False
            type_arrosage = "personnalise"
            arrosage_conseille = "personnalise"
            action_recommandee = "Reporte l'arrosage au prochain créneau sec."
            action_a_eviter = "Arroser immédiatement sur pelouse saturée."
        else:
            conseil_principal = f"Arroser {fenetre_texte} {passage_spacing}."
            if passages <= 1:
                action_recommandee = f"Appliquer {objectif_mm:.1f} mm en un passage."
            else:
                action_recommandee = f"Appliquer {objectif_mm:.1f} mm fractionnés ({passages}x, 20 à 30 min entre les passages)."
            action_a_eviter = "Tondre avant levée complète."
        return {
            "objectif_mm": objectif_mm,
            "objectif_mm_brut": objectif_mm_brut,
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": objectif_mm > 0,
            "type_arrosage": "manuel_frequent",
            "arrosage_conseille": "personnalise",
            "conseil_principal": conseil_principal,
            "action_recommandee": action_recommandee,
            "action_a_eviter": action_a_eviter,
            "raison_decision": (
                f"Sursemis / {sous_phase}: bilan={bilan_hydrique_mm:.1f} mm, tendance 3j={bilan_hydrique_3j:.1f} mm, 7j={bilan_hydrique_7j:.1f} mm. "
                f"Pluie efficace={pluie_efficace:.1f} mm."
            ),
            "decision_resume": {
                "faire": objectif_mm > 0,
                "action": "arrosage",
                "moment": fenetre_optimale,
                "objectif_mm": objectif_mm,
                "type_arrosage": "manuel_frequent",
                "niveau_action": niveau_action,
                "risque_gazon": risque_gazon,
            },
            "watering_passages": passages,
            "watering_pause_minutes": _watering_pause_minutes(passages),
            "watering_target_date": watering_target_date,
            **application_payload,
        }

    if not recommande:
        conseil_principal = f"Phase {phase_dominante}: n'arrose pas pour l'instant."
        action_recommandee = "Surveille les capteurs et l'évolution météo."
        action_a_eviter = "Éviter tout arrosage inutile."
        objectif_mm = 0.0
        type_arrosage = "personnalise"
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
        "action": "arrosage" if arrosage_recommande else ("aucune_action" if mowing_bundle["tonte_autorisee"] else "surveillance"),
        "moment": fenetre_optimale,
        "objectif_mm": objectif_mm,
        "type_arrosage": type_arrosage,
        "niveau_action": niveau_action,
        "risque_gazon": risque_gazon,
    }

    raison_parts = [
        f"Mode {phase_dominante} / {sous_phase} en cours ({phase_bundle['jours_restants']} jour(s) restants).",
        f"Bilan hydrique={bilan_hydrique_mm:.1f} mm, tendance 3j={bilan_hydrique_3j:.1f} mm, 7j={bilan_hydrique_7j:.1f} mm.",
        f"Pluie efficace={pluie_efficace:.1f} mm.",
    ]
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
    raison_parts.append(tonte_reason)

    return {
        "objectif_mm": objectif_mm,
        "objectif_mm_brut": objectif_mm_brut,
        "conseil_principal": conseil_principal,
        "action_recommandee": action_recommandee,
        "action_a_eviter": action_a_eviter,
        "arrosage_recommande": arrosage_recommande,
        "arrosage_auto_autorise": arrosage_auto_autorise,
        "type_arrosage": type_arrosage,
        "arrosage_conseille": arrosage_conseille,
        "decision_resume": decision_resume,
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
        **application_payload,
    }
