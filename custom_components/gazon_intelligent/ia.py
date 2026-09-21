"""Conseil par l'IA de Home Assistant (0.93.0).

L'intégration ne parle à aucun fournisseur elle-même : elle passe par l'action native
`ai_task.generate_data`, donc par l'IA que la maison a déjà configurée (OpenAI, Google, Ollama…),
avec ses clés et sa facturation. L'entité choisie dans les options est utilisée ; sans choix, la
seule entité `ai_task.*` de la maison s'il n'y en a qu'une, sinon celle que Home Assistant préfère.

L'IA ne commande RIEN : elle reçoit l'état du gazon en texte et répond en texte. Un appel part
soit quand quelqu'un demande un conseil, soit pour personnaliser une notification si cette source
est choisie dans la page. Chaque appel peut avoir un coût chez le fournisseur configuré.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .const import CONF_ENTITE_IA

QUESTION_PAR_DEFAUT = "Faire le point sur le gazon aujourd'hui : ce qui va et ce qui demande de l'attention."
NOM_DE_LA_TACHE = "Conseil Gazon Intelligent"
DELAI_REPONSE_S = 90
DELAI_NOTIFICATION_S = 15
MESSAGE_NOTIFICATION_MAX_CARACTERES = 1000
# Au-delà, une question n'est plus une question : c'est un document collé par erreur.
QUESTION_MAX_CARACTERES = 1000


class IaIndisponible(Exception):
    """L'action `ai_task.generate_data` est absente ou a échoué ; le message se lit tel quel."""


def entite_configuree(entry: Any) -> str | None:
    for source in (getattr(entry, "options", None), getattr(entry, "data", None)):
        if isinstance(source, Mapping) and CONF_ENTITE_IA in source:
            texte = str(source.get(CONF_ENTITE_IA) or "").strip()
            return texte if texte.startswith("ai_task.") else None
    return None


def entite_unique(hass: Any) -> str | None:
    """La seule entité `ai_task.*` de la maison, s'il n'y en a qu'une.

    Sans choix dans les options, Home Assistant prend son entité préférée ; s'il n'en a pas,
    l'action échoue. Quand la maison n'a qu'une IA, c'est forcément elle : on la nomme.
    """
    try:
        ids = list(hass.states.async_entity_ids("ai_task"))
    except Exception:  # noqa: BLE001 - états illisibles : on laisse Home Assistant choisir
        return None
    return str(ids[0]) if len(ids) == 1 else None


def entite_effective(hass: Any, entry: Any) -> str | None:
    return entite_configuree(entry) or entite_unique(hass)


def consigne(question: str | None, lignes: Sequence[str], *, maintenant: datetime) -> str:
    """Le texte envoyé à l'IA : le rôle, les limites, l'état du gazon, puis la question."""
    demande = str(question or "").strip()[:QUESTION_MAX_CARACTERES] or QUESTION_PAR_DEFAUT
    etat = "\n".join(f"- {ligne}" for ligne in lignes) or "- (aucune donnée disponible)"
    return (
        "Tu conseilles le propriétaire d'une pelouse suivie par Gazon Intelligent, une intégration "
        "Home Assistant qui décide seule de l'arrosage et de la tonte.\n"
        "Règles :\n"
        "- Réponds en français, simplement, en 6 phrases au plus : le lecteur n'est pas agronome.\n"
        "- Utilise une formulation neutre et valable pour n'importe quel utilisateur, sans nom, "
        "tutoiement ni détail personnel non présent dans l'état.\n"
        "- Appuie-toi uniquement sur l'état ci-dessous. S'il manque une information, dis-le "
        "au lieu de l'inventer.\n"
        "- Tu ne commandes rien : ne dis jamais qu'un arrosage ou une tonte a été lancé ou arrêté.\n"
        "- Les doses et les horaires d'arrosage sont calculés par l'intégration : si tu suggères "
        "d'en changer, présente-le comme une idée à vérifier, jamais comme une consigne.\n"
        f"\nÉtat du gazon le {maintenant.strftime('%d/%m/%Y à %H:%M')} :\n{etat}\n"
        f"\nQuestion : {demande}"
    )


def consigne_notification(
    titre: str,
    message: str,
    niveau: str,
    lignes: Sequence[str],
    *,
    maintenant: datetime,
) -> str:
    """Demande une reformulation courte sans laisser l'IA redéfinir les faits ni l'urgence."""
    contexte = "\n".join(f"- {ligne}" for ligne in lignes) or "- aucun contexte supplémentaire"
    return (
        "Tu rédiges une notification claire en français pour la personne qui suit le gazon.\n"
        "Réponds uniquement par le message final, sans titre, sans markdown, en 3 phrases au plus.\n"
        "Utilise une formulation neutre, sans nom, tutoiement ni détail personnel non fourni.\n"
        "Conserve exactement les faits, nombres, horaires, noms d'appareils et action demandée. "
        "N'invente rien, ne minimise jamais une urgence et ne prétends commander aucun appareil.\n"
        f"Niveau fixé par l'intégration : {niveau}.\n"
        f"Titre fixé par l'intégration : {titre}\n"
        f"Message factuel : {message}\n"
        f"Contexte du {maintenant.strftime('%d/%m/%Y à %H:%M')} :\n{contexte}"
    )


def texte_de_la_reponse(reponse: Any) -> str:
    """Le texte de `ai_task.generate_data` : `{"data": "…", "conversation_id": …}`."""
    donnees = reponse.get("data") if isinstance(reponse, Mapping) else reponse
    if isinstance(donnees, str):
        return donnees.strip()
    if isinstance(donnees, Mapping):
        for cle in ("text", "reponse", "answer"):
            valeur = donnees.get(cle)
            if isinstance(valeur, str) and valeur.strip():
                return valeur.strip()
    return ""


async def async_demander(
    hass: Any,
    instructions: str,
    *,
    entite: str | None,
    delai_s: float | None = None,
) -> str:
    """Appelle l'IA de la maison et rend sa réponse, ou lève `IaIndisponible` avec une phrase claire."""
    services = getattr(hass, "services", None)
    if services is None or not services.has_service("ai_task", "generate_data"):
        raise IaIndisponible(
            "L'IA de Home Assistant n'est pas disponible : ajoute une intégration qui fournit une "
            "tâche IA (OpenAI, Google Gemini, Ollama…)."
        )
    donnees: dict[str, Any] = {"task_name": NOM_DE_LA_TACHE, "instructions": instructions}
    if entite:
        donnees["entity_id"] = entite
    try:
        delai = DELAI_REPONSE_S if delai_s is None else delai_s
        async with asyncio.timeout(delai):
            reponse = await services.async_call(
                "ai_task",
                "generate_data",
                donnees,
                blocking=True,
                return_response=True,
            )
    except TimeoutError as err:
        raise IaIndisponible(f"L'IA n'a pas répondu en {delai:g} secondes.") from err
    except Exception as err:  # noqa: BLE001 - l'erreur du fournisseur est rendue en clair
        raise IaIndisponible(f"L'IA a refusé la demande : {err}") from err
    texte = texte_de_la_reponse(reponse)
    if not texte:
        raise IaIndisponible("L'IA a répondu sans texte.")
    return texte
