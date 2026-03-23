from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .water import compute_recent_watering_count

# Règles agronomiques soutenues par les sources:
# - arroser tôt le matin;
# - éviter les arrosages tardifs qui prolongent l'humectation nocturne;
# - pour les semis / sursemis, garder la surface humide sans saturation;
# - réduire la fréquence à mesure que l'enracinement progresse.
#
# Conventions internes de l'intégration:
# - fenêtre optimale stricte au matin;
# - fenêtre acceptable étendue jusqu'à 10h si le contexte reste favorable;
# - soirée réservée au rattrapage exceptionnel, jamais juste avant la nuit.
OPTIMAL_MORNING_START_HOUR = 4
OPTIMAL_MORNING_END_HOUR = 8
ACCEPTABLE_MORNING_END_HOUR = 10
EVENING_START_HOUR = 18
EVENING_END_HOUR = 20
NORMAL_WEEKLY_GUARDRAIL_MM_MIN = 20.0
NORMAL_WEEKLY_GUARDRAIL_MM_MAX = 25.0
NORMAL_MIN_USEFUL_SESSION_MM = 10.0
RAINY_WEATHER_CONDITIONS = {
    "rainy",
    "pouring",
    "lightning-rainy",
    "snowy-rainy",
}


def is_active_rain_weather(weather_profile: dict[str, Any] | None) -> bool:
    weather_profile = weather_profile or {}
    condition = str(weather_profile.get("weather_condition") or "").strip().lower()
    if condition in RAINY_WEATHER_CONDITIONS:
        return True
    precipitation_probability = weather_profile.get("weather_precipitation_probability")
    try:
        precipitation_probability = (
            float(precipitation_probability)
            if precipitation_probability is not None
            else None
        )
    except (TypeError, ValueError):
        precipitation_probability = None
    return precipitation_probability is not None and precipitation_probability >= 80.0


def _temperature_band(temperature: float | None) -> str:
    temperature = temperature if temperature is not None else 0.0
    if temperature < 10:
        return "cool"
    if temperature > 22:
        return "hot"
    return "mild"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _morning_window_bounds(phase_dominante: str, temperature: float | None) -> tuple[int, int, int, str]:
    """Retourne une fenêtre matinale explicite: optimale 4-8h, acceptable jusqu'à 10h."""
    band = _temperature_band(temperature)
    optimal_start = OPTIMAL_MORNING_START_HOUR * 60
    optimal_end = OPTIMAL_MORNING_END_HOUR * 60
    acceptable_end = ACCEPTABLE_MORNING_END_HOUR * 60
    if phase_dominante == "Sursemis" and band == "hot":
        acceptable_end = ACCEPTABLE_MORNING_END_HOUR * 60
    return optimal_start, optimal_end, acceptable_end, band


def _heat_stress_level(
    temperature: float | None,
    etp: float | None,
    humidite: float | None,
    weather_profile: dict[str, Any] | None,
    deficit_mm_brut: float,
) -> str:
    weather_profile = weather_profile or {}
    temperature = temperature if temperature is not None else _to_float(weather_profile.get("weather_temperature"))
    etp = etp if etp is not None else 0.0
    humidite = humidite if humidite is not None else _to_float(weather_profile.get("weather_humidity"))
    vent = _to_float(weather_profile.get("weather_wind_speed"))
    pluie_24h = _to_float(weather_profile.get("weather_precipitation")) or 0.0
    pluie_prob = _to_float(weather_profile.get("weather_precipitation_probability")) or 0.0

    score = 0
    temperature = temperature if temperature is not None else 0.0
    if temperature >= 38:
        score += 4
    elif temperature >= 34:
        score += 3
    elif temperature >= 30:
        score += 2
    elif temperature >= 27:
        score += 1

    if etp >= 5:
        score += 3
    elif etp >= 4:
        score += 2
    elif etp >= 3:
        score += 1

    if humidite is not None:
        if humidite <= 30:
            score += 2
        elif humidite <= 40:
            score += 1

    if vent is not None:
        if vent >= 25:
            score += 2
        elif vent >= 15:
            score += 1

    if pluie_24h <= 0 and pluie_prob <= 20:
        score += 1
    if deficit_mm_brut >= 8:
        score += 1

    if score >= 7:
        return "extreme"
    if score >= 5:
        return "canicule"
    if score >= 3:
        return "vigilance"
    return "normal"


def _evening_window_allowed(
    temperature: float | None,
    humidite: float | None,
    water_balance: dict[str, float],
    objectif_mm: float,
    heat_stress_level: str = "normal",
) -> bool:
    temperature = temperature if temperature is not None else 0.0
    humidite = humidite if humidite is not None else 0.0
    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)

    if heat_stress_level == "extreme":
        return False
    if temperature < 24:
        return False
    if humidite > 65:
        return False
    if arrosage_recent > 0.25:
        return False
    if bilan_hydrique_mm >= -0.3 and deficit_3j <= 0.8:
        return False
    return objectif_mm > 0


def _season_label(today: date) -> str:
    if today.month in {12, 1, 2}:
        return "winter"
    if today.month in {3, 4, 10, 11}:
        return "shoulder"
    return "summer"


