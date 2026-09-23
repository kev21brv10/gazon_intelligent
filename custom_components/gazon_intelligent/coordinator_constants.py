from __future__ import annotations

from datetime import timedelta


AUTO_IRRIGATION_AUTO_SOURCES = {
    "auto_irrigation",
    "application_technique",
    "application_technique_auto",
}

AUTO_IRRIGATION_CHECK_INTERVAL = timedelta(minutes=2)
# Cooldown anti-relance : après la fin d'un cycle auto, aucun NOUVEAU gros cycle ne peut
# repartir avant ce délai. La fenêtre du soir (petit rafraîchissement canicule) en est
# exemptée. Objectif : un seul gros cycle « du matin » par jour, fini les relances en
# boucle observées en canicule (le déclencheur repartait ~10 s après la fin du cycle).
AUTO_IRRIGATION_RELAUNCH_COOLDOWN = timedelta(hours=6)

# États Home Assistant qui signifient « pas de mesure » et ne doivent JAMAIS être traités comme
# une valeur (ni exposés en attribut, ni interprétés comme un code d'erreur).
_UNAVAILABLE_STATES: frozenset[str] = frozenset({"unavailable", "unknown", "none"})

# Motifs de blocage tondeuse qui NE SE RÉSOLVENT PAS d'eux-mêmes : robot à l'arrêt hors station,
# entité indisponible, tondeuse introuvable ou ambiguë. Seuls ceux-là ouvrent l'arrosage de
# détresse (cf. `_should_launch_auto_irrigation`) — « tonte en cours » et « retour à la station »
# en sont volontairement exclus : ils se terminent seuls et arroser alors tremperait le robot en
# plein cycle, ce que la coordination existe précisément pour éviter.
# Seuls états de `sun.sun` qui portent une information : tout le reste (`unavailable`, `unknown`)
# signifie « position du soleil inconnue », pas « il fait nuit ».
_SUN_KNOWN_STATES: frozenset[str] = frozenset({"above_horizon", "below_horizon"})

_MOWER_BLOCK_REASONS_PERSISTANTS: frozenset[str] = frozenset(
    {"mower_not_stowed", "mower_unreliable", "ambiguous", "missing", "configured_missing"}
)

# DURÉE MINIMALE du blocage tondeuse avant que l'arrosage de détresse s'autorise.
# Le code de motif ne suffit pas à prouver la persistance : au redémarrage de Home Assistant,
# l'intégration démarre AVANT celle de la tondeuse et lit son entité comme absente pendant
# quelques secondes — `configured_missing`, donc un motif classé « persistant ».
# Constaté le 29/07/2026 à 03:11:34 : l'exception s'est armée sur cette absence transitoire, alors
# que le robot était à la station, batterie à 100 %. Elle contourne à la fois le blocage tondeuse
# ET la fenêtre horaire (`fenetre_optimale`, cf. `_should_launch_auto_irrigation`) : sans ce délai,
# un simple redémarrage en pleine nuit avec un déficit critique pouvait déclencher un arrosage à
# 3 h du matin, à rebours de la règle « toujours arroser à l'aube ».
# Un robot réellement coincé dehors le reste des heures ; une course au démarrage dure des
# secondes. 30 minutes séparent les deux sans retarder sensiblement un vrai cas de détresse.
_MOWER_DISTRESS_MIN_BLOCK_MINUTES: float = 30.0

# Plafond d'un échantillon : au-delà, l'écart entre deux cycles est un arrêt de Home Assistant,
# pas une durée vécue. Le cycle tourne toutes les 2 min, donc 15 min laisse largement la place
# à quelques cycles ratés sans jamais avaler un redémarrage.
_ECHANTILLON_MAX_MINUTES: float = 15.0

# ── CARNET DE PASSES ──────────────────────────────────────────────────────────────────────
# Une « passe » = un aller-retour garage → garage. C'est l'unité de travail réelle du robot,
# celle que le cumul de minutes de la journée ne sait pas voir : mesuré du 30/07 au 08/08/2026,
# une journée à trois blocages affiche 302 min tondues quand une journée parfaite en affiche
# 127 — parce qu'elle repart après chaque blocage. Le nombre de minutes ne dit pas si le gazon
# a été tondu ; le nombre de passes ABOUTIES, si.
#
# ⚠️ CE CARNET N'ALIMENTE AUCUNE DÉCISION. Il observe, il ne tranche pas. Le seuil de
# déclaration reste celui réglé par l'utilisateur tant qu'on n'a pas mesuré ce qu'est
# réellement un cycle complet sur CE jardin.
_PASSES_JOURNAL_MAX: int = 60
# Sous ce niveau, un retour est un retour BATTERIE. Au-dessus, elle a décidé elle-même que
# c'était fini. Mesuré le 08/08/2026 : retour à 10 % après 109 min (batterie), et retour à
# ~96 % après 18 min (décision de la machine, elle est repartie 9 s plus tard).
# ⚠️ Ce seuil ne sert QU'À ÉTIQUETER : les batteries brutes sont écrites telles quelles dans
# le journal, donc un mauvais classement se rejoue sans rien perdre.
_BATTERIE_RETOUR_VIDE_PCT: float = 20.0

