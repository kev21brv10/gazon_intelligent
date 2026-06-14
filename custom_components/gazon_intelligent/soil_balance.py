from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None

SOIL_RESERVE_BASE_MM = {
    "sableux": 8.0,
    "limoneux": 12.0,
    "argileux": 16.0,
}

SOIL_RESERVE_MAX_MM = {
    "sableux": 16.0,
    "limoneux": 24.0,
    "argileux": 32.0,
}

SOIL_RESERVE_DEFAULT_BASE_MM = 12.0
SOIL_RESERVE_DEFAULT_MAX_MM = 24.0
SOIL_BALANCE_LEDGER_LIMIT = 120


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_half_up_1(value: float) -> float:
    # int(x * 10 + 0.5) rounds toward +inf for positives but toward zero for
    # negatives, producing an asymmetric result (e.g. -1.2 → -1.1).
    # We apply the same logic on the absolute value and restore the sign so that
    # previous_reserve + delta_mm == reserve_mm holds after rounding.
    if value < 0:
        return -float(int(abs(value) * 10.0 + 0.5)) / 10.0
    return float(int(value * 10.0 + 0.5)) / 10.0


def base_reserve_mm(type_sol: str | None) -> float:
    return float(SOIL_RESERVE_BASE_MM.get(type_sol or "", SOIL_RESERVE_DEFAULT_BASE_MM))


def max_reserve_mm(type_sol: str | None) -> float:
    return float(SOIL_RESERVE_MAX_MM.get(type_sol or "", SOIL_RESERVE_DEFAULT_MAX_MM))


def _normalize_ledger_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    raw_date = entry.get("date")
    if not raw_date:
        return None
    try:
        date.fromisoformat(str(raw_date))
    except ValueError:
        return None
    normalized = {
        "date": str(raw_date),
        "reserve_mm": _to_float(entry.get("reserve_mm")),
        "previous_reserve_mm": _to_float(entry.get("previous_reserve_mm")),
        "pluie_mm": _to_float(entry.get("pluie_mm")),
        "arrosage_mm": _to_float(entry.get("arrosage_mm")),
        "etp_mm": _to_float(entry.get("etp_mm")),
        "delta_mm": _to_float(entry.get("delta_mm")),
        "type_sol": str(entry.get("type_sol")) if entry.get("type_sol") else None,
        # Marque une réserve recalée manuellement (service recalibrate_reserve) : la
        # journée correspondante ne doit pas être recalculée depuis l'historique.
        "manual_anchor": True if entry.get("manual_anchor") else None,
    }
    clean = {key: value for key, value in normalized.items() if value not in (None, "", {}, [])}
    return clean or None


def normalize_soil_balance_state(state: dict[str, Any] | None) -> dict[str, Any]:
    state = state or {}
    ledger = state.get("ledger")
    if isinstance(ledger, list):
        normalized_ledger = []
        for item in ledger:
            normalized = _normalize_ledger_entry(item)
            if normalized is not None:
                normalized_ledger.append(normalized)
        ledger = normalized_ledger[-SOIL_BALANCE_LEDGER_LIMIT:]
    else:
        ledger = []

    today = state.get("date")
    reserve_mm = _to_float(state.get("reserve_mm"))
    previous_reserve_mm = _to_float(state.get("previous_reserve_mm"))
    pluie_mm = _to_float(state.get("pluie_mm"))
    arrosage_mm = _to_float(state.get("arrosage_mm"))
    etp_mm = _to_float(state.get("etp_mm"))
    delta_mm = _to_float(state.get("delta_mm"))
    type_sol = str(state.get("type_sol")) if state.get("type_sol") else None
    reserve_min_mm = _to_float(state.get("reserve_min_mm"))
    reserve_max = _to_float(state.get("reserve_max_mm"))

    if reserve_min_mm is None:
        reserve_min_mm = 0.0
    if reserve_max is None:
        reserve_max = max_reserve_mm(type_sol)
    if reserve_mm is None and ledger:
        reserve_mm = _to_float(ledger[-1].get("reserve_mm"))
    if previous_reserve_mm is None and ledger:
        previous_reserve_mm = _to_float(ledger[-1].get("previous_reserve_mm"))

    clean = {
        "date": today if isinstance(today, str) else (str(today) if today else None),
        "reserve_mm": reserve_mm,
        "previous_reserve_mm": previous_reserve_mm,
        "pluie_mm": pluie_mm,
        "arrosage_mm": arrosage_mm,
        "etp_mm": etp_mm,
        "delta_mm": delta_mm,
        "type_sol": type_sol,
        "reserve_min_mm": reserve_min_mm,
        "reserve_max_mm": reserve_max,
        "ledger": ledger,
    }
    return clean


