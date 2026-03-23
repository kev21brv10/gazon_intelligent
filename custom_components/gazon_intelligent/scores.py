from __future__ import annotations

from datetime import date
from typing import Any


def classify_stress_level(
    score_hydrique: int,
    score_stress: int,
    water_balance: dict[str, float] | None = None,
    temperature: float | None = None,
    etp: float | None = None,
) -> str:
    """Classe le stress en niveau lisible pour piloter les garde-fous."""
    water_balance = water_balance or {}
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    temperature = temperature or 0.0
    etp = etp or 0.0

    if (
        score_stress >= 75
        or score_hydrique >= 80
        or deficit_jour >= 3.0
        or deficit_7j >= 7.0
        or (temperature >= 34 and etp >= 5)
    ):
        return "fort"
    if (
        score_stress >= 45
        or score_hydrique >= 50
        or deficit_jour >= 1.5
        or deficit_3j >= 2.5
        or deficit_7j >= 3.5
        or temperature >= 30
        or etp >= 4
    ):
        return "modere"
    return "leger"


def compute_internal_scores(
    history: list[dict[str, Any]],
    today: date | None,
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    advanced_context: dict[str, Any] | None,
    pluie_24h: float | None,
    pluie_demain: float | None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
    humidite: float | None = None,
    temperature: float | None = None,
    etp: float | None = None,
) -> dict[str, int]:
    today = today or date.today()
    advanced_context = advanced_context or {}
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    pluie_efficace = water_balance.get("pluie_efficace", 0.0)
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    humidite_sol = advanced_context.get("humidite_sol")
    vent = advanced_context.get("vent")
    rosee = advanced_context.get("rosee")
    hauteur_gazon = advanced_context.get("hauteur_gazon")
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0

    score_hydrique = (deficit_jour * 8.0) + (deficit_3j * 3.0) + (deficit_7j * 1.2)
    if pluie_efficace >= 8:
        score_hydrique -= 10
    elif pluie_efficace >= 4:
        score_hydrique -= 5
    if pluie_3j >= 8:
        score_hydrique -= 6
    elif pluie_3j >= 4:
        score_hydrique -= 3
    if pluie_probabilite_max_3j >= 80:
        score_hydrique -= 4
    if arrosage_recent >= 8:
        score_hydrique -= 14
    elif arrosage_recent >= 4:
        score_hydrique -= 8
    elif arrosage_recent > 0:
        score_hydrique -= 3
    if phase_dominante == "Sursemis":
        score_hydrique += 10
    elif phase_dominante == "Scarification":
        score_hydrique += 6
    if sous_phase == "Germination":
        score_hydrique += 6
    elif sous_phase == "Enracinement":
        score_hydrique += 4
    if humidite_sol is not None:
        if humidite_sol <= 25:
            score_hydrique += 12
        elif humidite_sol <= 40:
            score_hydrique += 6
        elif humidite_sol >= 80:
            score_hydrique -= 10
        elif humidite_sol >= 65:
            score_hydrique -= 4
    if advanced_context.get("retour_arrosage") is not None:
        score_hydrique -= min(float(advanced_context["retour_arrosage"]) * 2.0, 8.0)
    score_hydrique = int(max(0.0, min(score_hydrique, 100.0)))

    score_stress = 0.0
    if temperature >= 34:
        score_stress += 36
    elif temperature >= 30:
        score_stress += 26
    elif temperature >= 27:
        score_stress += 14
    if etp >= 5:
        score_stress += 24
    elif etp >= 4:
        score_stress += 16
    elif etp >= 3:
        score_stress += 8
    if humidite <= 35:
        score_stress += 18
    elif humidite <= 45:
        score_stress += 10
    elif humidite >= 90:
        score_stress += 10
    elif humidite >= 82:
        score_stress += 6
    if pluie_24h >= 10:
        score_stress += 14
    elif pluie_24h >= 6:
        score_stress += 8
    if phase_dominante == "Sursemis":
        score_stress += 18
    if phase_dominante in {"Sursemis", "Scarification", "Traitement"}:
        score_stress += 15
    elif phase_dominante in {"Fertilisation", "Biostimulant", "Agent Mouillant"}:
        score_stress += 6
    if pluie_demain >= 8 and temperature >= 30:
        score_stress -= 5
    if pluie_j2 >= 4 or pluie_3j >= 8:
        score_stress -= 4
    if pluie_probabilite_max_3j >= 80:
        score_stress -= 3
    if vent is not None:
        if vent >= 25:
            score_stress += 16
        elif vent >= 15:
            score_stress += 10
        elif vent >= 8:
            score_stress += 4
    if rosee is not None and rosee > 0:
        score_stress += 5
    score_stress = int(max(0.0, min(score_stress, 100.0)))

    score_tonte = 0.0
    if pluie_24h >= 6:
        score_tonte += 30
    elif pluie_24h >= 3:
        score_tonte += 18
    if pluie_demain >= 5:
        score_tonte += 12
    elif pluie_demain >= 2:
        score_tonte += 6
    if pluie_j2 >= 5:
        score_tonte += 10
    elif pluie_j2 >= 2:
        score_tonte += 4
    if pluie_3j >= 8:
        score_tonte += 10
    elif pluie_3j >= 4:
        score_tonte += 4
    if pluie_probabilite_max_3j >= 80:
        score_tonte += 6
    if humidite >= 88:
        score_tonte += 16
    elif humidite >= 78:
        score_tonte += 8
    if arrosage_recent >= 3:
        score_tonte += 12
    elif arrosage_recent > 0:
        score_tonte += 6
    if phase_dominante == "Sursemis":
        score_tonte += 45
    elif phase_dominante in {"Traitement", "Hivernage"}:
        score_tonte += 38
    elif phase_dominante != "Normal":
        score_tonte += 18
    if sous_phase == "Germination":
        score_tonte += 10
    elif sous_phase == "Enracinement":
        score_tonte += 5
    if hauteur_gazon is not None:
        if hauteur_gazon >= 12:
            score_tonte += 18
        elif hauteur_gazon >= 9:
            score_tonte += 10
        elif hauteur_gazon >= 7:
            score_tonte += 5
    if rosee is not None and rosee > 0:
        score_tonte += 8
    score_tonte += score_stress * 0.35
    score_tonte = int(max(0.0, min(score_tonte, 100.0)))

    return {
        "score_hydrique": score_hydrique,
        "score_stress": score_stress,
        "score_tonte": score_tonte,
    }