# ⚠️ LA QUATRIÈME FIN, OUBLIÉE À LA LIVRAISON DU CARNET (0.53.0) — et c'est la plus fréquente
# sur cette installation. Le 13/08/2026 :
#
#     10:40:43,774   tonte_autorisee → off   (34,9 °C, seuil 30)
#     10:40:45,244   la tondeuse rentre      ← 1,5 seconde plus tard
#
# Elle est rentrée avec 58 % de batterie, RAPPELÉE par la coordination — pas parce qu'elle
# avait fini. Le carnet l'a pourtant étiquetée `retour_autonome`. Une étiquette qui ment, et
# qui nourrit ensuite `mower_autonomous_return_battery_median` : la mesure même censée dire à
# quel niveau la machine décide d'elle-même que le travail est terminé.
#
# Le rappel est reconnu sur l'AUTORISATION DE TONDRE au dernier échantillon de la passe.
# ⚠️ Elle est lue sur le résultat du cycle PRÉCÉDENT (`brain.last_result`) : le carnet tourne
# avant `compute_snapshot`, donc la décision du cycle courant n'existe pas encore. Ce n'est pas
# un pis-aller — c'est justement la décision publiée qui a provoqué le retour.
# En dessous de ce nombre de passes observées, aucune médiane n'est publiée : une « valeur
# apprise » tirée de deux observations est exactement le défaut « valeur fixe là où la réalité
# varie » que ce projet traque.
_PASSES_MIN_POUR_APPRENDRE: int = 3

# ── PLUIE MESURÉE ─────────────────────────────────────────────────────────────────────────
# La garde « il pleut en ce moment » n'avait qu'UNE entrée : la chaîne d'état d'une entité de
# PRÉVISION. Son second bras (`weather_precipitation_probability ≥ 80`) est toujours nul, la
# 0.44.0 l'avait déjà noté. Mesuré la nuit du 16/08/2026 :
#
#     00:12      pluviomètre 0,1 mm — la pluie COMMENCE     météo : partlycloudy
#     02:05:42   1,2 mm, il pleut toujours                  météo : clear-night
#                └→ 45 ms plus tard : 5 mm AUTORISÉS, `execution_autorisee: true`
#     03:59:47   2,4 mm                                     météo : rainy → la garde mord enfin
#
# 3 h 47 d'aveuglement, et c'est la prévision qui a DÉBLOQUÉ pendant qu'une mesure disait le
# contraire. Ce jour-là seuls le bilan hydrique (qui a compté la pluie réelle) et l'horaire ont
# évité l'arrosage sous l'averse. La garde reçoit donc ici une entrée MESURÉE.
#
# ⚠️ Le capteur configuré est un CUMUL (24 h glissantes) : sa VALEUR ne dit pas s'il pleut,
# seulement combien il est tombé — 3,2 mm restent affichés une journée entière après l'averse.
# Ce qui signe une averse EN COURS, c'est sa HAUSSE. On garde donc la dernière lecture et
# l'instant de la dernière hausse, et on ne conclut que sur la fraîcheur de cette hausse.
# ── LE SILENCE D'EN FACE ──────────────────────────────────────────────────────────────────
# Le DÉCLENCHEUR de la tonte ne vit pas dans cette intégration : c'est un flow Node-RED. Quand
# il est coupé, l'intégration continue de recommander dans le vide et RIEN ne le signale.
# Deux fois en 2026 : le nœud de déclaration éteint du 30/07 au 06/08 (sept jours d'historique
# perdus), et l'onglet Tondeuse désactivé qui a laissé filer 1 h 49 de fenêtre idéale le
# 21/08 — `action_possible` vrai à 10:01, la machine prête et au garage, aucun départ.
#
# Latence normale mesurée entre l'autorisation et le départ : 6 min le 16/08, 6 min le 19/08.
# 30 minutes laissent donc largement la place à un démarrage normal tout en restant loin de la
# fin de la fenêtre idéale (10h-14h depuis la 0.90.0).
#
# ⚠️ N'ALIMENTE AUCUNE DÉCISION — il observe, il ne tranche pas. Un compteur de silence qui
# relâcherait un garde-fou serait pire que le silence lui-même.
_RECOMMANDATION_IGNOREE_MINUTES: float = 30.0

_PLUIE_MESUREE_FENETRE_MINUTES: float = 30.0
# Pas de mesure du pluviomètre (0,1 mm). Le seuil s'intercale entre le bruit flottant (1e-9) et
# le plus petit incrément réel, donc toute vraie hausse est vue et aucune ne s'invente.
_PLUIE_MESUREE_HAUSSE_MIN_MM: float = 0.05

