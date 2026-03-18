from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _risk_rank(level: str) -> int:
    return {"faible": 0, "modere": 1, "eleve": 2}.get(level, 0)


def _risk_from_rank(rank: int) -> str:
    return {0: "faible", 1: "modere", 2: "eleve"}.get(max(0, min(rank, 2)), "faible")


def compute_objectif_mm(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    score_hydrique: int,
    score_stress: int,
) -> float:
    if phase_dominante in ("Traitement", "Hivernage"):
        return 0.0

    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)

    if phase_dominante == "Sursemis":
        base_mm = (deficit_jour * 0.95) + (deficit_3j * 0.12)
    elif phase_dominante == "Scarification":
        base_mm = (deficit_jour * 0.7) + (deficit_3j * 0.15)
    elif phase_dominante == "Fertilisation":
        base_mm = (deficit_jour * 0.65) + (deficit_3j * 0.12)
    elif phase_dominante == "Biostimulant":
        base_mm = (deficit_jour * 0.6) + (deficit_3j * 0.1)
    elif phase_dominante == "Agent Mouillant":
        base_mm = (deficit_jour * 0.75) + (deficit_3j * 0.1)
    else:
        base_mm = (deficit_jour * 0.55) + (deficit_3j * 0.25) + (deficit_7j * 0.08)

    if score_hydrique < 15:
        base_mm *= 0.25

    profile = {
        "Normal": (1.00, 0.0, 12.0),
        "Sursemis": (0.65, 0.5, 3.0),
        "Fertilisation": (0.80, 0.5, 3.5),
        "Biostimulant": (0.72, 0.4, 3.0),
        "Agent Mouillant": (0.88, 0.8, 4.0),
        "Scarification": (0.82, 0.6, 3.5),
    }.get(phase_dominante, (1.00, 0.0, 12.0))

    mult, min_mm, max_mm = profile
    objectif = base_mm * mult
    if phase_dominante == "Sursemis" and sous_phase == "Germination":
        max_mm = min(max_mm, 2.0)
    elif phase_dominante == "Sursemis" and sous_phase == "Enracinement":
        max_mm = min(max_mm, 2.5)
    elif phase_dominante == "Sursemis":
        max_mm = min(max_mm, 3.0)
    if score_hydrique < 20 and score_stress < 35:
        min_mm = 0.0
    objectif = max(min_mm, min(max_mm, objectif))
    return round(max(0.0, objectif), 1)


def compute_jours_restants_for(
    phase_dominante: str,
    date_fin: date | None,
    today: date | None = None,
) -> int:
    today = today or date.today()
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
    humidite: float | None,
    temperature: float | None,
    etp: float | None,
    objectif_mm: float,
    score_hydrique: int,
    score_stress: int,
    score_tonte: int,
    hour_of_day: int | None = None,
) -> dict[str, str]:
    advanced_context = advanced_context or {}
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0

    pressure = max(score_hydrique, score_stress, score_tonte)
    pluie_compensatrice = objectif_mm > 0 and pluie_demain >= max(2.0, objectif_mm * 0.8)
    pluie_proche = pluie_24h >= 4 or pluie_demain >= 4
    now_hour = hour_of_day if hour_of_day is not None else datetime.now().hour
    vent = advanced_context.get("vent")
    rosee = advanced_context.get("rosee")
    hauteur_gazon = advanced_context.get("hauteur_gazon")
    rain_source = advanced_context.get("pluie_source")

    if phase_dominante in {"Traitement", "Hivernage"}:
        return {
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": "faible",
        }

    if objectif_mm <= 0:
        fenetre_optimale = "attendre"
        if rosee is not None and rosee > 0:
            fenetre_optimale = "attendre"
        if vent is not None and vent >= 20:
            fenetre_optimale = "attendre"
        return {
            "niveau_action": "aucune_action" if phase_dominante == "Normal" else "surveiller",
            "fenetre_optimale": fenetre_optimale,
            "risque_gazon": "faible" if phase_dominante == "Normal" else "modere",
        }

    if phase_dominante == "Sursemis":
        niveau_action = "critique" if pressure >= 70 or score_hydrique >= 55 else "a_faire"
        if pluie_compensatrice or pluie_proche:
            fenetre_optimale = "apres_pluie"
        elif now_hour < 9:
            fenetre_optimale = "maintenant"
        else:
            fenetre_optimale = "demain_matin"
        if rain_source == "capteur_pluie_fine" and pluie_24h > 0:
            fenetre_optimale = "apres_pluie" if pluie_compensatrice else fenetre_optimale
        risque_gazon = "eleve" if pressure >= 70 or score_hydrique >= 55 or score_stress >= 70 else "modere"
        if vent is not None and vent >= 20:
            risque_gazon = "eleve"
        if hauteur_gazon is not None and hauteur_gazon >= 12:
            risque_gazon = "eleve"
        return {
            "niveau_action": niveau_action,
            "fenetre_optimale": fenetre_optimale,
            "risque_gazon": risque_gazon,
        }

    if pluie_compensatrice:
        fenetre_optimale = "apres_pluie"
        niveau_action = "surveiller"
    elif humidite >= 85:
        fenetre_optimale = "attendre"
        niveau_action = "surveiller"
    elif temperature >= 30 and etp >= 4:
        fenetre_optimale = "demain_matin"
        niveau_action = "a_faire"
    elif vent is not None and vent >= 20:
        fenetre_optimale = "demain_matin"
        niveau_action = "a_faire"
    elif rosee is not None and rosee > 0:
        fenetre_optimale = "attendre"
        niveau_action = "surveiller"
    elif now_hour < 9:
        fenetre_optimale = "maintenant"
        niveau_action = "a_faire"
    else:
        fenetre_optimale = "demain_matin"
        niveau_action = "a_faire"

    if pressure >= 75 or score_hydrique >= 60 or score_stress >= 75:
        risque_gazon = "eleve"
    elif pressure >= 40 or score_hydrique >= 35 or score_stress >= 50:
        risque_gazon = "modere"
    else:
        risque_gazon = "faible"
    if vent is not None and vent >= 20:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
    if hauteur_gazon is not None and hauteur_gazon >= 12:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))

    return {
        "niveau_action": niveau_action,
        "fenetre_optimale": fenetre_optimale,
        "risque_gazon": risque_gazon,
    }


def compute_next_reevaluation(
    phase_dominante: str,
    niveau_action: str,
    fenetre_optimale: str,
    risque_gazon: str,
    pluie_demain: float | None = None,
) -> str:
    pluie_demain = pluie_demain or 0.0

    if fenetre_optimale == "apres_pluie" and pluie_demain > 0:
        return "apres_pluie"
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
