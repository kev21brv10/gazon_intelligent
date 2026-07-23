from __future__ import annotations

"""Référentiel central des politiques d'arrosage.

Ce module ne modifie pas le moteur existant. Il fournit :
- un registre figé des politiques métier ;
- des dataclasses lisibles ;
- un resolver de base pour arbitrer la politique active.
"""

from dataclasses import dataclass, field
from typing import Any

from .decision_models import DoseInputs, DosePolicyPayload

MODE_NORMAL = "normal"
MODE_SURSEMIS = "sursemis"
MODE_FERTILISATION = "fertilisation"
MODE_BIOSTIMULANT = "biostimulant"
MODE_AGENT_MOUILLANT = "agent_mouillant"
MODE_SCARIFICATION = "scarification"
MODE_TRAITEMENT = "traitement"
MODE_HIVERNAGE = "hivernage"

POLICY_CATEGORY_WEEKLY = "weekly"
POLICY_CATEGORY_DAILY_EVENT = "daily_event"
POLICY_CATEGORY_EVENT = "event"
POLICY_CATEGORY_CONDITIONAL_EVENT = "conditional_event"
POLICY_CATEGORY_BLOCKED_MODE = "blocked_mode"

OVERRIDE_BEHAVIOR_BASE = "base"
OVERRIDE_BEHAVIOR_REPLACE_ALL = "replace_all"
OVERRIDE_BEHAVIOR_TARGETED_OVERRIDE = "targeted_override"
OVERRIDE_BEHAVIOR_BLOCK_ALL = "block_all"
OVERRIDE_BEHAVIOR_BLOCK_WATERING = "block_watering"

BLOCKING_BEHAVIOR_NONE = "none"
BLOCKING_BEHAVIOR_BLOCK_OTHER_MODES = "block_other_modes"
BLOCKING_BEHAVIOR_WEATHER_GUARD = "weather_guard"
BLOCKING_BEHAVIOR_CONDITION_GUARD = "condition_guard"
BLOCKING_BEHAVIOR_APPLICATION_TYPE_GUARD = "application_type_guard"
BLOCKING_BEHAVIOR_BLOCKED_BY_DEFAULT = "blocked_by_default"

MODE_ALIASES: dict[str, str] = {
    "normal": MODE_NORMAL,
    "sursemis": MODE_SURSEMIS,
    "fertilisation": MODE_FERTILISATION,
    "biostimulant": MODE_BIOSTIMULANT,
    "agent mouillant": MODE_AGENT_MOUILLANT,
    "agent_mouillant": MODE_AGENT_MOUILLANT,
    "scarification": MODE_SCARIFICATION,
    "traitement": MODE_TRAITEMENT,
    "hivernage": MODE_HIVERNAGE,
}

DOSE_BAND_BASELINE = "baseline"
DOSE_BAND_SPRING = "spring"
DOSE_BAND_SUMMER = "summer"
DOSE_BAND_HEATWAVE = "heatwave"
DOSE_BAND_AUTUMN = "autumn"
DOSE_BAND_SURSEMIS = "sursemis"
DOSE_BAND_HIVERNAGE = "hivernage"

APPLICATION_TYPE_ALIASES: dict[str, str] = {
    "sol": "racinaire",
    "racinaire": "racinaire",
    "foliaire": "foliaire",
}

