from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import ceil
from typing import Any

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None

from .seasonal_profile import get_seasonal_profile
from .const import (
    KC_GAZON_NORMAL_DEFAUT,
    OBJECTIVE_SCOPE_GLOBAL_SURFACE,
    OBJECTIVE_SCOPE_SURFACE_CYCLE,
    WATERING_STAGE_LEVEE,
    WATERING_STAGE_NORMAL,
    WATERING_STRATEGY_ADULT_DEEP,
    WATERING_STRATEGY_SEMIS_FREQUENT,
)
from .decision_models import normalize_watering_contract
from .watering_policy import resolve_semis_stage_program, resolve_watering_policy
from .water import (
    _is_external_watering,
    compute_recent_watering_count,
    resolve_history_moment,
)

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
OPTIMAL_MORNING_START_HOUR = 3.75  # 03h45 — fenêtre ouverte 15 min avant 04h pour éviter le bord d'heure
OPTIMAL_MORNING_END_HOUR = 8
ACCEPTABLE_MORNING_END_HOUR = 10
SEMIS_WINDOW_START_HOUR = 10
SEMIS_WINDOW_END_HOUR = 17
EVENING_START_HOUR = 18
EVENING_END_HOUR = 20
# Marge de séchage : un arrosage du soir doit finir au moins ce nombre de minutes avant
# le coucher du soleil, pour que l'herbe sèche avant la nuit (sinon risque fongique).
# NB : appliquée hors canicule. En canicule, le rafraîchissement vise le coucher du soleil
# (cf. EVENING_COOLING_START_BEFORE_SUNSET_MIN) — choix assumé de Kévin : arroser au frais
# (moins d'évaporation) plutôt que de garantir le séchage avant la nuit.
EVENING_DRYING_MARGIN_MIN = 90
# Rafraîchissement du soir (canicule) : démarre ce nombre de minutes AVANT le coucher du soleil
# (au plus frais → moins d'évaporation). Remplace l'ancienne fenêtre fixe 18-20 h.
EVENING_COOLING_START_BEFORE_SUNSET_MIN = 30
# Dose du rafraîchissement du soir en canicule extrême : petit arrosage léger destiné à
# faire baisser la température du gazon (PAS à recharger la réserve). Volontairement faible
# pour sécher avant la nuit. Appliqué même réserve saine, sous garde-fous (cf.
# _evening_window_allowed : séchage ≥ 90 min, humidité ≤ 60 %, pas de risque fongique).
EVENING_COOLING_MM = 3.0
# Température réelle minimale (°C) au moment du coucher du soleil pour activer le
# rafraîchissement du soir. Protège contre le faux-positif : le score de stress peut atteindre
# "eleve"/"severe" par un ET0 élevé ou une humidité faible même si la température mesurée
# en fin de journée est modérée (< 30 °C) — dans ce cas le refroidissement du gazon est
# agronomiquement inutile.
EVENING_COOLING_MIN_TEMP = 32.0

# FRACTIONNEMENT EN PHASE NORMAL — dose au-delà de laquelle l'arrosage est coupé en deux passages.
# Porté de 6 à 10 mm le 29/07/2026 sur une base agronomique EXPLICITE : le régime manuel éprouvé de
# Kévin appliquait 8,8 à 10,0 mm en UN SEUL passage (35-40 min par zone à 14/14/17 mm/h), trois fois
# par semaine, avec un gazon en pleine forme et sans ruissellement observé. Un seuil à 6 mm était
# donc plus prudent que sa pratique démontrée : il coupait en deux des doses qui passent sans
# problème, doublant la durée de séance pour rien.
FRACTIONNEMENT_NORMAL_SEUIL_MM = 10.0

# Dose minimale à partir de laquelle la pause entre passages se justifie. En dessous, le
# fractionnement (quand il est imposé par une autre règle) enchaîne les passages sans attente :
# la pause sert l'infiltration, pas la répartition.
PAUSE_LONGUE_MIN_DOSE_MM = 10.0

# Durée de la pause entre deux passages : le temps que le premier s'infiltre.
PAUSE_ENTRE_PASSAGES_MIN = 25
# Température réelle minimale (°C) pour armer la « survie canicule » (le seul override qui
# outrepasse le budget hebdomadaire). Même garde-fou que le rafraîchissement du soir : le score de
# stress composite peut atteindre "severe" dès 30 °C par un ET0 élevé + air sec + déficit, sans
# qu'il s'agisse d'une vraie canicule. Un arrosage de secours qui court-circuite le budget doit être
# réservé à une chaleur RÉELLE, pas à une journée d'été sèche et normale (30 °C ≠ canicule).
SURVIE_CANICULE_MIN_TEMP = 32.0
NORMAL_MIN_USEFUL_SESSION_MM = 10.0
SATURATION_BILAN_HYDRIQUE_MM = 5.0
# Garde-fou hebdo — plafond piloté par la DEMANDE réelle (ETc), en continu, plus par des paliers
# « canicule ». Le gazon perd ~ETc/jour (ETc = ET0 × Kc). Sur 7 jours + une marge de rattrapage,
# on obtient un plafond qui suit la demande à N'IMPORTE QUELLE température (forte ET0 ≠ canicule).
# Plancher = base saisonnière ; plafond de sûreté absolu = _GUARDRAIL_CEILING_MM.
_GUARDRAIL_KC_TYPIQUE = KC_GAZON_NORMAL_DEFAUT  # Kc gazon Normal (FAO-56) : ET0 → ETc
# FACTEUR D'ALIGNEMENT SUR LE Kc RÉEL — et NON une marge de rattrapage, contrairement à ce que
# ce nom et ce commentaire ont longtemps affirmé.
# Le plafond se calcule avec le Kc TYPIQUE (0,80), alors que le Kc réellement appliqué vaut 0,92
# dès qu'une tonte de moins de 8 jours est enregistrée — soit l'état permanent avec une tondeuse
# robot. Or 0,80 × 1,15 = 0,92 : ce facteur rattrape exactement cet écart. Le plafond vaut donc
# 7 jours d'ETc RÉELLE, ce qui est le bon garde-fou : borner à la demande effective du gazon.
# Le RETIRER serrerait le plafond SOUS le besoin réel (33,6 mm/sem au lieu de 38,6 à ET0 = 6) —
# vérifié le 29/07/2026, trois tests le confirment. Ce n'est donc pas du code trompeur à nettoyer,
# c'est un facteur nécessaire mal nommé. Renommé et redocumenté, valeur inchangée.
# Il n'y a par conséquent AUCUNE marge de rattrapage au-dessus de la demande, et c'est assumé :
# élargir un plafond de sûreté autorise plus d'eau, et le rattrapage après plusieurs jours bloqués
# est déjà assuré par la dose (calée sur la déplétion réelle) et par la réserve, qui peut monter
# jusqu'au stock maximal du sol. Le plafond borne, il ne rattrape pas.
_GUARDRAIL_ALIGNEMENT_KC_REEL = 1.15
_GUARDRAIL_CEILING_MM = 50.0         # plafond hebdo de sûreté absolu
MODE_MIN_WATERING_MM = {
    "Normal": 10.0,
    "Sursemis": 0.5,
    "Fertilisation": 3.0,
    "Biostimulant": 5.0,
    "Agent Mouillant": 5.0,
    "Scarification": 5.0,
    "Traitement": 0.0,
    "Hivernage": 0.0,
}
RAINY_WEATHER_CONDITIONS = {
    "rainy",
    "pouring",
    "lightning-rainy",
    "snowy-rainy",
}