def _heat_stress_phase(
    heat_stress_level: str,
    temperature: float | None,
    etp: float | None,
    pluie_demain: float,
    pluie_3j: float,
    recent_watering_count: int,
    recent_watering_mm_7j: float,
) -> str:
    if heat_stress_level == "normal":
        return "normal"
    if pluie_demain >= 4.0 or pluie_3j >= 6.0:
        return "sortie_de_canicule"
    if heat_stress_level == "extreme":
        if temperature is not None and temperature >= 34 and (etp or 0.0) >= 5.0:
            if recent_watering_count <= 1 or recent_watering_mm_7j < 6.0:
                return "canicule_prolongee"
        return "canicule_courte"
    if heat_stress_level == "canicule":
        if temperature is not None and temperature >= 31 and (etp or 0.0) >= 4.0:
            if recent_watering_count <= 2 and recent_watering_mm_7j < 10.0:
                return "canicule_prolongee"
        return "canicule_courte"
    if temperature is not None and temperature >= 30 and (etp or 0.0) >= 4.0:
        return "canicule_courte"
    return "normal"


def _dynamic_weekly_guardrail(
    today: date,
    phase_dominante: str,
    heat_stress_phase: str,
    soil_profile: str,
) -> tuple[float, float, str]:
    season = _season_label(today)
    if season == "winter":
        minimum, maximum = 17.0, 22.0
    elif season == "summer":
        minimum, maximum = 20.0, 25.0
    else:
        minimum, maximum = 19.0, 24.0

    if soil_profile == "sableux":
        minimum += 1.0
        maximum += 1.0
    elif soil_profile == "argileux":
        minimum -= 1.0
        maximum -= 0.5

    if phase_dominante == "Sursemis":
        minimum = max(0.5, minimum - 8.0)
        maximum = max(minimum + 1.0, maximum - 8.0)
    elif phase_dominante in {"Fertilisation", "Biostimulant"}:
        maximum = min(22.0, maximum)

    if heat_stress_phase == "canicule_prolongee":
        minimum += 2.0
        maximum += 3.0
    elif heat_stress_phase == "canicule_courte":
        minimum += 1.0
        maximum += 1.5
    elif heat_stress_phase == "sortie_de_canicule":
        minimum = max(15.0, minimum - 1.0)
        maximum = max(minimum + 4.0, maximum - 0.5)

    minimum = round(_clamp(minimum, 12.0, 28.0), 1)
    maximum = round(_clamp(maximum, minimum + 4.0, 28.0), 1)
    return minimum, maximum, f"saison={season}; sol={soil_profile}; phase={heat_stress_phase}"


def _confidence_assessment(
    *,
    phase_dominante: str,
    temperature: float | None,
    humidite: float | None,
    etp: float | None,
    weather_profile: dict[str, Any] | None,
    soil_profile: str,
    heat_stress_level: str,
    heat_stress_phase: str,
    block_reason: str | None,
    mm_final: float,
) -> tuple[int, str, list[str]]:
    score = 100
    reasons: list[str] = []

    if temperature is None:
        score -= 12
        reasons.append("température manquante")
    if etp is None:
        score -= 12
        reasons.append("ETP manquante")
    if humidite is None:
        score -= 8
        reasons.append("humidité manquante")

    weather_profile = weather_profile or {}
    if not weather_profile:
        score -= 6
        reasons.append("météo partielle")
    if weather_profile.get("weather_condition") is None:
        score -= 2
    if weather_profile.get("weather_precipitation_probability") is None:
        score -= 3

    if heat_stress_level in {"canicule", "extreme"}:
        score -= 4
        reasons.append(f"stress thermique={heat_stress_level}")
    if heat_stress_phase in {"canicule_prolongee", "sortie_de_canicule"}:
        score -= 3
        reasons.append(f"phase thermique={heat_stress_phase}")

    if soil_profile not in {"sableux", "limoneux", "argileux"}:
        score -= 4
        reasons.append("type de sol incertain")

    if phase_dominante in {"Traitement", "Hivernage"}:
        score += 0
    elif phase_dominante == "Sursemis":
        score -= 2
        reasons.append("sursemis: besoin plus variable")

    if block_reason in {"pluie_active", "mode_bloque"}:
        score += 0
    elif block_reason is not None:
        score -= 2
        reasons.append(f"blocage={block_reason}")

    if mm_final <= 0:
        score -= 3

    score = int(max(0.0, min(score, 100.0)))
    if score >= 75:
        level = "high"
    elif score >= 45:
        level = "medium"
    else:
        level = "low"
    return score, level, reasons


def _risk_rank(level: str) -> int:
    return {"faible": 0, "modere": 1, "eleve": 2}.get(level, 0)