_VALID_POLICY_CATEGORIES = frozenset(
    {
        POLICY_CATEGORY_WEEKLY,
        POLICY_CATEGORY_DAILY_EVENT,
        POLICY_CATEGORY_EVENT,
        POLICY_CATEGORY_CONDITIONAL_EVENT,
        POLICY_CATEGORY_BLOCKED_MODE,
    }
)
_VALID_OVERRIDE_BEHAVIORS = frozenset(
    {
        OVERRIDE_BEHAVIOR_BASE,
        OVERRIDE_BEHAVIOR_REPLACE_ALL,
        OVERRIDE_BEHAVIOR_TARGETED_OVERRIDE,
        OVERRIDE_BEHAVIOR_BLOCK_ALL,
        OVERRIDE_BEHAVIOR_BLOCK_WATERING,
    }
)
_VALID_BLOCKING_BEHAVIORS = frozenset(
    {
        BLOCKING_BEHAVIOR_NONE,
        BLOCKING_BEHAVIOR_BLOCK_OTHER_MODES,
        BLOCKING_BEHAVIOR_WEATHER_GUARD,
        BLOCKING_BEHAVIOR_CONDITION_GUARD,
        BLOCKING_BEHAVIOR_APPLICATION_TYPE_GUARD,
        BLOCKING_BEHAVIOR_BLOCKED_BY_DEFAULT,
    }
)


@dataclass(frozen=True)
class WateringRange:
    min_mm: float
    max_mm: float
    optimal_mm: float | None = None


@dataclass(frozen=True)
class DailyProgram:
    min_mm_per_cycle: float
    max_mm_per_cycle: float
    min_cycles_per_day: int
    max_cycles_per_day: int


@dataclass(frozen=True)
class WateringExecution:
    preferred: str
    min_session_mm: float | None = None
    max_session_mm: float | None = None
    objective: str | None = None


@dataclass(frozen=True)
class SemisStageProgram:
    stage: str
    surface_cycle_mm_min: float
    surface_cycle_mm_max: float
    surface_cycle_mm_optimal: float
    daily_cycles_min: int
    daily_cycles_max: int
    cycle_spacing_minutes_min: int
    cycle_spacing_minutes_max: int
    cycle_slots_minutes: tuple[int, ...]
    surface_moisture_target: str
    surface_dryness_risk: str
    runoff_risk: str


@dataclass(frozen=True)
class DosePolicyBand:
    band: str
    target_mm: float
    min_mm: float
    max_mm: float
    reason: str
    season_label: str


@dataclass(frozen=True)
class WateringApplicationTypeRule:
    target_mm: WateringRange
    override_behavior: str


@dataclass(frozen=True)
class WateringPolicy:
    mode: str
    category: str
    priority: int
    base_strategy: str
    override_behavior: str
    blocking_behavior: str
    weekly_target_mm: WateringRange | None = None
    event_target_mm: WateringRange | None = None
    execution: WateringExecution | None = None
    daily_program: DailyProgram | None = None
    conditions: dict[str, Any] = field(default_factory=dict)
    exceptions: dict[str, Any] = field(default_factory=dict)
    allow_override_by: tuple[str, ...] = ()
    application_types: dict[str, WateringApplicationTypeRule] = field(default_factory=dict)


@dataclass(frozen=True)
class BlockingEvaluation:
    is_blocked: bool
    reason: str | None = None


@dataclass(frozen=True)
class ResolvedWateringPolicy:
    requested_mode: str
    selected_mode: str
    policy: WateringPolicy
    target_range: WateringRange | None
    effective_strategy: str
    override_behavior: str
    blocking_behavior: str
    blocking: BlockingEvaluation
    application_type: str | None = None
    active_modes: tuple[str, ...] = ()


def _normalize_mode_name(mode: str | None) -> str:
    text = str(mode or "").strip().casefold()
    if not text:
        return MODE_NORMAL
    return MODE_ALIASES.get(text, MODE_NORMAL)


def _normalize_application_type(application_type: str | None) -> str | None:
    text = str(application_type or "").strip().casefold()
    return APPLICATION_TYPE_ALIASES.get(text, text or None)


def _normalize_weather_payload(weather: dict[str, Any] | None) -> dict[str, Any]:
    return weather if isinstance(weather, dict) else {}