SURSEMIS_POLICY_CONFIGS: dict[str, dict[str, float | str]] = {
    "germination_stricte": {
        "surface_bilan_max": 8.0,
        "pluie_24h_max": 1.5,
        # En germination, on laisse une marge plus large avant de bloquer.
        "pluie_demain_max": 3.0,
        "pluie_probabilite_max": 80.0,
        "mm_detected_24h_max": 0.5,
        "temperature_min": 8.0,
        "risk_level": "modere",
        "niveau_action": "a_faire",
        "fenetre_si_ok": "ce_matin",
    },
    "enracinement_prudent": {
        "surface_bilan_max": 7.0,
        "pluie_24h_max": 1.5,
        "pluie_demain_max": 1.5,
        "pluie_probabilite_max": 65.0,
        "mm_detected_24h_max": 0.25,
        "temperature_min": 8.0,
        "risk_level": "modere",
        "niveau_action": "surveiller",
        "fenetre_si_ok": "demain_matin",
    },
    "reprise_prudente": {
        "surface_bilan_max": 6.5,
        "pluie_24h_max": 1.5,
        "pluie_demain_max": 2.0,
        "pluie_probabilite_max": 70.0,
        "mm_detected_24h_max": 0.25,
        "temperature_min": 8.0,
        "risk_level": "faible",
        "niveau_action": "surveiller",
        "fenetre_si_ok": "attendre",
    },
    "reprise_transition": {
        "surface_bilan_max": 6.0,
        "pluie_24h_max": 1.5,
        "pluie_demain_max": 1.5,
        "pluie_probabilite_max": 65.0,
        "mm_detected_24h_max": 0.25,
        "temperature_min": 8.0,
        "risk_level": "faible",
        "niveau_action": "surveiller",
        "fenetre_si_ok": "attendre",
    },
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


def _to_int_or_none(value: Any) -> int | None:
    parsed = _to_float(value)
    return int(parsed) if parsed is not None else None


def _reference_hydric_balance_mm(water_balance: dict[str, Any] | None) -> float:
    water_balance = water_balance or {}
    try:
        return float(water_balance.get("bilan_hydrique_mm") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _hydraulic_pressure(
    bilan_hydrique_mm: float,
    deficit_3j: float,
    deficit_7j: float,
) -> tuple[float, float, float]:
    """Pression hydrique = besoin court terme (déficit du jour) + tendance pondérée 3j/7j."""
    besoin_court = max(0.0, -bilan_hydrique_mm)
    besoin_tendance = (deficit_3j * 0.18) + (deficit_7j * 0.06)
    return besoin_court, besoin_tendance, besoin_court + besoin_tendance


def _parse_history_datetime(value: Any) -> datetime | None:
    """Horodatage d'une VALEUR brute d'historique, en UTC. Conservé pour les appels legacy.

    Pour dater une ENTRÉE d'historique, utiliser `water.resolve_history_moment` : c'est la source
    unique partagée avec la tonte depuis le 29/07/2026. La divergence de 6 h entre les deux
    sous-systèmes (06:00 côté tonte, 00:00 ici, `declared_at` lu d'un seul côté) est résolue là-bas.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text[:10])
        except ValueError:
            return None
        parsed = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_watering_datetime(history: list[dict[str, Any]]) -> datetime | None:
    latest: datetime | None = None
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "arrosage":
            continue
        # Les petits arrosages TECHNIQUES (rafraîchissement du soir ~3 mm, incorporation
        # post-application) sont indépendants de la recharge hydrique : ils ne doivent PAS armer
        # le cooldown 24 h, sinon ils bloqueraient à tort la vraie recharge du lendemain matin.
        if str(item.get("watering_cause") or "").strip().lower() in (
            "rafraichissement_soir",
            "post_application",
        ):
            continue
        # Choix explicite (Kévin, 25/06/2026) : les arrosages EXTERNES (`zone_session`) sont
        # totalement ignorés → ils n'arment PAS non plus le cooldown 24 h (l'intégration pilote
        # son auto-arrosage indépendamment des arrosages manuels/Assist/Node-RED).
        if _is_external_watering(item):
            continue
        # Source unique partagée avec la tonte (cf. water.resolve_history_moment) : même ordre
        # de champs, même repli, même traitement de `declared_at` des deux côtés.
        parsed = resolve_history_moment(item)
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def _latest_phase_start_index(history: list[dict[str, Any]], phase_name: str) -> int | None:
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if isinstance(item, dict) and item.get("type") == phase_name:
            return index
    return None


def _count_tonte_events_since_latest_phase_start(history: list[dict[str, Any]], phase_name: str) -> int:
    start_index = _latest_phase_start_index(history, phase_name)
    if start_index is None:
        return 0
    count = 0
    for item in history[start_index + 1 :]:
        if isinstance(item, dict) and item.get("type") == "tonte":
            count += 1
    return count


def _compute_transition_sursemis_pret(
    *,
    history: list[dict[str, Any]],
    sous_phase: str,
    sous_phase_age_days: int | None,
    sous_phase_progression: float | None,
    hauteur_gazon: float | None,
    water_balance: dict[str, float],
    pluie_24h: float,
    pluie_demain: float,
    pluie_probabilite_24h: float,
    temperature: float,
) -> tuple[bool, int]:
    if sous_phase != "Reprise":
        return False, 0

    tonte_count = _count_tonte_events_since_latest_phase_start(history, "Sursemis")
    age_ok = (sous_phase_age_days or 0) >= 16
    progression_ok = (sous_phase_progression or 0.0) >= 70.0
    tonte_ok = tonte_count >= 2
    height_ok = hauteur_gazon is None or hauteur_gazon >= 6.0
    weather_ok = (
        _reference_hydric_balance_mm(water_balance) <= 2.0
        and pluie_24h < 1.0
        and pluie_demain < 1.0
        and pluie_probabilite_24h < 65.0
        and temperature >= 8.0
    )
    # Température doit être suffisante pour enracinement actif
    temp_ok = temperature >= 12.0  # En dessous, enracinement trop lent même si jours écoulés
    return age_ok and progression_ok and tonte_ok and height_ok and weather_ok and temp_ok, tonte_count


def _select_sursemis_policy(
    *,
    history: list[dict[str, Any]],
    sous_phase: str,
    sous_phase_age_days: int | None,
    sous_phase_progression: float | None,
    hauteur_gazon: float | None,
    water_balance: dict[str, float],
    pluie_24h: float,
    pluie_demain: float,
    pluie_probabilite_24h: float,
    temperature: float,
) -> tuple[str, dict[str, Any], bool, int]:
    transition_ready, tonte_count = _compute_transition_sursemis_pret(
        history=history,
        sous_phase=sous_phase,
        sous_phase_age_days=sous_phase_age_days,
        sous_phase_progression=sous_phase_progression,
        hauteur_gazon=hauteur_gazon,
        water_balance=water_balance,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_probabilite_24h=pluie_probabilite_24h,
        temperature=temperature,
    )
    if sous_phase == "Germination":
        policy_key = "germination_stricte"
    elif sous_phase == "Enracinement":
        policy_key = "enracinement_prudent"
    elif sous_phase == "Reprise":
        policy_key = "reprise_transition" if transition_ready else "reprise_prudente"
    else:
        policy_key = "enracinement_prudent"
    policy = dict(SURSEMIS_POLICY_CONFIGS[policy_key])
    policy["policy_key"] = policy_key
    policy["transition_ready"] = transition_ready
    policy["tonte_count_since_sursemis"] = tonte_count
    return policy_key, policy, transition_ready, tonte_count


def _mode_min_watering_mm(phase_dominante: str) -> float:
    return float(MODE_MIN_WATERING_MM.get(phase_dominante, 0.0))


def _apply_mode_watering_constraints(candidate_mm: float, deficit_mm_brut: float, phase_dominante: str) -> float:
    floor_mm = _mode_min_watering_mm(phase_dominante)
    return _apply_watering_floor_constraints(candidate_mm, deficit_mm_brut, floor_mm)


def _apply_watering_floor_constraints(candidate_mm: float, deficit_mm_brut: float, floor_mm: float) -> float:
    if deficit_mm_brut <= 0:
        return round(floor_mm, 1) if floor_mm > 0 else 0.0
    value = candidate_mm
    if value > 0:
        value = max(value, floor_mm)
    value = min(value, max(deficit_mm_brut, floor_mm))
    return round(max(0.0, value), 1)


def _scarification_soil_humidity_state(
    *,
    saturation_block: bool,
    humidite: float,
) -> str:
    if saturation_block or humidite >= 85:
        return "trop_humide"
    return "legerement_humide"


def _sursemis_micro_apport_decision(
    *,
    policy: dict[str, Any],
    sous_phase: str | None,
    transition_ready: bool,
    pluie_24h: float,
    pluie_demain: float,
    pluie_probabilite_24h: float,
    bilan_hydrique_mm: float,
    mm_detected_24h: float,
    temperature: float,
    humidite: float,
    humidite_sol: float | None,
    vent: float | None,
    soil_profile: str,
) -> dict[str, Any]:
    policy_key = str(policy.get("policy_key") or "enracinement_prudent")
    watering_stage, stage_program = resolve_semis_stage_program(sous_phase, transition_ready=transition_ready)
    surface_bilan_max = float(policy.get("surface_bilan_max") or 2.0)
    pluie_24h_max = float(policy.get("pluie_24h_max") or 1.0)
    pluie_demain_max = float(policy.get("pluie_demain_max") or 1.0)
    pluie_probabilite_max = float(policy.get("pluie_probabilite_max") or 70.0)
    temperature_min = float(policy.get("temperature_min") or 8.0)
    saturation_level = (
        humidite_sol
        if humidite_sol is not None
        else bilan_hydrique_mm
    )
    recent_watering_relief = min(max(mm_detected_24h, 0.0), 3.0)
    saturation_limit = 85.0 if humidite_sol is not None else surface_bilan_max + recent_watering_relief
    surface_sec = (
        pluie_24h <= pluie_24h_max
        and pluie_demain <= pluie_demain_max
        and pluie_probabilite_24h < pluie_probabilite_max
        and saturation_level < saturation_limit
        and temperature > temperature_min
    )
    seuil_declencheur = (
        f"policy={policy_key}, pluie_24h<={pluie_24h_max:.1f}, pluie_demain<={pluie_demain_max:.1f}, "
        f"pluie_probabilite_24h<{pluie_probabilite_max:.0f}%, saturation<{saturation_limit:.1f}, "
        f"temperature>{temperature_min:.1f}"
    )
    allowed = surface_sec
    block_reason = None
    reason = (
        "cycle de surface autorisé, humidité à maintenir."
        if allowed
        else "pluie récente ou prévue, stratégie semis_frequent reportée."
    )
    if not allowed:
        block_reason = "pluie_prevue_suffisante"
        if temperature <= temperature_min:
            block_reason = "temperature_trop_basse"
            reason = "température trop basse, cycle de surface reporté."
        elif saturation_level >= saturation_limit:
            block_reason = "sol_deja_humide"
            reason = "sol déjà trop humide pour un micro-cycle de surface."
        elif pluie_probabilite_24h >= pluie_probabilite_max:
            block_reason = "pluie_probabilite_elevee"
            reason = "pluie probable à court terme, cycle de surface reporté."
        elif pluie_24h >= pluie_24h_max or pluie_demain >= pluie_demain_max:
            block_reason = "pluie_prevue_suffisante"
            reason = "pluie récente ou prévue, stratégie semis_frequent reportée."

    # Garde germination basse température — placé APRÈS le bloc générique pour avoir le dernier
    # mot. Posé avant, il fixait bien `block_reason = "temperature_trop_basse_germination"`, mais
    # son propre `allowed = False` déclenchait aussitôt le bloc ci-dessus qui écrasait le motif par
    # le générique « temperature_trop_basse » : le diagnostic spécifique n'atteignait jamais l'UI.
    if sous_phase in {"Germination", "Levée"} and temperature <= 8.0:
        allowed = False
        block_reason = "temperature_trop_basse_germination"
        reason = "Germination bloquée: température trop basse pour la levée."

    cycle_mm = stage_program.surface_cycle_mm_optimal
    daily_cycles_target = max(stage_program.daily_cycles_min, min(stage_program.daily_cycles_max, stage_program.daily_cycles_min))
    cycle_spacing_minutes = stage_program.cycle_spacing_minutes_max
    if temperature >= 28.0 or (vent or 0.0) >= 15.0 or humidite <= 45.0:
        cycle_mm = min(stage_program.surface_cycle_mm_max, cycle_mm + 0.5)
        daily_cycles_target = min(stage_program.daily_cycles_max, daily_cycles_target + 1)
        cycle_spacing_minutes = stage_program.cycle_spacing_minutes_min
    elif humidite >= 70.0 or pluie_24h > 0.5 or pluie_demain > 0.5:
        cycle_mm = max(stage_program.surface_cycle_mm_min, cycle_mm - 0.5)
        daily_cycles_target = max(stage_program.daily_cycles_min, daily_cycles_target - 1)
        cycle_spacing_minutes = stage_program.cycle_spacing_minutes_max
    elif temperature <= 14.0:
        cycle_mm = max(stage_program.surface_cycle_mm_min, cycle_mm - 0.5)
        cycle_spacing_minutes = max(stage_program.cycle_spacing_minutes_min, stage_program.cycle_spacing_minutes_min)
    cycle_mm = round(_clamp(cycle_mm, stage_program.surface_cycle_mm_min, stage_program.surface_cycle_mm_max), 1)
    runoff_risk = stage_program.runoff_risk
    if soil_profile == "argileux" and cycle_mm >= 2.5:
        runoff_risk = "eleve"
    elif humidite >= 75.0 or pluie_24h >= 0.5:
        runoff_risk = "modere"
    dryness_risk = stage_program.surface_dryness_risk
    if temperature >= 30.0 or (vent or 0.0) >= 20.0 or humidite <= 35.0:
        dryness_risk = "eleve"
    elif temperature >= 26.0 or (vent or 0.0) >= 12.0 or humidite <= 45.0:
        dryness_risk = "modere"

    return {
        "allowed": not bool(block_reason),
        "surface_sec": surface_sec,
        "seuil_declencheur": seuil_declencheur,
        "block_reason": block_reason,
        "reason": reason,
        "pluie_probabilite_24h": round(pluie_probabilite_24h, 1),
        "mm_detected_24h": round(mm_detected_24h, 1),
        "policy_key": policy_key,
        "watering_stage": watering_stage,
        "watering_strategy": WATERING_STRATEGY_SEMIS_FREQUENT,
        "objective_scope": OBJECTIVE_SCOPE_SURFACE_CYCLE,
        "surface_cycle_mm_min": round(stage_program.surface_cycle_mm_min, 1),
        "surface_cycle_mm_max": round(stage_program.surface_cycle_mm_max, 1),
        "surface_cycle_mm": cycle_mm,
        "daily_cycles_target": daily_cycles_target,
        "cycle_spacing_minutes": cycle_spacing_minutes,
        "surface_moisture_target": stage_program.surface_moisture_target,
        "surface_dryness_risk": dryness_risk,
        "runoff_risk": runoff_risk,
        "transition_ready": transition_ready,
        "surface_saturation_level": round(float(saturation_level), 1),
        "surface_saturation_limit": round(float(saturation_limit), 1),
    }


def _policy_weather_inputs(
    *,
    pluie_proche: bool = False,
    pluie_compensatrice: bool = False,
    temperature: float | None = None,
    soil_humidity_state: str | None = None,
    prolonged_drought: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "heavy_rain_expected": pluie_proche,
        "rain_compensating": pluie_compensatrice,
    }
    if temperature is not None:
        payload["temperature_c"] = temperature
    if soil_humidity_state is not None:
        payload["soil_humidity_state"] = soil_humidity_state
    if prolonged_drought:
        payload["prolonged_drought"] = True
    return payload


def _resolve_phase_policy(
    *,
    phase_dominante: str,
    sous_phase: str,
    pluie_proche: bool = False,
    pluie_compensatrice: bool = False,
    temperature: float | None = None,
    humidite: float | None = None,
    saturation_block: bool = False,
    application_type: str | None = None,
    prolonged_drought: bool = False,
) -> Any:
    soil_humidity_state = None
    if phase_dominante == "Scarification":
        soil_humidity_state = _scarification_soil_humidity_state(
            saturation_block=saturation_block,
            humidite=humidite or 0.0,
        )
    return resolve_watering_policy(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        application_type=application_type,
        weather=_policy_weather_inputs(
            pluie_proche=pluie_proche,
            pluie_compensatrice=pluie_compensatrice,
            temperature=temperature,
            soil_humidity_state=soil_humidity_state,
            prolonged_drought=prolonged_drought,
        ),
    )


def _normalize_public_block_reason(policy_reason: str | None) -> str | None:
    if policy_reason == "blocked_by_default":
        return "mode_bloque"
    if policy_reason == "heavy_rain_expected":
        return "pluie_prevue_suffisante"
    if policy_reason == "rain_compensating":
        return "pluie_prevue_suffisante"
    if policy_reason == "temperature_below_minimum":
        return "temperature_trop_basse"
    if policy_reason == "soil_humidity_state_mismatch":
        return "sol_non_adapte"
    return policy_reason


def _build_fractionnement_payload(
    *,
    passages: int,
    pause_minutes: int,
    mm_final: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "enabled": passages > 1,
        "passages": passages,
        "pause_minutes": pause_minutes,
        "max_mm_per_passage": round(mm_final / passages, 1) if passages > 0 and mm_final > 0 else 0.0,
        "reason": reason,
    }


def _build_profile_payload(
    *,
    deficit_mm_brut: float,
    deficit_mm_ajuste: float,
    mm_cible: float,
    mm_final: float,
    besoin_mm: float | None = None,
    mm_detected: float,
    type_arrosage: str,
    arrosage_recommande: bool,
    arrosage_auto_autorise: bool,
    arrosage_conseille: str,
    passages: int,
    pause_minutes: int,
    fractionnement_reason: str,
    niveau_confiance: str,
    confidence_score: int | None,
    confidence_reasons: list[str],
    raison_decision_base: str,
    block_reason: str | None,
    fenetre_optimale: str,
    niveau_action: str,
    risque_gazon: str,
    risque_raisons: list[str] | None = None,
    heat_stress_level: str,
    heat_stress_phase: str,
    morning_start_minute: int,
    acceptable_end_minute: int,
    morning_end_minute: int,
    temperature_band: str,
    evening_allowed: bool,
    recent_watering_count: int,
    recent_watering_mm_7j: float,
    guardrail_min_mm: float,
    guardrail_max_mm: float,
    guardrail_reason: str,
    watering_strategy: str = WATERING_STRATEGY_ADULT_DEEP,
    objective_scope: str = OBJECTIVE_SCOPE_GLOBAL_SURFACE,
    watering_stage: str = WATERING_STAGE_NORMAL,
    surface_cycle_mm: float | None = None,
    daily_cycles_target: int | None = None,
    cycle_spacing_minutes: int | None = None,
    surface_moisture_target: str | None = None,
    surface_dryness_risk: str | None = None,
    runoff_risk: str | None = None,
    surface_saturation_level: float | None = None,
    surface_saturation_limit: float | None = None,
    seeding_transition_ready: bool | None = None,
    seeding_block_reason: str | None = None,
    seasonal_profile: dict[str, Any] | None = None,
    cooldown_24h_hours: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    type_arrosage, arrosage_conseille = normalize_watering_contract(type_arrosage, arrosage_conseille)
    payload = {
        "deficit_brut_mm": round(deficit_mm_brut, 1),
        "deficit_mm_brut": round(deficit_mm_brut, 1),
        "deficit_mm_ajuste": round(deficit_mm_ajuste, 1),
        "mm_cible": round(mm_cible, 1),
        "mm_final_recommande": round(mm_final, 1),
        "mm_final": round(mm_final, 1),
        # ⚠️ BESOIN ≠ DOSE. `mm_final` répond à « combien je vais verser » — donc 0 dès qu'un
        # blocage existe, ce qui est juste. `besoin_mm` répond à « combien il lui faut », et
        # ne bouge pas pour un garde-fou ou un démarrage. Sans lui, l'entité affichait 0,0 mm
        # pendant que ses attributs annonçaient 7,8 mm de déplétion (01/08/2026).
        "besoin_mm": round(float(besoin_mm), 1) if besoin_mm is not None else round(mm_final, 1),
        "mm_requested": round(mm_cible, 1),
        "mm_applied": round(mm_final, 1),
        "mm_detected": round(mm_detected, 1),
        "type_arrosage": type_arrosage,
        "arrosage_recommande": arrosage_recommande,
        "arrosage_auto_autorise": arrosage_auto_autorise,
        "arrosage_conseille": arrosage_conseille,
        "watering_passages": passages,
        "watering_pause_minutes": pause_minutes,
        "fractionnement": _build_fractionnement_payload(
            passages=passages,
            pause_minutes=pause_minutes,
            mm_final=mm_final,
            reason=fractionnement_reason,
        ),
        "niveau_confiance": niveau_confiance,
        "confidence_score": confidence_score,
        "confidence_reasons": confidence_reasons,
        "raison_decision_base": raison_decision_base,
        "block_reason": block_reason,
        "fenetre_optimale": fenetre_optimale,
        "niveau_action": niveau_action,
        "risque_gazon": risque_gazon,
        "risque_gazon_raisons": list(risque_raisons) if risque_raisons else _raisons_par_defaut(
            risque_gazon=risque_gazon,
            heat_stress_level=heat_stress_level,
            block_reason=locals().get("block_reason"),
        ),
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
        "weekly_guardrail_mm_min": guardrail_min_mm,
        "weekly_guardrail_mm_max": guardrail_max_mm,
        "weekly_guardrail_reason": guardrail_reason,
        "watering_strategy": watering_strategy,
        "objective_scope": objective_scope,
        "watering_stage": watering_stage,
        "surface_cycle_mm": round(surface_cycle_mm, 1) if surface_cycle_mm is not None else None,
        "daily_cycles_target": daily_cycles_target,
        "cycle_spacing_minutes": cycle_spacing_minutes,
        "surface_moisture_target": surface_moisture_target,
        "surface_dryness_risk": surface_dryness_risk,
        "runoff_risk": runoff_risk,
        "surface_saturation_level": round(surface_saturation_level, 1) if surface_saturation_level is not None else None,
        "surface_saturation_limit": round(surface_saturation_limit, 1) if surface_saturation_limit is not None else None,
        "seeding_transition_ready": seeding_transition_ready,
        "seeding_block_reason": seeding_block_reason,
        "cooldown_24h_hours": round(cooldown_24h_hours, 1) if cooldown_24h_hours is not None else None,
    }
    if seasonal_profile:
        payload.update(seasonal_profile)
    if extra:
        payload.update(extra)
    return payload


def _current_datetime() -> datetime:
    if dt_util is not None:
        now_getter = getattr(dt_util, "now", None)
        if callable(now_getter):
            current = now_getter()
            if isinstance(current, datetime):
                return current
    return datetime.now().astimezone()


def _current_date() -> date:
    return _current_datetime().date()


def _rain_signals(
    *,
    objective_reference_mm: float,
    pluie_24h: float,
    pluie_demain: float,
    pluie_j2: float,
    pluie_3j: float,
    pluie_probabilite_max_3j: float,
) -> tuple[bool, bool]:
    # Confiance J+1 = 70%, J+2 = 45%, J+3 = 30%
    pluie_demain_effective = pluie_demain * 0.70
    pluie_j2_effective = pluie_j2 * 0.45
    pluie_3j_effective = pluie_3j * 0.30
    # Une forte probabilité de pluie ne doit compter que si la QUANTITÉ prévue est
    # significative : une averse de trace (ex. 0,8 mm annoncée à 80-100 %) ne doit pas
    # bloquer l'arrosage d'un sol sec — sinon on laisse le gazon en stress alors qu'il
    # ne tombera quasiment rien. On exige donc ≥ 4 mm de cumul prévu sur 3 jours.
    proba_pluie_significative = pluie_probabilite_max_3j >= 80.0 and pluie_3j >= 4.0
    pluie_compensatrice = (
        pluie_demain_effective >= max(2.0, objective_reference_mm * 0.8)
        or pluie_j2_effective >= max(2.0, objective_reference_mm * 0.8)
        or pluie_3j_effective >= max(4.0, objective_reference_mm * 1.2)
        or proba_pluie_significative
    )
    pluie_proche = (
        pluie_24h >= 4.0
        or pluie_demain_effective >= 4.0
        or pluie_j2_effective >= 4.0
        or pluie_3j_effective >= 6.0
        or proba_pluie_significative
    )
    return pluie_compensatrice, pluie_proche


def _morning_window_bounds(
    phase_dominante: str, temperature: float | None
) -> tuple[int, int, int, str]:
    # `OPTIMAL_MORNING_START_HOUR` vaut 3,75 (03h45, ouvert 15 min avant 04h pour éviter le bord
    # d'heure) : le produit donnait 225.0, un FLOTTANT, là où toute la chaîne aval déclare des
    # minutes entières. Converti à la source plutôt que d'élargir sept signatures — 225.0 et 225
    # sont interchangeables pour les comparaisons ET pour l'affichage (division entière), ce qui a
    # été prouvé par comparaison d'empreinte sur 8 640 scénarios.
    """Retourne une fenêtre matinale explicite: optimale 4-8h, acceptable jusqu'à 10h."""
    band = _temperature_band(temperature)
    optimal_start = int(OPTIMAL_MORNING_START_HOUR * 60)
    optimal_end = OPTIMAL_MORNING_END_HOUR * 60
    acceptable_end = ACCEPTABLE_MORNING_END_HOUR * 60
    return optimal_start, optimal_end, acceptable_end, band


def _semis_window_bounds(
    *,
    temperature: float | None,
    humidite: float | None,
    vent: float | None,
    pluie_24h: float,
    pluie_demain: float,
) -> tuple[int, int, int, str]:
    """Retourne une fenêtre semis qui autorise les micro-cycles de journée sans relâcher les garde-fous."""
    optimal_start = SEMIS_WINDOW_START_HOUR * 60
    optimal_end = SEMIS_WINDOW_END_HOUR * 60
    acceptable_end = SEMIS_WINDOW_END_HOUR * 60
    band = _temperature_band(temperature)

    vent_value = float(vent or 0.0)
    humidite_value = float(humidite or 0.0)

    # ⚠️ SEULS LES PLAFONDS À 16 H AGISSENT. `acceptable_end` part de SEMIS_WINDOW_END_HOUR = 17 h
    # et n'est jamais relevé : les trois `min(…, 17 * 60)` ci-dessous sont donc l'IDENTITÉ. Ils
    # explicitent des paliers (26-30 °C, vent 12-18, air sec) dont la réponse correcte se trouve
    # être la valeur par défaut — le comportement est juste, mais on pourrait croire en lisant
    # qu'une règle « 26-30 °C = fenêtre réduite » s'applique. Elle ne s'applique pas.
    # Ne PAS « corriger » en abaissant ces paliers sans raison agronomique : ce serait resserrer
    # la fenêtre de semis, pas nettoyer du code.
    if pluie_24h >= 0.5 or pluie_demain >= 0.5 or humidite_value >= 70.0:
        acceptable_end = min(acceptable_end, 16 * 60)
    elif temperature is not None and temperature >= 30.0:
        acceptable_end = min(acceptable_end, 16 * 60)
    elif temperature is not None and temperature >= 26.0:
        acceptable_end = min(acceptable_end, 17 * 60)

    if vent_value >= 18.0:
        acceptable_end = min(acceptable_end, 16 * 60)
    elif vent_value >= 12.0:
        acceptable_end = min(acceptable_end, 17 * 60)

    if humidite_value <= 35.0:
        acceptable_end = min(acceptable_end, 17 * 60)

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
        return "severe"
    if score >= 5:
        return "eleve"
    if score >= 3:
        return "vigilance"
    return "normal"


def _evening_window_allowed(
    temperature: float | None,
    humidite: float | None,
    water_balance: dict[str, float],
    objectif_mm: float,
    heat_stress_level: str = "normal",
    fungal_risk_level: str | None = None,
    minutes_to_sunset: float | None = None,
) -> bool:
    temperature = temperature if temperature is not None else 0.0
    humidite = humidite if humidite is not None else 0.0
    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)

    # Garde-fous universels (valent AUSSI pour le rafraîchissement de canicule) :
    # 1) risque fongique élevé → jamais d'arrosage du soir.
    if fungal_risk_level in {"moderate", "high"}:
        return False
    # 2) séchage : HORS canicule, un arrosage du soir doit finir ≥ 90 min avant le coucher
    #    pour que l'herbe sèche avant la nuit. EN canicule, le rafraîchissement vise justement
    #    le coucher (−30 min) pour arroser au frais → on n'impose pas cette marge (choix assumé,
    #    cf. EVENING_COOLING_START_BEFORE_SUNSET_MIN), la fenêtre du cooling gère le timing.
    if (
        heat_stress_level not in {"eleve", "severe"}
        and minutes_to_sunset is not None
        and minutes_to_sunset < EVENING_DRYING_MARGIN_MIN
    ):
        return False
    # Vague de chaleur (CANICULE ou EXTRÊME) : un petit arrosage de rafraîchissement le soir
    # fait baisser la température du gazon. Son objet est le refroidissement, pas la recharge —
    # il est donc autorisé MÊME quand la réserve est saine (il court-circuite volontairement le
    # garde-fou « pas de soir en saison de végétation »). On accepte « canicule » et pas
    # seulement « extreme » car le soir la température redescend souvent d'un cran : exiger
    # « extreme » au moment du soir ne se déclencherait quasiment jamais. Conditions de sûreté
    # impératives : coucher du soleil connu (+ marge ≥ 90 min déjà vérifiée) et air assez sec,
    # sinon on s'abstient pour ne pas laisser le gazon humide la nuit (dose fixée ailleurs).
    if heat_stress_level in {"eleve", "severe"}:
        if minutes_to_sunset is None or humidite > 60:
            return False
        return True
    # Hors canicule : pas d'arrosage du soir en saison de végétation (avril-septembre) sauf
    # déficit hydrique critique — priorité anti-maladies (gazon humide la nuit = risque).
    today = _current_date()
    if today.month in {4, 5, 6, 7, 8, 9}:
        if bilan_hydrique_mm > -3.0:
            return False
    if temperature < 24:
        return False
    if humidite > 65:
        return False
    # « RIEN REÇU DE TOUTE LA SEMAINE » — et non une erreur d'unité, contrairement à ce qu'un
    # audit avait conclu le 29/07/2026. `arrosage_recent` est bien le cumul SEPT JOURS, et le
    # comparer à 0,25 mm se lit « le gazon n'a reçu strictement rien depuis une semaine ».
    # C'est une condition cohérente pour un arrosage de SECOURS du soir, pas un seuil journalier
    # mal branché. VÉRIFIÉ ATTEIGNABLE : déficit −5 mm, aucun arrosage depuis 7 jours et 26 °C
    # déclenchent bien l'exception. Elle ne dort que tant que l'arrosage fonctionne — c'est-à-dire
    # qu'elle est un filet pour le cas où il ne fonctionne PAS (absence prolongée, arrosage coupé,
    # blocage d'une semaine). Ne pas la « corriger » en lisant l'arrosage du jour : ça la
    # transformerait en exception quotidienne et rouvrirait une voie d'arrosage du soir.
    if arrosage_recent > 0.25:
        return False
    if bilan_hydrique_mm >= -0.3 and deficit_3j <= 0.8:
        return False
    return objectif_mm > 0


def _seasonal_profile_payload(today: date) -> dict[str, Any]:
    profile = get_seasonal_profile(today)
    return {
        "season_label": profile.get("season"),
        "season_phase": profile.get("season_phase"),
        "month_profile": profile.get("month_profile"),
        "watering_bias": profile.get("watering_bias"),
        "mowing_bias": profile.get("mowing_bias"),
        "intervention_bias": profile.get("intervention_bias"),
        "risk_bias": profile.get("risk_bias"),
    }


def _heat_stress_phase(
    heat_stress_level: str,
    temperature: float | None,
    etp: float | None,
    pluie_demain: float,
    pluie_3j: float,
) -> str:
    if heat_stress_level == "normal":
        return "normal"
    if pluie_demain >= 4.0 or pluie_3j >= 6.0:
        return "sortie_de_stress"
    if heat_stress_level == "severe":
        # Stress extrême + ET0 élevée = canicule prolongée quelle que soit la quantité
        # déjà arrosée — pénaliser un jardin correctement arrosé serait contre-productif.
        # Seuil 32 °C (non 34) : "severe" peut se déclencher dès 32 °C via le score
        # combiné (ET0 ≥ 5, humidité sèche, pas de pluie) — exiger 34 bloquerait ces cas.
        if temperature is not None and temperature >= 32 and (etp or 0.0) >= 5.0:
            return "stress_prolonge"
        return "stress_court"
    if heat_stress_level == "eleve":
        if temperature is not None and temperature >= 31 and (etp or 0.0) >= 4.0:
            return "stress_prolonge"
        return "stress_court"
    if temperature is not None and temperature >= 30 and (etp or 0.0) >= 4.0:
        return "stress_court"
    return "normal"


def _dynamic_weekly_guardrail(
    today: date,
    phase_dominante: str,
    et0_mm: float | None,
    soil_profile: str,
) -> tuple[float, float, str]:
    seasonal_profile = get_seasonal_profile(today)
    season = str(seasonal_profile.get("season") or "shoulder")
    season_phase = str(seasonal_profile.get("season_phase") or "normal")
    month_profile = str(seasonal_profile.get("month_profile") or "stable")
    minimum = float(seasonal_profile.get("weekly_budget_min_mm") or 19.0)
    maximum = float(seasonal_profile.get("weekly_budget_max_mm") or 24.0)

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

    # Plafond hebdo = la DEMANDE réelle du gazon, EN CONTINU (fini les paliers « canicule »).
    # Le gazon perd ~ETc/jour (ETc = ET0 × Kc ≈ ET0 × 0,8 en Normal) ; sur 7 jours + une marge de
    # rattrapage, ça donne un plafond qui suit la demande à N'IMPORTE QUELLE température — une forte
    # demande évaporative (ET0 haute, air sec) n'est PAS une canicule. Ainsi : plus de yo-yo 26↔42,
    # et un plafond figé à 28 n'étrangle plus l'arrosage quand la demande grimpe (cause racine
    # constatée 06/2026 : recharge à 5 mm alors que la réserve était à 0). Le vrai « chaud » (survie,
    # rafraîchissement du soir) reste géré ailleurs, sur la température RÉELLE ≥ 32 °C.
    demand_max = 7.0 * max(0.0, et0_mm or 0.0) * _GUARDRAIL_KC_TYPIQUE * _GUARDRAIL_ALIGNEMENT_KC_REEL
    ceiling = _GUARDRAIL_CEILING_MM
    maximum = max(maximum, demand_max)
    minimum = max(minimum, demand_max - 15.0)

    minimum = round(_clamp(minimum, 12.0, ceiling), 1)
    maximum = round(_clamp(maximum, minimum + 4.0, ceiling), 1)
    return (
        minimum,
        maximum,
        (
            f"saison={season}; phase_saison={season_phase}; mois={month_profile}; "
            f"sol={soil_profile}; demande_etc={round(demand_max, 1)}"
        ),
    )


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

    if heat_stress_level in {"eleve", "severe"}:
        score -= 4
        reasons.append(f"stress thermique={heat_stress_level}")
    if heat_stress_phase in {"stress_prolonge", "sortie_de_stress"}:
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


def _raisons_par_defaut(
    *,
    risque_gazon: str,
    heat_stress_level: str | None = None,
    block_reason: str | None = None,
) -> list[str]:
    """Motif de repli pour les chemins qui posent un niveau sans l'expliquer.

    ⚠️ Plusieurs profils (semis, produit, repos…) posent un niveau LITTÉRAL sans raison. Le
    capteur restait donc muet sur ces chemins-là — et une liste vide, masquée par le rendu,
    était indistinguable d'un attribut jamais posé : trois déploiements perdus à chercher où
    la valeur se perdait, le 31/07/2026. Un motif générique vaut mieux que le silence.
    """
    raisons: list[str] = []
    if block_reason:
        raisons.append(str(block_reason))
    # ⚠️ Une raison doit EXPLIQUER le niveau qu'elle accompagne. Sans ce garde, un profil qui
    # pose « risque faible » par littéral sortait « risque_gazon: faible » avec pour seule
    # raison « stress hydrique eleve » — mesuré le 01/08/2026 à 15:32:44 et le 06/08 à
    # 00:00:50. Le lecteur devait alors choisir laquelle des deux sorties croire.
    if (
        heat_stress_level
        and heat_stress_level not in {"normal", "", None}
        and risque_gazon != "faible"
    ):
        raisons.append(f"stress hydrique {heat_stress_level}")
    if not raisons:
        raisons.append(
            "aucun facteur de risque" if risque_gazon == "faible"
            else f"niveau {risque_gazon} posé par le profil courant"
        )
    return raisons


def _evaluer_risque_gazon(
    *,
    water_balance: dict[str, Any] | None,
    bilan_hydrique_mm: float,
    pression_hydrique: float,
    utiliser_reserve: bool = True,
    plancher: str | None = None,
    vent: float | None = None,
    hauteur_gazon: float | None = None,
    heat_stress_level: str = "normal",
    heat_stress_phase: str | None = None,
    seuil_eleve: float = -1.5,
    seuil_modere: float = -0.8,
    seuil_pression_eleve: float = 2.5,
    seuil_pression_modere: float = 1.2,
) -> tuple[str, list[str]]:
    """Niveau de risque du gazon, ET les raisons qui l'expliquent.

    ⚠️ CORRIGÉ le 31/07/2026, sur une question de Kévin (« pourquoi risque élevé ? »).

    Le risque se décidait sur `bilan_hydrique_mm`, qui est le bilan de la JOURNÉE EN COURS
    (pluie + arrosage du jour − ETc du jour). À 2 h du matin, rien n'a encore été arrosé et
    l'ETc attendue vaut ~6 mm : le bilan est donc négatif MÉCANIQUEMENT chaque nuit, quel que
    soit l'état réel du gazon. Mesuré : « risque élevé » la nuit, « faible » à la seconde où
    l'arrosage du matin partait — trois nuits d'affilée dans l'historique. Et 72 scénarios sur
    288 (25 %) affichaient « bilan équilibré » ET « risque élevé » au même instant.

    Ce n'était donc pas « ton gazon est en danger » mais « tu n'as pas encore arrosé aujourd'hui ».

    Le risque se décide désormais sur la RÉSERVE DU SOL quand le ledger en fournit une réelle —
    la vérité physique, qui ne s'effondre pas à minuit. Même recentrage que celui appliqué à
    `hydric_balance_level` en 0.16.0, dont le correctif n'avait jamais été porté ici.
    Sans réserve (ledger vide, tout premier cycle), on retombe sur le bilan journalier : c'est
    le seul signal disponible, et il vaut mieux qu'aucun.

    Les raisons sont retournées pour être exposées en attribut : le capteur n'expliquait pas
    son niveau, il fallait lire le code.
    """
    wb = water_balance or {}
    raisons: list[str] = []

    # ⚠️ `utiliser_reserve=False` en SURSEMIS : un semis n'a pas de réserve exploitable, et la
    # règle du projet interdit d'y étendre le pilotage par déplétion (elle y surestime — c'était
    # la cause du bug d'origine). Le bilan du jour EST le bon signal quand on arrose un semis
    # plusieurs fois par jour. Un test l'a rattrapé.
    if utiliser_reserve and bool(wb.get("reserve_from_soil_ledger")):
        ratio = float(wb.get("depletion_ratio") or 0.0)
        mad = float(wb.get("mad_ratio") or 0.5)
        if ratio >= 1.0:
            niveau = "eleve"
            raisons.append("réserve du sol épuisée")
        elif ratio >= mad:
            niveau = "modere"
            raisons.append(f"réserve sous le seuil d'épuisement ({ratio:.0%} de déplétion)")
        else:
            niveau = "faible"
    else:
        if bilan_hydrique_mm <= seuil_eleve or pression_hydrique >= seuil_pression_eleve:
            niveau = "eleve"
            raisons.append(f"déficit du jour {bilan_hydrique_mm:.1f} mm (sans réserve sol connue)")
        elif bilan_hydrique_mm <= seuil_modere or pression_hydrique >= seuil_pression_modere:
            niveau = "modere"
            raisons.append(f"déficit du jour {bilan_hydrique_mm:.1f} mm (sans réserve sol connue)")
        else:
            niveau = "faible"

    def _monter(motif: str) -> None:
        nonlocal niveau
        avant = niveau
        niveau = _risk_from_rank(min(_risk_rank(niveau) + 1, 2))
        if niveau != avant:
            raisons.append(motif)

    if vent is not None and vent >= 20:
        if niveau != "eleve":
            raisons.append(f"vent soutenu ({vent:.0f} km/h)")
        niveau = "eleve"
    if hauteur_gazon is not None and hauteur_gazon >= 12:
        if niveau != "eleve":
            raisons.append(f"gazon très haut ({hauteur_gazon:.0f} cm)")
        niveau = "eleve"
    if heat_stress_level == "severe":
        if niveau != "eleve":
            raisons.append("stress hydrique sévère")
        niveau = "eleve"
    elif heat_stress_level in {"eleve", "vigilance"}:
        _monter(f"stress hydrique {heat_stress_level}")
    if heat_stress_phase == "stress_prolonge":
        _monter("stress prolongé")

    # PLANCHER — en Sursemis, la phase impose « au moins modéré » quoi qu'en dise l'eau : un
    # semis fragile ne doit jamais être annoncé « sans risque ». Le helper ne peut donc que
    # MONTER au-dessus de ce niveau, jamais descendre en dessous. En phase Normal, aucun
    # plancher : c'est là tout l'objet du correctif — pouvoir redescendre à « faible » quand
    # la réserve du sol est saine.
    if plancher and _risk_rank(niveau) < _risk_rank(plancher):
        niveau = plancher
        raisons.append(f"plancher de phase ({plancher})")

    if not raisons:
        raisons.append("aucun facteur de risque")
    return niveau, raisons


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _build_guidance_window_payload(
    *,
    risque_gazon: str,
    risque_raisons: list[str] | None = None,
    niveau_action: str,
    fenetre_optimale: str,
    heat_stress_level: str,
    heat_stress_phase: str,
    optimal_start_minute: int,
    acceptable_end_minute: int,
    optimal_end_minute: int,
    temperature_band: str,
    evening_allowed: bool,
) -> dict[str, Any]:
    return {
        "niveau_action": niveau_action,
        "fenetre_optimale": fenetre_optimale,
        "risque_gazon": risque_gazon,
        # ⚠️ Cette fonction n'a PAS de `block_reason` dans sa portée : l'appel portait
        # `block_reason=locals().get("block_reason")`, copié depuis `_build_decision_payload`
        # où la variable existe vraiment. Ici l'expression valait donc TOUJOURS None — le
        # motif réel n'arrivait jamais dans les raisons. Retiré plutôt que maquillé : tant
        # que `compute_action_guidance` ne reçoit pas le motif, il n'y a rien à transmettre.
        "risque_gazon_raisons": list(risque_raisons) if risque_raisons else _raisons_par_defaut(
            risque_gazon=risque_gazon,
            heat_stress_level=heat_stress_level,
        ),
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


@dataclass
class _WateringCtx:
    # inputs
    phase_dominante: str
    sous_phase: str
    water_balance: dict[str, Any]
    weather_profile: dict[str, Any]
    history: list[dict[str, Any]]
    today: date
    now: datetime
    pluie_24h: float
    pluie_demain: float
    pluie_j2: float
    pluie_3j: float
    pluie_probabilite_max_3j: float
    pluie_probabilite_24h: float
    humidite: float
    temperature: float
    etp: float
    vent: float | None
    soil_profile: str
    sous_phase_age_days: int | None
    sous_phase_progression: float | None
    hauteur_gazon: float | None
    application_type: str | None
    evening_cooling_enabled: bool
    fungal_risk_level: str | None
    # computed — shared preamble
    now_hour: int
    now_minutes: int
    recent_watering_count: int
    recent_watering_mm_7j: float
    latest_watering_dt: datetime | None
    cooldown_24h_hours: float | None
    cooldown_24h_active: bool
    bilan_hydrique_mm: float
    deficit_jour: float
    deficit_3j: float
    deficit_7j: float
    deficit_mm_brut: float
    pluie_support: float
    deficit_mm_ajuste: float
    heat_stress_level: str
    heat_stress_phase: str
    guardrail_min_mm: float
    guardrail_max_mm: float
    guardrail_reason: str
    seasonal_profile_payload: dict[str, Any]
    # morning window (original, before possible Sursemis override)
    morning_start_minute: int
    morning_end_minute: int
    acceptable_end_minute: int
    temperature_band: str
    # computed — post-preamble (after Hivernage guard)
    besoin_court: float = 0.0
    besoin_tendance: float = 0.0
    pression_hydrique: float = 0.0
    pluie_compensatrice: bool = False
    pluie_proche: bool = False
    saturation_block: bool = False
    evening_allowed: bool = False
    sunset_minute: int | None = None


def _build_watering_ctx(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    today: date,
    pluie_24h: float,
    pluie_demain: float,
    pluie_j2: float,
    pluie_3j: float,
    pluie_probabilite_max_3j: float,
    humidite: float,
    temperature: float,
    etp: float,
    type_sol: str,
    weather_profile: dict[str, Any],
    history: list[dict[str, Any]],
    sous_phase_age_days: int | None,
    sous_phase_progression: float | None,
    hauteur_gazon: float | None,
    application_type: str | None,
    forecast_temperature_today: float | None = None,
    evening_cooling_enabled: bool = True,
    fungal_risk_level: str | None = None,
) -> _WateringCtx:
    pluie_probabilite_24h_raw = _to_float(weather_profile.get("weather_precipitation_probability"))
    pluie_probabilite_24h = pluie_probabilite_24h_raw if pluie_probabilite_24h_raw is not None else 0.0
    vent = _to_float(weather_profile.get("weather_wind_speed"))
    soil_profile = (type_sol or "limoneux").strip().lower()
    # Garde-fou hebdo : on ne compte que les arrosages pilotés par l'intégration (pas les sessions
    # externes `zone_session`), cohérent avec le budget mm exclu côté water.py.
    # ⚠️ LES DEUX TERMES DOIVENT MESURER LA MÊME CHOSE. Ce compteur et `recent_watering_mm_7j`
    # sont combinés par un `and` dans la retenue hebdomadaire, mais ils portaient sur des
    # fenêtres DIFFÉRENTES :
    #   - ici `days=7`, or le filtre retient `delta <= days` → 8 jours calendaires ;
    #   - côté budget, `days=6` → 7 jours, conformément à la règle `days = K-1` que water.py
    #     documente et qu'il applique déjà partout ailleurs (jour=0, 3j=2, 7j=6).
    # Et surtout : ce compteur n'excluait PAS les arrosages manuels, que le budget exclut
    # depuis le 25/07/2026. Le cercle vicieux que cette exclusion avait supprimé pouvait donc
    # se refermer par ici — un arrosage manuel de secours faisait passer le compte de 2 à 3 et
    # RÉARMAIT le blocage qu'il venait précisément de contourner.
    recent_watering_count = (
        compute_recent_watering_count(
            history, today=today, days=6, include_external=False, include_manual=False
        )
        if history
        else 0
    )
    latest_watering_dt = _latest_watering_datetime(history) if history else None
    now = _current_datetime()
    cooldown_24h_hours: float | None = None
    cooldown_24h_active = False
    if phase_dominante == "Normal" and latest_watering_dt is not None:
        local_last = latest_watering_dt.astimezone(now.tzinfo)
        delta_hours = (now - local_last).total_seconds() / 3600.0
        if delta_hours >= 0:
            cooldown_24h_hours = delta_hours
            # « UNE FOIS PAR JOUR », et non « 24 h glissantes » (arbitrage de Kévin, 30/07/2026).
            #
            # Le compte à rebours partait de la FIN du cycle. Comme le cycle dure ~1 h, l'heure
            # autorisée reculait d'autant CHAQUE JOUR : mesuré sur l'install, fin à 06:36 le 28,
            # 07:36 le 29, 08:40 le 30 — et projection à 10:44 le 1er août, soit HORS de la
            # fenêtre du matin (qui ferme à 10:00). L'arrosage se serait bloqué un jour entier
            # en pleine chaleur, puis serait reparti à l'aube, et la dérive aurait recommencé.
            #
            # La règle des 24 h faisait deux métiers : empêcher un second arrosage (voulu) ET
            # fixer l'heure du suivant (effet secondaire non voulu). On ne garde que le premier.
            # La fenêtre du matin rouvre à 04:00 chaque jour → retour à l'aube, conforme à la
            # règle de Kévin « toujours arroser à l'aube ».
            #
            # Comparaison sur la date LOCALE : en UTC, tout ce qui se produit entre minuit et 2 h
            # (heure d'été) porte la date de la veille — l'arrosage du matin serait vu comme
            # « hier » et la garde ne s'armerait pas. Même piège que la falaise de minuit.
            cooldown_24h_active = local_last.date() == now.date()
    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    recent_watering_mm_7j = float(water_balance.get("arrosage_recent_7j", 0.0) or 0.0)
    deficit_mm_brut = max(0.0, max(deficit_jour, deficit_3j, deficit_7j))
    pluie_support = max(
        0.0,
        (pluie_24h * 0.35) + (pluie_demain * 0.35) + (pluie_j2 * 0.2) + (pluie_3j * 0.1),
    )
    historique_support = min(recent_watering_mm_7j * 0.2, deficit_mm_brut * 0.5)
    humidite_penalty = 0.0
    if humidite >= 85:
        humidite_penalty = deficit_mm_brut * 0.2
    elif humidite >= 75:
        humidite_penalty = deficit_mm_brut * 0.1
    deficit_mm_ajuste = max(0.0, deficit_mm_brut - pluie_support - historique_support - humidite_penalty)
    # Utiliser la prévision du maximum journalier si elle dépasse la température actuelle :
    # à l'aube (04h-06h) la temp réelle peut être ≤25°C alors que le pic prévu est >35°C.
    # Sans ce max(), le score thermique reste "vigilance" → garde_fou bloque → arrosage décalé
    # en pleine chaleur. La prévision est fournie par le coordinator via forecast_temperature_today.
    _temp_for_stress = max(temperature, forecast_temperature_today or 0.0)
    # HUMIDITÉ ABSENTE ≠ AIR TOTALEMENT SEC. `_heat_stress_level` garde explicitement le cas
    # `None` (et retombe alors sur l'entité météo), mais l'appelant force `humidite or 0.0` bien
    # en amont : le garde ne voyait donc jamais l'absence, et une humidité manquante était comptée
    # comme 0 % HR — le palier le plus pénalisant, qui monte le score d'un cran et ARME les
    # exemptions d'urgence (dépassement du garde-fou hebdo, du cooldown 24 h).
    # 0 % HR n'existe pas dans la nature (le désert le plus sec tourne autour de 5 %) : on le
    # traite donc comme « pas de mesure », ce qui laisse le repli météo faire son travail.
    _humidite_pour_stress = humidite if humidite else None
    heat_stress_level = _heat_stress_level(
        temperature=_temp_for_stress, etp=etp, humidite=_humidite_pour_stress,
        weather_profile=weather_profile, deficit_mm_brut=deficit_mm_brut,
    )
    heat_stress_phase = _heat_stress_phase(
        heat_stress_level=heat_stress_level, temperature=_temp_for_stress, etp=etp,
        pluie_demain=pluie_demain, pluie_3j=pluie_3j,
    )
    guardrail_min_mm, guardrail_max_mm, guardrail_reason = _dynamic_weekly_guardrail(
        today=today, phase_dominante=phase_dominante,
        et0_mm=etp, soil_profile=soil_profile,
    )
    seasonal_profile_payload = _seasonal_profile_payload(today)
    morning_start_minute, morning_end_minute, acceptable_end_minute, temperature_band = _morning_window_bounds(
        phase_dominante=phase_dominante, temperature=temperature,
    )
    return _WateringCtx(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        water_balance=water_balance,
        weather_profile=weather_profile,
        history=history,
        today=today,
        now=now,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
        pluie_probabilite_24h=pluie_probabilite_24h,
        humidite=humidite,
        temperature=temperature,
        etp=etp,
        vent=vent,
        soil_profile=soil_profile,
        sous_phase_age_days=sous_phase_age_days,
        sous_phase_progression=sous_phase_progression,
        hauteur_gazon=hauteur_gazon,
        application_type=application_type,
        evening_cooling_enabled=evening_cooling_enabled,
        fungal_risk_level=fungal_risk_level,
        now_hour=now.hour,
        now_minutes=now.hour * 60 + now.minute,
        sunset_minute=_to_int_or_none(weather_profile.get("sunset_minute")),
        recent_watering_count=recent_watering_count,
        recent_watering_mm_7j=recent_watering_mm_7j,
        latest_watering_dt=latest_watering_dt,
        cooldown_24h_hours=cooldown_24h_hours,
        cooldown_24h_active=cooldown_24h_active,
        bilan_hydrique_mm=bilan_hydrique_mm,
        deficit_jour=deficit_jour,
        deficit_3j=deficit_3j,
        deficit_7j=deficit_7j,
        deficit_mm_brut=deficit_mm_brut,
        pluie_support=pluie_support,
        deficit_mm_ajuste=deficit_mm_ajuste,
        heat_stress_level=heat_stress_level,
        heat_stress_phase=heat_stress_phase,
        guardrail_min_mm=guardrail_min_mm,
        guardrail_max_mm=guardrail_max_mm,
        guardrail_reason=guardrail_reason,
        seasonal_profile_payload=seasonal_profile_payload,
        morning_start_minute=morning_start_minute,
        morning_end_minute=morning_end_minute,
        acceptable_end_minute=acceptable_end_minute,
        temperature_band=temperature_band,
    )


def _fill_post_preamble(ctx: _WateringCtx) -> None:
    ctx.besoin_court, ctx.besoin_tendance, ctx.pression_hydrique = _hydraulic_pressure(
        ctx.bilan_hydrique_mm, ctx.deficit_3j, ctx.deficit_7j
    )
    ctx.pluie_compensatrice, ctx.pluie_proche = _rain_signals(
        objective_reference_mm=ctx.deficit_mm_brut,
        pluie_24h=ctx.pluie_24h,
        pluie_demain=ctx.pluie_demain,
        pluie_j2=ctx.pluie_j2,
        pluie_3j=ctx.pluie_3j,
        pluie_probabilite_max_3j=ctx.pluie_probabilite_max_3j,
    )
    ctx.saturation_block = ctx.phase_dominante != "Sursemis" and ctx.bilan_hydrique_mm > SATURATION_BILAN_HYDRIQUE_MM
    _minutes_to_sunset = (
        ctx.sunset_minute - ctx.now_minutes if ctx.sunset_minute is not None else None
    )
    ctx.evening_allowed = _evening_window_allowed(
        temperature=ctx.temperature,
        humidite=ctx.humidite,
        water_balance=ctx.water_balance,
        objectif_mm=ctx.deficit_mm_brut,
        heat_stress_level=ctx.heat_stress_level,
        minutes_to_sunset=_minutes_to_sunset,
        # Le garde anti-fongique de `_evening_window_allowed` n'était jamais alimenté : le
        # paramètre gardait sa valeur par défaut None, si bien qu'un risque de maladie élevé
        # n'a jamais empêché un arrosage du soir — alors que gazon humide toute la nuit est
        # précisément le facteur déclenchant.
        fungal_risk_level=ctx.fungal_risk_level,
    )


def _confidence(ctx: _WateringCtx, block_reason: str | None, mm_final: float) -> tuple[int, str, list]:
    # Le score est un ENTIER : `_confidence_assessment` le borne par `int(max(0, min(score, 100)))`.
    # L'annotation `float` faisait diverger ce contrat de celui de `_build_profile_payload`, qui
    # déclare `int | None` — six appels étaient signalés à tort.
    return _confidence_assessment(
        phase_dominante=ctx.phase_dominante,
        temperature=ctx.temperature,
        humidite=ctx.humidite,
        etp=ctx.etp,
        weather_profile=ctx.weather_profile,
        soil_profile=ctx.soil_profile,
        heat_stress_level=ctx.heat_stress_level,
        heat_stress_phase=ctx.heat_stress_phase,
        block_reason=block_reason,
        mm_final=mm_final,
    )


def _profile_for_blocked(ctx: _WateringCtx, block_reason: str) -> dict[str, Any]:
    confidence_score, confidence_level, confidence_reasons = _confidence(ctx, block_reason, 0.0)
    return _build_profile_payload(
        deficit_mm_brut=0.0,
        deficit_mm_ajuste=0.0,
        mm_cible=0.0,
        mm_final=0.0,
        mm_detected=ctx.recent_watering_mm_7j,
        type_arrosage="bloque",
        arrosage_recommande=False,
        arrosage_auto_autorise=False,
        arrosage_conseille="personnalise",
        passages=1,
        pause_minutes=0,
        fractionnement_reason=block_reason,
        niveau_confiance=confidence_level,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        raison_decision_base=f"Phase {ctx.phase_dominante}: arrosage bloqué.",
        block_reason=block_reason,
        fenetre_optimale="attendre",
        niveau_action="surveiller",
        risque_gazon="faible",
        heat_stress_level=ctx.heat_stress_level,
        heat_stress_phase=ctx.heat_stress_phase,
        morning_start_minute=ctx.morning_start_minute,
        acceptable_end_minute=ctx.acceptable_end_minute,
        morning_end_minute=ctx.morning_end_minute,
        temperature_band=ctx.temperature_band,
        evening_allowed=False,
        recent_watering_count=ctx.recent_watering_count,
        recent_watering_mm_7j=ctx.recent_watering_mm_7j,
        guardrail_min_mm=ctx.guardrail_min_mm,
        guardrail_max_mm=ctx.guardrail_max_mm,
        guardrail_reason=ctx.guardrail_reason,
        seasonal_profile=ctx.seasonal_profile_payload,
        cooldown_24h_hours=ctx.cooldown_24h_hours,
    )


def _profile_for_sursemis(ctx: _WateringCtx) -> dict[str, Any]:
    opt_start, _opt_end, acc_end, temp_band = _semis_window_bounds(
        temperature=ctx.temperature,
        humidite=ctx.humidite,
        vent=ctx.vent,
        pluie_24h=ctx.pluie_24h,
        pluie_demain=ctx.pluie_demain,
    )
    resolved_policy = _resolve_phase_policy(
        phase_dominante=ctx.phase_dominante,
        sous_phase=ctx.sous_phase,
    )
    policy_key, sursemis_policy, transition_ready, tonte_count = _select_sursemis_policy(
        history=ctx.history,
        sous_phase=ctx.sous_phase,
        sous_phase_age_days=ctx.sous_phase_age_days,
        sous_phase_progression=ctx.sous_phase_progression,
        hauteur_gazon=ctx.hauteur_gazon,
        water_balance=ctx.water_balance,
        pluie_24h=ctx.pluie_24h,
        pluie_demain=ctx.pluie_demain,
        pluie_probabilite_24h=ctx.pluie_probabilite_24h,
        temperature=ctx.temperature,
    )
    sursemis_state = _sursemis_micro_apport_decision(
        policy=sursemis_policy,
        sous_phase=ctx.sous_phase,
        transition_ready=transition_ready,
        pluie_24h=ctx.pluie_24h,
        pluie_demain=ctx.pluie_demain,
        pluie_probabilite_24h=ctx.pluie_probabilite_24h,
        bilan_hydrique_mm=ctx.bilan_hydrique_mm,
        mm_detected_24h=float(ctx.water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
        temperature=ctx.temperature,
        humidite=ctx.humidite,
        humidite_sol=(
            _to_float(ctx.water_balance.get("humidite_sol"))
            if ctx.water_balance.get("humidite_sol") is not None
            else None
        ),
        vent=ctx.vent,
        soil_profile=ctx.soil_profile,
    )
    mm_cible = float(sursemis_state.get("surface_cycle_mm") or 0.0) if sursemis_state["allowed"] else 0.0
    block_reason = sursemis_state["block_reason"]
    mm_final = mm_cible
    watering_strategy = str(sursemis_state.get("watering_strategy") or WATERING_STRATEGY_SEMIS_FREQUENT)
    objective_scope = str(sursemis_state.get("objective_scope") or OBJECTIVE_SCOPE_SURFACE_CYCLE)
    watering_stage = str(sursemis_state.get("watering_stage") or WATERING_STAGE_LEVEE)
    surface_cycle_mm = float(sursemis_state.get("surface_cycle_mm") or mm_cible or 0.0)
    daily_cycles_target = int(sursemis_state.get("daily_cycles_target") or 1)
    cycle_spacing_minutes = int(sursemis_state.get("cycle_spacing_minutes") or 0)
    type_arrosage = "manuel_frequent" if mm_final > 0 else ("bloque" if block_reason else "aucune_action")
    if policy_key == "reprise_transition":
        if not sursemis_state["allowed"]:
            fenetre_optimale = "attendre"
        elif ctx.now_minutes < opt_start:
            fenetre_optimale = "ce_matin"
        elif ctx.now_minutes < acc_end and (ctx.vent is None or ctx.vent < 15):
            fenetre_optimale = "maintenant"
        else:
            fenetre_optimale = "attendre"
        niveau_action = "surveiller"
        risque_gazon = "modere" if transition_ready else "faible"
    elif policy_key == "germination_stricte":
        fenetre_optimale = "apres_pluie" if ctx.pluie_compensatrice or ctx.pluie_proche else (
            "ce_matin" if ctx.now_minutes < opt_start
            else "maintenant" if ctx.now_minutes < acc_end and (ctx.vent is None or ctx.vent < 15)
            else "demain_matin"
        )
        niveau_action = "critique" if ctx.bilan_hydrique_mm <= -1.0 or ctx.pression_hydrique >= 1.8 else "a_faire"
        risque_gazon = "eleve" if ctx.bilan_hydrique_mm <= -1.0 or ctx.pression_hydrique >= 2.0 else "modere"
    else:
        fenetre_optimale = "apres_pluie" if ctx.pluie_compensatrice or ctx.pluie_proche else (
            "ce_matin" if ctx.now_minutes < opt_start
            else "maintenant" if ctx.now_minutes < acc_end and (ctx.vent is None or ctx.vent < 15)
            else "demain_matin"
        )
        niveau_action = "critique" if ctx.pression_hydrique >= 2.2 or ctx.bilan_hydrique_mm <= -1.5 else "a_faire"
        risque_gazon = "eleve" if ctx.bilan_hydrique_mm <= -1.5 or ctx.pression_hydrique >= 2.5 else "modere"
    risque_gazon, risque_raisons = _evaluer_risque_gazon(
        water_balance=ctx.water_balance,
        bilan_hydrique_mm=ctx.bilan_hydrique_mm,
        pression_hydrique=ctx.pression_hydrique,
        utiliser_reserve=False,          # Sursemis
        plancher=risque_gazon,           # la phase impose son minimum
        vent=ctx.vent,
        hauteur_gazon=ctx.hauteur_gazon,
        heat_stress_level=ctx.heat_stress_level,
    )
    confidence_score, confidence_level, confidence_reasons = _confidence(ctx, block_reason, mm_final)
    return _build_profile_payload(
        deficit_mm_brut=ctx.deficit_mm_brut,
        deficit_mm_ajuste=ctx.deficit_mm_ajuste,
        mm_cible=mm_cible,
        mm_final=mm_final,
        mm_detected=ctx.recent_watering_mm_7j,
        type_arrosage=type_arrosage,
        arrosage_recommande=mm_final > 0,
        arrosage_auto_autorise=False,
        arrosage_conseille="personnalise",
        passages=1,
        pause_minutes=0,
        fractionnement_reason="semis_surface_cycle" if mm_final > 0 else "sursemis_aucune_action",
        niveau_confiance=confidence_level,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        raison_decision_base=(
            f"Sursemis / {ctx.sous_phase}: stratégie semis_frequent en cycle de surface, "
            f"{daily_cycles_target} cycle(s)/jour cible(s), {cycle_spacing_minutes} min entre cycles."
        ),
        block_reason=block_reason,
        fenetre_optimale=fenetre_optimale,
        niveau_action=niveau_action,
        risque_gazon=risque_gazon,
        risque_raisons=risque_raisons,
        heat_stress_level=ctx.heat_stress_level,
        heat_stress_phase=ctx.heat_stress_phase,
        morning_start_minute=ctx.morning_start_minute,
        acceptable_end_minute=ctx.acceptable_end_minute,
        morning_end_minute=ctx.morning_end_minute,
        temperature_band=temp_band,
        evening_allowed=False,
        recent_watering_count=ctx.recent_watering_count,
        recent_watering_mm_7j=ctx.recent_watering_mm_7j,
        guardrail_min_mm=ctx.guardrail_min_mm,
        guardrail_max_mm=ctx.guardrail_max_mm,
        guardrail_reason=ctx.guardrail_reason,
        watering_strategy=watering_strategy,
        objective_scope=objective_scope,
        watering_stage=watering_stage,
        surface_cycle_mm=surface_cycle_mm,
        daily_cycles_target=daily_cycles_target,
        cycle_spacing_minutes=cycle_spacing_minutes,
        surface_moisture_target=str(sursemis_state.get("surface_moisture_target") or ""),
        surface_dryness_risk=str(sursemis_state.get("surface_dryness_risk") or ""),
        runoff_risk=str(sursemis_state.get("runoff_risk") or ""),
        surface_saturation_level=sursemis_state.get("surface_saturation_level"),
        surface_saturation_limit=sursemis_state.get("surface_saturation_limit"),
        seeding_transition_ready=transition_ready,
        seeding_block_reason=block_reason,
        seasonal_profile=ctx.seasonal_profile_payload,
        cooldown_24h_hours=ctx.cooldown_24h_hours,
        extra={
            "mm_detected_24h": sursemis_state["mm_detected_24h"],
            "pluie_probabilite_24h": sursemis_state["pluie_probabilite_24h"],
            "surface_sec": sursemis_state["surface_sec"],
            "sursemis_micro_apport_allowed": sursemis_state["allowed"],
            "sursemis_block_reason": block_reason,
            "sursemis_reason": sursemis_state["reason"],
            "sursemis_seuil_declencheur": sursemis_state["seuil_declencheur"],
            "sursemis_policy": policy_key,
            "sursemis_policy_mode": resolved_policy.selected_mode,
            "sursemis_override_behavior": resolved_policy.override_behavior,
            "sursemis_execution_preferred": (
                resolved_policy.policy.execution.preferred if resolved_policy.policy.execution is not None else None
            ),
            "sursemis_daily_min_mm_per_cycle": (
                resolved_policy.policy.daily_program.min_mm_per_cycle
                if resolved_policy.policy.daily_program is not None else None
            ),
            "sursemis_daily_max_mm_per_cycle": (
                resolved_policy.policy.daily_program.max_mm_per_cycle
                if resolved_policy.policy.daily_program is not None else None
            ),
            "sursemis_daily_min_cycles": (
                resolved_policy.policy.daily_program.min_cycles_per_day
                if resolved_policy.policy.daily_program is not None else None
            ),
            "sursemis_daily_max_cycles": (
                resolved_policy.policy.daily_program.max_cycles_per_day
                if resolved_policy.policy.daily_program is not None else None
            ),
            "sursemis_transition_ready": transition_ready,
            "sursemis_tonte_count": tonte_count,
            "watering_strategy": watering_strategy,
            "objective_scope": objective_scope,
            "watering_stage": watering_stage,
            "surface_cycle_mm": surface_cycle_mm,
            "daily_cycles_target": daily_cycles_target,
            "cycle_spacing_minutes": cycle_spacing_minutes,
            "surface_moisture_target": sursemis_state.get("surface_moisture_target"),
            "surface_dryness_risk": sursemis_state.get("surface_dryness_risk"),
            "runoff_risk": sursemis_state.get("runoff_risk"),
            "surface_saturation_level": sursemis_state.get("surface_saturation_level"),
            "surface_saturation_limit": sursemis_state.get("surface_saturation_limit"),
            "seeding_transition_ready": transition_ready,
            "seeding_block_reason": block_reason,
        },
    )


def _profile_for_traitement(ctx: _WateringCtx) -> dict[str, Any]:
    resolved_policy = _resolve_phase_policy(
        phase_dominante=ctx.phase_dominante,
        sous_phase=ctx.sous_phase,
        application_type=ctx.application_type,
        pluie_proche=ctx.pluie_proche,
        pluie_compensatrice=ctx.pluie_compensatrice,
    )
    target_range = resolved_policy.target_range
    minimum = target_range.min_mm if target_range is not None else 0.0
    maximum = target_range.max_mm if target_range is not None else 0.0
    mm_cible = 0.0
    block_reason = None
    if resolved_policy.blocking.is_blocked:
        block_reason = _normalize_public_block_reason(resolved_policy.blocking.reason)
    elif resolved_policy.override_behavior == "block_watering":
        block_reason = "application_foliaire"
    else:
        mm_cible = _clamp((ctx.besoin_court * 0.4) + (ctx.besoin_tendance * 0.08), minimum, maximum)
        mm_cible = _apply_watering_floor_constraints(mm_cible, ctx.deficit_mm_brut, minimum)
    mm_final = 0.0 if block_reason else mm_cible
    passages = 1 if mm_final <= 4.0 else 2
    pause_minutes = 25 if passages > 1 else 0
    confidence_score, confidence_level, confidence_reasons = _confidence(ctx, block_reason, mm_final)
    return _build_profile_payload(
        deficit_mm_brut=ctx.deficit_mm_brut,
        deficit_mm_ajuste=ctx.deficit_mm_ajuste,
        mm_cible=mm_cible,
        mm_final=mm_final,
        mm_detected=float(ctx.water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
        type_arrosage=(
            "bloque"
            if block_reason in {"application_type_required", "unsupported_application_type", "application_foliaire"}
            else "auto" if mm_final > 0 else "aucune_action"
        ),
        arrosage_recommande=mm_final > 0 and block_reason is None,
        arrosage_auto_autorise=mm_final > 0 and block_reason is None,
        arrosage_conseille="personnalise" if block_reason else "auto" if mm_final > 0 else "aucune_action",
        passages=passages,
        pause_minutes=pause_minutes,
        fractionnement_reason="managed_fractionation" if passages > 1 else "single_pass",
        niveau_confiance=confidence_level,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        raison_decision_base=f"Traitement ({ctx.application_type or 'inconnu'}): application dépendante du produit.",
        block_reason=block_reason,
        fenetre_optimale="ce_matin" if mm_final > 0 else "attendre",
        niveau_action="a_faire" if mm_final > 0 else "surveiller",
        risque_gazon="faible" if mm_final > 0 else "modere",
        heat_stress_level=ctx.heat_stress_level,
        heat_stress_phase=ctx.heat_stress_phase,
        morning_start_minute=ctx.morning_start_minute,
        acceptable_end_minute=ctx.acceptable_end_minute,
        morning_end_minute=ctx.morning_end_minute,
        temperature_band=ctx.temperature_band,
        evening_allowed=ctx.evening_allowed,
        recent_watering_count=ctx.recent_watering_count,
        recent_watering_mm_7j=float(ctx.water_balance.get("arrosage_recent_7j", 0.0) or 0.0),
        guardrail_min_mm=ctx.guardrail_min_mm,
        guardrail_max_mm=ctx.guardrail_max_mm,
        guardrail_reason=ctx.guardrail_reason,
        seasonal_profile=ctx.seasonal_profile_payload,
        extra={"application_type": ctx.application_type},
    )


def _profile_for_normal(ctx: _WateringCtx) -> dict[str, Any]:
    resolved_policy = _resolve_phase_policy(
        phase_dominante=ctx.phase_dominante,
        sous_phase=ctx.sous_phase,
        pluie_proche=ctx.pluie_proche,
        pluie_compensatrice=ctx.pluie_compensatrice,
    )
    normal_weekly_range = resolved_policy.target_range
    normal_execution = resolved_policy.policy.execution
    weekly_min_mm = normal_weekly_range.min_mm if normal_weekly_range is not None else ctx.guardrail_min_mm
    weekly_max_mm = normal_weekly_range.max_mm if normal_weekly_range is not None else ctx.guardrail_max_mm
    # En canicule, le garde-fou hebdo dynamique (ETc-aware, cf. _dynamic_weekly_guardrail) doit
    # pouvoir DÉPASSER la plage hebdo "normale" de la politique. Sinon le plafond normal (30 mm)
    # ré-écrase la dose de canicule (~45 mm/sem de besoin) et le gazon sèche malgré la chaleur.
    weekly_max_mm = max(weekly_max_mm, ctx.guardrail_max_mm)
    min_session_mm = normal_execution.min_session_mm if normal_execution is not None else NORMAL_MIN_USEFUL_SESSION_MM
    max_session_mm = normal_execution.max_session_mm if normal_execution is not None else None
    rain_adjustment = min(ctx.pluie_support * 0.7, 5.0)
    guardrail_min_effective = round(
        _clamp(max(min_session_mm, ctx.guardrail_min_mm - rain_adjustment), weekly_min_mm, weekly_max_mm), 1,
    )
    guardrail_max_effective = round(
        _clamp(
            max(guardrail_min_effective + 4.0, ctx.guardrail_max_mm - rain_adjustment),
            guardrail_min_effective + 4.0,
            weekly_max_mm,
        ), 1,
    )
    # Déplétion RÉELLE (et non anticipée) pour les seuls OVERRIDES D'URGENCE ci-dessous. Le ledger
    # débite tout l'ET0 du jour dès minuit → `depletion_ratio` sature dès 00h01 (« falaise de
    # minuit ») alors qu'aucune évapotranspiration n'a encore eu lieu. Déclencher une URGENCE
    # (outrepasser le cooldown ou le garde-fou hebdo) sur cette déplétion anticipée revenait à
    # armer une fausse urgence nocturne. On ne compte donc, pour l'urgence, que l'ET RÉELLEMENT
    # écoulée (`et_elapsed_fraction`, 0 au lever → 1 au coucher) : `depletion_réelle = depletion −
    # ET0·(1−fraction)`. Le pilotage NORMAL (mm_cible) reste anticipatif — il continue de planifier
    # l'arrosage du matin. Appliqué au seul chemin ledger (source de la falaise) ; repli sûr :
    # fraction/soleil inconnu → 1.0 → déplétion anticipée = comportement historique.
    _depletion_ratio_urgence = float(ctx.water_balance.get("depletion_ratio") or 0.0)
    # Déplétion critique : réserve très basse (≥ 80 % RÉELLEMENT épuisée). Dans ce cas seulement, on
    # autorise l'arrosage à outrepasser le cooldown 24 h — respecter le délai laisserait le gazon en
    # stress sévère. Les autres blocages (pluie, sol détrempé) restent prioritaires.
    _critical_depletion = _depletion_ratio_urgence >= 0.8
    # Survie canicule : réserve quasi épuisée (≥ 90 % RÉELLEMENT) ET vraie chaleur. Dans ce seul cas,
    # on autorise un petit cycle de survie même si le garde-fou hebdomadaire est atteint — laisser le
    # sol à 0 en pleine chaleur dépasse le « stress bénéfique » et grille le gazon. Double garde pour
    # ne PAS armer cet override (le seul qui court-circuite le budget) sur une journée d'été sèche mais
    # normale : le score de stress composite peut dire "severe" dès 30 °C (ET0 + air sec + déficit),
    # donc on exige EN PLUS une température réelle ≥ SURVIE_CANICULE_MIN_TEMP. Blocages pluie réelle /
    # sol détrempé restent prioritaires.
    _survie_canicule = (
        _depletion_ratio_urgence >= 0.9
        and ctx.heat_stress_level in {"eleve", "severe"}
        and (ctx.temperature or 0.0) >= SURVIE_CANICULE_MIN_TEMP
    )
    # Quand le bilan sol interne (ledger, mis à jour en TEMPS RÉEL) est actif et indique que
    # la réserve est sous le seuil d'épuisement (MAD), c'est LUI qui fait foi pour l'état du
    # sol : on n'applique plus les blocages « sol déjà humide » / « humidité excessive »
    # dérivés du `bilan_hydrique_mm` GLISSANT — celui-ci peut rester positif tout le lendemain
    # d'un gros arrosage et bloquait alors à tort la recharge du matin alors que la réserve
    # réelle est épuisée. La pluie réelle et l'humidité de l'AIR (≥ 85 %) restent prioritaires.
    _ledger_reserve = bool(ctx.water_balance.get("reserve_from_soil_ledger"))
    _depletion_ratio = float(ctx.water_balance.get("depletion_ratio") or 0.0)
    _mad_ratio = float(ctx.water_balance.get("mad_ratio") or 0.5)
    _ledger_demande_eau = _ledger_reserve and _depletion_ratio >= _mad_ratio
    # RÉSERVE RÉELLEMENT VIDE — exemption indépendante de la température.
    # Depuis que le ledger débite l'ET0 au prorata de la journée (plus de « falaise de minuit »),
    # `_depletion_ratio` (dérivé de la réserve RÉELLE) reflète l'état vrai du sol à tout instant,
    # à l'aube comme en journée. Si la réserve est genuinement quasi vide (≥ 90 % épuisée), le
    # gazon a soif POUR DE VRAI et doit pouvoir arroser MÊME sous 32 °C — sinon un sol réellement
    # à sec reste bloqué par le garde-fou hebdo (qui plafonne surtout un sur-arrosage HÉRITÉ) ou
    # par le cooldown d'un petit arrosage manuel de secours (constaté 25/07/2026 : réserve à 0,
    # 31 °C prévus < 32, rien ne s'est déclenché à l'aube). Distinct de la survie canicule
    # (basée sur la CHALEUR) et de `_depletion_ratio_urgence` (qui retranche l'ET0 non écoulée pour
    # ne pas ARMER une recharge ANTICIPÉE la nuit) : ici on constate un FAIT — la réserve est vide —
    # pas une projection. Ne s'arme qu'avec le bilan sol interne actif (jamais sur le modèle déficit).
    # ET on exige une DEMANDE réelle (`heat_stress_level` ≠ « normal ») : par temps frais à ET0
    # faible (ex. 15 °C), une réserve « vide » n'est pas une urgence — le gazon ne transpire quasi
    # pas, on peut attendre pluie/fraîcheur. Le secours ne se justifie que si le sol est vide ET la
    # journée demandante (au moins « vigilance »).
    _reserve_critique_reelle = (
        _ledger_reserve
        and _depletion_ratio >= 0.9
        and ctx.heat_stress_level in {"vigilance", "eleve", "severe"}
    )
    # ⚠️ UNE PRÉVISION NE BLOQUE PAS UN SOL QUI A DÉJÀ SOIF.
    # Les quatre autres blocages ci-dessous ont tous une échappatoire quand le sol est
    # réellement sec (`not _reserve_critique_reelle`, `not _ledger_demande_eau`,
    # `not _survie_canicule`). La pluie était le SEUL à bloquer sans condition — et c'est
    # le seul qui repose sur une PRÉVISION, donc le moins fiable des cinq.
    # Nuit du 02/08/2026 : à 03 h 20, la prévision passe de 3,1 à 9,1 mm. L'objectif tombe de
    # 8,6 à 0,0 et y reste jusqu'à 10 h 13 — TOUTE la fenêtre d'arrosage (03:45–10:00) — alors
    # que le même cycle publiait `reserve_actuelle_mm: 1,2 sur 12`, `hydric_state: critique`,
    # `hydric_strategy: arroser rapidement en profondeur` et 34,5 °C prévus. Il est tombé
    # 3,2 mm effectifs pour 4,8 mm consommés : la réserve a touché ZÉRO à 12 h 09.
    # Arbitrage de Kévin, 02/08/2026 : « la pluie prévue n'est jamais sûre, je préfère arroser ».
    # Le seuil retenu est le MAD — le même que celui qui déclenche l'arrosage. Autrement dit :
    # tant que le sol est confortable, une pluie annoncée fait encore économiser un cycle ;
    # dès qu'il réclame, la prévision ne décide plus à sa place.
    # ⚠️ Volontairement SANS la condition `_ledger_reserve` de `_ledger_demande_eau` : ce garde
    # ne peut que DÉBLOQUER, jamais bloquer. Le faire dépendre d'une source qui peut manquer le
    # rendrait inerte au pire moment — précisément le défaut qu'on passe la semaine à corriger.
    _sol_reclame_de_l_eau = _depletion_ratio >= _mad_ratio

    block_reason = None
    if (ctx.pluie_compensatrice or ctx.pluie_proche) and not _sol_reclame_de_l_eau:
        block_reason = "pluie_prevue_suffisante"
    elif ctx.cooldown_24h_active and not _critical_depletion and not _reserve_critique_reelle:
        block_reason = "cooldown_24h"
    elif ctx.saturation_block and not _ledger_demande_eau:
        block_reason = "sol_deja_humide"
    elif ctx.humidite >= 85 or (ctx.bilan_hydrique_mm > 0.5 and not _ledger_demande_eau):
        block_reason = "humidite_excessive"
    elif (
        ctx.recent_watering_count >= 3
        and ctx.recent_watering_mm_7j >= ctx.guardrail_min_mm
        and ctx.deficit_mm_ajuste < ctx.guardrail_min_mm
        # ⚠️ Un déficit INCONNU n'est pas un déficit nul. Sans ET0, `deficit_mm_ajuste` vaut 0
        # par défaut — la condition ci-dessus devient vraie automatiquement et la retenue se
        # déclenche sur du vide. Constaté le 01/08/2026 : au premier cycle d'un redémarrage
        # (capteur de température pas encore là) le motif `garde_fou_hebdomadaire` apparaissait
        # alors que la réserve était à 3,8 mm pour un seuil à 6,0. Sur une coupure plus longue
        # du capteur, la même mécanique a supprimé l'objectif pendant 20 min DANS la fenêtre
        # d'arrosage (30/07, 08 h 13 → 08 h 33). La retenue exige désormais un déficit MESURÉ.
        and bool(ctx.water_balance.get("etp_connue", True))
        # ⚠️ LA RETENUE DOIT JUGER SUR LA MÊME GRANDEUR QUE LE DÉCLENCHEMENT.
        # `deficit_mm_ajuste` vient du modèle LEGACY ; le déclenchement, lui, se fait sur la
        # déplétion du LEDGER. Les deux divergent, et c'est la retenue qui gagnait.
        # Matin du 01/08/2026, 04 h 00 : déficit legacy 4,3 mm (« pas besoin », car < plancher
        # 21) contre déplétion réelle 6,6 mm sur 12 → ratio 0,55, AU-DESSUS du MAD 0,50. Le même
        # cycle publiait `hydric_state: depletion` et `hydric_strategy: arroser profondément`,
        # et l'arrosage n'est pas parti. Sans eau ce matin-là, le sol est arrivé au 02/08 à
        # 1,2 mm, puis à ZÉRO. Le legacy sous-estimait de 2,3 mm.
        # Ce garde ne vide PAS le garde-fou de son sens : `_depletion_ratio` est la déplétion
        # RÉELLE, alors que le déclenchement se fait sur la déplétion PROJETÉE (réelle + ETc
        # restante). Un sol encore confortable à l'aube mais qui aura soif ce soir déclenche
        # toujours — et reste donc retenable. C'est exactement le cas du 31/07 (ratio réel
        # 0,283), où le blocage était légitime et le reste.
        # L'intention écrite du garde-fou est de « plafonner un sur-arrosage HÉRITÉ » : un sol
        # au-delà du seuil de déclenchement n'est pas du sur-arrosage.
        and not _sol_reclame_de_l_eau
        and not _survie_canicule
        and not _reserve_critique_reelle
    ):
        block_reason = "garde_fou_hebdomadaire"
    # Mode Normal (pelouse établie).
    # Si le bilan sol interne fournit une réserve réelle (ledger soil_balance tenu par
    # l'intégration), on pilote par épuisement de la réserve utile : on laisse descendre
    # jusqu'au seuil MAD (épuisement autorisé) puis on recharge en profondeur jusqu'au
    # plein utile — arrosages espacés, enracinement profond, mini-stress sain, borné par le
    # garde-fou hebdomadaire (cap dur). Sans réserve sol (ex. tout premier cycle, ledger
    # vide), la réserve dérive du bilan court et n'atteindrait pas le seuil : on retombe
    # alors sur le modèle déficit (legacy), plus prudent. La dépletion reste cantonnée à
    # Normal : en Sursemis elle surestimait (recharge profonde inadaptée au semis), d'où
    # _profile_for_sursemis.
    # Besoin RÉEL du sol, indépendant des politiques (garde-fou, blocages). Initialisé ici
    # pour couvrir aussi le cas « sol au-dessus du seuil » : il n'a alors besoin de rien, et
    # 0 est la bonne réponse — mais elle doit être calculée, pas laissée indéfinie.
    besoin_mm = 0.0
    reserve_from_ledger = bool(ctx.water_balance.get("reserve_from_soil_ledger"))
    if reserve_from_ledger:
        depletion_ratio = float(ctx.water_balance.get("depletion_ratio") or 0.0)
        mad_ratio = float(ctx.water_balance.get("mad_ratio") or 0.5)
        depletion_mm = float(ctx.water_balance.get("depletion_mm") or 0.0)
        # DÉCLENCHEMENT ANTICIPÉ, DOSE RÉELLE.
        # Depuis que le ledger débite l'ET0 au fil de la journée, `depletion_ratio` ne franchit le
        # seuil MAD qu'une fois la soif RÉELLEMENT installée — donc souvent en milieu de journée,
        # le pire moment pour arroser. Or l'arrosage doit TOUJOURS partir à l'aube (évaporation
        # minimale, feuillage sec avant la nuit). On déclenche donc sur la déplétion PROJETÉE en
        # fin de journée = déplétion actuelle + ET0 qu'il reste à s'écouler. À l'aube cela répond
        # à la bonne question : « le sol va-t-il manquer d'eau aujourd'hui ? ».
        # La DOSE, elle, reste calée sur la déplétion RÉELLE, c'est-à-dire la place réellement
        # disponible dans le sol : verser au-delà ne ferait que drainer sous les racines — c'était
        # la cause du sur-arrosage (~59 mm/semaine appliqués pour ~33 mm de besoin ETc).
        # Les URGENCES (survie canicule, déplétion critique) gardent volontairement la déplétion
        # réelle via `_depletion_ratio_urgence` : pas de fausse urgence armée la nuit.
        _reserve_utile_decl = float(ctx.water_balance.get("reserve_utile_mm") or 0.0)
        if _reserve_utile_decl > 0:
            _frac_decl_raw = ctx.water_balance.get("et_elapsed_fraction")
            _frac_decl = float(_frac_decl_raw) if _frac_decl_raw is not None else 1.0
            # On projette l'ETc (ET0 × Kc), PAS l'ET0 brute : le sol perd son eau au rythme de
            # l'herbe, et c'est bien l'ETc que le ledger débite (0.17.3). Projeter l'ET0 gonflait
            # la soif prévue de ~25 % et pouvait déclencher un arrosage le LENDEMAIN d'une recharge
            # complète (réserve pleine, déplétion ≈ 0 : ET0 6,1 → ratio 0,51 > MAD 0,50 → arrosage
            # inutile ; ETc 4,9 → 0,41, pas d'arrosage). Repli sur le Kc typique si l'ETc n'est pas
            # fournie, pour garder la même unité plutôt que de retomber sur l'ET0 brute.
            _etc_projection = ctx.water_balance.get("etc_mm")
            if _etc_projection is None:
                _etc_projection = float(ctx.water_balance.get("et0_mm") or 0.0) * _GUARDRAIL_KC_TYPIQUE
            _etc_restant = float(_etc_projection or 0.0) * max(0.0, 1.0 - _frac_decl)
            depletion_ratio = min(1.0, (depletion_mm + _etc_restant) / _reserve_utile_decl)
        if depletion_ratio < mad_ratio:
            mm_cible = 0.0
        else:
            mm_cible = max(depletion_mm, min_session_mm)
            if max_session_mm is not None:
                mm_cible = min(mm_cible, max_session_mm)
            # BESOIN DU SOL, avant toute politique. `mm_cible` va ensuite être rogné par le
            # garde-fou hebdomadaire puis remis à zéro par un éventuel blocage : la question
            # « combien il lui faut » n'aurait plus aucune réponse lisible. C'est exactement ce
            # que Kévin a vu le 01/08/2026 — l'entité « Objectif d'arrosage » affichait 0,0 mm
            # pendant que ses propres attributs annonçaient 7,8 mm de déplétion.
            besoin_mm = mm_cible
            weekly_room = max(0.0, guardrail_max_effective - ctx.recent_watering_mm_7j)
            if _survie_canicule:
                # Réserve à 0 en canicule : garantir la recharge complète (depletion_mm)
                # même si le budget hebdo est épuisé — laisser le sol à sec en pleine
                # canicule extrême dépasse le simple « stress bénéfique ». Sinon le
                # garde-fou bloque à min_session_mm (5 mm) alors qu'ET0 ≈ 8-9 mm/j et
                # qu'aucune dose inférieure ne permet de sortir du plancher à 0.
                _survie_floor = depletion_mm if depletion_ratio >= 1.0 else min_session_mm
                weekly_room = max(weekly_room, _survie_floor)
            elif _reserve_critique_reelle:
                # Réserve réellement vide MAIS sous 32 °C : on débloque un arrosage de SECOURS
                # MODÉRÉ (min_session ~5 mm) au lieu de la recharge complète. Assez pour maintenir
                # le gazon un jour de plus sans le laisser bone-dry, mais on ne recharge pas à fond
                # hors canicule (la recharge pleine reste réservée à `_survie_canicule` ≥ 32 °C,
                # cf. règle 0.16.0). Le garde-fou plafonne un sur-arrosage HÉRITÉ, pas ce secours.
                weekly_room = max(weekly_room, min_session_mm)
            mm_cible = round(min(mm_cible, weekly_room), 1)
        if block_reason is not None:
            mm_cible = 0.0
        mm_final = mm_cible
    else:
        useful_threshold = max(min_session_mm, guardrail_min_effective * 0.5)
        if ctx.deficit_mm_ajuste < useful_threshold:
            mm_cible = 0.0
        else:
            upper_bound = min(guardrail_max_effective, ctx.deficit_mm_brut)
            if upper_bound <= guardrail_min_effective:
                mm_cible = upper_bound
            else:
                mm_cible = _clamp(
                    max(ctx.deficit_mm_ajuste, guardrail_min_effective),
                    guardrail_min_effective,
                    upper_bound,
                )
        besoin_mm = mm_cible
        if block_reason is not None:
            mm_cible = 0.0
        else:
            mm_cible = _apply_watering_floor_constraints(mm_cible, ctx.deficit_mm_brut, min_session_mm)
        mm_final = mm_cible
        if not block_reason and mm_final > 0:
            _reserve_max = float(ctx.water_balance.get("reserve_stock_max_mm") or 0.0)
            _reserve_cur = float(ctx.water_balance.get("reserve_stock_mm") or 0.0)
            _depletion_r = float(ctx.water_balance.get("depletion_ratio") or 0.0)
            _mad = float(ctx.water_balance.get("mad_ratio") or 0.5)
            if _reserve_max > 0 and _depletion_r < _mad:
                _fill_cap = max(0.0, _reserve_max - _reserve_cur)
                mm_cible = round(min(mm_cible, _fill_cap), 1)
                mm_final = mm_cible
    # Rafraîchissement du soir en canicule : LE SOIR = TOUJOURS COOLING, JAMAIS DE RECHARGE.
    # Dans la fenêtre du soir (canicule, air sec + marge de séchage déjà garantis par
    # _evening_window_allowed), on applique un PETIT arrosage de cooling (3 mm) pour faire baisser
    # la température du gazon — MÊME si une recharge de déficit était prévue à cet instant. Toute
    # vraie recharge (hydrique) est alors REPORTÉE à la fenêtre du matin (au frais), où elle arme
    # le cooldown 24 h. Conséquence voulue : un arrosage du soir n'arme JAMAIS le cooldown et ne
    # bloque donc plus la recharge du lendemain matin (fin du cercle soir→cooldown→matin bloqué).
    # On ne court-circuite que les blocages « budget d'eau » (réserve saine, cooldown, garde-fou
    # hebdo) ; une vraie pluie ou un sol détrempé restent prioritaires (pas de cooling alors).
    mm_before_cooling = mm_final  # dose de recharge qui aurait été appliquée (reportée au matin)
    # Fenêtre du rafraîchissement : démarre 30 min AVANT le coucher du soleil (au frais), au lieu
    # de la fenêtre fixe 18-20 h (trop tôt = grosse évaporation en pleine chaleur). Nécessite que
    # le coucher soit connu (capteur sun.sun → sunset_minute).
    cooling_window = (
        ctx.sunset_minute is not None
        and (ctx.sunset_minute - EVENING_COOLING_START_BEFORE_SUNSET_MIN)
        <= ctx.now_minutes
        < ctx.sunset_minute
    )
    cooling_active = (
        ctx.evening_cooling_enabled
        and ctx.heat_stress_level in {"eleve", "severe"}
        and ctx.temperature >= EVENING_COOLING_MIN_TEMP
        and ctx.evening_allowed
        and cooling_window
        and not ctx.pluie_compensatrice
        and not ctx.pluie_proche
        # SOL DÉTREMPÉ = PAS DE COOLING. Sans ce garde, le `block_reason = None` ci-dessous
        # effacerait aussi « sol_deja_humide » : on arroserait un sol déjà saturé (gros orage la
        # veille) et le gazon passerait la nuit trempé pour rien. Les seuls blocages que le
        # rafraîchissement court-circuite légitimement sont ceux de BUDGET d'eau (cooldown 24 h,
        # garde-fou hebdo, réserve saine) : ils protègent la recharge, or 3 mm de cooling ne
        # rechargent rien. La variante « air humide » de humidite_excessive est déjà écartée en
        # amont — _evening_window_allowed refuse la fenêtre du soir dès humidité > 60 %.
        and not ctx.saturation_block
    )
    if cooling_active:
        mm_cible = EVENING_COOLING_MM
        mm_final = EVENING_COOLING_MM
        block_reason = None
    # Anticipation (affichage) : le rafraîchissement du soir est PROBABLE quand il SERAIT
    # réellement l'action du soir — mêmes conditions que `cooling_active` (vague de chaleur, vrai
    # test du soir via `evening_allowed`, pas de pluie, aucun arrosage normal prévu), mais sans
    # exiger d'être déjà dans la fenêtre 18-20 h (on l'annonce dès la journée). Recalculé à chaque
    # refresh → se retire si l'air redevient humide ou si une recharge devient prévue.
    evening_cooling_likely = bool(
        ctx.evening_cooling_enabled
        and ctx.heat_stress_level in {"eleve", "severe"}
        and ctx.temperature >= EVENING_COOLING_MIN_TEMP
        and ctx.evening_allowed
        and not ctx.pluie_compensatrice
        and not ctx.pluie_proche
        and not ctx.saturation_block  # même garde que cooling_active : sol détrempé = pas de soir
        and (ctx.sunset_minute is None or ctx.now_minutes < ctx.sunset_minute)
    )
    # Diagnostic : expose le raisonnement de la décision du soir pour pouvoir voir, depuis HA,
    # POURQUOI le cooling se déclenche ou non (sans deviner). Purement informatif.
    evening_cooling_debug = {
        "enabled": bool(ctx.evening_cooling_enabled),
        "evening_allowed": bool(ctx.evening_allowed),
        "cooling_active": bool(cooling_active),
        "mm_before_cooling": round(float(mm_before_cooling), 1),
        "mm_final": round(float(mm_final), 1),
        "heat_stress": ctx.heat_stress_level,
        "humidite": ctx.humidite,
        "minutes_to_sunset": (
            ctx.sunset_minute - ctx.now_minutes if ctx.sunset_minute is not None else None
        ),
        "now_minutes": ctx.now_minutes,
        "evening_window_minutes": (
            [ctx.sunset_minute - EVENING_COOLING_START_BEFORE_SUNSET_MIN, ctx.sunset_minute]
            if ctx.sunset_minute is not None
            else None
        ),
        "temperature": round(ctx.temperature, 1),
        "temperature_min_cooling": EVENING_COOLING_MIN_TEMP,
        "pluie_block": bool(ctx.pluie_compensatrice or ctx.pluie_proche),
        "depletion_ratio": round(_depletion_ratio, 3),
        "mad_ratio": round(_mad_ratio, 2),
        "block_reason": block_reason,
    }
    passages = 1
    if max_session_mm is not None and mm_final > max_session_mm:
        passages = max(passages, int(ceil(mm_final / max_session_mm)))
    elif mm_final > FRACTIONNEMENT_NORMAL_SEUIL_MM:
        passages = 2
    if ctx.recent_watering_count >= 2 and ctx.recent_watering_mm_7j >= ctx.guardrail_max_mm:
        passages = max(passages, 2)
    if cooling_active:
        # Rafraîchissement du soir : dose légère (3 mm) → AUCUN risque de ruissellement, donc
        # pas de fractionnement. Un seul passage = relief rapide + fin plus tôt (meilleure
        # marge de séchage avant la nuit). On annule la règle anti-ruissellement ci-dessus.
        passages = 1
    # LA PAUSE LONGUE EST RÉSERVÉE AUX GROSSES DOSES (demande de Kévin, 29/07/2026).
    # Elle existe pour laisser le premier passage S'INFILTRER avant le second — un enjeu de
    # ruissellement, qui ne se pose que sur un volume conséquent. Or le fractionnement peut aussi
    # être déclenché pour de tout autres raisons (session maximale dépassée, budget hebdo saturé
    # après deux arrosages récents) : imposer alors 25 minutes d'attente à une petite dose
    # rallongeait la séance sans rien apporter, et repoussait la fin hors du créneau frais.
    pause_minutes = (
        PAUSE_ENTRE_PASSAGES_MIN
        if passages > 1 and mm_final >= PAUSE_LONGUE_MIN_DOSE_MM
        else 0
    )
    confidence_score, confidence_level, confidence_reasons = _confidence(ctx, block_reason, mm_final)
    # Profil NORMAL — le chemin qu'emprunte une installation en régime courant. Il posait
    # un niveau littéral sans jamais dire pourquoi : le capteur restait muet là où on le
    # consulte le plus. Le helper décide sur la réserve du sol et produit les raisons.
    _risque_n, _raisons_n = _evaluer_risque_gazon(
    water_balance=ctx.water_balance,
    bilan_hydrique_mm=ctx.bilan_hydrique_mm,
    pression_hydrique=ctx.pression_hydrique,
    vent=ctx.vent,
    hauteur_gazon=ctx.hauteur_gazon,
    heat_stress_level=ctx.heat_stress_level,
    heat_stress_phase=ctx.heat_stress_phase,
    plancher="modere" if ctx.deficit_mm_brut >= 5 else None,
    )
    normal_payload = _build_profile_payload(
        deficit_mm_brut=ctx.deficit_mm_brut,
        deficit_mm_ajuste=ctx.deficit_mm_ajuste,
        mm_cible=mm_cible,
        mm_final=mm_final,
        besoin_mm=besoin_mm,
        mm_detected=float(ctx.water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
        type_arrosage="bloque" if block_reason is not None else ("auto" if mm_final > 0 else "aucune_action"),
        arrosage_recommande=mm_final > 0 and block_reason is None,
        arrosage_auto_autorise=mm_final > 0 and block_reason is None,
        arrosage_conseille="personnalise" if block_reason is not None else "aucune_action" if mm_final <= 0 else "auto",
        passages=passages,
        pause_minutes=pause_minutes,
        fractionnement_reason="deep_watering_fractionation" if passages > 1 else "single_pass_deep_watering",
        niveau_confiance=confidence_level,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        raison_decision_base=(
            "Rafraîchissement du soir : petit arrosage de cooling par forte chaleur pour faire baisser la température du gazon."
            if cooling_active
            else "Mode Normal: arrosage profond déclenché quand la réserve atteint le seuil d'épuisement (MAD)."
        ),
        block_reason=block_reason,
        fenetre_optimale=(
            # LE SOIR = UNIQUEMENT LE RAFRAÎCHISSEMENT (3 mm), JAMAIS UNE RECHARGE.
            # On exige `cooling_active` et non le simple `evening_allowed` : en canicule,
            # _evening_window_allowed LÈVE volontairement la marge de séchage de 90 min en
            # supposant la petite dose de cooling. Si le cooling ne s'active pas (température
            # mesurée < EVENING_COOLING_MIN_TEMP, switch désactivé, pluie), `mm_final` vaut la
            # dose de RECHARGE complète : la proposer le soir arroserait lourdement à la tombée
            # de la nuit sans marge de séchage → risque fongique. Dans ce cas la recharge est
            # reportée à la fenêtre du matin (au frais), conformément au contrat du module.
            "soir"
            if cooling_active
            else "maintenant"
            if ctx.morning_start_minute <= ctx.now_minutes < ctx.acceptable_end_minute
            else "ce_matin"
        ),
        niveau_action="a_faire" if mm_final > 0 else "surveiller",
        risque_gazon=_risque_n,
        risque_raisons=_raisons_n,
        heat_stress_level=ctx.heat_stress_level,
        heat_stress_phase=ctx.heat_stress_phase,
        morning_start_minute=ctx.morning_start_minute,
        acceptable_end_minute=ctx.acceptable_end_minute,
        morning_end_minute=ctx.morning_end_minute,
        temperature_band=ctx.temperature_band,
        evening_allowed=ctx.evening_allowed,
        recent_watering_count=ctx.recent_watering_count,
        recent_watering_mm_7j=ctx.recent_watering_mm_7j,
        guardrail_min_mm=guardrail_min_effective,
        guardrail_max_mm=guardrail_max_effective,
        guardrail_reason=f"{ctx.guardrail_reason}; pluie_support={ctx.pluie_support:.1f}",
        seasonal_profile=ctx.seasonal_profile_payload,
        cooldown_24h_hours=ctx.cooldown_24h_hours,
    )
    # VRAIE canicule (≥ SURVIE_CANICULE_MIN_TEMP réels + réserve quasi vide), à ne pas confondre
    # avec `heat_stress_level` qui est un score COMPOSITE pouvant dire « severe » dès 30 °C via
    # l'ET0 et l'air sec. Exposé pour que l'affichage puisse signaler un arrosage de SURVIE —
    # jusqu'ici aucun attribut ne portait cette information et la carte n'avait aucun moyen de
    # distinguer une recharge de routine d'une intervention d'urgence.
    normal_payload["survie_canicule_active"] = bool(_survie_canicule)
    normal_payload["evening_cooling"] = bool(cooling_active)
    normal_payload["evening_cooling_likely"] = evening_cooling_likely
    normal_payload["evening_cooling_debug"] = evening_cooling_debug
    normal_payload["fenetre_optimale_profil"] = normal_payload.get("fenetre_optimale")
    # Fenêtre du soir exposée au coordinateur : basée sur le coucher du soleil (-30 min → coucher)
    # pour que le coordinateur autorise le lancement à ~coucher-30, au lieu de la fenêtre fixe
    # 18-20 h (sinon il bloquerait « hors fenêtre »). Repli sur 18-20 h si le coucher est inconnu.
    # EN CANICULE, LE SOIR N'EST SÛR QUE POUR LE COOLING. `_evening_window_allowed` renvoie True
    # dans la branche canicule en LEVANT la marge de séchage de 90 min, parce qu'elle suppose la
    # petite dose de 3 mm. Si le rafraîchissement n'est finalement pas plausible (température
    # mesurée < EVENING_COOLING_MIN_TEMP, switch coupé, pluie), il faut retirer l'autorisation :
    # sinon le coordinateur lancerait la dose de RECHARGE dans la fenêtre du soir, sans séchage
    # avant la nuit → risque fongique. Hors canicule, la branche « soir » impose déjà la marge de
    # 90 min : on conserve sa décision telle quelle.
    if ctx.heat_stress_level in {"eleve", "severe"} and not evening_cooling_likely:
        normal_payload["watering_evening_allowed"] = False
    # Fenêtre exposée au coordinateur : basée sur le coucher du soleil (-30 min → coucher) quand un
    # rafraîchissement est plausible, au lieu de la fenêtre fixe 18-20 h.
    if ctx.sunset_minute is not None and evening_cooling_likely:
        normal_payload["watering_evening_start_minute"] = (
            ctx.sunset_minute - EVENING_COOLING_START_BEFORE_SUNSET_MIN
        )
        normal_payload["watering_evening_end_minute"] = ctx.sunset_minute
    return normal_payload


def _profile_for_agro_phases(ctx: _WateringCtx) -> dict[str, Any]:
    resolved_policy = _resolve_phase_policy(
        phase_dominante=ctx.phase_dominante,
        sous_phase=ctx.sous_phase,
        pluie_proche=ctx.pluie_proche,
        pluie_compensatrice=ctx.pluie_compensatrice,
        temperature=ctx.temperature,
        humidite=ctx.humidite,
        saturation_block=ctx.saturation_block,
    )
    minimum = resolved_policy.target_range.min_mm if resolved_policy.target_range is not None else 0.0
    maximum = resolved_policy.target_range.max_mm if resolved_policy.target_range is not None else 0.0
    if ctx.phase_dominante == "Fertilisation":
        mm_cible = _clamp((ctx.besoin_court * 0.4) + (ctx.besoin_tendance * 0.08), minimum, maximum)
    elif ctx.phase_dominante == "Biostimulant":
        mm_cible = _clamp((ctx.besoin_court * 0.5) + (ctx.besoin_tendance * 0.08), minimum, maximum)
    elif ctx.phase_dominante == "Agent Mouillant":
        mm_cible = _clamp((ctx.besoin_court * 0.55) + (ctx.besoin_tendance * 0.1), minimum, maximum)
    else:
        mm_cible = _clamp((ctx.besoin_court * 0.6) + (ctx.besoin_tendance * 0.1), minimum, maximum)
    block_reason = None
    # `_resolve_phase_policy` a un unique `return` typé non-optionnel : le test de nullité
    # était toujours vrai (les autres sites déréférencent d'ailleurs sans le tester).
    if resolved_policy.blocking.is_blocked:
        block_reason = _normalize_public_block_reason(resolved_policy.blocking.reason)
    elif ctx.pluie_compensatrice or ctx.pluie_proche:
        block_reason = "pluie_prevue_suffisante"
    elif ctx.saturation_block:
        block_reason = "sol_deja_humide"
    elif ctx.humidite >= 85:
        block_reason = "humidite_elevee"
    if block_reason is None:
        if resolved_policy.target_range is not None:
            mm_cible = _apply_watering_floor_constraints(mm_cible, ctx.deficit_mm_brut, resolved_policy.target_range.min_mm)
        else:
            mm_cible = _apply_mode_watering_constraints(mm_cible, ctx.deficit_mm_brut, ctx.phase_dominante)
    mm_final = 0.0 if block_reason else mm_cible
    if (
        resolved_policy is not None
        and resolved_policy.policy.execution is not None
        and resolved_policy.policy.execution.preferred == "single_pass"
    ):
        passages = 1
    else:
        passages = 1 if mm_final <= 4.0 else 2
    pause_minutes = 25 if passages > 1 else 0
    # « soir » UNIQUEMENT dans le créneau du soir. La borne basse `EVENING_START_HOUR <=` était
    # absente ici (contrairement à la version canonique de compute_action_guidance) : de 00h00 à
    # 17h59, `now_hour < EVENING_END_HOUR` restait vrai, donc en phase produit avec T ≥ 24 la
    # fenêtre s'annonçait « soir » toute la journée — ce qui court-circuitait le garde
    # anti-réarrosage (coordinator : `fenetre != "soir"`) dès le matin, pas seulement le soir.
    fenetre_optimale = (
        "soir"
        if ctx.evening_allowed
        and ctx.temperature >= 24
        and EVENING_START_HOUR <= ctx.now_hour < EVENING_END_HOUR
        else "ce_matin"
    )
    confidence_score, confidence_level, confidence_reasons = _confidence(ctx, block_reason, mm_final)
    return _build_profile_payload(
        deficit_mm_brut=ctx.deficit_mm_brut,
        deficit_mm_ajuste=ctx.deficit_mm_ajuste,
        mm_cible=mm_cible,
        mm_final=mm_final,
        mm_detected=float(ctx.water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
        type_arrosage="auto" if mm_final > 0 else "aucune_action",
        arrosage_recommande=mm_final > 0,
        arrosage_auto_autorise=mm_final > 0,
        arrosage_conseille="auto" if ctx.phase_dominante == "Fertilisation" else "personnalise",
        passages=passages,
        pause_minutes=pause_minutes,
        fractionnement_reason="managed_fractionation" if passages > 1 else "single_pass",
        niveau_confiance=confidence_level,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        raison_decision_base=f"{ctx.phase_dominante}: arrosage léger adapté.",
        block_reason=block_reason,
        fenetre_optimale=fenetre_optimale if mm_final > 0 else "attendre",
        niveau_action="a_faire" if mm_final > 0 else "surveiller",
        risque_gazon="faible" if mm_final > 0 else "modere",
        heat_stress_level=ctx.heat_stress_level,
        heat_stress_phase=ctx.heat_stress_phase,
        morning_start_minute=ctx.morning_start_minute,
        acceptable_end_minute=ctx.acceptable_end_minute,
        morning_end_minute=ctx.morning_end_minute,
        temperature_band=ctx.temperature_band,
        evening_allowed=ctx.evening_allowed,
        recent_watering_count=ctx.recent_watering_count,
        recent_watering_mm_7j=float(ctx.water_balance.get("arrosage_recent_7j", 0.0) or 0.0),
        guardrail_min_mm=ctx.guardrail_min_mm,
        guardrail_max_mm=ctx.guardrail_max_mm,
        guardrail_reason=ctx.guardrail_reason,
        seasonal_profile=ctx.seasonal_profile_payload,
        cooldown_24h_hours=ctx.cooldown_24h_hours,
    )


def _profile_for_generic(ctx: _WateringCtx) -> dict[str, Any]:
    mm_cible = _clamp(max(ctx.deficit_mm_ajuste, 5.0), 5.0, 20.0)
    block_reason = None
    if ctx.pluie_compensatrice or ctx.pluie_proche:
        block_reason = "pluie_prevue_suffisante"
    elif ctx.saturation_block:
        block_reason = "sol_deja_humide"
    elif ctx.humidite >= 85:
        block_reason = "humidite_elevee"
    if block_reason is None:
        mm_cible = _apply_mode_watering_constraints(mm_cible, ctx.deficit_mm_brut, ctx.phase_dominante)
    mm_final = 0.0 if block_reason else mm_cible
    passages = 1 if mm_final <= 12.0 else 2
    pause_minutes = 25 if passages > 1 else 0
    confidence_score, confidence_level, confidence_reasons = _confidence(ctx, block_reason, mm_final)
    return _build_profile_payload(
        deficit_mm_brut=ctx.deficit_mm_brut,
        deficit_mm_ajuste=ctx.deficit_mm_ajuste,
        mm_cible=mm_cible,
        mm_final=mm_final,
        mm_detected=float(ctx.water_balance.get("arrosage_recent_jour", 0.0) or 0.0),
        type_arrosage="aucune_action" if mm_final <= 0 else "auto",
        arrosage_recommande=mm_final > 0,
        arrosage_auto_autorise=mm_final > 0,
        arrosage_conseille="personnalise",
        passages=passages,
        pause_minutes=pause_minutes,
        fractionnement_reason="generic_deep_watering" if passages > 1 else "single_pass",
        niveau_confiance=confidence_level,
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons,
        raison_decision_base=f"Phase {ctx.phase_dominante}: arrosage maîtrisé.",
        block_reason=block_reason,
        fenetre_optimale="soir"
        if ctx.evening_allowed
        and ctx.temperature >= 24
        and EVENING_START_HOUR <= ctx.now_hour < EVENING_END_HOUR
        else ("ce_matin" if mm_final > 0 else "attendre"),
        niveau_action="a_faire" if mm_final > 0 else "surveiller",
        risque_gazon="faible",
        heat_stress_level=ctx.heat_stress_level,
        heat_stress_phase=ctx.heat_stress_phase,
        morning_start_minute=ctx.morning_start_minute,
        acceptable_end_minute=ctx.acceptable_end_minute,
        morning_end_minute=ctx.morning_end_minute,
        temperature_band=ctx.temperature_band,
        evening_allowed=ctx.evening_allowed,
        recent_watering_count=ctx.recent_watering_count,
        recent_watering_mm_7j=float(ctx.water_balance.get("arrosage_recent_7j", 0.0) or 0.0),
        guardrail_min_mm=ctx.guardrail_min_mm,
        guardrail_max_mm=ctx.guardrail_max_mm,
        guardrail_reason=ctx.guardrail_reason,
        seasonal_profile=ctx.seasonal_profile_payload,
    )


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
    sous_phase_age_days: int | None = None,
    sous_phase_progression: float | None = None,
    hauteur_gazon: float | None = None,
    application_type: str | None = None,
    forecast_temperature_today: float | None = None,
    evening_cooling_enabled: bool = True,
    fungal_risk_level: str | None = None,
) -> dict[str, Any]:
    today = today or _current_date()
    weather_profile = weather_profile or {}
    history = [item for item in (history or []) if isinstance(item, dict)]
    ctx = _build_watering_ctx(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        water_balance=water_balance,
        today=today,
        pluie_24h=pluie_24h or 0.0,
        pluie_demain=pluie_demain or 0.0,
        pluie_j2=pluie_j2 or 0.0,
        pluie_3j=pluie_3j or 0.0,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j or 0.0,
        humidite=humidite or 0.0,
        temperature=temperature or 0.0,
        etp=etp or 0.0,
        type_sol=type_sol,
        weather_profile=weather_profile,
        history=history,
        sous_phase_age_days=sous_phase_age_days,
        sous_phase_progression=sous_phase_progression,
        hauteur_gazon=hauteur_gazon,
        application_type=application_type,
        forecast_temperature_today=forecast_temperature_today,
        evening_cooling_enabled=evening_cooling_enabled,
        fungal_risk_level=fungal_risk_level,
    )
    if phase_dominante == "Hivernage":
        resolved_policy = _resolve_phase_policy(
            phase_dominante=phase_dominante,
            sous_phase=sous_phase,
            prolonged_drought=False,
        )
        block_reason = _normalize_public_block_reason(resolved_policy.blocking.reason) or "mode_bloque"
        return _profile_for_blocked(ctx, block_reason)
    if is_active_rain_weather(weather_profile):
        return _profile_for_blocked(ctx, "pluie_active")
    _fill_post_preamble(ctx)
    if phase_dominante == "Sursemis":
        return _profile_for_sursemis(ctx)
    if phase_dominante == "Traitement":
        return _profile_for_traitement(ctx)
    if phase_dominante == "Normal":
        return _profile_for_normal(ctx)
    if phase_dominante in {"Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"}:
        return _profile_for_agro_phases(ctx)
    return _profile_for_generic(ctx)


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
    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
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
    today = today or _current_date()
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
    hour_of_day: float | None = None,
    history: list[dict[str, Any]] | None = None,
    sous_phase_age_days: int | None = None,
    sous_phase_progression: float | None = None,
    hauteur_gazon: float | None = None,
    minutes_to_sunset: float | None = None,
    fungal_risk_level: str | None = None,
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
    bilan_hydrique_mm = _reference_hydric_balance_mm(water_balance)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    besoin_court, besoin_tendance, pression_hydrique = _hydraulic_pressure(
        bilan_hydrique_mm, deficit_3j, deficit_7j
    )
    pluie_compensatrice, pluie_proche = _rain_signals(
        objective_reference_mm=objectif_mm if objectif_mm > 0 else max(0.0, max(-bilan_hydrique_mm, deficit_3j, deficit_7j)),
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        pluie_j2=pluie_j2,
        pluie_3j=pluie_3j,
        pluie_probabilite_max_3j=pluie_probabilite_max_3j,
    )
    now = _current_datetime()
    now_hour = hour_of_day if hour_of_day is not None else now.hour
    now_minutes = now_hour * 60 + int(now.minute if hour_of_day is None else 0)
    vent = _to_float(advanced_context.get("vent"))
    hauteur_gazon = _to_float(advanced_context.get("hauteur_gazon"))
    optimal_start_minute, optimal_end_minute, acceptable_end_minute, temperature_band = _morning_window_bounds(
        phase_dominante=phase_dominante,
        temperature=temperature,
    )
    heat_stress_level = _heat_stress_level(
        temperature=temperature,
        etp=etp,
        # Voir le commentaire du jumeau dans `_build_watering_ctx` : une humidité absente,
        # coercée à 0 en amont, était comptée comme air totalement sec (palier le plus pénalisant).
        humidite=humidite if humidite else None,
        weather_profile={
            "weather_wind_speed": vent,
            "weather_precipitation": pluie_24h,
            "weather_precipitation_probability": pluie_probabilite_max_3j,
        },
        deficit_mm_brut=max(0.0, max(-bilan_hydrique_mm, deficit_3j, deficit_7j)),
    )
    heat_stress_phase = _heat_stress_phase(
        heat_stress_level=heat_stress_level,
        temperature=temperature,
        etp=etp,
        pluie_demain=pluie_demain,
        pluie_3j=pluie_3j,
    )
    # Mêmes garde-fous universels que le chemin principal (_build_watering_ctx) : marge de séchage
    # (minutes_to_sunset) et blocage anti-fongique (fungal_risk_level). Sans eux, ce second calcul
    # de `evening_allowed` — qui alimente le libellé « soir » et, via lui, le court-circuit du garde
    # anti-réarrosage du coordinateur — pouvait autoriser le soir même par risque fongique élevé ou
    # sans marge de séchage suffisante. Alignés sur l'appel de la ligne 1325.
    evening_allowed = _evening_window_allowed(
        temperature=temperature,
        humidite=humidite,
        water_balance=water_balance,
        objectif_mm=objectif_mm,
        heat_stress_level=heat_stress_level,
        minutes_to_sunset=minutes_to_sunset,
        fungal_risk_level=fungal_risk_level,
    )

    if phase_dominante in {"Traitement", "Hivernage"}:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="surveiller",
            fenetre_optimale="attendre",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if is_active_rain_weather(advanced_context):
        return _build_guidance_window_payload(
            risque_gazon="modere" if phase_dominante == "Sursemis" else "faible",
            niveau_action="surveiller" if phase_dominante != "Normal" else "aucune_action",
            fenetre_optimale="apres_pluie",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if objectif_mm <= 0:
        # ⚠️ L'ALERTE NE DOIT PAS S'ÉTEINDRE PARCE QUE LE BLOCAGE S'ALLUME.
        # Ce chemin est pris dès que l'objectif est ramené à 0 — donc chaque fois qu'un
        # garde-fou retient l'eau. Il posait « risque_gazon: faible » par LITTÉRAL, sans
        # regarder le sol. Mesuré le 01/08/2026 : à 15:30:35 réserve 2,8 mm → « eleve /
        # critique » ; à 15:32:44, même réserve, même `hydric_state: critique`, mais
        # `block_reason: garde_fou_hebdomadaire` → « faible / aucune_action ». Sur la fenêtre
        # auditée, 19 h 34 sur 239 h d'`etat_hydrique: critique` coexistaient avec un risque
        # annoncé faible — et comme `risque_gazon` alimente `compute_next_reevaluation`, la
        # cadence de réévaluation baissait en même temps que l'alerte se taisait. C'est ce qui
        # a rendu les 31/07-02/08 (réserve à 0 mm) invisibles.
        # Le NIVEAU D'ACTION reste « aucune_action » : il n'y a effectivement rien à faire
        # tant que le garde-fou tient. C'est le DIAGNOSTIC du gazon qui doit rester vrai.
        _risque_bloque, _raisons_bloque = _evaluer_risque_gazon(
            water_balance=water_balance,
            bilan_hydrique_mm=bilan_hydrique_mm,
            pression_hydrique=pression_hydrique,
            plancher=None if phase_dominante == "Normal" else "modere",
            vent=vent,
            hauteur_gazon=hauteur_gazon,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
        )
        return _build_guidance_window_payload(
            risque_gazon=_risque_bloque,
            risque_raisons=_raisons_bloque,
            niveau_action="aucune_action" if phase_dominante == "Normal" else "surveiller",
            fenetre_optimale="apres_pluie" if pluie_proche else "attendre",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if phase_dominante == "Sursemis":
        optimal_start_minute, optimal_end_minute, acceptable_end_minute, temperature_band = _semis_window_bounds(
            temperature=temperature,
            humidite=humidite,
            vent=vent,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
        )
        policy_key, _, transition_ready, tonte_count = _select_sursemis_policy(
            history=[item for item in (history or []) if isinstance(item, dict)],
            sous_phase=sous_phase,
            sous_phase_age_days=sous_phase_age_days,
            sous_phase_progression=sous_phase_progression,
            hauteur_gazon=hauteur_gazon,
            water_balance=water_balance,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            pluie_probabilite_24h=pluie_probabilite_max_3j,
            temperature=temperature,
        )
        if policy_key == "germination_stricte":
            niveau_action = "critique" if pression_hydrique >= 1.8 or bilan_hydrique_mm <= -1.0 else "a_faire"
        elif policy_key == "reprise_transition":
            niveau_action = "surveiller" if transition_ready else "a_faire"
        else:
            niveau_action = "critique" if pression_hydrique >= 2.2 or bilan_hydrique_mm <= -1.5 else "a_faire"
        if pluie_compensatrice or pluie_proche:
            fenetre_optimale = "apres_pluie"
        elif policy_key == "reprise_transition":
            if transition_ready and (now_minutes >= acceptable_end_minute or pression_hydrique < 1.0):
                fenetre_optimale = "attendre"
            elif now_minutes < optimal_start_minute:
                fenetre_optimale = "ce_matin"
            elif now_minutes < acceptable_end_minute and (vent is None or vent < 15):
                fenetre_optimale = "maintenant"
            else:
                fenetre_optimale = "attendre"
        elif now_minutes < optimal_start_minute:
            fenetre_optimale = "ce_matin"
        elif now_minutes < acceptable_end_minute and (vent is None or vent < 15):
            fenetre_optimale = "maintenant"
        else:
            fenetre_optimale = "demain_matin"
        if policy_key == "germination_stricte":
            risque_gazon = "eleve" if bilan_hydrique_mm <= -1.0 or pression_hydrique >= 2.0 else "modere"
        elif policy_key == "reprise_transition" and transition_ready:
            risque_gazon = "modere" if pression_hydrique < 2.0 else "eleve"
        else:
            risque_gazon = "eleve" if bilan_hydrique_mm <= -1.5 or pression_hydrique >= 2.5 else "modere"
        # Le niveau brut ci-dessus reste calculé pour les phases Sursemis (germination,
        # reprise), où le bilan du jour EST le bon signal : un semis n'a pas de réserve
        # exploitable. Le helper le reprend, applique la réserve du sol quand elle existe,
        # et produit les raisons.
        risque_gazon, risque_raisons = _evaluer_risque_gazon(
            water_balance=water_balance,
            bilan_hydrique_mm=bilan_hydrique_mm,
            pression_hydrique=pression_hydrique,
            utiliser_reserve=False,      # branche Sursemis (germination / reprise)
            plancher=risque_gazon,       # la phase impose son minimum
            vent=vent,
            hauteur_gazon=hauteur_gazon,
            heat_stress_level=heat_stress_level,
        )
        return _build_guidance_window_payload(
            risque_gazon=risque_gazon,
            risque_raisons=risque_raisons,
            niveau_action=niveau_action,
            fenetre_optimale=fenetre_optimale,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if evening_allowed and EVENING_START_HOUR <= now_hour < EVENING_END_HOUR:
        return _build_guidance_window_payload(
            risque_gazon="modere" if heat_stress_level in {"eleve", "severe"} else "faible",
            niveau_action="a_faire",
            fenetre_optimale="soir",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if pluie_compensatrice:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="surveiller",
            fenetre_optimale="apres_pluie",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if humidite >= 85 and bilan_hydrique_mm >= -0.5:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="surveiller",
            fenetre_optimale="attendre",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if bilan_hydrique_mm <= -4.0:
        # ⚠️ Ce `return` ANTICIPÉ est LE chemin qui annonçait « risque élevé » chaque nuit.
        # `bilan_hydrique_mm` est le bilan de la JOURNÉE (pluie + arrosage − ETc du jour) :
        # à 2 h du matin, rien n'a encore été arrosé et l'ETc attendue vaut ~6 mm, donc le
        # bilan tombe sous −4 mécaniquement. Il sortait ici avant tous les blocs de
        # finalisation, d'où un « élevé » que rien n'expliquait — et qui repassait « faible »
        # à la seconde où l'arrosage du matin partait (trois nuits d'affilée dans l'historique).
        # `niveau_action="critique"` reste JUSTE : un déficit journalier de 4 mm mérite bien
        # d'agir. C'est le LIBELLÉ DE RISQUE qui mentait, pas la décision d'arroser.
        _risque_j4, _raisons_j4 = _evaluer_risque_gazon(
            water_balance=water_balance,
            bilan_hydrique_mm=bilan_hydrique_mm,
            pression_hydrique=pression_hydrique,
            vent=vent,
            hauteur_gazon=hauteur_gazon,
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            seuil_eleve=-4.0,
            seuil_modere=-4.0,
        )
        return _build_guidance_window_payload(
            risque_gazon=_risque_j4,
            risque_raisons=_raisons_j4,
            niveau_action="critique",
            fenetre_optimale="demain_matin" if now_minutes >= acceptable_end_minute else "maintenant",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if bilan_hydrique_mm <= -0.8 or pression_hydrique >= 1.5:
        if now_minutes < optimal_start_minute:
            return _build_guidance_window_payload(
                risque_gazon="modere",
                niveau_action="a_faire",
                fenetre_optimale="ce_matin",
                heat_stress_level=heat_stress_level,
                heat_stress_phase=heat_stress_phase,
                optimal_start_minute=optimal_start_minute,
                acceptable_end_minute=acceptable_end_minute,
                optimal_end_minute=optimal_end_minute,
                temperature_band=temperature_band,
                evening_allowed=evening_allowed,
            )
        if now_minutes < acceptable_end_minute:
            return _build_guidance_window_payload(
                risque_gazon="modere",
                niveau_action="a_faire",
                fenetre_optimale="maintenant",
                heat_stress_level=heat_stress_level,
                heat_stress_phase=heat_stress_phase,
                optimal_start_minute=optimal_start_minute,
                acceptable_end_minute=acceptable_end_minute,
                optimal_end_minute=optimal_end_minute,
                temperature_band=temperature_band,
                evening_allowed=evening_allowed,
            )
        return _build_guidance_window_payload(
            risque_gazon="modere",
            niveau_action="a_faire",
            fenetre_optimale="demain_matin",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    if now_minutes < optimal_start_minute:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="a_faire",
            fenetre_optimale="ce_matin",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )
    if now_minutes < acceptable_end_minute:
        return _build_guidance_window_payload(
            risque_gazon="faible",
            niveau_action="a_faire",
            fenetre_optimale="maintenant",
            heat_stress_level=heat_stress_level,
            heat_stress_phase=heat_stress_phase,
            optimal_start_minute=optimal_start_minute,
            acceptable_end_minute=acceptable_end_minute,
            optimal_end_minute=optimal_end_minute,
            temperature_band=temperature_band,
            evening_allowed=evening_allowed,
        )

    risque_gazon, risque_raisons = _evaluer_risque_gazon(
        water_balance=water_balance,
        bilan_hydrique_mm=bilan_hydrique_mm,
        pression_hydrique=pression_hydrique,
        vent=vent,
        hauteur_gazon=hauteur_gazon,
        heat_stress_level=heat_stress_level,
        heat_stress_phase=heat_stress_phase,
        seuil_eleve=-2.5,
        seuil_modere=-0.8,
        seuil_pression_modere=1.2,
    )

    return _build_guidance_window_payload(
        risque_gazon=risque_gazon,
        risque_raisons=risque_raisons,
        niveau_action="a_faire",
        fenetre_optimale="demain_matin",
        heat_stress_level=heat_stress_level,
        heat_stress_phase=heat_stress_phase,
        optimal_start_minute=optimal_start_minute,
        acceptable_end_minute=acceptable_end_minute,
        optimal_end_minute=optimal_end_minute,
        temperature_band=temperature_band,
        evening_allowed=evening_allowed,
    )


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
