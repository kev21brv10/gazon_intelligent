from __future__ import annotations

from typing import Any


DEFAULT_ASSISTANT_DECISION: dict[str, Any] = {
    "action": "none",
    "moment": "none",
    "quantity_mm": 0.0,
    "status": "ok",
    "reason": "conditions optimales",
}


def _clean_text(value: object | None) -> str:
    if value in (None, "", [], {}):
        return ""
    return str(value).strip()


def _to_float(value: object | None, default: float = 0.0) -> float:
    if value in (None, "", [], {}):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _result(
    *,
    action: str,
    moment: str,
    quantity_mm: float,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "moment": moment,
        "quantity_mm": round(float(quantity_mm), 1),
        "status": status,
        "reason": reason.strip() or DEFAULT_ASSISTANT_DECISION["reason"],
    }


def _resolve_irrigation(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    objective = _to_float(snapshot.get("objectif_mm", snapshot.get("mm_final", 0.0)))
    if objective <= 0.0 or not bool(snapshot.get("arrosage_recommande", False)):
        return None

    block_reason = _clean_text(
        snapshot.get("sursemis_block_reason")
        or snapshot.get("block_reason")
    )
    moment = _clean_text(snapshot.get("fenetre_optimale")) or "maintenant"
    reason = _clean_text(
        snapshot.get("sursemis_reason")
        or snapshot.get("reason_decision")
        or snapshot.get("conseil_principal")
        or snapshot.get("action_recommandee")
    )

    if block_reason:
        return _result(
            action="arrosage",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=block_reason,
        )

    if not reason:
        reason = "Arrosage requis"

    return _result(
        action="arrosage",
        moment=moment,
        quantity_mm=objective,
        status="action_required",
        reason=reason,
    )


def _resolve_critical_action(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    phase = _clean_text(snapshot.get("phase_dominante") or snapshot.get("phase_active"))
    application_type = _clean_text(snapshot.get("application_type")).lower()
    application_block_active = bool(snapshot.get("application_block_active", False))
    application_requires = bool(snapshot.get("application_requires_watering_after", False))
    application_pending = bool(snapshot.get("application_post_watering_pending", False))
    application_summary = snapshot.get("derniere_application")

    critical_needed = phase == "Traitement" or (
        application_type in {"sol", "foliaire"} and application_requires
    )
    if not critical_needed:
        return None

    if phase == "Traitement" and application_block_active:
        return _result(
            action="traitement",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=_clean_text(snapshot.get("raison_decision") or "Traitement bloqué"),
        )

    if application_requires and not application_pending:
        return _result(
            action="traitement",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason="Application en attente, arrosage post-application non encore autorisé.",
        )

    reason = _clean_text(
        snapshot.get("reason_decision")
        or snapshot.get("conseil_principal")
        or snapshot.get("action_recommandee")
    )
    if not reason and isinstance(application_summary, dict):
        reason = _clean_text(
            application_summary.get("libelle")
            or application_summary.get("produit")
            or application_summary.get("type")
        )
    if not reason:
        reason = "Action critique requise"

    return _result(
        action="traitement",
        moment="maintenant",
        quantity_mm=0.0,
        status="action_required",
        reason=reason,
    )


def _resolve_mowing(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    mowing_allowed = bool(snapshot.get("tonte_autorisee", False))
    if not mowing_allowed:
        return None

    tonte_statut = _clean_text(snapshot.get("tonte_statut")).lower()
    block_reason = _clean_text(snapshot.get("raison_blocage_tonte"))
    if tonte_statut in {"interdite", "deconseillee", "bloquee", "bloque"} or block_reason:
        return _result(
            action="tonte",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=block_reason or "Tonte bloquée",
        )

    return _result(
        action="tonte",
        moment="maintenant",
        quantity_mm=0.0,
        status="action_required",
        reason="Tonte autorisée",
    )


def build_assistant_decision(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    data = snapshot if isinstance(snapshot, dict) else {}

    irrigation = _resolve_irrigation(data)
    if irrigation is not None:
        return irrigation

    critical = _resolve_critical_action(data)
    if critical is not None:
        return critical

    mowing = _resolve_mowing(data)
    if mowing is not None:
        return mowing

    return dict(DEFAULT_ASSISTANT_DECISION)
