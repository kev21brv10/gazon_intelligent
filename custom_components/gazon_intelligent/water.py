from __future__ import annotations

from datetime import date
from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_half_up_1(value: float) -> float:
    return float(int(value * 10.0 + 0.5)) / 10.0


def compute_recent_watering_mm(
    history: list[dict[str, Any]],
    today: date | None = None,
    days: int = 2,
) -> float:
    today = today or date.today()
    total = 0.0
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "arrosage":
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            d = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        delta = (today - d).days
        if delta < 0 or delta > days:
            continue
        mm = item.get("objectif_mm")
        if mm is None:
            continue
        try:
            total += float(mm)
        except (TypeError, ValueError):
            continue
    return total


def compute_advanced_context(
    humidite_sol: float | None = None,
    vent: float | None = None,
    rosee: float | None = None,
    hauteur_gazon: float | None = None,
    retour_arrosage: float | None = None,
    pluie_fine: float | None = None,
) -> dict[str, Any]:
    humidite_sol = _to_float(humidite_sol)
    vent = _to_float(vent)
    rosee = _to_float(rosee)
    hauteur_gazon = _to_float(hauteur_gazon)
    retour_arrosage = max(0.0, _to_float(retour_arrosage) or 0.0)
    pluie_fine = _to_float(pluie_fine)

    soil_factor = 1.0
    if humidite_sol is not None:
        if humidite_sol <= 25:
            soil_factor = 1.18
        elif humidite_sol <= 40:
            soil_factor = 1.08
        elif humidite_sol >= 80:
            soil_factor = 0.82
        elif humidite_sol >= 65:
            soil_factor = 0.92

    wind_factor = 1.0
    if vent is not None:
        if vent >= 25:
            wind_factor = 1.18
        elif vent >= 15:
            wind_factor = 1.10
        elif vent >= 8:
            wind_factor = 1.04

    dew_factor = 0.96 if rosee is not None and rosee > 0 else 1.0
    rain_factor = 0.92 if pluie_fine is not None else 0.85
    pluie_source = "capteur_pluie_fine" if pluie_fine is not None else "capteur_pluie_24h"

    return {
        "humidite_sol": humidite_sol,
        "vent": vent,
        "rosee": rosee,
        "hauteur_gazon": hauteur_gazon,
        "retour_arrosage": retour_arrosage if retour_arrosage > 0 else None,
        "pluie_fine": pluie_fine,
        "pluie_source": pluie_source,
        "soil_factor": soil_factor,
        "wind_factor": wind_factor,
        "dew_factor": dew_factor,
        "rain_factor": rain_factor,
    }


def compute_etp(
    temperature: float | None,
    pluie_24h: float | None,
    etp_capteur: float | None,
) -> float | None:
    if etp_capteur is not None:
        return etp_capteur
    if temperature is None:
        return None
    base = max(0.0, 0.08 * temperature)
    correction = max(0.0, (pluie_24h or 0) * 0.05)
    return max(0.0, base - correction)


def compute_water_balance(
    history: list[dict[str, Any]],
    today: date | None = None,
    etp: float | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    type_sol: str = "limoneux",
    recent_watering_mm_override: float | None = None,
    advanced_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    advanced_context = advanced_context or {}
    etp_j = max(0.0, etp or 0.0)
    pluie_j = max(0.0, pluie_24h or 0.0)
    pluie_j1 = max(0.0, pluie_demain or 0.0)
    pluie_fine = advanced_context.get("pluie_fine")
    pluie_source = advanced_context.get("pluie_source", "capteur_pluie_24h")
    if pluie_fine is not None:
        pluie_j = max(0.0, pluie_fine)

    reserve_sol = {
        "sableux": 8.0,
        "limoneux": 12.0,
        "argileux": 16.0,
    }.get(type_sol, 12.0)
    soil_factor = (12.0 / reserve_sol) * float(advanced_context.get("soil_factor", 1.0))
    soil_factor *= float(advanced_context.get("wind_factor", 1.0))
    soil_factor *= float(advanced_context.get("dew_factor", 1.0))

    pluie_efficace = _round_half_up_1((pluie_j * float(advanced_context.get("rain_factor", 0.85))) + (pluie_j1 * 0.55))
    arrosage_recent = (
        recent_watering_mm_override
        if recent_watering_mm_override is not None
        else compute_recent_watering_mm(history, today=today, days=7)
    )
    retour_arrosage = advanced_context.get("retour_arrosage")
    if retour_arrosage is not None:
        arrosage_recent = max(arrosage_recent, float(retour_arrosage))
    arrosage_recent_jour = compute_recent_watering_mm(history, today=today, days=1)
    arrosage_recent_3j = compute_recent_watering_mm(history, today=today, days=3)
    arrosage_recent_7j = arrosage_recent
    if retour_arrosage is not None:
        arrosage_recent_jour = max(arrosage_recent_jour, float(retour_arrosage))
        arrosage_recent_3j = max(arrosage_recent_3j, float(retour_arrosage))
        arrosage_recent_7j = max(arrosage_recent_7j, float(retour_arrosage))

    deficit_jour = max(0.0, (etp_j - pluie_efficace - arrosage_recent_jour) * soil_factor)
    deficit_3j = max(0.0, ((etp_j * 3.0) - (pluie_efficace * 1.4) - arrosage_recent_3j) * soil_factor)
    deficit_7j = max(0.0, ((etp_j * 7.0) - (pluie_efficace * 2.4) - arrosage_recent_7j) * soil_factor)

    return {
        "deficit_jour": _round_half_up_1(deficit_jour),
        "deficit_3j": _round_half_up_1(deficit_3j),
        "deficit_7j": _round_half_up_1(deficit_7j),
        "pluie_efficace": pluie_efficace,
        "arrosage_recent": _round_half_up_1(arrosage_recent_7j),
        "arrosage_recent_jour": _round_half_up_1(arrosage_recent_jour),
        "arrosage_recent_3j": _round_half_up_1(arrosage_recent_3j),
        "arrosage_recent_7j": _round_half_up_1(arrosage_recent_7j),
        "pluie_source": pluie_source,
        "pluie_fine": pluie_fine,
        "humidite_sol": advanced_context.get("humidite_sol"),
        "vent": advanced_context.get("vent"),
        "rosee": advanced_context.get("rosee"),
        "hauteur_gazon": advanced_context.get("hauteur_gazon"),
        "retour_arrosage": advanced_context.get("retour_arrosage"),
        "soil_factor": _round_half_up_1(soil_factor),
    }