def _risk_from_rank(rank: int) -> str:
    return {0: "faible", 1: "modere", 2: "eleve"}.get(max(0, min(rank, 2)), "faible")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def compute_watering_profile(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    today: date | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
    humidite: float | None = None,
    temperature: float | None = None,
    etp: float | None = None,
    type_sol: str = "limoneux",
    weather_profile: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    weather_profile = weather_profile or {}
    history = [item for item in (history or []) if isinstance(item, dict)]
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0
    pluie_24h = pluie_24h or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    soil_profile = (type_sol or "limoneux").strip().lower()
    recent_watering_count = compute_recent_watering_count(history, today=today, days=7) if history else 0

    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    recent_watering_mm_7j = float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0)
    deficit_mm_brut = max(0.0, max(deficit_jour, deficit_3j, deficit_7j))
    pluie_support = max(
        0.0,
        (pluie_24h * 0.35)
        + (pluie_demain * 0.35)
        + (pluie_j2 * 0.2)
        + (pluie_3j * 0.1),
    )
    historique_support = min(recent_watering_mm_7j * 0.2, deficit_mm_brut * 0.5)
    humidite_penalty = 0.0
    if humidite >= 85:
        humidite_penalty = deficit_mm_brut * 0.2
    elif humidite >= 75:
        humidite_penalty = deficit_mm_brut * 0.1
    deficit_mm_ajuste = max(0.0, deficit_mm_brut - pluie_support - historique_support - humidite_penalty)
    heat_stress_level = _heat_stress_level(
        temperature=temperature,
        etp=etp,
        humidite=humidite,
        weather_profile=weather_profile,
        deficit_mm_brut=deficit_mm_brut,
    )
    heat_stress_phase = _heat_stress_phase(
        heat_stress_level=heat_stress_level,
        temperature=temperature,
        etp=etp,
        pluie_demain=pluie_demain,
        pluie_3j=pluie_3j,
        recent_watering_count=recent_watering_count,
        recent_watering_mm_7j=recent_watering_mm_7j,
    )
    guardrail_min_mm, guardrail_max_mm, guardrail_reason = _dynamic_weekly_guardrail(
        today=today,
        phase_dominante=phase_dominante,
        heat_stress_phase=heat_stress_phase,
        soil_profile=soil_profile,
    )
    optimal_start_minute, optimal_end_minute, acceptable_end_minute, temperature_band = _morning_window_bounds(
        phase_dominante=phase_dominante,
        temperature=temperature,
    )
    if phase_dominante in {"Traitement", "Hivernage"} or is_active_rain_weather(weather_profile):
        block_reason = "mode_bloque" if phase_dominante in {"Traitement", "Hivernage"} else "pluie_active"
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=0.0,
        )
        return {
            "deficit_brut_mm": 0.0,
            "deficit_mm_brut": 0.0,
            "deficit_mm_ajuste": 0.0,
            "mm_cible": 0.0,
            "mm_final_recommande": 0.0,
            "mm_final": 0.0,
            "mm_requested": 0.0,
            "mm_applied": 0.0,
            "mm_detected": recent_watering_mm_7j,
            "type_arrosage": "bloque",
            "arrosage_recommande": False,
            "arrosage_auto_autorise": False,
            "arrosage_conseille": "personnalise",
            "watering_passages": 1,
            "watering_pause_minutes": 0,
            "fractionnement": {
                "enabled": False,
                "passages": 1,
                "pause_minutes": 0,
                "max_mm_per_passage": 0.0,
                "reason": block_reason,
            },
            "niveau_confiance": confidence_level,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "raison_decision_base": f"Phase {phase_dominante}: arrosage bloqué.",
            "block_reason": block_reason,
            "fenetre_optimale": "attendre",
            "niveau_action": "surveiller",
            "risque_gazon": "faible",
            "heat_stress_level": heat_stress_level,
            "heat_stress_phase": heat_stress_phase,
            "watering_window_start_minute": optimal_start_minute,
            "watering_window_end_minute": acceptable_end_minute,
            "watering_window_optimal_start_minute": optimal_start_minute,
            "watering_window_optimal_end_minute": optimal_end_minute,
            "watering_window_acceptable_end_minute": acceptable_end_minute,
            "watering_evening_start_minute": EVENING_START_HOUR * 60,
            "watering_evening_end_minute": EVENING_END_HOUR * 60,
            "watering_window_profile": temperature_band,
            "watering_evening_allowed": False,
            "recent_watering_count_7j": recent_watering_count,
            "recent_watering_mm_7j": recent_watering_mm_7j,
            "weekly_guardrail_mm_min": guardrail_min_mm,
            "weekly_guardrail_mm_max": guardrail_max_mm,
            "weekly_guardrail_reason": guardrail_reason,
        }

    besoin_court = max(0.0, -bilan_hydrique_mm)
    besoin_tendance = (deficit_3j * 0.18) + (deficit_7j * 0.06)
    pression_hydrique = besoin_court + besoin_tendance
    pluie_compensatrice = (
        pluie_demain >= max(2.0, deficit_mm_brut * 0.8)
        or pluie_j2 >= max(2.0, deficit_mm_brut * 0.8)
        or pluie_3j >= max(4.0, deficit_mm_brut * 1.2)
        or pluie_probabilite_max_3j >= 80.0
    )
    pluie_proche = (
        pluie_24h >= 4.0
        or pluie_demain >= 4.0
        or pluie_j2 >= 4.0
        or pluie_3j >= 6.0
        or pluie_probabilite_max_3j >= 80.0
    )
    morning_start_minute = optimal_start_minute
    morning_end_minute = optimal_end_minute
    now_hour = datetime.now().hour
    now_minutes = now_hour * 60 + datetime.now().minute
    evening_allowed = _evening_window_allowed(
        temperature=temperature,
        humidite=humidite,
        water_balance=water_balance,
        objectif_mm=deficit_mm_brut,
        heat_stress_level=heat_stress_level,
    )
    if phase_dominante == "Sursemis":
        if sous_phase == "Germination":
            mm_cible = _clamp((besoin_court * 0.5) + (besoin_tendance * 0.1), 0.6, 1.8)
        elif sous_phase == "Enracinement":
            mm_cible = _clamp((besoin_court * 0.45) + (besoin_tendance * 0.08), 0.5, 2.1)
        else:
            mm_cible = _clamp((besoin_court * 0.7) + (besoin_tendance * 0.12), 0.5, 2.5)
        if humidite >= 85 and temperature < 28:
            mm_cible *= 0.9
        block_reason = None
        if pluie_compensatrice or pluie_proche:
            block_reason = "pluie_prevue_suffisante"
        elif humidite >= 85:
            block_reason = "humidite_elevee"
        mm_final = 0.0 if block_reason else mm_cible
        type_arrosage = "manuel_frequent" if mm_final > 0 else "personnalise"
        arrosage_auto = False
        passages = 1 if mm_final <= 1.0 else 2
        pause_minutes = 25 if passages > 1 else 0
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=mm_final,
        )
        return {
            "deficit_brut_mm": round(deficit_mm_brut, 1),
            "deficit_mm_brut": round(deficit_mm_brut, 1),
            "deficit_mm_ajuste": round(deficit_mm_ajuste, 1),
            "mm_cible": round(mm_cible, 1),
            "mm_final_recommande": round(mm_final, 1),
            "mm_final": round(mm_final, 1),
            "mm_requested": round(mm_cible, 1),
            "mm_applied": round(mm_final, 1),
            "mm_detected": round(recent_watering_mm_7j, 1),
            "type_arrosage": type_arrosage,
            "arrosage_recommande": mm_final > 0,
            "arrosage_auto_autorise": False,
            "arrosage_conseille": "personnalise",
            "watering_passages": passages,
            "watering_pause_minutes": pause_minutes,
            "fractionnement": {
                "enabled": passages > 1,
                "passages": passages,
                "pause_minutes": pause_minutes,
                "max_mm_per_passage": round(mm_final / passages, 1) if passages > 0 and mm_final > 0 else 0.0,
                "reason": "sursemis_micro_apports",
            },
            "niveau_confiance": confidence_level,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "raison_decision_base": "Sursemis: micro-apports fréquents et fractionnés.",
            "block_reason": block_reason,
            "fenetre_optimale": "maintenant"
            if morning_start_minute <= now_minutes < acceptable_end_minute
            else "ce_matin",
            "niveau_action": "a_faire" if mm_final > 0 else "surveiller",
            "risque_gazon": "modere",
            "heat_stress_level": heat_stress_level,
            "heat_stress_phase": heat_stress_phase,
            "watering_window_start_minute": morning_start_minute,
            "watering_window_end_minute": acceptable_end_minute,
            "watering_window_optimal_start_minute": morning_start_minute,
            "watering_window_optimal_end_minute": morning_end_minute,
            "watering_window_acceptable_end_minute": acceptable_end_minute,
            "watering_evening_start_minute": EVENING_START_HOUR * 60,
            "watering_evening_end_minute": EVENING_END_HOUR * 60,
            "watering_window_profile": temperature_band,
            "watering_evening_allowed": False,
            "recent_watering_count_7j": recent_watering_count,
            "recent_watering_mm_7j": recent_watering_mm_7j,
            "weekly_guardrail_mm_min": guardrail_min_mm,
            "weekly_guardrail_mm_max": guardrail_max_mm,
            "weekly_guardrail_reason": guardrail_reason,
        }

    if phase_dominante == "Normal":
        rain_adjustment = min(pluie_support * 0.7, 5.0)
        guardrail_min_effective = round(
            max(NORMAL_MIN_USEFUL_SESSION_MM, guardrail_min_mm - rain_adjustment),
            1,
        )
        guardrail_max_effective = round(
            max(guardrail_min_effective + 4.0, guardrail_max_mm - rain_adjustment),
            1,
        )
        useful_threshold = max(NORMAL_MIN_USEFUL_SESSION_MM, guardrail_min_effective * 0.5)
        block_reason = None
        if pluie_compensatrice or pluie_proche:
            block_reason = "pluie_prevue_suffisante"
        elif humidite >= 85 or bilan_hydrique_mm > 0.5:
            block_reason = "humidite_excessive"
        elif (
            recent_watering_count >= 3
            and recent_watering_mm_7j >= guardrail_min_mm
            and deficit_mm_ajuste < guardrail_min_mm
        ):
            block_reason = "garde_fou_hebdomadaire"
        if deficit_mm_ajuste < useful_threshold:
            mm_cible = 0.0
        else:
            upper_bound = min(guardrail_max_effective, deficit_mm_brut)
            if upper_bound <= guardrail_min_effective:
                mm_cible = upper_bound
            else:
                mm_cible = _clamp(
                    max(deficit_mm_ajuste, guardrail_min_effective),
                    guardrail_min_effective,
                    upper_bound,
                )
        if block_reason is not None:
            mm_cible = 0.0
        mm_final = mm_cible
        passages = 1
        if mm_final > 12.0:
            passages = 2
        if recent_watering_count >= 2 and recent_watering_mm_7j >= guardrail_max_mm:
            passages = max(passages, 2)
        pause_minutes = 25 if passages > 1 else 0
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=mm_final,
        )
        return {
            "deficit_brut_mm": round(deficit_mm_brut, 1),
            "deficit_mm_brut": round(deficit_mm_brut, 1),
            "deficit_mm_ajuste": round(deficit_mm_ajuste, 1),
            "mm_cible": round(mm_cible, 1),
            "mm_final_recommande": round(mm_final, 1),
            "mm_final": round(mm_final, 1),
            "mm_requested": round(mm_cible, 1),
            "mm_applied": round(mm_final, 1),
            "mm_detected": round(water_balance.get("arrosage_recent_jour", 0.0), 1),
            "type_arrosage": "bloque" if block_reason is not None else ("auto" if mm_final > 0 else "personnalise"),
            "arrosage_recommande": mm_final > 0 and block_reason is None,
            "arrosage_auto_autorise": mm_final > 0 and block_reason is None,
            "arrosage_conseille": "personnalise" if block_reason is not None or mm_final <= 0 else "auto",
            "watering_passages": passages,
            "watering_pause_minutes": pause_minutes,
            "fractionnement": {
                "enabled": passages > 1,
                "passages": passages,
                "pause_minutes": pause_minutes,
                "max_mm_per_passage": round(mm_final / passages, 1) if passages > 0 and mm_final > 0 else 0.0,
                "reason": "deep_watering_fractionation" if passages > 1 else "single_pass_deep_watering",
            },
            "niveau_confiance": confidence_level,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "raison_decision_base": "Mode Normal: arrosage profond uniquement si le déficit est utile.",
            "block_reason": block_reason,
            "fenetre_optimale": "maintenant"
            if morning_start_minute <= now_minutes < acceptable_end_minute
            else "ce_matin",
            "niveau_action": "a_faire" if mm_final > 0 else "surveiller",
            "risque_gazon": "modere" if deficit_mm_brut >= 5 else "faible",
            "heat_stress_level": heat_stress_level,
            "heat_stress_phase": heat_stress_phase,
            "watering_window_start_minute": morning_start_minute,
            "watering_window_end_minute": acceptable_end_minute,
            "watering_window_optimal_start_minute": morning_start_minute,
            "watering_window_optimal_end_minute": morning_end_minute,
            "watering_window_acceptable_end_minute": acceptable_end_minute,
            "watering_evening_start_minute": EVENING_START_HOUR * 60,
            "watering_evening_end_minute": EVENING_END_HOUR * 60,
            "watering_window_profile": temperature_band,
            "watering_evening_allowed": evening_allowed,
            "recent_watering_count_7j": recent_watering_count,
            "recent_watering_mm_7j": recent_watering_mm_7j,
            "weekly_guardrail_mm_min": guardrail_min_effective,
            "weekly_guardrail_mm_max": guardrail_max_effective,
            "weekly_guardrail_reason": f"{guardrail_reason}; pluie_support={pluie_support:.1f}",
        }

    if phase_dominante in {"Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"}:
        ranges = {
            "Fertilisation": (3.0, 8.0),
            "Biostimulant": (5.0, 10.0),
            "Agent Mouillant": (5.0, 12.0),
            "Scarification": (5.0, 10.0),
        }
        minimum, maximum = ranges[phase_dominante]
        if phase_dominante == "Fertilisation":
            mm_cible = _clamp((besoin_court * 0.4) + (besoin_tendance * 0.08), minimum, maximum)
        elif phase_dominante == "Biostimulant":
            mm_cible = _clamp((besoin_court * 0.5) + (besoin_tendance * 0.08), minimum, maximum)
        elif phase_dominante == "Agent Mouillant":
            mm_cible = _clamp((besoin_court * 0.55) + (besoin_tendance * 0.1), minimum, maximum)
        else:
            mm_cible = _clamp((besoin_court * 0.6) + (besoin_tendance * 0.1), minimum, maximum)
        block_reason = None
        if pluie_compensatrice or pluie_proche:
            block_reason = "pluie_prevue_suffisante"
        elif humidite >= 85:
            block_reason = "humidite_elevee"
        mm_final = 0.0 if block_reason else mm_cible
        passages = 1 if mm_final <= 4.0 else 2
        pause_minutes = 25 if passages > 1 else 0
        fenetre_optimale = "soir" if evening_allowed and temperature >= 24 and now_hour < EVENING_END_HOUR else "ce_matin"
        confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
            phase_dominante=phase_dominante,
            temperature=temperature,
            humidite=humidite,
            etp=etp,
            weather_profile=weather_profile,
            soil_profile=soil_profile,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            block_reason=block_reason,
            mm_final=mm_final,
        )
        return {
            "deficit_brut_mm": round(deficit_mm_brut, 1),
            "deficit_mm_brut": round(deficit_mm_brut, 1),
            "deficit_mm_ajuste": round(deficit_mm_ajuste, 1),
            "mm_cible": round(mm_cible, 1),
            "mm_final_recommande": round(mm_final, 1),
            "mm_final": round(mm_final, 1),
            "mm_requested": round(mm_cible, 1),
            "mm_applied": round(mm_final, 1),
            "mm_detected": round(water_balance.get("arrosage_recent_jour", 0.0), 1),
            "type_arrosage": "auto" if mm_final > 0 else "personnalise",
            "arrosage_recommande": mm_final > 0,
            "arrosage_auto_autorise": mm_final > 0,
            "arrosage_conseille": "auto" if phase_dominante == "Fertilisation" else "personnalise",
            "watering_passages": passages,
            "watering_pause_minutes": pause_minutes,
            "fractionnement": {
                "enabled": passages > 1,
                "passages": passages,
                "pause_minutes": pause_minutes,
                "max_mm_per_passage": round(mm_final / passages, 1) if passages > 0 and mm_final > 0 else 0.0,
                "reason": "managed_fractionation" if passages > 1 else "single_pass",
            },
            "niveau_confiance": confidence_level,
            "confidence_score": confidence_score,
            "confidence_reasons": confidence_reasons,
            "raison_decision_base": f"{phase_dominante}: arrosage léger adapté.",
            "block_reason": block_reason,
            "fenetre_optimale": fenetre_optimale if mm_final > 0 else "attendre",
            "niveau_action": "a_faire" if mm_final > 0 else "surveiller",
            "risque_gazon": "faible" if mm_final > 0 else "modere",
            "heat_stress_level": heat_stress_level,
            "heat_stress_phase": heat_stress_phase,
            "watering_window_start_minute": morning_start_minute,
            "watering_window_end_minute": acceptable_end_minute,
            "watering_window_optimal_start_minute": morning_start_minute,
            "watering_window_optimal_end_minute": morning_end_minute,
            "watering_window_acceptable_end_minute": acceptable_end_minute,
            "watering_evening_start_minute": EVENING_START_HOUR * 60,
            "watering_evening_end_minute": EVENING_END_HOUR * 60,
            "watering_window_profile": temperature_band,
            "watering_evening_allowed": evening_allowed,
            "recent_watering_count_7j": recent_watering_count,
            "recent_watering_mm_7j": float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0),
            "weekly_guardrail_mm_min": guardrail_min_mm,
            "weekly_guardrail_mm_max": guardrail_max_mm,
            "weekly_guardrail_reason": guardrail_reason,
        }

    mm_cible = _clamp(max(deficit_mm_ajuste, 5.0), 5.0, 20.0)
    block_reason = None
    if pluie_compensatrice or pluie_proche:
        block_reason = "pluie_prevue_suffisante"
    elif humidite >= 85:
        block_reason = "humidite_elevee"
    mm_final = 0.0 if block_reason else mm_cible
    passages = 1 if mm_final <= 12.0 else 2
    pause_minutes = 25 if passages > 1 else 0
    confidence_score, confidence_level, confidence_reasons = _confidence_assessment(
        phase_dominante=phase_dominante,
        temperature=temperature,
        humidite=humidite,
        etp=etp,
        weather_profile=weather_profile,
        soil_profile=soil_profile,
        heat_stress_level=heat_stress_level,
        heat_stress_phase=heat_stress_phase,
        block_reason=block_reason,
        mm_final=mm_final,
    )
    return {
        "deficit_brut_mm": round(deficit_mm_brut, 1),
        "deficit_mm_brut": round(deficit_mm_brut, 1),
        "deficit_mm_ajuste": round(deficit_mm_ajuste, 1),
        "mm_cible": round(mm_cible, 1),
        "mm_final_recommande": round(mm_final, 1),
        "mm_final": round(mm_final, 1),
        "mm_requested": round(mm_cible, 1),
        "mm_applied": round(mm_final, 1),
        "mm_detected": round(water_balance.get("arrosage_recent_jour", 0.0), 1),
        "type_arrosage": "personnalise" if mm_final <= 0 else "auto",
        "arrosage_recommande": mm_final > 0,
        "arrosage_auto_autorise": mm_final > 0,
        "arrosage_conseille": "personnalise",
        "watering_passages": passages,
        "watering_pause_minutes": pause_minutes,
        "fractionnement": {
            "enabled": passages > 1,
            "passages": passages,
            "pause_minutes": pause_minutes,
            "max_mm_per_passage": round(mm_final / passages, 1) if passages > 0 and mm_final > 0 else 0.0,
            "reason": "generic_deep_watering" if passages > 1 else "single_pass",
        },
        "niveau_confiance": confidence_level,
        "confidence_score": confidence_score,
        "confidence_reasons": confidence_reasons,
        "raison_decision_base": f"Phase {phase_dominante}: arrosage maîtrisé.",
        "block_reason": block_reason,
        "fenetre_optimale": "soir"
        if evening_allowed and temperature >= 24 and now_hour < EVENING_END_HOUR
        else ("ce_matin" if mm_final > 0 else "attendre"),
        "niveau_action": "a_faire" if mm_final > 0 else "surveiller",
        "risque_gazon": "faible",
        "heat_stress_level": heat_stress_level,
        "heat_stress_phase": heat_stress_phase,
        "watering_window_start_minute": morning_start_minute,
        "watering_window_end_minute": acceptable_end_minute,
        "watering_window_optimal_start_minute": morning_start_minute,
        "watering_window_optimal_end_minute": morning_end_minute,
        "watering_window_acceptable_end_minute": acceptable_end_minute,
        "watering_evening_start_minute": EVENING_START_HOUR * 60,
        "watering_evening_end_minute": EVENING_END_HOUR * 60,
        "watering_window_profile": temperature_band,
        "watering_evening_allowed": evening_allowed,
        "recent_watering_count_7j": recent_watering_count,
        "recent_watering_mm_7j": float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0),
        "weekly_guardrail_mm_min": guardrail_min_mm,
        "weekly_guardrail_mm_max": guardrail_max_mm,
        "weekly_guardrail_reason": guardrail_reason,
    }


