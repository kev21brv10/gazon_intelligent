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
    pluie_source: str = "capteur_pluie_24h",
    weather_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weather_profile = weather_profile or {}
    humidite_sol = _to_float(humidite_sol)
    vent = _to_float(vent)
    rosee = _to_float(rosee)
    hauteur_gazon = _to_float(hauteur_gazon)
    retour_arrosage = max(0.0, _to_float(retour_arrosage) or 0.0)
    weather_precipitation_probability = _to_float(
        weather_profile.get("weather_precipitation_probability")
    )

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
    rain_factor = 0.85
    if weather_precipitation_probability is not None:
        if weather_precipitation_probability >= 80:
            rain_factor = 0.95
        elif weather_precipitation_probability >= 50:
            rain_factor = 0.9
        elif weather_precipitation_probability >= 20:
            rain_factor = 0.86
        else:
            rain_factor = 0.82
    if weather_profile.get("weather_condition") in {"rainy", "pouring"}:
        rain_factor = max(rain_factor, 0.95)

    return {
        "humidite_sol": humidite_sol,
        "vent": vent,
        "rosee": rosee,
        "hauteur_gazon": hauteur_gazon,
        "retour_arrosage": retour_arrosage if retour_arrosage > 0 else None,
        "pluie_source": pluie_source,
        "soil_factor": soil_factor,
        "wind_factor": wind_factor,
        "dew_factor": dew_factor,
        "rain_factor": rain_factor,
        "weather_precipitation_probability": weather_precipitation_probability,
        "weather_temperature": weather_profile.get("weather_temperature"),
        "weather_apparent_temperature": weather_profile.get("weather_apparent_temperature"),
        "weather_humidity": weather_profile.get("weather_humidity"),
        "weather_wind_speed": weather_profile.get("weather_wind_speed"),
        "weather_pressure": weather_profile.get("weather_pressure"),
        "weather_cloud_coverage": weather_profile.get("weather_cloud_coverage"),
        "weather_dew_point": weather_profile.get("weather_dew_point"),
        "weather_uv_index": weather_profile.get("weather_uv_index"),
        "weather_precipitation_probability": weather_profile.get("weather_precipitation_probability"),
        "weather_condition": weather_profile.get("weather_condition"),
    }


def compute_etp(
    temperature: float | None,
    pluie_24h: float | None,
    etp_capteur: float | None,
    weather_profile: dict[str, Any] | None = None,
) -> float | None:
    if etp_capteur is not None:
        return etp_capteur
    weather_profile = weather_profile or {}
    if temperature is None:
        temperature = weather_profile.get("weather_temperature") or weather_profile.get("weather_apparent_temperature")
    if temperature is None:
        return None
    temperature = float(temperature)

    base = max(0.0, 0.06 * temperature)
    apparent = weather_profile.get("weather_apparent_temperature")
    humidity = weather_profile.get("weather_humidity")
    wind = weather_profile.get("weather_wind_speed")
    cloud = weather_profile.get("weather_cloud_coverage")
    dew_point = weather_profile.get("weather_dew_point")
    precip_probability = weather_profile.get("weather_precipitation_probability")

    if apparent is not None and float(apparent) > temperature:
        base += min(0.5, (float(apparent) - temperature) * 0.03)
    if humidity is not None:
        base *= max(0.75, 1.0 - max(0.0, float(humidity) - 50.0) / 300.0)
    if wind is not None:
        base += min(0.7, float(wind) * 0.02)
    if cloud is not None:
        base *= max(0.75, 1.0 - float(cloud) / 600.0)
    if precip_probability is not None:
        base *= max(0.7, 1.0 - float(precip_probability) / 250.0)
    if dew_point is not None and temperature - float(dew_point) <= 2.0:
        base *= 0.9
    base = max(0.0, base - max(0.0, (pluie_24h or 0.0) * 0.05))
    return round(base, 1)


def compute_water_balance(
    history: list[dict[str, Any]],
    today: date | None = None,
    etp: float | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    type_sol: str = "limoneux",
    recent_watering_mm_override: float | None = None,
    advanced_context: dict[str, Any] | None = None,
    weather_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    advanced_context = advanced_context or {}
    weather_profile = weather_profile or {}
    etp_j = max(0.0, etp or 0.0)
    pluie_j = max(0.0, pluie_24h or 0.0)
    pluie_j1 = max(0.0, pluie_demain or 0.0)
    pluie_source = advanced_context.get("pluie_source", "capteur_pluie_24h")

    reserve_sol = {
        "sableux": 8.0,
        "limoneux": 12.0,
        "argileux": 16.0,
    }.get(type_sol, 12.0)
    soil_factor = (12.0 / reserve_sol) * float(advanced_context.get("soil_factor", 1.0))
    soil_factor *= float(advanced_context.get("wind_factor", 1.0))
    soil_factor *= float(advanced_context.get("dew_factor", 1.0))

    pluie_factor = float(advanced_context.get("rain_factor", 0.85))
    pluie_efficace = _round_half_up_1((pluie_j * pluie_factor) + (pluie_j1 * 0.55))
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
        "weather_precipitation_probability": weather_profile.get("weather_precipitation_probability"),
        "humidite_sol": advanced_context.get("humidite_sol"),
        "vent": advanced_context.get("vent"),
        "rosee": advanced_context.get("rosee"),
        "hauteur_gazon": advanced_context.get("hauteur_gazon"),
        "retour_arrosage": advanced_context.get("retour_arrosage"),
        "soil_factor": _round_half_up_1(soil_factor),
    }