def _normalize_active_modes(
    active_modes: list[str] | tuple[str, ...] | None,
    requested_mode: str,
) -> tuple[str, ...]:
    raw_modes: tuple[Any, ...]
    if isinstance(active_modes, (list, tuple)):
        raw_modes = tuple(active_modes)
    elif active_modes in (None, "", [], {}):
        raw_modes = (requested_mode,)
    else:
        raw_modes = (active_modes,)

    normalized_modes = {
        _normalize_mode_name(item)
        for item in raw_modes
        if item not in (None, "", [], {})
    }
    normalized_modes.add(requested_mode)
    return tuple(sorted(mode for mode in normalized_modes if mode in WATERING_POLICIES))


WATERING_POLICIES: dict[str, WateringPolicy] = {
    MODE_NORMAL: WateringPolicy(
        mode=MODE_NORMAL,
        category=POLICY_CATEGORY_WEEKLY,
        priority=10,
        base_strategy="adaptive_weekly",
        weekly_target_mm=WateringRange(min_mm=15.0, max_mm=30.0),
        execution=WateringExecution(
            preferred="deep_watering",
            min_session_mm=5.0,
            max_session_mm=15.0,
        ),
        override_behavior=OVERRIDE_BEHAVIOR_BASE,
        blocking_behavior=BLOCKING_BEHAVIOR_NONE,
    ),
    MODE_SURSEMIS: WateringPolicy(
        mode=MODE_SURSEMIS,
        category=POLICY_CATEGORY_DAILY_EVENT,
        priority=100,
        base_strategy="surface_moisture",
        daily_program=DailyProgram(
            min_mm_per_cycle=2.0,
            max_mm_per_cycle=4.0,
            min_cycles_per_day=2,
            max_cycles_per_day=3,
        ),
        execution=WateringExecution(
            preferred="fractionated",
            objective="humidite_constante",
        ),
        override_behavior=OVERRIDE_BEHAVIOR_REPLACE_ALL,
        blocking_behavior=BLOCKING_BEHAVIOR_BLOCK_OTHER_MODES,
    ),
    MODE_FERTILISATION: WateringPolicy(
        mode=MODE_FERTILISATION,
        category=POLICY_CATEGORY_EVENT,
        priority=70,
        base_strategy="product_activation",
        event_target_mm=WateringRange(min_mm=5.0, max_mm=8.0, optimal_mm=5.0),
        execution=WateringExecution(preferred="single_pass"),
        override_behavior=OVERRIDE_BEHAVIOR_TARGETED_OVERRIDE,
        blocking_behavior=BLOCKING_BEHAVIOR_WEATHER_GUARD,
    ),
    MODE_BIOSTIMULANT: WateringPolicy(
        mode=MODE_BIOSTIMULANT,
        category=POLICY_CATEGORY_EVENT,
        priority=60,
        base_strategy="light_support",
        event_target_mm=WateringRange(min_mm=3.0, max_mm=7.0, optimal_mm=5.0),
        execution=WateringExecution(preferred="light_support"),
        override_behavior=OVERRIDE_BEHAVIOR_TARGETED_OVERRIDE,
        # Même garde météo que la Fertilisation : « bloquer » = ne pas arroser l'incorporation
        # car la pluie s'en charge — valable aussi pour le biostimulant (s'incorpore très bien
        # avec la pluie, fenêtre ~48 h). Pas de garde « light » distincte (ne se justifiait pas).
        blocking_behavior=BLOCKING_BEHAVIOR_WEATHER_GUARD,
    ),
    MODE_AGENT_MOUILLANT: WateringPolicy(
        mode=MODE_AGENT_MOUILLANT,
        category=POLICY_CATEGORY_EVENT,
        priority=65,
        base_strategy="infiltration_support",
        event_target_mm=WateringRange(min_mm=5.0, max_mm=12.0),
        execution=WateringExecution(preferred="adaptive_soil_state"),
        override_behavior=OVERRIDE_BEHAVIOR_TARGETED_OVERRIDE,
        blocking_behavior=BLOCKING_BEHAVIOR_NONE,
    ),
    MODE_SCARIFICATION: WateringPolicy(
        mode=MODE_SCARIFICATION,
        category=POLICY_CATEGORY_EVENT,
        priority=75,
        base_strategy="recovery_support",
        event_target_mm=WateringRange(min_mm=5.0, max_mm=10.0),
        conditions={
            "soil_humidity_state": "legerement_humide",
            "temperature_min_c": 12.0,
            "avoid_excess_rain": True,
        },
        override_behavior=OVERRIDE_BEHAVIOR_TARGETED_OVERRIDE,
        blocking_behavior=BLOCKING_BEHAVIOR_CONDITION_GUARD,
    ),
    MODE_TRAITEMENT: WateringPolicy(
        mode=MODE_TRAITEMENT,
        category=POLICY_CATEGORY_CONDITIONAL_EVENT,
        priority=80,
        base_strategy="product_dependent",
        application_types={
            "foliaire": WateringApplicationTypeRule(
                target_mm=WateringRange(min_mm=0.0, max_mm=0.0),
                override_behavior=OVERRIDE_BEHAVIOR_BLOCK_WATERING,
            ),
            "racinaire": WateringApplicationTypeRule(
                target_mm=WateringRange(min_mm=3.0, max_mm=6.0),
                override_behavior=OVERRIDE_BEHAVIOR_TARGETED_OVERRIDE,
            ),
        },
        override_behavior=OVERRIDE_BEHAVIOR_TARGETED_OVERRIDE,
        blocking_behavior=BLOCKING_BEHAVIOR_APPLICATION_TYPE_GUARD,
    ),
    MODE_HIVERNAGE: WateringPolicy(
        mode=MODE_HIVERNAGE,
        category=POLICY_CATEGORY_BLOCKED_MODE,
        priority=90,
        base_strategy="blocked",
        weekly_target_mm=WateringRange(min_mm=0.0, max_mm=0.0),
        exceptions={"prolonged_drought": True},
        allow_override_by=(MODE_SURSEMIS,),
        override_behavior=OVERRIDE_BEHAVIOR_BLOCK_ALL,
        blocking_behavior=BLOCKING_BEHAVIOR_BLOCKED_BY_DEFAULT,
    ),
}

