from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Règles agronomiques soutenues par les sources:
# - arroser tôt le matin;
# - pour les semis / sursemis, garder la surface humide sans saturation;
# - réduire la fréquence à mesure que l'enracinement progresse.
#
# Conventions internes de l'intégration:
# - bornes horaires concrètes pour décider "maintenant" vs "demain matin";
# - seuils de bascule pour le moteur Home Assistant.
SURSEMIS_MORNING_START_HOUR = 6
SURSEMIS_MORNING_END_HOUR = 10
GENERAL_MORNING_START_HOUR = 5
GENERAL_MORNING_END_HOUR = 10
EVENING_START_HOUR = 18
EVENING_END_HOUR = 21


def _temperature_band(temperature: float | None) -> str:
    temperature = temperature if temperature is not None else 0.0
    if temperature < 10:
        return "cool"
    if temperature > 22:
        return "hot"
    return "mild"


def _morning_window_bounds(phase_dominante: str, temperature: float | None) -> tuple[int, int, str]:
    band = _temperature_band(temperature)
    if phase_dominante == "Sursemis":
        if band == "cool":
            return 330, 600, band
        if band == "hot":
            return 360, 540, band
        return 360, 570, band

    if band == "cool":
        return 300, 600, band
    if band == "hot":
        return 330, 540, band
    return 330, 570, band


def _evening_window_allowed(
    temperature: float | None,
    humidite: float | None,
    water_balance: dict[str, float],
    objectif_mm: float,
) -> bool:
    temperature = temperature if temperature is not None else 0.0
    humidite = humidite if humidite is not None else 0.0
    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)

    if temperature < 24:
        return False
    if humidite > 65:
        return False
    if arrosage_recent > 0.25:
        return False
    if bilan_hydrique_mm >= -0.3 and deficit_3j <= 0.8:
        return False
    return objectif_mm > 0


def _risk_rank(level: str) -> int:
    return {"faible": 0, "modere": 1, "eleve": 2}.get(level, 0)


def _risk_from_rank(rank: int) -> str:
    return {0: "faible", 1: "modere", 2: "eleve"}.get(max(0, min(rank, 2)), "faible")


def compute_objectif_mm(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    today: date | None = None,
    pluie_demain: float | None = None,
    humidite: float | None = None,
    temperature: float | None = None,
    etp: float | None = None,
    type_sol: str = "limoneux",
) -> float:
    today = today or date.today()
    if phase_dominante in ("Traitement", "Hivernage"):
        return 0.0

    pluie_demain = pluie_demain or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    soil_profile = (type_sol or "limoneux").strip().lower()

    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    besoin_court = max(0.0, -bilan_hydrique_mm)
    besoin_tendance = (deficit_3j * 0.18) + (deficit_7j * 0.06)

    if phase_dominante != "Sursemis" and bilan_hydrique_mm >= 1.2:
        return 0.0
    if pluie_demain >= 2.0 and bilan_hydrique_mm >= -0.5:
        return 0.0

    if phase_dominante == "Sursemis":
        if sous_phase == "Germination":
            objectif = (besoin_court * 0.5) + (besoin_tendance * 0.1)
            if humidite >= 85 and temperature < 28:
                objectif *= 0.9
            minimum, maximum = 0.6, 1.8
        elif sous_phase == "Enracinement":
            objectif = (besoin_court * 0.45) + (besoin_tendance * 0.08)
            minimum, maximum = 0.5, 2.1
        else:
            objectif = (besoin_court * 0.7) + (besoin_tendance * 0.12)
            minimum, maximum = 0.5, 2.5
    elif phase_dominante == "Scarification":
        objectif = (besoin_court * 0.6) + (besoin_tendance * 0.10)
        minimum, maximum = 0.0, 2.5
    elif phase_dominante in {"Fertilisation", "Biostimulant"}:
        objectif = (besoin_court * 0.4) + (besoin_tendance * 0.08)
        minimum, maximum = 0.0, 1.8
    elif phase_dominante == "Agent Mouillant":
        objectif = (besoin_court * 0.55) + (besoin_tendance * 0.10)
        minimum, maximum = 0.0, 2.8
    else:
        objectif = (besoin_court * 0.85) + (besoin_tendance * 0.12)
        minimum, maximum = 0.0, 5.0

    if phase_dominante in {"Fertilisation", "Biostimulant"} and not is_fertilization_window_open(
        today=today,
        temperature=temperature,
        humidite=humidite,
        etp=etp,
        water_balance=water_balance,
    ):
        return 0.0

    if phase_dominante not in {"Traitement", "Hivernage"}:
        soil_factor = {"sableux": 1.08, "limoneux": 1.0, "argileux": 0.92}.get(soil_profile, 1.0)
        objectif *= soil_factor

    if temperature >= 30 and etp >= 4:
        objectif += 0.4
    if humidite >= 85 and phase_dominante == "Normal":
        objectif *= 0.75
    if humidite >= 90 and phase_dominante != "Sursemis":
        objectif *= 0.8

    if bilan_hydrique_mm > 0.5 and phase_dominante == "Normal":
        return 0.0
    if phase_dominante == "Normal" and objectif < 1.2:
        return 0.0

    objectif = max(minimum, min(maximum, objectif))
    return round(max(0.0, objectif), 1)