# ── LAME D'EAU RÉCENTE — FENÊTRE GLISSANTE ────────────────────────────────────────────────
# ⚠️ « IL A PLU » NE DIT PAS COMBIEN, et c'est ce qui manquait au ressuyage de la tonte. Le
# 09/09/2026 à 20:12, UN basculement d'auget du pluviomètre voisin — 0,0 → 0,1 mm — a armé les
# mêmes 180 minutes de ressuyage qu'une vraie averse, sur une pelouse où la station du jardin
# n'a rien mesuré (compteur figé à 2,3 de 04:14 à minuit).
#
# ⚠️ ET LE PREMIER JET DU CORRECTIF FAISAIT PIRE QUE LE DÉFAUT. Il cumulait un « épisode »
# remis à zéro dès qu'une hausse arrivait après un trou d'une heure. Une revue adversariale l'a
# rejoué sur du code réel : 6,0 mm de 14:00 à 14:50, ressuyage armé jusqu'à 17:50 — puis UN
# auget de traîne à 16:25 REMETTAIT l'épisode à 0,1 mm, donc sous le minimum, donc **ressuyage
# supprimé**. La tonte redevenait autorisée à 17:00 sur une pelouse ayant reçu 6,1 mm. Plus il
# pleuvait, moins on bloquait. Un accumulateur qu'on DÉTRUIT n'est pas une mesure.
#
# On tient donc une FENÊTRE GLISSANTE : chaque hausse est horodatée, celles qui sortent de la
# fenêtre tombent d'elles-mêmes, et la lame est leur somme. Rien n'est jamais effacé par une
# pluie plus récente ; une bruine fractionnée s'additionne au lieu de se découper ; et une pluie
# vieille de plusieurs heures sort du calcul sans qu'on ait à la « fermer ».
#
# 240 min : le ressuyage le plus long vaut 180 min à partir de la DERNIÈRE goutte. La fenêtre
# doit donc rester plus large que lui, sinon la lame s'évanouirait avant la fin du délai
# qu'elle a elle-même armé.
_PLUIE_LAME_FENETRE_MINUTES: float = 240.0
# Filet mémoire : une averse tique au plus une fois par cycle (2 min), soit 120 entrées sur la
# fenêtre. Le plafond ne sert qu'à borner une horloge qui reculerait ou un état corrompu.
_PLUIE_LAME_MAX_ENTREES: int = 200

# ── TOTAL DU JOUR DEPUIS UN COMPTEUR CUMULATIF ────────────────────────────────────────────
# Le compteur du WS90 ne se remet JAMAIS à zéro, et il chute parfois brutalement à 0 avant de
# revenir à sa valeur — trames corrompues documentées, simultanées à des rafales à plus de
# 25 000 km/h. Un `utility_meter` branché dessus compte ces remontées comme de la pluie.
#
# On ne compte donc QUE CE QUI DÉPASSE LE MAXIMUM DÉJÀ VU :
#     250 → 0     chute parasite  → aucun gain, le maximum reste 250
#     0   → 250   remontée        → aucun gain, on est sous le maximum
#     250 → 250,4 vraie pluie     → +0,4 mm
# Et le total du jour est remis à zéro par NOTRE horloge, pas par celle du capteur.
#
# ⚠️ Plafond de plausibilité par pas de cycle (~2 min). Les pluies les plus intenses relevées
# en France plafonnent vers 3 mm/min ; 30 mm en un pas laisse un facteur 5 de marge et écarte
# les sauts de compteur. À recalibrer quand la station sera là et qu'on aura ses vrais écarts.
_PLUIE_GAIN_MAX_PAR_PAS_MM: float = 30.0

# Fenêtres pour lesquelles un renoncement à arroser est un vrai REFUS, digne d'être tracé.
# Doit rester un sous-ensemble de `POSSIBLE_FENETRE_OPTIMALE_VALUES` (decision_models.py) :
# une valeur inventée ici désactive silencieusement la trace pour cette fenêtre.
_SKIP_RECORDED_WINDOWS: frozenset[str] = frozenset({"ce_matin", "demain_matin", "maintenant", "soir"})

# Journée civile de repli quand le lever/coucher du soleil est inconnu (`sun.sun` pas encore
# publié au démarrage). 06:00 → 21:00 : volontairement large, elle n'a qu'à tenir quelques
# secondes. Voir `_et_elapsed_fraction` pour ce que l'ancien repli à 1.0 a coûté.
_FALLBACK_DAY_START_MINUTE: int = 6 * 60
_FALLBACK_DAY_END_MINUTE: int = 21 * 60

# Veilleur de vanne : cadence de contrôle pendant un segment d'arrosage, et nombre de
# relances tolérées avant d'abréger. Une seule relance : un relais qui retombe deux fois
# n'est plus un accident.
_ZONE_WATCH_INTERVAL_S = 15.0
_ZONE_WATCH_MAX_RELANCES = 1

# Étape 2 (choix retenu, 15/09/2026) : l'arrosage du matin vise une fin 15 min avant le lever du
# soleil. La marge couvre surtout le retard au lancement (jusqu'à un intervalle de contrôle, 2 min)
# et un objectif qui monte pendant l'attente. La latence des vannes n'y pèse presque rien : 0,3 s
# mesurées par cycle (11 et 15/09).
WATERING_SUNRISE_MARGIN_MINUTES = 15
