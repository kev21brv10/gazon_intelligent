from __future__ import annotations

from datetime import date
from typing import Any

_STRESS_LEVEL_THRESHOLDS = {
    "fort": {
        "score_stress": 75,
        "score_hydrique": 80,
        "deficit_jour": 3.0,
        "deficit_7j": 7.0,
        "temperature": 34.0,
        "etp": 5.0,
    },
    "modere": {
        "score_stress": 45,
        "score_hydrique": 50,
        "deficit_jour": 1.5,
        "deficit_3j": 2.5,
        "deficit_7j": 3.5,
        "temperature": 30.0,
        "etp": 4.0,
    },
}

_HYDRIC_DEFICIT_WEIGHTS = {
    "deficit_jour": 8.0,
    "deficit_3j": 3.0,
    "deficit_7j": 1.2,
}

_HYDRIC_RAIN_MALUS = {
    "pluie_efficace": ((8.0, -10.0), (4.0, -5.0)),
    "pluie_3j": ((8.0, -6.0), (4.0, -3.0)),
    "pluie_probabilite_max_3j": ((80.0, -4.0),),
}

_HYDRIC_WATERING_MALUS = (
    (8.0, -14.0),
    (4.0, -8.0),
    (0.0, -3.0),
)

_HYDRIC_PHASE_BONUS = {
    "Sursemis": 10.0,
    "Scarification": 6.0,
}

_HYDRIC_SUBPHASE_BONUS = {
    "Germination": 6.0,
    "Enracinement": 4.0,
}

_STRESS_TEMPERATURE_WEIGHTS = (
    (34.0, 36.0),
    (30.0, 26.0),
    (27.0, 14.0),
)

_STRESS_ETP_WEIGHTS = (
    (5.0, 24.0),
    (4.0, 16.0),
    (3.0, 8.0),
)

_STRESS_HUMIDITY_WEIGHTS = (
    ("<=", 35.0, 18.0),
    ("<=", 45.0, 10.0),
    (">=", 90.0, 10.0),
    (">=", 82.0, 6.0),
)

_STRESS_RAIN_WEIGHTS = {
    "pluie_24h": ((10.0, 14.0), (6.0, 8.0)),
}

_STRESS_PHASE_BONUS = {
    "Sursemis": 18.0,
}

_STRESS_PHASE_FAMILIES = {
    "high": ({"Sursemis", "Scarification", "Traitement"}, 15.0),
    "medium": ({"Fertilisation", "Biostimulant", "Agent Mouillant"}, 6.0),
}

_STRESS_FORECAST_RELIEF = {
    "hot_rain_tomorrow": -5.0,
    "rain_coming": -4.0,
    "high_probability": -3.0,
}

_STRESS_WIND_WEIGHTS = (
    (25.0, 16.0),
    (15.0, 10.0),
    (8.0, 4.0),
)

_TONTE_RAIN_WEIGHTS = {
    "pluie_24h": ((6.0, 30.0), (3.0, 18.0)),
    "pluie_demain": ((5.0, 12.0), (2.0, 6.0)),
    "pluie_j2": ((5.0, 10.0), (2.0, 4.0)),
    "pluie_3j": ((8.0, 10.0), (4.0, 4.0)),
    "pluie_probabilite_max_3j": ((80.0, 6.0),),
}

_TONTE_HUMIDITY_WEIGHTS = (
    (88.0, 16.0),
    (78.0, 8.0),
)

_TONTE_WATERING_WEIGHTS = (
    (3.0, 12.0),
    (0.0, 6.0),
)

_TONTE_PHASE_BONUS = {
    "Sursemis": 45.0,
    "Traitement": 38.0,
    "Hivernage": 38.0,
}

_TONTE_PHASE_DEFAULT_BONUS = 18.0

_TONTE_SUBPHASE_BONUS = {
    "Germination": 10.0,
    "Enracinement": 5.0,
}

_TONTE_HEIGHT_WEIGHTS = (
    (12.0, 18.0),
    (9.0, 10.0),
    (7.0, 5.0),
)

_TONTE_STRESS_TRANSFER_FACTOR = 0.35


def _clamp_score(value: float) -> int:
    return int(max(0.0, min(value, 100.0)))


