from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .const import APPLICATION_INTERVENTIONS
from .memory import (
    _normalize_text,
    format_application_months_label,
    normalize_application_months,
    normalize_product_id,
)


def _parse_date(value: object | None) -> date | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    return None


def _normalize_product_catalogue(product: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(product, dict):
        return {}
    return product


def _selected_product_candidate(
    products: list[dict[str, Any]],
    selected_product_id: str | None,
    selected_product_name: str | None,
) -> dict[str, Any] | None:
    normalized_product_id = normalize_product_id(selected_product_id)
    normalized_product_name = normalize_product_id(selected_product_name)
    if not normalized_product_id and not normalized_product_name:
        return None

    for product in products:
        if not isinstance(product, dict):
            continue
        product_id = normalize_product_id(product.get("id"))
        product_name = normalize_product_id(product.get("nom"))
        if normalized_product_id and normalized_product_id == product_id:
            return product
        if normalized_product_name and normalized_product_name in {product_id, product_name}:
            return product
    return None


def _latest_application_for_product(
    history: list[dict[str, Any]],
    product_id: str,
    product_name: str | None = None,
) -> dict[str, Any] | None:
    normalized_product_id = normalize_product_id(product_id)
    normalized_product_name = normalize_product_id(product_name)
    if not normalized_product_id and not normalized_product_name:
        return None

    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type not in APPLICATION_INTERVENTIONS and not any(
            item.get(key) not in (None, "", [], {})
            for key in (
                "application_type",
                "application_requires_watering_after",
                "application_post_watering_mm",
                "application_irrigation_block_hours",
                "application_irrigation_delay_minutes",
                "application_irrigation_mode",
                "application_label_notes",
                "produit",
                "dose",
                "reapplication_after_days",
            )
        ):
            continue

        candidate_ids = {
            normalize_product_id(item.get("produit_id")),
            normalize_product_id(item.get("produit")),
            normalize_product_id(item.get("libelle")),
        }
        produit_catalogue = _normalize_product_catalogue(item.get("produit_catalogue"))
        candidate_ids.update(
            {
                normalize_product_id(produit_catalogue.get("id")),
                normalize_product_id(produit_catalogue.get("nom")),
            }
        )
        if normalized_product_id in candidate_ids or (
            normalized_product_name and normalized_product_name in candidate_ids
        ):
            return item

    return None


def _format_reasons(reasons: list[str]) -> str:
    clean = [str(reason).strip() for reason in reasons if str(reason).strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    return " · ".join(clean[:3])


def _clamp_score(value: int | float | None) -> int:
    if value is None:
        return 0
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


def _state_metadata(state: str) -> dict[str, str]:
    if state == "recommended":
        return {
            "title": "Intervention recommandée",
            "badge": "Choisie automatiquement",
            "tone": "success",
            "icon": "mdi:spray-bottle",
            "summary": "Prête à déclarer",
            "action_label": "Déclarer maintenant",
        }
    if state == "possible":
        return {
            "title": "Intervention à préparer",
            "badge": "À préparer",
            "tone": "warning",
            "icon": "mdi:package-variant-closed",
            "summary": "Produit conseillé",
            "action_label": "Choisir le produit",
        }
    if state == "blocked":
        return {
            "title": "Intervention en pause",
            "badge": "En attente",
            "tone": "danger",
            "icon": "mdi:pause-circle-outline",
            "summary": "Déclaration verrouillée",
            "action_label": "Attendre",
        }
    return {
        "title": "Catalogue vide",
        "badge": "À compléter",
        "tone": "neutral",
        "icon": "mdi:package-variant-closed",
        "summary": "Aucun produit enregistré",
        "action_label": "Ajouter un produit",
    }


def _evaluate_product_candidate(
    *,
    product: dict[str, Any],
    history: list[dict[str, Any]],
    today: date,
    phase_active: str | None,
    selected_product_id: str | None,
) -> dict[str, Any]:
    product_id = normalize_product_id(product.get("id"))
    product_name = str(product.get("nom") or product_id or "").strip()
    product_type = str(product.get("type") or "").strip()
    phase_compatible = [str(value).strip() for value in (product.get("phase_compatible") or []) if str(value).strip()]
    months = normalize_application_months(product.get("application_months"))
    months_label = format_application_months_label(months)
    latest_application = _latest_application_for_product(history, product_id or "", product_name)
    delay_days = None
    try:
        delay_days = int(float(product.get("reapplication_after_days")))
    except (TypeError, ValueError):
        delay_days = None
    latest_application_date = _parse_date(
        latest_application.get("date") if isinstance(latest_application, dict) else None
    )
    next_reapplication_date = None
    due = True
    if delay_days is not None and delay_days >= 0 and latest_application_date is not None:
        next_reapplication_date = latest_application_date + timedelta(days=delay_days)
        due = today >= next_reapplication_date

    reasons: list[str] = []
    score = 0

    if selected_product_id and product_id and normalize_product_id(selected_product_id) == product_id:
        score += 20
        reasons.append("Produit sélectionné")

    normalized_phase = _normalize_text(phase_active)
    normalized_phase_compatible = {_normalize_text(value) for value in phase_compatible}
    phase_match = not phase_compatible or normalized_phase in normalized_phase_compatible
    if phase_compatible:
        if phase_match:
            score += 25
            reasons.append(f"Phase compatible ({', '.join(phase_compatible[:3])})")
        else:
            score -= 12
            reasons.append(f"Phase moins adaptée ({', '.join(phase_compatible[:3])})")
    else:
        score += 2

    month_match = not months or today.month in months
    if months:
        if month_match:
            score += 18
            reasons.append(f"Mois compatibles ({months_label})")
        else:
            score -= 8
            reasons.append(f"Hors période idéale ({months_label})")

    if delay_days is not None:
        if latest_application_date is None:
            score += 4
            reasons.append("Aucun historique de réapplication")
        elif due:
            score += 18
            reasons.append(
                f"Réapplication possible depuis le {next_reapplication_date.strftime('%d/%m/%Y')}"
            )
        else:
            score -= 45
            reasons.append(
                f"Réapplication possible à partir du {next_reapplication_date.strftime('%d/%m/%Y')}"
            )
    else:
        score += 3 if latest_application_date is None else 0

    if product_type:
        score += 1

    blocked_reason = None
    if delay_days is not None and not due and next_reapplication_date is not None:
        blocked_reason = f"Réapplication attendue jusqu'au {next_reapplication_date.strftime('%d/%m/%Y')}."

    return {
        "product_id": product_id,
        "product_name": product_name or product_id,
        "product_type": product_type or None,
        "phase_compatible": phase_compatible,
        "months": months,
        "months_label": months_label,
        "latest_application_date": latest_application_date.isoformat() if latest_application_date else None,
        "next_reapplication_date": next_reapplication_date.isoformat() if next_reapplication_date else None,
        "due": due,
        "phase_match": phase_match,
        "month_match": month_match,
        "selected": bool(selected_product_id and product_id and normalize_product_id(selected_product_id) == product_id),
        "score": _clamp_score(score),
        "reasons": reasons,
        "blocked_reason": blocked_reason,
    }


def _priority_from_state(state: str, score: int) -> str:
    if state == "recommended":
        return "high" if score >= 70 else "medium"
    if state == "possible":
        return "medium"
    if state == "blocked":
        return "blocked"
    return "none"


def _constraint_entry(
    *,
    code: str,
    label: str,
    value: Any = None,
    hint: str = "",
    blocking: bool = False,
    met: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "value": value,
        "hint": hint,
        "blocking": bool(blocking),
        "met": bool(met),
    }


def _missing_requirement_entry(
    *,
    code: str,
    label: str,
    value: Any = None,
    hint: str = "",
    blocking: bool = False,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "value": value,
        "hint": hint,
        "blocking": bool(blocking),
    }


def _product_details(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if not candidate:
        return {
            "id": None,
            "name": None,
            "type": None,
            "months": [],
            "months_label": None,
            "phase_compatible": [],
            "latest_application_date": None,
            "next_reapplication_date": None,
            "next_reapplication_display": None,
            "due": False,
            "phase_match": False,
            "month_match": False,
        }
    next_reapplication_date = candidate.get("next_reapplication_date")
    next_reapplication_display = None
    parsed_next_date = _parse_date(next_reapplication_date)
    if parsed_next_date is not None:
        next_reapplication_display = parsed_next_date.strftime("%d/%m/%Y")
    elif next_reapplication_date:
        next_reapplication_display = str(next_reapplication_date)
    return {
        "id": candidate.get("product_id"),
        "name": candidate.get("product_name"),
        "type": candidate.get("product_type"),
        "months": candidate.get("months") or [],
        "months_label": candidate.get("months_label"),
        "phase_compatible": candidate.get("phase_compatible") or [],
        "latest_application_date": candidate.get("latest_application_date"),
        "next_reapplication_date": next_reapplication_date,
        "next_reapplication_display": next_reapplication_display,
        "due": bool(candidate.get("due")),
        "phase_match": bool(candidate.get("phase_match")),
        "month_match": bool(candidate.get("month_match")),
    }


def _selection_details(
    *,
    selected_product_id: str | None,
    selected_product_name: str | None,
    selected_candidate: dict[str, Any] | None,
    ready: bool,
) -> dict[str, Any]:
    if not selected_product_id and not selected_product_name and not selected_candidate:
        return {
            "id": None,
            "name": None,
            "type": None,
            "months": [],
            "months_label": None,
            "ready": False,
            "selected": False,
        }

    details = _product_details(selected_candidate) if selected_candidate else {
        "id": normalize_product_id(selected_product_id) or None,
        "name": selected_product_name or selected_product_id or None,
        "type": None,
        "months": [],
        "months_label": None,
        "phase_compatible": [],
        "latest_application_date": None,
        "next_reapplication_date": None,
        "next_reapplication_display": None,
        "due": False,
        "phase_match": False,
        "month_match": False,
    }
    return {
        "id": details.get("id"),
        "name": details.get("name") or selected_product_name or selected_product_id,
        "type": details.get("type"),
        "months": details.get("months") or [],
        "months_label": details.get("months_label"),
        "ready": bool(ready),
        "selected": True,
    }


def _constraints_for_candidate(
    *,
    candidate: dict[str, Any] | None,
    state: str,
    block_reason: str | None,
    selected_ready: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if not candidate:
        constraints = [
            _constraint_entry(
                code="catalogue_empty",
                label="Aucun produit enregistré",
                value={"catalogue_count": 0},
                hint="Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                blocking=True,
                met=False,
            )
        ]
        return (
            constraints,
            [
                _missing_requirement_entry(
                    code="catalogue_empty",
                    label="Ajouter un produit au catalogue",
                    value={"catalogue_count": 0},
                    hint="Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                    blocking=True,
                )
            ],
            "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
        )

    constraints: list[dict[str, Any]] = []
    missing_requirements: list[dict[str, Any]] = []

    phase_compatible = candidate.get("phase_compatible") or []
    if phase_compatible:
        phase_label = ", ".join(str(value) for value in phase_compatible[:3])
        constraints.append(
            _constraint_entry(
                code="phase_compatibility",
                label=f"Phase compatible ({phase_label})" if candidate.get("phase_match") else f"Phase moins adaptée ({phase_label})",
                value={
                    "expected": phase_compatible,
                    "current": candidate.get("current_phase"),
                    "matched": bool(candidate.get("phase_match")),
                },
                hint="La phase dominante du gazon influence la pertinence du produit.",
                blocking=False,
                met=bool(candidate.get("phase_match")),
            )
        )

    months = candidate.get("months") or []
    months_label = candidate.get("months_label")
    if months:
        constraints.append(
            _constraint_entry(
                code="application_months",
                label=f"Mois compatibles ({months_label})" if candidate.get("month_match") else f"Hors période idéale ({months_label})",
                value={
                    "months": months,
                    "current_month": candidate.get("current_month"),
                    "matched": bool(candidate.get("month_match")),
                },
                hint="Les mois d’application aident à garder la recommandation saisonnière cohérente.",
                blocking=False,
                met=bool(candidate.get("month_match")),
            )
        )

    if candidate.get("next_reapplication_date"):
        next_display = candidate.get("next_reapplication_display") or candidate.get("next_reapplication_date")
        constraints.append(
            _constraint_entry(
                code="reapplication_delay",
                label=(
                    f"Réapplication possible depuis le {next_display}"
                    if candidate.get("due")
                    else f"Réapplication attendue jusqu'au {next_display}"
                ),
                value={
                    "due": bool(candidate.get("due")),
                    "next_reapplication_date": candidate.get("next_reapplication_date"),
                    "next_reapplication_display": next_display,
                },
                hint="Le délai de réapplication évite les interventions trop rapprochées.",
                blocking=not bool(candidate.get("due")),
                met=bool(candidate.get("due")),
            )
        )

    if state == "recommended" and not selected_ready:
        missing_requirements.append(
            _missing_requirement_entry(
                code="select_product",
                label="Sélectionner le produit recommandé",
                value={"product_id": candidate.get("product_id"), "product_name": candidate.get("product_name")},
                hint="Le produit recommandé est prêt, mais il doit être sélectionné pour déclencher la déclaration.",
                blocking=False,
            )
        )
    elif state == "possible":
        missing_requirements.append(
            _missing_requirement_entry(
                code="prepare_declaration",
                label="Préparer la déclaration avec le produit recommandé",
                value={"product_id": candidate.get("product_id"), "product_name": candidate.get("product_name")},
                hint="La recommandation est disponible, mais la déclaration doit encore être préparée.",
                blocking=False,
            )
        )
    elif state == "blocked":
        missing_requirements.append(
            _missing_requirement_entry(
                code="wait",
                label="Attendre la fin du blocage",
                value={"blocked_reason": block_reason},
                hint="Une application récente ou un délai post-application bloque encore la déclaration.",
                blocking=True,
            )
        )

    if block_reason:
        constraints.append(
            _constraint_entry(
                code="post_application_block",
                label=block_reason,
                value={"blocked_reason": block_reason},
                hint="Le moteur attend la fin du blocage post-application.",
                blocking=True,
                met=False,
            )
        )
        if not missing_requirements or missing_requirements[0]["code"] != "wait":
            missing_requirements.insert(
                0,
                _missing_requirement_entry(
                    code="wait",
                    label="Attendre la fin du blocage",
                    value={"blocked_reason": block_reason},
                    hint="Le délai ou l’arrosage post-application n’est pas encore terminé.",
                    blocking=True,
                ),
            )

    if not missing_requirements and state == "recommended" and selected_ready:
        missing_requirements = []

    return constraints, missing_requirements, ""


def _ui_for_state(
    *,
    state: str,
    metadata: dict[str, str],
    candidate: dict[str, Any] | None,
    selected_details: dict[str, Any] | None,
    selected_ready: bool,
    block_reason: str | None,
    reason: str,
    why_now: str,
    today: date,
) -> dict[str, str]:
    selected_name = (selected_details or {}).get("name")
    selected_months_label = (selected_details or {}).get("months_label")
    selected_display = selected_name or (candidate or {}).get("product_name")
    today_display = today.strftime("%d/%m/%Y")
    if state == "recommended":
        if selected_ready:
            summary = "Prête à déclarer"
            hint = reason or f"{selected_display or 'Le produit'} est prêt à être déclaré."
            action_label = "Déclarer maintenant"
        else:
            summary = "Produit conseillé"
            hint = reason or (
                f"Sélectionne {selected_display} pour lancer la déclaration."
                if selected_display
                else "Sélectionne ce produit pour préparer la déclaration."
            )
            action_label = "Choisir le produit"
    elif state == "possible":
        summary = "À préparer"
        hint = reason or "Le produit est disponible, mais la déclaration attend encore un petit réglage."
        action_label = "Choisir le produit"
    elif state == "blocked":
        summary = "En pause"
        hint = block_reason or reason or "La réapplication n'est pas encore possible."
        action_label = "Attendre"
    else:
        summary = "Catalogue vide"
        hint = reason or "Ajoute au moins un produit au catalogue pour obtenir une recommandation."
        action_label = "Ajouter un produit"

    return {
        "title": metadata["title"],
        "badge": metadata["badge"],
        "tone": metadata["tone"],
        "icon": metadata["icon"],
        "summary": summary,
        "hint": why_now or hint,
        "action_label": action_label,
        "selection_summary": (
            f"Produit choisi : {selected_display}. Date d'action : {today_display}."
            if selected_display and selected_ready
            else (
                f"Produit choisi : {selected_display}."
                if selected_display
                else (
                    f"Produit recommandé : {(candidate or {}).get('product_name')}. Sélectionne-le pour préparer la déclaration."
                    if candidate and candidate.get("product_name") and state in {"recommended", "possible"}
                    else "Sélectionne un produit dans la liste pour préparer la déclaration."
                )
            )
        ),
        "selection_hint": (
            f"Période sélectionnée: {selected_months_label}."
            if selected_months_label and selected_display
            else (
                f"Période recommandée: {(candidate or {}).get('months_label')}."
                if candidate and candidate.get("months_label")
                else "La sélection met à jour le produit actif."
            )
        ),
        "declaration_summary": (
            f"Produit choisi : {selected_display}. Date d'action : {today_display}."
            if selected_ready and selected_display
            else (
                f"Produit choisi : {selected_display}."
                if selected_display
                else "Sélectionne un produit pour activer la déclaration."
            )
        ),
        "declaration_hint": (
            "Tu peux déclarer l’intervention maintenant."
            if selected_ready
            else (
                "Le produit choisi doit correspondre à la recommandation automatique."
                if selected_display
                else "Le bouton se débloque dès qu’un produit est prêt."
            )
        ),
        "history_summary": "Dernière application",
        "history_hint": "Historique local des applications enregistrées.",
    }


def build_intervention_recommendation(
    *,
    today: date,
    phase_active: str | None,
    sous_phase: str | None,
    selected_product_id: str | None,
    selected_product_name: str | None,
    products: dict[str, dict[str, Any]] | None,
    history: list[dict[str, Any]] | None,
    application_state: dict[str, Any] | None,
) -> dict[str, Any]:
    products_map = products if isinstance(products, dict) else {}
    history_list = [item for item in (history or []) if isinstance(item, dict)]
    catalogue_products = [
        product
        for product in products_map.values()
        if isinstance(product, dict) and normalize_product_id(product.get("id"))
    ]

    selected_product_id = normalize_product_id(selected_product_id)
    selected_product_name = str(selected_product_name or "").strip() or None
    selected_candidate = _selected_product_candidate(catalogue_products, selected_product_id, selected_product_name)
    selected_details = _selection_details(
        selected_product_id=selected_product_id,
        selected_product_name=selected_product_name,
        selected_candidate=selected_candidate,
        ready=False,
    )
    application_state = application_state or {}
    block_active = bool(application_state.get("application_block_active"))
    post_watering_pending = bool(application_state.get("application_post_watering_pending"))
    delay_remaining = float(application_state.get("application_post_watering_delay_remaining_minutes") or 0.0)
    block_reason = str(application_state.get("application_block_reason") or "").strip()
    if not block_reason and block_active:
        block_reason = "Une application récente bloque encore toute nouvelle intervention."
    if not block_reason and post_watering_pending:
        block_reason = "L'arrosage post-application n'est pas encore terminé."
    if not block_reason and delay_remaining > 0:
        block_reason = "Un délai post-application est encore en cours."

    if not catalogue_products:
        metadata = _state_metadata("unavailable")
        ui = _ui_for_state(
            state="unavailable",
            metadata=metadata,
            candidate=None,
            selected_details=selected_details,
            selected_ready=False,
            block_reason=None,
            reason="Aucun produit enregistré",
            why_now="Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
            today=today,
        )
        return {
            "schema_version": 3,
            "status": "unavailable",
            "recommended_action": "add_product",
            "priority": _priority_from_state("unavailable", 0),
            "score": 0,
            "reason": "Aucun produit enregistré",
            "why_now": "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
            "reasons": [],
            "constraints": [
                {
                    "code": "catalogue_empty",
                    "label": "Aucun produit enregistré",
                    "value": {"catalogue_count": 0},
                    "hint": "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                    "blocking": True,
                    "met": False,
                }
            ],
            "missing_requirements": [
                _missing_requirement_entry(
                    code="catalogue_empty",
                    label="Ajouter un produit au catalogue",
                    value={"catalogue_count": 0},
                    hint="Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                    blocking=True,
                )
            ],
            "month_match": False,
            "ready_to_declare": False,
            "selected_product_ready": False,
            "product": _product_details(None),
            "selection": _selection_details(
                selected_product_id=selected_product_id,
                selected_product_name=selected_product_name,
                selected_candidate=None,
                ready=False,
            ),
            "context": {
                "catalogue_count": 0,
                "eligible_count": 0,
                "current_month": today.month,
                "current_phase": phase_active,
                "current_sub_phase": sous_phase,
            },
            "ui": ui,
        }

    candidates = [
        _evaluate_product_candidate(
            product=product,
            history=history_list,
            today=today,
            phase_active=phase_active,
            selected_product_id=selected_product_id,
        )
        for product in catalogue_products
    ]
    candidates.sort(
        key=lambda item: (
            int(bool(item["selected"])),
            int(bool(item["due"])),
            int(bool(item["phase_match"])),
            int(bool(item["month_match"])),
            float(item["score"]),
            str(item["product_name"]).casefold(),
        ),
        reverse=True,
    )

    best = candidates[0] if candidates else None
    eligible_candidates = [
        candidate
        for candidate in candidates
        if candidate["due"] and candidate["phase_match"] and candidate["month_match"]
    ]
    blocked_candidates = [candidate for candidate in candidates if not candidate["due"]]

    if block_active or post_watering_pending:
        metadata = _state_metadata("blocked")
        reasons = []
        if block_reason:
            reasons.append(block_reason)
        if selected_product_id and best and best["product_id"] == selected_product_id:
            reasons.append(f"{best['product_name']} est sélectionné mais reste bloqué.")
        reason_text = _format_reasons(reasons) or "Attends la fin du blocage post-application avant de déclarer une nouvelle intervention."
        ui = _ui_for_state(
            state="blocked",
            metadata=metadata,
            candidate=best,
            selected_details=selected_details,
            selected_ready=False,
            block_reason=block_reason,
            reason=reason_text,
            why_now=reason_text,
            today=today,
        )
        constraints, missing_requirements, _ = _constraints_for_candidate(
            candidate=best,
            state="blocked",
            block_reason=block_reason or reason_text,
            selected_ready=False,
        )
        return {
            "schema_version": 3,
            "status": "blocked",
            "recommended_action": "wait",
            "priority": _priority_from_state("blocked", int(best["score"]) if best else 0),
            "score": int(best["score"]) if best else 0,
            "reason": reason_text,
            "why_now": reason_text,
            "reasons": best["reasons"] if best else reasons,
            "constraints": constraints,
            "missing_requirements": missing_requirements,
            "month_match": bool(best["month_match"]) if best else False,
            "ready_to_declare": False,
            "selected_product_ready": False,
            "product": _product_details(best),
            "selection": _selection_details(
                selected_product_id=selected_product_id,
                selected_product_name=selected_product_name,
                selected_candidate=selected_candidate,
                ready=False,
            ),
            "context": {
                "catalogue_count": len(catalogue_products),
                "eligible_count": len(eligible_candidates),
                "current_month": today.month,
                "current_phase": phase_active,
                "current_sub_phase": sous_phase,
            },
            "ui": ui,
        }

    if best is None:
        metadata = _state_metadata("unavailable")
        ui = _ui_for_state(
            state="unavailable",
            metadata=metadata,
            candidate=None,
            selected_details=selected_details,
            selected_ready=False,
            block_reason=None,
            reason="Aucun produit enregistré",
            why_now="Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
            today=today,
        )
        return {
            "schema_version": 3,
            "status": "unavailable",
            "recommended_action": "add_product",
            "priority": _priority_from_state("unavailable", 0),
            "score": 0,
            "reason": "Aucun produit enregistré",
            "why_now": "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
            "reasons": [],
            "constraints": [
                {
                    "code": "catalogue_empty",
                    "label": "Aucun produit enregistré",
                    "value": {"catalogue_count": 0},
                    "hint": "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                    "blocking": True,
                    "met": False,
                }
            ],
            "missing_requirements": [
                _missing_requirement_entry(
                    code="catalogue_empty",
                    label="Ajouter un produit au catalogue",
                    value={"catalogue_count": 0},
                    hint="Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                    blocking=True,
                )
            ],
            "month_match": False,
            "ready_to_declare": False,
            "selected_product_ready": False,
            "product": _product_details(None),
            "selection": _selection_details(
                selected_product_id=selected_product_id,
                selected_product_name=selected_product_name,
                selected_candidate=selected_candidate,
                ready=False,
            ),
            "context": {
                "catalogue_count": len(catalogue_products),
                "eligible_count": len(eligible_candidates),
                "current_month": today.month,
                "current_phase": phase_active,
                "current_sub_phase": sous_phase,
            },
            "ui": ui,
        }

    state = "recommended" if best["due"] and best["phase_match"] and best["month_match"] else "possible"
    if not best["due"]:
        state = "blocked"

    metadata = _state_metadata(state)
    selected_ready = bool(selected_product_id and best["product_id"] == selected_product_id and state == "recommended")
    reason = _format_reasons(best["reasons"]) or (
        "Le produit sélectionné est prêt à être déclaré."
        if selected_ready
        else "Sélectionne ce produit pour préparer la déclaration."
        if state == "recommended"
        else "Le produit est disponible, mais certains critères restent moins favorables."
        if state == "possible"
        else best["blocked_reason"] or "La réapplication n'est pas encore possible."
    )
    why_now = reason
    if state == "blocked" and best["blocked_reason"]:
        why_now = best["blocked_reason"]
    elif state == "recommended" and best["months_label"]:
        why_now = f"{reason} · Période recommandée: {best['months_label']}."
    constraints, missing_requirements, _ = _constraints_for_candidate(
        candidate=best,
        state=state,
        block_reason=best["blocked_reason"],
        selected_ready=selected_ready,
    )
    product = _product_details(best)
    selection = _selection_details(
        selected_product_id=selected_product_id,
        selected_product_name=selected_product_name,
        selected_candidate=selected_candidate,
        ready=selected_ready,
    )
    ui = _ui_for_state(
        state=state,
        metadata=metadata,
        candidate=best,
        selected_details=selection,
        selected_ready=selected_ready,
        block_reason=best["blocked_reason"],
        reason=reason,
        why_now=why_now,
        today=today,
    )
    recommended_action = (
        "declare_intervention"
        if selected_ready and state == "recommended"
        else "select_product"
        if state in {"recommended", "possible"}
        else "wait"
        if state == "blocked"
        else "add_product"
    )
    return {
        "schema_version": 3,
        "status": state,
        "recommended_action": recommended_action,
        "priority": _priority_from_state(state, int(best["score"])),
        "score": int(best["score"]),
        "reason": reason,
        "why_now": why_now,
        "reasons": best["reasons"],
        "constraints": constraints,
        "missing_requirements": missing_requirements,
        "month_match": bool(best["month_match"]),
        "ready_to_declare": bool(selected_ready and state == "recommended"),
        "selected_product_ready": bool(selected_ready),
        "product": product,
        "selection": selection,
        "context": {
            "catalogue_count": len(catalogue_products),
            "eligible_count": len(eligible_candidates),
            "blocked_products_count": len(blocked_candidates),
            "current_month": today.month,
            "current_phase": phase_active,
            "current_sub_phase": sous_phase,
        },
        "ui": ui,
    }