SEMIS_STAGE_PROGRAMS: dict[str, SemisStageProgram] = {
    "germination": SemisStageProgram(
        stage="germination",
        surface_cycle_mm_min=1.2,
        surface_cycle_mm_max=1.8,
        surface_cycle_mm_optimal=1.5,
        daily_cycles_min=3,
        daily_cycles_max=4,
        cycle_spacing_minutes_min=120,
        cycle_spacing_minutes_max=120,
        cycle_slots_minutes=(600, 720, 840, 960),
        surface_moisture_target="surface_humide_constante",
        surface_dryness_risk="eleve",
        runoff_risk="faible",
    ),
    "levee": SemisStageProgram(
        stage="levee",
        surface_cycle_mm_min=2.0,
        surface_cycle_mm_max=3.0,
        surface_cycle_mm_optimal=2.5,
        daily_cycles_min=1,
        daily_cycles_max=2,
        cycle_spacing_minutes_min=240,
        cycle_spacing_minutes_max=240,
        cycle_slots_minutes=(600, 840),
        surface_moisture_target="surface_humide_stable",
        surface_dryness_risk="modere",
        runoff_risk="modere",
    ),
    "enracinement": SemisStageProgram(
        stage="enracinement",
        surface_cycle_mm_min=2.5,
        surface_cycle_mm_max=4.0,
        surface_cycle_mm_optimal=3.0,
        daily_cycles_min=1,
        daily_cycles_max=2,
        cycle_spacing_minutes_min=270,
        cycle_spacing_minutes_max=270,
        cycle_slots_minutes=(630, 900),
        surface_moisture_target="transition_progressive",
        surface_dryness_risk="modere",
        runoff_risk="modere",
    ),
}