def _threshold_score(value: float, thresholds: tuple[tuple[float, float], ...]) -> float:
    for minimum, score in thresholds:
        if value >= minimum:
            return score
    return 0.0


def _apply_grouped_metric_thresholds(
    metrics: dict[str, float], thresholds_by_metric: dict[str, tuple[tuple[float, float], ...]]
) -> float:
    score = 0.0
    for metric_name, thresholds in thresholds_by_metric.items():
        score += _threshold_score(metrics.get(metric_name, 0.0), thresholds)
    return score


def _apply_comparison_rules(
    value: float, rules: tuple[tuple[str, float, float], ...]
) -> float:
    score = 0.0
    for operator, threshold, delta in rules:
        if operator == "<=" and value <= threshold:
            score += delta
        elif operator == ">=" and value >= threshold:
            score += delta
    return score


def _compute_stress_forecast_relief(
    *,
    pluie_demain: float,
    pluie_j2: float,
    pluie_3j: float,
    pluie_probabilite_max_3j: float,
    temperature: float,
) -> float:
    relief = 0.0
    if pluie_demain >= 8 and temperature >= 30:
        relief += _STRESS_FORECAST_RELIEF["hot_rain_tomorrow"]
    if pluie_j2 >= 4 or pluie_3j >= 8:
        relief += _STRESS_FORECAST_RELIEF["rain_coming"]
    if pluie_probabilite_max_3j >= 80:
        relief += _STRESS_FORECAST_RELIEF["high_probability"]
    return relief


def _compute_score_hydrique(
    *,
    deficit_jour: float,
    deficit_3j: float,
    deficit_7j: float,
    pluie_efficace: float,
    pluie_3j: float,
    pluie_probabilite_max_3j: float,
    arrosage_recent: float,
    phase_dominante: str,
    sous_phase: str,
    humidite_sol: float | None,
    retour_arrosage: float | None,
) -> int:
    score_hydrique = (
        (deficit_jour * _HYDRIC_DEFICIT_WEIGHTS["deficit_jour"])
        + (deficit_3j * _HYDRIC_DEFICIT_WEIGHTS["deficit_3j"])
        + (deficit_7j * _HYDRIC_DEFICIT_WEIGHTS["deficit_7j"])
    )
    score_hydrique += _apply_grouped_metric_thresholds(
        {
            "pluie_efficace": pluie_efficace,
            "pluie_3j": pluie_3j,
            "pluie_probabilite_max_3j": pluie_probabilite_max_3j,
        },
        _HYDRIC_RAIN_MALUS,
    )
    score_hydrique += _threshold_score(arrosage_recent, _HYDRIC_WATERING_MALUS)
    score_hydrique += _HYDRIC_PHASE_BONUS.get(phase_dominante, 0.0)
    score_hydrique += _HYDRIC_SUBPHASE_BONUS.get(sous_phase, 0.0)
    if humidite_sol is not None:
        score_hydrique += _apply_comparison_rules(
            float(humidite_sol),
            (
                ("<=", 25.0, 12.0),
                ("<=", 40.0, 6.0),
                (">=", 80.0, -10.0),
                (">=", 65.0, -4.0),
            ),
        )
    if retour_arrosage is not None:
        score_hydrique -= min(float(retour_arrosage) * 2.0, 8.0)
    return _clamp_score(score_hydrique)


def _compute_score_stress(
    *,
    phase_dominante: str,
    pluie_24h: float,
    pluie_demain: float,
    pluie_j2: float,
    pluie_3j: float,
    pluie_probabilite_max_3j: float,
    humidite: float,
    temperature: float,
    etp: float,
    vent: float | None,
    rosee: float | None,
) -> int:
    score_stress = 0.0
    score_stress += _threshold_score(temperature, _STRESS_TEMPERATURE_WEIGHTS)
    score_stress += _threshold_score(etp, _STRESS_ETP_WEIGHTS)
    score_stress += _apply_comparison_rules(humidite, _STRESS_HUMIDITY_WEIGHTS)
    score_stress += _apply_grouped_metric_thresholds(
        {"pluie_24h": pluie_24h},
        _STRESS_RAIN_WEIGHTS,
    )
    score_stress += _STRESS_PHASE_BONUS.get(phase_dominante, 0.0)
    high_family, high_bonus = _STRESS_PHASE_FAMILIES["high"]
    medium_family, medium_bonus = _STRESS_PHASE_FAMILIES["medium"]
    if phase_dominante in high_family:
        score_stress += high_bonus
    elif phase_dominante in medium_family:
        score_stress += medium_bonus
    score_stress += _compute_stress_forecast_relief(
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
        temperature=temperature,
    )
    if vent is not None:
        score_stress += _threshold_score(float(vent), _STRESS_WIND_WEIGHTS)
    if rosee is not None and rosee > 0:
        score_stress += 5
    return _clamp_score(score_stress)


