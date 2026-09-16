from __future__ import annotations

from typing import Any

from .const import block_reason_label


ASSISTANT_ACTION_VALUES = ("none", "arrosage", "traitement", "tonte")
ASSISTANT_MOMENT_VALUES = (
    "none",
    "maintenant",
    "attendre",
    "ce_matin",
    "demain_matin",
    "apres_pluie",
    "soir",
)
ASSISTANT_STATUS_VALUES = ("no_need", "ok", "blocked", "blocked_due_to_conditions", "action_required")

DEFAULT_ASSISTANT_DECISION: dict[str, Any] = {
    "action": "none",
    "moment": "none",
    "quantity_mm": 0.0,
    "status": "no_need",
    "reason": "conditions optimales",
}

# ⚠️ PAS DE TABLE DE LIBELLÉS ICI (0.88.0). L'assistant avait sa propre `_BLOCK_REASON_LABELS`,
# copie divergente de `const.BLOCK_REASON_DISPLAY_LABELS` : « Sol humide » contre « Sol détrempé »,
# « Fenêtre de tonte fermée » contre « Hors fenêtre de tonte », et quatre codes réellement émis
# (`semis_cycle_pending`, `semis_cycle_daily_target_reached`, `application_foliaire`,
# `temperature_trop_basse_germination`) affichés en snake_case brut dans le hero de la carte.
# Les libellés courts vivent dans `const` ; une garde AST (tests) interdit d'en recréer une copie.
# « Nuit » n'y est pas : c'est une phrase-consigne rédigée par la décision de tonte, pas un libellé.
_NUIT = "Nuit: attendre le lever du soleil."


def _libelle_motif(valeur: str) -> str:
    """Libellé court d'un CODE connu ; sinon le texte tel quel (l'assistant reçoit surtout des phrases)."""
    if str(valeur or "").strip().lower() == "mowing_night":
        return _NUIT
    return block_reason_label(valeur) or valeur

_STRONG_MOWING_BLOCK_CODES = {
    "phase_sursemis",
    "phase_traitement",
    "phase_hivernage",
    "machine_unavailable",
    "mowing_night",
    "post_application_active",
    "watering_in_progress",
    "watering_cooldown",
}

_SOFT_MOWING_BLOCK_CODES = {
    "mowing_spacing",
    "recent_watering",
    "watering_cooldown",
    "wet_grass",
    "soil_wet",
}


def _normalize_choice(value: object | None, allowed: tuple[str, ...], default: str) -> str:
    normalized = _clean_text(value)
    return normalized if normalized in allowed else default


def _clean_text(value: object | None) -> str:
    if value in (None, "", [], {}):
        return ""
    return str(value).strip()


def _to_float(value: object | None, default: float = 0.0) -> float:
    if value in (None, "", [], {}):
        return default
    try:
        # `float(object)` est refusé par le vérificateur de types, mais c'est exactement le but :
        # on accepte n'importe quelle entrée et on retombe sur le défaut si elle n'est pas
        # convertible. Le `str()` rend l'intention explicite sans changer le comportement —
        # `float("3.5")` comme `float(3.5)` donnent 3.5, et une valeur absurde lève toujours.
        return float(str(value).strip())
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
        "action": _normalize_choice(action, ASSISTANT_ACTION_VALUES, DEFAULT_ASSISTANT_DECISION["action"]),
        "moment": _normalize_choice(moment, ASSISTANT_MOMENT_VALUES, DEFAULT_ASSISTANT_DECISION["moment"]),
        "quantity_mm": round(float(quantity_mm), 1),
        "status": _normalize_choice(status, ASSISTANT_STATUS_VALUES, DEFAULT_ASSISTANT_DECISION["status"]),
        "reason": reason.strip() or DEFAULT_ASSISTANT_DECISION["reason"],
    }


def _irrigation_block_reason(snapshot: dict[str, Any]) -> str:
    return _clean_text(
        snapshot.get("watering_block_reason_label")
        or snapshot.get("watering_block_reason_code")
        or snapshot.get("sursemis_block_reason")
        or snapshot.get("block_reason")
    )