DOSE_POLICY_BANDS: dict[str, DosePolicyBand] = {
    DOSE_BAND_BASELINE: DosePolicyBand(
        band=DOSE_BAND_BASELINE,
        target_mm=0.0,
        min_mm=0.0,
        max_mm=0.0,
        reason="Dose adaptative inactive: objectif existant conservé.",
        season_label="legacy",
    ),
    DOSE_BAND_SPRING: DosePolicyBand(
        band=DOSE_BAND_SPRING,
        target_mm=6.0,
        min_mm=5.0,
        max_mm=6.5,
        reason="Printemps ou conditions modérées: dose plus profonde mais encore économique.",
        season_label="spring",
    ),
    DOSE_BAND_SUMMER: DosePolicyBand(
        band=DOSE_BAND_SUMMER,
        target_mm=8.0,
        min_mm=7.0,
        max_mm=8.5,
        reason="Été chaud: dose renforcée pour un mouillage plus utile.",
        season_label="summer",
    ),
    DOSE_BAND_HEATWAVE: DosePolicyBand(
        band=DOSE_BAND_HEATWAVE,
        target_mm=10.0,
        min_mm=9.0,
        max_mm=10.5,
        reason="Canicule ou stress thermique: cycle plus profond pour limiter le stress hydrique.",
        season_label="heatwave",
    ),
    DOSE_BAND_AUTUMN: DosePolicyBand(
        band=DOSE_BAND_AUTUMN,
        target_mm=5.5,
        min_mm=5.0,
        max_mm=6.0,
        reason="Automne: dose plus légère, suffisante pour garder la réserve utile cohérente.",
        season_label="autumn",
    ),
    DOSE_BAND_SURSEMIS: DosePolicyBand(
        band=DOSE_BAND_SURSEMIS,
        target_mm=2.5,
        min_mm=2.0,
        max_mm=4.0,
        reason="Sursemis: micro-cycles plus doux et plus fréquents.",
        season_label="sursemis",
    ),
    DOSE_BAND_HIVERNAGE: DosePolicyBand(
        band=DOSE_BAND_HIVERNAGE,
        target_mm=0.0,
        min_mm=0.0,
        max_mm=0.0,
        reason="Hivernage: pas de dose cible active.",
        season_label="winter",
    ),
}

_DOSE_HEATWAVE_TEMPERATURE_C = 34.0
_DOSE_HEATWAVE_ET0_MM = 4.5
_DOSE_SUMMER_TEMPERATURE_C = 28.0
_DOSE_SUMMER_ET0_MM = 3.0
_DOSE_AUTUMN_MONTHS = {9, 10, 11}
_DOSE_SPRING_MONTHS = {3, 4, 5}
_DOSE_WINTER_MONTHS = {12, 1, 2}


def resolve_semis_stage_program(
    sous_phase: str | None,
    *,
    transition_ready: bool = False,
) -> tuple[str, SemisStageProgram]:
    normalized = str(sous_phase or "").strip().casefold()
    if normalized == "germination":
        stage = "germination"
    elif normalized == "levee":
        stage = "levee"
    elif normalized == "enracinement":
        stage = "enracinement"
    elif normalized == "reprise":
        stage = "enracinement" if transition_ready else "levee"
    else:
        stage = "enracinement" if transition_ready else "levee"
    return stage, SEMIS_STAGE_PROGRAMS[stage]