def is_fertilization_window_open(
    today: date,
    temperature: float | None,
    humidite: float | None,
    etp: float | None,
    water_balance: dict[str, float] | None = None,
) -> bool:
    """Indique si la fertilisation peut raisonnablement être activée."""
    water_balance = water_balance or {}
    temperature = temperature or 0.0
    humidite = humidite or 0.0
    etp = etp or 0.0
    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    mois = today.month

    if mois in {12, 1, 2}:
        return False
    if temperature >= 31 or etp >= 4.5 or humidite <= 35:
        return False
    if bilan_hydrique_mm <= -2.0:
        return False
    if mois in {6, 7, 8}:
        return temperature < 27 and etp < 4.0 and humidite >= 40 and bilan_hydrique_mm >= -1.0
    return mois in {3, 4, 5, 9, 10, 11}


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
    hour_of_day: int | None = None,
) -> dict[str, str]:
    advanced_context = advanced_context or {}
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)

    besoin_court = max(0.0, -bilan_hydrique_mm)
    besoin_tendance = (deficit_3j * 0.18) + (deficit_7j * 0.06)
    pression_hydrique = besoin_court + besoin_tendance
    pluie_compensatrice = objectif_mm > 0 and pluie_demain >= max(2.0, objectif_mm * 0.8)
    pluie_proche = pluie_24h >= 4 or pluie_demain >= 4
    now_hour = hour_of_day if hour_of_day is not None else datetime.now().hour
    now_minutes = now_hour * 60 + int(datetime.now().minute if hour_of_day is None else 0)
    vent = advanced_context.get("vent")
    rosee = advanced_context.get("rosee")
    hauteur_gazon = advanced_context.get("hauteur_gazon")
    morning_start_minute, morning_end_minute, temperature_band = _morning_window_bounds(
        phase_dominante=phase_dominante,
        temperature=temperature,
    )
    evening_allowed = _evening_window_allowed(
        temperature=temperature,
        humidite=humidite,
        water_balance=water_balance,
        objectif_mm=objectif_mm,
    )

    if phase_dominante in {"Traitement", "Hivernage"}:
        return {
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": "faible",
            "watering_window_start_minute": morning_start_minute,
            "watering_window_end_minute": morning_end_minute,
            "watering_evening_start_minute": EVENING_START_HOUR * 60,
            "watering_evening_end_minute": EVENING_END_HOUR * 60,
            "watering_window_profile": temperature_band,
            "watering_evening_allowed": False,
        }

    if objectif_mm <= 0:
        fenetre_optimale = "attendre"
        if pluie_proche:
            fenetre_optimale = "apres_pluie"
        return {
            "niveau_action": "aucune_action" if phase_dominante == "Normal" else "surveiller",
            "fenetre_optimale": fenetre_optimale,
            "risque_gazon": "faible" if phase_dominante == "Normal" else "modere",
            "watering_window_start_minute": morning_start_minute,
            "watering_window_end_minute": morning_end_minute,
            "watering_evening_start_minute": EVENING_START_HOUR * 60,
            "watering_evening_end_minute": EVENING_END_HOUR * 60,
            "watering_window_profile": temperature_band,
            "watering_evening_allowed": evening_allowed,
        }

    if phase_dominante == "Sursemis":
        niveau_action = "critique" if pression_hydrique >= 2.2 or bilan_hydrique_mm <= -1.5 else "a_faire"
        if pluie_compensatrice or pluie_proche:
            fenetre_optimale = "apres_pluie"
        elif morning_start_minute <= now_minutes < morning_end_minute and (vent is None or vent < 15):
            fenetre_optimale = "maintenant"
        else:
            fenetre_optimale = "demain_matin"
        risque_gazon = "eleve" if bilan_hydrique_mm <= -1.5 or pression_hydrique >= 2.5 else "modere"
        if vent is not None and vent >= 20:
            risque_gazon = "eleve"
        if hauteur_gazon is not None and hauteur_gazon >= 12:
            risque_gazon = "eleve"
        return {
            "niveau_action": niveau_action,
            "fenetre_optimale": fenetre_optimale,
            "risque_gazon": risque_gazon,
            "watering_window_start_minute": morning_start_minute,
            "watering_window_end_minute": morning_end_minute,
            "watering_evening_start_minute": EVENING_START_HOUR * 60,
            "watering_evening_end_minute": EVENING_END_HOUR * 60,
            "watering_window_profile": temperature_band,
            "watering_evening_allowed": False,
        }

    if evening_allowed and now_hour >= EVENING_START_HOUR:
        fenetre_optimale = "soir"
        niveau_action = "a_faire"
    elif pluie_compensatrice:
        fenetre_optimale = "apres_pluie"
        niveau_action = "surveiller"
    elif humidite >= 85 and bilan_hydrique_mm >= -0.5:
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
    elif bilan_hydrique_mm <= -4.0:
        fenetre_optimale = "maintenant" if now_hour < GENERAL_MORNING_END_HOUR - 1 else "demain_matin"
        niveau_action = "critique"
    elif bilan_hydrique_mm <= -0.8 or pression_hydrique >= 1.5:
        fenetre_optimale = "maintenant" if now_hour < GENERAL_MORNING_END_HOUR else "demain_matin"
        niveau_action = "a_faire"
    elif morning_start_minute <= now_minutes < morning_end_minute:
        fenetre_optimale = "maintenant"
        niveau_action = "a_faire"
    else:
        fenetre_optimale = "demain_matin"
        niveau_action = "a_faire"

    if bilan_hydrique_mm <= -2.5:
        risque_gazon = "eleve"
    elif bilan_hydrique_mm <= -0.8 or pression_hydrique >= 1.2:
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
        "watering_window_start_minute": morning_start_minute,
        "watering_window_end_minute": morning_end_minute,
        "watering_evening_start_minute": EVENING_START_HOUR * 60,
        "watering_evening_end_minute": EVENING_END_HOUR * 60,
        "watering_window_profile": temperature_band,
        "watering_evening_allowed": evening_allowed,
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


def compute_legacy_urgence(
    phase_dominante: str,
    arrosage_recommande: bool,
    niveau_action: str,
    risque_gazon: str,
    score_hydrique: int,
    score_stress: int,
) -> str:
    """Retourne l'ancien niveau d'urgence pour compatibilité Home Assistant."""
    if phase_dominante in {"Traitement", "Hivernage"}:
        return "faible"
    if not arrosage_recommande:
        return "faible"
    if phase_dominante == "Sursemis":
        if niveau_action == "critique" or risque_gazon == "eleve" or score_hydrique >= 45:
            return "haute"
        return "moyenne"
    if niveau_action == "critique" or score_hydrique >= 75 or score_stress >= 80 or risque_gazon == "eleve":
        return "haute"
    if niveau_action in {"a_faire", "surveiller"} or score_hydrique >= 40 or score_stress >= 55 or risque_gazon == "modere":
        return "moyenne"
    return "faible"