def _irrigation_reason(snapshot: dict[str, Any]) -> str:
    return _clean_text(
        snapshot.get("sursemis_reason")
        or snapshot.get("conseil_principal")
        or snapshot.get("action_recommandee")
    )


def _watering_cause(snapshot: dict[str, Any]) -> str:
    raw_cause = _clean_text(snapshot.get("watering_cause")).lower()
    if raw_cause in {"hydrique", "post_application"}:
        return raw_cause
    post_status = _clean_text(snapshot.get("application_post_watering_status")).lower()
    type_arrosage = _clean_text(snapshot.get("type_arrosage")).lower()
    if post_status in {"bloque", "en_attente", "autorise"}:
        return "post_application"
    if type_arrosage in {"application_technique", "application_technique_auto"}:
        return "post_application"
    return "hydrique"


def _resolve_irrigation(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    objective = _to_float(snapshot.get("objectif_mm", snapshot.get("mm_final", 0.0)))
    if objective <= 0.0 or not bool(snapshot.get("arrosage_recommande", False)):
        return None

    block_reason = _irrigation_block_reason(snapshot)
    watering_cause = _watering_cause(snapshot)
    moment = _clean_text(snapshot.get("fenetre_optimale")) or "maintenant"

    if block_reason:
        return _result(
            action="arrosage",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=_libelle_motif(block_reason),
        )

    reason = _irrigation_reason(snapshot)
    if not reason:
        reason = "Arrosage post-produit requis" if watering_cause == "post_application" else "Arrosage requis"

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
    post_status = _clean_text(snapshot.get("application_post_watering_status")).lower()
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
        if post_status == "termine":
            return None
        return _result(
            action="traitement",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason="Application en attente, arrosage post-application non encore autorisé.",
        )

    reason = _clean_text(
        snapshot.get("conseil_principal")
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
    # Cette couche répond à la faisabilité exécutable finale, pas seulement à l'autorisation agronomique.
    has_mowing_signal = any(
        snapshot.get(key) not in (None, "", [], {})
        for key in (
            "tonte_autorisee",
            "tonte_statut",
            "mowing_block_reason_code",
            "mowing_block_reason_label",
            "raison_blocage_code",
            "raison_blocage_tonte",
            "mower_operation_state",
            "mower_reason_code",
            "tondeuse_prete",
        )
    )
    if not has_mowing_signal:
        return None

    mowing_allowed = bool(snapshot.get("tonte_autorisee", False))
    mowing_block_reason = _clean_text(
        snapshot.get("mowing_block_reason_label")
        or snapshot.get("mowing_block_reason_code")
    )
    mowing_block_reason_code = _clean_text(snapshot.get("mowing_block_reason_code")).lower()
    public_block_reason_code = _clean_text(
        snapshot.get("raison_blocage_code")
    ).lower()
    phase = _clean_text(snapshot.get("phase_dominante") or snapshot.get("phase_active"))

    mower_operation_state = _clean_text(snapshot.get("mower_operation_state")).lower()
    mower_reason_code = _clean_text(snapshot.get("mower_reason_code")).lower()
    mower_operation_label = _clean_text(snapshot.get("mower_operation_label"))
    mower_reason_label = _clean_text(snapshot.get("mower_reason_label"))
    mower_is_mowing = mower_operation_state in {"mowing", "tonte", "tonte_en_cours"} or "tonte" in mower_operation_label.casefold()
    mower_is_returning = mower_operation_state in {"transit", "retour", "retour_station"} or mower_reason_code == "mower_returning" or "retour" in mower_operation_label.casefold()
    if mower_is_mowing:
        return _result(
            action="tonte",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=mower_reason_label or mower_operation_label or "Tondeuse en cours de tonte.",
        )
    if mower_is_returning:
        return _result(
            action="tonte",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=mower_reason_label or mower_operation_label or "Tondeuse en retour station.",
        )

    strong_phase_block = phase in {"Sursemis", "Traitement", "Hivernage"}
    strong_mowing_block = (
        strong_phase_block
        or mowing_block_reason_code in _STRONG_MOWING_BLOCK_CODES
        or public_block_reason_code in _STRONG_MOWING_BLOCK_CODES
    )
    soft_mowing_block = (
        not strong_mowing_block
        and (
            mowing_block_reason_code in _SOFT_MOWING_BLOCK_CODES
            or public_block_reason_code in _SOFT_MOWING_BLOCK_CODES
        )
    )

    if not mowing_allowed:
        if mowing_block_reason_code == "mowing_night" or "nocturne" in mowing_block_reason.casefold() or "nuit" in mowing_block_reason.casefold() or "lever du soleil" in mowing_block_reason.casefold():
            return _result(
                action="tonte",
                moment="attendre",
                quantity_mm=0.0,
                status="blocked",
                # La PHRASE qui a déclenché cette branche (« Nuit: attendre le lever du soleil. »),
                # pas le libellé du code : à 22 h, soleil encore levé, le code est
                # `mowing_window_blocked` et son libellé « Hors fenêtre de tonte » taisait la nuit.
                reason=_libelle_motif(mowing_block_reason) or _NUIT,
            )
        if soft_mowing_block or not strong_mowing_block:
            return None

    if strong_mowing_block and mowing_block_reason:
        return _result(
            action="tonte",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=_libelle_motif(mowing_block_reason),
        )

    mower_ready = snapshot.get("tondeuse_prete")
    mower_reason = _clean_text(snapshot.get("tondeuse_raison"))
    mower_status_label = _clean_text(snapshot.get("tondeuse_statut_libelle"))
    if snapshot.get("mower_coordination_enabled") is not False and mower_ready is False:
        reason_label = _libelle_motif(mower_reason)
        if not reason_label:
            reason_label = _libelle_motif(mower_status_label)
        return _result(
            action="tonte",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=reason_label or "Tondeuse non prête",
        )

    tonte_statut = _clean_text(snapshot.get("tonte_statut")).lower()
    block_reason = _clean_text(snapshot.get("raison_blocage_tonte"))
    actionable_statuses = {"autorisee", "autorisee_avec_precaution", "a_surveiller"}

    if soft_mowing_block:
        return None

    if strong_mowing_block:
        return _result(
            action="tonte",
            moment="attendre",
            quantity_mm=0.0,
            status="blocked",
            reason=block_reason or "Tonte bloquée",
        )

    if tonte_statut and tonte_statut not in actionable_statuses:
        return None

    return _result(
        action="tonte",
        moment="maintenant",
        quantity_mm=0.0,
        status="action_required",
        reason="Tonte autorisée",
    )


_STATUTS_POST_APPLICATION_ACTIFS = frozenset({"bloque", "en_attente", "autorise"})


def blocage_sans_objet(
    besoin_mm: Any,
    *,
    application_block_active: bool = False,
    application_post_watering_status: Any = "",
    application_post_watering_pending: bool = False,
) -> bool:
    """Un garde-fou armé qui n'a RIEN retenu : le sol ne demandait pas d'eau.

    ⚠️ LE DÉFAUT DU 11/09/2026. L'arrosage de l'aube venait de remplir la réserve à 12/12 ;
    la garde « un arrosage par jour » (`cooldown_24h`) est restée armée, comme prévu. Et
    QUATRE surfaces l'ont affiché comme un blocage :

        prochain_arrosage     « Bloqué » · « Attendre des conditions favorables »
        fenetre_optimale      « Arrosage bloqué: Déjà arrosé aujourd'hui »
        assistant             « attente_conditions » — le hero de la carte
        signal_irrigation     « Arrosage bloqué par conditions : Déjà arrosé aujourd'hui »

    avec `besoin_mm: 0` publié à côté. Rien n'était demandé, donc rien n'était retenu :
    annoncer un blocage laissait croire qu'on refusait de l'eau au gazon, juste après l'avoir
    arrosé.

    ⚠️ UNE SEULE DÉFINITION, ET C'EST TOUT LE CORRECTIF. La bonne règle existait déjà depuis la
    0.72.0 dans `_motif_de_blocage_effectif` (sensor.py), avec ce commentaire : « Deux copies
    finiraient par diverger, et l'une des deux mentirait sans qu'on sache laquelle. » Elles
    avaient divergé : quatre autres endroits recalculaient « un motif existe, donc bloqué ».
    Tous passent désormais par ici.

    ⚠️ ABSENCE ≠ ZÉRO : un besoin non publié ne désarme rien. Ne pas savoir n'autorise pas à
    conclure que tout va bien — c'est le côté sûr.

    ⚠️ JAMAIS POUR UN BLOCAGE POST-APPLICATION. Un produit épandu attend son eau pour être
    dissous : ce besoin-là est une ACTIVATION, pas un déficit hydrique, et `besoin_mm` peut
    très bien valoir 0 pendant qu'un engrais attend sur le feuillage. Ce blocage doit rester
    visible quoi qu'il arrive.

    ⚠️ AFFICHAGE SEULEMENT. Rien ici ne touche à `type_arrosage` ni à l'exécution : la garde
    continue de retenir exactement ce qu'elle retenait. Seul le récit change.
    """
    if not isinstance(besoin_mm, (int, float)) or isinstance(besoin_mm, bool):
        return False
    if float(besoin_mm) > 0.0:
        return False
    if application_block_active or application_post_watering_pending:
        return False
    statut = str(application_post_watering_status or "").strip().lower()
    if statut in _STATUTS_POST_APPLICATION_ACTIFS:
        return False
    return True


def _resolve_passive_state(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    # Les états passifs doivent retomber en no_need quand aucun exécutable n'est réellement attendu.
    block_reason = _clean_text(
        snapshot.get("sursemis_block_reason")
        or snapshot.get("block_reason")
    )
    post_status = _clean_text(snapshot.get("application_post_watering_status")).lower()
    type_arrosage = _clean_text(snapshot.get("type_arrosage")).lower()
    conseil = _clean_text(snapshot.get("conseil_principal"))
    if not block_reason and type_arrosage != "bloque":
        return None

    reason = conseil
    if not reason and block_reason:
        reason = _libelle_motif(block_reason)
    if not reason:
        reason = DEFAULT_ASSISTANT_DECISION["reason"]

    moment = _clean_text(snapshot.get("fenetre_optimale")) or "attendre"
    if moment == "none":
        moment = "attendre"

    objective_mm = _to_float(snapshot.get("objectif_mm", snapshot.get("mm_final", 0.0)))
    requested_mm = _to_float(snapshot.get("mm_requested", 0.0))
    application_block_active = bool(snapshot.get("application_block_active", False))
    application_requires = bool(snapshot.get("application_requires_watering_after", False))
    application_pending = bool(snapshot.get("application_post_watering_pending", False))
    blocked_due_to_conditions = bool(block_reason or type_arrosage == "bloque") and not blocage_sans_objet(
        snapshot.get("besoin_mm"),
        application_block_active=application_block_active,
        application_post_watering_status=post_status,
        application_post_watering_pending=application_pending,
    )
    passive_no_need = (
        objective_mm <= 0.0
        and requested_mm <= 0.0
        and not application_block_active
        and not application_pending
        and post_status in {"indisponible", "non_requis", "termine", "none", ""}
        and (not application_requires or post_status in {"non_requis", "termine"})
    )
    status = "blocked_due_to_conditions" if blocked_due_to_conditions else "no_need"
    if passive_no_need and not blocked_due_to_conditions:
        status = "no_need"

    if blocked_due_to_conditions:
        reason = _clean_text(
            snapshot.get("conseil_principal")
            or snapshot.get("action_recommandee")
        )
        if block_reason:
            reason = _libelle_motif(block_reason)
        if not reason:
            reason = "Arrosage bloqué par conditions."
    else:
        reason = _clean_text(
            snapshot.get("conseil_principal")
            or snapshot.get("action_recommandee")
        )
        if not reason:
            reason = DEFAULT_ASSISTANT_DECISION["reason"]

    return _result(
        action="none",
        moment=moment,
        quantity_mm=0.0,
        status=status,
        reason=reason,
    )


_ASSISTANT_RESOLVERS = (
    _resolve_irrigation,
    _resolve_critical_action,
    _resolve_mowing,
    _resolve_passive_state,
)


def build_assistant_decision(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    data = snapshot if isinstance(snapshot, dict) else {}
    for resolver in _ASSISTANT_RESOLVERS:
        resolved = resolver(data)
        if resolved is not None:
            return resolved

    return dict(DEFAULT_ASSISTANT_DECISION)
