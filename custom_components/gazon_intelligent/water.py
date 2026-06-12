from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any
import logging

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None


_SOIL_RESERVE_UTILE_MM: dict[str, float] = {
    "sableux": 8.0,
    "limoneux": 12.0,
    "argileux": 16.0,
}

_PHASE_MAD_RATIO: dict[str, float] = {
    "Sursemis": 0.35,
    "Hivernage": 0.6,
}

_RAIN_HORIZON_WEIGHTS: dict[str, float] = {
    "today": 1.0,
    "tomorrow": 0.55,
    "day_after_tomorrow": 0.25,
}

_BALANCE_HORIZON_WEIGHTS: dict[int, dict[str, float]] = {
    1: {"etp": 1.0, "rain": 1.0},
    3: {"etp": 3.0, "rain": 1.4},
    7: {"etp": 7.0, "rain": 2.4},
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_half_up_1(value: float) -> float:
    return float(int(value * 10.0 + 0.5)) / 10.0


def _current_date() -> date:
    if dt_util is not None:
        now_getter = getattr(dt_util, "now", None)
        if callable(now_getter):
            current = now_getter()
            if isinstance(current, datetime):
                return current.date()
    return datetime.now(timezone.utc).date()


def _bound(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _zone_mm_value(zone: dict[str, Any] | None) -> float | None:
    if not isinstance(zone, dict):
        return None
    amount = _to_float(zone.get("mm"))
    if amount is None:
        rate_mm_h = _to_float(zone.get("rate_mm_h"))
        duration_min = _to_float(zone.get("duration_min"))
        if rate_mm_h is not None and duration_min is not None:
            amount = (rate_mm_h * duration_min) / 60.0
    if amount is None:
        amount = _to_float(zone.get("objectif_mm"))
    if amount is None:
        return None
    return max(0.0, amount)


def _zone_session_mm_values(zones: list[dict[str, Any]] | None) -> list[float]:
    if not isinstance(zones, list):
        return []
    values: list[float] = []
    for zone in zones:
        amount = _zone_mm_value(zone)
        if amount is None:
            continue
        values.append(amount)
    return values


def _zone_session_surface_mm(
    zones: list[dict[str, Any]] | None,
    *,
    objective_mm: float | None = None,
) -> float | None:
    if objective_mm is not None and objective_mm > 0:
        return _round_half_up_1(objective_mm)
    values = _zone_session_mm_values(zones)
    if not values:
        return None
    return _round_half_up_1(sum(values) / len(values))


def _zone_session_total_mm(zones: list[dict[str, Any]] | None) -> float | None:
    values = _zone_session_mm_values(zones)
    if not values:
        return None
    return _round_half_up_1(sum(values))


def _normalize_allowed_zone_ids(allowed_zone_ids: Any) -> set[str]:
    if not isinstance(allowed_zone_ids, (list, tuple, set)):
        return set()
    normalized: set[str] = set()
    for raw in allowed_zone_ids:
        text = str(raw or "").strip()
        if text:
            normalized.add(text)
    return normalized


def _zone_ids_for_item(item: dict[str, Any] | None) -> set[str]:
    if not isinstance(item, dict):
        return set()
    zones = item.get("zones")
    if not isinstance(zones, list):
        return set()
    zone_ids: set[str] = set()
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        zone_id = str(zone.get("entity_id") or zone.get("zone") or "").strip()
        if zone_id:
            zone_ids.add(zone_id)
    return zone_ids


def _watering_item_matches_zones(
    item: dict[str, Any] | None,
    allowed_zone_ids: Any = None,
) -> bool:
    allowed = _normalize_allowed_zone_ids(allowed_zone_ids)
    if not allowed:
        return True
    zone_ids = _zone_ids_for_item(item)
    if not zone_ids:
        return False
    return bool(zone_ids & allowed)


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
    zones = item.get("zones")
    if isinstance(zones, list):
        surface_mm = _zone_session_surface_mm(zones)
        if surface_mm is not None:
            return surface_mm
    for key in ("total_mm", "session_total_mm", "objectif_mm", "mm"):
        amount = _to_float(item.get(key))
        if amount is not None:
            return amount
    return None


def build_watering_session_summary(
    zones: list[dict[str, Any]],
    source: str | None = None,
    objective_mm: float | None = None,
) -> dict[str, Any]:
    normalized_zones: list[dict[str, Any]] = []
    zones_total_mm = 0.0
    for order, zone in enumerate(zones, start=1):
        if not isinstance(zone, dict):
            continue
        zone_name = str(zone.get("zone") or zone.get("entity_id") or "").strip()
        if not zone_name:
            continue
        rate_mm_h = _to_float(zone.get("rate_mm_h"))
        duration_min = _to_float(zone.get("duration_min"))
        mm = _zone_mm_value(zone)
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
        zones_total_mm += mm

    objective_value = _zone_session_surface_mm(normalized_zones, objective_mm=objective_mm)
    if objective_value is None:
        objective_value = 0.0
    zones_total_mm = _round_half_up_1(zones_total_mm)
    session: dict[str, Any] = {
        "mm_scope": "global_surface",
        "mm_interpretation": "surface_uniform",
        "objective_mm": objective_value,
        "objectif_mm": objective_value,
        "total_mm": objective_value,
        "session_total_mm": objective_value,
        "zones_total_mm": zones_total_mm,
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
    allowed_zone_ids: Any = None,
) -> float:
    today = today or _current_date()
    total = 0.0
    for item in _iter_recent_watering_items(history, today=today, days=days, allowed_zone_ids=allowed_zone_ids):
        mm = _watering_item_mm(item)
        if mm is not None:
            total += float(mm)
    return total


def _iter_recent_watering_items(
    history: list[dict[str, Any]],
    today: date,
    days: int,
    allowed_zone_ids: Any = None,
):
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "arrosage":
            continue
        if not _watering_item_matches_zones(item, allowed_zone_ids):
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
        yield item


def compute_recent_watering_count(
    history: list[dict[str, Any]],
    today: date | None = None,
    days: int = 7,
    allowed_zone_ids: Any = None,
) -> int:
    today = today or _current_date()
    return sum(1 for _ in _iter_recent_watering_items(history, today=today, days=days, allowed_zone_ids=allowed_zone_ids))


def _effective_rain_mm(
    pluie_j: float,
    pluie_j1: float,
    pluie_j2: float,
    pluie_factor: float,
) -> float:
    return _round_half_up_1(
        (pluie_j * pluie_factor * _RAIN_HORIZON_WEIGHTS["today"])
        + (pluie_j1 * _RAIN_HORIZON_WEIGHTS["tomorrow"])
        + (pluie_j2 * _RAIN_HORIZON_WEIGHTS["day_after_tomorrow"])
    )


def _recent_watering_windows(
    history: list[dict[str, Any]],
    today: date,
    recent_watering_mm_override: float | None,
    retour_arrosage: float | None,
) -> dict[str, float]:
    arrosage_recent_7j = (
        recent_watering_mm_override
        if recent_watering_mm_override is not None
        else compute_recent_watering_mm(history, today=today, days=7)
    )
    arrosage_recent_jour = compute_recent_watering_mm(history, today=today, days=1)
    arrosage_recent_3j = compute_recent_watering_mm(history, today=today, days=3)
    if retour_arrosage is not None:
        retour = float(retour_arrosage)
        arrosage_recent_jour = max(arrosage_recent_jour, retour)
        arrosage_recent_3j = max(arrosage_recent_3j, retour)
        arrosage_recent_7j = max(arrosage_recent_7j, retour)
    arrosage_recent_3j = max(arrosage_recent_3j, arrosage_recent_jour)
    arrosage_recent_7j = max(arrosage_recent_7j, arrosage_recent_3j)
    if arrosage_recent_7j > 100:
        _LOGGER.warning("arrosage_recent_7j aberrant (%.1f mm), valeur clampée à 100 mm", arrosage_recent_7j)
        arrosage_recent_7j = 100.0
    return {
        "jour": arrosage_recent_jour,
        "3j": arrosage_recent_3j,
        "7j": arrosage_recent_7j,
    }


def _hydric_parameters(
    type_sol: str,
    advanced_context: dict[str, Any],
    phase_dominante: str | None,
) -> dict[str, float]:
    reserve_utile_mm = _SOIL_RESERVE_UTILE_MM.get(type_sol, _SOIL_RESERVE_UTILE_MM["limoneux"])
    soil_need_factor = float(advanced_context.get("soil_need_factor", advanced_context.get("soil_factor", 1.0)))
    soil_factor = (12.0 / reserve_utile_mm) * soil_need_factor
    soil_factor *= float(advanced_context.get("wind_factor", 1.0))
    soil_factor *= float(advanced_context.get("dew_factor", 1.0))
    mad_ratio = _PHASE_MAD_RATIO.get(str(phase_dominante or ""), 0.5)
    return {
        "reserve_utile_mm": reserve_utile_mm,
        "soil_factor": soil_factor,
        "mad_ratio": mad_ratio,
    }


def _soil_balance_priority(
    reserve_utile_mm: float,
    bilan_hydrique_mm: float,
    soil_balance: dict[str, Any] | None,
) -> dict[str, Any]:
    reserve_actuelle_source = None
    if isinstance(soil_balance, dict):
        reserve_actuelle_source = _to_float(soil_balance.get("reserve_mm"))
    # Réserve issue du bilan sol interne de l'intégration (ledger soil_balance, mis à jour
    # chaque cycle : réserve += pluie + arrosage − ETc, borné par type de sol) ?
    # Le pilotage par épuisement (MAD) n'est fiable que dans ce cas ; sinon la réserve
    # dérive du bilan court et n'atteint pas le seuil, d'où le repli sur le modèle déficit.
    reserve_from_soil_ledger = reserve_actuelle_source is not None
    if reserve_actuelle_source is None:
        reserve_actuelle_source = reserve_utile_mm + bilan_hydrique_mm
    reserve_stock_max_mm = _to_float(soil_balance.get("reserve_max_mm")) if isinstance(soil_balance, dict) else None
    if reserve_stock_max_mm is None:
        reserve_stock_max_mm = max(reserve_utile_mm, reserve_utile_mm * 2.0)
    reserve_stock_max_mm = max(reserve_utile_mm, float(reserve_stock_max_mm))
    return {
        "reserve_actuelle_source": float(reserve_actuelle_source),
        "reserve_stock_max_mm": reserve_stock_max_mm,
        "reserve_from_soil_ledger": reserve_from_soil_ledger,
    }


def _reserve_metrics(
    reserve_utile_mm: float,
    mad_ratio: float,
    reserve_actuelle_source: float,
    reserve_stock_max_mm: float,
) -> dict[str, float]:
    reserve_stock_mm = _bound(float(reserve_actuelle_source), 0.0, reserve_stock_max_mm)
    reserve_actuelle_mm = _bound(reserve_stock_mm, 0.0, reserve_utile_mm)
    depletion_allowed_mm = reserve_utile_mm * mad_ratio
    reserve_minimale_mm = reserve_utile_mm - depletion_allowed_mm
    depletion_mm = max(0.0, reserve_utile_mm - reserve_actuelle_mm)
    depletion_ratio = depletion_mm / reserve_utile_mm if reserve_utile_mm > 0 else 0.0
    reserve_surplus_mm = max(0.0, reserve_stock_mm - reserve_utile_mm)
    reserve_fill_ratio = reserve_stock_mm / reserve_stock_max_mm if reserve_stock_max_mm > 0 else 0.0
    reserve_available_ratio = reserve_actuelle_mm / reserve_utile_mm if reserve_utile_mm > 0 else 0.0
    return {
        "reserve_stock_mm": reserve_stock_mm,
        "reserve_actuelle_mm": reserve_actuelle_mm,
        "depletion_allowed_mm": depletion_allowed_mm,
        "reserve_minimale_mm": reserve_minimale_mm,
        "depletion_mm": depletion_mm,
        "depletion_ratio": depletion_ratio,
        "reserve_surplus_mm": reserve_surplus_mm,
        "reserve_fill_ratio": reserve_fill_ratio,
        "reserve_available_ratio": reserve_available_ratio,
    }


def _horizon_balance(
    etp_j: float,
    pluie_efficace: float,
    arrosage_mm: float,
    soil_factor: float,
    horizon_days: int,
) -> tuple[float, float]:
    weights = _BALANCE_HORIZON_WEIGHTS[horizon_days]
    deficit = max(0.0, ((etp_j * weights["etp"]) - (pluie_efficace * weights["rain"]) - arrosage_mm) * soil_factor)
    bilan = _round_half_up_1((pluie_efficace * weights["rain"] + arrosage_mm) - (etp_j * weights["etp"]))
    return deficit, bilan


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
        "weather_condition": weather_profile.get("weather_condition"),
    }


def _ra_extraterrestrial(latitude_deg: float, day_of_year: int) -> float:
    """Rayonnement extraterrestre Ra (MJ/m²/j) — FAO-56 équation 21.

    Varie de ~12 MJ/m²/j en hiver à ~40 MJ/m²/j en été à 45°N.
    """
    lat = math.radians(float(latitude_deg))
    doy = max(1, min(365, int(day_of_year)))
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)
    delta = 0.409 * math.sin(2.0 * math.pi * doy / 365.0 - 1.39)
    cos_ws = -math.tan(lat) * math.tan(delta)
    cos_ws = max(-1.0, min(1.0, cos_ws))
    ws = math.acos(cos_ws)
    Ra = (24.0 * 60.0 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat) * math.sin(delta)
        + math.cos(lat) * math.cos(delta) * math.sin(ws)
    )
    return max(0.0, Ra)