def update_soil_balance(
    previous_state: dict[str, Any] | None,
    today: date | None = None,
    pluie_mm: float | None = None,
    arrosage_mm: float | None = None,
    etp_mm: float | None = None,
    type_sol: str | None = None,
) -> dict[str, Any]:
    if today is None:
        if dt_util is not None:
            now_getter = getattr(dt_util, "now", None)
            if callable(now_getter):
                current = now_getter()
                if isinstance(current, datetime):
                    today = current.date()
        if today is None:
            today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    state = normalize_soil_balance_state(previous_state)
    ledger = list(state.get("ledger") or [])

    if ledger and ledger[-1].get("date") == today_str and ledger[-1].get("manual_anchor"):
        # Réserve recalée manuellement aujourd'hui (service recalibrate_reserve) : on
        # conserve l'ancre pour le reste de la journée au lieu de la recalculer depuis
        # l'historique (qui peut contenir d'anciens doublons). L'évolution normale (ET,
        # pluie, arrosage) reprend dès le lendemain.
        return state

    reserve_min_mm = _to_float(state.get("reserve_min_mm"))
    if reserve_min_mm is None:
        reserve_min_mm = 0.0
    reserve_max_mm = _to_float(state.get("reserve_max_mm"))
    if reserve_max_mm is None:
        reserve_max_mm = max_reserve_mm(type_sol or state.get("type_sol"))
    if reserve_max_mm < reserve_min_mm:
        reserve_max_mm = reserve_min_mm

    if ledger and ledger[-1].get("date") == today_str:
        previous_reserve = _to_float(ledger[-1].get("previous_reserve_mm"))
        if previous_reserve is None:
            previous_reserve = _to_float(state.get("previous_reserve_mm"))
    else:
        previous_reserve = _to_float(state.get("reserve_mm"))
        if previous_reserve is None:
            previous_reserve = base_reserve_mm(type_sol or state.get("type_sol"))

    pluie_raw = max(0.0, _to_float(pluie_mm) or 0.0)
    arrosage_raw = max(0.0, _to_float(arrosage_mm) or 0.0)
    pluie_suspect = pluie_raw > 100.0
    arrosage_suspect = arrosage_raw > 50.0
    pluie = min(pluie_raw, 30.0) if pluie_suspect else pluie_raw
    arrosage = min(arrosage_raw, 25.0) if arrosage_suspect else arrosage_raw
    etp = max(0.0, _to_float(etp_mm) or 0.0)
    delta = pluie + arrosage - etp
    reserve_mm = min(max(previous_reserve + delta, reserve_min_mm), reserve_max_mm)

    entry = {
        "date": today_str,
        "previous_reserve_mm": _round_half_up_1(previous_reserve),
        "pluie_mm": _round_half_up_1(pluie),
        "arrosage_mm": _round_half_up_1(arrosage),
        "etp_mm": _round_half_up_1(etp),
        "delta_mm": _round_half_up_1(delta),
        "reserve_mm": _round_half_up_1(reserve_mm),
        "type_sol": type_sol or state.get("type_sol"),
    }
    if pluie_suspect:
        entry["pluie_suspect"] = True
    if arrosage_suspect:
        entry["arrosage_suspect"] = True
    entry = {key: value for key, value in entry.items() if value not in (None, "", {}, [])}

    if ledger and ledger[-1].get("date") == today_str:
        ledger[-1] = entry
    else:
        ledger.append(entry)
    ledger = ledger[-SOIL_BALANCE_LEDGER_LIMIT:]

    return {
        "date": today_str,
        "reserve_mm": _round_half_up_1(reserve_mm),
        "previous_reserve_mm": _round_half_up_1(previous_reserve),
        "pluie_mm": _round_half_up_1(pluie),
        "arrosage_mm": _round_half_up_1(arrosage),
        "etp_mm": _round_half_up_1(etp),
        "delta_mm": _round_half_up_1(delta),
        "type_sol": type_sol or state.get("type_sol"),
        "reserve_min_mm": _round_half_up_1(reserve_min_mm),
        "reserve_max_mm": _round_half_up_1(reserve_max_mm),
        "ledger": ledger,
    }


def set_reserve_mm(
    previous_state: dict[str, Any] | None,
    reserve_mm: float,
    today: date | None = None,
    type_sol: str | None = None,
) -> dict[str, Any]:
    """Recale la réserve sol à une valeur connue (calibration manuelle).

    Pose une entrée « ancre » pour aujourd'hui : `update_soil_balance` ne la recalcule
    pas depuis l'historique (utile quand l'historique contient d'anciens doublons). La
    valeur est bornée à [reserve_min, reserve_max]. L'évolution normale reprend le
    lendemain à partir de cette valeur.
    """
    if today is None:
        if dt_util is not None:
            now_getter = getattr(dt_util, "now", None)
            if callable(now_getter):
                current = now_getter()
                if isinstance(current, datetime):
                    today = current.date()
        if today is None:
            today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    state = normalize_soil_balance_state(previous_state)
    ledger = list(state.get("ledger") or [])

    resolved_type = type_sol or state.get("type_sol")
    reserve_max = _to_float(state.get("reserve_max_mm"))
    if reserve_max is None:
        reserve_max = max_reserve_mm(resolved_type)
    reserve_min = _to_float(state.get("reserve_min_mm"))
    if reserve_min is None:
        reserve_min = 0.0
    if reserve_max < reserve_min:
        reserve_max = reserve_min
    raw = _to_float(reserve_mm)
    if raw is None or raw != raw:  # None ou NaN (NaN != NaN)
        raw = reserve_min
    value = _round_half_up_1(min(max(raw, reserve_min), reserve_max))

    entry = {
        "date": today_str,
        "previous_reserve_mm": value,
        "pluie_mm": 0.0,
        "arrosage_mm": 0.0,
        "etp_mm": 0.0,
        "delta_mm": 0.0,
        "reserve_mm": value,
        "type_sol": resolved_type,
        "manual_anchor": True,
    }
    entry = {key: val for key, val in entry.items() if val not in (None, "", {}, [])}
    if ledger and ledger[-1].get("date") == today_str:
        ledger[-1] = entry
    else:
        ledger.append(entry)
    ledger = ledger[-SOIL_BALANCE_LEDGER_LIMIT:]

    return {
        "date": today_str,
        "reserve_mm": value,
        "previous_reserve_mm": value,
        "pluie_mm": 0.0,
        "arrosage_mm": 0.0,
        "etp_mm": 0.0,
        "delta_mm": 0.0,
        "type_sol": resolved_type,
        "reserve_min_mm": _round_half_up_1(reserve_min),
        "reserve_max_mm": _round_half_up_1(reserve_max),
        "ledger": ledger,
    }