def _dose_to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dose_candidate_band(dose_inputs: DoseInputs) -> DosePolicyBand:
    phase = str(dose_inputs.get("phase_dominante") or "").strip()
    temperature = _dose_to_float(dose_inputs.get("temperature"))
    et0_mm = _dose_to_float(dose_inputs.get("et0_mm"))
    heat_stress_level = str(dose_inputs.get("heat_stress_level") or "").strip().casefold()
    heat_stress_phase = str(dose_inputs.get("heat_stress_phase") or "").strip().casefold()
    month = dose_inputs.get("month")

    if phase == "Sursemis":
        return DOSE_POLICY_BANDS[DOSE_BAND_SURSEMIS]

    if phase == "Hivernage" or month in _DOSE_WINTER_MONTHS:
        return DOSE_POLICY_BANDS[DOSE_BAND_HIVERNAGE]

    if (
        heat_stress_level in {"canicule", "extreme"}
        or heat_stress_phase in {"canicule", "extreme"}
        or (temperature is not None and temperature >= _DOSE_HEATWAVE_TEMPERATURE_C)
        or (et0_mm is not None and et0_mm >= _DOSE_HEATWAVE_ET0_MM)
    ):
        return DOSE_POLICY_BANDS[DOSE_BAND_HEATWAVE]

    if (
        heat_stress_level in {"vigilance", "fort"}
        or (temperature is not None and temperature >= _DOSE_SUMMER_TEMPERATURE_C)
        or (et0_mm is not None and et0_mm >= _DOSE_SUMMER_ET0_MM)
    ):
        return DOSE_POLICY_BANDS[DOSE_BAND_SUMMER]

    if month in _DOSE_AUTUMN_MONTHS:
        return DOSE_POLICY_BANDS[DOSE_BAND_AUTUMN]

    if month in _DOSE_SPRING_MONTHS:
        return DOSE_POLICY_BANDS[DOSE_BAND_SPRING]

    return DOSE_POLICY_BANDS[DOSE_BAND_SPRING]


def resolve_dose_policy(
    dose_inputs: DoseInputs | None = None,
    *,
    dynamic_enabled: bool = False,
) -> DosePolicyPayload:
    """Résout une politique de dose sans toucher au calcul objectif.

    La politique calcule un band candidat lisible, mais tant que
    ``dynamic_enabled`` reste faux, le moteur conserve la dose legacy
    existante.
    """

    normalized_inputs: DoseInputs = dose_inputs if isinstance(dose_inputs, dict) else {}
    candidate_band = _dose_candidate_band(normalized_inputs)
    baseline_band = DOSE_POLICY_BANDS[DOSE_BAND_BASELINE]
    legacy_objective_mm = _dose_to_float(normalized_inputs.get("legacy_objective_mm")) or 0.0
    enabled = bool(dynamic_enabled)
    has_legacy_objective = legacy_objective_mm > 0.0
    active_band = candidate_band if enabled and has_legacy_objective else baseline_band
    active_mm = candidate_band.target_mm if enabled and has_legacy_objective else legacy_objective_mm
    payload: DosePolicyPayload = {
        "enabled": enabled,
        "source": "dynamic" if enabled else "legacy",
        "dose_band": active_band.band,
        "dose_reason": active_band.reason if enabled and has_legacy_objective else baseline_band.reason,
        "dose_mm_base": round(max(0.0, legacy_objective_mm), 1),
        "dose_mm_effective": round(max(0.0, active_mm), 1),
        "dose_mm_target": round(candidate_band.target_mm, 1),
        "dose_mm_min": round(candidate_band.min_mm, 1),
        "dose_mm_max": round(candidate_band.max_mm, 1),
        "dose_inputs": normalized_inputs,
        "candidate_band": candidate_band.band,
        "candidate_mm": round(candidate_band.target_mm, 1),
        "candidate_reason": candidate_band.reason,
    }
    return payload


def _validate_policy_registry() -> None:
    for mode, policy in WATERING_POLICIES.items():
        if policy.mode != mode:
            raise ValueError(f"Policy registry mismatch for mode '{mode}'")
        if policy.category not in _VALID_POLICY_CATEGORIES:
            raise ValueError(f"Unsupported policy category for mode '{mode}': {policy.category}")
        if policy.override_behavior not in _VALID_OVERRIDE_BEHAVIORS:
            raise ValueError(
                f"Unsupported override behavior for mode '{mode}': {policy.override_behavior}"
            )
        if policy.blocking_behavior not in _VALID_BLOCKING_BEHAVIORS:
            raise ValueError(
                f"Unsupported blocking behavior for mode '{mode}': {policy.blocking_behavior}"
            )
        for allowed_mode in policy.allow_override_by:
            if allowed_mode not in WATERING_POLICIES:
                raise ValueError(
                    f"Unknown override mode '{allowed_mode}' declared by policy '{mode}'"
                )
        for application_type, rule in policy.application_types.items():
            normalized_type = _normalize_application_type(application_type)
            if normalized_type != application_type:
                raise ValueError(
                    f"Application type '{application_type}' for mode '{mode}' must be canonical"
                )
            if rule.override_behavior not in _VALID_OVERRIDE_BEHAVIORS:
                raise ValueError(
                    f"Unsupported application override behavior for mode '{mode}': {rule.override_behavior}"
                )


