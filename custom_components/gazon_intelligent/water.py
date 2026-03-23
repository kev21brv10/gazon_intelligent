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


_SOIL_MODEL_BASES: dict[str, dict[str, float]] = {
    "sableux": {
        "retention_factor": 0.84,
        "drainage_factor": 1.16,
        "infiltration_factor": 1.08,
    },
    "limoneux": {
        "retention_factor": 1.0,
        "drainage_factor": 1.0,
        "infiltration_factor": 1.0,
    },
    "argileux": {
        "retention_factor": 1.14,
        "drainage_factor": 0.88,
        "infiltration_factor": 0.92,
    },
}


def _compute_soil_profile(
    type_sol: str,
    humidite_sol: float | None = None,
    vent: float | None = None,
    rosee: float | None = None,
) -> dict[str, float | str]:
    soil_type = (type_sol or "limoneux").strip().lower()
    base = _SOIL_MODEL_BASES.get(soil_type, _SOIL_MODEL_BASES["limoneux"])
    retention_factor = float(base["retention_factor"])
    drainage_factor = float(base["drainage_factor"])
    infiltration_factor = float(base["infiltration_factor"])

    if humidite_sol is not None:
        if humidite_sol <= 25:
            retention_factor += 0.04
            drainage_factor += 0.05
            infiltration_factor += 0.03
        elif humidite_sol <= 40:
            retention_factor += 0.02
        elif humidite_sol >= 80:
            retention_factor -= 0.05
            drainage_factor -= 0.04
            infiltration_factor -= 0.04
        elif humidite_sol >= 65:
            retention_factor -= 0.03
            drainage_factor -= 0.02

    if vent is not None:
        if vent >= 25:
            drainage_factor += 0.08
            infiltration_factor += 0.04
        elif vent >= 15:
            drainage_factor += 0.05
        elif vent >= 8:
            drainage_factor += 0.02

    if rosee is not None and rosee > 0:
        retention_factor += 0.01

    retention_factor = max(0.75, min(retention_factor, 1.25))
    drainage_factor = max(0.75, min(drainage_factor, 1.25))
    infiltration_factor = max(0.75, min(infiltration_factor, 1.25))
    need_factor = 1.0
    need_factor += max(0.0, 1.0 - retention_factor) * 0.6
    need_factor += max(0.0, drainage_factor - 1.0) * 0.4
    need_factor += max(0.0, 1.0 - infiltration_factor) * 0.25
    need_factor = max(0.8, min(need_factor, 1.35))

    return {
        "soil_type": soil_type,
        "retention_factor": _round_half_up_1(retention_factor),
        "drainage_factor": _round_half_up_1(drainage_factor),
        "infiltration_factor": _round_half_up_1(infiltration_factor),
        "need_factor": _round_half_up_1(need_factor),
    }


def _watering_item_mm(item: dict[str, Any] | None) -> float | None:
    if not isinstance(item, dict):
        return None
    for key in ("total_mm", "session_total_mm", "objectif_mm", "mm"):
        amount = _to_float(item.get(key))
        if amount is not None:
            return amount
    zones = item.get("zones")
    if not isinstance(zones, list):
        return None
    total = 0.0
    found = False
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        amount = _to_float(zone.get("mm"))
        if amount is None:
            amount = _to_float(zone.get("objectif_mm"))
        if amount is None:
            rate_mm_h = _to_float(zone.get("rate_mm_h"))
            duration_min = _to_float(zone.get("duration_min"))
            if rate_mm_h is not None and duration_min is not None:
                amount = (rate_mm_h * duration_min) / 60.0
        if amount is None:
            continue
        total += amount
        found = True
    if not found:
        return None
    return total


def build_watering_session_summary(
    zones: list[dict[str, Any]],
    source: str | None = None,
) -> dict[str, Any]:
    normalized_zones: list[dict[str, Any]] = []
    total_mm = 0.0
    for order, zone in enumerate(zones, start=1):
        if not isinstance(zone, dict):
            continue
        zone_name = str(zone.get("zone") or zone.get("entity_id") or "").strip()
        if not zone_name:
            continue
        rate_mm_h = _to_float(zone.get("rate_mm_h"))
        duration_min = _to_float(zone.get("duration_min"))
        mm = _to_float(zone.get("mm"))
        if mm is None and rate_mm_h is not None and duration_min is not None:
            mm = (rate_mm_h * duration_min) / 60.0
        if mm is None:
            mm = _to_float(zone.get("objectif_mm"))
        if mm is None:
            continue
        normalized_zone = {
            "order": order,
            "zone": zone_name,
            "entity_id": zone.get("entity_id") or zone_name,
            "mm": _round_half_up_1(mm),
        }
        if rate_mm_h is not None:
            normalized_zone["rate_mm_h"] = _round_half_up_1(rate_mm_h)
        if duration_min is not None:
            normalized_zone["duration_min"] = _round_half_up_1(duration_min)
        if zone.get("duration_seconds") is not None:
            duration_seconds = _to_float(zone.get("duration_seconds"))
            if duration_seconds is not None:
                normalized_zone["duration_seconds"] = int(max(0.0, duration_seconds))
        normalized_zones.append(normalized_zone)
        total_mm += mm

    total_mm = _round_half_up_1(total_mm)
    session: dict[str, Any] = {
        "objectif_mm": total_mm,
        "total_mm": total_mm,
        "session_total_mm": total_mm,
        "zone_count": len(normalized_zones),
        "zones": normalized_zones,
    }
    if source:
        session["source"] = source
    return session


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
        mm = _watering_item_mm(item)
        if mm is None:
            continue
        total += float(mm)
    return total