def _compute_score_tonte(
    *,
    phase_dominante: str,
    sous_phase: str,
    pluie_24h: float,
    pluie_demain: float,
    pluie_j2: float,
    pluie_3j: float,
    pluie_probabilite_max_3j: float,
    humidite: float,
    arrosage_recent: float,
    hauteur_gazon: float | None,
    rosee: float | None,
    score_stress: int,
) -> int:
    score_tonte = 0.0
    score_tonte += _apply_grouped_metric_thresholds(
        {
            "pluie_24h": pluie_24h,
            "pluie_demain": pluie_demain,
            "pluie_j2": pluie_j2,
            "pluie_3j": pluie_3j,
            "pluie_probabilite_max_3j": pluie_probabilite_max_3j,
        },
        _TONTE_RAIN_WEIGHTS,
    )
    score_tonte += _threshold_score(humidite, _TONTE_HUMIDITY_WEIGHTS)
    score_tonte += _threshold_score(arrosage_recent, _TONTE_WATERING_WEIGHTS)
    if phase_dominante in _TONTE_PHASE_BONUS:
        score_tonte += _TONTE_PHASE_BONUS[phase_dominante]
    elif phase_dominante != "Normal":
        score_tonte += _TONTE_PHASE_DEFAULT_BONUS
    score_tonte += _TONTE_SUBPHASE_BONUS.get(sous_phase, 0.0)
    if hauteur_gazon is not None:
        score_tonte += _threshold_score(float(hauteur_gazon), _TONTE_HEIGHT_WEIGHTS)
    if rosee is not None and rosee > 0:
        score_tonte += 8
    # Une partie du stress global reste volontairement transférée vers la tonte.
    score_tonte += score_stress * _TONTE_STRESS_TRANSFER_FACTOR
    return _clamp_score(score_tonte)


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

    fort = _STRESS_LEVEL_THRESHOLDS["fort"]
    modere = _STRESS_LEVEL_THRESHOLDS["modere"]
    if (
        score_stress >= fort["score_stress"]
        or score_hydrique >= fort["score_hydrique"]
        or deficit_jour >= fort["deficit_jour"]
        or deficit_7j >= fort["deficit_7j"]
        or (temperature >= fort["temperature"] and etp >= fort["etp"])
    ):
        return "fort"
    if (
        score_stress >= modere["score_stress"]
        or score_hydrique >= modere["score_hydrique"]
        or deficit_jour >= modere["deficit_jour"]
        or deficit_3j >= modere["deficit_3j"]
        or deficit_7j >= modere["deficit_7j"]
        or temperature >= modere["temperature"]
        or etp >= modere["etp"]
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
    # `today` reste présent pour compatibilité d'API legacy ; le scoring courant n'en dépend pas.
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

    score_hydrique = _compute_score_hydrique(
        deficit_jour=deficit_jour,
        deficit_3j=deficit_3j,
        deficit_7j=deficit_7j,
        pluie_efficace=pluie_efficace,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
        arrosage_recent=arrosage_recent,
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        humidite_sol=humidite_sol,
        retour_arrosage=advanced_context.get("retour_arrosage"),
    )

    score_stress = _compute_score_stress(
        phase_dominante=phase_dominante,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
        humidite=humidite,
        temperature=temperature,
        etp=etp,
        vent=vent,
        rosee=rosee,
    )

    score_tonte = _compute_score_tonte(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
        humidite=humidite,
        arrosage_recent=arrosage_recent,
        hauteur_gazon=hauteur_gazon,
        rosee=rosee,
        score_stress=score_stress,
    )

    return {
        "score_hydrique": score_hydrique,
        "score_stress": score_stress,
        "score_tonte": score_tonte,
    }