def compute_objectif_mm(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    today: date | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
    humidite: float | None = None,
    temperature: float | None = None,
    etp: float | None = None,
    type_sol: str = "limoneux",
    weather_profile: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> float:
    return float(
        compute_watering_profile(
            phase_dominante=phase_dominante,
            sous_phase=sous_phase,
            water_balance=water_balance,
            today=today,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            pluie_j2=pluie_j2,
            pluie_3j=pluie_3j,
            pluie_probabilite_max_3j=pluie_probabilite_max_3j,
            humidite=humidite,
            temperature=temperature,
            etp=etp,
            type_sol=type_sol,
            weather_profile=weather_profile,
            history=history,
        )["mm_final_recommande"]
    )


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
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
    humidite: float | None = None,
    temperature: float | None = None,
    etp: float | None = None,
    objectif_mm: float = 0.0,
    hour_of_day: int | None = None,
) -> dict[str, Any]:
    advanced_context = advanced_context or {}
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    besoin_court = max(0.0, -bilan_hydrique_mm)
    besoin_tendance = (deficit_3j * 0.18) + (deficit_7j * 0.06)
    pression_hydrique = besoin_court + besoin_tendance
    pluie_compensatrice = objectif_mm > 0 and (
        pluie_demain >= max(2.0, objectif_mm * 0.8)
        or pluie_j2 >= max(2.0, objectif_mm * 0.8)
        or pluie_3j >= max(4.0, objectif_mm * 1.5)
        or pluie_probabilite_max_3j >= 80.0
    )
    pluie_proche = (
        pluie_24h >= 4
        or pluie_demain >= 4
        or pluie_j2 >= 4
        or pluie_3j >= 6
        or pluie_probabilite_max_3j >= 80.0
    )
    now_hour = hour_of_day if hour_of_day is not None else datetime.now().hour
    now_minutes = now_hour * 60 + int(datetime.now().minute if hour_of_day is None else 0)
    vent = _to_float(advanced_context.get("vent"))
    rosee = _to_float(advanced_context.get("rosee"))
    hauteur_gazon = _to_float(advanced_context.get("hauteur_gazon"))
    optimal_start_minute, optimal_end_minute, acceptable_end_minute, temperature_band = _morning_window_bounds(
        phase_dominante=phase_dominante,
        temperature=temperature,
    )
    heat_stress_level = _heat_stress_level(
        temperature=temperature,
        etp=etp,
        humidite=humidite,
        weather_profile={
            "weather_wind_speed": vent,
            "weather_precipitation": pluie_24h,
            "weather_precipitation_probability": pluie_probabilite_max_3j,
        },
        deficit_mm_brut=max(0.0, max(-bilan_hydrique_mm, deficit_3j, deficit_7j)),
    )
    recent_watering_mm_7j = float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0)
    heat_stress_phase = _heat_stress_phase(
        heat_stress_level=heat_stress_level,
        temperature=temperature,
        etp=etp,
        pluie_demain=pluie_demain,
        pluie_3j=pluie_3j,
        recent_watering_count=int(water_balance.get("arrosage_recent_count_7j", 0) or 0),
        recent_watering_mm_7j=recent_watering_mm_7j,
    )
    evening_allowed = _evening_window_allowed(
        temperature=temperature,
        humidite=humidite,
        water_balance=water_balance,
        objectif_mm=objectif_mm,
        heat_stress_level=heat_stress_level,
    )

    def _window_payload(risque_gazon: str, niveau_action: str, fenetre_optimale: str) -> dict[str, Any]:
        return {
            "niveau_action": niveau_action,
            "fenetre_optimale": fenetre_optimale,
            "risque_gazon": risque_gazon,
            "heat_stress_level": heat_stress_level,
            "watering_window_start_minute": optimal_start_minute,
            "watering_window_end_minute": acceptable_end_minute,
            "watering_window_optimal_start_minute": optimal_start_minute,
            "watering_window_optimal_end_minute": optimal_end_minute,
            "watering_window_acceptable_end_minute": acceptable_end_minute,
            "watering_evening_start_minute": EVENING_START_HOUR * 60,
            "watering_evening_end_minute": EVENING_END_HOUR * 60,
            "watering_window_profile": temperature_band,
            "watering_evening_allowed": evening_allowed,
            "heat_stress_phase": heat_stress_phase,
        }

    if phase_dominante in {"Traitement", "Hivernage"}:
        return _window_payload("faible", "surveiller", "attendre")

    if is_active_rain_weather(advanced_context):
        return _window_payload(
            "modere" if phase_dominante == "Sursemis" else "faible",
            "surveiller" if phase_dominante != "Normal" else "aucune_action",
            "apres_pluie",
        )

    if objectif_mm <= 0:
        return _window_payload(
            "faible" if phase_dominante == "Normal" else "modere",
            "aucune_action" if phase_dominante == "Normal" else "surveiller",
            "apres_pluie" if pluie_proche else "attendre",
        )

    if phase_dominante == "Sursemis":
        niveau_action = "critique" if pression_hydrique >= 2.2 or bilan_hydrique_mm <= -1.5 else "a_faire"
        if pluie_compensatrice or pluie_proche:
            fenetre_optimale = "apres_pluie"
        elif now_minutes < optimal_start_minute:
            fenetre_optimale = "ce_matin"
        elif now_minutes < acceptable_end_minute and (vent is None or vent < 15):
            fenetre_optimale = "maintenant"
        else:
            fenetre_optimale = "demain_matin"
        risque_gazon = "eleve" if bilan_hydrique_mm <= -1.5 or pression_hydrique >= 2.5 else "modere"
        if heat_stress_level in {"canicule", "extreme"}:
            risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
        if vent is not None and vent >= 20:
            risque_gazon = "eleve"
        if hauteur_gazon is not None and hauteur_gazon >= 12:
            risque_gazon = "eleve"
        return _window_payload(risque_gazon, niveau_action, fenetre_optimale)

    if evening_allowed and EVENING_START_HOUR <= now_hour < EVENING_END_HOUR:
        return _window_payload(
            "modere" if heat_stress_level in {"canicule", "extreme"} else "faible",
            "a_faire",
            "soir",
        )

    if pluie_compensatrice:
        return _window_payload("faible", "surveiller", "apres_pluie")

    if humidite >= 85 and bilan_hydrique_mm >= -0.5:
        return _window_payload("faible", "surveiller", "attendre")

    if bilan_hydrique_mm <= -4.0:
        return _window_payload("eleve", "critique", "demain_matin" if now_minutes >= acceptable_end_minute else "maintenant")

    if bilan_hydrique_mm <= -0.8 or pression_hydrique >= 1.5:
        if now_minutes < optimal_start_minute:
            return _window_payload("modere", "a_faire", "ce_matin")
        if now_minutes < acceptable_end_minute:
            return _window_payload("modere", "a_faire", "maintenant")
        return _window_payload("modere", "a_faire", "demain_matin")

    if now_minutes < optimal_start_minute:
        return _window_payload("faible", "a_faire", "ce_matin")
    if now_minutes < acceptable_end_minute:
        return _window_payload("faible", "a_faire", "maintenant")

    risque_gazon = "faible"
    if bilan_hydrique_mm <= -2.5:
        risque_gazon = "eleve"
    elif bilan_hydrique_mm <= -0.8 or pression_hydrique >= 1.2:
        risque_gazon = "modere"
    if vent is not None and vent >= 20:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
    if hauteur_gazon is not None and hauteur_gazon >= 12:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
    if heat_stress_level == "extreme":
        risque_gazon = "eleve"
    elif heat_stress_level in {"canicule", "vigilance"}:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
    if heat_stress_phase == "canicule_prolongee":
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))

    return _window_payload(risque_gazon, "a_faire", "demain_matin")


def compute_next_reevaluation(
    phase_dominante: str,
    niveau_action: str,
    fenetre_optimale: str,
    risque_gazon: str,
    pluie_demain: float | None = None,
    pluie_j2: float | None = None,
    pluie_3j: float | None = None,
    pluie_probabilite_max_3j: float | None = None,
) -> str:
    pluie_demain = pluie_demain or 0.0
    pluie_j2 = pluie_j2 or 0.0
    pluie_3j = pluie_3j or 0.0
    pluie_probabilite_max_3j = pluie_probabilite_max_3j or 0.0

    if fenetre_optimale == "apres_pluie" and (
        pluie_demain > 0 or pluie_j2 > 0 or pluie_3j > 0 or pluie_probabilite_max_3j > 0
    ):
        return "apres_pluie"
    if fenetre_optimale == "ce_matin":
        return "dans quelques heures"
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