def compute_etp(
    temperature: float | None,
    pluie_24h: float | None,
    etp_capteur: float | None,
    temperature_reference_hydrique: float | None = None,
    weather_profile: dict[str, Any] | None = None,
) -> float | None:
    """Estimation ET0 par Penman-Monteith simplifié (FAO-56) sans capteur dédié.

    Utilise la température, l'humidité, le vent et la couverture nuageuse
    disponibles dans le profil météo HA. Nettement plus précis que la formule
    empirique linéaire précédente, notamment en conditions estivales où
    l'ancienne formule sous-estimait l'ET0 d'un facteur 2 à 3.

    Le capteur dédié (etp_capteur) reste prioritaire s'il est configuré.
    """
    if etp_capteur is not None:
        return etp_capteur

    weather_profile = weather_profile or {}

    # Résolution de la température de référence
    if temperature_reference_hydrique is not None:
        temperature = temperature_reference_hydrique
    if temperature is None:
        temperature = weather_profile.get("weather_temperature")
    if temperature is None:
        temperature = weather_profile.get("weather_apparent_temperature")
    if temperature is None:
        return None
    temperature = float(temperature)

    humidity = weather_profile.get("weather_humidity")
    wind = weather_profile.get("weather_wind_speed")
    cloud = weather_profile.get("weather_cloud_coverage")
    uv_index = weather_profile.get("weather_uv_index")
    dew_point = weather_profile.get("weather_dew_point")

    # Pression de vapeur saturante (kPa)
    es = 0.6108 * math.exp(17.27 * temperature / (temperature + 237.3))

    # Pression de vapeur réelle (kPa) — point de rosée prioritaire sur humidité relative
    if dew_point is not None:
        ea = 0.6108 * math.exp(17.27 * float(dew_point) / (float(dew_point) + 237.3))
    elif humidity is not None:
        ea = es * max(0.0, min(1.0, float(humidity) / 100.0))
    else:
        ea = es * 0.60  # hypothèse conservative : 60 % HR

    vpd = max(0.0, es - ea)  # déficit de pression de vapeur (kPa)

    # Pente de la courbe pression de vapeur saturante (kPa/°C)
    delta = 4098.0 * es / (temperature + 237.3) ** 2

    # Constante psychrométrique (kPa/°C) à pression standard
    gamma = 0.067

    # Fraction de ciel dégagé — couverture nuageuse prioritaire, sinon UV
    if cloud is not None:
        sky_clear = max(0.2, 1.0 - float(cloud) / 100.0 * 0.80)
    elif uv_index is not None:
        sky_clear = max(0.2, min(1.0, float(uv_index) / 9.0))
    else:
        sky_clear = 0.55  # valeur médiane par défaut

    # Rayonnement net estimé (MJ/m²/j)
    # Si la latitude et le jour de l'année sont disponibles (injectés par le coordinator
    # depuis hass.config.latitude), on calcule Ra exactement selon FAO-56.
    # Sinon on utilise un proxy température valable en zone tempérée.
    ha_latitude = weather_profile.get("ha_latitude")
    ha_day_of_year = weather_profile.get("ha_day_of_year")
    if ha_latitude is not None and ha_day_of_year is not None:
        Ra_ref = _ra_extraterrestrial(float(ha_latitude), int(ha_day_of_year))
    else:
        Ra_ref = max(2.0, 0.5 * temperature + 2.0)
    Rns = 0.77 * sky_clear * 0.75 * Ra_ref   # rayonnement net courtes longueurs d'onde
    # Rayonnement net grandes longueurs d'onde sortant (FAO-56 éq. 39, simplifié) :
    # loi de Stefan-Boltzmann pondérée par l'humidité (ea) et la couverture nuageuse.
    # L'ancienne approximation (0.5 + 0.01*T ≈ 0.7 MJ/m²/j) sous-estimait Rnl d'un
    # facteur ~7, gonflant Rn et surestimant l'ET0 (~8 mm à 20 °C au lieu de ~5).
    sigma_tk4 = 4.903e-9 * (temperature + 273.16) ** 4
    emissivity_net = max(0.05, 0.34 - 0.14 * math.sqrt(max(0.0, ea)))
    cloud_factor = max(0.05, min(1.0, 1.35 * sky_clear - 0.35))
    Rnl = sigma_tk4 * emissivity_net * cloud_factor
    Rn = max(0.0, Rns - Rnl)

    # Vitesse du vent à 2 m, convertie en m/s (Penman-Monteith l'exige en m/s).
    # Les entités météo HA fournissent le vent en km/h par défaut ; l'utiliser tel
    # quel comme des m/s surestimait fortement le terme aérodynamique de l'ET0.
    if wind is not None:
        wind_unit = str(weather_profile.get("weather_wind_speed_unit") or "").strip().lower()
        wind_ms = float(wind)
        if wind_unit in ("mph", "mi/h"):
            wind_ms *= 0.44704
        elif wind_unit in ("m/s", "ms", "mps"):
            pass
        else:  # km/h (défaut des entités météo HA) ou unité inconnue
            wind_ms /= 3.6
        u2 = max(0.5, wind_ms)
    else:
        u2 = 1.5  # légère brise par défaut

    # Formule Penman-Monteith FAO-56 (mm/j)
    numerator = 0.408 * delta * Rn + gamma * (900.0 / (temperature + 273.0)) * u2 * vpd
    denominator = delta + gamma * (1.0 + 0.34 * u2)
    et0 = max(0.0, numerator / denominator) if denominator > 0 else 0.0

    # Légère réduction si pluie récente (sol frais, évaporation réduite)
    if pluie_24h and pluie_24h > 0:
        et0 *= max(0.85, 1.0 - float(pluie_24h) * 0.015)

    return round(et0, 1)


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
    soil_balance: dict[str, Any] | None = None,
    phase_dominante: str | None = None,
) -> dict[str, Any]:
    today = today or _current_date()
    advanced_context = advanced_context or {}
    weather_profile = weather_profile or {}
    etp_j = max(0.0, etp or 0.0)
    pluie_j = max(0.0, pluie_24h or 0.0)
    pluie_j1 = max(0.0, pluie_demain or 0.0)
    pluie_j2 = max(0.0, pluie_j2 or 0.0)
    pluie_source = advanced_context.get("pluie_source", "capteur_pluie_24h")
    hydric_params = _hydric_parameters(
        type_sol=type_sol,
        advanced_context=advanced_context,
        phase_dominante=phase_dominante,
    )
    reserve_utile_mm = hydric_params["reserve_utile_mm"]
    soil_factor = hydric_params["soil_factor"]
    mad_ratio = hydric_params["mad_ratio"]

    pluie_factor = float(advanced_context.get("rain_factor", 0.85))
    pluie_efficace = _effective_rain_mm(pluie_j=pluie_j, pluie_j1=pluie_j1, pluie_j2=pluie_j2, pluie_factor=pluie_factor)
    recent_watering = _recent_watering_windows(
        history=history,
        today=today,
        recent_watering_mm_override=recent_watering_mm_override,
        retour_arrosage=advanced_context.get("retour_arrosage"),
    )
    arrosage_recent_jour = recent_watering["jour"]
    arrosage_recent_3j = recent_watering["3j"]
    arrosage_recent_7j = recent_watering["7j"]

    deficit_jour, bilan_hydrique_mm = _horizon_balance(
        etp_j=etp_j,
        pluie_efficace=pluie_efficace,
        arrosage_mm=arrosage_recent_jour,
        soil_factor=soil_factor,
        horizon_days=1,
    )
    deficit_3j, bilan_hydrique_3j = _horizon_balance(
        etp_j=etp_j,
        pluie_efficace=pluie_efficace,
        arrosage_mm=arrosage_recent_3j,
        soil_factor=soil_factor,
        horizon_days=3,
    )
    deficit_7j, bilan_hydrique_7j = _horizon_balance(
        etp_j=etp_j,
        pluie_efficace=pluie_efficace,
        arrosage_mm=arrosage_recent_7j,
        soil_factor=soil_factor,
        horizon_days=7,
    )
    soil_balance_priority = _soil_balance_priority(
        reserve_utile_mm=reserve_utile_mm,
        bilan_hydrique_mm=bilan_hydrique_mm,
        soil_balance=soil_balance,
    )
    reserve_metrics = _reserve_metrics(
        reserve_utile_mm=reserve_utile_mm,
        mad_ratio=mad_ratio,
        reserve_actuelle_source=soil_balance_priority["reserve_actuelle_source"],
        reserve_stock_max_mm=soil_balance_priority["reserve_stock_max_mm"],
    )

    return {
        "et0_mm": _round_half_up_1(max(0.0, etp_j)),
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
        "reserve_utile_mm": _round_half_up_1(reserve_utile_mm),
        "reserve_stock_mm": _round_half_up_1(reserve_metrics["reserve_stock_mm"]),
        "reserve_stock_max_mm": _round_half_up_1(soil_balance_priority["reserve_stock_max_mm"]),
        "reserve_from_soil_ledger": bool(soil_balance_priority["reserve_from_soil_ledger"]),
        "reserve_surplus_mm": _round_half_up_1(reserve_metrics["reserve_surplus_mm"]),
        "reserve_actuelle_mm": _round_half_up_1(reserve_metrics["reserve_actuelle_mm"]),
        "reserve_fill_ratio": round(_bound(reserve_metrics["reserve_fill_ratio"], 0.0, 1.0), 3),
        "reserve_available_ratio": round(_bound(reserve_metrics["reserve_available_ratio"], 0.0, 1.0), 3),
        "mad_ratio": round(_bound(mad_ratio, 0.0, 1.0), 2),
        "depletion_allowed_mm": _round_half_up_1(reserve_metrics["depletion_allowed_mm"]),
        "reserve_minimale_mm": _round_half_up_1(reserve_metrics["reserve_minimale_mm"]),
        "depletion_mm": _round_half_up_1(reserve_metrics["depletion_mm"]),
        "depletion_ratio": round(_bound(reserve_metrics["depletion_ratio"], 0.0, 1.0), 3),
        "soil_factor": _round_half_up_1(soil_factor),
        "soil_profile": advanced_context.get("soil_profile"),
        "soil_retention_factor": advanced_context.get("soil_retention_factor"),
        "soil_drainage_factor": advanced_context.get("soil_drainage_factor"),
        "soil_infiltration_factor": advanced_context.get("soil_infiltration_factor"),
        "soil_need_factor": advanced_context.get("soil_need_factor"),
    }