_validate_policy_registry()


def get_watering_policy(mode: str | None) -> WateringPolicy:
    return WATERING_POLICIES[_normalize_mode_name(mode)]


def _evaluate_weather_guard(weather: dict[str, Any]) -> BlockingEvaluation:
    if weather.get("heavy_rain_expected"):
        return BlockingEvaluation(True, "heavy_rain_expected")
    if weather.get("rain_compensating"):
        return BlockingEvaluation(True, "rain_compensating")
    return BlockingEvaluation(False, None)


def _evaluate_condition_guard(policy: WateringPolicy, weather: dict[str, Any], hydric_state: str | None) -> BlockingEvaluation:
    minimum_temperature = policy.conditions.get("temperature_min_c")
    if minimum_temperature is not None:
        try:
            if float(weather.get("temperature_c")) < float(minimum_temperature):
                return BlockingEvaluation(True, "temperature_below_minimum")
        except (TypeError, ValueError):
            return BlockingEvaluation(True, "temperature_unknown")

    required_soil_state = policy.conditions.get("soil_humidity_state")
    if required_soil_state:
        current_state = str(weather.get("soil_humidity_state") or hydric_state or "").strip().casefold()
        if current_state and current_state != str(required_soil_state).casefold():
            return BlockingEvaluation(True, "soil_humidity_state_mismatch")
    if policy.conditions.get("avoid_excess_rain") and weather.get("heavy_rain_expected"):
        return BlockingEvaluation(True, "heavy_rain_expected")
    return BlockingEvaluation(False, None)


def _evaluate_application_type_guard(policy: WateringPolicy, application_type: str | None) -> BlockingEvaluation:
    normalized_type = _normalize_application_type(application_type)
    if not normalized_type:
        return BlockingEvaluation(True, "application_type_required")
    if normalized_type not in policy.application_types:
        return BlockingEvaluation(True, "unsupported_application_type")
    return BlockingEvaluation(False, None)


def _evaluate_blocking(
    policy: WateringPolicy,
    *,
    weather: dict[str, Any],
    hydric_state: str | None,
    application_type: str | None,
) -> BlockingEvaluation:
    behavior = policy.blocking_behavior
    if behavior == BLOCKING_BEHAVIOR_NONE:
        return BlockingEvaluation(False, None)
    if behavior == BLOCKING_BEHAVIOR_WEATHER_GUARD:
        return _evaluate_weather_guard(weather)
    if behavior == BLOCKING_BEHAVIOR_CONDITION_GUARD:
        return _evaluate_condition_guard(policy, weather, hydric_state)
    if behavior == BLOCKING_BEHAVIOR_APPLICATION_TYPE_GUARD:
        return _evaluate_application_type_guard(policy, application_type)
    if behavior == BLOCKING_BEHAVIOR_BLOCKED_BY_DEFAULT:
        if policy.exceptions.get("prolonged_drought") and weather.get("prolonged_drought"):
            return BlockingEvaluation(False, None)
        return BlockingEvaluation(True, "blocked_by_default")
    return BlockingEvaluation(False, None)


def _select_target_range(policy: WateringPolicy, application_type: str | None) -> tuple[WateringRange | None, str]:
    normalized_type = _normalize_application_type(application_type)
    if normalized_type and normalized_type in policy.application_types:
        rule = policy.application_types[normalized_type]
        return rule.target_mm, rule.override_behavior
    if policy.event_target_mm is not None:
        return policy.event_target_mm, policy.override_behavior
    if policy.weekly_target_mm is not None:
        return policy.weekly_target_mm, policy.override_behavior
    return None, policy.override_behavior


