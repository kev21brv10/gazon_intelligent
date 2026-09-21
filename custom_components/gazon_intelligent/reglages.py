"""Registre des réglages ajustables depuis la page « Réglages du gazon ».

Source UNIQUE de ce que la page montre : pour chaque réglage, une question simple, une phrase
d'aide, la valeur par défaut, les bornes, le pas, l'unité et la source. Les valeurs par défaut
sont celles que le moteur utilise AUJOURD'HUI : `tests/test_reglages.py` les compare une à une
aux constantes du code. Tant que personne n'y touche, rien ne change.

Module PUR : aucune dépendance à Home Assistant. Il est servi tel quel à la page (commande
WebSocket) et exporté en JSON pour l'aperçu local (`dev/panel/exporter_registre.py`).

Conventions de valeurs :
    · « heure » : minutes depuis minuit (600 = 10:00) ;
    · « duree » : minutes ;
    · « jour » : numéro du jour depuis le semis (0 = le jour du semis), bornes incluses ;
    · « table_mois » : douze valeurs, de janvier à décembre ;
    · « nombre » : la valeur telle quelle, dans l'unité indiquée.

Les CHOIX (type de sol) sont à part : une option parmi quelques-unes, rangée là où l'intégration
la lit déjà (les options de l'entrée), jamais recopiée dans les réglages.

BRANCHEMENT (0.92.0). Chaque instance garde ses réglages dans ses options (`entry.options
["reglages"]`), et seulement ceux qui diffèrent du conseil. Le coordinateur les nettoie
(`nettoyer`), les confie au `GazonBrain`, qui les pose sur le `DecisionContext` ; chaque
fonction du moteur les lit avec `lire(reglages, cle, CONSTANTE)`. Sans réglage, la constante du
moteur s'applique : c'est elle, et non le défaut recopié ici, qui fait foi à l'exécution.
`tests/test_reglages_branches.py` change chaque réglage et vérifie que la DÉCISION change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

GENRES = ("nombre", "heure", "duree", "jour", "table_mois", "interrupteur")


@dataclass(frozen=True)
class Groupe:
    cle: str
    titre: str
    phrase: str
    icone: str


@dataclass(frozen=True)
class Reglage:
    cle: str
    groupe: str
    titre: str
    aide: str
    genre: str
    defaut: bool | float | tuple[float, ...]
    minimum: float
    maximum: float
    pas: float
    unite: str = ""
    source: str = ""
    avertissement: str = ""


@dataclass(frozen=True)
class Contrainte:
    """`gauche` doit rester strictement inférieur (ou inférieur ou égal) à `droite`."""

    gauche: str
    droite: str
    message: str
    stricte: bool = True


@dataclass(frozen=True)
class Option:
    valeur: str
    titre: str
    aide: str
    reserve_mm: float = 0.0
    reserve_max_mm: float = 0.0


@dataclass(frozen=True)
class Choix:
    cle: str
    groupe: str
    titre: str
    aide: str
    defaut: str
    options: tuple[Option, ...]
    source: str = ""


GROUPES: tuple[Groupe, ...] = (
    Groupe("tonte", "Tonte", "Quand et comment la tondeuse a le droit de travailler.", "mdi:robot-mower"),
    Groupe("arrosage", "Arrosage", "L'arrosage de tous les jours, avant le lever du soleil.", "mdi:sprinkler-variant"),
    Groupe("graines", "Graines", "L'arrosage des graines, après un semis ou un sursemis.", "mdi:seed-outline"),
    Groupe("sursemis", "Sursemis", "La tonte après un semis dans un gazon qui pousse déjà.", "mdi:sprout"),
    Groupe("semis", "Semis", "La tonte après un semis sur terrain nu.", "mdi:grass"),
    Groupe("modes", "Modes", "La durée de chaque mode et les fiches produit qui pilotent son comportement.", "mdi:swap-horizontal"),
    Groupe("installation", "Installation", "Les arroseurs, la tondeuse, les interrupteurs et les alertes.", "mdi:tune-variant"),
)

_H = 60  # une heure, en minutes

REGLAGES: tuple[Reglage, ...] = (
    # ── Tonte ────────────────────────────────────────────────────────────────────────────
    Reglage(
        "tonte_fenetre_ideale_debut", "tonte",
        "Dès quelle heure la tondeuse peut-elle tondre ?",
        "Avant, l'herbe est encore mouillée par la rosée. Une herbe mouillée se coupe mal.",
        "heure", 10 * _H, 6 * _H, 14 * _H, 15,
        source="decision_mowing._MOWING_WINDOW_IDEAL_START",
    ),
    Reglage(
        "tonte_fenetre_ideale_fin", "tonte",
        "Jusqu'à quelle heure est-ce le meilleur moment ?",
        "Ensuite il fait souvent trop chaud : la tondeuse attend le soir.",
        "heure", 14 * _H, 10 * _H, 18 * _H, 15,
        source="decision_mowing._MOWING_WINDOW_IDEAL_END",
    ),
    Reglage(
        "tonte_soir_avant_coucher", "tonte",
        "Le soir, combien de temps avant le coucher du soleil peut-elle repartir ?",
        "Quand le soleil baisse, il fait moins chaud et l'herbe supporte mieux la coupe.",
        "duree", 300, 60, 480, 15,
        source="decision_mowing._MOWING_EVENING_START_BEFORE_SUNSET_MIN",
    ),
    Reglage(
        "tonte_soir_apres_coucher", "tonte",
        "Et jusqu'à combien de temps après le coucher ?",
        "Ensuite il fait nuit : la tondeuse rentre à sa base.",
        "duree", 30, 0, 90, 5,
        source="decision_mowing._MOWING_EVENING_END_AFTER_SUNSET_MIN (fin du crépuscule civil)",
    ),
    Reglage(
        "tonte_vent_a_eviter", "tonte",
        "À partir de quel vent vaut-il mieux attendre ?",
        "Avec du vent, l'herbe coupée s'envole et la coupe est moins nette.",
        "nombre", 20, 10, 40, 1, "km/h",
        source="decision_mowing._MOWING_WINDOW_DISCOURAGED_WIND",
    ),
    Reglage(
        "tonte_vent_bloque", "tonte",
        "Au-delà de quel vent la tonte est-elle interdite ?",
        "Trop de vent : la tondeuse ne sort pas du tout.",
        "nombre", 40, 20, 60, 1, "km/h",
        source="decision_mowing._MOWING_WINDOW_BLOCK_WIND",
        avertissement="Réglage sensible : une valeur trop haute peut autoriser la tondeuse avec un vent dangereux ou une coupe très irrégulière.",
    ),
    Reglage(
        "tonte_temperature_a_eviter", "tonte",
        "À partir de quelle chaleur vaut-il mieux attendre ?",
        "Couper une herbe qui a chaud la fatigue.",
        "nombre", 25, 20, 35, 1, "°C",
        source="decision_mowing._MOWING_WINDOW_DISCOURAGED_TEMP_MIN",
    ),
    Reglage(
        "tonte_temperature_bloquee", "tonte",
        "Au-delà de quelle chaleur la tonte est-elle interdite ?",
        "Par forte chaleur, couper abîme le gazon.",
        "nombre", 30, 25, 40, 1, "°C",
        source="decision_mowing._MOWING_WINDOW_BLOCK_TEMP_MIN",
        avertissement="Réglage sensible : relever cette limite peut faire tondre un gazon en stress thermique et accentuer son dessèchement.",
    ),
    Reglage(
        "tonte_humidite_bloquee", "tonte",
        "À partir de quelle humidité de l'air la tonte est-elle interdite ?",
        "Un air très humide veut dire une herbe mouillée : la tondeuse attend.",
        "nombre", 90, 80, 100, 1, "%",
        source="decision_mowing._MOWING_WINDOW_BLOCK_HUMIDITY",
        avertissement="Réglage sensible : relever cette limite peut autoriser une coupe sur herbe mouillée, avec bourrage et risque de maladies.",
    ),
    Reglage(
        "tonte_ecart_min_jours", "tonte",
        "Combien de jours au minimum entre deux tontes ?",
        "Le gazon a besoin d'un peu de repos après une coupe.",
        "nombre", 2, 1, 7, 1, "jours",
        source="decision_mowing._mowing_spacing_min_days (régime normal)",
    ),
    Reglage(
        "tonte_max_par_jour", "tonte",
        "Combien de tontes au maximum par jour ?",
        "Une tonte, c'est un tour complet du jardin. Les retours pour recharger ne comptent pas.",
        "nombre", 2, 1, 4, 1, "tontes",
        source="decision_mowing._mowing_daily_session_policy (régime normal)",
        avertissement="Réglage sensible : plusieurs tontes complètes le même jour augmentent le tassement, l'usure et le stress du gazon.",
    ),
    Reglage(
        "tonte_hauteur_par_mois", "tonte",
        "Quelle hauteur de gazon selon le mois ?",
        "Plus haut en été pour garder la fraîcheur, un peu plus haut au printemps pour qu'il s'épaississe.",
        "table_mois", (4.0, 4.0, 4.5, 4.0, 4.0, 4.5, 5.0, 5.0, 4.0, 4.0, 4.0, 4.0), 3.0, 8.0, 0.5, "cm",
        source="decision_mowing._HAUTEUR_BASE_PAR_MOIS",
    ),
    Reglage(
        "tonte_frequence_par_mois", "tonte",
        "Combien de tontes par semaine, selon le mois ?",
        "C'est le rythme visé. Sans tonte depuis une fois et demie l'intervalle, la tonte est dite en retard. "
        "Le semis et le sursemis ont leur propre rythme.",
        "table_mois", (0.0, 0.0, 2.5, 2.5, 5.0, 5.0, 3.0, 3.0, 5.0, 5.0, 1.5, 0.0), 0.0, 7.0, 0.5, "par semaine",
        source="decision_mowing._MOWING_FREQUENCY_BY_MONTH",
    ),
    # ── Arrosage du matin ────────────────────────────────────────────────────────────────
    Reglage(
        "arrosage_ouverture", "arrosage",
        "Dès quelle heure l'arrosage peut-il commencer ?",
        "La nuit, l'eau ne s'évapore presque pas : c'est le bon moment pour arroser.",
        "heure", 225, 2 * _H, 6 * _H, 15,
        source="guidance.OPTIMAL_MORNING_START_HOUR",
    ),
    Reglage(
        "arrosage_fin_optimale", "arrosage",
        "Jusqu'à quelle heure est-ce le meilleur moment pour arroser ?",
        "Après, le soleil commence à chauffer.",
        "heure", 8 * _H, 6 * _H, 10 * _H, 15,
        source="guidance.OPTIMAL_MORNING_END_HOUR",
    ),
    Reglage(
        "arrosage_fin_acceptable", "arrosage",
        "Et au plus tard ?",
        "Au-delà, trop d'eau s'évapore : l'arrosage attend le lendemain.",
        "heure", 10 * _H, 8 * _H, 12 * _H, 15,
        source="guidance.ACCEPTABLE_MORNING_END_HOUR",
    ),
    Reglage(
        "arrosage_marge_avant_lever", "arrosage",
        "Combien de temps avant le lever du soleil l'arrosage doit-il être fini ?",
        "L'herbe sèche vite au soleil. Les maladies aiment l'herbe qui reste mouillée longtemps.",
        "duree", 15, 0, 60, 5,
        source="coordinator_constants.WATERING_SUNRISE_MARGIN_MINUTES",
    ),
    Reglage(
        "arrosage_delai_relance", "arrosage",
        "Combien d'heures attendre avant un nouvel arrosage automatique ?",
        "Ça évite d'arroser deux fois de suite par erreur.",
        "nombre", 6, 1, 24, 1, "h",
        source="coordinator_constants.AUTO_IRRIGATION_RELAUNCH_COOLDOWN",
        avertissement="Réglage sensible : un délai trop court peut permettre deux arrosages automatiques très rapprochés.",
    ),
    Reglage(
        "arrosage_sensibilite_pluie", "arrosage",
        "Comment tenir compte de la pluie annoncée ?",
        "Prudente protège davantage le gazon, Équilibrée garde le comportement conseillé et Économe reporte plus tôt pour économiser l'eau.",
        "nombre", 1.0, 0.75, 1.25, 0.25, "×",
        source="guidance._rain_signals (multiplicateur des seuils de pluie prévue)",
        avertissement="Réglage sensible : le profil Économe se fie davantage aux prévisions ; si la pluie annoncée ne tombe pas, le gazon peut attendre plus longtemps.",
    ),
    # Une zone ombragée évapore moins qu'une zone en plein soleil. La réduction reste explicite
    # et indépendante par vanne : 0 % conserve exactement le plan historique.
    *(
        Reglage(
            f"arrosage_reduction_ombre_zone_{numero}", "arrosage",
            f"De combien réduire l'arrosage de la zone {numero} si elle est ombragée ?",
            "La durée de cette zone sera réduite de ce pourcentage, sans changer les autres zones.",
            "nombre", 0.0, 0.0, 50.0, 5.0, "%",
            source="watering_plan.build_watering_plan (réduction propre à la zone)",
            avertissement="Réglage sensible : une réduction trop forte peut laisser cette zone trop sèche, surtout si l'ombre ne dure qu'une partie de la journée.",
        )
        for numero in range(1, 6)
    ),
    # Découpage d'une grosse dose (mode Normal). Valeurs du 29/07/2026, tirées du régime manuel
    # éprouvé de Kévin : 8,8 à 10 mm d'un seul passage, sans ruissellement.
    Reglage(
        "arrosage_decoupage_seuil", "arrosage",
        "Au-delà de combien d'eau l'arrosage se fait-il en deux fois ?",
        "Trop d'eau d'un coup coule en surface au lieu d'entrer dans la terre. En mode Normal.",
        # Bornes : la plus petite dose du mode Normal (5 mm), et sa plus grosse séance (15 mm),
        # au-delà de laquelle le moteur coupe déjà en passages de 15 mm au plus.
        "nombre", 10.0, 5.0, 15.0, 0.5, "mm",
        source="guidance.FRACTIONNEMENT_NORMAL_SEUIL_MM",
        avertissement="Réglage sensible : un seuil trop haut augmente le risque de ruissellement sur un sol qui absorbe lentement.",
    ),
    Reglage(
        "arrosage_pause_dose_min", "arrosage",
        "À partir de combien d'eau faire une pause entre les deux fois ?",
        "En dessous, les deux passages s'enchaînent : la pause ne sert qu'à laisser l'eau s'enfoncer.",
        "nombre", 10.0, 0.0, 20.0, 0.5, "mm",
        source="guidance.PAUSE_LONGUE_MIN_DOSE_MM",
    ),
    Reglage(
        "arrosage_pause_duree", "arrosage",
        "Combien de temps dure cette pause ?",
        "Le temps que l'eau du premier passage rentre dans la terre.",
        "duree", 25, 5, 90, 5,
        source="guidance.PAUSE_ENTRE_PASSAGES_MIN",
        avertissement="Réglage sensible : une pause trop courte peut empêcher la première dose de pénétrer avant la suivante.",
    ),
    Reglage(
        "rafraichissement_temperature", "arrosage",
        "Le soir, à partir de quelle chaleur rafraîchir le gazon ?",
        "Un petit arrosage le soir aide le gazon à passer les grosses chaleurs.",
        "nombre", 32, 28, 40, 1, "°C",
        source="guidance.EVENING_COOLING_MIN_TEMP",
        avertissement="Réglage sensible : une limite trop basse multiplie les arrosages du soir et peut maintenir le feuillage humide inutilement.",
    ),
    Reglage(
        "rafraichissement_dose", "arrosage",
        "Combien d'eau pour ce rafraîchissement ?",
        "Juste de quoi refroidir le gazon, pas de quoi le noyer.",
        "nombre", 3.0, 1.0, 6.0, 0.5, "mm",
        source="guidance.EVENING_COOLING_MM",
        avertissement="Réglage sensible : une dose trop forte le soir gaspille de l'eau et augmente le temps passé avec un feuillage humide.",
    ),
    # ── Graines (semis et sursemis) ──────────────────────────────────────────────────────
    Reglage(
        "graines_duree", "graines",
        "Combien de jours dure le suivi des graines ?",
        "Pendant tout ce temps, l'arrosage et la tonte s'adaptent aux jeunes pousses.",
        "nombre", 45, 30, 90, 1, "jours",
        source="phases.PHASE_DURATIONS_DAYS",
    ),
    Reglage(
        "graines_fin_germination", "graines",
        "Jusqu'à quel jour les graines germent-elles ?",
        "Pour sortir de terre, les graines ont besoin d'une surface toujours humide.",
        "jour", 10, 5, 21, 1,
        source="phases.SUBPHASE_RULES (Germination)",
    ),
    Reglage(
        "graines_fin_enracinement", "graines",
        "Jusqu'à quel jour les racines s'installent-elles ?",
        "On arrose moins souvent mais plus fort, pour que les racines descendent.",
        "jour", 24, 14, 40, 1,
        source="phases.SUBPHASE_RULES (Enracinement)",
    ),
    Reglage(
        "graines_fin_reprise", "graines",
        "Jusqu'à quel jour dure la reprise ?",
        "Le jeune gazon se renforce. Ensuite, il se stabilise jusqu'à la fin du suivi.",
        "jour", 34, 20, 60, 1,
        source="phases.SUBPHASE_RULES (Reprise)",
    ),
    Reglage(
        "graines_germination_dose", "graines",
        "Pendant la germination, combien d'eau à chaque arrosage ?",
        "Un tout petit peu, mais souvent : juste de quoi mouiller la surface.",
        "nombre", 1.5, 0.5, 3.0, 0.1, "mm",
        source="watering_policy.SEMIS_STAGE_PROGRAMS['germination']",
        avertissement="Réglage sensible : trop peu assèche la surface ; trop d'eau peut déplacer les graines ou favoriser la pourriture.",
    ),
    Reglage(
        "graines_germination_cycles", "graines",
        "Combien d'arrosages par jour en météo normale pendant la germination ?",
        "C'est la base : la météo peut retirer ou ajouter un cycle pour garder la surface humide sans la détremper.",
        "nombre", 3, 1, 4, 1, "par jour",
        source="watering_policy.SEMIS_STAGE_PROGRAMS['germination']",
        avertissement="Réglage sensible : la météo adapte déjà ce nombre. Une base trop haute peut détremper le lit de semences.",
    ),
    Reglage(
        "graines_enracinement_dose", "graines",
        "Pendant l'enracinement, combien d'eau à chaque arrosage ?",
        "Plus d'eau d'un coup, pour que l'eau descende vers les racines.",
        "nombre", 3.0, 1.0, 6.0, 0.5, "mm",
        source="watering_policy.SEMIS_STAGE_PROGRAMS['enracinement']",
    ),
    # Deux au plus pour l'enracinement et la reprise : leurs programmes n'ont que deux créneaux
    # (10:00 puis 14:00 ou 15:00), et un troisième, 4 h 30 plus tard, tomberait après la fin de
    # la fenêtre des graines. Il ne partirait jamais : le réglage mentirait.
    Reglage(
        "graines_enracinement_cycles", "graines",
        "Combien d'arrosages par jour en météo normale pendant l'enracinement ?",
        "C'est la base : la météo l'ajuste, tandis que les racines apprennent à chercher l'eau.",
        "nombre", 1, 1, 2, 1, "par jour",
        source="watering_policy.SEMIS_STAGE_PROGRAMS['enracinement']",
    ),
    Reglage(
        "graines_reprise_dose", "graines",
        "Ensuite, combien d'eau à chaque arrosage ?",
        "Pour la reprise et la stabilisation, jusqu'à la fin du suivi.",
        "nombre", 2.5, 1.0, 6.0, 0.5, "mm",
        source="watering_policy.SEMIS_STAGE_PROGRAMS['levee']",
    ),
    Reglage(
        "graines_reprise_cycles", "graines",
        "Et combien d'arrosages par jour en météo normale ?",
        "C'est la base : la météo l'ajuste et le jeune gazon tient progressivement mieux sans eau.",
        "nombre", 1, 1, 2, 1, "par jour",
        source="watering_policy.SEMIS_STAGE_PROGRAMS['levee']",
    ),
    Reglage(
        "graines_fenetre_debut", "graines",
        "Dès quelle heure arroser les graines ?",
        "Les graines s'arrosent en journée, quand la surface commence à sécher.",
        "heure", 10 * _H, 8 * _H, 14 * _H, 15,
        source="guidance.SEMIS_WINDOW_START_HOUR",
    ),
    Reglage(
        "graines_fenetre_fin", "graines",
        "Jusqu'à quelle heure ?",
        "Jamais le soir : des jeunes pousses mouillées toute la nuit risquent de pourrir.",
        "heure", 17 * _H, 12 * _H, 19 * _H, 15,
        source="guidance.SEMIS_WINDOW_END_HOUR",
        avertissement="Réglage sensible : finir trop tard laisse les jeunes pousses humides pendant la nuit et augmente le risque de maladies.",
    ),
    Reglage(
        "graines_vent_max", "graines",
        "À partir de quel vent ne pas arroser les graines ?",
        "Le vent emporte l'eau : elle tombe à côté des graines.",
        "nombre", 15, 5, 30, 1, "km/h",
        source="guidance.compute_action_guidance (branche semis)",
    ),
    Reglage(
        "graines_temperature_min", "graines",
        "Au-dessus de quelle température peut-on arroser les graines ?",
        "Quand il fait trop froid, les graines ne poussent pas : inutile de les mouiller.",
        "nombre", 8, 2, 15, 1, "°C",
        source="guidance.SURSEMIS_POLICY_CONFIGS (temperature_min)",
    ),
    Reglage(
        "graines_alerte_retard", "graines",
        "Au bout de combien de temps prévenir quand un arrosage des graines ne part pas ?",
        "Un arrosage prévu part d'habitude dans les deux minutes. Un délai plus court prévient plus tôt, "
        "parfois pour un simple retard.",
        "duree", 20, 10, 120, 5,
        source="notifications.DELAI_RETARD_GRAINES (alerte, pas une décision)",
    ),
    # ── Sursemis : tonte sur gazon en place ──────────────────────────────────────────────
    Reglage(
        "sursemis_levee", "sursemis",
        "Combien de jours la tondeuse attend-elle après le semis ?",
        "Le temps que les graines s'accrochent au sol. Sinon, les roues les déplacent.",
        "nombre", 7, 0, 21, 1, "jours",
        source="phases.SURSEMIS_LEVEE_JOURS (UC IPM : ray-grass 5 à 10 j)",
    ),
    Reglage(
        "sursemis_pousse_plantules", "sursemis",
        "De combien les jeunes pousses grandissent-elles chaque jour ?",
        "C'est une estimation : elle sert à prévoir le jour de leur première coupe.",
        "nombre", 0.4, 0.1, 1.0, 0.05, "cm/jour",
        source="phases.PLANTULES_POUSSE_CM_JOUR (estimation)",
    ),
    Reglage(
        "sursemis_lame", "sursemis",
        "À quelle hauteur couper pendant le sursemis ?",
        "Couper court laisse la lumière arriver jusqu'aux jeunes pousses.",
        "nombre", 4.0, 3.0, 6.0, 0.5, "cm",
        source="phases.SURSEMIS_HAUTEUR_COUPE_CM (Purdue : 1,5 pouce)",
    ),
    Reglage(
        "sursemis_lame_finale", "sursemis",
        "À quelle hauteur remonter la lame ensuite ?",
        "Une fois les jeunes pousses coupées, on laisse le gazon un peu plus haut.",
        "nombre", 4.5, 3.0, 8.0, 0.5, "cm",
        source="decision_mowing.SURSEMIS_HAUTEUR_FINALE_CM (arbitrage produit)",
    ),
    Reglage(
        "sursemis_coupes_avant_remontee", "sursemis",
        "Combien de coupes des jeunes pousses avant de remonter la lame ?",
        "Chaque coupe les aide à s'épaissir.",
        "nombre", 2, 1, 5, 1, "coupes",
        source="decision_mowing.SURSEMIS_COUPES_AVANT_REMONTEE (Purdue)",
    ),
    Reglage(
        "sursemis_ecart_tontes", "sursemis",
        "Combien de jours au minimum entre deux tontes ?",
        "Moins de passages, c'est moins de piétinement sur les jeunes pousses.",
        "nombre", 5, 2, 14, 1, "jours",
        source="decision_mowing.SURSEMIS_ESPACEMENT_TONTE_JOURS",
    ),
    Reglage(
        "sursemis_premiere_coupe", "sursemis",
        "À quelle taille couper les jeunes pousses la première fois ?",
        "En nombre de fois la hauteur de coupe. Par exemple 1,5 × 4 cm = 6 cm.",
        "nombre", 1.5, 1.2, 2.0, 0.1, "×",
        source="phases.PLANTULES_RATIO_PREMIERE_COUPE (UC IPM)",
    ),
    # ── Semis : tonte sur terrain nu ─────────────────────────────────────────────────────
    Reglage(
        "semis_hauteur_germination", "semis",
        "Pendant la germination, quelle hauteur conseiller ?",
        "Sur un terrain nu, on ne tond pas encore : l'herbe doit d'abord s'installer.",
        "nombre", 7.5, 4.0, 10.0, 0.5, "cm",
        source="decision_mowing._SEMIS_PLANCHERS_CM['Germination']",
    ),
    Reglage(
        "semis_hauteur_enracinement", "semis",
        "Pendant l'enracinement, quelle hauteur conseiller ?",
        "On ne tond toujours pas : les racines s'installent.",
        "nombre", 7.0, 4.0, 10.0, 0.5, "cm",
        source="decision_mowing._SEMIS_PLANCHERS_CM['Enracinement']",
    ),
    Reglage(
        "semis_hauteur_reprise", "semis",
        "Pour les premières coupes, à quelle hauteur ?",
        "Les premières coupes se font haut, pour ne pas arracher le jeune gazon.",
        "nombre", 6.5, 4.0, 10.0, 0.5, "cm",
        source="decision_mowing._SEMIS_PLANCHERS_CM['Reprise']",
    ),
    Reglage(
        "semis_hauteur_stabilisation", "semis",
        "Ensuite, à quelle hauteur au minimum ?",
        "Le gazon se stabilise : on descend doucement vers la hauteur du mois.",
        "nombre", 5.0, 3.0, 10.0, 0.5, "cm",
        source="decision_mowing._SEMIS_PLANCHERS_CM['Stabilisation']",
    ),
    # ── Durée des autres modes ───────────────────────────────────────────────────────────
    # Le jour de la déclaration compte : 2 jours = ce jour-là et le lendemain. Pendant ce temps,
    # l'arrosage suit le profil du mode (guidance._profile_for_*), plus celui du mode Normal.
    Reglage(
        "mode_traitement_duree", "modes",
        "Combien de jours dure le mode Traitement ?",
        "Le jour du traitement compte. Pendant ce temps, la tondeuse attend et l'arrosage suit les règles du traitement.",
        "nombre", 2, 1, 14, 1, "jours",
        source="phases.PHASE_DURATIONS_DAYS",
    ),
    Reglage(
        "mode_fertilisation_duree", "modes",
        "Combien de jours dure le mode Fertilisation ?",
        "Le jour de l'engrais compte. Pendant ce temps, l'arrosage suit les règles de l'engrais.",
        "nombre", 2, 1, 14, 1, "jours",
        source="phases.PHASE_DURATIONS_DAYS",
    ),
    Reglage(
        "mode_biostimulant_duree", "modes",
        "Combien de jours dure le mode Biostimulant ?",
        "Le jour de l'application compte. Pendant ce temps, l'arrosage suit les règles du biostimulant.",
        "nombre", 1, 1, 14, 1, "jours",
        source="phases.PHASE_DURATIONS_DAYS",
    ),
    Reglage(
        "mode_agent_mouillant_duree", "modes",
        "Combien de jours dure le mode Agent mouillant ?",
        "Le jour de l'application compte. Pendant ce temps, l'arrosage suit les règles de l'agent mouillant.",
        "nombre", 1, 1, 14, 1, "jours",
        source="phases.PHASE_DURATIONS_DAYS",
    ),
    Reglage(
        "mode_scarification_duree", "modes",
        "Combien de jours dure le mode Scarification ?",
        "Le jour de la scarification compte. Pendant ce temps, la tondeuse sort une fois par jour au plus "
        "et l'arrosage suit les règles de la scarification.",
        "nombre", 7, 1, 21, 1, "jours",
        source="phases.PHASE_DURATIONS_DAYS",
    ),
    Reglage(
        "mode_scarification_temperature_min", "modes",
        "À partir de quelle température arroser après une scarification ?",
        "En dessous, la reprise du gazon est trop lente : l'arrosage d'accompagnement attend.",
        "nombre", 12.0, 5.0, 20.0, 0.5, "°C",
        source="watering_policy.WATERING_POLICIES['scarification'].conditions['temperature_min_c']",
        avertissement="Réglage sensible : sous 12 °C la reprise est lente ; abaisser cette limite peut arroser sans bénéfice réel.",
    ),
    # ── Pilotage matériel de la tondeuse ───────────────────────────────────────────────
    Reglage(
        "tondeuse_pilotage_batterie_min", "installation",
        "Quelle batterie minimale avant un départ automatique ?",
        "Le départ attend que la batterie atteigne ce niveau. Une valeur élevée évite un cycle incomplet.",
        "nombre", 100, 50, 100, 5, "%",
        source="mower_control_constants.DEFAULT_MOWER_CONTROL_MIN_BATTERY",
        avertissement="Réglage sensible : une batterie trop basse peut interrompre la tonte avant la fin du passage.",
    ),
    Reglage(
        "tondeuse_pilotage_delai_commandes", "installation",
        "Combien de temps empêcher une commande identique ?",
        "Ce délai évite plusieurs départs, retours ou mouvements du volet si un état tarde à remonter.",
        "duree", 10, 5, 60, 5,
        source="mower_control_constants.DEFAULT_MOWER_CONTROL_COMMAND_COOLDOWN_MINUTES",
        avertissement="Réglage sensible : un délai trop court peut envoyer plusieurs fois la même commande au matériel.",
    ),
    Reglage(
        "tondeuse_garage_ouvrir_avant_depart", "installation",
        "Ouvrir automatiquement le garage avant un départ ?",
        "Sinon, le volet doit être ouvert manuellement ; la tondeuse attend toujours la confirmation de son ouverture.",
        "interrupteur", True, 0, 1, 1,
        source="mower_control_constants.DEFAULT_MOWER_GARAGE_OPEN_BEFORE_START",
        avertissement="Réglage sensible : désactivé, un volet fermé bloque le départ jusqu'à son ouverture manuelle.",
    ),
    Reglage(
        "tondeuse_garage_ouvrir_pour_retour", "installation",
        "Ouvrir automatiquement le garage pour le retour ?",
        "Sinon, l'intégration n'ordonne pas le retour tant que le volet n'est pas confirmé ouvert.",
        "interrupteur", True, 0, 1, 1,
        source="mower_control_constants.DEFAULT_MOWER_GARAGE_OPEN_FOR_RETURN",
        avertissement="Réglage sensible : désactivé, le volet doit être ouvert avant qu'une autre automatisation rappelle la tondeuse.",
    ),
    Reglage(
        "tondeuse_garage_fermer_apres_retour", "installation",
        "Fermer automatiquement le garage après la rentrée ?",
        "Sinon, le volet reste ouvert jusqu'à sa fermeture manuelle.",
        "interrupteur", True, 0, 1, 1,
        source="mower_control_constants.DEFAULT_MOWER_GARAGE_CLOSE_AFTER_DOCK",
        avertissement="Réglage sensible : la fermeture automatique exige toujours une rentrée fortement confirmée.",
    ),
    Reglage(
        "tondeuse_garage_avance_ouverture", "installation",
        "Après l'ouverture du garage, combien de temps attendre avant le départ ?",
        "La tondeuse ne démarre qu'après l'ouverture confirmée puis ce délai de sécurité.",
        "duree", 2, 0, 10, 0.25,
        source="mower_control_constants.DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES",
        avertissement="Réglage sensible : zéro minute réduit la marge laissée au volet pour libérer complètement le passage.",
    ),
    Reglage(
        "tondeuse_garage_ouverture_min", "installation",
        "Quelle ouverture minimale confirme que le passage est libre ?",
        "Si le volet publie sa position, la tondeuse attend que ce pourcentage soit atteint. Sans position publiée, l'état ouvert reste utilisé.",
        "nombre", 95, 50, 100, 5, "%",
        source="mower_control_constants.DEFAULT_MOWER_GARAGE_MIN_OPEN_POSITION",
        avertissement="Réglage sensible : une valeur trop basse peut autoriser le passage sous un volet encore partiellement fermé.",
    ),
    Reglage(
        "tondeuse_garage_delai_fermeture", "installation",
        "Après la rentrée confirmée, combien de temps attendre avant de fermer ?",
        "Le volet reste ouvert après un signal fort de station ou de charge, puis se ferme.",
        "duree", 2, 1, 15, 0.25,
        source="mower_control_constants.DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES",
        avertissement="Réglage sensible : un délai trop court peut fermer le volet alors que la tondeuse termine sa manœuvre.",
    ),
)

# Les chiffres de chaque sol sont ceux du moteur (réserve de départ et stock maximal) :
# `tests/test_reglages.py` les compare à `soil_balance` et à son jumeau de `water`.
CHOIX: tuple[Choix, ...] = (
    Choix(
        "pilotage_tondeuse", "installation",
        "Qui commande les départs et les retours de la tondeuse ?",
        "Commencer par Observation. Actif envoie réellement les commandes à la tondeuse et au garage configuré.",
        "desactive",
        (
            Option("desactive", "Désactivé", "L'intégration observe la tondeuse mais ne décide ni départ ni retour."),
            Option("observation", "Observation", "Elle affiche ce qu'elle ferait, sans envoyer aucune commande."),
            Option(
                "actif",
                "Actif",
                "Elle lance le cycle, laisse la tondeuse gérer ses recharges, puis la relance une fois si elle l'a rappelée.",
            ),
        ),
        source="const.MOWER_CONTROL_MODES",
    ),
    Choix(
        "tondeuse_creneaux_depart", "installation",
        "Dans quels créneaux la tondeuse peut-elle démarrer automatiquement ?",
        "Ce choix filtre uniquement les nouveaux départs. Une tondeuse déjà dehors rentre toujours si les conditions deviennent bloquantes.",
        "ideal_seulement",
        (
            Option("ideal_seulement", "Idéal seulement", "Le choix conseillé pour un gazon d'ornement : départ uniquement dans le meilleur créneau."),
            Option("ideal_acceptable", "Idéal ou acceptable", "Autorise aussi le créneau du soir quand le meilleur moment n'a pas suffi."),
            Option("tout_non_bloque", "Tout créneau non bloqué", "Autorise même un départ dans un créneau déconseillé ; les blocages de sécurité restent prioritaires."),
        ),
        source="mower_control_constants.MOWER_START_WINDOW_POLICIES",
    ),
    Choix(
        "type_sol", "installation",
        "Quel est le type de terre du jardin ?",
        "Elle décide combien d'eau le sol garde pour le gazon, donc quand arroser et combien.",
        "limoneux",
        (
            Option(
                "sableux", "Sableuse",
                "Elle coule entre les doigts. L'eau file vite : les arrosages sont plus petits et plus fréquents.",
                8.0, 16.0,
            ),
            Option(
                "limoneux", "Limoneuse",
                "Douce comme de la farine. Elle garde l'eau sans la retenir trop longtemps.",
                12.0, 24.0,
            ),
            Option(
                "argileux", "Argileuse",
                "Elle colle aux doigts et se fend l'été. Elle garde l'eau longtemps : les arrosages s'espacent.",
                16.0, 32.0,
            ),
        ),
        source="const.TYPES_SOL, soil_balance.SOIL_RESERVE_BASE_MM et SOIL_RESERVE_MAX_MM",
    ),
)

CONTRAINTES: tuple[Contrainte, ...] = (
    Contrainte("tonte_fenetre_ideale_debut", "tonte_fenetre_ideale_fin",
               "Le début du meilleur moment doit venir avant sa fin."),
    Contrainte("tonte_vent_a_eviter", "tonte_vent_bloque",
               "Le vent « à éviter » doit être plus faible que le vent « interdit »."),
    Contrainte("tonte_temperature_a_eviter", "tonte_temperature_bloquee",
               "La chaleur « à éviter » doit être plus basse que la chaleur « interdite »."),
    Contrainte("arrosage_ouverture", "arrosage_fin_optimale",
               "L'arrosage doit pouvoir commencer avant la fin du meilleur moment."),
    Contrainte("arrosage_fin_optimale", "arrosage_fin_acceptable",
               "Le meilleur moment doit finir avant l'heure limite.", stricte=False),
    Contrainte("graines_fin_germination", "graines_fin_enracinement",
               "La germination doit finir avant l'enracinement."),
    Contrainte("graines_fin_enracinement", "graines_fin_reprise",
               "L'enracinement doit finir avant la reprise."),
    Contrainte("graines_fin_reprise", "graines_duree",
               "La reprise doit finir avant la fin du suivi des graines."),
    Contrainte("graines_fenetre_debut", "graines_fenetre_fin",
               "Les graines doivent pouvoir être arrosées avant l'heure de fin."),
    # « attente de la tondeuse < durée du suivi » n'est pas une contrainte : les bornes (21 < 30)
    # la garantissent déjà, et `tests/test_reglages.py` y veille.
    Contrainte("sursemis_lame", "sursemis_lame_finale",
               "La lame ne peut que remonter : la hauteur finale doit être au moins égale.", stricte=False),
    Contrainte("semis_hauteur_enracinement", "semis_hauteur_germination",
               "La hauteur conseillée ne remonte pas en cours de route.", stricte=False),
    Contrainte("semis_hauteur_reprise", "semis_hauteur_enracinement",
               "La hauteur conseillée ne remonte pas en cours de route.", stricte=False),
    Contrainte("semis_hauteur_stabilisation", "semis_hauteur_reprise",
               "La hauteur conseillée ne remonte pas en cours de route.", stricte=False),
)

_PAR_CLE: dict[str, Reglage] = {r.cle: r for r in REGLAGES}


def reglage(cle: str) -> Reglage:
    return _PAR_CLE[cle]


def valeurs_par_defaut() -> dict[str, Any]:
    return {r.cle: (list(r.defaut) if isinstance(r.defaut, tuple) else r.defaut) for r in REGLAGES}


def _valeurs_de(r: Reglage, valeur: Any) -> list[Any] | None:
    """Les nombres à contrôler, ou None si la forme ne va pas (une table veut douze nombres)."""
    if r.genre == "table_mois":
        if not isinstance(valeur, (list, tuple)) or len(valeur) != 12:
            return None
        return list(valeur)
    return [valeur]


def _est_un_nombre(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v  # NaN exclu


def _fr(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _tombe_sur_le_pas(r: Reglage, v: float) -> bool:
    crans = (v - r.minimum) / r.pas
    return abs(crans - round(crans)) < 1e-6


def _erreur_de_valeur(r: Reglage, valeur: Any) -> str | None:
    """Ce qui ne va pas dans une valeur prise seule (forme, bornes, pas), ou None."""
    if r.genre == "interrupteur":
        return None if isinstance(valeur, bool) else "Sélectionner activé ou désactivé."
    nombres = _valeurs_de(r, valeur)
    if nombres is None or not all(_est_un_nombre(v) for v in nombres):
        return "Il faut un nombre pour chaque mois." if r.genre == "table_mois" else "Il faut un nombre."
    if not all(r.minimum <= float(v) <= r.maximum for v in nombres):
        return f"Sélectionner une valeur entre {_fr(r.minimum)} et {_fr(r.maximum)}."
    if not all(_tombe_sur_le_pas(r, float(v)) for v in nombres):
        return f"La valeur avance de {_fr(r.pas)} en {_fr(r.pas)}."
    return None


def _contraintes_violees(complet: Mapping[str, Any]) -> list[Contrainte]:
    violees = []
    for c in CONTRAINTES:
        gauche, droite = float(complet[c.gauche]), float(complet[c.droite])
        if gauche > droite or (c.stricte and gauche == droite):
            violees.append(c)
    return violees


def valider(valeurs: dict[str, Any]) -> dict[str, str]:
    """Erreurs par clé, en phrases simples. Vide = tout est bon.

    Les valeurs absentes prennent leur valeur par défaut pour juger les contraintes : pour juger
    une modification, passer l'ensemble ENREGISTRÉ complété des changements, pas les seuls
    changements (sinon une contrainte serait jugée contre un défaut qui n'est plus en vigueur).
    """
    erreurs: dict[str, str] = {}
    for cle, valeur in valeurs.items():
        r = _PAR_CLE.get(cle)
        if r is None:
            erreurs[cle] = "Réglage inconnu."
            continue
        erreur = _erreur_de_valeur(r, valeur)
        if erreur is not None:
            erreurs[cle] = erreur
    complet = {**valeurs_par_defaut(), **{c: v for c, v in valeurs.items() if c not in erreurs}}
    for c in _contraintes_violees(complet):
        if c.gauche in erreurs or c.droite in erreurs:
            continue
        erreurs.setdefault(c.gauche, c.message)
    return erreurs


def _normaliser(r: Reglage, valeur: Any) -> Any:
    if r.genre == "interrupteur":
        return bool(valeur)
    if r.genre == "table_mois":
        return [float(v) for v in valeur]
    nombre = float(valeur)
    return int(nombre) if nombre.is_integer() and float(r.pas).is_integer() else nombre


def _egal_au_defaut(r: Reglage, valeur: Any) -> bool:
    if r.genre == "interrupteur":
        return valeur is r.defaut
    if isinstance(r.defaut, tuple):
        return [float(v) for v in valeur] == [float(v) for v in r.defaut]
    return abs(float(valeur) - float(r.defaut)) < 1e-9


def nettoyer(brut: Any) -> dict[str, Any]:
    """Les réglages enregistrés d'une instance, tels que le moteur peut les lire sans risque.

    Tout a été validé à l'écriture, mais une mise à jour peut avoir resserré une borne ou ajouté
    une contrainte depuis. Un réglage devenu invalide est ÉCARTÉ, et le moteur reprend sa
    constante : une valeur hors bornes ne doit jamais faire tomber un calcul, ni passer en douce.
    Une contrainte violée écarte ses DEUX côtés (on ne sait pas lequel l'utilisateur voulait).
    Les valeurs égales au conseil sont retirées : elles ne changent rien aujourd'hui, et laissées
    là elles empêcheraient de suivre un conseil corrigé dans une version suivante.
    """
    if not isinstance(brut, Mapping):
        return {}
    gardees: dict[str, Any] = {}
    for cle, valeur in brut.items():
        r = _PAR_CLE.get(cle)
        if r is None or _erreur_de_valeur(r, valeur) is not None:
            continue
        gardees[cle] = _normaliser(r, valeur)
    while True:
        fautives = set()
        for c in _contraintes_violees({**valeurs_par_defaut(), **gardees}):
            fautives |= {c.gauche, c.droite} & gardees.keys()
        if not fautives:
            break
        for cle in fautives:
            gardees.pop(cle)
    return {cle: valeur for cle, valeur in gardees.items() if not _egal_au_defaut(_PAR_CLE[cle], valeur)}


def lire(reglages: Mapping[str, Any] | None, cle: str, defaut: Any) -> Any:
    """La valeur réglée pour cette instance, ou `defaut` — la constante du moteur.

    `reglages` doit sortir de `nettoyer` : aucune validation n'est refaite ici, ce chemin est lu à
    chaque cycle. Une clé inconnue du registre est une faute de frappe dans le moteur : elle lève.
    """
    if cle not in _PAR_CLE:
        raise KeyError(f"Réglage inconnu du registre : {cle}")
    if reglages:
        valeur = reglages.get(cle)
        if valeur is not None:
            return valeur
    return defaut


def valeurs_effectives(reglages: Mapping[str, Any] | None) -> dict[str, Any]:
    """Toutes les valeurs d'une instance : le conseil, remplacé par ce qu'elle a réglé."""
    return {**valeurs_par_defaut(), **nettoyer(reglages)}


def valider_choix(valeurs: dict[str, Any]) -> dict[str, str]:
    """Erreurs par clé pour les choix (type de sol). Vide = tout est bon."""
    erreurs: dict[str, str] = {}
    par_cle = {c.cle: c for c in CHOIX}
    for cle, valeur in valeurs.items():
        choix = par_cle.get(cle)
        if choix is None:
            erreurs[cle] = "Choix inconnu."
        elif valeur not in {o.valeur for o in choix.options}:
            erreurs[cle] = "Sélectionner parmi : " + ", ".join(o.titre.lower() for o in choix.options) + "."
    return erreurs


def exporter() -> dict[str, Any]:
    """Tout ce dont la page a besoin, en types JSON."""
    return {
        "groupes": [asdict(g) for g in GROUPES],
        "reglages": [
            {**asdict(r), "defaut": list(r.defaut) if isinstance(r.defaut, tuple) else r.defaut}
            for r in REGLAGES
        ],
        "contraintes": [asdict(c) for c in CONTRAINTES],
        "choix": [asdict(c) for c in CHOIX],
    }
