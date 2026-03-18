from __future__ import annotations

from datetime import date
from typing import Any

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
    today = today or date.today()
    today_str = today.isoformat()
    state = normalize_soil_balance_state(previous_state)
    ledger = list(state.get("ledger") or [])

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

    pluie = max(0.0, _to_float(pluie_mm) or 0.0)
    arrosage = max(0.0, _to_float(arrosage_mm) or 0.0)
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