def resolve_watering_policy(
    *,
    phase_dominante: str,
    sous_phase: str | None = None,
    application_type: str | None = None,
    weather: dict[str, Any] | None = None,
    hydric_state: str | None = None,
    active_modes: list[str] | tuple[str, ...] | None = None,
) -> ResolvedWateringPolicy:
    """Résout la politique active à partir du contexte métier.

    Ce resolver reste volontairement simple :
    - il sélectionne le mode le plus prioritaire ;
    - il applique les gardes de blocage connues ;
    - il retourne la plage cible effective.
    """

    del sous_phase  # réservé pour la future logique fine

    weather = _normalize_weather_payload(weather)
    normalized_requested_mode = _normalize_mode_name(phase_dominante)
    override_modes = set(_normalize_active_modes(active_modes, normalized_requested_mode))
    selected_policy = max(
        (WATERING_POLICIES[mode] for mode in override_modes),
        key=lambda policy: policy.priority,
    )

    if selected_policy.mode == MODE_HIVERNAGE and selected_policy.allow_override_by:
        for allowed_mode in selected_policy.allow_override_by:
            if allowed_mode in override_modes:
                selected_policy = WATERING_POLICIES[allowed_mode]
                break

    target_range, override_behavior = _select_target_range(selected_policy, application_type)
    blocking = _evaluate_blocking(
        selected_policy,
        weather=weather,
        hydric_state=hydric_state,
        application_type=application_type,
    )

    effective_strategy = selected_policy.base_strategy
    if selected_policy.execution is not None:
        effective_strategy = f"{effective_strategy}:{selected_policy.execution.preferred}"

    return ResolvedWateringPolicy(
        requested_mode=normalized_requested_mode,
        selected_mode=selected_policy.mode,
        policy=selected_policy,
        target_range=target_range,
        effective_strategy=effective_strategy,
        override_behavior=override_behavior,
        blocking_behavior=selected_policy.blocking_behavior,
        blocking=blocking,
        application_type=_normalize_application_type(application_type),
        active_modes=tuple(sorted(override_modes)),
    )


__all__ = [
    "BLOCKING_BEHAVIOR_APPLICATION_TYPE_GUARD",
    "BLOCKING_BEHAVIOR_BLOCKED_BY_DEFAULT",
    "BLOCKING_BEHAVIOR_BLOCK_OTHER_MODES",
    "BLOCKING_BEHAVIOR_CONDITION_GUARD",
    "BLOCKING_BEHAVIOR_NONE",
    "BLOCKING_BEHAVIOR_WEATHER_GUARD",
    "BlockingEvaluation",
    "DailyProgram",
    "MODE_AGENT_MOUILLANT",
    "MODE_BIOSTIMULANT",
    "MODE_FERTILISATION",
    "MODE_HIVERNAGE",
    "MODE_NORMAL",
    "MODE_SCARIFICATION",
    "MODE_SURSEMIS",
    "MODE_TRAITEMENT",
    "ResolvedWateringPolicy",
    "SemisStageProgram",
    "WATERING_POLICIES",
    "WateringApplicationTypeRule",
    "WateringExecution",
    "WateringPolicy",
    "WateringRange",
    "get_watering_policy",
    "resolve_dose_policy",
    "resolve_semis_stage_program",
    "resolve_watering_policy",
    "DosePolicyBand",
    "DOSE_BAND_AUTUMN",
    "DOSE_BAND_BASELINE",
    "DOSE_BAND_HEATWAVE",
    "DOSE_BAND_HIVERNAGE",
    "DOSE_BAND_SPRING",
    "DOSE_BAND_SUMMER",
    "DOSE_BAND_SURSEMIS",
    "DOSE_POLICY_BANDS",
]