def compute_recent_watering_count(
    history: list[dict[str, Any]],
    today: date | None = None,
    days: int = 7,
) -> int:
    today = today or date.today()
    count = 0
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
        if _watering_item_mm(item) is None:
            continue
        count += 1
    return count


def compute_advanced_context(
    humidite_sol: float | None = None,
    vent: float | None = None,
    rosee: float | None = None,
    hauteur_gazon: float | None = None,
    retour_arrosage: float | None = None,
    pluie_source: str = "capteur_pluie_24h",
    type_sol: str = "limoneux",
    weather_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weather_profile = weather_profile or {}
    humidite_sol = _to_float(humidite_sol)
    vent = _to_float(vent)
    rosee = _to_float(rosee)
    hauteur_gazon = _to_float(hauteur_gazon)
    retour_arrosage = max(0.0, _to_float(retour_arrosage) or 0.0)
    soil_profile = _compute_soil_profile(
        type_sol=type_sol,
        humidite_sol=humidite_sol,
        vent=vent,
        rosee=rosee,
    )
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
        "soil_profile": soil_profile,
        "soil_retention_factor": soil_profile["retention_factor"],
        "soil_drainage_factor": soil_profile["drainage_factor"],
        "soil_infiltration_factor": soil_profile["infiltration_factor"],
        "soil_need_factor": soil_profile["need_factor"],
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
        weather_temperature = weather_profile.get("weather_temperature")
        weather_apparent_temperature = weather_profile.get("weather_apparent_temperature")
        if weather_temperature is not None:
            temperature = weather_temperature
        elif weather_apparent_temperature is not None:
            temperature = weather_apparent_temperature
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
    pluie_j2: float | None = None,
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
    pluie_j2 = max(0.0, pluie_j2 or 0.0)
    pluie_source = advanced_context.get("pluie_source", "capteur_pluie_24h")

    reserve_sol = {
        "sableux": 8.0,
        "limoneux": 12.0,
        "argileux": 16.0,
    }.get(type_sol, 12.0)
    soil_need_factor = float(advanced_context.get("soil_need_factor", advanced_context.get("soil_factor", 1.0)))
    soil_factor = (12.0 / reserve_sol) * soil_need_factor
    soil_factor *= float(advanced_context.get("wind_factor", 1.0))
    soil_factor *= float(advanced_context.get("dew_factor", 1.0))

    pluie_factor = float(advanced_context.get("rain_factor", 0.85))
    pluie_efficace = _round_half_up_1((pluie_j * pluie_factor) + (pluie_j1 * 0.55) + (pluie_j2 * 0.25))
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
    bilan_hydrique_mm = _round_half_up_1((pluie_efficace + arrosage_recent_jour) - etp_j)
    bilan_hydrique_3j = _round_half_up_1((pluie_efficace * 1.4 + arrosage_recent_3j) - (etp_j * 3.0))
    bilan_hydrique_7j = _round_half_up_1((pluie_efficace * 2.4 + arrosage_recent_7j) - (etp_j * 7.0))

    return {
        "bilan_hydrique_mm": bilan_hydrique_mm,
        "bilan_hydrique_3j": bilan_hydrique_3j,
        "bilan_hydrique_7j": bilan_hydrique_7j,
        "deficit_jour": _round_half_up_1(deficit_jour),
        "deficit_3j": _round_half_up_1(deficit_3j),
        "deficit_7j": _round_half_up_1(deficit_7j),
        "pluie_efficace": pluie_efficace,
        "pluie_j2": pluie_j2,
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
        "soil_profile": advanced_context.get("soil_profile"),
        "soil_retention_factor": advanced_context.get("soil_retention_factor"),
        "soil_drainage_factor": advanced_context.get("soil_drainage_factor"),
        "soil_infiltration_factor": advanced_context.get("soil_infiltration_factor"),
        "soil_need_factor": advanced_context.get("soil_need_factor"),
    }
