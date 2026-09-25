# Changelog

## 1.0.0-rc.10

- **Page du gazon de nouveau défilable** : depuis peu, la page ne défilait plus du tout au-delà
  du premier écran, quel que soit l'onglet — y compris Accueil, jamais concerné par le
  réaménagement de rc.9. En cause : la page dépendait d'une hauteur transmise par l'enrobage de
  Home Assistant (`ha-panel-custom` / `partial-panel-resolver`) pour savoir où faire défiler
  son propre contenu ; cette hauteur n'était plus fournie. La page se dimensionne maintenant
  directement sur la hauteur de la fenêtre, sans dépendre de cet enrobage.
- **Vérifié** : suite complète avec 2 218 tests et 3 242 sous-tests, verte ; défilement
  revérifié en conditions réelles sur l'instance Home Assistant.

## 1.0.0-rc.9

- **Page « Réglages » réorganisée sur grand écran** : chaque carte de réglage est repliable
  depuis longtemps, mais restait forcée ouverte en permanence sur ordinateur quel que soit
  le nombre de réglages. Avec 69 réglages aujourd'hui, chaque onglet (Tonte, Arrosage,
  Sursemis, Semis, Installation, Entités) déballait toutes ses cartes d'un coup à chaque
  visite. Les cartes se replient désormais par défaut sur grand écran comme sur mobile ; une
  carte contenant un réglage personnalisé (différent du conseil) ou en cours de modification
  reste ouverte. Dans les onglets Semis et Sursemis, un bandeau distingue maintenant
  clairement « Arrosage des graines » (commun aux deux modes) de la tonte propre à la phase,
  jusque-là mêlés dans une seule liste.
- **Vérifié** : suite complète avec 2 218 tests et 3 242 sous-tests, verte.

## 1.0.0-rc.8

- **Plafond hebdomadaire d'arrosage plus honnête hors phase Normal** : la carte « L'eau de la
  semaine » présentait le cumul des 7 derniers jours comme une limite bloquante (barre rouge,
  « pour ne pas trop arroser ») quelle que soit la phase active, alors que le moteur de décision
  ne cappe réellement la dose sur ce plafond que pendant la phase Normal — Semis, Sursemis,
  Traitement, Fertilisation, Biostimulant, Agent Mouillant, Scarification et Hivernage ne le
  font jamais. La carte distingue maintenant une vraie limite (phase Normal, ou motif de
  blocage explicitement nommé par le moteur) d'un simple repère informatif pour les autres
  phases, avec un texte neutre plutôt que ciblé sur une seule phase. Une phase indisponible ou
  non reconnue reste traitée comme une vraie limite par défaut, pour ne jamais masquer un
  plafond qui s'applique réellement.
- **Capteur « prochain arrosage » qui ne ment plus pendant une session active** : il affichait
  encore une cible théorique (heure, date, fenêtre) parfois déjà passée pendant qu'un cycle
  d'arrosage tournait. Pendant une session active, il indique maintenant « En cours » et
  n'expose plus aucun attribut de cible périmée.
- **Vérifié** : suite complète avec 2 212 tests et 3 242 sous-tests, verte.

## 1.0.0-rc.7

- **Réglage dédié pour la reprise de tonte en Semis** : nouveau réglage `semis_reprise_tonte_jours`
  (groupe Semis, 25 jours par défaut, réglable de 14 à 40), qui découple l'AUTORISATION et la
  FRÉQUENCE de tonte de `graines_fin_enracinement`. Ce dernier continue de régler l'arrosage des
  graines et reste par ailleurs la borne des sous-phases affichées, dont dépend la hauteur de
  tonte recommandée pendant le Semis (`_plancher_semis`) : les deux réglages restent donc liés
  sur ce point précis, pas totalement indépendants.
- **Date de reprise corrigée en Sursemis** : le panneau annonçait un jour de moins que ce que le
  moteur autorise réellement ; la zone d'attente et la date affichée suivent maintenant la même
  échéance.
- **Bulletin de tonte plus précis** : le texte « Ce qu'il faut savoir » annonçait la tonte
  possible dès maintenant même quand le statut réel imposait de la prudence ou une surveillance ;
  il reprend désormais le vrai statut publié.
- **Bandeau d'accueil aligné sur le même statut** : le titre « En ce moment » affichait la même
  généralisation optimiste que le bulletin ; il distingue maintenant tonte possible, possible
  avec précaution et à surveiller.
- **Surface du gazon réellement modifiable** : le réglage de surface était déclaré mais invisible
  dans l'onglet Installation ; son édition n'alimentait pas le compteur de brouillon ni le bouton
  « Annuler les changements » de l'onglet. Les trois trous sont corrigés.
- **Préparation du sol propagée par le service public** : une déclaration de Semis/Sursemis via le
  service (pas seulement via le changement de mode direct) enregistre désormais la préparation du
  sol associée, pour un historique cohérent quel que soit le chemin emprunté.
- **Capteur de consommation d'eau plus honnête après un échec du coordinateur** : il ne se fiait
  qu'à la surface configurée et pouvait donc rester « disponible », avec le dernier total calculé,
  même après un rafraîchissement en échec.
- **Conseil de tonte qui ne se fait plus masquer par un texte d'arrosage générique** : l'« Action
  recommandée » affichait un blocage d'arrosage sans motif (ou un texte d'arrosage par ailleurs
  spécifique mais non pertinent, ex. prochain cycle graines programmé) alors qu'un conseil de
  tonte plus informatif était déjà calculé ailleurs sur la page. Un motif d'arrosage nommé
  (ex. « Sol déjà humide ») reste prioritaire comme avant.
- **Vérifié** : suite complète avec 2 198 tests et 3 233 sous-tests, verte.

## 1.0.0-rc.6

- **Trois chantiers clairement distincts** : le Sursemis comprend désormais explicitement la
  scarification du gazon existant, le Semis comprend un travail complet du sol et le mode
  Scarification désigne uniquement une scarification sans graines.
- **Historique explicite** : les nouvelles déclarations conservent la préparation du sol associée
  (`scarification_incluse`, `travail_complet_du_sol` ou
  `scarification_seule_sans_graines`) sans créer de deuxième phase concurrente.
- **Activation plus sûre** : la page demande d'activer Semis ou Sursemis seulement après la
  préparation correspondante et la mise en place des graines. Une scarification seule ne lance
  aucun programme d'arrosage de graines.
- **Vérifié** : 71 tests ciblés et 24 sous-tests, puis suite complète avec 2 182 tests et
  3 220 sous-tests.

## 1.0.0-rc.5

- **Estimation de la consommation d'eau** : un nouveau capteur additionne les lames d'eau
  enregistrées pour aujourd'hui, le mois courant et depuis le 1er janvier, puis les convertit en
  litres avec la surface totale du gazon (`1 mm × 1 m² = 1 L`).
- **Surface configurable** : le nouveau réglage `surface_gazon_m2` reste neutre par défaut afin
  que chaque installation renseigne sa propre surface. Sans surface, le capteur demeure
  indisponible plutôt que d'afficher un faux zéro.
- **Couverture historique explicite** : l'estimation indique la première date encore conservée
  et ne présente l'année comme complète que si une trace remonte au 1er janvier ou avant. Elle
  reste clairement identifiée comme une estimation jusqu'à l'installation d'un compteur d'eau.
- **Vérifié** : scénarios sur une surface de 255 m², registres de réglages et d'entités, puis
  suite complète avec 2 180 tests et 3 217 sous-tests. Compilation Python et contrôle du diff
  verts.

## 1.0.0-rc.4

- **Une pluie apparue pendant une recharge intermédiaire ne pouvait pas interrompre le cycle** :
  le pilote rendait immédiatement la main au constructeur dès que la tondeuse était à sa base,
  même lorsque le gazon retirait formellement son autorisation. Le robot pouvait donc repartir
  sous la pluie et le volet devait rester ouvert. Le pilote envoie désormais une unique commande
  `dock` dans ce cas précis. La dette de reprise n'est créée qu'après le succès réel du service
  Home Assistant; un refus ne ferme pas le garage et ne mémorise pas une reprise fictive.
- **Recharge normale inchangée** : tant que la tonte reste autorisée, le volet demeure ouvert et
  le constructeur gère seul la recharge et le redépart. Un créneau seulement « déconseillé »
  n'interrompt pas un cycle déjà engagé.
- **Reprise complète après interruption** : une fois l'arrêt accepté, le volet peut se fermer
  après la temporisation configurée. Au retour de conditions sûres, il est rouvert et une seule
  commande de reprise est envoyée, avec les gardes de batterie, de disponibilité et d'arrosage.
- **Le repli sans télémétrie ne confond plus une charge avec une fin de travail** : l'opération
  `charging`, une interdiction active ou une dette de reprise empêchent désormais ce repli
  d'effacer prématurément le cycle géré.
- **Vérifié** : 54 tests ciblés sur le moteur pur et le coordinateur, puis suite complète avec
  2 175 tests et 3 214 sous-tests sous Pytest. La suite `unittest` passe également avec 2 132
  tests. Compilation Python et `git diff --check` verts. Un essai surveillé sur le matériel reste
  requis pour confirmer la réaction propre à l'adaptateur lorsqu'il reçoit `dock` déjà à la base.
- **Trou de couverture comblé après vérification indépendante** : le garde qui exclut `charging`
  du repli sans télémétrie est correct, mais rien ne le prouvait — le retirer par mutation
  laissait passer les 60 tests ciblés sans qu'aucun n'échoue, en reproduisant pourtant le danger
  initial (recharge normale, tonte encore autorisée, aucune télémétrie). Un test dédié comble ce
  trou. Suite complète : 2176 tests, verte.

## 1.0.0-rc.3

- **Un départ jamais confirmé restait bloqué pour toujours** : signalé en relecture automatique
  de la PR #52. Le diagnostic ajouté en rc.2 après un long silence changeait seulement le
  libellé affiché, sans rien effacer : `managed_start_pending` restait vrai indéfiniment et plus
  aucune nouvelle tentative de départ n'était jamais envoyée. L'état est désormais libéré après
  ce délai, ce qui permet une vraie nouvelle tentative au cycle suivant — toujours protégée par
  le délai habituel entre deux commandes.
- **Un cycle sans télémétrie ne pouvait plus jamais se terminer** : pour un robot qui ne publie
  ni progression ni état de travail, rien ne permettait de détecter la fin d'un cycle autonome.
  Une fois le premier départ confirmé, l'intégration restait persuadée qu'un cycle était en
  cours pour toujours — plus aucun nouveau départ, plus aucune fermeture de garage. Un signal de
  quai fort sert désormais de repli, uniquement quand aucune télémétrie n'a jamais été observée
  (une simple pause batterie mi-travail, avec télémétrie, n'est jamais concernée).
- **Le nouveau rôle « Point de rosée (air) » (0.97.24) pouvait mal lire un capteur en °F ou K** :
  la page l'acceptait, mais la valeur n'était jamais convertie avant d'être comparée à une
  température en °C — 50 °F aurait été traité comme 50 °C, faisant croire l'herbe mouillée en
  permanence et bloquant la tonte. Restreint au °C, comme le rôle Température existant.
- **Vérifié** : 4 tests supplémentaires, chacun confirmé par mutation séparément (un seul test
  échoue à chaque fois, le bon). Suite complète : 2170 tests, verte.

## 1.0.0-rc.2

- **Un vieux pourcentage de tonte ne confirme plus un départ jamais observé** : signalé en
  relecture de la PR #52. Après l'envoi de `start_mowing`, le pilote considérait le cycle
  « bien parti » (`managed_cycle_active`) dès que la progression publiée par la tondeuse
  passait sous 100 % — même si cette valeur venait d'un travail ancien, interrompu, jamais
  remis à zéro, et que la tondeuse était toujours à quai. Le pilote pouvait alors croire un
  cycle autonome lancé qui n'avait jamais réellement commencé, et ne plus jamais relancer la
  machine.
- **Un signal frais est désormais exigé** : une référence (identifiant de travail, progression,
  état du travail, horodatage) est mémorisée au moment même de la commande ; le départ n'est
  confirmé que sur une vraie TRANSITION par rapport à cette référence — sortie ou tonte observée,
  nouvel identifiant de travail, progression qui a réellement augmenté, ou passage à un état actif
  qui n'y était pas déjà. Une deuxième relecture a montré qu'un premier correctif laissait encore
  passer un travail resté `en_pause` sans changement (même identifiant, même progression, tondeuse
  toujours à quai) : corrigé en exigeant aussi une transition sur l'état du travail, pas seulement
  sur l'identifiant et la progression.
- **Repli prudent sur un état hérité d'avant ce correctif** : un cycle déjà en attente (persisté)
  sans aucune référence capturée ne confirme le départ que sur un signal physique sans ambiguïté
  (sortie ou tonte observée), jamais sur l'identifiant ou la progression seuls.
- **Diagnostic après un long silence** : si aucun signal frais n'arrive dans les 15 minutes
  suivant la commande, l'état affiché devient « départ non confirmé » — purement informatif,
  aucune commande n'est relancée ni annulée.
- **Aucun impact aujourd'hui** : les commandes réelles ne partent qu'en mode Pilotage **Actif** ;
  ce correctif ne change rien pour une installation restée en Observation, mais protège le
  passage futur à Actif.
- **Vérifié** : cas de régression exact (travail ancien à 18 %, tondeuse à quai) reproduit et
  couvert pour les trois signaux (identifiant, progression, état), plus l'état hérité sans
  référence et l'expiration diagnostique — 9 tests dédiés au total ; chaque trou corrigé a été
  confirmé par mutation (le comportement retiré fait échouer le test correspondant, jamais
  d'autres). Suite complète : 2166 tests, verte.

## 1.0.0-rc.1

- **Premiere candidate officielle a la version stable** : les fonctions validees des versions
  0.97.10 a 0.97.24 sont regroupees sous un numero SemVer lisible. `rc.1` signifie que le contenu
  vise la future 1.0.0, mais qu'il reste encore une validation reelle avant de le declarer stable.
- **Aucun changement de comportement dans ce changement de numero** : calculs, seuils,
  arrosage, tonte, garage, notifications, reglages et valeurs existantes restent identiques a la
  0.97.24.
- **Validation exigee avant 1.0.0** : tester le bouton reel `5 min` dans un creneau surveille,
  puis observer cette candidate pendant au moins 24 heures sans erreur ni regression. Une
  correction eventuelle produira `1.0.0-rc.2`; une observation propre permettra de publier
  `1.0.0` apres accord explicite.
- **Double verification de la candidate fonctionnelle** : 2 157 tests et 3 212 sous-tests sous
  Pytest, Ruff vert et Mypy sans probleme sur 53 fichiers avant le changement de numero.

## 0.97.24

- **Nouveau rôle « Point de rosée (air) » dans Réglages > Entités** : le bandeau météo affiche
  plusieurs valeurs (UV, point de rosée, condition) sans qu'on puisse toutes les remplacer par ses
  propres capteurs. Vérifié une par une : UV et la plage du jour sont purement cosmétiques ou déjà
  masqués par la couverture nuageuse mesurée — rien à gagner à les brancher. Le point de rosée,
  lui, sert réellement de repli à la détection de l'herbe mouillée (`estimate_rosee`) quand aucune
  « Rosée sur l'herbe » n'est branchée, et ne lisait jusqu'ici que la prévision générique de
  l'entité météo au lieu d'une station personnelle.
- **Rôle bien distinct de « Rosée sur l'herbe »**, volontairement voisin dans `sources.py` pour le
  contraste : celui-ci attend une température (°C, avec « rosée » ou « dew » dans le nom d'entité,
  jamais une température de l'air ordinaire) ; l'autre une humidité du feuillage (%) et refuse
  justement toute température, seule protection qui évitait de reproduire le bug de 0.94.0. Repli
  inchangé si le rôle n'est pas branché : le point de rosée de l'entité météo, comme avant.
- **Vérifié** : suite complète (2157 tests, 3212 sous-tests), banc de mutations sur la priorité
  capteur/entité météo (le mutant inversant l'ordre a bien fait échouer 3 tests), `git diff
  --check` verts. Aucun changement pour une installation qui ne branche pas ce nouveau rôle.

## 0.97.23

- **Le panneau Semis/Sursemis laissait croire que les réglages « Commun Semis / Sursemis »
  pilotaient aussi la tonte des deux modes de la même façon** : signalé — « pour réglage semis et
  sursemis ils ne font pas la même chose ». Vérifié dans le code : le délai avant la reprise de la
  tonte n'est PAS partagé. En Semis (terrain nu), il est fixé par la fin d'enracinement
  (`graines_fin_enracinement`, un réglage de la page « Graines », 24 jours par défaut). En
  Sursemis (gazon déjà en place), il est fixé par son propre réglage séparé (`sursemis_levee`,
  7 jours par défaut). Seul l'arrosage des graines est réellement commun aux deux modes.
- **Trois corrections de texte, aucun changement de comportement** : la phrase d'introduction des
  onglets Semis et Sursemis précise maintenant que le libellé « Commun Semis / Sursemis » ne vaut
  que pour l'arrosage. La carte « La hauteur conseillée à chaque étape » (onglet Semis) affiche en
  plus une note dynamique donnant le jour exact où la tondeuse reprend, avec un renvoi explicite
  vers le réglage séparé du Sursemis pour éviter de confondre les deux délais.
- **Vérifié** : contrôle visuel dans l'aperçu local (fixture `?example=1`) sur les deux onglets, en
  ordinateur ; la nouvelle note reprend la valeur réelle du réglage (« jour 24 ») sans débordement.
  Aucun réglage, seuil ni calcul modifié — texte d'affichage seulement.

## 0.97.22

- **Les délais du garage de la tondeuse se règlent à la seconde près** : signalé — « pour le volet
  ça serait bien qu'il y ait des secondes pour que ce soit plus précis ». Le délai avant départ
  (après ouverture confirmée) et le délai avant fermeture (après rentrée confirmée) passaient
  d'une minute à l'autre sans étape intermédiaire. Ils se règlent maintenant au quart de minute
  (15 s) — l'affichage montre par exemple « 1 min 15 s » au lieu d'arrondir à « 1 min ». Les
  valeurs par défaut ne changent pas (2 min chacune) ; aucun changement pour une installation qui
  n'a pas encore de volet configuré.
- **Vérifié** : 2148 tests (3 nouveaux, dont un qui prouve — par mutation volontaire — que
  l'affichage des secondes est vraiment testé et pas juste présent), Ruff, Mypy (53 fichiers) et
  `git diff --check` verts. Contrôlé dans l'aperçu local (fixture `?example=1`, volet configuré) :
  le curseur avance par pas de 15 s, la bulle affiche « 1 min 15 s », « Revenir à 2 min » reste
  correct, et le résumé du sous-menu replié aussi.

## 0.97.21

- **Le bandeau météo compact disait « rosée », pas « point de rosée »** : signalé dans l'audit du
  20/09 comme dernier point avant la 1.0.0 (la page Météo détaillée avait déjà le bon libellé).
  Le badge de la carte « En ce moment » affiche maintenant « Point de rosée » — évite la confusion
  avec la rosée sur l'herbe (`capteur_rosee`, un concept différent, voir la note d'architecture).
  Aucun seuil ni calcul touché, texte d'affichage seulement.
- **Vérifié** : 2 145 tests, Ruff et `git diff --check` verts. Contrôlé à l'écran sur ordinateur
  (le badge s'affiche sur sa propre ligne, sans débordement) et sur téléphone (déjà masqué par la
  limite existante de 4 badges visibles sur petit écran — aucun changement visuel là).

## 0.97.20

- **Réduction par zone ombragée** : chaque vanne configurée dispose maintenant d'un réglage de
  `0 à 50 %` dans `Réglages > Arrosage > Les zones ombragées`. Une réduction de 20 % raccourcit
  uniquement la durée de cette zone de 20 %, sans modifier les autres zones.
- **Compatibilité totale par défaut** : les cinq réductions valent `0 %` après mise à jour. Sans
  personnalisation, les durées, doses, résumés, historiques et décisions restent identiques à la
  version précédente.
- **Plan et bilan cohérents** : le débit physique de l'arroseur reste inchangé. Le plan conserve
  la dose générale comme référence, expose la réduction de chaque zone et enregistre dans le
  bilan du sol la lame moyenne réellement délivrée. Un cycle ajusté terminé n'est pas signalé à
  tort comme incomplet.
- **Panneau adapté à l'installation** : seules les zones réellement configurées sont affichées,
  avec leur nom Home Assistant. Le groupe est ouvert sur ordinateur, replié sur téléphone, et
  chaque réduction porte un avertissement contre un réglage excessif.
- **Double vérification locale** : rendu contrôlé sur ordinateur et au format app Home Assistant
  390 × 844, y compris une modification à 20 %, la barre Enregistrer et son annulation. Les
  suites complètes passent avec **2 145 tests et 3 198 sous-tests** sous Pytest, puis **2 117
  tests** sous Unittest. Ruff et Mypy sur 53 fichiers sont verts.

## 0.97.19

- **Semis et Sursemis enfin complets** : chacun des deux onglets réunit désormais le programme
  d'arrosage des graines et ses propres règles de tonte. Semis affiche 19 réglages réels dans 10
  sous-menus ; Sursemis en affiche 22 dans 12 sous-menus.
- **Réglages communs sans doublon** : durée du suivi, étapes, doses, nombres de cycles, fenêtre
  horaire, météo et alerte restent stockés une seule fois et pilotent réellement les deux modes.
  La mention `Commun Semis / Sursemis` évite de faire croire à deux valeurs indépendantes.
- **Navigation simplifiée** : l'ancien onglet séparé `Graines` disparaît. Les sous-menus restent
  repliés pour garder une page lisible, affichent leur valeur résumée et la recherche ouvre
  directement le bon sous-menu dans Semis ou Sursemis.
- **Même rangement dans tous les réglages** : Tonte, Arrosage, Semis, Sursemis, Modes,
  Installation et Entités utilisent les mêmes groupes lisibles. Ils sont ouverts sur grand écran
  et repliés sur téléphone ; un groupe modifié se rouvre automatiquement pour ne pas masquer une
  valeur en attente. Les grilles stables évitent les grands espaces vides entre deux groupes.
- **En-tête mobile compact** : `Réglages du gazon` remplace le grand cadre explicatif. Sur
  téléphone, il mesure 102 px, masque le texte déjà connu et range les états sur une seule ligne
  glissable ; sur ordinateur, l'explication complète reste visible.
- **Restauration cohérente** : `Tout remettre comme conseillé` restaure à la fois les réglages
  communs aux graines et ceux propres au programme consulté, sans toucher aux autres familles.
- **Moteur inchangé** : aucun seuil agronomique, dose, adaptation météo, calendrier, décision
  d'arrosage ou comportement de tonte n'est modifié par cette réorganisation du panneau.
- **Double vérification locale** : les sept onglets ont été contrôlés sur ordinateur et au format
  téléphone Home Assistant 390 × 844, groupes fermés puis ouverts, sans débordement. Les suites
  complètes passent avec **2 140 tests et 3 178 sous-tests** sous Pytest, puis **2 112 tests** sous
  Unittest. Ruff, Mypy sur 53 fichiers, compilation Python, JavaScript, JSON et diff sont verts.

## 0.97.18

- **Nouvel onglet Entités** : toutes les liaisons externes utilisées par l'intégration sont
  regroupées dans Réglages, par famille : vannes, tondeuse et ses signaux, météo et capteurs,
  pompe, volet du garage, appareils de notification et IA.
- **Changement rapide et expliqué** : chaque liaison affiche son rôle, l'identifiant Home
  Assistant, sa valeur ou son état actuel, son comportement de repli et un bouton pour la
  remplacer ou la retirer lorsque c'est autorisé.
- **Vannes et tondeuse enfin modifiables depuis la page** : les cinq zones, la tondeuse
  principale, son erreur, sa batterie, sa pluie, sa charge et sa hauteur de coupe utilisent le
  même chemin de rechargement surveillé que les capteurs météo. Le prochain départ constructeur
  reste compatible en arrière-plan, mais n'est pas proposé ici : le pilotage natif décide lui-même
  quand partir et ouvre le garage avant sa propre commande.
- **Protections serveur** : mauvais domaine, entité absente, auto-référence, vanne dupliquée,
  pompe utilisée comme vanne et changement pendant un arrosage sont refusés avant toute écriture.
  La zone 1 reste obligatoire et les listes ne proposent pas les vannes déjà affectées.
- **Rangement sans doublon** : Installation conserve les comportements et automatismes ; Entités
  conserve les branchements. Les boutons d'annulation ne touchent qu'aux changements de leur
  propre onglet.
- **Stations météo personnelles détectées** : une station non encore branchée est reconnue à
  partir de ses mesures compatibles, sans liste fermée de marques ou de modèles. Ses capteurs sont
  proposés en priorité dans les fenêtres de choix, mais rien n'est relié automatiquement.
- **Suggestions météo prudentes** : pluie cumulée, pluie du jour et intensité sont distinguées ;
  les rafales, les lux, la batterie et le point de rosée ne sont pas proposés pour un mauvais rôle.
  Une humidité foliaire ne peut plus être confondue avec une humidité du sol.
- **WS90 réelle vérifiée** : l'installation Home Assistant a confirmé les entités Shelly WS90 de
  température, humidité, pression, vent et pluie. Le rayonnement reste fourni par une source en
  W/m², car la luminosité en lux de la WS90 n'est pas interchangeable.
- **Rythme de tonte contextualisé** : en Semis et Sursemis, la page Tonte affiche désormais
  `Rythme actuel` avec le mode concerné au lieu de présenter la fréquence adaptée aux jeunes
  pousses comme une simple cible mensuelle. Le libellé `Ce mois-ci` reste utilisé en mode normal.
- **Bandeau mobile réellement compact** : `En ce moment` utilise une tête resserrée, une seule
  rangée de pastilles glissable et une météo sur une ligne. Les six scénarios de l'aperçu tiennent
  entre 157 et 245 px de haut, y compris l'arrosage actif avec progression et bouton d'arrêt.
  Semis et Sursemis ne répètent plus deux fois le mode et son étape.
- **Typographie adaptée dans tout le panneau** : titres, descriptions, valeurs, onglets, boutons,
  météo, réglages et fenêtres utilisent une hiérarchie plus compacte sur ordinateur, tablette et
  téléphone. Les zones tactiles gardent leur taille et les champs restent à 16 px sur mobile pour
  éviter le zoom automatique. Les identifiants d'entité longs peuvent revenir à la ligne.
- **Profils du gazon plus directs** : les trois longues lignes sont remplacées par un sélecteur
  segmenté compact. Ornement, Jeu et Rustique affichent leur objectif et leur état dans un seul
  bloc ; le profil actif est immédiatement visible et les autres conservent l'action `Appliquer`.
- **Garage de la tondeuse mieux rangé et plus sûr** : les automatismes sont regroupés dans deux
  sous-menus compacts, `Avant le départ` et `Au retour`, avec un résumé permanent des choix. Un
  nouveau seuil sensible, conseillé à 95 %, attend l'ouverture réelle du passage lorsqu'un volet
  publie sa position ; les volets sans position conservent la vérification par état. La recherche
  ouvre automatiquement le sous-menu qui contient le réglage demandé.
- **Double verification locale** : l'onglet et ses fenetres ont ete controles sur ordinateur et
  au format telephone Home Assistant 390 x 844. Les suites completes passent avec **2 132 tests
  et 3 178 sous-tests** sous Pytest, puis **2 104 tests** avec Unittest. Ruff, Mypy sur 53
  fichiers, compilation Python, syntaxe JavaScript, manifeste JSON et `git diff --check` sont
  verts.

## 0.97.17

- **Publications meteo plafonnees sans ralentir le moteur** : les sept capteurs optimises en
  0.97.16 continuent d'etre recalcules a chaque evenement, mais une variation de leurs seuls
  attributs ne republie l'entite qu'une fois par minute, quelle que soit l'origine du recalcul.
  Une modification de l'etat principal ou de la disponibilite reste immediate.
- **Recorder et interface alignes** : l'historique conserve les changements utiles et les
  statistiques, tandis que le panneau recoit au pire une minute plus tard les diagnostics qui ne
  changent aucune decision visible. Les automatismes utilisent toujours le snapshot interne frais.

## 0.97.16

- **Recorder beaucoup moins sollicite sans ralentir les decisions** : les sept capteurs les plus
  bavards conservent leurs attributs complets en direct, mais Home Assistant ne les recopie plus
  dans l'historique a chaque evenement meteo. Leur etat principal et leurs statistiques restent
  enregistres normalement.
- **ETo horaire lisible et stable** : l'entite affiche maintenant le taux a deux decimales. Le
  calcul interne FAO-56 et le bilan du sol conservent toute leur precision ; seule la valeur
  d'affichage/historique est arrondie, avec une erreur maximale de 0,005 mm/h.
- **Perimetre volontairement etroit** : aucun intervalle de calcul, seuil, garde, automatisme,
  dose d'eau ou commande de tondeuse n'est modifie.

## 0.97.15

- **Un départ, puis autonomie constructeur** : après un `start_mowing` accepté, Gazon
  Intelligent ne renvoie plus de commande à chaque recharge. La tondeuse gère seule ses retours
  batterie et ses redéparts jusqu'à la fin du travail.
- **Reprise unique après rappel** : si l'intégration rappelle ce cycle avec `dock` parce que les
  conditions deviennent bloquantes, elle mémorise une reprise due. Quand les sécurités, la
  station et la batterie sont de nouveau prêtes, elle envoie exactement un `start_mowing`, puis
  rend immédiatement la main à l'autonomie de la tondeuse.
- **Pas de fausse responsabilité** : un retour constructeur, une commande seulement observée ou
  un service `dock` refusé ne créent aucune reprise. La dette et le cycle survivent aux
  redémarrages, et la fin est reconnue même si l'inscription automatique des tontes est coupée.
- **Garage compatible** : le volet reste disponible pendant les recharges autonomes. Après un
  rappel de l'intégration, il peut être fermé pendant l'attente puis rouvert et confirmé avant
  l'unique reprise.
- **État visible et réglage expliqué** : la page Tonte distingue départ envoyé, cycle autonome et
  reprise attendue. La page Réglages explique cette répartition des responsabilités dans la carte
  du pilotage automatique.
- **Double vérification** : 64 tests ciblés et 261 sous-tests, puis deux suites complètes de
  **2 118 tests et 3 161 sous-tests**. Ruff, Mypy sur 53 fichiers, compilation Python, syntaxe
  JavaScript, JSON et `git diff --check` sont verts. La carte Réglages a aussi été contrôlée dans
  l'aperçu au format téléphone Home Assistant 390 × 844.

## 0.97.14

- **Ancien travail de tonte correctement rangé** : une tâche inachevée reste « en pause à la
  base » pendant une heure. Au-delà, si la tondeuse est toujours à quai, inactive et sans passe
  en cours, l'état courant redevient « au repos ».
- **Reprise préservée** : la tâche, sa progression et ses minutes restent mémorisées. Le panneau
  les présente séparément comme « Travail précédent · reprise possible », avec la date de mise en
  pause, et une sortie ultérieure reprend le suivi sans créer ni perdre une tonte.
- **Aucune fausse déclaration** : le délai ne transforme jamais une tâche inachevée en travail
  terminé et n'écrit rien dans l'historique de tonte.
- **Double vérification** : 51 tests ciblés et 42 sous-tests, puis deux suites complètes vertes
  (jusqu'à **2 109 tests** et **3 159 sous-tests**), Ruff, Mypy sur 53 fichiers, compilation Python, syntaxe
  JavaScript, JSON et `git diff --check` verts.

## 0.97.13

- **Motif exact en Semis et Sursemis** : le bilan hydrique journalier est désormais présenté
  comme le signal de la surface du semis. Si la réserve profonde est connue, le texte précise
  qu'elle n'est volontairement pas utilisée pour les graines au lieu d'annoncer qu'elle manque.
- **Cause et contexte séparés** : lorsqu'un facteur météo fait réellement monter le niveau, la
  première raison publiée est marquée `Déclencheur` et le bilan de surface devient `Contexte`.
  La tuile affiche ainsi la cause réelle, tandis que le détail conserve l'information hydrique.
- **Calcul inchangé** : aucun seuil, niveau de risque, programme d'arrosage ou automatisme n'est
  modifié par cette correction de traçabilité.
- **Double vérification** : tests ciblés avec cinq familles de risque, puis suite complète de
  **2 085 tests**, Ruff, Mypy sur 53 fichiers, compilation Python, JSON et diff verts.

## 0.97.12

- **Les rafales isolées ne font plus clignoter le risque gazon** : une hausse du palier ET0 doit
  maintenant rester présente pendant deux minutes avant d'entrer dans le score de stress. La
  séquence réelle observée toutes les 10 à 60 secondes reste donc au niveau précédent.
- **Les vraies alertes restent immédiates** : réserve épuisée, chaleur sévère, vent soutenu direct
  et gazon très haut ne passent pas par cette temporisation. Les seuils agronomiques sont inchangés.
- **Mémoire persistante** : le palier candidat et son heure de début survivent aux recalculs et aux
  redémarrages Home Assistant. Une baisse sous le seuil annule immédiatement la candidature, tandis
  que la bande morte de descente existante reste appliquée au palier déjà validé.
- **Double vérification** : 10 scénarios ciblés puis suite complète de **2 081 tests**, Ruff, Mypy
  sur 53 fichiers, compilation Python, JSON et `git diff --check` verts.

## 0.97.11

- **La zone « 5 min » ne dépend plus du navigateur** : le panneau appelle maintenant le service
  persistant `gazon_intelligent.run_zone_for_duration`. Fermer la page ou l'app Home Assistant
  n'annule plus la fermeture programmée de la vanne.
- **Reprise sûre après redémarrage** : la zone temporisée utilise le moteur de sessions
  d'arrosage existant. L'échéance, la zone active et l'eau réellement versée sont persistées ;
  après une interruption, seule la durée restante est exécutée.
- **Pompe facultative protégée** : si la séquence démarre la pompe configurée, elle en conserve la
  responsabilité et l'arrête avec trois tentatives. Une pompe déjà en marche avant le cycle reste
  intacte. Un échec de fermeture pose le verrou de sécurité existant.
- **Arrêt manuel cohérent** : le bouton Arrêter passe aussi par `stop_irrigation`, ce qui annule la
  reprise persistante avant de confirmer la fermeture directe de la vanne.
- **Vérifié deux fois** : 6 tests ciblés dédiés, suite complète de **2 076 tests**, Ruff, Mypy sur
  53 fichiers, syntaxe JavaScript et `git diff --check` verts.

## 0.97.10

- **Textes adaptés à toutes les installations** : la page Gazon, les réglages, les fenêtres,
  les notifications, les erreurs et les conseils ne font plus référence à une personne ni à
  « ton/ta/tes ». Les libellés décrivent désormais le gazon, la tondeuse et les appareils de
  manière neutre. `Mon installation`, `Ma tondeuse`, `Mes arroseurs` et `Mes produits` deviennent
  notamment `Installation`, `Tondeuse`, `Arroseurs` et `Produits enregistrés`.
- **Conseiller Gazon neutre** : les consignes envoyées à l'IA interdisent désormais les noms, le
  tutoiement et les détails personnels absents de l'état fourni. Le contenu factuel, les niveaux
  d'urgence et les actions recommandées restent inchangés.
- **Aucune logique métier modifiée** : cette version ne change ni les calculs d'arrosage et de
  tonte, ni les sécurités, ni les commandes Home Assistant. Les noms d'entités et d'appareils
  restent naturellement ceux définis par chaque installation.
- **Vérifié deux fois** : 250 tests ciblés puis la suite complète de **2 069 tests**, Ruff, Mypy
  sur 53 fichiers, syntaxe JavaScript, JSON et `git diff --check` sont verts. L'aperçu a été
  régénéré et contrôlé sur téléphone Home Assistant 390 × 844 ainsi que sur bureau, sans
  chevauchement ni débordement des nouveaux textes.

## 0.97.9

- **Une tâche inachevée à quai n'est plus présentée comme une tondeuse encore au travail.** Le
  capteur constructeur peut conserver un `task_id` à 0 % après le retour du robot. Quand la
  tondeuse est confirmée à sa base, Gazon Intelligent publie maintenant **Travail en pause à la
  base** au lieu de **Travail pas fini**.
- **Aucune tonte inventée** : cet état reste inachevé et ne peut rien inscrire dans l'historique.
  Si le même travail repart, il repasse en cours ; s'il atteint ensuite réellement 100 %, le suivi
  normal reprend et la durée minimale reste obligatoire.
- **Vérifié** : scénario complet pause à quai → reprise → fin, 47 tests ciblés tondeuse verts,
  mutation volontaire de la condition détectée, suite complète **2 089 tests et 3 144 sous-tests**,
  Ruff, Mypy sur 53 fichiers, syntaxe JavaScript et `git diff --check` verts. Rendu contrôlé sur
  téléphone HA 390 × 844 sans débordement.

## 0.97.8

- **Le créneau qui peut déclencher un départ est maintenant choisi explicitement** dans
  `Réglages > Mon installation > Tondeuse` : `Idéal seulement`, `Idéal ou acceptable`, ou
  `Tout créneau non bloqué`. Le choix conseillé et le repli de sécurité sont **Idéal seulement**
  pour qu'un simple créneau déconseillé ne lance plus une tondeuse automatiquement.
- **Profils cohérents** : appliquer le profil Ornement prépare `Idéal seulement`; les profils Jeu
  et Rustique préparent `Idéal ou acceptable`. Le mode Désactivé/Observation/Actif reste un choix
  séparé : modifier les créneaux n'active jamais le matériel.
- **Retours toujours prioritaires** : le filtre ne concerne que les nouveaux départs. Une tondeuse
  déjà dehors est toujours rappelée si le gazon retire son autorisation, quel que soit le créneau
  choisi.
- **Vérifié** : tests du moteur pur, du câblage coordinateur jusqu'à l'appel Home Assistant, de la
  validation/enregistrement du panneau et des profils. Un créneau acceptable est refusé en mode
  Ornement puis autorisé avec le choix correspondant ; un créneau bloqué ne déclenche jamais.
  Suite complète : **2 088 tests et 3 144 sous-tests**, Ruff, Mypy sur 53 fichiers, JavaScript,
  JSON et `git diff --check` verts. Rendu contrôlé sur ordinateur et téléphone HA 390 × 844.

## 0.97.7

- **Notifications d'activité au choix** : trois nouvelles catégories indépendantes dans
  `Réglages > Mon installation > Alertes et conseils` annoncent le début et la fin d'un arrosage,
  le départ/retour/rangement de la tondeuse et l'ouverture/fermeture confirmée de son garage.
  Elles sont désactivées par défaut pour les installations existantes afin d'éviter des messages
  inattendus après mise à jour.
- **Quantités et erreurs utiles** : la fin d'arrosage indique la quantité réellement exécutée et
  le nombre de segments de zone connus. Une interruption ou une commande tondeuse/garage refusée
  devient une notification de niveau `action` ; les activités normales restent au niveau
  `information` et respectent le niveau minimal et les heures calmes.
- **Pas de doublons au redémarrage** : les derniers identifiants de session et états confirmés sont
  conservés dans la mémoire persistante des alertes. La première observation sert de référence et
  n'annonce jamais une ancienne activité.
- **Vérifié** : tests rouges avant correction, preuve de non-répétition après sérialisation et
  activation tardive, suite complète (**2 083 tests**), Ruff, Mypy sur 53 fichiers, syntaxe
  JavaScript, JSON et `git diff --check` verts.

## 0.97.6

- **Barre “Enregistrer” vraiment masquée quand elle ne sert pas**. La barre du bas était déjà
  descendue hors écran quand il n'y avait aucun changement, mais elle restait présente dans le DOM
  avec son ancien contenu. Sur certains affichages HA/mobile, cela pouvait laisser une bande visible
  ou une zone cliquable en bas de page. Maintenant elle devient aussi invisible, non cliquable et
  masquée à l'accessibilité tant qu'il n'y a rien à enregistrer.
- **Vérifié** : syntaxe JavaScript, test dédié de la barre d'enregistrement, Ruff et
  `git diff --check` verts.

## 0.97.5

- **Garage de tondeuse plus clair dans Réglages**. La carte du volet reste dans
  `Mon installation > Tondeuse`, mais si un volet `cover` est choisi elle affiche maintenant son
  état réel : ouvert, fermé, ouverture/fermeture en cours, indisponible, inconnu ou introuvable.
  Les automatismes sont séparés visuellement : ouverture avant départ, ouverture pour retour,
  fermeture après rentrée, délai avant départ et délai avant fermeture. Sans volet choisi, cette
  partie reste masquée et le garage reste entièrement inactif.
- **Aperçu local** : l'exemple de développement simule un volet de garage fermé pour vérifier le
  rendu complet avant que le matériel réel soit installé.
- **Vérifié** : syntaxe JavaScript, tests panneau ciblés, tests serveur du panneau et tests du
  contrôleur tondeuse/garage verts. La logique de commande n'a pas été modifiée.

## 0.97.4

- **Réglages : seules les valeurs se rafraîchissent**. Le correctif 0.97.3 figeait le bandeau du
  haut, mais Kévin a confirmé que la page bougeait encore. Cause restante : en mode Réglages, chaque
  mise à jour Home Assistant d'une entité suivie reconstruisait toute la page puis remettait le même
  `scrollTop`. Si une carte au-dessus changeait un peu de hauteur, le contenu lu glissait quand même.
  Maintenant, une mise à jour HA passive dans Réglages ne reconstruit plus la page : elle met à jour
  seulement les valeurs visibles des lignes d'entités, la pompe et les entrées météo. La structure,
  les cartes, les onglets, la recherche et la position restent en place. Un changement de thème garde
  volontairement un rendu complet.
- **Vérifié** : syntaxe JavaScript, 74 tests panneau ciblés puis suite complète
  (**2 072 tests**), Ruff Python, Mypy (53 fichiers) et `git diff --check` verts.

## 0.97.3

- **La page de réglages bougeait toute seule** : Kévin — « pourquoi ma page bouge tout seul » puis
  « la page descend petit à petit jusqu'au bas de la page », sur toutes les pages de réglages,
  sans rien toucher. Cause : le bandeau en tête de page (mode, hauteur conseillée, fenêtre,
  soleil...) est nourri par le moteur de décision, recalculé à chaque cycle du coordinateur
  (~2 min) ; à chaque petit changement, sa hauteur bougeait, et comme il est au-dessus de tout le
  reste, ça décalait la page pendant la lecture — cycle après cycle, sans interaction. Ce bandeau
  reste maintenant figé tant que la pelouse chargée ne change pas (au chargement, en changeant de
  pelouse, après une sauvegarde) ; il ne se recalcule plus au fil des rafraîchissements passifs.
  Un test dédié prouve le comportement (et son absence sans le correctif, vérifié par mutation).
- **Vérifié** : 2 070 tests (2 nouveaux), Ruff, Mypy (53 fichiers), syntaxe JavaScript et
  `git diff --check` verts.

## 0.97.2

- **Trois profils de gazon** (au lieu d'un seul) : Kévin voulait plusieurs profils qui changent
  la « Valeur conseillée ». Le raccourci « Gazon d'ornement » devient un choix entre trois profils
  cohérents, chacun ajustant deux leviers agronomiques — la hauteur/fréquence de tonte et la
  confiance dans la pluie annoncée (`arrosage_sensibilite_pluie`) — sans jamais toucher aux
  réglages qui sont des limites physiques (vent, chaleur, humidité, fractionnement de
  l'arrosage) plutôt qu'un style d'entretien :
  - **Gazon d'ornement** (inchangé, toujours le profil conseillé par défaut) : tonte courte
    (4 à 5 cm) et fréquente, sensibilité pluie équilibrée (×1,0).
  - **Gazon de jeu** : tonte un peu plus haute (4,5 à 5,5 cm, densité = résistance au
    piétinement), sensibilité pluie prudente (×1,25) pour ne jamais sous-arroser un gazon qui
    doit encaisser.
  - **Gazon rustique, économe en eau** : tonte nettement plus haute et espacée (5,5 à 7 cm,
    racines profondes), sensibilité pluie économe (×0,75) et rafraîchissement du soir réduit
    (35 °C au lieu de 32 °C, 2 mm au lieu de 3 mm).
  - Chacune des 54 valeurs (18 réglages × 3 profils) est vérifiée par un test dédié contre les
    bornes et le pas réels du registre (`reglages.py`) — pas seulement relue à l'œil.
- **Vérifié** : 2 068 tests (54 nouvelles vérifications de bornes), Ruff, Mypy (53 fichiers),
  syntaxe JavaScript et `git diff --check` verts. Contrôlé à l'écran : les trois profils
  s'appliquent, se désactivent/s'activent correctement selon les valeurs en cours, et
  « Annuler » revient proprement en arrière.

## 0.97.1

- **Mon installation, classée par thème** : Kévin — « range les par groupe, par exemple tondeuse,
  arrosage ». Les cartes de l'onglet (arroseurs, tondeuse, pilotage automatique et son garage,
  capteurs branchés, alertes et notifications) portaient déjà chacune un titre, mais se
  suivaient sans repère commun. Un intitulé de groupe (Arrosage / Tondeuse / Capteurs branchés /
  Alertes et notifications) précède désormais chaque paquet de cartes. La carte « Les
  interrupteurs », qui mélangeait des réglages d'arrosage et de tondeuse, est scindée en deux :
  une par groupe.
- **Noms de zone tronqués sur téléphone** : Kévin — « vérifie l'affichage, le visuel peut être
  mieux sur mobile ». Le graphique « Les 24 dernières heures » de l'accueil affichait « Zone 1
  A… » à 375 px de large (colonne de 70 px face au nom complet de l'entité, ex. « Zone 1
  Arrosage ») — trouvé en parcourant les six onglets de l'accueil sur téléphone. La colonne
  affiche maintenant « Zone 1 », toujours lisible quelle que soit la largeur ; le nom complet
  reste accessible au survol/appui long.
- **Vérifié** : audit visuel complet des six onglets de l'accueil et des sept de Réglages sur
  téléphone (375 × 812) et ordinateur. 2 067 tests, Ruff, Mypy (53 fichiers), syntaxe JavaScript
  et `git diff --check` verts.

## 0.97.0

Nouveautés de l'étape 7 (Codex), revues et complétées par Claude.

- **Pilotage natif de la tondeuse et garage optionnel** (`mower_control.py`) : un moteur pur décide
  d'une unique action, le coordinateur l'exécute selon le mode choisi dans Réglages → Mon
  installation — **Désactivé** (par défaut, aucune commande, comportement actuel strictement
  inchangé), **Observation** (publie la décision sans appeler de service) et **Actif** (exécute une
  seule commande à la fois : `lawn_mower.start_mowing`, `lawn_mower.dock`, `cover.open_cover`,
  `cover.close_cover`). Un rappel n'est demandé que si le **gazon** retire son autorisation ; une
  indisponibilité ou une incertitude machine ne suffit jamais. Un garage électrique facultatif
  (entité `cover`) ajoute trois automatismes indépendants et modifiables séparément — ouvrir avant
  le départ, ouvrir pour le retour, fermer après la rentrée — avec fermeture uniquement sur signal
  fort de station (`docked`/charge), jamais sur un `idle` ou une estimation ; sans volet configuré,
  ce sous-système reste entièrement inerte. Sept nouveaux réglages sensibles (batterie minimale,
  délai anti-double-commande, délais d'ouverture/fermeture du garage).
  **Revue Claude** : un défaut réel a été trouvé et corrigé avant tout déploiement — la fonction
  plantait (`UnboundLocalError`) dès qu'un garage était configuré, la tondeuse fermement à quai, le
  gazon n'autorisant plus de départ, et le garage ni ouvert ni en cours d'ouverture (typiquement un
  garage déjà refermé) ; aucun test ne couvrait ce chemin. Un banc de mutations dédié a ensuite
  trouvé 5 trous de couverture supplémentaires (entité tondeuse invalide, drapeaux
  dehors/retour/tonte non testés indépendamment de l'état brut du cloud constructeur, attente sur
  garage en cours d'ouverture) : les six comblés, **23 mutants sur 23** tués.
  Migration prévue avec Kévin : déployer d'abord Désactivé, observer, puis désactiver les deux
  pilotes Node-RED existants (« Tondeuse Gazon Intelligent », « Tondeuse New ») avant d'activer un
  premier départ/retour surveillé.
- **Profil Gazon d'ornement** : un raccourci prépare les valeurs recommandées pour une pelouse
  soignée, puis attend un clic explicite sur « Enregistrer ». Il ne touche ni aux entités, ni aux
  vannes, ni à la pompe, ni aux protections physiques.
- **Notifications** : le niveau minimal et les heures calmes sont enregistrés ensemble. Les traces
  restent visibles dans Home Assistant même quand le téléphone est filtré ; une urgence critique
  traverse toujours les heures calmes. L'heure locale de Home Assistant (`dt_util.now()`) est
  transmise jusqu'au filtre pour éviter un décalage lié au fuseau du serveur.
- **Rédaction des notifications** : l'ancien choix ambigu « Veille intelligente / Choix manuel »
  est remplacé par « Gazon Intelligent / Conseiller Gazon ». Le premier envoie le texte factuel de
  l'intégration ; le second demande à l'IA de le personnaliser sans changer les faits, le niveau ni
  l'action demandée. Une IA absente, en erreur ou trop lente (délai de 15 s) retombe
  automatiquement sur le message factuel. Les catégories, le niveau minimal, les heures calmes et
  la trace HA restent indépendants du rédacteur.
- **Sensibilité à la pluie prévue** : les trois profils agissent sur les seuils réels du moteur,
  dans `guidance` comme dans la décision directe. La pluie déjà mesurée n'est volontairement pas
  atténuée : 5 mm tombés restent 5 mm quel que soit le profil.
- **Besoins du mode actif** : vérifiés sur Arrosage, Tonte et Gazon pour tous les modes. Le panneau
  réutilise le même état métier et n'ajoute pas de second réglage concurrent.
- **Interface** : profil, sensibilité pluie, niveau de notifications, heures calmes et pilotage
  tondeuse/garage contrôlés à 390 × 844 puis sur bureau, sans chevauchement ni doublon visible.
- **Vérifié** : **2 067 tests** (63 réglages, 21 sensibles), Ruff, Mypy sur **53 fichiers**
  (`mower_control.py`/`mower_control_constants.py` ajoutés au périmètre mypy, oubliés par la
  passe initiale), syntaxe
  JavaScript et `git diff --check`. Six mutations Codex détectées sur le profil d'ornement et la
  rédaction des notifications (urgence masquée la nuit, sensibilité pluie neutralisée, pompe
  introduite dans le profil d'ornement, source IA neutralisée, repli factuel supprimé, filtrage
  exécuté après l'appel IA) + banc dédié de Claude sur `mower_control.py` (23 mutants sur 23,
  après correction du plantage et ajout des 6 tests manquants).

## 0.96.5

2031 tests verts. **Six nouveautés de la même nuit (Codex), revues et complétées par Claude** : le risque fongique tient compte de la durée d'humectation du feuillage, le verrou de sécurité de l'arrosage se lève sans changer de mode, la pastille de tonte est plus claire, la projection de tonte ne recule plus quand une phase de graines est masquée, les notifications ont un niveau minimal et des heures calmes, et un nouveau réglage ajuste la confiance dans la pluie prévue.

### Risque fongique cumulé (Codex)

- Une nouvelle fonction pure (`update_fungal_wetness_state`) suit combien de temps le feuillage reste humide en continu, sans inventer les trous de mesure : un redémarrage de plusieurs heures ne compte pas comme du temps humide, et une lecture « inconnue » casse la continuité plutôt que de la deviner. Douze heures d'humidité continue relèvent la pression fongique, six heures la relèvent un peu.
- Persisté et restauré au redémarrage, comme les deux autres hystérésis du même fichier (`amortir_niveau_risque`, `palier_et0_stress`).

### Lever le verrou de sécurité, séparé du retour au mode Normal (Codex)

- Nouveau bouton et service `clear_irrigation_safety_lock` : après vérification physique des vannes, le verrou se lève sans changer le mode du gazon. Refusé si une zone arrose encore. Avant, la seule façon documentée de lever le verrou était « Retour au mode normal » — un bouton qui change aussi le mode actif, pour un geste qui ne devrait concerner que la sécurité des vannes.
- Deux correctifs de concurrence sur l'arrêt d'arrosage : le statut et l'erreur d'une session s'écrivent maintenant *avant* la première sauvegarde (sinon un redémarrage juste après aurait pu restaurer une session en échec comme terminée) ; l'attente de finalisation lors d'un arrêt est bornée à 30 s et protégée (`asyncio.shield`) — un stockage bloqué ne fait plus pendre l'arrêt, et ne tue jamais la finalisation en cours.

### Tonte : une pastille plus claire, une projection qui ne recule plus (Codex)

- Les deux badges « Gazon permet-il / Machine peut-elle » se lisaient parfois comme contradictoires ; une pastille unique (« pelouse prête / prête avec précaution / à surveiller / tonte à éviter / pas prête ») résume désormais le verdict du gazon, la disponibilité du robot restant un badge séparé.
- Prochaine tonte projetée : quand un Semis ou Sursemis encore actif est temporairement masqué par une phase prioritaire (un Traitement, par exemple), la projection reculait puis avançait de nouveau quand la phase masquée redevenait dominante. Un plancher retient désormais la date que les graines encore actives imposent, même masquées.

### Notifications : niveau minimal et heures calmes (Codex)

- Un niveau minimal (Tout recevoir / Important / Urgences seulement) et des heures calmes filtrent ce qui arrive sur le téléphone, en plus de Veille intelligente / Choix manuel.

### Sensibilité à la pluie prévue (Codex, complété par Claude)

- Nouveau réglage `arrosage_sensibilite_pluie` (Prudente ×1,25 / Équilibrée ×1,0 / Économe ×0,75), qui ajuste les seuils de pluie prévue dans `guidance._rain_signals`. Prudente protège davantage le gazon (il faut plus de pluie annoncée pour reporter l'arrosage) ; Économe fait confiance à la prévision plus tôt, au prix d'un peu plus de risque.
- **Complété** : le réglage était bien câblé mais sans preuve — ni listé dans le test des réglages sensibles, ni couvert par le test qui exige un scénario prouvant qu'il change vraiment la décision (la règle que ce projet impose à chaque réglage). Les deux sont comblés : un scénario à 3,5 mm de pluie montre Économe reporter l'arrosage (« pluie prévue suffisante ») là où le réglage par défaut et Prudente arrosent normalement.

### Vérifié

- 2031 tests (5 nouveaux : 2 côté réglages sensibles/scénario, 2 côté risque fongique, 1 déjà présent), ruff, mypy (51 fichiers), syntaxe JavaScript OK.
- Banc de mutations sur le risque fongique et l'arrêt d'arrosage : 9 mutants sur 11 tués au premier passage ; les 2 survivants (source invalide non testée, palier à 6 h non testé) comblés par les tests ajoutés ci-dessus — 11 sur 11 au second passage.

## 0.96.4

2001 tests verts. **Une recherche pour retrouver un réglage, où qu'il vive.** Kévin, le 18/09 : « dans les réglages, range tout correctement, j'ai du mal à m'y retrouver et à savoir à quoi ça correspond, même si c'est déjà bien fait ».

- **Nouvelle barre de recherche**, visible en haut de la page Réglages quel que soit l'onglet ouvert : tape un mot (« vent », « hauteur », « graines »…) et les réglages qui correspondent apparaissent, chacun avec son chemin complet (« Tonte › Le vent »). Un clic bascule sur le bon onglet, fait défiler jusqu'au réglage et le fait brièvement ressortir.
- Chaque réglage réel de `reglages.py` (55 réglages + le type de sol) est cherchable, y compris ceux qui n'ont pas de section dédiée (le type de sol, propre à l'onglet « Mon installation »). Recherche insensible aux accents et aux majuscules, comme celle qui existait déjà pour brancher une entité météo — même principe, pas une nouvelle idée.
- Le registre lui-même rangeait déjà chaque réglage dans un onglet et une section précise (vérifié : les 55 réglages ont tous leur place, aucun n'atterrit dans un fourre-tout) — c'est la NAVIGATION qui manquait, pas le rangement.
- Vérifié : 2001 tests (11 nouveaux), ruff, mypy (51 fichiers), syntaxe JavaScript OK. Banc de mutations : 10 mutants sur 10 tués (recherche, câblage du clic jusqu'au changement d'onglet, chemin affiché).

## 0.96.3

1990 tests verts. **L'ajustement météo des cycles de graines (Semis et Sursemis) ne clignote plus.** Kévin, le 18/09 : « vérifie la météo avec l'arrosage du mode semis et sursemis, il faut que ça fonctionne comme une horloge, simule tous les scénarios ».

- **Correctif** : `daily_cycles_target`, la dose du cycle et l'espacement entre cycles réagissaient à chaque seuil météo (température, ETP, vent, humidité, pluie de demain) sans aucune marge. Simulé : une prévision qui oscille de ±0,3 °C autour de 28 °C faisait basculer le nombre de cycles cible à chaque lecture, et sautait le prochain cycle annoncé de 75 minutes (12 h 15 ↔ 11 h 00) sans que rien n'ait vraiment changé dehors.
- Même défaut, même remède que l'hystérésis du risque de germination et la bande morte du palier d'ET0 (0.96.1) : entrer dans un état chaud/sec ou humide/frais reste immédiat (un vrai coup de chaleur n'attend pas), mais en sortir demande une marge — sinon la sortie se ferait sur le seuil qui vient de faire entrer, et le clignotement reviendrait par la porte d'à côté.
- Semis et Sursemis partagent le même moteur (`is_seeding_phase`) : le correctif couvre les deux d'un coup. La mémoire d'un cycle à l'autre est portée par le même canal que les deux hystérésis précédentes (`risk_context`), sauvegardée et restaurée aux redémarrages.
- Vérifié : 1990 tests (8 nouveaux), ruff, mypy (51 fichiers) verts. Banc de mutations : 11 mutants sur 11 tués (logique de l'hystérésis, priorité chaud/humide, et chaque maillon du câblage jusqu'au coordinateur).

## 0.96.2

1982 tests verts. **La page dit les besoins du mode actif, pour tous les modes — pas seulement Semis et Sursemis.** Kévin, le 18/09 : « quand je suis en semis ou sursemis ou autre, il faudrait que la page bascule sur les besoins de chaque mode ».

- Le bandeau « En ce moment » et l'intro des Réglages affichaient déjà l'étape, la dose et la fenêtre des graines en Semis/Sursemis. Les **modes produit** (Traitement, Fertilisation, Biostimulant, Agent Mouillant, Scarification) et l'**Hivernage** ont maintenant le même traitement : combien de jours il reste au mode, son besoin propre (« Le foliaire reste au sec », « La pluie prévue peut incorporer »…), et l'état de la tonte.
- **Correctif préalable** : le nombre de jours écoulés et restants d'un mode (`phase_age_days`, `jours_restants`, `date_fin`) était calculé par le moteur mais n'était publié sur aucun capteur — seul l'équivalent pour les graines l'était. Publié sur « Phase dominante ».
- L'Hivernage n'affiche pas de compte de jours (sa durée n'est pas bornée) ; corrigé pour que la fonction elle-même l'empêche, pas seulement son appelant.
- Vérifié : 1982 tests, ruff, mypy (51 fichiers) et syntaxe JavaScript OK. Banc de mutations : 8 mutants sur 8 tués (après avoir couvert un premier survivant en simplifiant une garde redondante dans le code).

## 0.96.1

1974 tests verts. **En Semis et Sursemis, le prochain arrosage est le prochain cycle de graines, ses cycles se répartissent sur toute la fenêtre, et les notifications ont une Veille intelligente.** Kévin, le 17/09 : « je suis en sursemis et il me dit des trucs comme ça : Prochain arrosage : dimanche 20 septembre ».

### Le prochain arrosage des graines (Claude)

- **Correctif** : la date annoncée était l'estimation du régime Normal (les jours avant que la réserve du sol atteigne son seuil, pour un arrosage profond à l'aube). Les graines sont arrosées chaque jour : le prochain cycle partait le lendemain à 8:30. En Semis et Sursemis, l'intégration annonce désormais aujourd'hui tant que des cycles restent à faire dans la fenêtre des graines, sinon demain (`date_prochain_arrosage_estime`). Le régime Normal garde son estimation.
- **Correctif** : le suivi des cycles de graines n'arrivait à aucun capteur. Ses neuf attributs (`semis_followup_state`, `semis_followup_due_at`, `semis_cycles_completed_today`, `semis_cycles_remaining_today`…) étaient calculés pour la décision, mais valaient toujours vide une fois publiés. Ils sont maintenant publiés sur « Fenêtre optimale ».
- **La page** dit où en sont les graines : « Graines : c'est fini pour aujourd'hui. Prochain cycle demain dès 8 h 30 », ou « Prochain cycle de graines vers 12 h 30 (2 cycles faits sur 3) ». L'attente normale entre deux cycles ne s'affiche plus « Bloqué ». Un vrai blocage (vent, pluie, froid) reste affiché comme tel.
- **Aperçu local** : il se remplit avec un relevé réel de Home Assistant (états et attributs, options, réglages, fiches produit, historique des vannes), sans rien qui situe la maison. Les familles d'alertes y sont enregistrées, et « Tout remettre » revient aux réglages de la maison.

### Répartition des cycles et « vrai » prochain arrosage (Codex, relu)

- **Les cycles de graines se répartissent sur toute la fenêtre** au lieu de se tasser au début : le premier part à l'ouverture, le dernier une heure avant la fermeture, les intermédiaires à intervalles réguliers (exemple avec 08:30-16:00 : 2 cycles → 08:30 et 15:00 ; 3 → 08:30, 11:45, 15:00 ; 4 → 08:30, 10:40, 12:50, 15:00). Le minimum agronomique du stade (120 min en germination) reste prioritaire, et le coordinateur comme le capteur « Prochain arrosage » lisent les mêmes créneaux — vérifié que la vraie vanne suit exactement ce que la page annonce, pas seulement l'affichage.
- Une fois les cycles du jour terminés, « Prochain arrosage » affiche désormais la date **et l'heure** du premier créneau du lendemain, recalculées avec les réglages courants, au lieu de retomber sur « Non requis ».
- La page de réglages Graines affiche un aperçu « Départs prévus » qui suit en direct la fenêtre et le nombre de cycles choisis.

### Notifications : Veille intelligente et réglages sensibles (Codex, relu)

- **Veille intelligente** (nouveau, à côté du choix manuel existant) : les quatre familles restent toujours surveillées, mais seules les informations calmes (cycle suspendu ou rattrapé normalement, mesures revenues) restent dans les notifications de Home Assistant sans déranger le téléphone ; un vrai problème (verrou, tondeuse en erreur, cycle manqué, mesures manquantes) part toujours. La partie IA s'appelle désormais **Conseiller Gazon**.
- **13 réglages sensibles** (4 tonte, 5 arrosage, 3 graines, 1 modes) affichent un avertissement sous le curseur ; ce sont de vrais réglages du registre, bornés et testés, pas de simples curseurs visuels. Les invariants de sécurité (verrou de vanne, priorités entre modes, gardes de panne…) restent non réglables.
- **Hystérésis du risque en germination** : le niveau montait et redescendait 73 fois en une nuit sur de minuscules variations de déficit (±0,1 mm). Il monte toujours immédiatement aux seuils agronomiques, mais ne redescend qu'une fois franchement revenu en zone sûre — sans toucher aux vraies alertes (vent fort, stress sévère), qui montent toujours tout de suite.
- **« Tes entrées »** déplacé de l'onglet Météo vers Réglages → Mon installation (une seule copie) ; « Rosée sur l'herbe » précise partout « Ce n'est pas le point de rosée », dans la page comme dans les formulaires Home Assistant.

### Vérifié

- 1974 tests, ruff et mypy verts (51 fichiers), syntaxe JavaScript OK.
- Banc de mutations sur le correctif du prochain arrosage : 23 mutants sur 23 tués (après avoir couvert 4 survivants du premier passage : motif seul, « 4 sur 3 », phrase du bulletin).
- Déployé le 18/09 : après un redémarrage complet de Home Assistant (hors arrosage), page servie identique au local, 62 entités, aucune erreur, un seul avertissement connu (le point de rosée toujours branché). Un capteur avait gardé une valeur d'un précédent redémarrage juste après coup ; un second redémarrage propre l'a remis en phase avec le reste.

## 0.96.0

1940 tests verts. **Les cycles des graines suivent la météo, les alertes se choisissent par famille, l'onglet Modes est refait, et un point de rosée branché sur la rosée est ignoré.** Déployé le 17/09 à la demande de Kévin (« fais ce qu'il faut et déploie »), en pleine germination : cette version change des décisions du moteur.

### Les graines suivent la météo (passe de Codex)

- **Le nombre de cycles réglé est celui d'une météo normale.** Avant, il servait de minimum : la météo pouvait réduire la dose, jamais le nombre de cycles.
  - Temps humide (air à 70 % ou plus), pluie tombée ou annoncée pour le lendemain (plus de 0,5 mm), ou temps frais et peu évaporant (14 °C au plus et évaporation d'au plus 2 mm) : **un cycle de moins**, et une dose réduite.
  - Temps chaud (28 °C, mesurés ou prévus dans la journée), évaporation d'au moins 4 mm, vent d'au moins 12 km/h ou air sec (45 % au plus) : **un cycle de plus**, et une dose plus forte.
  - Toujours dans la limite des créneaux de la fenêtre. La pluie suffisante, le sol humide, le froid de germination et le vent au-delà de la limite gardent leurs blocages.
  - Germination par défaut : 3 cycles en météo normale (de 2 à 4). Avec les réglages de Kévin (4 cycles, ouverture à 8:30) : 4 cycles à 8:30, 10:30, 12:30 et 14:30 ; 3 par temps humide ou frais.
- **Le vent du jardin fait foi** pour les graines et le risque du gazon ; la prévision ne sert que s'il manque. Le 17/09, la prévision annonçait 14,4 km/h contre 3,2 km/h mesurés au jardin.
- **L'espacement se compte depuis le début du cycle précédent**, pas depuis sa fin : un cycle de 10:00 à 10:21 place le suivant à 12:00, et le dernier ne sort plus de la fenêtre.
- **Température minimale d'arrosage après une scarification** : un réglage (12 °C par défaut, de 5 à 20 °C). 55 réglages.

### Les alertes (passe de Codex, relue)

- **Quatre familles, chacune cochable** (Réglages → Mon installation → Alertes et conseils) : arrosage et graines, sécurité de l'arrosage (une vanne qui ne se ferme pas), capteurs et météo, tondeuse. Toutes cochées par défaut. Décochée, une famille retire sa trace et oublie ses retards.
- **Nouvelle alerte « Tondeuse : erreur détectée »**, une fois par code d'erreur, retirée au retour à la normale.
  - Corrigé avant livraison : **une pause pluie n'est pas une panne.** La Landroid publie `rain_delay` sur son capteur d'erreur : sans filtre, chaque averse aurait envoyé l'alerte.
- La page affiche les familles actives dans la carte « Conseils et alertes ».

### L'onglet Modes, refait

- **Les neuf modes sur une rangée**, celui du moment marqué « en ce moment ». L'onglet s'ouvre sur le mode du moment ; toucher un autre mode affiche sa fiche. Normal, Semis et Sursemis y figurent désormais.
- **La fiche du mode** : ce qu'il change, en quelques phrases relues sur `watering_policy.py` et `decision_mowing.py`. Pour un mode lié à un produit, sa durée avec le dessin des jours. Pour Normal, Semis et Sursemis, des raccourcis vers les onglets de leurs réglages.
- **Une carte d'action à côté de la fiche** :
  - pour un mode lié à un produit, « J'ai mis un produit » en premier (la fenêtre s'ouvre sur un produit de ce type), puis « Passer en … sans produit » ;
  - pour les autres modes, « Passer en mode … » ;
  - sur le mode du moment, le jour depuis le semis et « Revenir au mode Normal », avec l'avertissement que le suivi est effacé.
- Les fiches des produits de ce type restent en dessous (passe de Codex). Sur téléphone, les modes tiennent en trois colonnes. Les boutons centrent leur icône avec le texte.
- Relu avant livraison :
  - l'hivernage ne bloque pas l'arrosage automatique **en cas de sécheresse prolongée**, alors que la page le disait toujours bloqué ;
  - la phrase d'un mode ne répète plus ses règles ;
  - « J'ai mis un produit » retrouve un produit dont le type a des espaces autour, comme le catalogue.

### La rosée sur l'herbe

- **Un point de rosée branché sur « Rosée sur l'herbe » est ignoré.** Le moteur lit « au-dessus de 0 = herbe mouillée » : une température y bloquait la tonte pour toujours et gonflait le risque de maladies. Le 17/09, le point de rosée de la station y avait été branché par « Configurer » (vide à 12:06, présent à 15:40) : risque de maladies « modéré » avec « rosée présente », arrosage du soir bloqué, et une tonte qui serait restée bloquée après la levée. La rosée est désormais estimée, et le journal le signale une fois.
- **« Configurer » refuse un point de rosée**, à la création comme dans les options, avec un message dans les cinq langues. Tant qu'il reste dans le champ, le formulaire ne s'enregistre pas : le vider suffit.
- La page le signale « unité inattendue », l'ignore pour « herbe mouillée », et « Changer → Aucune » le retire.

### Vérifié

- 1940 tests, ruff et mypy verts (51 fichiers ; mypy a relevé un conflit de type dans l'alerte tondeuse, corrigé).
- Banc de mutations : 42 mutants sur 42 tués, sur le code final (un 43ᵉ, volontairement introuvable, vérifie que le banc le signale).
- La page et le serveur jugent toujours pareil (475 200 cas), y compris pour ce que le moteur ignore.
- L'onglet Modes est exécuté dans Node par un nouveau test (12 tests, avec le vrai registre et les listes du moteur). 22 mutants de l'onglet, 21 tués : le survivant retire une phrase de règle, que le test ne fige pas.
- Dans l'aperçu local :
  - l'onglet Modes à 1 440 px (neuf modes sur une ligne, page de 839 px), à 664 px (trois colonnes) et sur téléphone en sombre ;
  - les boutons « Revenir au mode Normal » et « J'ai mis un produit », et les raccourcis vers les onglets ;
  - les quatre familles d'alertes ;
  - le point de rosée branché (« unité inattendue », herbe jugée sur l'estimation, retrait par « Aucune »).

## 0.95.0

1892 tests verts. **Les entrées météo et jardin se changent sur la page, et la page ne propose que ce que le moteur sait lire.**

### Changer une entrée sur la page

- **Onglet Météo → « Tes entrées »** : « Changer » (ou « Brancher ») sur chaque ligne, pour les administrateurs. Demandé par Kévin le 17/09.
- La fenêtre ne liste que les entités que l'intégration sait lire. Viennent d'abord celles des appareils déjà branchés, puis celles dont le nom annonce le rôle, puis les autres. Pour chacune : sa valeur, son appareil, et si elle est déjà lue ailleurs. Une recherche par nom prend le relais au-delà de 60 entités. « Aucune » retire une entrée facultative.
- **Les règles**, dans `sources.refus`, revérifiées par le serveur à l'enregistrement :
  - **le domaine** (une entité météo pour l'entité météo, un capteur pour le reste) ;
  - **une unité que le moteur lit ou convertit** : °C ; % ; km/h, m/s, mph, kn ; W/m² ; hPa, mbar, kPa, Pa, bar, inHg, mmHg ; mm ; mm/h ; cm. Des °F seraient lus comme des °C, des kW/m² diviseraient l'évaporation par cinq. Un test relie chaque unité acceptée au convertisseur du moteur ;
  - **une classe d'appareil cohérente** : une batterie en % n'est pas une humidité ;
  - **pour « Pluie en ce moment », une mesure de l'instant** : un cumul dirait « il pleut » toute la journée après une averse. Une unité est exigée : l'indice UV de la station, sans unité et à 2 en plein jour, n'y a pas sa place ;
  - **pour la pluie du jour et le compteur, un cumul**, jamais une mesure de l'instant, la dernière heure ou une prévision ;
  - **un nombre**, quand l'entité donne déjà une valeur (« Pas de pluie » n'en est pas un) ;
  - **un nom qui annonce le rôle** pour la rosée sur l'herbe, la pluie de demain, l'évaporation, la hauteur du gazon et le retour d'arrosage. Un pluviomètre, lui aussi en mm, y reporterait les arrosages, remplacerait l'évaporation ou ferait croire à un arrosage. Même exigence pour l'humidité de l'air et du sol quand l'entité ne déclare pas de classe : le « stress thermique » de la station est en %, sans classe ;
  - **aucun nom qui annonce autre chose** : point de rosée, ressenti, humidex ou sol pour la température ; rafales pour le vent ; sol ou feuillage pour l'humidité de l'air.
- **Toutes ces règles ont été tirées des vrais capteurs de la maison** : à chaque étape, la liste proposée a été relue sur les entités de la station et du Netatmo.
- **Refusé en clair, sans rien écrire** : une entrée inconnue, l'entité météo retirée, une entité absente, une entité de Gazon Intelligent (l'intégration se lirait elle-même), et tout changement **pendant un arrosage**. Le refus s'affiche en tête de la fenêtre, et le choix reste coché.
- Une entité déjà branchée qui ne passerait pas ces règles est signalée « unité inattendue » dans le tableau.
- **Le même résultat que « Configurer »** : options de l'entrée, configuration partagée pour les 12 entrées météo (l'autre pelouse suit), et une entrée retirée l'est aussi de la configuration d'origine, sinon elle y reprendrait sa place. L'intégration se recharge si une entrée surveillée change ; sinon, un cycle part tout de suite.
  - `async_update_config` n'est pas utilisée : elle relance la surveillance du coordinateur pendant que l'écriture des options déclenche son rechargement. Croisés, les deux laisseraient des minuteries sur un coordinateur arrêté.
- Les suggestions « Déjà chez toi » passent les mêmes règles.
- La commande `gazon_intelligent/reglages/set` accepte une clé `entrees` ; la réponse rend `sources`, `appareils`, `meteo` et `recharge`.

### Un pluviomètre remplacé repart de sa propre lecture

- Le suivi du compteur de pluie et celui de la pluie du jour retiennent désormais **le capteur qu'ils suivent**.
- Un autre capteur ne se compare plus au maximum de l'ancien. Plus bas, il ne comptait plus rien tant qu'il ne l'avait pas dépassé : des semaines de pluie perdues pour un compteur qui ne repart jamais à zéro. Plus haut, l'écart était pris pour une averse.
- Sa lecture devient la référence ; le total du jour et la lame d'eau récente restent. Sans référence du tout, rien n'est inventé (« aucune référence = aucun total », PR #49). Un suivi d'avant cette version adopte le capteur du moment, sans rien changer.
- C'est le seul effet de cette version sur le moteur, et seulement quand un capteur de pluie change.

### Vérifié

- 1892 tests, ruff et mypy verts (51 fichiers).
- **La page et le serveur jugent pareil** : un test exécute les règles de la page avec Node sur 475 200 cas (15 entrées × 31 680 profils d'entité) et compare chaque verdict à celui du serveur. Il vérifie aussi que chaque champ lu par la page est servi.
- Banc de mutations : **77 mutants sur 77 tués** : chaque règle, côté serveur et côté page, l'écriture des entrées (ordre du partage, configuration d'origine, rechargement, autre pelouse, arrosage en cours) et les deux suivis de pluie.
- Dans l'aperçu local, avec les vrais capteurs : les listes de chaque entrée, un changement complet (« Un instant… », fenêtre fermée, tableau à jour), le refus pendant un arrosage, la recherche, et l'affichage sur téléphone sans défilement de côté. L'aperçu reprend les règles de la page elle-même, sans copie.

## 0.94.1

1853 tests verts. **La page ne remonte plus toute seule en haut, et l'onglet Météo ne propose plus un point de rosée pour la rosée.**

### Correctifs

- **La page remontait en haut pendant qu'on la faisait défiler** (signalé par Kévin le 17/09).
  - La cause : à chaque mise à jour, la page est redessinée, et les cases neuves n'ont pas encore leur hauteur. Mesuré dans l'onglet Météo : la page tombait de 3 688 à 1 671 px le temps de les mesurer, et le défilement reculait d'autant (de 1 500 à 1 091 px), avant d'être remis en place. Pendant un défilement en cours, cette remise en place ne tenait pas : la page restait en haut.
  - L'onglet Météo, redessiné à chaque relevé de la station, rendait le défaut fréquent.
  - Désormais, la page garde sa hauteur pendant le rendu, et chaque case reprend d'abord la hauteur de celle qu'elle remplace.
  - Une mise à jour qui arrive pendant un défilement attend qu'il soit fini depuis 400 ms, comme elle attendait déjà la fin d'un appui.
- **« Rosée sur l'herbe » n'est pas un point de rosée.**
  - Pour le moteur, cette entrée dit « au-dessus de 0, l'herbe est mouillée » : la tonte attend.
  - La 0.94.0 l'appelait « Point de rosée » et proposait, sur la foi du nom, le point de rosée de la station. C'est une température, 11 °C par exemple : branché, il aurait fait croire l'herbe toujours mouillée, et la tonte ne serait plus partie.
  - Il n'était pas branché. L'entrée s'appelle maintenant « Rosée sur l'herbe », et la page ne propose plus que des capteurs d'humidité du feuillage.
  - Dans l'onglet Météo, le point de rosée affiché est celui de l'entité météo. La ligne « herbe mouillée » suit la règle du moteur : le capteur s'il répond, sinon l'air à 2 °C ou moins de son point de rosée, une humidité d'au moins 88 %, du brouillard ou de la pluie.
  - Le README le précise à côté de `capteur_rosee`.

### Vérifié

- Dans l'aperçu local (Chrome), onglet Météo défilé à 1 500 px : la position ne bouge plus pendant un rendu, et aucun défilement n'est déclenché. Avec une vraie molette et un rendu toutes les 250 ms (44 rendus), la page reste où on l'a mise. Les mises à jour qui arrivent pendant le défilement donnent un seul rendu, après l'arrêt.
- La ligne « herbe mouillée » dans cinq cas : capteur à 1 et à 0, capteur indisponible (estimation), brouillard, air à 1,5 °C de son point de rosée.
- Un test vérifie qu'aucun nom de point de rosée n'est proposé pour la rosée, et que le nom d'un capteur d'humidité du feuillage l'est.

## 0.94.0

1852 tests verts. **Un onglet Météo complet sur la page « Gazon », la pompe qui se choisit sur la page, un délai d'alerte réglable, et une alerte quand une mesure météo manque.**

### L'onglet Météo

- **Un nouvel onglet de l'accueil**, entre Gazon et Produits, qui montre tout ce que l'intégration sait du temps :
  - **au jardin, en ce moment** : température, humidité, vent, pression, rayonnement, point de rosée, UV et nuages. Chaque valeur dit si elle vient du jardin ou de la prévision ;
  - **les prochains jours** (sept jours) et **les prochaines heures** (vingt-quatre heures), demandés à l'entité météo ;
  - **la pluie** : maintenant, aujourd'hui au jardin et sur le second capteur, la dernière pluie mesurée, la part comptée pour le sol, demain et les jours suivants ;
  - **l'évaporation** : celle du jour et sa source, ce que le sol a déjà perdu, celle de l'heure (soleil et pression mesurés ou estimés), celle du gazon (coefficient compris) ;
  - **le vent, la rosée et les maladies** : ce que le vent autorise (arroser les graines, tondre) avec les limites réglées, l'herbe mouillée ou non, le risque de maladies, le stress du gazon ;
  - **ce que l'intégration utilise vraiment** : les voyants de santé, en vert quand la mesure est lue, en orange quand une prévision la remplace.
- **« Tes entrées »** : chaque entité donnée à l'intégration, ce qu'elle lui apporte, sa valeur, son âge et son état (lue, indisponible, introuvable, illisible). Une entrée non branchée dit par quoi elle est remplacée. Si un appareil déjà branché publie de quoi la tenir, la page le signale (par exemple un point de rosée).
- **« Toutes les mesures de tes appareils »** : les appareils de ces entrées, avec toutes leurs mesures, en direct ; celles que l'intégration lit sont en vert. Ni les boutons, ni les entités désactivées, ni ce qui situerait la maison.
- La page suit ces entités en direct seulement quand l'onglet est ouvert.
- Sur téléphone, les mesures passent sur deux colonnes et le tableau des entrées devient une liste, sans défilement de côté.

### La pompe sur la page

- **Réglages → Mon installation → « Ma pompe »** : l'interrupteur de la pompe se choisit dans une liste, ceux dont le nom parle d'une pompe en tête. Ni les vannes ni les interrupteurs de l'intégration n'y figurent.
- Enregistré avec le reste, dans les options de l'entrée (`entite_pompe`). La commande `gazon_intelligent/reglages/set` accepte une clé `pompe` ; sans elle, la pompe ne change pas. Une vanne ou un interrupteur absent est refusé en clair, et rien n'est écrit.

### Les alertes

- **Le délai de l'alerte des graines se règle** : Réglages → Graines → « L'alerte », de 10 minutes à 2 heures (20 minutes par défaut). 54 réglages.
- **Une alerte quand une mesure manque depuis une heure** : chaque entrée qui mesure (entité météo, température, humidité, vent, rayonnement, pression, point de rosée, pluies, humidité du sol, évaporation) est lue au contrôle de 2 minutes.
  - Elle est en panne quand elle n'a pas de valeur utilisable, ou quand aucune mesure de son appareil n'a bougé depuis trois heures : un appareil à piles peut garder sa dernière valeur un jour entier avant d'être déclaré absent.
  - Le message nomme chaque mesure, son appareil et l'heure du début, et dit ce qui la remplace.
  - Une alerte par panne : si la liste change, la trace de Home Assistant suit sans refaire sonner le téléphone ; le retour de toutes les mesures se dit, et la trace part.
  - Une entité introuvable (renommée, supprimée) est datée de la première fois qu'on la constate.
- Comme les autres, cette alerte n'entre dans aucune décision.

### En plus

- `sources.py` : la liste des entrées météo et jardin, leur rôle, ce qu'elles apportent et leur repli, partagée par la page et l'alerte. Un test vérifie qu'elle couvre toutes les entrées de la configuration et que chacune est proposée dans les options.
- Les capteurs d'évaporation (ET0, ETo horaire, ETc) sont lus par la page.

### Vérifié

- 32 nouveaux tests : chaque cas de l'alerte des mesures (délai, liste qui change, retour, entité météo seule ou non, appareil muet), le délai réglé qui déplace l'alerte, la lecture des appareils, les entrées et appareils de la page (entité désactivée, bouton, position exclus), la pompe (tri, refus, clé absente).
- Banc de mutations sur le code de la 0.93.0 et de la 0.94.0 : 79 mutations, toutes tuées. Deux avaient d'abord survécu dans la lecture des appareils ; le test a été renforcé.
- Dans l'aperçu, sur les vraies mesures de la maison (prévisions simulées) : clair et sombre, téléphone, 1 007, 1 184, 1 440 et 1 920 px. L'origine d'une mesure ne sort plus de sa case sur téléphone. La carte des alertes et la pompe tiennent dans Mon installation. La nouvelle carte de l'onglet Graines a été placée pour garder les colonnes d'aplomb.

## 0.93.0

1820 tests verts. **Gazon Intelligent prévient quand un arrosage des graines ne part pas, envoie l'état du gazon sur un téléphone et répond aux questions par l'IA de Home Assistant.**

### Les alertes

- **Un cycle de graines qui ne part pas est signalé.** Si le moteur veut arroser et que rien ne coule 20 minutes après l'heure prévue, un message dit pourquoi :
  - le vent au jardin dépasse la limite réglée (à la limite, le moteur attend déjà) ;
  - l'arrosage automatique est coupé, ou le verrou de sécurité est posé ;
  - la fenêtre des graines a fermé, y compris pour un cycle prévu après sa fermeture ;
  - le lancement a échoué (avec le motif du refus, s'il date de moins de 3 h).
- **Une alerte par cycle, même après un redémarrage** : ce qui a été envoyé est gardé dans l'état persisté. Quand le cycle finit par partir, un second message le dit (« cycle rattrapé ») et la trace de l'alerte est retirée.
- **Le moteur qui renonce n'est pas une panne.** Pluie, sol humide ou froid : une simple information, une fois par jour, sans trace.
- **Le verrou de sécurité est signalé** dès qu'il se pose (une vanne ne s'est pas fermée), avec la vanne et l'erreur. Le message rappelle que le seul déverrouillage, « Retour au mode normal », efface aussi une phase Semis ou Sursemis en cours. La trace disparaît quand le verrou est levé.
- **Une trace dans les notifications de Home Assistant**, avec ou sans téléphone : l'alerte suivante la remplace, et elle est retirée quand le problème est réglé (ou le lendemain).
- **Les alertes n'entrent dans aucune décision** : elles lisent ce que le moteur a décidé, au tick qui lance les arrosages, juste après la tentative de lancement. Une panne dans leur calcul est journalisée et ne retient jamais un arrosage.

### Les actions

- **`gazon_intelligent.send_notification`** : un message aux téléphones choisis. Sans message, l'état du gazon : phase, cycles de graines, moment conseillé, arrosage automatique, réserve, météo, tonte, semis, dernier produit, risque et conseil du moteur. L'action rend le texte envoyé et les téléphones joints ; un téléphone injoignable n'empêche pas les autres.
- **`gazon_intelligent.ask_ai`** : une question à l'IA de Home Assistant (action « Générer des données »), accompagnée de l'état du gazon. L'IA répond en texte et ne commande rien. La réponse peut aussi partir sur les téléphones, et l'action la rend.
  - L'IA utilisée : celle des options, sinon la seule de la maison, sinon celle que Home Assistant préfère.
  - Aucun appel ne part tout seul : chaque question compte auprès du fournisseur d'IA. Délai maximal : 90 s.
  - La consigne interdit d'inventer ou de prétendre avoir agi. Aucune coordonnée ni aucun nom de lieu n'est envoyé.
- Les deux actions rendent leur résultat à qui le demande (`response_variable`, outils de développement) et restent appelables sans. 17 actions au total.

### Les réglages

- **Sur la page « Gazon » : Réglages → Mon installation → « Alertes et conseils »**, une carte pleine largeur avec trois réglages :
  - prévenir ou non (alertes automatiques, allumées par défaut) ;
  - les téléphones à prévenir, parmi les appareils à notifier de Home Assistant (plusieurs possibles) ;
  - l'IA des conseils, parmi les entités `ai_task`, ou « Automatique ».
- Ils suivent le même « Enregistrer » que les autres réglages, dans le même envoi.
  - La commande `gazon_intelligent/reglages/set` accepte une clé `notifications`. Seules les clés envoyées changent.
  - Un téléphone ou une IA qui n'existe plus est refusé en clair, et rien n'est écrit, réglages compris.
- **Les mêmes réglages dans les options de l'intégration** (Configurer) : les deux chemins écrivent au même endroit. Vider un champ le retire. Libellés en cinq langues.
- Ils s'appliquent sans recharger l'intégration.

### La page « Gazon »

- **Onglet Gazon, carte « Conseils et alertes »** : où partent les alertes, quelle IA répond, et deux boutons. Elle renvoie vers les réglages ci-dessus.
  - « Demander conseil à l'IA » ouvre une fenêtre : la question (trois questions proposées), l'envoi sur le téléphone, puis la réponse, qui reste affichée. L'envoi et les erreurs sont dits dans la fenêtre, pas dans un message qui passerait dessous.
  - « Envoyer l'état sur mon téléphone », quand un téléphone est choisi.
- Vérifié dans l'aperçu : clair et sombre, téléphone (375 × 812), 1 184, 1 440 et 1 920 px.
  - Onglet Gazon : les deux colonnes finissent à 52 px l'une de l'autre au plus.
  - Mon installation : la carte des alertes en bas, sur toute la largeur. Dans une colonne, elle allongeait la page de 450 px.
  - Sur téléphone, les questions proposées passent à la ligne au lieu de sortir de la fenêtre.
- L'onglet « Mon installation » se présente désormais ainsi : « Tes arroseurs, ta tondeuse, les interrupteurs et les alertes ».

### Documentation

- Le README liste les deux nouvelles actions, et `reset_mower_passes`, qui manquait au tableau.

### Vérifié

- 76 nouveaux tests : chaque motif d'alerte, le délai de 20 min à la seconde près, le rattrapage, la journée suivante, le verrou, la mémoire qui traverse le disque (les deux listes blanches), le réglage de vent de la page réellement lu, l'isolement d'une panne, les deux actions et leurs champs, les options, et l'écriture des alertes par la page (refus compris).
- Banc de mutations sur le nouveau code : 47 mutants sur 47 tués.
- Dans l'aperçu : poser une question, cocher « Envoyer sur mon téléphone », une erreur du fournisseur, « Envoyer l'état », enregistrer puis annuler un choix, un téléphone disparu.

## 0.92.1

1744 tests verts. **Les fenêtres de la page « Gazon » défilent quand leur contenu est plus haut que l'écran.**

### Corrigé

- **Une fenêtre trop haute était coupée, sans défilement.** Sur téléphone, « Changer de mode » et la fiche d'un produit à modifier cachaient leur bouton de validation.
  - La cause : le formulaire, seul enfant de la fenêtre, gardait la hauteur de son contenu. La fenêtre le coupait et son corps ne défilait jamais.
  - Désormais, le formulaire est borné à la hauteur de la fenêtre : le corps défile entre l'en-tête et les boutons, qui restent visibles.
- **Les blocs d'une fenêtre ne se laissent plus écraser.** Le plan des zones de « Arroser » ne montrait plus que la zone A quand la fenêtre était bornée. C'est le corps qui défile, jamais ses blocs qui rétrécissent.
- La hauteur maximale suit la partie réellement visible de l'écran (`dvh`) quand le navigateur la connaît.

### Vérifié

- Les 12 fenêtres (la fiche produit en ajout et en modification), mesurées dans l'aperçu sur des écrans de 320 × 568, 375 × 667, 375 × 812 et 860 × 650, puis avec une hauteur maximale forcée à 343, 300 et 250 px, dans les six scénarios.
  - Aucune n'est coupée ni écrasée.
  - L'en-tête et le bouton de validation restent visibles.
  - La fin du corps est atteinte en le faisant défiler.
- Le contrôle repère bien l'ancien défaut quand on le remet sur un bloc : 130 px affichés pour 182.
- Le numéro de version change l'adresse du fichier de la page (`?v=`) : un navigateur ne garde pas l'ancienne fenêtre.

## 0.92.0

1744 tests verts. **La page « Gazon » : une base de contrôle et 53 réglages que le moteur applique vraiment, instance par instance.**

### La page

- **Dans la barre latérale** (« Gazon »), activée par une case des options de l'intégration, cochée par défaut. Elle disparaît quand plus aucune instance chargée ne la veut.
- **Accueil** : tout ce que montre la carte (bulletin, arrosage, tonte, gazon, produits), avec les actions. Le plan d'arrosage y est calculé comme le moteur l'exécute, à la seconde.
- **Réglages** : 53 réglages en sept onglets (tonte, arrosage, graines, sursemis, semis, modes, installation), le type de terre et le catalogue de produits (ajouter, modifier, retirer). Chaque réglage a une question simple, sa valeur conseillée et un bouton « Revenir ». Rien ne s'applique avant « Enregistrer ».
- **Une commande WebSocket** (`gazon_intelligent/reglages/get` et `…/set`). L'écriture est réservée aux administrateurs.
  - Elle refuse en clair une valeur hors bornes, hors pas ou contradictoire, jugée contre les autres réglages ENREGISTRÉS.
  - Elle n'enregistre que ce qui diffère du conseil, dans les options de l'entrée, puis relance un cycle : aucun redémarrage n'est nécessaire.
- **Les noms des zones sont ceux des entités de vannes** : les renommer dans Home Assistant renomme la zone sur la page. La **pompe**, que l'intégration ne pilote pas, se choisit dans les options (facultatif).

### Le branchement

- **Chaque instance lit ses propres réglages.** Le coordinateur les relit dans les options à chaque cycle, écarte une valeur devenue invalide (le moteur reprend alors sa constante) et les confie au `GazonBrain`, qui les pose sur le contexte de décision.
  - Chaque module les lit à la place de sa constante : phases, arrosage, graines, tonte, et, dans le coordinateur, la marge avant le lever, le délai de relance et les créneaux des graines.
  - **Sans réglage, rien ne change** : les 1 653 tests d'avant passent tels quels.
- **Trois valeurs écrites en dur suivent maintenant leur réglage** :
  - le seuil de 8 °C de la germination ;
  - le vent de 15 km/h des graines, désormais nommé `SEMIS_VENT_MAX_KMH` ;
  - le J+25 de la reprise d'un semis.
- **La durée du suivi des graines n'a plus trois copies** : `decision_mowing._SEMIS_DUREE_JOURS` est retiré et la tonte lit la durée de la phase.
- **Les créneaux des graines suivent l'heure d'ouverture réglée.** Un créneau qui tomberait après la fermeture est retiré. Pour la même raison, l'enracinement et la reprise ont 2 arrosages par jour au plus, puisqu'un troisième tomberait après 17 h.
- **Le libellé du rythme de tonte suit le chiffre réglé** (« 1 / semaine »). Un mois non touché garde son texte.
- **Une fin de fenêtre des graines plus tardive n'invente pas de plafond à 17 h** : seul le plafond de 16 h des jours de pluie, de forte chaleur ou de vent fort reste écrit en dur.

### Corrigé en route

- **La pause entre deux passages ignorait la règle du 29/07.** En mode Normal, le bundle d'arrosage réécrivait « 25 min dès deux passages ». Le calcul du profil, qui ne pose la pause qu'à partir de 10 mm, était donc perdu.
  - Conséquence : un petit arrosage coupé en deux par le budget hebdomadaire attendait 25 minutes pour rien.
  - Désormais, la pause publiée et exécutée est celle du profil.

### Tests

- 91 tests ajoutés :
  - `test_reglages_branches.py` change chaque réglage et vérifie que la DÉCISION change, par le chemin de production ;
  - `test_panneau.py` couvre la commande et le panneau ;
  - trois tests du coordinateur couvrent la marge avant le lever, le délai de relance et les créneaux des graines ;
  - un autre suit les réglages de l'entrée jusqu'au cerveau.
- **Mutations** : 79 points de passage des réglages ont été retirés ou remplacés un à un, sur une copie du dépôt. La suite les a tous détectés.

## 0.91.0

1622 tests verts. **Deux modes de semis : « Semis » sur terrain nu, « Sursemis » dans un gazon déjà installé, où la tonte reprend après la levée.**

### Pourquoi deux modes

- **La question de Kévin (16/09/2026).** « Pour le sursemis, la pelouse déjà implantée continue à pousser. » Le mode Sursemis traitait pourtant tout le gazon comme un semis sur terrain nu :
  - tonte interdite 25 jours ;
  - pousse estimée nulle ;
  - hauteur plancher de 7,5 cm.
- **Ce que ça donnait** : un gazon en place coupé à 3 cm le jour du semis approchait 10 cm vingt-cinq jours plus tard, pendant que l'intégration le croyait toujours à 3 cm. Sa première coupe aurait enlevé bien plus du tiers.
- **Ce que disent les sources** (vérifiées) : aucune source universitaire lue ne suspend la tonte après un sursemis.
  - Purdue (AY-13-W) : « Mow frequently to limit the competition from the established turf. Mow at 1.5 inches until new seedlings have been cut at least two times. » Ensuite, remonter la lame par paliers.
  - UMass : arroser le sursemis « in the same manner as for new seedings ».

### Semis — terrain nu

- **L'ancien comportement du Sursemis, à l'identique, sous un nouveau nom** : tonte interdite jusqu'à J+24, pousse nulle, planchers 7,5 → 7,0 → 6,5 → 5,0 cm, prochaine tonte annoncée au semis + 25 jours.
- Nouvelle option « Semis » dans le sélecteur de mode, `set_mode`, `declare_intervention` et la compatibilité des produits. Traduite en cinq langues.

### Sursemis — gazon en place

- **Arrosage des graines : inchangé**, identique au Semis. Mêmes micro-cycles (1,5 mm × 3 en germination à 10 h, 12 h et 14 h), mêmes conditions, même fenêtre de 10 h à 17 h. Tout ce qui concerne les graines teste désormais `phases.is_seeding_phase` :
  - le programme de micro-cycles et l'arrosage automatique ;
  - le Kc et le seuil MAD ;
  - le fractionnement ;
  - le risque et l'urgence ;
  - les scores hydrique et de stress.
- **Tonte suspendue pendant la levée (J0 à J7)** : les graines ne sont pas ancrées et la surface reste détrempée. C'est un choix prudent, qu'aucune source ne chiffre. Le code public reste `phase_sursemis`, connu de Node-RED et de la carte, et la prochaine tonte est annoncée à J+8.
- **Ensuite, la tonte est permise** :
  - fréquence visée de 1 à 2 par semaine ;
  - au moins 5 jours d'écart entre deux tontes (0,35 cm/j en septembre, soit environ 6 jours pour passer de 4 à 6 cm) ;
  - seuil de score assoupli à 65, comme la reprise d'un semis.
- **Le gazon en place pousse au rythme du mois** : 0,35 cm/j en septembre, 0,25 cm/j en octobre.
- **Hauteur conseillée** : 4,0 cm (Purdue : 1,5 in), puis 4,5 cm après deux coupes des plantules (arbitrage de Kévin). Cette consigne remplace la hauteur du mois, bonus de phase et de chaleur compris. Seule la règle du tiers peut la relever.
- **Score de tonte** : le Sursemis prend le bonus ordinaire des phases (+18) au lieu de +45. Avec +45, une journée ordinaire de sursemis dépassait le seuil : la tonte, autorisée sur le papier, aurait été refusée par le score.
- **Statut « interdite »** : seulement pendant la levée. Après, un refus vient de la météo ou du gazon, et le statut le dit.
- **Transition de l'arrosage** (en Reprise) : en sursemis, seules comptent les tontes qui coupent des plantules, à partir de leur première coupe. Les tontes du gazon en place, dès J8, ne disent rien de leur installation.

### Suivi des plantules — les deux modes

- **Sur le capteur « Hauteur de tonte conseillée »** : `semis_mode`, `semis_age_jours`, `plantules_levee_date`, `plantules_hauteur_estimee_cm`, `plantules_premiere_coupe_date` et `plantules_coupes`.
- **Calendrier partagé** (`phases.py`) :
  - levée à J+7, pour le ray-grass anglais du mélange semé (UC IPM : 5 à 10 jours ; fétuque rouge : 7 à 14 jours) ;
  - puis 0,4 cm/j ;
  - première coupe à 6 cm, soit une fois et demie la lame (UC IPM) : J+22.
  - ⚠️ La vitesse de pousse des plantules est une **estimation** : les sources ne publient que des délais de première tonte (18 à 21 jours chez Team Green, 3 à 6 semaines chez DLF).
- **Une tonte déclarée à partir de la date de première coupe compte comme une coupe des plantules.**

### Au passage

- **Fenêtre d'arrosage affichée pendant un semis** : les jours où le cycle de surface était bloqué (froid, pluie), les capteurs publiaient la fenêtre du matin standard, 03:45 → 10:00, alors qu'aucun arrosage n'a lieu à l'aube en semis. Les sorties anticipées de `compute_action_guidance` (pluie active, objectif nul) gardaient les bornes du matin. Elles prennent désormais celles du semis dès le début du calcul : 10:00 → 17:00, ou 16:00 après une pluie. Constaté en vérifiant une analyse transmise par Kévin.
- Le message d'espacement entre deux tontes disait « laisse un jour de repos » quel que soit l'écart réel. Il donne maintenant le nombre de jours et la date.

### Tests

- 19 tests ajoutés, dont un qui suit les six attributs des plantules du moteur jusqu'au capteur, et un pour la fenêtre publiée un jour bloqué (sol nu et sursemis, froid et pluie).
- Les tests de l'ancien comportement passent sur le mode Semis.
- **20 mutations, toutes détectées** :
  - levée débloquée, raccourcie ou allongée ;
  - sursemis bloqué comme un semis ;
  - pousse nulle ;
  - espacement de 2 jours ;
  - consigne ignorée ;
  - remontée après une seule coupe ;
  - tontes comptées dès le semis ;
  - bonus de +45 rendu ;
  - statut « interdite » à tout refus ;
  - arrosage réservé au sursemis ;
  - attribut non recopié ;
  - projection à 25 jours ;
  - seuil assoupli retiré ;
  - plancher du sol nu appliqué ;
  - transition sur toutes les tontes ;
  - pousse des plantules ignorée ;
  - fréquence du mois ;
  - bornes du matin rendues aux semis.

### Laissé ouvert

- **Mesure à la règle des plantules**, pour recaler l'estimation : proposée, pas encore faite.
- **Azote** : ne pas en rajouter avant environ 4 semaines après la levée (Minnesota, Purdue). La recommandation d'intervention ne le dit pas encore.
- **Carte** : les attributs des plantules ne sont pas encore affichés.

## 0.90.0

1603 tests verts. **L'arrosage du matin finit 15 min avant le lever du soleil, la tonte se décale plus tard dans des fenêtres élargies, et l'heure du prochain lancement s'affiche.**

### Partir pour finir avant le lever, plus partir à 03:45

- **Étape 2 de la recommandation sur l'humidité.** Arbitrage de Kévin, 15/09/2026. Les sources agronomiques recommandent d'arroser juste avant le lever du soleil : l'eau tombe sur la rosée, et le feuillage sèche dans la journée.
- **Le problème.** L'arrosage partait dès l'ouverture de la fenêtre (03:45) et finissait vers 04:50, bien avant l'aube. La nuit, l'évapotranspiration est quasi nulle : partir plus tard ne coûte rien au sol.
- **La règle** (`coordinator_irrigation.plan_morning_departure`) :
  - la fin visée est **15 min avant le lever du soleil** ;
  - le départ ne précède **jamais l'ouverture de la fenêtre** : un cycle trop long pour tenir part à 03:45 et finit plus tard ;
  - la durée compte les **pauses entre passages** et la **minute entamée** (66,5 min comptent pour 67).
- **Exemple.** Lever 07:34, cycle de 63,5 min : départ 06:15, fin 07:19.
- **Pas de plafond lié à la tonte.** Un premier jet, jamais déployé, finissait au plus tard à 07:00 pour que le délai de reprise de 180 min tombe à 10:00. La prémisse était fausse : après ce délai, le ressuyage estimé retient encore la tonte, 4 à 6 h après la fin de l'arrosage en sol limoneux (5 h le 11/09, près de 4 h le 13/09 : fin 09:59, tonte autorisée à 13:45, relevés sur l'installation). Kévin a choisi de **tondre plus tard** et d'élargir les fenêtres de tonte.
- **Sans lever du soleil connu** (`sun.sun` absent), l'arrosage part à l'ouverture, comme avant.
- **Exemptés, au lancement comme à l'affichage** : le semis (cycles espacés), l'incorporation post-produit, le rafraîchissement du soir et la détresse tondeuse. Ils vivent dans une seule condition (`_morning_departure_exempt`). Avant, la publication les ignorait : un semis qui part à l'ouverture se voyait annoncer un départ calé.
- **Latence mesurée.** La marge de 15 min couvre surtout le retard au lancement (jusqu'à 2 min) et un objectif qui monte pendant l'attente. Les vannes, elles, ne rallongent un cycle que de 0,3 s.

### Tonte : des fenêtres plus larges

- **Fenêtre idéale : 10:00 → 14:00** (au lieu de 12:00).
- **Fenêtre du soir : de 5 h avant le coucher jusqu'au coucher + 30 min** (au lieu de coucher − 4 h 30 → coucher − 1 h 30). Coucher à 20:12 : 15:12 → 20:42 ; en juillet : environ 16:45 → 22:15.
- **La nuit de la tonte commence au coucher + 30 min**, pas au coucher. C'est la fin du crépuscule civil, qui dure en France métropolitaine de 28 min (sud, équinoxes) à 47 min (nord, juin). La fenêtre et le motif de blocage lisent la même nuit (`_est_la_nuit`), sinon la fenêtre dirait « acceptable » pendant que `tonte_autorisee` retomberait.
- **La fin du soir est la dernière minute autorisée**, pas une heure de départ. Ensuite `tonte_autorisee` retombe, et une automatisation qui rappelle le robot à ce signal le fait rentrer.
- **Le prix assumé.** L'ancienne fin gardait 90 min de séchage avant la nuit ; une herbe coupée tard reste humide plus longtemps.
- **Frontières à la minute.** Les bornes calculées depuis le coucher se comparent en minutes entières, arrondies : remultipliée par 60, l'heure décimale n'est pas exacte (`(16 + 35 / 60) * 60` vaut 994,999…), et la frontière glissait d'une minute pour certains couchers.
- **Prochaine tonte après la nuit du soir.** Le seuil « demain » valait 22 h : entre la tombée de la nuit et 22 h, la prochaine tonte était annoncée pour le jour même. Il vaut désormais midi.
- **Inchangé** : le repli 17:00 → 19:00 quand le coucher est inconnu, et la garde « matin trop tôt » avant 10:00.

### Ce qui s'affiche

- **« Blocage arrosage auto »** : pendant l'attente, « Départ calé sur le lever du soleil », avec `depart_prevu` et `fin_prevue`. Ce n'est pas un refus : rien n'est consigné dans les refus du jour.
- **« Prochain arrosage »** : `target_datetime` devient l'heure de départ calée, et le résumé devient « Arrosage prévu demain matin à 06:15, fin vers 07:19 ». Nouveaux attributs `departure_time` et `end_time`, calculés par la même fonction que le lanceur.
  - **Pendant l'attente aussi.** La décision publie `maintenant` dès 03:45 : l'heure disparaissait au moment précis où l'arrosage l'attendait.
  - **Jamais pour une matinée passée.** Le soir, la fenêtre repasse parfois sur `ce_matin` avec la date du jour (relevé le 10/09 à 18:12) : seul un départ à venir, aujourd'hui ou demain, est annoncé.
  - **Le jour se lit sur la date**, plus sur le nom de la fenêtre : la veille au soir, « demain matin ».
- **Carte 0.30.0** : la tuile « Prochain arrosage » affiche « 06:15 → 07:19 », et l'onglet Arrosage « Demain · départ 06:15 · fin vers 07:19 ».

### Tests

- **Fonction pure** : lever − 15, plus de plafond, été, ouverture jamais précédée, minute entamée sur le cycle réel de 3990 s (un arrondi au plus proche donne 66), marge négative, lever inconnu.
- **Lanceur**, sur le vrai `_should_launch_auto_irrigation` avec le lever lu par la vraie façade soleil : frontière exacte 06:54/06:55, pause comptée, délai de tonte sans effet, plan de l'entité prioritaire, cycle trop long annoncé à l'ouverture, exemptions au lancement et à la publication, attente non tracée comme un refus.
- **Capteurs** : la veille au soir, pendant l'attente, départ passé, au-delà de demain, repli sans départ.
- **Tonte** : idéale 10:00/14:00, ouverture du soir, fermeture au coucher + 30 min, juillet après 22 h, décembre, petit matin, soleil couché sans coucher connu, état du soleil absent, coucher aberrant, `tonte_autorisee` jusqu'à la fin de la fenêtre, prochaine tonte après la nuit du soir, frontières à la minute.
- **Preuve.** Sur le code d'avant (premier jet plafonné à 07:00), 42 de ces tests échouent. 50 mutations, toutes détectées, dont les 5 qui survivaient à la revue indépendante.

### Revue indépendante : corrigé avant tout déploiement

- **La veille du passage à l'heure d'été, la tonte restait autorisée environ une heure dans le noir.** Une fois le soleil couché, `next_setting` désigne le coucher du LENDEMAIN, lu à l'heure du lendemain : la veille d'un changement d'heure, il saute d'une heure. La nuit de la tonte (coucher + 30 min) tombait donc une heure trop tard avant l'heure d'été, une minute après le coucher avant l'heure d'hiver. Le coucher publié est désormais celui DU JOUR : `next_setting` reculé de 24 h en UTC, à une ou deux minutes près (`coordinator_weather.sunset_today_minute_from_context`). Il sert aussi au rafraîchissement du soir, au risque et à la fraction d'ET écoulée, qui y gagnent la même justesse.
- **Une heure de départ était annoncée alors que l'arrosage automatique ne partirait pas** : verrou de sécurité actif, interrupteur coupé, arrosage auto non autorisé (post-produit en mode manuel), exécution refusée, fenêtre « attendre ». « Prochain arrosage » et la carte disaient « 06:15 → 07:19 » pendant que « Blocage arrosage auto » disait « Bloqué (sécurité) ». La publication passe par les mêmes refus durables que le lanceur (`_auto_irrigation_can_start`).
- **Le soir, la cible changeait de date d'une lecture à l'autre, et avec elle l'heure affichée.** `_profile_for_normal` publiait `ce_matin`, avec la date du jour, tout l'après-midi et le soir ; le risk bundle disait `demain_matin`, sauf quand il proposait « soir », où l'arbitrage reprenait le profil. Relevé le 07/09 : « ce matin (07/09) » à 18:01, « demain matin (08/09) » à 18:02:39, retour à 18:02:50. Passé la fenêtre du matin, le profil Normal et le profil agronomique publient désormais `demain_matin`, comme le faisait déjà `compute_action_guidance`.
- **Les tests du départ calé tournaient sur une fenêtre qui n'existe pas** (`matin`). Ils utilisent la vraie valeur, `maintenant` : un lanceur qui n'attendrait plus sur `maintenant` passait tous les tests.
- **Carte** : le soir d'un changement d'heure, « Demain » s'affichait comme une date (voir carte 0.30.0).
- **Deux affirmations fausses corrigées** dans les commentaires : la cause de l'arrondi à la minute (voir plus haut) et la durée du crépuscule civil.

### Fin de cycle et arrêt manuel (Codex, points D1, C10, C11 de la revue du 15/09)

- **Une session dont l'eau est déjà enregistrée est close, même s'il reste un segment en attente** (`coordinator_runtime.is_finished_irrigation_session`). Un segment « zombie » (zone jugée finie pendant une coupure, segment de durée nulle) gardait la session active, et un arrêt ou une reprise réenregistrait l'eau. La garde « zone active » reste prioritaire : le marqueur ne clôt jamais une session dont une vanne tourne.
- **Clôturée « terminée », pas « échouée »**, quand l'eau est enregistrée, même si la reprise a laissé `last_error = restart_recovery`.
- **Arrêt manuel : une seule sauvegarde efface la session ET inscrit l'eau déjà versée.**
  - **Ordre d'origine** : l'eau d'abord, puis la session effacée. Un redémarrage entre les deux reprenait la session et rouvrait les vannes restantes.
  - **Premier correctif (Codex)** : la session effacée d'abord, puis l'eau. Plus de vanne rouverte, mais un redémarrage entre les deux sauvegardes perdait l'eau de l'arrêt.
  - **Désormais** : la session est effacée en mémoire, puis `async_record_watering` écrit l'historique et le runtime dans la même sauvegarde. Sans eau, la session effacée est sauvée seule. Si l'écriture de l'eau lève une exception, l'arrêt est sauvé quand même avant de remonter l'erreur : le disque ne garde jamais un cycle que la reprise relancerait.
- **Preuves disque** : des tests avec le vrai cerveau, le vrai enregistrement et la vraie sauvegarde vérifient chaque écriture. Pour le marqueur : jamais le marqueur sans l'eau, ni l'eau d'une session active sans le marqueur. Pour l'arrêt : jamais une session active avec l'eau de l'arrêt, ni une session effacée sans cette eau.
- Mutations : 6 sur 7 à la passe de Codex. La survivante, la clôture « terminée » au redémarrage (`_restore_active_irrigation_session`), est épinglée depuis. Les quatre mutations de la sauvegarde unique sont détectées : les deux anciens ordres, l'arrêt sans eau et l'écriture en échec.

### Reprises après redémarrage (Codex, points D2, D3, D4, C12 de la revue du 15/09)

- **Une reprise qui échoue n'efface plus l'eau déjà versée.** Plan illisible, vannes indisponibles, verrou de sécurité, arrosage automatique coupé, vanne impossible à fermer : l'eau des zones déjà jouées est inscrite avant de clore la session (`_close_degraded_irrigation_session`). Quand une vanne ne ferme pas, le verrou de sécurité reste posé.
- **Affirmation fausse de la revue, corrigée.** La vanne impossible à fermer ne laissait pas de « session fantôme qui refusait tout lancement ». `_safe_turn_off_zone` passe la session en « échouée », et la lecture suivante la ferme. Tant que la vanne coule, un arrosage est bien vu en cours, et c'est voulu. Le vrai défaut était l'eau des zones déjà jouées, jamais inscrite : vérifié en exécutant l'ancien code.
- **L'eau versée pendant la coupure est comptée.** Une zone qui a fini pendant que Home Assistant était arrêté passe dans les zones jouées, et son segment quitte la file d'attente. Une zone reprise est créditée pour tout son temps d'ouverture, avant et après le redémarrage, sans dépasser la dose prévue.
- **Un post-produit automatique ne repart plus au redémarrage quand l'arrosage automatique est coupé**, comme le lanceur le refusait déjà.
- **Arrêt pendant l'enregistrement de fin de cycle** : l'arrêt laisse la fin de cycle se terminer et annonce la vraie lame, au lieu de « 0,0 mm » ; l'événement de fin et le délai de relance restent armés.
- Mutations : 9 sur 9 détectées. Au départ 5 sur 9 : quatre tests ajoutés épinglent le segment retiré de la file d'attente, le marqueur posé avant l'écriture, la garde « eau déjà enregistrée » de la reprise dégradée et l'eau inscrite après un échec de fermeture.
- **La suite repasse de 62 s à 3 s** : le test des vannes indisponibles attendait le vrai délai de 60 s de `_wait_for_zones_available`. Le verdict de cette attente reste testé, avec un délai court.

### Le cinquième verrou de l'humidité de l'air

- **Un matin humide bloquait encore l'arrosage en phase Scarification.** La 0.89.0 annonce « quatre verrous, pas un » et cite les phases agronomiques, scarification comprise. Il en restait un cinquième, propre à cette phase : `guidance._scarification_soil_humidity_state` renvoyait « trop_humide » dès **85 % d'humidité de l'AIR**, la politique Scarification exige un sol `legerement_humide`, et le garde de condition refusait l'arrosage en « sol non adapté ».
- **Ce que ça coûtait** : pendant les 7 jours de la phase, un matin d'automne à 88 % — le cas normal à l'aube — refusait l'eau d'un sol qui la demandait, juste après le geste le plus abîmant de l'année. C'est exactement le blocage que l'arbitrage de Kévin, appuyé sur les sources agronomiques, avait retiré partout ailleurs.
- **La correction** : seul `saturation_block` (bilan du jour au-dessus du seuil de saturation) rend désormais l'état « trop humide ». Le paramètre `humidite` de `_resolve_phase_policy`, devenu mort, est retiré.
- **Ce qui ne change pas** : un sol réellement détrempé bloque toujours, par deux chemins indépendants (le garde de politique et la branche `sol_deja_humide` du profil).
- **Tests** : l'air à 88 % ne bloque plus, le sol saturé bloque toujours, et le contrat du garde lui-même est épinglé — sans ce dernier, retirer la saturation du garde ne cassait rien, le profil bloquant déjà par ailleurs. 4 mutations, toutes détectées, dont le retour du verrou.
- **Reste ouvert** : `humidite_penalty` (`guidance.py`) retranche encore 10 à 20 % du déficit legacy quand l'air est humide. Ce n'est pas un blocage mais une dose, et c'est un arbitrage à part.

### Laissé ouvert

- **Redémarrage pendant l'attente.** Si `sun.sun` n'est pas encore publié au premier cycle après un redémarrage, le lever est inconnu et l'arrosage part à l'ouverture, comme en 0.89.0. Sur les redémarrages observés, `sun.sun` était là avant. Mieux vaut éviter de redémarrer entre 03:45 et l'heure de départ.
- **`apres_pluie`** : le lanceur attend l'heure calée, mais le capteur ne l'affiche pas. Cas non reproduit avec un objectif positif dans une décision complète.
- **« Tonte possible au lever du jour »** (prochaine tonte, nuit) : la tonte reste bloquée jusqu'à 10 h après le lever. Déjà présent avant.
- **Fraction d'ET écoulée** : le lever reste lu sur `next_rising` ; après le lever, la veille d'un changement d'heure, il saute aussi d'une heure. Déjà présent avant, effet limité à la journée.
- **Étape 3** : risque fongique cumulé, qui conseille sans bloquer.
- **`humidite_penalty`** (déficit legacy) : à arbitrer.

## 0.89.0

1530 tests verts. **L'air humide de l'aube ne retient plus l'arrosage : arroser sur la rosée est justement le bon moment.**

### L'arrosage « de l'aube » partait à 08:58

- **Le défaut.** Dès que l'humidité de l'air atteignait 85 %, l'arrosage était bloqué (« Conditions trop humides »), sans regarder la soif du sol. Or, à l'aube, l'air est naturellement proche de la saturation.
  - **13/09/2026.** L'humidité du jardin est restée entre 88 et 93 % de 03:30 à 08:57 : l'arrosage « de l'aube » est parti à 08:58, trois secondes après son passage à 84 %.
  - **15/09/2026.** Autour du seuil, l'objectif basculait entre 5,3 et 0 mm à chaque lecture (84 ↔ 85 %), un écart qui se situe dans la précision du capteur (±5 %). L'arrosage a dû être lancé à la main.
- **Arbitrage de Kévin (15/09), sur recherche documentaire.** Aucune source agronomique ne justifie ce blocage.
  - **NC State** recommande d'arroser juste avant le lever du soleil : l'eau fait tomber la rosée et accélère le séchage.
  - **L'université de Géorgie** rappelle qu'arroser sur la rosée n'aggrave pas les maladies. C'est en arrosant *après* le séchage du matin qu'on prolonge l'humectation.
  - **Purdue** situe l'idéal entre 4 h et 8 h.
  - **Aucun contrôleur connecté étudié** (Rachio, Rain Bird, Hydrawise, B-hyve, OpenSprinkler, Smart Irrigation) ne saute un arrosage pour humidité : elle sert seulement au calcul de l'ET, donc de la dose, ce que l'intégration fait déjà.

### Quatre verrous, pas un

⚠️ **Il en restait un cinquième**, propre à la phase Scarification et trouvé le 16/09/2026 : voir « Le cinquième verrou de l'humidité de l'air » en 0.90.0. La liste ci-dessous était donc incomplète au moment où elle a été écrite.

Retirer le seul blocage visible aurait laissé la même porte fermée ailleurs.
- **Phase Normal** : `ctx.humidite >= 85` est retiré de `humidite_excessive`. La seconde moitié reste, et elle ne regarde pas l'air : un bilan du jour déjà positif (apports > évaporation) sur un sol qui ne réclame rien.
- **Autres phases** : le blocage `humidite_elevee` est retiré des phases agronomiques (fertilisation, biostimulant, agent mouillant, scarification) et du profil générique.
- **Fenêtre** : `compute_action_guidance` renvoyait « attendre » dès 85 %, quand le bilan du jour était ≥ −0,5 mm. On n'y arrivait qu'avec un objectif > 0, donc un arrosage demandé, et le lanceur refuse « attendre ». Le 15/09, `fenetre_optimale` basculait entre « ce_matin » et « attendre » au rythme de l'humidité.
- **Textes** :
  - un matin humide sans besoin affiche « aucune action », plus « bloqué » ;
  - le conseil « Attends un léger ressuyage avant d'arroser » disparaît, car il contredisait le lancement ;
  - l'explication « humidité élevée : sol trop chargé » aussi ;
  - celle du motif `humidite_excessive` décrit la condition qui reste.

**Inchangé** : la garde du soir (air > 60 %), l'ajustement des micro-apports de semis, le risque fongique, les codes publiés, la dose et le seuil MAD.

### Tests

- **Le 13/09 rejoué par la chaîne complète.** À 84, 85, 91 et 93 % d'humidité, le snapshot d'un matin humide est identique à celui d'un matin sec : objectif, fenêtre, autorisation, type, conseil, action. Aucun « attendre », aucune explication « sol trop chargé », et un matin humide sans besoin n'est pas « bloqué ».
- **Au niveau du profil et de la fenêtre** : dose identique de 84 à 100 %, phases agronomiques et profil générique, pluie prévue et « un arrosage par jour » qui tiennent toujours, bilan positif qui bloque encore, fenêtre « ce_matin » puis « maintenant » à 60, 85 et 93 %.
- **Deux tests épinglaient l'ancien comportement.** « Le besoin survit à un blocage » se servait de l'humidité de l'air comme blocage indépendant du sol. Il passe désormais par la garde « un arrosage par jour », avec l'horloge patchée dans le module réellement appelé.
- **Preuve.** Sur l'ancien code, les nouveaux tests échouent dès 85 % et passent à 84 %. 8 mutations, toutes détectées : chacun des quatre verrous remis, chacun des trois textes remis, et la condition conservée retirée.

### Laissé ouvert

- **Étape 2** : caler la fin de l'arrosage sur le lever du soleil au lieu de partir à 03:45.
- **Étape 3** : remplacer le risque fongique instantané par un indicateur cumulé (heures de feuillage mouillé), qui conseille sans bloquer.
- **`humidite_penalty`** (`_build_watering_ctx`) retranche encore 10 à 20 % du déficit *legacy* au-dessus de 75 ou 85 %. C'est un double compte de l'humidité, déjà dans l'ET0. Il n'est actif que sans réserve du ledger et dans la retenue hebdomadaire. Ce n'est pas un veto mais une dose : à arbitrer à part.

## 0.88.0

1523 tests verts. **Une application ne coupe plus l'eau pour toujours, un semis redescend par paliers, et une seule table dit les motifs de blocage.**

### Une application foliaire bloquait tonte et arrosage indéfiniment

Trouvé par la cartographie de ce chantier, et reproduit par simulation. Les règles « application foliaire » et « type d'application inconnu » s'armaient sur la seule **existence** de `derniere_application`, qui est la dernière application de toute la vie de l'installation. Aucune fin, et **trois copies** :

- la décision : un Traitement déclaré en phase Normal gardait tonte et arrosage bloqués à J+2, J+20, J+100 ; un Traitement pendant un sursemis privait **le semis d'eau** ;
- le capteur « Fenêtre optimale / Prochain arrosage » : « Bloqué : type d'application inconnu » à vie ;
- l'arrosage après application du coordinateur : refusé à vie.

Ce n'était pas actif chez Kévin (dernière application : Floranid, type « sol »), mais cela se serait armé au premier Traitement déclaré.

**Source unique** : `memory.compute_application_state` évalue **chaque application récente pour elle-même** et publie `application_foliaire_en_cours`, `application_inconnue_en_cours` et `application_block_label`. Les trois consommateurs les lisent. Une application agit encore :
- tant que son blocage explicite court ;
- pendant ses **jours d'effet**, jour de l'application compris : Traitement et Fertilisation 2 jours, Biostimulant et Agent Mouillant 1 jour ;
- ou 24 h au moins depuis son **moment** réel, ou la durée de son blocage si elle est plus longue. Un Biostimulant pulvérisé à 21 h reste protégé jusqu'au lendemain 21 h.

Vérifié à horloge réelle : un Traitement déclaré à 10 h bloque J0 et J+1, et l'arrosage de l'aube revient à J+2.

### Deux revues adversariales ont renforcé ce correctif

- **Un semis n'est pas une application.** Une fiche semences, ou le produit sélectionné que `declare_intervention` rattachait d'office à un Sursemis, comptait comme « application de type inconnu » : le semis était privé d'eau de J+0 à J+44, et à vie avant. `Sursemis` et `Hivernage` sont exclus partout : la mémoire, les deux copies de la recommandation d'intervention qui délèguent maintenant à la définition de référence, et la prochaine réapplication. Le produit n'est plus rattaché d'office qu'aux vraies applications, et un semis sans produit ne lève plus « plusieurs produits sont enregistrés ».
- **La contrainte la plus lointaine l'emporte**, et plus seulement celle de la dernière application déclarée. Un Floranid déclaré le soir d'un fongicide effaçait les 24 h de protection de ce dernier. Un Humuslight déclaré après un H2Pro foliaire (catalogue réel) effaçait sa protection foliaire. Le message nomme le produit qui bloque.
- **L'incorporation d'un produit « sol » retardée par le blocage d'une autre application n'est plus abandonnée.** Sa fenêtre s'étend jusqu'à la fin de ce blocage ; avant, elle était affichée « Terminé » avec 5 mm restants.
- **`delai_avant_tonte_jours` est enfin appliqué.** Ce champ du catalogue n'était lu nulle part. Motif : « Délai avant tonte (Herbicide X): pas de tonte avant le 15/03/2026. ».
- **Le moment d'une application** est celui de `water.resolve_history_moment`. Une déclaration rétroactive compte depuis sa date, et non depuis sa saisie. Une déclaration faite entre 0 h et 2 h est reconnue comme du jour même : la date saisie est locale, `declared_at` est en UTC. Une application datée dans le futur n'agit pas avant son moment.

⚠️ **Chez Kévin**, deux comportements dormants s'activent avec le catalogue réel :
- les délais avant tonte de Floranid (2 jours), H2Pro (1 jour) et Kick Pro (1 jour) s'appliquent désormais ;
- H2Pro TriSmart est typé `foliaire` avec 5 mm de post-arrosage, alors que ses entrées passées étaient « sol ». En foliaire, il n'aura pas d'arrosage d'incorporation, et bloquera l'arrosage 24 h. C'est un réglage à confirmer.

### La sortie de sursemis, par paliers

- **Avant** : à J+45, la recommandation tombait de 6-7 cm vers 4 cm en quelques cycles. Le barème de reprise (`_post_sursemis_bonus`, de 36 à 59 jours) était **mort depuis la 0.7.2** : sa garde exigeait un âge ≤ 35 jours, alors que la phase avait été portée à 45 jours. Et un Traitement ou un Hivernage déclaré pendant un semis prenait la phase dominante : le plancher sautait, et on conseillait 5 cm sur des plantules de 10 jours.
- **Maintenant** : un plancher qui suit l'**âge du semis le plus récent par date**, quelle que soit la phase dominante. Valeurs publiées, sur la grille de 0,5 cm : Germination 7,5 · Enracinement 7,0 · Reprise 6,5 · Stabilisation 5,0 · puis la base du mois à J+45. Chaque marche reste sous le tiers. Chez Kévin (tondeuse 3-6 cm) : 6,0 cm jusqu'à J+34, 5,0 cm de J+35 à J+44, puis la base.
- **C'est un arbitrage prudent, pas une valeur sourcée.** Les sources, relues deux fois, divergent :
  - Barenbrug : premier passage en position haute (6-7 cm), deuxième en position moyenne (4-5 cm). C'est la seule qui soutienne « haute puis moyenne », et le modèle de ces paliers.
  - Ohio State : première tonte à la hauteur normale.
  - RHS : semis de printemps, baisser la lame progressivement ; semis d'automne, plus de tonte avant le printemps.
  Une descente de 0,5 cm par semaine restait défendable pour un semis de printemps : **le rythme reste à arbitrer**.
- **Le plancher est un conseil** : il n'interdit pas une lame réglée plus bas. La lame réelle reste le seuil de décision (arbitrage du 30/08).
- **Limite** : une fin manuelle avant J+45 (« Retour au mode normal ») retire l'entrée Sursemis, et le plancher avec elle.
- **Le motif cite le plancher qui fait réellement la valeur** : c'est le plus haut, et il doit dépasser la saison. Il dit aussi l'arrondi quand celui-ci change la somme (« … +0,2 → arrondi à 4,0 cm »).
- **Lame inconnue** : « hauteur trop faible » dit « la hauteur conseillée est X cm (réglage de lame inconnu) », et non plus « la lame coupe à X cm ».

### Une seule table pour les libellés des motifs

L'assistant gardait sa propre table (`_BLOCK_REASON_LABELS`), copie divergente de `const.BLOCK_REASON_DISPLAY_LABELS`.

- Elle est supprimée. L'assistant consulte `const.block_reason_label()` et garde son repli, le texte tel quel. Les deux copies de `_block_reason_display_label` des capteurs deviennent un alias de `const.block_reason_display_label`.
- **Effet réel**, mesuré par la revue sur 4 541 instantanés via `GazonBrain` : le hero affichait `temperature_trop_basse_germination` en brut, en Sursemis combiné à une application « sol » par temps froid. Trois autres codes étaient bruts dans la table de l'assistant, sans chemin réel trouvé jusqu'au hero.
- **Libellés tranchés** : `soil_wet` devient « Sol humide » et non plus « Sol détrempé ». Le seuil est 70 % d'humidité du sol, ou 90 % d'humidité de l'air juste après un arrosage. Les 6 fichiers de traduction ont été mis à jour. `mowing_window_blocked` reste « Hors fenêtre de tonte ».
- **Nuit** : quand le créneau publie « Nuit: attendre le lever du soleil. » (22 h, soleil encore levé), l'assistant garde cette phrase.
- **Adaptateur tondeuse** : une erreur en toutes lettres est ramenée au code connu (« Battery low » → `battery_low` → « Batterie faible »), et le filtre « pas d'erreur » porte aussi sur la forme normalisée. La première version lisait « No-error » comme une panne. **Pas de normalisation vers une pause pluie** : « Rain delay » en toutes lettres garde son comportement prudent, car le convertir aurait contourné le cliquet `idle`.
- **Pause pluie** : le code `rain_delay`, que la Landroid publie dans l'enum de son capteur d'**erreur**, s'affichait « Robot en erreur: Pause pluie active. », jusque dans le hero. C'est maintenant « Robot en pause pluie: attendre qu'elle soit prête. ».
- **Garde AST** (`test_aucune_autre_table_code_vers_libelle`) : aucun dictionnaire hors de `const`, ni aucun `dict(...)`, n'associe au moins deux codes de la table à un libellé (chaîne, f-string, tuple, liste ou dictionnaire imbriqué). Deux exceptions, nommées dans le test : `_MOWER_WATERING_BLOCK_LABELS` (des phrases) et `_AUTO_IRRIGATION_BLOCK_INFO`, une dette visible car ses titres divergent encore pour 5 codes.

### `derniere_tonte_date`, enfin publiée

La carte lit cet attribut depuis sa 0.21.2 pour ne pas reproposer « J'ai tondu » le jour même. Rien ne le publiait. Il arrive désormais sur « Tonte autorisée ».

### Tests

45 nouveaux tests, dont 8 à **horloge réelle**. Le harnais fige `dt_util.now` au 04/04/2026, et avec des dates antérieures la partie « depuis le moment » de la fenêtre n'était jamais exercée. Ces 8 tests couvrent :
- l'aube de J+2 ;
- un semis avec un Traitement ;
- un produit foliaire suivi d'un produit « sol » ;
- l'incorporation retardée et le nom du produit qui bloque ;
- une application datée dans le futur ;
- une déclaration à 00 h 30 ;
- le produit sélectionné non rattaché à un semis.

Les autres tests couvrent :
- les paliers de semis (`==`) et l'attribution du plancher ;
- la recommandation d'intervention qui ignore un semis porteur de produit ;
- la parité des libellés ;
- trois chaînes suivies jusqu'aux entités par la recopie réelle du coordinateur : `application_inconnue_en_cours`, `derniere_tonte_date`, et la pause pluie de l'adaptateur jusqu'au libellé.

⚠️ Piège de harnais trouvé en route : d'autres fichiers de tests réimportent le paquet. `patch.object(importlib.import_module("…memory"))` visait alors un **autre** objet module que celui de la décision. Ces tests passaient seuls et échouaient en suite complète. On patche désormais les globales du module réellement appelé.

### Coordinateur découpé en modules (refactor Codex, sans changement de comportement)

`coordinator.py` délègue désormais ses calculs purs à sept modules. Les méthodes du coordinateur restent en place comme **façades** : aucun appelant, aucun test existant n'a changé.

- `coordinator_constants.py` : les constantes du coordinateur ;
- `coordinator_helpers.py` : conversions et médiane ;
- `coordinator_states.py` : lecture et validation des états HA ;
- `coordinator_runtime.py` : sessions d'arrosage runtime, minutes créditables, cause d'arrosage ;
- `coordinator_weather.py` : lever/coucher du soleil, fraction d'ET écoulée, rosée ;
- `coordinator_observability.py` : motif de blocage, ETP écoulée du jour, charge d'observabilité ;
- `coordinator_irrigation.py` : débit par zone, segments en attente, trace d'exécution d'une zone.

52 tests dédiés (`test_coordinator_extracted_helpers.py`), et les sept modules entrent dans le périmètre mypy (46 fichiers). Une revue adversariale a comparé l'ancien et le nouveau code sur 77 851 cas : aucun écart en production. Restent en place, volontairement : `_COORDINATOR_SNAPSHOT_KEYS`, la sérialisation/restauration de l'état runtime, la pluie et la tondeuse.

Deux défauts corrigés dans la foulée :

- **Arrêter l'arrosage pendant la première zone d'un passage n'enregistrait pas l'eau déjà versée.** Au passage 1, rien n'était crédité pour cette zone ; et après une fin de zone normale, son segment restait en attente. Défaut antérieur au refactor, trouvé par sa revue : `int(x.get("zone_index") or -1) == zone_index` ne reconnaissait jamais l'index 0, puisque `0 or -1` vaut `-1`. `coordinator_irrigation.is_matching_zone_segment` compare désormais `(passage, zone_index)` aux deux endroits, robuste à `None` et aux valeurs non entières. Remettre l'ancien `or -1` fait échouer les trois tests zone 0.
- **Un arrêt ou un redémarrage pendant la sauvegarde de fin de cycle faisait perdre l'eau du cycle.**
  - **Le problème.** Effet de bord de la correction précédente, trouvé par la contre-vérification. La purge vide enfin `zones_pending` après la dernière zone, et `is_finished_irrigation_session` concluait alors « terminée » pendant la sauvegarde, *avant* l'enregistrement de l'eau. Un `stop_irrigation` ou un redémarrage à cet instant clôturait la session sans rien enregistrer : 0 mm au lieu de 6 sur un banc 3 zones × 2 passages.
  - **La correction.** Le marqueur `watering_recorded` (`coordinator_runtime.WATERING_RECORDED_KEY`) est posé juste avant `async_record_watering`. Tant que des zones ont tourné sans ce marqueur, la session reste active : l'arrêt ou la reprise enregistrent l'eau, une seule fois. Posé avant l'appel, il ne peut pas être sauvegardé sans l'eau, car `brain.record_watering` s'exécute avant le premier `await` et l'historique part dans la même sauvegarde que la session.
  - **Ce qu'on garde.** La fenêtre inverse existait avant la zone 0 : l'eau déjà enregistrée, un arrêt réenregistrait le cycle en `arret_manuel`. Elle reste fermée.
  - **Tests.** Six tests : quatre sur le vrai exécuteur, deux sur le prédicat.
    - arrêt pendant la sauvegarde finale ;
    - redémarrage depuis cette sauvegarde, avec aller-retour JSON ;
    - arrêt puis redémarrage après l'enregistrement ;
    - purge exacte sur 2 zones × 2 passages.

    Sept mutations, toutes détectées : marqueur jamais posé, posé après l'appel, garde retirée, marqueur exigé sans zone jouée, ancien `or -1`, purge qui vide tout, purge qui ignore le passage.

**Tests des deux revues.** Les câblages que les revues avaient trouvés sans filet sont épinglés. Pour chacun, une mutation temporaire fait tomber au moins un test :

- les lectures d'état sans `hass` ;
- le plafond de 15 min, à la seconde près : 15 min se créditent, 15 min 01 s non ;
- `feedback_observation` dans la charge de debug ;
- l'identifiant runtime horodaté en UTC ;
- l'objectif lu dans `self.result` ;
- les façades lever/coucher du soleil (bonne clé, heure locale) et leur point d'appel dans `_calculer_donnees`, qui transmet le coucher au garde-fou de l'arrosage du soir ;
- la façade rosée sur ses deux chemins (point de rosée, humidité), et le point d'appel qui transmet l'estimation et l'humidité ;
- le sérialiseur des événements runtime ;
- les bornes exactes de `validate_sensor_value` pour la température, la pluie, l'ETP et l'humidité. Ces deux dernières tournent bien en production : les dire « code mort » était faux ;
- `estimate_rosee` : seuil de 2,0 °C, humidité à 88 %, chacune des conditions `fog`, `rainy` et `pouring`, priorités, valeurs non numériques ;
- `sun_event_minute_from_context` : conversion UTC → heure locale, valeurs absentes ou non reconnues.

### Laissé ouvert

- **L'humidité de l'air à 85 % ou plus bloque l'arrosage de l'aube, même quand le sol a soif** (corrigé en 0.89.0). Le 13/09, l'humidité est restée entre 88 et 93 % de 03:30 à 08:57 : l'arrosage « de l'aube » est parti à 08:58. Sans hystérésis, l'objectif bascule à chaque lecture entre 84 et 85 %. À arbitrer : reprendre l'échappatoire des règles voisines ne suffirait pas, car elle se base sur la déplétion actuelle, pas sur la soif projetée qui déclenche l'arrosage.
- **Un redémarrage de HA pendant l'enregistrement d'un arrêt manuel peut rouvrir les vannes** (corrigé en 0.90.0). L'arrêt enregistre l'eau avant d'effacer la session : si HA s'arrête entre les deux, la reprise relance les zones restantes et réenregistre l'eau. Défaut antérieur, rare.
- **Le marqueur `watering_recorded` est ignoré tant qu'un segment reste en attente.** Cela arrive après une zone jugée finie pendant une coupure, ou avec un segment de durée 0. Un arrêt ou un redémarrage pendant l'enregistrement de fin de cycle réenregistre alors l'eau, comme avant C1. Rare.
- **Une reprise qui échoue au redémarrage n'enregistre pas l'eau déjà versée.**
  - Vannes indisponibles plus de 60 s, verrou de sécurité actif, ou arrosage automatique coupé entre-temps : la session est close sans enregistrer `zones_done`.
  - Une zone jugée finie pendant la coupure n'est jamais créditée, et une zone reprise ne l'est que pour son temps restant.
  - Un échec de fermeture de vanne pendant la reprise perd aussi cette eau. (Il était écrit ici qu'il laissait une session zombie refusant tout lancement : c'est faux, voir 0.90.0.)
  - Un arrosage post-produit automatique est repris au redémarrage même si l'arrosage automatique a été coupé : seule la source `auto_irrigation` est testée.
  - Défauts antérieurs.
- Sans effet en production, non épinglés : les gardes de `is_matching_zone_segment` (segment qui n'est pas un dict, booléen) et le cas où le parseur de dates lève une exception dans `sun_event_minute_from_context`.
- **Quatre codes émis n'ont de libellé dans aucune table** : `temp_extreme`, `temperature_unknown`, `application_type_required`, `unsupported_application_type`. Le test d'invariant `test_aucun_code_publie_ne_reste_sans_libelle` est un faux vert : il ne lit que trois fichiers, et seulement sur une ligne.
- **Le bouton « Retour au mode normal » lève aussi le verrou de sécurité des vannes.** Débloquer une vanne pendant un semis efface donc le semis. Ce couplage est volontaire depuis juin, pour ne jamais rester sans recours.
- La pastille « Tonte » réagit aussi à l'état de la machine (`tonte_statut` calculé sur `tonte_ok`).
- La projection « prochaine tonte » suit la phase dominante, pas le semis.
- Le rythme de sortie de semis est à arbitrer.

## 0.87.0

1410 tests verts. **La hauteur conseillée suit les mois : 4 cm aujourd'hui, et non plus 6.**

### « Elle a toujours été à 6 cm »

Kévin tond volontairement à 4 cm (lame à 40 mm). La recommandation affichait 6,0 cm de juillet à septembre, soit le maximum de la tondeuse. Trois causes s'empilaient :

| cause | effet |
|---|---|
| une table qui ne descendait jamais sous 5 cm (5,0 · 5,8 · 5,0 · **6,2** · 5,0, arrivée en 0.7.0 sans justification écrite) | 6,2 en été, écrêté à 6,0 |
| un stress « fort » lu dans un déficit **projeté** (`deficit_7j ≥ 7`, soit 7 × l'ETP du jour moins pluie et arrosage), armé en permanence sur un gazon arrosé | **+1,0 cm** avec une réserve « pleine » et un risque « faible » |
| des corrections presque toutes positives (rosée +0,4, pluie jusqu'à +0,7 ; une seule négative, −0,5), arrondies **vers le haut** | la moindre rosée montait d'un cran |

Le même déficit projeté suivait le scintillement de l'ET0 à l'aube : **160 changements d'état** le 11/09 entre 04:51 et 07:12, dont 156 entre 5,5 et 6,0.

### Ce qui règle la hauteur désormais

- **Une nouvelle table** : 4 cm de pousse, 4,5 à la reprise de mars et en juin, 5 cm en juillet-août, 4 cm de septembre à février, plus le +0,5 d'hiver que le calcul ajoutait déjà. La base de 4 cm est le choix de Kévin, dans la fourchette des sources européennes (DRG 3,5-4,5 cm, DLF/Johnsons 3-4 cm, RHS environ 4 cm au printemps et à l'automne). Le relèvement d'été (+1 cm) suit DLF/Johnsons, la DRG et les universités américaines (Iowa et NC State, +1,3 cm). Le RHS, lui, conseille plus court en été, pour un été britannique arrosé par la pluie. Aucune source ne donne de table mois par mois : les sources fixent la direction et les bornes, pas les chiffres.
- **Le stress lu dans la réserve réelle** du registre du sol, comparée au seuil MAD de la phase (0,5 en phase Normal, 0,6 en Hivernage). Pas de relèvement sous le seuil. +0,5 dès qu'il est atteint (`>=`, la convention de l'arrosage). +1,0 à mi-chemin de la réserve vide. Sans registre (premier cycle), repli sur l'ancien indicateur : ne pas savoir ne vaut pas « aucun stress ».
- **La température de la journée**, et non celle du thermomètre : c'est le maximum prévu ou mesuré depuis minuit, retenu par un cliquet mémorisé (`hauteur_tonte_temperature_jour`) qui ne redescend qu'au changement de date. Une lame se règle pour la journée. Lue sur la mesure instantanée, la hauteur montait l'après-midi et prenait « froid » (+0,5) à chaque aube fraîche. Une prévision hors de −30..50 °C est ignorée.
- **Arrondi au plus proche** (demi vers le haut, jamais « au pair ») pour la part saisonnière. Les **planchers** (règle du tiers, sursemis) restent arrondis vers le haut et passent **après** le lissage. Sinon un gazon à 7 cm, dont le tiers interdit de descendre sous 4,67, se verrait conseiller 4,5.

### Ce qui ne règle plus la hauteur

- **La rosée et la pluie** : elles disent *quand* tondre, pas à quelle hauteur, et elles ont déjà leurs blocages. La rosée est estimée faute de capteur : une humidité ≥ 88 % suffisait à l'armer, soit 22 % des heures du 05 au 11/09.
- **La « légère réduction » par bonnes conditions** (−0,5 en avril, mai, juin, septembre) : sur une base de 4,0, elle aurait conseillé 3,5 cm, sous la hauteur voulue.
- **Le « +0,2 de reprise en mars »** : la base de mars (4,5) porte déjà la reprise, et arrondi au plus proche ce terme ne changeait jamais la valeur.
- **L'air sec** (≤ 40 % → +0,3) quand le registre mesure la réserve : l'ETc qu'il débite intègre déjà la sécheresse de l'air. Il reste dans le repli.
- **Une absence n'est plus un zéro** : une température inconnue (premier cycle d'un redémarrage) déclenchait « froid », une humidité inconnue « air sec ».

### Le pourquoi, publié

Nouvel attribut **`hauteur_tonte_motif`**, sur « Hauteur de tonte conseillée », « État de tonte » et « Tonte autorisée » (les trois entités qui publient la hauteur). Exemples : « Septembre : base 4,0 cm (hauteur de pousse). », « Juillet : base 5,0 cm, forte chaleur (34,0 °C) +1,0. ». Il décrit la valeur **publiée** : règle du tiers, plafond ou minimum de la tondeuse, lissage en cours (« en route vers 4,0 cm »). Le stress qui montait la lame n'était publié nulle part : « pourquoi 6 cm » ne se comprenait qu'en relisant le code.

### Revue adversariale

Six angles de relecture, 26 agents, aucun bloquant. Les constats retenus ont été corrigés avant déploiement :

- **La prévision « du jour » s'érode le soir.** Chez ce fournisseur, c'est le maximum des heures **restantes** : 22,5 °C à 14 h, 15,8 à 23 h 40 le 10/09. Sans le cliquet, « journée froide » revenait le soir en demi-saison, et la chaleur d'été retombait avant la nuit.
- **La règle du tiers était attribuée sur des valeurs brutes** : un relèvement réel (tiers 4,13 → 4,5) était tu quand la saison brute valait 4,2. Elle se juge désormais sur les valeurs arrondies, pour le motif comme pour le libellé de garde-fou.
- **Le lissage pouvait republier une valeur sous le plancher du tiers.** Les planchers passent maintenant après lui.
- **Des seuils sans test** : `> MAD + 0,1`, fort à 0,85, 33 °C au lieu de 32, le +0,5 à 28 °C, le +0,3 de phase, un MAD figé à 0,5, et la lecture de `temperature_reference_hydrique` à la place de la prévision (la mutation la plus plausible : le coordinateur la transmet toujours). Toutes passaient. Chacune a maintenant son test.

### Ce qui ne change pas

**Aucune décision de tonte chez Kévin.** La lame réelle (40 mm, via l'option de hauteur de coupe, lue même tondeuse injoignable) sert de seuil. Pour une installation **sans lame connue**, la recommandation sert de repli : plus basse, elle refuse moins souvent une herbe courte (« hauteur trop faible ») et déclenche la règle du tiers plus tôt, dans les deux cas comme le ferait une lame réelle à 4 cm. Le lissage d'un pas par cycle reste en place : la descente de 6,0 à 4,0 prend quelques cycles.

### Limites connues, non traitées ici

- **Sortie de sursemis** : à J+45 la phase repasse en Normal et la recommandation descend en quelques cycles vers 4 cm. Le barème de reprise `_post_sursemis_bonus` (36-59 jours) est mort depuis toujours : sa garde exige un âge ≤ 35 jours, alors que la phase dure 45 jours.
- **Pas d'hystérésis au seuil MAD** : le registre ne fait que baisser par l'ETc et monter par pluie ou arrosage, donc il n'oscille pas autour du seuil. Rien ne l'interdit pour autant.
- **La carte n'affiche pas encore le motif.**

### Tests

31 nouveaux tests (`RecommandationDeHauteurTests`, `LeMotifDeHauteurAtteintLeCapteurTests`, `LeCliquetDeTemperatureSurvitAuDisqueTests`) :
- table mois par mois ;
- aucun terme mouillé, même absorbé par l'arrondi, testé sur la hauteur théorique **avant** arrondi par les vrais bundles ;
- jamais sous 4 cm ;
- seuils de réserve et de chaleur de part et d'autre ;
- MAD de la phase ;
- cliquet du soir, remise à zéro à minuit, filtre des prévisions aberrantes ;
- cliquet suivi jusqu'au **disque** (`dump_state` → `load_state` → soir) ;
- planchers du tiers et du sursemis hors grille (les tests voisins utilisaient des gazons de 12 et 15 cm, dont les 2/3 tombent pile sur la grille) ;
- motif suivi jusqu'aux attributs des trois entités par la recopie réelle du coordinateur.

Trois anciens tests réécrits avec leur raison, dont un attendu posé en 0.27.0 sur la foi des fiches américaines (7,5 à 10 cm en été). Aucun des onze termes retirés ou modifiés n'était épinglé par un test. Banc de 34 mutations, toutes détectées. Une 35e est équivalente : retirer le motif de `_MOWING_BUNDLE_CORE_KEYS`. Cette liste n'est lue que par deux tests d'inclusion : elle ressemble à une liste blanche mais ne filtre rien.

## 0.86.0

1379 tests verts. **Home Assistant affiche « Aucune action », plus `aucune_action`.**

### Des codes à l'écran

Onze capteurs publiaient un code interne que Home Assistant montrait tel quel, tirets bas compris : `aucune_action`, `a_surveiller`, `modere`, `preparation`, `attendre`… (question de Kévin le 11/09 : « Pourquoi il y a ce tiret ? »).

| capteur | avant | maintenant |
|---|---|---|
| Assistant · Niveau d'action | `aucune_action` | Aucune action |
| État de tonte | `a_surveiller` | À surveiller |
| Risque gazon | `modere` | Modéré |
| État hydrique | `depletion` | Réserve entamée |
| Fenêtre optimale · Prochaine fenêtre optimale | `demain_matin` | Demain matin |
| Prochaine intervention · Debug intervention | `preparation` | À préparer |
| Dernière exécution | `ok` | Réussie |
| Prochain blocage attendu | `pluie_prevue_suffisante` | Pluie prévue suffisante |

### L'état publié ne change pas

**Aucune automatisation ne casse** : l'état reste `aucune_action`, et c'est lui que lisent les automatisations, Node-RED et la carte. Seul l'affichage change. Chaque capteur porte une clé de traduction (`_attr_translation_key`), et le frontend cherche le libellé dans `translations/<langue>.json`. S'il n'en trouve pas, il affiche le code, comme avant. Les noms et `entity_id` sont intacts (le nom explicite prime sur la traduction).

**Pas d'énumération stricte** (`SensorDeviceClass.ENUM`), et c'est voulu. Avec elle, un état absent de la liste lève `ValueError` et l'entité cesse de se mettre à jour. Une valeur oubliée coûterait alors le capteur, et non plus seulement un libellé.

### Une seule formulation

- **Prochain blocage attendu** : le français *est* `BLOCK_REASON_DISPLAY_LABELS` (`const.py`), mot pour mot. Un test impose l'égalité, pour éviter une deuxième table qui dériverait.
- **Intervention** : « Recommandé », « À préparer », « Bloqué » reprennent les titres du moteur (`_state_metadata`), les mêmes que le badge de la carte.
- **Hydrique, risque, tonte** : mêmes mots que la carte (« Réserve entamée », « Modéré », « À surveiller »).
- `USER_ACTION_STATES` (`memory.py`) nomme les quatre états qu'une exécution peut garder en mémoire. Le normaliseur s'en sert, et le test aussi.

### Ce qui n'est pas traduit

- **Niveau de pertinence** (`faible`, `moyen`, `élevé`) : ce sont déjà des mots français, et une clé de traduction ne peut pas contenir d'accent (règle hassfest), donc `élevé` n'aurait pas eu de libellé.
- **`unavailable`** (intervention sans produit) : Home Assistant le lit comme « entité indisponible » avant toute traduction.

### Tests

`LesEtatsCodesSontTraduitsTests` (11 tests, 428 sous-cas) suivent la **valeur** : vrai capteur, vraie valeur publiée, résolue dans les cinq langues comme le fait le frontend. Chaque balayage doit en outre **couvrir** tous les états : un capteur figé sur une constante échoue. Les actions de l'assistant et les niveaux de risque sont récoltés dans le code du moteur (AST), si bien qu'une nouvelle valeur non traduite fait échouer la CI. Banc de 14 mutations, toutes mordent. La première version en laissait passer une : « hydrique figé sur *plein* » était masqué par le second chemin de calcul, qui fournissait l'état manquant.

## 0.85.0

1368 tests verts. **« Bloqué » ne s'affiche plus quand rien n'est retenu.**

### Le matin du 11/09

L'arrosage de l'aube vient de remplir la réserve à **12/12**. La garde « un arrosage par jour » (`cooldown_24h`) reste armée — c'est voulu. Et pourtant, avec `besoin_mm: 0` publié à côté, **quatre surfaces** l'ont raconté comme un blocage :

| entité | affichait |
|---|---|
| `prochain_arrosage` | **« Bloqué »** · « Attendre des conditions favorables » |
| `fenetre_optimale` | « Arrosage bloqué: Déjà arrosé aujourd'hui » |
| `assistant` | **« attente_conditions »** — le hero de la carte |
| `signal_irrigation` | « Arrosage bloqué par conditions : Déjà arrosé aujourd'hui » |

Rien n'était demandé, donc rien n'était retenu. Annoncer un blocage laissait croire qu'on refusait de l'eau au gazon, juste après l'avoir arrosé.

### Une règle juste, recopiée fausse

La bonne règle existait depuis la 0.72.0 dans `_motif_de_blocage_effectif`, avec ce commentaire : *« Deux copies finiraient par diverger, et l'une des deux mentirait sans qu'on sache laquelle. »* Elles avaient divergé : quatre autres endroits recalculaient « un motif existe, donc bloqué ». Deux surfaces disaient juste (`arrosage_auto_blocage` : « Aucun besoin »), quatre mentaient.

`blocage_sans_objet()` est désormais **la** définition, et les cinq endroits passent par elle — y compris l'ancienne, qui lui délègue.

### Ce qui reste bloqué, et doit l'être

- **Le même garde avec un vrai besoin** : arrosé ce matin, et le sol a de nouveau soif cet après-midi. La garde retient bien de l'eau, elle le dit.
- **Le cas du 31/07** : la garde hebdomadaire retenait une eau dont le gazon avait besoin. « Retenu » y reste la vérité. Les deux défauts ne diffèrent que par un nombre, `besoin_mm`, et les tests épinglent les deux côtés.
- **Un besoin inconnu** : absence ≠ zéro. Ne pas savoir n'autorise pas à conclure que tout va bien.
- **Tout blocage post-application** : un produit épandu attend son eau pour être dissous. C'est une activation, pas un déficit hydrique, et `besoin_mm` peut valoir 0 pendant qu'un engrais attend sur le feuillage. Garde nouvelle — l'ancienne définition ne l'avait pas.

### Une cinquième copie, trouvée en vérifiant le déploiement

Après redémarrage, les quatre états étaient justes — mais le **résumé** de `prochain_arrosage` affichait encore « Arrosage retenu: Déjà arrosé aujourd'hui » sous un état « Non requis ». L'état lisait le motif *effectif*, le résumé relisait le motif *brut* : deux phrases contradictoires dans la même entité. Le premier test ne cherchait que le mot « bloqué » ; il exige maintenant la phrase exacte, et un second vérifie que l'état et le résumé racontent la même chose dans les deux sens.

### Et une sixième, toujours sur l'installation

`action_recommandee` et `conseil_principal` affichaient encore « Arrosage bloqué par conditions: Déjà arrosé aujourd'hui. ». Ils passent par `_irrigation_blocked_due_to_conditions_summary`, dont la première moitié lit l'assistant — corrigé — mais qui retombait, dès que l'assistant ne disait plus « bloqué », sur une seconde moitié recalculant l'ancienne règle depuis le motif brut. Le premier relevé n'avait vérifié en direct que cinq entités sur sept. Une chasse systématique aux conditions `type_arrosage == "bloque"` produisant du texte sans passer par la définition n'en trouve plus : la seule restante est gardée par `objectif_mm > 0`, où l'eau est bien retenue.

### Affichage seulement

Rien ne touche à `type_arrosage` ni à l'exécution : la garde retient exactement ce qu'elle retenait. Seul le récit change.

### Vérification

Les nouveaux tests passent par le **vrai** `_contextual_watering_state` — les tests voisins le court-circuitaient pour tester la présentation, ils ne pouvaient donc pas voir le défaut. Six mutations, chacune vérifiée : la définition qui ne désarme plus rien, chacun des trois points d'appel débranché, l'exclusion post-application retirée, et une absence lue comme un zéro.

## 0.84.0

1348 tests verts. **Quand tu cliques, l'écran suit tout de suite.**

### Dix secondes d'attente, invisibles

Kévin, 10/09/2026 : « quand je clique j'ai quelques secondes avant que ça se mette à jour ».

Le coordinateur s'initialise **sans debouncer personnalisé** : il hérite de celui de Home Assistant. Valeurs lues dans la version installée (HA 2026.2.3), pas citées de mémoire :

```
REQUEST_REFRESH_DEFAULT_COOLDOWN  = 10 s
REQUEST_REFRESH_DEFAULT_IMMEDIATE = True
```

`immediate=True` laisse passer le **premier** appel, puis ferme la porte dix secondes. Or `async_request_refresh` n'est pas sollicité que par les actions : chaque changement d'un capteur suivi en demande un aussi. **Mesuré sur l'installation** — le fichier d'état est réécrit toutes les **10,04 s**, quatorze fois d'affilée : le debouncer est en permanence dans sa fenêtre. Un clic attendait donc le reste des dix secondes.

Le clic passait, le service s'exécutait, le cerveau était à jour : **seule la republication attendait**. Une attente invisible se lit « ça n'a pas marché ».

### Les actions passent devant, les capteurs attendent

`_rafraichir_apres_action_utilisateur()` appelle `async_refresh()` (immédiat) ; les 20 points d'appel nés d'une action de Kévin y passent. Les capteurs gardent leur debouncer de 10 s — c'est lui qui protège l'installation d'un recalcul en boucle, et **on n'y touche pas**.

### La réentrance tient désormais par le code

Rafraîchir depuis l'intérieur du cycle se rappellerait lui-même. Le piège est connu ici : c'est lui qui a imposé l'écriture synchrone dans le cerveau pour la déclaration automatique de tonte. La promesse tenait par la discipline ; un drapeau `_dans_le_cycle`, levé par le cycle et rabaissé dans un `finally`, la tient maintenant par une garde. Depuis le cycle, on retombe sur le chemin débouncé.

### Trois défauts de câblage, trouvés par la revue avant livraison

- **Deux services oubliés** : `register_product` et `remove_product` — des actions comme les autres — restaient sur le chemin lent. « Câblé à moitié », le défaut n°1 du projet, dans le correctif censé le corriger.
- **Deux chemins MIXTES branchés à tort** : `async_record_watering` et `async_record_user_action` servent bien un service, mais elles sont aussi appelées par l'exécuteur d'arrosage à chaque étape — une quinzaine de points internes. Les brancher sur l'immédiat faisait tourner **un cycle complet, en ligne, dans la tâche d'arrosage**. Elles sont revenues au débouncé, et c'est le point d'entrée utilisateur (`_handle_declare_watering`) qui rafraîchit.
- **Un test rendu aveugle par mon propre montage** : en ajoutant un `async_refresh` stubbé partout, j'avais aveuglé le seul test comportemental qui vérifie que le chemin des **capteurs** reste débouncé. Il est de nouveau voyant.

La revue a aussi écarté ses propres constats les plus alarmants — « arrêter l'arrosage le relance », « le lancement manuel se fait refuser » — après rejeu du code réel.

### Ce qui reste assumé

`async_refresh()` **ne groupe pas** : un arrêt d'arrosage enchaîne jusqu'à trois cycles là où le debouncer en groupait. Mesuré sur l'installation, un cycle coûte **~40 ms** et il en tourne déjà ~8 640 par jour : quelques gestes quotidiens ajoutent moins de 1 %. Le compromis est retenu en connaissance de cause.

### Vérification

Huit mutations, chacune vérifiée pour qu'elle fasse tomber le test visé — dont le retour au chemin débouncé, la disparition de la garde de réentrance, le drapeau qui ne retombe plus après une exception, les deux services produits, et le rebranchement d'un chemin mixte.

## 0.83.0

1339 tests verts. **Le ressuyage de la tonte dépend enfin de la LAME D'EAU tombée — et la station du jardin y a voix.**

### Un basculement d'auget valait trois heures

Le 09/09/2026 à 20:12, `sensor.meteo_netatmo_precipitation_aujourd_hui` — le pluviomètre du **voisin** — passe de 0,0 à **0,1 mm**. Un auget. Le garde `wet_grass` arme aussitôt les **180 minutes** de ressuyage empruntées au délai d'après-arrosage, calibrées pour un cycle d'irrigation de plusieurs millimètres.

Pendant ce temps la station du jardin, celle qui est **sur la pelouse**, n'a rien mesuré : compteur figé à 2,3 mm de 04:14 à minuit. Tonte bloquée jusqu'à 23:12 pour une pluie que le gazon n'a pas reçue.

Deux causes, pas une : **aucun minimum de quantité** (0,1 mm et 10 mm armaient le même délai), et **une seule source**, qui n'est pas la bonne.

### Les trois corrections, tenues ensemble

| | |
|---|---|
| **un minimum** | sous **0,3 mm**, aucun ressuyage n'est armé. La tonte reste bloquée tant qu'il *pleut* — c'est un autre garde, intact — mais sans traîne de trois heures |
| **une durée proportionnelle** | 0,3 mm → 45 min · 1,0 → 71 · 2,0 → 107 · **≥ 4,0 → le délai plein configuré** |
| **les deux pluviomètres** | la lame retenue est la **plus grande** des deux. Quand la station du jardin voit une averse que le voisin sous-estime, c'est elle qui commande |

**D'où viennent 0,3 et 4,0.** Un couvert de gazon retient plusieurs millimètres avant qu'une goutte n'atteigne le sol — **4,4 mm** mesurés sur zoysia et agrostide par pluviomètres co-localisés (PLOS ONE 2022, *Measuring turfgrass canopy interception and throughfall using co-located pluviometers*). C'est la bonne échelle pour la vraie question de la tonte : **l'eau sur la feuille**. 4,0 mm vaut donc saturation du couvert, et 0,3 mm — moins d'un dixième — le film que les premières minutes d'évaporation enlèvent. Ce sont des repères réglables, pas des constantes physiques : la mesure porte sur des gazons plus ras et plus denses que celui-ci.

### Le premier jet était pire que le défaut, et une revue adversariale l'a montré

Il cumulait une « lame d'épisode » **remise à zéro** dès qu'une hausse arrivait après une heure de trou. Rejoué sur du code réel :

| heure | événement | verdict |
|---|---|---|
| 14:00 → 14:50 | **6,0 mm** sur les deux pluviomètres | ressuyage plein, jusqu'à 17:50 |
| 16:24 | — | bloqué, « ressuyage après 6,0 mm (85 min restantes) » |
| 16:25 | **un auget de traîne** (6,0 → 6,1) | l'épisode est remis à 0, puis rechargé à **0,1 mm** |
| 17:00 | — | **tonte AUTORISÉE**, sur une pelouse ayant reçu 6,1 mm |

Sans le correctif, la même chronologie bloquait jusqu'à 19:25. **Plus il pleuvait, moins on bloquait.** Quatre relecteurs indépendants ont convergé ; deux autres défauts de la même racine ont suivi — un pluviomètre `unavailable` faisait disparaître sa lame au lieu d'être ignoré, et une bruine fractionnée n'armait jamais rien.

**Un accumulateur qu'on détruit n'est pas une mesure.** La lame est désormais une **fenêtre glissante de 4 h** : chaque hausse est horodatée, celles qui sortent tombent d'elles-mêmes, et rien ne peut être effacé par une pluie plus récente. Une hausse ne peut qu'**ajouter**. La fenêtre est plus large que le ressuyage le plus long (180 min), sinon la lame s'évanouirait avant la fin du délai qu'elle a armé.

Et elle **vieillit à l'horloge, pas à la lecture** : une coupure du capteur ne l'efface plus — vérifié des deux côtés, par un test et par une mutation.

### Ce qui n'a pas bougé

`is_active_rain_weather` et `active_rain_source` sont intacts : bloquer **pendant** la pluie est un autre garde, et il commande aussi l'arrosage. Le cliquet anti-oscillation, l'horodatage de l'averse et sa garde « une prévision que la mesure dément n'arme rien » (29/08), le total du jour qui alimente le bilan du sol depuis la 0.79.0 : inchangés, sous test.

### Visible à l'écran

`sensor_health` publie **`pluie_lame_voisin_mm`** et **`pluie_lame_station_mm`** côte à côte — c'est leur écart qui a expliqué le blocage du 09/09. Et le motif annonce désormais la lame : « Herbe mouillée: ressuyage après 1,2 mm de pluie (48 min restantes) ». Le blocage du 09/09 a coûté une demi-heure de recherche parce que rien à l'écran ne disait de quelle pluie il parlait.

`mower_travail_termine_minutes_jour` (0.82.0) est corrigé au passage, **deux fois**. Il n'était renseigné que sur le cycle traitant une complétion — deux ou trois fois par jour sur ~700 cycles. Et une fois cela réparé, il restait invisible : `_attrs_from_data` **filtre les valeurs `None`**, et tant qu'aucun travail ne s'est terminé la valeur était `None`. Trois listes blanches traversées, tests de câblage verts, et personne ne voyait rien — la variante « entité éteinte » du défaut n°1 du projet. La règle « une absence n'est pas un zéro » vaut pour une **mesure** dont la source peut se taire ; ce cumul-là est notre propre comptabilité, et « zéro minute de travail terminé aujourd'hui » est un fait connu. Vérifié sur l'installation le 10/09.

### Trois affirmations du code remises d'aplomb

- `_lire_progression_tonte` : « rien n'est branché sur une décision » — faux depuis la 0.61.0, ses sorties pilotent l'écriture de la tonte.
- « même délai que après un arrosage », à trois lignes du correctif : celui-ci n'en est plus que le **plafond**.
- La citation des 4,4 mm ne nomme plus d'auteurs : le titre et la revue, vérifiables, suffisent.

### Deux trous trouvés par la revue Codex, avant merge

- **Le total dérivé primait sans référence.** Au tout premier cycle — installation neuve, ou état d'exécution persisté perdu — le compteur s'initialise sur la lecture courante et le total du jour vaut 0. Or il a la **priorité** sur `capteur_pluie_24h` depuis la 0.79.0 : un zéro sans référence écrasait un capteur qui savait, lui, qu'il était tombé 10 mm le matin. Le bilan du sol perdait la journée entière et pouvait lancer un arrosage inutile. Il rend désormais `None` tant qu'il n'a aucune référence, et le capteur 24 h garde la main.
- **La lame maigrissait pendant le délai qu'elle avait armé.** La fenêtre se mesurait depuis *chaque* goutte, alors que le ressuyage court depuis la **dernière**. Une averse qui dure voyait donc son début expirer en cours de délai : 4 mm entre 12:00 et 14:00, puis la lame retombe à ~2 mm, le délai calculé passe de 180 à ~107 min — déjà écoulés — et la tonte repart une heure trop tôt. On remonte désormais le temps depuis la dernière hausse jusqu'au premier trou plus long que la fenêtre : **l'averse est prise entière, quelle que soit sa durée**.

⚠️ Le premier jet du test de non-régression du second **ne mordait pas** : à deux heures d'écart, l'ancienne règle gardait encore toutes les hausses. Il fallait se placer assez loin pour que le *début* de l'averse soit sorti de la fenêtre pendant que la dernière goutte y était encore. La mutation l'a montré.

### Vérification

Sept mutations, chacune vérifiée pour qu'elle fasse tomber le test visé — dont **le premier jet lui-même** (une hausse qui efface les précédentes), la fenêtre qui ne vieillit plus, les deux survies à une coupure, la station retirée du calcul, et les deux sources croisées à l'affichage.

Et trois de plus sur les correctifs Codex : le total dérivé qui reprime sans référence, la fenêtre remesurée depuis maintenant, et une averse ancienne qui n'expire jamais.

## 0.82.0

1308 tests verts. **Une journée de tonte découpée en travaux courts est enfin déclarée — sans qu'une coupe de bordure puisse le faire à sa place.**

### 164 minutes de lame, zéro tonte inscrite

Le 08/09/2026 la tondeuse est sortie **trois fois** : 15:29→16:27, 19:47→20:07, 20:44→22:11. Deux heures quarante-cinq de lame sur la pelouse.

Trois sorties, trois `task_id`, donc **trois travaux**. Le plancher de qualification s'appliquait au travail courant : chacun pris isolément restait sous les 90 min, le dernier compté à **88** — raté de deux minutes. Chaque complétion a été consommée en `travail_trop_court`, et la journée n'a rien inscrit.

Le 09/09 au matin : hauteur estimée montée de 5,1 à **5,3 cm**, `mowing_is_overdue` à `true`, **3 jours de retard** annoncés — sur une pelouse tondue la veille au soir.

Et ce n'était pas un accident isolé. Minutes réellement tondues du 04 au 08/09 : **188 · 135 · 149 · 0 · 164**. La machine sort presque tous les jours ; c'est le **découpage** qui passait sous le plancher.

### Ce n'est pas de l'affichage

`overdue_relaxed_baseline` (`decision_mowing.py`) ouvre une voie alternative vers `tonte_ok` **et contourne les blocages agronomiques**. Se croire en retard relâche des gardes qui devaient tenir. Le retard est un levier de décision, pas un compteur décoratif.

### Le premier correctif était faux, et c'est une revue adversariale qui l'a montré

Le premier jet qualifiait sur `max(cumul du travail, mower_mowing_minutes_today)`. Quatre relecteurs indépendants ont convergé sur le même défaut **bloquant**, rejoué sur le code :

| heure | événement | verdict |
|---|---|---|
| 09:00 | la tâche A naît | — |
| 11:40 | A à **55 %**, journée 160 min — puis elle se bloque et rentre. Elle n'atteindra jamais 100 %. | `travail_en_cours` |
| 18:00 | coupe de bordure B | — |
| 18:12 | B à 100 %, journée 172 → `max(12, 172) = 172` | **`declaree`** |

Une bordure de **douze minutes** inscrivait la tonte du jour avec les minutes d'un travail abandonné : hauteur ré-ancrée sur la lame, retard remis à zéro, surveillance endormie sur une pelouse tondue à 55 %. C'était le défaut du 30/08/2026 revenu par une autre porte.

`mower_mowing_minutes_today` mesure du temps de lame **toutes tâches confondues, abouties ou non**. Il ne prouve rien sur ce qui a été mené à son terme.

### Ce qu'on cumule à la place : les travaux **terminés**

Chaque travail ne verse que ses minutes propres — base du jour déjà retranchée (0.69.0) — et **il ne les verse qu'en atteignant 100 %**. La somme dit exactement ce qu'on veut savoir : combien de temps de lame a été mené à son terme aujourd'hui.

- Le 08/09 : 58 → 77,4 → **164,6** — les trois travaux étaient terminés, la tonte part au troisième.
- Le travail abandonné à 55 % : ses 160 minutes ne sont versées **nulle part**. La bordure vaut 12, et 12 ne franchit rien.
- Le 30/08 (déclarée à 49 % de progression) : aucun travail terminé, donc rien versé, donc rien déclaré.
- Le 03/09 (337 min dont 86 % appartenant à la veille) : le cumul est indexé sur la date. Ce chemin reste fermé, et un test le prouve au lieu de l'affirmer.

Le cumul est **persisté des deux côtés** : sans cela, un redémarrage en milieu de journée oublierait les travaux déjà terminés et une soirée découpée redeviendrait indéclarable — le défaut qu'on corrige, sur une installation qui redémarre souvent.

### Un nouvel attribut, parce qu'un automatisme muet est indiscernable d'un automatisme cassé

`mower_travail_termine_minutes_jour` publie la grandeur **réellement comparée au plancher**. Sans elle, `travail_trop_court` ne dit pas s'il manquait dix minutes ou une heure — et c'est précisément ce qu'il fallait savoir pour trouver le défaut du 08/09. Trois listes blanches traversées, une de plus dans le banc de câblage.

### Trois affirmations du code qui mentaient

- `_suivre_pluie_du_jour` : « **observation seule, n'alimente aucune décision** ». Faux depuis la 0.79.0 — elle alimente le bilan du sol. Vérifié sur la station dans la nuit du 08→09/09 : compteur 2,1 → 2,3, cumul du jour 0,2 mm, réserve 10,8 → 11,0.
- `_lire_progression_tonte` : « **rien n'est branché sur une décision** ». Faux depuis la 0.61.0 — ses deux sorties pilotent l'écriture de la tonte. Le mensonge jumeau du précédent, resté debout côté tonte.
- La docstring de `_declarer_tonte_du_jour` annonçait « quatre gardes » et oubliait celle du **travail terminé** — née du 30/08, et précisément celle sur laquelle l'ouverture s'appuie. Elles sont cinq.

Et la ligne de journal lisait `suivi.get("mower_job_id")`, une clé que `_suivre_travail_tondeuse` n'a jamais produite : elle s'appelle `mower_job_followed_id`. Depuis la 0.61.0 le journal écrivait « travail ? » à chaque déclaration, là où l'identifiant sert. Sous test.

### Vérification

Sept mutations, chacune vérifiée pour qu'elle fasse tomber le test visé — dont **le premier correctif lui-même** (`max` avec le compteur du jour), désormais attrapé par le test du travail jamais terminé. Les six autres : retour au comportement 0.81.0, le compteur du jour seul, un cumul qui ne repart pas à zéro le lendemain, une complétion re-offerte, le cumul sauvegardé mais non restauré, et la clé retirée des attributs du capteur.

## 0.81.0

1299 tests verts. **En dessous du minimum utile, on n'arrose plus du tout.**

### La porte que la 0.80.0 avait entrouverte

Désarmer le plancher d'activation une fois le produit dissous était juste — mais l'objectif retombait alors sur le besoin réel, si petit soit-il. Mesuré en production **une heure après** la mise en service de la 0.80.0 : objectif **0,2 mm**, annoncé et « recommandé ».

0,2 mm sur trois zones, c'est **cinquante secondes de vanne chacune**. Ça mouille le feuillage, ça s'évapore, ça n'atteint pas les racines — et ça consomme un cycle complet. Exactement le phénomène qu'on avait diagnostiqué sur la bruine du 06/09.

### Deux logiques, une seule était codée

- Un plancher d'**activation** doit **remonter** la dose : pour dissoudre un produit épandu, il faut en mettre assez.
- Un plancher **hydrique** doit **refuser** : si le besoin est dérisoire, on n'arrose pas du tout.

Les phases d'application ne connaissaient que la première. `_profile_for_normal` possède la seconde depuis toujours (`useful_threshold`) — et c'est pour ça qu'un arrosage de 0,2 mm est impossible en mode Normal, où le déclencheur MAD (6 mm) et la dose minimale de session (5 mm) le rendent inatteignable.

La même règle s'applique désormais aux phases d'application, avec le plancher **brut** de la phase — celui d'avant désarmement — comme seuil d'utilité.

### Une seule source pour le seuil et le plancher

`_plancher_brut_de_phase` suit le même ordre de priorité que le calcul de la cible : la politique quand elle définit une plage, la table des modes sinon. Un seuil d'utilité qui divergerait du plancher laisserait une bande de doses ni remontées ni refusées — « deux descriptions du même fait », le défaut que ce projet traque.

### Vérification

Sur le cas réel reproduit, incorporation terminée : objectif **0,0 mm** et `arrosage_recommande` à **False**, au lieu de 0,9 mm « recommandé ». Avant incorporation, les 5 mm d'activation restent intacts. Deux mutations vérifiées.

## 0.80.0

1298 tests verts. **Le plancher d'activation s'éteint quand le produit est déjà dissous.**

### Le cas réel

Floranid Twin Permanent épandu le 07/09/2026, **incorporé automatiquement le soir même** — 5 mm sur trois zones, `application_post_watering_status = "termine"`. Le lendemain, sous la pluie, réserve à **11,3 mm sur 12** et déplétion de **0,7 mm** pour un seuil MAD à 6, l'assistant annonçait **5 mm de plus** pour le matin suivant, motif « Fertilisation active ».

Le plancher d'activation existe pour dissoudre un produit épandu, et il avait raison la veille. Le lendemain, il ignorait la seule information qui compte : **le produit était déjà dissous**.

⚠️ L'arrosage n'est pas parti, mais **par accident** : la phase Fertilisation dure 2 jours et expirait à minuit, avant le créneau de 03h45. Scarification en dure **7** — le même enchaînement y aurait arrosé un sol détrempé six jours d'affilée.

### Trois endroits posent ce plancher, pas un

C'est ce qui a rendu le correctif difficile, et le banc de mutation l'a montré à chaque étape :

1. le **clamp** `_clamp(besoin, minimum, maximum)`, qui remonte la cible au minimum de la politique **avant tout garde-fou** ;
2. la branche « politique » de `_profile_for_agro_phases` (`target_range.min_mm`) ;
3. la branche « table des modes » (`MODE_MIN_WATERING_MM`).

Les phases d'application définissent toutes un `event_target_mm` : elles passent donc par 1 et 2, jamais par 3. Câbler d'abord la branche 3 seule n'a **rien changé**. Câbler ensuite 2 et 3 n'a **rien changé non plus** — le clamp avait déjà remonté la cible, et aucune fonction en aval ne pouvait la redescendre. Le drapeau arrivait pourtant bien à `True`.

Les trois points passent désormais par une **règle unique**, `_plancher_activation_effectif`, et un test compte les points d'application pour qu'aucun ne reparte seul.

### Ce qui n'est PAS désarmé

Seules les phases où le plancher sert à **activer un produit** : Fertilisation, Biostimulant, Agent Mouillant, Scarification. Les planchers de **Normal (10 mm)** et **Sursemis (0,5 mm)** sont agronomiques — « en dessous, arroser ne sert à rien » — et restent en place quoi qu'il arrive. Un test le verrouille.

Et une mémoire muette ne désarme rien : l'absence d'information n'est pas une incorporation faite.

### Vérification

Sur le cas réel reproduit : objectif **5,0 mm** avant incorporation, **0,9 mm** après — l'objectif redevient le besoin réel au lieu d'un forfait. Trois mutations vérifiées, une par point de câblage.

## 0.79.0

1293 tests verts. **Le total de pluie dérivé du compteur propre devient la source du bilan sol.**

### La condition posée par le code est remplie

Depuis la 0.74.0, l'intégration dérive elle-même un total journalier depuis un compteur cumulatif monotone (`capteur_pluie_cumul`), avec cliquet sur le maximum et mémoire persistée. Cette valeur était **volontairement en observation seule** : « tant qu'on ne l'a pas vue vivre sur une vraie station ».

Elle a vécu, le 08/09/2026 : pluie réelle dès 01h36, `precipitation` montant de 0,1 mm toutes les ~15 min, 0 → 1,4 mm. Total dérivé **exact**, pic suivi, **aucun gain rejeté**, réserve créditée de +0,3 mm, aucun arrosage déclenché à tort.

### Pourquoi c'est mieux que le cumul journalier fourni

| | station (dérivé) | Netatmo du voisin |
|---|---|---|
| même épisode, 08/09 | **1,4 mm** | 0,7 mm |
| peut redescendre ? | non, monotone par construction | **oui** — 3,6 → 3,0 mm mesuré le 30/08 |
| remise à zéro | à NOTRE minuit | plusieurs dizaines de minutes après |
| emplacement | le jardin | chez le voisin |

Un cumul journalier qui **perd** 0,6 mm est physiquement impossible ; c'est ce défaut qui avait imposé le cliquet correctif `appliquer_cliquet_pluie`. Le total dérivé n'en a pas besoin : il n'ajoute que les hausses au-dessus du pic du jour.

### Le câblage

Priorité dans `_resolve_precipitation_inputs` : total dérivé → `capteur_pluie_24h` → prévision. **Sans `capteur_pluie_cumul` configuré, rien ne change** — le paramètre vaut `None` et l'ordre historique s'applique.

⚠️ Le libellé de source est `capteur_cumul_station`, et le préfixe est porteur : `gazon_brain` teste `startswith("capteur")` pour décider si la valeur est une **mesure** (à créditer au sol) ou une **prévision** (à ignorer). Le renommer sans ce préfixe ferait silencieusement disparaître la pluie du bilan — une mutation le vérifie.

### Une garde qui gardait la mauvaise porte

`test_elle_n_alimente_aucune_decision` promettait : « le jour où une décision voudra la lire, ce test tombera et forcera la discussion ». **Il n'est pas tombé.** Il vérifiait l'absence de la clé dans les quatre modules de décision, alors que la consommation passe par le **coordinateur** — le cinquième fichier. Un faux vert.

Il est remplacé par l'affirmation du nouveau contrat, et son remplacement est expliqué dans le test lui-même pour que la leçon ne se perde pas.

## 0.78.0

1291 tests verts. **L'arrosage du sursemis n'est plus seulement calculé : il s'exécute — étape 2 sur 2.**

### Calculé, publié, jamais appliqué

Le programme de micro-cycles semis existait déjà en entier : 1,5 mm en Germination, 3,0 en Enracinement, 2,5 en Reprise, créneaux 10h/12h/14h/16h. Il était publié à chaque cycle et **le portail du coordinateur le refusait systématiquement** en `auto_not_allowed`. Sur les dix jours de germination, 45 mm devenaient environ **35 appels de service à la main**, sur un semis qui ne pardonne pas une surface sèche.

Deux verrous en série :

- `auto_ok` (`decision_watering.py:1694`) listait Normal, Fertilisation, Biostimulant, Agent Mouillant et Scarification — **pas Sursemis**.
- Les trois sorties de `_resolve_sursemis_override` forçaient `arrosage_auto_autorise=False`.

### La liste blanche qu'on oublie

Ajouter « Sursemis » à `auto_ok` **ne suffisait pas** : les résolveurs de priorité court-circuitent par un `return` anticipé le bloc qui pose `arrosage_auto_autorise = auto_ok`. Un override n'avait donc aucun moyen de savoir si l'automatisme était permis — il ne pouvait que le refuser en dur.

`auto_ok` est désormais publié dans `priority_state` et relu par l'override. C'est la variante exacte du défaut n°1 du projet, et un test lit le dictionnaire pour l'empêcher de revenir.

### Le contrat public ne ment plus

Quand un cycle est dû et l'automatisme permis, `type_arrosage` passe de `manuel_frequent` à `auto` : annoncer « manuel » pendant que le coordinateur arrose seul, c'était la façade qui mentait. `watering_strategy` continue de porter `semis_frequent`, la nuance de régime n'est pas perdue.

### Le garde qui rend cette version livrable

`auto_irrigation_enabled` est **à False par défaut** (`DEFAULT_AUTO_IRRIGATION_ENABLED`) et reste vérifié en amont : personne ne se réveille avec un arrosage autonome qu'il n'a pas armé. Vérifié par un test dédié, et le contourner fait tomber trois tests.

| switch utilisateur | objectif | type | `arrosage_auto_autorise` |
|---|---|---|---|
| OFF (défaut) | 1,5 mm | `manuel_frequent` | **False** |
| ON | 1,5 mm | `auto` | **True** |

### Ce que le banc de mutation a dit, et qui est consigné

⚠️ La clause `sursemis_allowed and surface_cycle_mm > 0` de `sursemis_auto_ok` est **redondante** : en la retirant, aucun test ne rougit — un garde en amont ferme déjà le robinet quand le cycle est reporté. Elle est **conservée volontairement**, parce que c'est la seule ligne du projet qui ouvre un arrosage autonome dans une phase jamais exercée en production, et que l'intention doit être lisible au point de décision. Le test concerné le dit explicitement pour que personne ne s'y fie à tort.

## 0.77.0

1286 tests verts. **Le Sursemis n'usurpe plus le verdict de la tonte — étape 1 sur 2 du déverrouillage.**

### Une usurpation, pas un bug

`_resolve_sursemis_override` rendait, sur ses **trois** sorties, deux verdicts qui ne lui appartiennent pas : `tonte_autorisee` et `arrosage_auto_autorise`. Or `base_bundle` porte déjà `mowing_bundle["tonte_autorisee"]` et `tonte_statut` (`decision_watering.py:654-655`), et `decision.py:451` fait le **ET** des deux bundles. Les figer à `False` écrasait donc la décision de `decision_mowing`.

Conséquence : **la tonte était interdite les 45 jours de la phase**, alors que le module de tonte ne bloque que Germination et Enracinement — 24 jours (`_SURSEMIS_MOWING_BLOCKED_SUBPHASES`, `decision_mowing.py:185`). Deux sorties de l'intégration se contredisaient, et c'est l'arrosage qui gagnait.

### Le verrou était circulaire

`seeding_transition_ready` exige **deux tontes déclarées** depuis le début de la phase (`guidance.py:361`) — des tontes que la phase interdisait elle-même. Un sursemis ne pouvait donc **jamais** se terminer.

Mesuré sur un snapshot réel, Sursemis démarré le 01/03 :

| | avant | après |
|---|---|---|
| J+5 Germination | interdite | **interdite** (inchangé, c'est le bon verdict) |
| J+18 Enracinement | interdite | **interdite** (inchangé) |
| J+30 Reprise | interdite | **autorisée avec précaution** |
| transition prête (2 tontes) | jamais | **oui** |

### Ce qui n'est PAS dans cette version

`arrosage_auto_autorise` reste forcé à `False` : le programme de micro-cycles semis est toujours calculé sans jamais être appliqué. C'est l'étape 2, volontairement séparée — c'est elle qui fait couler de l'eau en autonomie, trois à quatre fois par jour, dans une phase que l'installation n'a **jamais exercée**. Elle doit être observée sur un premier cycle réel avant de tourner 45 jours sur un semis.

### Ce qui le prouve

Quatre tests. Le correctif tient en une **absence** — trois lignes retirées — donc rien n'empêcherait de les réintroduire « pour être sûr » : un test lit le corps de la fonction et refuse toute réécriture de la tonte sur n'importe laquelle des trois sorties.

⚠️ **Couverture mesurée au banc de mutation**, et consignée dans le test : des trois sorties, seule la dernière est atteinte par un test comportemental — les deux premières dépendent de `runtime_context["semis_followup_state"]`, que `build_decision_snapshot` n'expose pas. Fabriquer un `state` à la main (12 clés dont trois objets composites) reviendrait à tester une fiction. Dette assumée.

## 0.76.0

1282 tests verts. **Les valeurs que le modèle utilise réellement sont enfin visibles.**

### Le drapeau dit d'où, jamais ce que ça vaut

`sensor_health` publiait un booléen par entrée — « la mesure vient bien de ton capteur, pas du repli ». Ces drapeaux sont justes depuis leur correction : ils testent la SOURCE, avant repli. Mais aucun ne dit **quel nombre** est entré dans le modèle après conversion.

Or c'est là que vivent les pièges. `wind_speed_to_kmh` et `pression_vers_hpa` transforment la valeur selon l'unité **déclarée par l'entité** : une unité absente ou inattendue passe sans un mot, tous les voyants au vert. Le Shelly/Ecowitt WS90 publie des **kPa** — sans `pression_vers_hpa` il donnerait 101 hPa au lieu de 1010, en plein calcul FAO-56, et `eto_pressure_measured` resterait `true`.

Trois questions restaient sans réponse, vécues le 06/09/2026 :

- **décomposer une ET0 surprenante** — le vent ? la température ? l'humidité ? Il fallait refaire le calcul à la main depuis les entités sources.
- **vérifier qu'un changement de capteur a bougé le nombre** — les drapeaux ne distinguent pas le capteur A du capteur B, tous deux « configurés ».
- **contrôler une unité** — un capteur publiant des m/s sans déclarer son unité donnerait un vent **3,6 fois trop faible**, `wind_measured` au vert. Et le vent est le levier majeur de l'ET0 : le repli est chiffré à **+36 %** sur les entrées réelles du 29/07.

### Ce qui est ajouté

Trois valeurs, unité dans le nom, à lire **avec** le drapeau voisin : `temperature_utilisee_c`, `humidite_utilisee_pct`, `vent_utilise_kmh`. Ce sont les valeurs **résolues** — celles qui entrent réellement dans le modèle, repli compris : sous repli le drapeau tombe au rouge et la valeur reste lisible, ce qui rend enfin visible le genre d'incident du 29/07 où **deux secondes de repli du vent** ont posé le pic d'ET0 du jour à 12,4 avant que le cliquet ne le fige.

`sensor_health` étant déjà publié en bloc, aucune liste blanche à traverser.

### Ce qui le prouve

Quatre tests, dont un sur le **point d'appel** : les trois paramètres ont un défaut `None`, donc un câblage oublié laisserait les clés publiées mais éternellement nulles sans qu'aucun test de la fonction seule ne le voie. Deux mutations vérifiées — débrancher le point d'appel fait tomber **trois** tests, transformer l'absence en zéro en fait tomber un.

## 0.75.0

1278 tests verts. **Deux correctifs trouvés par la revue Codex sur la PR #48 — les deux dans mes propres commits de cette série.**

### Une alerte publiée sur une entité éteinte

La 0.74.0 ajoutait `sol_ecart_raccord_mm` à la seule « Réserve utile actuelle ». Cette entité porte `_attr_entity_registry_enabled_default = False` et la catégorie `DIAGNOSTIC` : **sur une installation neuve elle n'est même pas créée**. Le garde construit pour rompre une semaine de silence sur le registre du sol était donc lui-même muet — et le CHANGELOG de la 0.74.0 promettait pourtant l'attribut « publié sur l'objectif d'arrosage ». Le code contredisait sa propre note de version.

L'attribut est désormais publié aussi sur `sensor.gazon_intelligent_objectif_d_arrosage`, entité active par défaut, via un helper unique (`_ecart_raccord_publiable`) appelé par les deux capteurs : deux copies de la même condition, c'est deux descriptions du même fait qui finissent par diverger.

### Un cliquet qui ne pouvait plus se rouvrir

La 0.70.0 a appris à la coordination que `idle` ne prouve pas une rentrée : tant qu'une passe est ouverte, la tondeuse est déclarée « dehors ». Correct pour une machine qui annonce `docked` ou la charge — elle finit toujours par le dire.

Mais `mower_is_docked` dérive de cette présence, `au_garage` en dérive, et **une passe ne se ferme QUE si `au_garage`**. Sur une tondeuse dont `idle` est le seul état de repos, la boucle se refermait sur elle-même : sortie, passe ouverte, retour lu « dehors », passe jamais fermée, cliquet jamais relâché. `mower_is_safe_for_watering` restait faux **pour toujours** et plus aucun arrosage ne partait. La Landroid Vision y échappe — elle signale `docked` et la charge.

Le cliquet ne vaut désormais que pour les machines dont un signal FORT de station a déjà été observé (`dock_signal_vu`, mémoire collante rangée **dans** le carnet de passes — déjà sérialisé et restauré en bloc, donc aucune des deux listes blanches à traverser). Faux par défaut : au pire on retombe quelques cycles sur le comportement d'avant la 0.70.0, là où l'inverse bloquait l'arrosage définitivement.

### Ce qui manquait pour que ça se voie

Aucun test ne couvrait `sol_ecart_raccord_mm` — c'est par là que le défaut est passé. Quatre mutations vérifiées, chacune faisant tomber un seul test, le bon : cliquet privé du drapeau, drapeau jamais posé, argument retiré du point d'appel, attribut retiré de l'entité active.

## 0.74.0

1274 tests verts. **Un raccord rompu dans le registre du sol ne peut plus passer inaperçu.**

### Ce qui s'est passé, et que rien n'avait signalé

Contrôle manuel des **119 raccords** du registre le 04/09/2026 — en comparant l'*ouverture* de chaque jour à la *clôture* de la veille. Quatre étaient rompus, chacun valant exactement `etp_elapsed_mm − etp_mm`, la signature de l'ancien garde de clôture qui remplaçait la mesure par l'estimation :

```
22 → 23/08   −2,9 mm        28 → 29/08   −2,0 mm  (le plafond absorbe 0,7)
29 → 30/08   −2,3 mm        30 → 31/08   −1,6 mm
```

Le stock avait resaturé à 24,0 mm le 28/08 : seules les pertes d'après comptaient encore, soit **5,9 mm**. Sans elles le stock valait 14,6 au lieu de 8,7 — réserve utile pleine, déplétion nulle, **aucun arrosage dû**. L'arrosage prévu partait sur une erreur de comptabilité.

La cause est corrigée depuis la **0.63.0**, et les quatre raccords du 31/08 au 04/09 sont propres — vérifié. Mais **rien n'aurait détecté la suivante**. C'est ce silence que cette version casse.

### L'invariant

À la bascule de date, la clôture **recalculée** de la veille doit égaler celle **déjà stockée** : les deux partent de la même ouverture, de la même pluie, du même arrosage et de la même ETc mesurée. Un écart signifie qu'une des deux voies a utilisé autre chose.

⚠️ **Sauf sur une journée tronquée**, où la clôture retombe volontairement sur l'estimation : l'écart y est délibéré. Crier là-dessus rendrait l'alerte inutilisable — c'est exactement le piège dans lequel l'ancien garde était tombé, en jugeant l'ampleur au lieu de la couverture.

Quand la rupture est réelle : un `WARNING` nommé dans le journal, la valeur écrite dans l'entrée du registre, et l'attribut **`sol_ecart_raccord_mm`** publié sur l'objectif d'arrosage. Publié **seulement s'il y en a un** — sa présence est l'alerte.

⚠️ L'écart **survit aux cycles de la journée** : sans ce report il disparaîtrait deux minutes après avoir été détecté, aussi silencieusement que le défaut qu'il surveille.

### Correction du stock

Les 5,9 mm ont été recrédités le 04/09 sur décision de Kévin, via `recalibrate_reserve` avec **`figer_la_journee: false`** — le drapeau qui réécrit la réserve d'*ouverture* et laisse la journée se dérouler normalement, par opposition au défaut `true` qui fige la valeur jusqu'à minuit (celui-là est pour « j'ai sondé mon sol au tournevis »). Stock 8,7 → 14,6, réserve utile de nouveau pleine, arrosage du lendemain annulé.

## 0.73.0

1269 tests verts. **La date de prochain arrosage séchait le sol au modèle pendant que la décision suivait la mesure.**

Relevé à 20:00 : `date_prochain_arrosage_estime` annonçait **01/09 → 02/09**, puis **02/09 → 03/09**, puis **03/09 → 04/09** — « demain » trois jours de suite, avec `arrosage_recent_7j = 0` sur toute la période. Aucun arrosage n'est parti.

La formule séchait le sol à **4,1 mm/j** (modèle ET0 × Kc) quand le registre en débitait réellement **2,9**.

⚠️ **Et c'est d'abord une question de cohérence.** Depuis la 0.71.0, la projection de déclenchement utilise le rythme **mesuré**. Laisser l'estimation d'affichage sur le modèle, c'était publier deux réponses à la même question — la famille de défaut n°1 de ce projet, reproduite par mon propre correctif de la veille.

Le biais est désormais calculé **une seule fois**, en amont, et sert aux deux.

⚠️ **`etc_mm` reste brut** : `guidance._profile_for_normal` applique le biais lui-même. Le pré-multiplier l'appliquerait **deux fois**, et la soif projetée tomberait à 0,46 de sa valeur au lieu de 0,68. Un test verrouille ce piège.

⚠️ **Constat non vérifié à l'origine** : les deux sceptiques de l'audit avaient été coupés par une limite de session. Repris à zéro — la seconde cause qu'il avançait (« la marge est évaluée sur la réserve de l'instant, pas à l'aube ») n'a **pas** été retenue : l'écart entre 19 h et l'aube suivante est de ~0,3 mm, et le terme `− rate` de la formule couvre déjà une journée entière de séchage.

### Le seuil de température à 27 °C : diagnostic consigné, pas de bande morte

Le score de stress contient **neuf seuils entiers** et un seul est amorti. Chaque palier vaut +1 point et « vigilance » commence à 3 : tout franchissement fait basculer un rang entier. Relevé du 01 au 04/09 (501 mesures) :

| facteur | seuils | valeurs réelles | franchissements (4 j) |
|---|---|---|---|
| **ET0** | 3 / 4 / 5 mm | 3,6 – 4,8 | **9 en un après-midi** |
| température | 27 / 30 / 34 / 38 °C | 15 – 29,4 | 3 (cycle jour/nuit) |
| humidité | ≤ 40 / ≤ 30 % | 60 – 89 % | 0 |
| vent | 15 / 25 km/h | 6 – 8 km/h | 0 |
| déficit | 8 mm | — | 0 |

L'ET0 est la seule à osciller *au voisinage* d'un seuil : c'est une grandeur **calculée** qui hérite du bruit du rayonnement, du vent, de l'humidité et de la pression. La température a l'inertie thermique de l'air — bruit médian **0,10 °C**, 53 changements de sens sur 500 mouvements, et ses trois franchissements sont des transitions franches tenues des heures.

⚠️ **Le défaut reste générique et latent** : une après-midi qui hésiterait autour de 27,0 °C reclignoterait comme l'ET0 autour de 4,0. Mais étendre la bande demande une largeur **par facteur**, et une largeur ne s'invente pas — celle de l'ET0 (0,4 mm) est le genou *mesuré* de sa propre courbe de clignotement. Tant qu'aucun de ces seuils n'oscille, il n'y a pas de courbe à mesurer. Diagnostic consigné dans le code et dans l'onglet « Santé du code », à rouvrir le jour où l'un d'eux se met à battre.

## 0.72.0

1267 tests verts. **Une retenue était annoncée alors que rien n'était demandé.**

Le 03/09 à 04:00:15,217 l'humidité passe de 77,5 à 88 %. L'affichage bascule de « Aucun besoin » à « **Conditions trop humides** » — avec `besoin_mm = 0`, `depletion_mm = 0` et une réserve à **12/12**. Rien n'était demandé : annoncer une retenue laissait croire qu'on refusait de l'eau au gazon. Second épisode le même jour, de 09:30:29 à 10:19:16.

**Le mécanisme.** `humidite_excessive` s'arme sur le seul `humidite >= 85`, sans regarder le besoin — là où ses voisins immédiats se gardent :

```
pluie_prevue_suffisante  → and not _sol_reclame_de_l_eau
sol_deja_humide          → and not _ledger_demande_eau
humidite >= 85           → (aucun garde)
```

Puis l'affichage promeut ce motif au-dessus de « aucun besoin », par un correctif de juillet dont l'intention était juste : ne pas annoncer « réserve suffisante » quand on retient volontairement l'eau.

**La correction, côté affichage seulement.** Un motif ne remplace « aucun besoin » que s'il a **effectivement** retenu de l'eau — `_motif_de_blocage_effectif`, **une seule définition** partagée par les deux capteurs qui l'affichent.

⚠️ **L'autre sens est verrouillé** : dire « aucun besoin » alors qu'on refuse de l'eau à un sol qui en demande serait le mensonge inverse — précisément celui que ces capteurs corrigeaient déjà (31/07, « Non requis » avec `garde_fou_hebdomadaire` en attribut). Et **absence ≠ zéro** : sans besoin publié, on garde le motif.

⚠️ **Non touché volontairement** : le motif reste posé dans la décision. Le neutraliser là ferait passer l'objectif par le plancher de dose et changerait la fenêtre de rafraîchissement — une correction d'affichage n'a pas à déplacer une décision d'arrosage.

⚠️ Le banc a montré que seul l'un des deux capteurs était couvert : retirer le helper de « prochain arrosage » ne faisait tomber aucun test.

### Étape 4 : le constat est réfuté

« La hauteur estimée aveugle à la seconde déclaration » — le gel de 25 h venait de la **fausse déclaration du 03/09 à 01:56**, causée par le cumul de travail que la 0.69.0 corrige. Vérifié le 04/09 : la hauteur repousse normalement (5,7 cm, +0,24 cm/j). Le « zéro pousse le jour de la tonte » est un choix documenté dont l'erreur est bornée à 0,1 cm — sous l'arrondi du capteur.

## 0.71.0

1263 tests verts. **Deux ETc du même jour coexistaient : le sol se vidait au rythme mesuré pendant que la décision projetait le modèle.**

### Ce qui a été mesuré

Relevés à 23:59, sur des journées complètes :

| jour | ETc **mesurée** (intégrale horaire) | ETc **estimée** (ET0 × Kc) | écart |
|---|---|---|---|
| 02/09 | 2,991 mm | 4,6 mm | −35 % |
| 03/09 | 2,886 mm | 4,2 mm | −31 % |

Le ledger **débite** la mesurée (intégrale du taux horaire FAO-56, depuis le passage à l'horaire). La projection d'aube qui décide du déclenchement utilisait la **estimée**. Quatre jours d'affilée : ce n'est pas du bruit.

⚠️ **Vérifié avant de corriger** : les deux grandeurs sont bien des **ETc** avec le même Kc (`gazon_brain` passe `etp_mm = etp × kc` au ledger) — l'écart n'est pas un facteur Kc caché. Et l'intégrale horaire est fiable : son code écarte explicitement les trous de capteur, et l'ET0 horaire n'a eu aucune interruption le 02/09.

### La correction

On ne peut pas mesurer le futur : à l'aube la fraction écoulée est quasi nulle et la projection vaut « toute l'ETc du jour ». On corrige donc le **modèle** par le biais qu'il a réellement montré sur les journées **déjà closes** — `soil_balance.biais_etc_mesure`, rapport médian sur sept jours, chez Kévin ≈ 0,68.

⚠️ **Bornes asymétriques, et c'est le garde-fou** : plafond à 1,0, le biais ne peut que *réduire* la projection — le modèle seul reste la borne prudente. Plancher à 0,5, un rapport aberrant ne peut pas effondrer la soif projetée et retarder un arrosage nécessaire. **Médiane** et non moyenne. `None` sous trois journées exploitables → le modèle seul reprend la main.

⚠️ Seules les journées **couvertes jusqu'au bout** comptent, via le prédicat de clôture existant : deux définitions de « journée complète » finiraient par diverger.

**Conséquence, mesurée** : réserve 9,5 mm sur 12 utiles, ET0 5,2 à l'aube. Le modèle seul déclenchait **5 mm** d'arrosage ; corrigé, il attend. **L'arrosage part plus tard** — c'est l'effet arbitré par Kévin le 04/09/2026.

### Ce que le banc a rattrapé

Sur huit mutations, **trois** ont survécu au premier jet.

- La projection ne s'applique pas sans `et_elapsed_fraction` : le repli vaut 1,0, donc « rien à venir », et le biais n'a aucune prise. Mon test était vert **sans exercer une seule ligne**.
- Une seule journée tronquée ne déplace pas une médiane : il en faut trois, et les plus récentes, pour que le filtre se prouve.
- Le commentaire de `guidance.py` affirmait « c'est bien l'ETc que le ledger débite (0.17.3) » — faux depuis le passage à l'horaire. Corrigé, avec les mesures et l'arbitrage consignés sur place.

## 0.70.0

1253 tests verts. **`idle` était lu comme « rangée » : une tondeuse en plein jardin était déclarée rentrée.**

### Ce qui a été mesuré

Sortie du 02/09 de **22:40:18 à 00:39:52** — jamais `docked`, jamais en charge, batterie 91 → 10 sans discontinuer. À **23:54:12,171** le robot annonce `idle` dans le jardin (son capteur d'erreur passera à `trapped_timeout` 18 ms plus tard, trop tard pour ce cycle) :

```
tondeuse_statut        = "au_repos"
mower_presence_label   = "Tondeuse rangée"
mower_is_docked        = true
mower_pass_in_progress = true → false     ← la passe est clôturée en pleine tonte
mower_last_pass_minutes = 73,2  (91 → 52 %, "retour_autonome")
mower_autonomous_return_battery_median = 85 → 78
```

La sortie a fini en **trois entrées au carnet** au lieu d'une (73,2 · 0,0 · 42,3 min), et le profil appris porte un « retour autonome à 52 % » qui n'a jamais eu lieu.

⚠️ **Et ce n'est pas qu'un défaut de carnet** : `mower_is_safe_for_watering` vaut `ready and is_docked`. Une tondeuse déclarée rangée alors qu'elle est dehors **autorise l'arrosage sur une pelouse occupée**. La coordination était désactivée ce soir-là ; elle est active depuis.

### La correction

Le savoir était déjà écrit dans `mower_adapter._status_label` — « le robot annonce `idle` quand il est immobilisé en plein jardin ». Et dans le domaine `lawn_mower` de Home Assistant, l'état rangé standard est `docked`, pas `idle`.

Une **passe ouverte** dit exactement ce que `idle` ne dit pas : elle est sortie et n'est pas revenue. Les signaux **forts** (`docked`, charge, tonte, retour) font les transitions ; `idle` ne fait que conserver l'état déjà prouvé.

⚠️ **L'autre sens est verrouillé par un test** : sans passe ouverte, `idle` reste une rentrée. Beaucoup de tondeuses n'annoncent que `idle` à la station — inverser cela aurait bloqué l'arrosage en permanence.

### Portée corrigée par la double vérification

Le constat d'origine annonçait « 74 minutes de blocage disparues ». **C'est faux** : sur la sortie 18:23 → 19:47, le code `trapped_timeout` force le statut « erreur », donc la position « inconnue », donc la passe est restée ouverte et `mower_blocked_minutes_today` est bien monté à 74. Ce cas-là n'était pas concerné.

⚠️ Le banc a montré que je testais la fonction et **pas le câblage** : neutraliser le helper ou retirer l'argument du point d'appel ne faisait tomber aucun test. Un test part désormais de l'état de la tondeuse et va jusqu'à la présence publiée. Et sur les trois points d'appel, seul celui qui peut agir porte l'argument — les deux autres sont les chemins dégradés où `tondeuse_connectee` est `False` et où la position vaut « inconnue » avant tout examen.

Un test de séquence rejoue la sortie complète, échantillonnée toutes les 2 minutes : **trois passes sans le correctif** (70 · 0,0 · 38 min), **une seule avec**. ⚠️ Un premier jet sautait de 72 minutes d'un coup — `_minutes_creditables` plafonne les trous, donc aucune minute n'était créditée et les fragments tombaient comme fantômes : le test aurait été vert pour la mauvaise raison. Et il importait `mower_coordination` à l'exécution, ce qui récupérait le faux module posé par `test_init.py`.

### Le constat « passe fantôme retenue par `a_ete_bloquee` » est RÉFUTÉ

L'audit proposait aussi d'écarter les passes « bloquee » à zéro minute bloquée. Vérification faite : le fantôme du 02/09 portait **0,8 minute de blocage mesuré** (`mower_blocked_minutes_today` 74,0 → 74,8) — il entrait par la clause `bloquees > 0`, pas par le drapeau.

Et durcir ici serait **nuisible** : `minutes_bloquees` se crédite depuis l'échantillon *précédent*, donc un blocage réel plus court qu'un cycle crédite légitimement 0,0. On perdrait de vrais blocages courts sans rien empêcher. L'arbitrage est consigné dans la docstring de `_passe_a_retenir`. La vraie cause du fantôme était la fausse rentrée sur `idle`, corrigée ci-dessus.

## 0.69.0

1246 tests verts. **Le cumul du travail comptait la journée entière, pas le travail — et le plancher anti coupe-de-bordure était devenu inopérant.**

### Ce que l'installation a montré

```
02/09 21:00  tâche 345a423c née vers 20:31 → 185,8 min DÈS SA NAISSANCE
03/09 01:00  tâche 67ba4fa7 née vers 23:58 → 328,5 min pour 39,4 du jour
03/09 19:20  même tâche                    → 337,1 min pour ~48 min réelles
```

**86 % du cumul appartenait à la veille**, dont à un travail déjà déclaré. Le plancher de 90 minutes était donc franchi en permanence : une **coupe de bordure de 16 minutes** l'a passé le 02/09 — seul le garde « déjà déclarée aujourd'hui » a empêché l'inscription — et la tonte du 03/09 a été déclarée sur une sortie de **8,7 minutes**.

### La racine, et ce que j'avais écrit à tort

À la naissance d'une tâche, aucune base n'était retranchée : elle héritait de tout `mower_mowing_minutes_today`. La 0.66.0 a ensuite reporté ce total sur les jours suivants. ⚠️ **Le report de minuit n'est pas la cause** — la tâche du 03/09 est née *avant* minuit, les 289 minutes étaient déjà dans son suivi ; annuler la 0.66.0 n'aurait rien changé.

J'avais documenté cet héritage comme une « hypothèse assumée », en écrivant que « le risque penche du bon côté ». **C'était l'inverse.** Sur-compter déclare une tonte qui n'a pas eu lieu : la hauteur retombe à la lame, le retard est remis à zéro, la prochaine tonte est repoussée — le modèle est corrompu et rien ne le rattrape. Sous-compter ne fait que retarder : le retard continue de courir et la tonte suivante corrige.

La base du jour est désormais mémorisée à la naissance de la tâche et retranchée, puis oubliée au changement de date (le compteur repart de zéro). ⚠️ **Coût accepté** : une tâche découverte *en cours* de route sous-comptera son travail et pourra être jugée trop courte — c'est le côté sûr, et le filet Node-RED de 23:50 reste derrière.

⚠️ **Quatre de mes tests encodaient une prémisse irréaliste** : ils faisaient naître la tâche au milieu du travail, avec 120 ou 200 minutes déjà au compteur. C'est exactement le cas qui masquait le défaut. Réécrits sur le cas réel — la tâche naît au démarrage — plus deux tests neufs : la bordure qui suit un vrai travail n'hérite plus de rien, et le vrai travail qui suit une bordure reste déclarable.

## 0.68.0

1244 tests verts. **Une mise à jour de firmware était annoncée comme une panne.**

Le 02/09/2026 à 01:26, le robot est resté en état `error` plusieurs minutes pendant une **mise à jour de firmware** — tête caméra 2.5.6+7 → 2.5.7+12 à 01:28:59, sortie de l'état quatre secondes plus tard. Pendant tout l'épisode, son propre capteur `sensor.…_erreur` affichait **`no_error`**.

L'intégration lisait bien ce capteur et normalisait `no_error` en `None`… puis son repli **inventait** « Erreur tondeuse. ». Ce texte remontait ensuite jusqu'au bandeau : « **Robot en erreur: Erreur tondeuse.** » — à une heure du matin, pour une machine qui allait parfaitement bien, et jusqu'aux notifications.

Deux endroits affirmaient la panne, tous deux corrigés :

- `mower_adapter` : le repli dit désormais « Robot indisponible, aucun code d'erreur signalé ».
- `decision_mowing` : le préfixe « Robot en erreur: » part de `mower_operation_state == "error"` seul. Sans code d'erreur, le libellé devient « Robot indisponible: il ne signale aucun code d'erreur ».

⚠️ **Le blocage est conservé** — elle ne peut effectivement pas tondre pendant ce temps. Seul le mot change. Un test verrouille les deux moitiés, et un autre garde l'autre sens : un **vrai** code d'erreur conserve son libellé fort, sinon ce correctif rendrait toute panne réelle muette.

⚠️ La liste `_NO_ERROR_CODES` couvre aussi la chaîne vide, et c'est voulu depuis l'origine : un capteur d'erreur muet ne prouve pas une panne non plus.

Corrigé au passage : un commentaire de test parlait encore d'une « Mammotion ». C'est un **Worx Landroid**.

## 0.67.1

1242 tests verts. **Le palier d'ET0 était calculé, persisté… et jamais affiché.**

`stress_palier_et0` atteignait bien le snapshot — un test le prouvait — et n'apparaissait pas dans les attributs du capteur de risque. Cause : `_decision_value` passe par `_normalize_exposed_value`, qui arrondit **tout nombre sans précision déclarée à trois décimales**. Un `int` en ressort donc en `float`, et le garde `isinstance(palier, int)` que j'avais écrit était systématiquement faux.

Six heures en production, invisibles : le capteur publiait tout le reste normalement, et la bande morte, elle, fonctionnait — seule son observabilité manquait.

⚠️ **La couche que mes tests ne traversaient pas.** Ils s'arrêtaient au snapshot, où la valeur est encore un entier. Le test ajouté part de `coordinator.data` et lit `extra_state_attributes`, la vraie sortie. Trois mutations tuées, dont le retour au garde fautif.

⚠️ **Piège général, à retenir** : toute valeur lue par `_decision_value` ressort en `float` sauf précision explicite. Un garde `isinstance(x, int)` sur une telle valeur est toujours faux. Un seul site était concerné dans le code — vérifié.

## 0.67.0

1240 tests verts. **La cause réelle du risque qui clignote, trouvée en corrélant à la seconde près.**

### Le risque basculait parce que l'ET0 franchissait 4,0 mm, pas parce qu'il manquait un amortissement

Les **dix** bascules `faible ↔ modere` de l'après-midi du 31/08 coïncident **à la seconde** avec une mise à jour d'ET0, et toujours dans le bon sens :

```
16:25:51  ET0 4,1 → 4,0   risque → faible    (même seconde)
17:36:27  ET0 4,0 → 3,9   risque → faible    (même seconde)
17:48:27  ET0 3,9 → 4,0   risque → modéré    (même seconde)
18:02:23  ET0 4,0 → 3,8   risque → faible    (même seconde)
19:14:26  ET0 3,7 → 4,1   risque → modéré    (même seconde)
```

L'ET0 a passé l'après-midi entre **3,6 et 4,4 mm**, franchissant neuf fois le palier `etp >= 4` de `_heat_stress_level`. Les autres facteurs valaient exactement 2 ce jour-là (vent 6-8 km/h sous le seuil de 15, humidité 62-71 % au-dessus de 40, température sous 27) : ce pas seul faisait passer le score de 2 à 3, très exactement le seuil « vigilance ».

⚠️ **Et le capteur ne pouvait pas le montrer** : il arrondit au dixième, et le seuil tombe *dans* l'intervalle d'arrondi. Deux valeurs de part et d'autre de 4,0 s'affichent toutes deux « 4,0 ».

**Bande morte de 0,4 mm sur les paliers d'ET0** (`palier_et0_stress`) : on monte au seuil nominal, on ne redescend qu'une bande plus bas. Le 0,4 est le **genou mesuré** sur les 103 relevés réels du 31/08 — il fait tomber les changements de palier de 17 à 5 (−70 %), et l'élargir à 0,5 ou 0,6 n'en supprime pas un de plus. ⚠️ Asymétrique du bon côté : un assèchement réel est vu aussi vite qu'avant, seul le retour au calme attend d'être franc. Le palier est publié (`stress_palier_et0`) et persisté.

⚠️ **L'amortissement de la 0.65.0 ne pouvait rien contre ça, et je l'ai dit trop vite.** Sur les quinze paliers du 31/08, le plus court dure **douze minutes** : trois cycles en absorbent **un**. Il ne supprimait aucune bascule, il les décalait. Il reste utile pour les transitoires (double calcul au démarrage), et sa docstring est corrigée : « trois cycles ≈ 6 minutes » était **faux**, la cadence est événementielle (rafraîchissement sur changement de source), donc trois cycles peuvent passer en quelques secondes.

### Les passes fantômes n'étaient écartées qu'à l'écriture

La 0.64.0 filtrait au moment d'inscrire une passe. Les **trois** déjà au carnet — des rebonds du 30/08, dix secondes, 0,0 min tondue — continuaient d'alimenter tout ce qui est publié. Mesuré : `mower_autonomous_return_battery_median` sortait **96,5 % au lieu de 85,0**, soit 11,5 points, trois retours à 99-100 % s'ajoutant aux cinq vrais. Le filtre s'applique désormais aussi à la lecture, `derniere` comprise. ⚠️ Le carnet **persisté** reste intact : on masque, on n'efface pas.

### Corrections de mes propres affirmations

- **Trois** passes fantômes, pas quatre : recomptées en exécutant le prédicat sur le journal réel.
- ⚠️ **La prémisse de la 0.66.0 était fausse.** Elle invoquait « le travail de 4 à 5 h que la tondeuse a fait le 31/08 » : elle **n'est pas sortie ce jour-là**. Aucune passe les 31/08 et 01/09, la dernière du 30/08 s'achève à 23:01:54 — près de minuit, jamais à cheval. Le défaut du passage de minuit reste réel *par lecture du code* et par le calendrier de la machine (22:45→23:01 le 30/08, 22:30→23:44 le 22/08), mais il est **latent**, pas constaté.
- Le commentaire au-dessus du garde de clôture du bilan sol décrivait encore la règle des 50 % remplacée en 0.63.0.

## 0.66.0

1223 tests verts. **Deux défauts introduits par mes propres correctifs de cette nuit, relevés par la revue de la PR #47.**

**Le travail de tonte qui traverse minuit n'est plus perdu.** `mower_mowing_minutes_today` est un compteur de JOURNÉE : il repart à zéro à minuit. Un travail de 4 à 5 h démarré à 20 h — ce que la tondeuse a fait le 31/08 — atteint 100 % après minuit avec quelques dizaines de minutes au compteur du jour. Le plancher de qualification le jugeait « trop court » **et brûlait la complétion**. Et la veille n'avait rien déclaré non plus, puisque depuis la 0.62.0 la déclaration attend la fin du travail : le travail entier disparaissait, en silence, comme s'il n'avait pas eu lieu. Les minutes s'accumulent désormais par jour sur la durée de la tâche (`mower_job_minutes_total`, publié). ⚠️ Le plancher continue d'écarter une vraie coupe de bordure — un test le verrouille dans les deux sens.

**Les motifs de risque suivent le niveau publié.** `amortir_niveau_risque` (0.65.0) ne remplaçait que `risque_gazon` : pendant les deux cycles de retenue, le capteur publiait « risque faible » avec pour raison « conditions asséchantes vigilance ». C'est exactement l'invariant que `_raisons_par_defaut` protège depuis le 01/08/2026 — *une raison doit EXPLIQUER le niveau qu'elle accompagne* — contourné par le côté, en changeant le niveau après coup. Le motif dit maintenant le vrai : `niveau faible maintenu : modere observé 1/3 cycles`. Les motifs bruts restent lisibles via `risque_gazon_brut` et `risque_amortissement`.

⚠️ **Le banc de mutations a de nouveau trouvé ce que les tests rataient** : sur huit mutations, deux ont survécu au premier jet. Le test de non-débordement du cumul faisait démarrer les deux travaux le MÊME jour — or la fuite ne se produit qu'au changement de date. Et retirer `mower_job_minutes_total` de `_MOWER_CONTEXT_KEYS` ne faisait tomber aucun test : **le piège des listes blanches, deuxième fois sur cette même famille de clés.**

## 0.65.2

1218 tests verts. **La phrase de blocage ne se répète plus.**

Effet de bord de la 0.64.0 : depuis que le motif de blocage et la fenêtre horaire partagent
`_est_la_nuit`, ils tombent souvent d'accord **au mot près**. La phrase publiée devenait :

```
Nuit: attendre le lever du soleil. Fenêtre horaire: Nuit: attendre le lever du soleil.
```

Les faire concorder était le but ; les imprimer deux fois n'en faisait pas partie. La fenêtre
n'est ajoutée que lorsqu'elle apporte quelque chose de **neuf**.

- Le test existant qui protège l'ajout de la fenêtre quand elle dit autre chose reste vert —
  vérifié par mutation, il tombe si on cesse de l'ajouter.
- ⚠️ `reason` peut valoir `None` : rattrapé par mypy, pas par les tests.

## 0.65.1

1217 tests verts. **L'amortissement de la 0.65.0 ne faisait RIEN.** Constaté en production
quinze minutes après son déploiement.

`risque_amortissement` — la mémoire que le coordinateur relit au cycle suivant — était bien
produite par le bundle et bien rangée par le coordinateur, mais elle n'était **ni recopiée dans
`decision.py`** (recopie clé par clé) **ni déclarée dans `_COORDINATOR_SNAPSHOT_KEYS`**. Elle
n'atteignait donc jamais le snapshot :

```
snapshot.get("risque_amortissement")   → None
persisté sur le disque                 → null
```

Chaque cycle repartait d'une mémoire vide, prenait la branche « premier cycle » et republiait le
brut. **L'amortissement avait l'air parfaitement branché et ne servait à rien.**

C'est le **quatrième** défaut de cette même famille en une nuit — « calculer n'est pas
appliquer », puis « déclarer n'est pas câbler ». Mes tests d'alors vérifiaient le TEXTE du code :
l'appel présent, la persistance écrite, l'ordre des lignes. Aucun ne suivait la valeur.

- Les deux clés traversent maintenant les **deux** listes blanches, et `risque_gazon_brut` est
  publié à côté du niveau amorti **seulement quand il diffère** — un amortissement muet serait
  indiscernable d'un capteur figé.
- Un test part de la sortie RÉELLE et la suit jusqu'au snapshot publié, puis vérifie la seconde
  liste blanche. ⚠️ Sans cette seconde vérification, retirer la clé de la liste du coordinateur
  ne faisait tomber aucun test — « quatre listes blanches, pas deux ».
- Les **3 mutations** du banc sont détectées.

## 0.65.0

1216 tests verts. **Le risque cesse de clignoter, et son motif cesse de mentir.**

### Quatorze bascules en une journée

`risque_gazon` a basculé **quatorze fois** entre `faible` et `modere` le 31/08/2026, dont six
entre 16 h et 18 h hors de tout redémarrage — 16 min à « modéré », 32 min à « faible », 39 min
à « modéré »…

La cause est **structurelle**. `heat_stress_level` sort d'un score ENTIER où chaque facteur vaut
+1 et où « vigilance » commence à 3 : n'importe quel facteur qui oscille fait basculer un rang
entier. Vérifié ce jour-là, ce n'était **ni le vent** (6 à 8 km/h, seuil 15) **ni l'humidité**
(62 à 71 %, seuil 40) — corriger un capteur n'aurait rien réglé.

⚠️ Et ce n'était pas cosmétique : `risque_gazon` alimente `compute_next_reevaluation`. Un risque
qui clignote fait clignoter la cadence.

- **Amortissement sur le niveau PUBLIÉ** : il ne change qu'après **trois cycles stables** (~6 min).
- **⚠️ ASYMÉTRIQUE, et c'est le cœur** : une montée vers `eleve` passe **au cycle même**. Amortir
  n'est pas différer une alerte.
- **Amorti AVANT** `compute_next_reevaluation` et `_decision_urgence`, qui le lisent tous deux :
  amortir seulement à la publication aurait laissé la décision travailler sur le brut — deux
  valeurs pour un même fait.
- **Rien touché aux seuils (3/5/7) ni aux poids** : le défaut est l'absence d'amortissement, pas
  le calibrage. Le brut reste publié (`risque_gazon_brut`) — un amortissement muet serait
  indiscernable d'un capteur figé.
- Mémoire **persistée des deux côtés** : sans elle, chaque redémarrage relancerait sur le brut.

### « stress hydrique » à côté d'une réserve pleine

Relevé le 01/09 : *« risque modéré — stress hydrique vigilance »* pendant que le bilan sol
annonçait la réserve **pleine** (12/12) et la déplétion **nulle**. Deux affirmations
inconciliables sur le même écran.

Le calcul est juste, c'est le **mot** qui ment : le score additionne température, air sec, vent,
absence de pluie et déficit — c'est la demande de l'**atmosphère**, pas l'état du **sol**. Il
devient **« conditions asséchantes »**, formulé à un seul endroit (`libelle_stress`) au lieu de
trois. On peut avoir un sol saturé et un air qui tire : les deux sorties peuvent enfin coexister.

Les **7 mutations** du banc sont détectées par le test visé.

⚠️ **Trois trous trouvés par le banc, pas par les tests** — le même piège trois fois, de plus en
plus profond : mon test du compteur ne traversait pas le chemin muté ; supprimer la
**réinjection** du niveau amorti ne faisait tomber personne (calculer n'est pas appliquer) ; et
deux tests qui vérifiaient l'ABSENCE de « stress hydrique » seraient devenus verts pour la
mauvaise raison après le renommage. Les assertions partent désormais de la source du libellé,
et un test interdit le mot « hydrique » plutôt que de figer une formulation.

⚠️ **Et mypy a rattrapé ce que les tests laissaient passer** : `risk_context` devait aussi
traverser `GazonBrain.compute_snapshot`, que la suite de tests ne franchit pas.

## 0.64.0

1207 tests verts. **Trois constats de l'audit corrigés**, tous vérifiés sur l'installation
avant d'y toucher.

### Deux définitions de la nuit qui se contredisaient à l'écran

Le motif de blocage lisait le **soleil** ; la fenêtre horaire ne lisait que l'**heure**, et
testait « avant 10 h » AVANT « après 22 h ». Toute la plage 00 h → 09 h 59 était donc étiquetée
« Matin trop tôt : attendre le ressuyage » — un message de rosée en pleine nuit noire.

Relevé le 01/09/2026 à 00:48, dans une seule et même phrase publiée :

```
Nuit: attendre le lever du soleil. Fenêtre horaire: Matin trop tôt: attendre le ressuyage.
```

- **Une seule définition** désormais, `_est_la_nuit` : le soleil d'abord, l'horloge en repli
  (22 h → 7 h). Les deux sorties partagent la même.
- **⚠️ « Matin trop tôt » garde son sens** : il parle de ROSÉE, pas d'obscurité. Il ne vaut plus
  qu'entre le lever du soleil et 10 h — un test le verrouille, sinon la correction l'aurait
  purement et simplement supprimé.
- La décision était heureusement la même des deux côtés (bloqué) : c'était un défaut de
  message, pas de comportement.

### Quatre passes fantômes sur trente au carnet

L'intégration de la tondeuse publie une séquence qui rebondit au démarrage — `starting` →
`docked` **9 s** → `starting` → `mowing` — et chaque rebond ouvrait puis refermait une passe :

```
30/08 14:17:18 → 14:17:28   10 s   0,0 min tondue   100→100
30/08 20:15:41 → 20:15:51   10 s   0,0 min tondue   100→100
30/08 20:40:16 → 20:42:01    2 min 0,0 min tondue   100→ 99
```

Elles ne sont pas neutres. **Précision par rapport au signalement d'origine** : les trois
médianes du profil appris ne filtrent pas de la même façon.

| médiane | filtre | touchée ? |
|---|---|---|
| `mower_full_pass_minutes_median` | fins `batterie_vide` | **non** |
| `mower_autonomous_return_battery_median` | fins `retour_autonome` | **oui** — les fantômes y entrent à 100, 100, 99 |
| `mower_passes_per_day_median` | tout sauf `bloquee` | **oui** — le 30/08 comptait 7 passes pour 4 réelles |

- Une sortie qui n'a **rien tondu** n'entre plus au carnet. **⚠️ Une passe BLOQUÉE sans tonte y
  reste** : c'est le fait le plus intéressant du carnet.
- **⚠️ `None` n'est pas zéro** : une durée absente signifie « on ne sait pas », et la passe est
  conservée.

Les **6 mutations** du banc sont détectées par le test visé.

⚠️ **Le banc a trouvé ce que les tests rataient** : supprimer le filtre AU POINT D'APPEL ne
faisait tomber aucun test, parce que je ne testais que le prédicat. Un test rejoue désormais une
vraie séquence sortie/retour et regarde ce qui atterrit dans le journal — vérifier qu'une
fonction est correcte ne prouve pas qu'elle est branchée.

⚠️ **Piège d'isolation rencontré** : `test_init.py` remplace le coordinator dans `sys.modules`
par un faux module. Un test qui réimporte le module récupère le faux et tombe — mais seulement
quand toute la suite tourne, jamais seul.

## 0.63.0

1200 tests verts. **Le filet de clôture du bilan sol jetait la mesure les jours de pluie.**

Trouvé en auditant l'historique de toutes les entités, à la demande de Kévin.

À la clôture de la veille, l'ETc **réellement mesurée** heure par heure était remplacée par
l'estimation pleine journée dès qu'elle valait moins de la moitié de la prévision. Le filet
visait les journées **tronquées** (Home Assistant arrêté avant minuit, cumul amputé, eau
fantôme laissée dans la réserve). Mais il jugeait sur l'**ampleur** de l'évaporation, or une
journée de pluie évapore légitimement 38 à 47 % de la prévision.

Relevé sur le registre réel de l'installation :

```
28/08   mesurée 2,388   estimée 5,1   seuil 2,55   → jetée, sur-débit 2,712 mm
29/08   mesurée 1,085   estimée 3,4   seuil 1,70   → jetée, sur-débit 2,315 mm
30/08   mesurée 1,339   estimée 2,9   seuil 1,45   → jetée, sur-débit 1,561 mm
31/08   mesurée 2,348   estimée 3,5   seuil 1,75   → conservée (le bon chemin existe)
```

**6,6 mm débités en trop en trois jours**, et le repli ne va jamais dans l'autre sens : la
réserve ne peut que perdre de l'eau. Effet net observable aujourd'hui, plafond des 24 mm
appliqué : stock à **19,3 mm au lieu de ~22,8**.

**⚠️ Et les trois journées avaient tourné jusqu'à minuit.** Le registre portait déjà la réponse,
juste à côté de la valeur jetée :

```
28/08  dernier cumul 23:58:35     29/08  23:59:01     30/08  23:59:49
```

C'est la **couverture** qui distingue une journée tronquée d'une journée pluvieuse, pas
l'ampleur de l'évaporation. Le filet lit désormais `etp_last_ts` — l'instant du dernier cumul —
et tolère au plus **une heure** manquante avant minuit.

- **Le filet garde sa raison d'être** : une veille arrêtée à midi retombe bien sur l'estimation.
  Deux tests, un par sens.
- **⚠️ Une absence ne désarme pas le garde-fou** : horodatage manquant, vide ou illisible →
  journée réputée non couverte, comportement prudent d'avant.
- Les **5 mutations** du banc sont détectées par le test visé. ⚠️ La dernière — horodatage
  illisible réputé couvert — n'était couverte par AUCUN test : trouvée par le banc, pas par la
  suite.
- ⚠️ Le test existant de clôture s'arrêtait à 20 h : sous la nouvelle règle c'est une journée
  réellement tronquée. Sa donnée a été étendue jusqu'à 23:58 **et son taux abaissé** pour qu'il
  continue de mordre — une extension qui aurait fait passer l'accumulation au-dessus de
  l'estimation aurait vidé l'assertion de son sens.

**Ce que l'audit a confirmé de sain** : passage de minuit propre des deux côtés (compteurs de
tonte remis à zéro, carnet cumulatif préservé, part d'ET écoulée repartie de 0), cliquet pluie
opérant, et aucune fuite d'un jour à l'autre.

## 0.62.1

1197 tests verts. **Une fin de travail ne vaut qu'une fois.** Défaut introduit par la 0.61.0,
trouvé le 01/09/2026 à 00:15 en auditant le passage de minuit.

`progression_de_la_tonte` reste à 100 % entre deux travaux — 2 à 3 jours, mesuré sur huit jours
d'historique. La fin de travail était donc **re-offerte à chaque cycle** : au lendemain matin,
`mower_job_completion_state` valait encore `termine` alors que la complétion datait de la veille.

Relevé en production le 01/09 à 00:01, juste après le passage de minuit :

```
mower_job_completion_state   termine        ← complétion de la VEILLE, 23:00
mower_auto_declaration_state travail_trop_court
mower_mowing_minutes_today   0              ← compteur remis à zéro, correctement
```

Le seul rempart restant était le plancher de minutes. **Dès 90 min tondues dans la journée, la
tonte aurait été déclarée sur une complétion de la veille.**

- Une fin de travail appartient au jour où elle a eu lieu. Dès qu'elle est **traitée** —
  déclarée, déjà déclarée, ou écartée comme trop courte — elle est éteinte : la tâche retombe
  au repos, et il faut une **nouvelle** tâche vue inachevée pour redéclarer.
- Deux tests : la même tâche à 100 % ne redéclenche rien au cycle suivant, et une fin écartée
  comme trop courte ne ressurgit pas quand le compteur repart de zéro le lendemain.
- **2 mutations sur 3** détectées par le test visé. ⚠️ La troisième — consommer dès la détection
  plutôt qu'après la décision — est **équivalente** : tous les chemins qui atteignent `termine`
  sont terminaux et consomment de toute façon. Signalée telle quelle plutôt que maquillée.

**Ce que le passage de minuit a bien fait**, vérifié au même moment : les compteurs du jour
(`mower_mowing_minutes_today`, `mower_pass_count_today`, `mower_blocked_minutes_today`,
`mower_block_count_today`) sont tous repartis de zéro, et le carnet cumulatif
(`mower_passes_observed` = 30) a été correctement préservé.

## 0.62.0

1195 tests verts. **Le seuil qui débloque la tonte suit la lame RÉELLE, plus la recommandation.**

Trouvé en élucidant une incohérence d'affichage signalée par Kévin — le défaut était en fait
dans la décision, pas dans la carte.

`hauteur_tonte_recommandee_cm` est ce que l'intégration **conseille de régler sur la lame** :
son calcul part de `_seasonal_base_height` (« hauteur de coupe prudente selon la saison ») et
elle est bornée par la plage MACHINE. Or elle servait aussi de seuil sur la hauteur d'**herbe** :

```python
if current_height <= target_height:   # target_height = la recommandation de LAME
    → « Hauteur actuelle trop faible: vise au moins 6.0 cm avant de tondre. »
```

Deux effets, tous deux vérifiés sur le code réel :

- **Lame à 5,5 · consigne à 6,0** — l'herbe repart de 5,5 (la lame) après chaque tonte mais doit
  atteindre 6,1 (la consigne) pour débloquer : **~2,5 jours de croissance imposés** à 0,24 cm/j,
  alors qu'un robot est fait pour raser peu et souvent.
- **Obéir à la consigne aggravait le cas** : lame réglée à 6,0 → l'herbe repart de 6,0, le seuil
  vaut 6,0, le déblocage arrive à 6,1. Chaque tonte n'ôterait plus qu'**un millimètre**. Suivre
  le conseil publié dégradait le comportement.

**Arbitré par Kévin le 30/08/2026 : la hauteur réelle de la lame fait foi.**

- Nouveau helper `_hauteur_coupe_reelle_cm`, même source que l'amorce de l'estimation d'herbe —
  c'est de cette hauteur que le gazon repart, donc c'est elle la référence.
- **La règle du tiers l'utilise aussi**, et c'était nécessaire : la juger sur la consigne
  validait une coupe à 6,0 pendant que la machine descend réellement à 5,5.
- **⚠️ `None` ne désarme pas le garde-fou** : réglage inconnu → repli sur la recommandation.
  Une mutation le verrouille.
- Le message nomme enfin la bonne grandeur : « la lame coupe à 5,5 cm, attends que le gazon
  la dépasse » au lieu de « vise au moins 6,0 cm ».
- Les **4 mutations** du banc sont détectées par le test visé.

⚠️ **Ce que je n'ai PAS fait, et pourquoi.** L'enquête proposait de déclencher selon la règle du
tiers, soit vers 8,3–9 cm. C'est une règle de tondeuse thermique passée une fois par semaine ;
un robot est conçu pour raser 1 à 2 mm plusieurs fois par semaine — c'est le régime configuré
ici (3 passages/semaine). Non retenu.

⚠️ **Défaut LATENT, pas observé.** Sur le 27→30/08, tous les blocages relevés sur l'installation
sont `wet_grass` : ce seuil n'a pas été constaté en train de gêner. La correction vient d'une
lecture de code et d'un arbitrage, pas d'une gêne mesurée.

## 0.61.0

1193 tests verts. **La tonte se déclare sur le TRAVAIL terminé, plus sur une durée.**

Demandé par Kévin le 30/08/2026, après avoir vu le défaut se produire en direct.

**Ce qui n'allait pas.** Le seuil inscrivait une tonte dès 90 min cumulées, quelle que soit la
surface faite. Mesuré ce jour-là : déclarée à 14:32 avec **102,8 min tondues et le travail à
49 %**. Conséquences immédiates — hauteur estimée ramenée de 6,4 à **5,5 cm** comme si toute la
pelouse avait été coupée, retard remis de 3 jours à **0**, prochaine tonte repoussée au 02/09,
pendant que la moitié de la pelouse restait haute et que la tondeuse tondait encore. Le seuil
mesurait une durée là où il fallait une surface.

**⚠️ Et le piège qui aurait tout cassé si on l'avait branché naïvement.**
`progression_de_la_tonte` n'est PAS un événement quand elle vaut 100 : c'est l'état de **repos**.
Relevé sur huit jours d'historique réel :

```
25/08  13:00 → 0 … 17:00 → 100    puis 100 pendant 51 h
27/08  16:00 → 0 … 21:00 → 100    puis 100 pendant 62 h
30/08  11:21 → 0 …  (en cours)
```

Un test `== 100` aurait donc été vrai la quasi-totalité du temps, et aurait déclaré une tonte
**tous les jours**. On déclare sur le **passage** à 100 d'une tâche qu'on a vue inachevée,
jamais sur la valeur seule.

- **`task_id` recolle les passes d'un même travail**, recharge comprise : c'est exactement
  l'unité voulue. Le 30/08, la reprise après charge est repartie de 35 % et non de 0.
- **Le suivi est persisté des deux côtés.** Un travail dure 4 à 5 h ; non persisté, il repartirait
  vide au milieu, le passage à 100 serait lu comme un repos, et **plus aucune tonte ne serait
  déclarée** — un silence total, indiscernable d'un capteur muet.
- **Le réglage existant change de sens sans changer de nom** : il ne DÉCLENCHE plus, il QUALIFIE.
  Un travail terminé ne compte que s'il a représenté au moins ce temps de tonte dans la journée —
  une coupe de bordure est aussi une tâche qui monte à 100, et elle est courte.
- **⚠️ `None` reste une absence** : tondeuse injoignable ou entité absente ne valent pas
  « travail inachevé ». Une mutation le verrouille.
- Trois clés publiées pour que la règle soit lisible de l'extérieur :
  `mower_job_completion_state`, `mower_job_followed_id`, `mower_job_seen_incomplete`.
- Les **7 mutations** du banc sont détectées par le test visé.

**⚠️ Conséquence assumée : un travail jamais terminé n'est plus déclaré.** Une journée où la
batterie lâche avant la fin ne comptera plus comme une tonte — c'est le but, mais le retard
continuera de courir tant que le travail n'est pas bouclé.

⚠️ **Deux trous trouvés par le banc, pas par les tests.** Le premier test du « 100 au repos »
ne traversait qu'un des deux chemins ; et les trois nouvelles clés n'étaient protégées dans
aucune liste de câblage — retirer l'une du capteur ne faisait tomber personne.

## 0.60.2

1187 tests verts. **Trois défauts de plus sur la voie « arrêt manuel », remontés par la revue
automatique de la PR.** Tous les trois réels, tous les trois vérifiés dans le code avant d'être
retenus.

**⚠️ Les zones jamais ouvertes étaient exclues de la moyenne.** Arrêter un cycle après la
première de trois zones enregistrait **5 mm** de lame surfacique. Or deux tiers du gazon
n'avaient rien reçu : la lame moyenne vaut **1,7 mm**. Le bilan du sol était crédité au triple,
et les deux zones restées sèches — celles qui ont le plus soif — attendaient d'autant plus le
cycle suivant. Les zones prévues mais non arrosées comptent désormais **pour zéro**, ce qui
reste une seule règle de moyenne (celle de `_zone_session_surface_mm`, à laquelle on ajoute des
entrées à 0 mm).

**⚠️ La proratisation d'une vanne qui retombe ne servait à RIEN.**
`_build_zone_execution_record` réduit bien la dose de `zones_done` quand le relais retombe en
cours de segment — mais la fin de cycle appelait `async_record_watering` avec
`plan.objective_mm`, l'objectif **prévu**. L'historique, le bilan du sol et le budget
hebdomadaire créditaient donc l'eau qui n'a pas coulé, et le système sous-arrosait ensuite :
exactement ce que la surveillance de vanne devait empêcher. La voie nominale enregistre
maintenant l'exécution dès qu'elle est inférieure au plan de plus de 0,1 mm — la marge évite
tout bruit d'arrondi sur un cycle complet, dont le comportement ne change pas.

**⚠️ La cause `arret_manuel` traversait DEUX listes blanches et mourait dans la seconde.**
`_normalize_watering_cause` (coordinator) et `record_watering` (gazon_brain) filtrent chacune
les causes reconnues, et la seconde était restée à trois valeurs. L'historique retombait sur
« hydrique » : impossible de distinguer un cycle interrompu d'un arrosage normal, c'est-à-dire
exactement la trace d'audit que le service `stop_irrigation` était censé laisser. **Le piège
n°1 de ce projet, appliqué à la fonctionnalité qui le documente.** Les deux listes sont
remplacées par une seule, `const.WATERING_CAUSES`.

- **4 mutations sur 5 sont détectées** par le test visé, dont le retour au plan sur la voie
  nominale — testé à travers la **vraie séquence** d'arrosage, pas au niveau du helper : une
  première version du test vérifiait le helper seul et **ne mordait pas**.
- ⚠️ **La mutation non couverte est signalée, pas dissimulée** : retirer `zones_prevues` de
  l'appel nominal ne casse rien tant que toutes les zones prévues ont tourné — il faudrait un
  scénario où une zone échoue entièrement en fin de cycle normale.

## 0.60.1

1183 tests verts. **Un cycle arrêté à la main créditait la lame × le nombre de zones.**

Trouvé en relisant les revues automatiques accumulées sur les PR en attente : la même
remarque y revenait **neuf fois**, sur neuf PR différentes. Elle était juste.

Sur la voie « arrêt manuel » (`stop_irrigation`, introduite dans ce lot), la dose enregistrée
était la **somme** des segments exécutés. Or un segment porte la lame appliquée à SA zone :

```
3 zones à 5 mm  →  enregistré 15 mm  |  reçu par chaque carré d'herbe : 5 mm
```

Le bilan du sol se croyait crédité au triple, le budget hebdomadaire se croyait dépassé, et le
système **sous-arrosait** ensuite — l'inverse exact de ce que cet enregistrement protège.

**Les trois autres voies disaient déjà la bonne chose** : la fin de cycle normale enregistre
`plan.objective_mm`, l'affichage temps réel cumule par zone avant de moyenner
(`compute_live_session_water`), et `_zone_session_surface_mm` documente explicitement la
moyenne. Seul l'arrêt manuel divergeait — une quatrième implémentation d'une règle déjà écrite
trois fois, exactement le piège que ce projet documente.

- **Une seule règle, un seul endroit** : `water.surface_mm_depuis_segments` cumule **par zone**
  (deux passages sur la même zone s'additionnent — le même carré d'herbe a reçu les deux) puis
  **moyenne les zones** (deux zones distinctes ne s'additionnent pas). La moyenne elle-même
  reste celle de `_zone_session_surface_mm`.
- **⚠️ Deux tests encodaient le comportement faux** et affirmaient `7.0` et `10.0`. Ils ont été
  corrigés en y inscrivant la raison, pas seulement le nouveau chiffre. Deux tests neufs
  distinguent réellement les deux erreurs symétriques : sommer les zones, et moyenner les
  passages.
- Les **5 mutations** du banc sont détectées par le test visé, dont les deux erreurs
  symétriques et le retour au cumul brut.

**Au passage, un cinquième verrou « observation seule » était plus étroit que les quatre
autres.** Le carnet de passes se vérifiait contre `decision_mowing`, `guidance` et `decision`,
mais **pas** `decision_watering` — une clé du carnet lue par la décision d'arrosage serait
passée sans bruit, alors que les quatre autres verrous couvrent bien les quatre modules. Même
liste partout, et la mutation le confirme.

## 0.60.0

1181 tests verts. **Le total de pluie du jour peut venir d'un compteur qui ne se remet jamais
à zéro.** Nouvelle entrée `capteur_pluie_cumul`, préparée pour le Shelly/Ecowitt WS90.

Deux défauts documentés de ce compteur, qu'un `utility_meter` ne sait pas gérer :

- il **ne se réinitialise pas à minuit** — il compte depuis toujours ;
- il **chute parfois brutalement à 0 puis revient** à sa valeur (trames corrompues, simultanées
  à des rafales relevées au-dessus de 25 000 km/h). Un compteur d'énergie branché dessus
  enregistre la remontée comme de la pluie : 250 mm d'un coup.

**On ne compte donc que ce qui dépasse le maximum déjà vu**, et le total repart à zéro sur
**notre** horloge :

```
250 → 0      chute parasite  → aucun gain, le maximum reste 250
0   → 250    remontée        → aucun gain, on est sous le maximum
250 → 250,4  vraie pluie     → +0,4 mm
```

- **Les deux mémoires sont persistées.** Sans elles, une chute parasite suivie d'un redémarrage
  recompterait tout le compteur en pluie.
- **Plafond de plausibilité de 30 mm par pas de cycle** (~2 min) : les pluies les plus intenses
  relevées en France plafonnent vers 3 mm/min, la marge est d'un facteur 5. Un gain rejeté est
  **conservé en trace** (`pluie_gain_rejete_mm`) — un rejet silencieux serait indiscernable
  d'une panne. À recalibrer sur les vrais écarts de la station.
- **⚠️ OBSERVATION SEULE** : publiée dans `sensor_health`, elle n'alimente aucune décision.
  Un test le verrouille sur quatre modules.
- Les **7 mutations** du banc sont détectées.

⚠️ Deux pièges attrapés par les tests avant livraison. **Collision de nom** : `pluie_jour_mm`
existait déjà dans le bilan sol — la clé est devenue `pluie_cumul_jour_mm`. Et une première
version du test de chute parasite utilisait 250 mm : le **plafond de plausibilité** rejetait
la remontée et masquait un maximum cassé. Le test décisif utilise 20 mm, sous le plafond, où
seul le maximum peut protéger.

## 0.59.0

1170 tests verts. **Les capteurs sont lus avec leur unité, plus avec une unité supposée.**

Défaut **préexistant**, trouvé en préparant l'arrivée d'une station WS90 :

```python
wind_unit_raw = "km/h" if vent is not None else weather_profile.get("weather_wind_speed_unit")
```

Dès qu'un capteur de vent était configuré, le code **supposait des km/h** et ne lisait jamais
son unité — il ne la consultait que sur l'entité météo de repli. Juste par chance avec le
Netatmo. Avec un capteur en **m/s**, l'ET0 divisait par 3,6 une valeur déjà en m/s, et les
seuils de tonte devenaient inatteignables : un vent réel de 40 km/h vaut 11 m/s, très loin
du seuil de blocage à 40.

- **Vent normalisé en km/h et pression en hPa, une fois, À LA LECTURE.** Tout l'aval garde ses
  hypothèses actuelles — seuils de tonte, `wind_unit="km/h"` transmis à l'ET0 — et devient
  vrai au lieu d'être supposé.
- **⚠️ Unité absente ou inconnue → aucune conversion.** C'est exactement ce que le code faisait
  avant : rien ne change pour une installation existante. Quatre sous-tests le verrouillent.
- **Une seule table d'unités.** `facteur_vent_vers_ms` est extraite de `wind_speed_to_ms`, qui
  garde son comportement au chiffre près (une mutation le vérifie). Deux tables finiraient par
  diverger — c'est déjà arrivé sur ce projet.
- **⚠️ Le plancher de 0,5 m/s de Penman-Monteith ne fuit pas** dans les seuils de tonte : il
  empêche la formule de diverger, il n'a aucun sens pour décider si le vent gêne la coupe.
  Une mutation le vérifie.
- Pression : kPa, Pa, bar, inHg, mmHg reconnus. Le WS90 publie des **kPa** — branché tel quel,
  il aurait donné une pression dix fois trop faible au cœur du calcul du besoin en eau.
- Les **7 mutations** du banc sont détectées.

## 0.58.0

1160 tests verts. **Nouvelle entrée de configuration : la pluie INSTANTANÉE.**

Depuis le début, « pleut-il ? » est déduit d'un **cumul journalier**. Un cumul ne le dit pas :
3,6 mm y restent affichés toute la journée après l'averse. D'où tout l'appareillage construit
pour le deviner — détecteur de hausse, cliquet intra-journée, horodatage sur la dernière
hausse — et d'où viennent ses défauts : la fausse averse du 16/08 (bruit lu comme une hausse)
et celle du 29/08 (remise à zéro mal détectée sous 1 mm de cumul).

Or la station expose depuis toujours une pluie **instantanée**, qui répond sans calcul.
Le 29/08 à 12:23, quand le cliquet a inventé une averse, ce capteur affichait **0,0** depuis
10:11 — il aurait évité l'erreur d'entrée de jeu.

- **`capteur_pluie_actuelle`**, optionnel, offert dans les deux formulaires. Netatmo :
  `sensor.<station>_precipitation`. Ecowitt/Shelly **WS90** : `rain_rate`. Le jour où la
  station de Kévin arrive, il change l'entité et rien d'autre ne bouge.
- **Publiée à côté** de `pluie_mesuree_active` dans `sensor_health`, volontairement : c'est en
  comparant les deux sur plusieurs averses qu'on saura si la mesure directe peut remplacer la
  déduction. **Elle n'alimente aucune décision** — un test le verrouille sur quatre modules.
- **⚠️ `None` reste une absence.** Capteur non configuré, injoignable ou illisible : on ne
  conclut rien, surtout pas « il ne pleut pas ». Deux mutations le vérifient.
- Les **6 mutations** du banc sont détectées, dont celle qui retire l'entrée du formulaire —
  la clé existerait dans le code mais resterait inatteignable depuis l'interface.

**Mesuré au passage** : la station publique Netatmo est à **55 m** de la tondeuse (coordonnées
comparées). Elle n'est donc pas « chez un voisin lointain » comme la note de projet le laissait
croire — une averse locale ne peut pas lui échapper. Ça affaiblit l'argument qui justifiait de
bloquer la tonte sur une prévision que la mesure dément (0.57.0), point à rouvrir.

## 0.57.0

1152 tests verts. **Bloquer n'est plus armer trois heures de ressuyage.**

Mesuré le 29/08/2026 : la prévision annonce `rainy` de 13:10 à 14:07, la dernière hausse du
pluviomètre remonte à 10:17. Le ressuyage après pluie courait donc jusqu'à **17:07** pour une
averse que rien n'avait mesurée.

- **Quand la PRÉVISION annonce la pluie et que le pluviomètre la DÉMENT, on continue de
  bloquer** — ça ne coûte que la durée de la prévision, et le pluviomètre n'est pas sur la
  pelouse : une averse locale peut lui échapper. **Mais on n'horodate plus l'averse**, donc
  on n'engage pas 180 min de ressuyage sur une pluie jamais tombée.
- **⚠️ `is False`, jamais la valeur brute.** `None` veut dire « aucune mesure », et une
  absence ne dément rien : sans pluviomètre, la prévision garde le dernier mot. Une mutation
  le verrouille.
- Une mesure qui **confirme** la prévision horodate toujours à l'instant. Verrouillé aussi.

⚠️ Le banc a montré que le test sur la source est **redondant** : `active_rain_source` ne rend
« mesure » que si la mesure est vraie, donc les deux conditions ne peuvent pas se contredire.
Aucune mutation ne peut le tuer. Il est conservé **volontairement** — il dit qui parle, et la
priorité entre les deux bras est exactement ce qui change avec le temps (cf. la charge qui
passait avant l'état réel dans `_normalize_mower_status`). Le jour où la mesure primerait,
cette ligne resterait juste au lieu de devenir fausse en silence.

## 0.56.1

1149 tests verts. **Le cliquet inventait de la pluie les jours de bruine** — défaut introduit
par le cliquet lui-même en 0.54.2, mesuré le 29/08/2026.

Journée à 0,4 mm de cumul :

```
09:00  0,3    10:17  0,4 (pic)    11:23  0,2 ↓    12:23  0,4 ↑
```

La détection de remise à zéro testait `lecture ≤ max(0,5 ; pic/2)` **et** `lecture ≤ 0,5`.
Pour 0,2 sous un pic de 0,4, les deux sont vrais : le cliquet croyait le compteur rebouclé,
se recalait sur 0,2, et la remontée à 0,4 devenait une **nouvelle averse**.
`pluie_mesuree_active` s'est allumé sur une pluie qui n'a jamais eu lieu.

Le commentaire disait « une chute vers **~0** ». Le code disait « sous 0,5 ». Ce n'est pas la
même chose quand la journée entière vaut 0,4 mm — le défaut ne pouvait apparaître que sous
1 mm de cumul, invisible sur l'orage de 29 mm du 24/08 où le cliquet a parfaitement tenu.

- **Une remise à zéro est désormais une chute vers zéro** (≤ 0,1 mm, la résolution du capteur),
  quel que soit le cumul de la veille — la forme observée à chaque minuit.
- **Le bras relatif est conservé mais gardé** par un pic d'au moins 1 mm : après une journée à
  29 mm, un compteur qui repart à 0,3 a bien rebouclé. Sans ce bras, un `max()` figerait le
  cumul de la veille toute la journée — le piège que le commentaire d'origine met en garde de
  réintroduire.
- Les **5 mutations** du banc sont détectées, dont celle qui rejoue l'ancienne règle sur la
  journée du 29/08.

⚠️ Aucun test existant n'a vu ce défaut : ils portaient tous sur des cumuls de plusieurs
millimètres. La règle était juste là où on l'avait regardée, fausse là où on ne l'avait pas.

## 0.56.0

1144 tests verts. Deux correctifs de carnet, **observation seule, aucune décision touchée**.

**« Rappelée » suppose qu'il y ait eu une autorisation À RETIRER.** Mesuré le 22/08/2026 :
passe de 73 min lancée à la main le soir, coordination coupée, `tonte_autorisee` faux du
début à la fin. Elle est rentrée à **51 %** sur un travail réellement terminé — la seule
réponse mesurée à « à quel niveau estime-t-elle avoir fini ». Le carnet l'a étiquetée
`rappelee`, donc exclue de `mower_autonomous_return_battery_median`, resté vide.

- Le motif `rappelee` exige désormais que l'autorisation ait été **vraie au moins une fois**
  pendant la passe. Sinon on retombe sur le classement normal — et un retour à 51 % nourrit
  enfin la médiane qu'il devait nourrir.
- **⚠️ Le cas du 13/08 ne régresse pas** : autorisée puis interdite par la chaleur reste un
  vrai rappel. Deux mutations gardent les deux sens.
- Nouveau fait brut `hors_coordination` dans le journal, à côté de l'étiquette — pas un
  motif : il dit que la passe s'est déroulée sans qu'aucune autorisation n'ait jamais existé.

**La progression du travail est publiée** — `mower_job_progress_pct`, `mower_job_id`,
`mower_job_status_raw`, lus sur l'entité dérivée `sensor.<tondeuse>_progression_de_la_tonte`.

Le carnet compte des **passes** ; il n'a jamais su ce qu'est un **travail**. Le `task_id`
survit à la recharge, donc il recolle deux passes en un seul travail. Mesuré le 25/08 :
13:20:38 progression → 0, montée régulière, 17:24:11 → 100, au garage à 17:26:51.

- **⚠️ RIEN N'EST BRANCHÉ SUR UNE DÉCISION**, et deux inconnues l'imposent : le vocabulaire
  de `task_status` (vaut 2, sens ignoré — donc publié BRUT pour l'apprendre), et le
  comportement sur une **coupe de bordure**. Si elle monte aussi à 100, « progression = 100 »
  veut dire « une tâche s'est terminée », pas « le gazon est tondu ». Un test verrouille
  l'absence de branchement sur quatre modules.
- Le suffixe de l'entité dépend de la langue de l'intégration tondeuse : absente, la réponse
  est `None` partout — une absence, jamais un zéro.
- Les **10 mutations** du banc sont détectées, chacune par le test visé.

## 0.55.0

1135 tests verts. **L'intégration s'aperçoit enfin qu'on ne l'écoute pas.**

Le DÉCLENCHEUR de la tonte ne vit pas dans cette intégration : c'est un flow Node-RED. Quand
il est coupé, l'intégration continue de recommander dans le vide et **rien ne le signale**.
Deux fois en 2026 :

- le nœud de déclaration éteint du 30/07 au 06/08 — sept jours d'historique perdus ;
- l'onglet Tondeuse désactivé le 19/08 et oublié : le 21/08, `action_possible` vrai à 10:01,
  machine prête et au garage, **aucun départ jusqu'à 11:50**. 1 h 49 de fenêtre idéale.

Nouveaux attributs `mower_recommendation_ignored_minutes` et `mower_recommendation_ignored` :
depuis combien de temps la tonte est recommandée sans que rien ne parte.

- **Seuil à 30 min.** La latence normale entre l'autorisation et le départ est de **6 minutes**
  (mesurée le 16/08 et le 19/08). 30 min laissent la place à un démarrage normal tout en
  restant loin de la fin de la fenêtre idéale (10h-12h).
- **⚠️ Muet quand la coordination est coupée.** L'utilisateur a alors choisi le pilotage
  manuel : crier au silence serait crier sur une décision.
- **⚠️ `None` reste une absence.** Sans décision publiée au cycle précédent, on ne conclut
  rien — ce n'est pas « rien n'est recommandé ». Deux mutations le verrouillent.
- **⚠️ N'ALIMENTE AUCUNE DÉCISION**, comme le carnet de passes. Un compteur de silence qui
  relâcherait un garde-fou serait pire que le silence. Un test le verrouille sur quatre modules.
- **`_booleen_publie_au_cycle_precedent` remplace `_tonte_autorisee_au_cycle_precedent`** et
  cherche l'attribut PUIS `extra` : `tonte_autorisee` est un membre de `DecisionResult`,
  `action_possible` n'existe que dans `extra`. Le banc a montré que sans test dédié cette
  lecture pouvait casser en silence — le détecteur aurait alors lu `None` à chaque cycle et
  ne se serait **jamais** déclenché.
- Le compteur est persisté : c'est sur la DURÉE qu'il alerte, un redémarrage la remettrait à zéro.
- Les **10 mutations** du banc sont détectées, chacune par le test visé.

## 0.54.2

1122 tests verts. **La garde « il pleut » prenait le bruit du pluviomètre pour des averses.**
Défaut trouvé par Kévin deux heures après la livraison de la 0.54.0, sur une simple question :
« tu es sûr qu'il pleut ? »

Le détecteur comparait chaque lecture à la **précédente**. Or ce capteur journalier oscille
toute la journée — un compteur du jour qui descend, c'est du bruit, pas de la pluie négative.
Journée du 16/08/2026, **sans une goutte après 05:52** :

```
05:52  3,6   06:22  3,5   08:33  4,2   09:32  3,7   10:32  3,6   11:26  3,5
12:20  3,3   12:26  3,1   12:38  3,3   13:07  3,4   13:19  3,3   13:25  3,2   14:25  3,6
```

Le détecteur criait « il pleut » **quatre fois** : 08:33, 12:38, 13:07 et 14:25.

- **La comparaison se fait désormais sur le PIC DU JOUR**, pas sur la lecture précédente : seul
  un dépassement du maximum est une pluie nouvelle. Sur cette journée, une seule hausse retenue
  (le pic de 4,2) au lieu de quatre.
- **⚠️ Le cliquet n'est pas réécrit : il est PARTAGÉ.** `soil_balance.appliquer_cliquet_pluie`
  est extrait de `update_soil_balance` et sert maintenant les deux. La règle — et sa détection
  de remise à zéro par la chute vers ~0, arbitrée le 06/08/2026 — existait déjà pour le bilan
  sol ; en écrire une seconde version était précisément le piège, et la seconde version a
  effectivement menti.
- **Le cumul publié suit le cliquet** (`pluie_mesuree_cumul_mm`) : afficher la lecture brute
  montrerait au diagnostic une valeur que ni la garde ni le bilan n'utilisent.
- Le banc a trouvé une **garde morte** au passage — `not remise_a_zero` était intestable, une
  remise à zéro fait tomber le pic donc l'écart est toujours négatif. Supprimée.
- Les **7 mutations** du banc sont détectées, chacune par le test visé, dont le retrait du
  cliquet côté bilan sol.

## 0.54.1

1119 tests verts. **L'averse est horodatée à sa dernière hausse mesurée**, plus au dernier
cycle où la garde était vraie.

La 0.54.0 laisse la garde « il pleut » vraie **30 min après le dernier tic du pluviomètre** —
c'est voulu, une averse fait des pauses et le capteur a 0,1 mm de résolution. Mais l'horodatage
de l'averse, lui, était posé à « maintenant » à chaque cycle : le ressuyage après pluie, déjà
long de 180 min, courait donc jusqu'à **fin de pluie + 30 + 180**. Trois heures et demie
d'attente pour une pluie terminée.

- **Quand seule la MESURE conclut**, l'horodatage recule de
  `pluie_mesuree_minutes_depuis_hausse` : le dernier instant de pluie qu'on ait réellement
  mesuré. Le rab de 30 min disparaît, la garde garde sa tolérance aux pauses.
- **Quand la PRÉVISION conclut, on horodate maintenant** : elle affirme une pluie à l'instant,
  reculer inventerait une accalmie. Elle l'emporte donc quand les deux parlent.
- **⚠️ L'horodatage ne recule JAMAIS.** Si un constat plus récent est déjà noté, on le garde :
  ce correctif supprime le rab, il ne raccourcit jamais un ressuyage déjà justifié.
- **`active_rain_source` devient la source unique de la règle** — `"mesure"`, `"prevision"`
  ou `None`. `is_active_rain_weather` n'est plus qu'un « est-ce non nul ? » posé dessus.
  Réécrire le test ailleurs pour savoir qui a parlé aurait fait deux implémentations de la
  même règle, et l'une des deux aurait fini par mentir sans qu'on sache laquelle. Une mutation
  vérifie que les deux fonctions restent d'accord.
- Les **8 mutations** du banc sont détectées, chacune par le test visé — dont le franchissement
  de minuit et la divergence garde/source.

**Mesuré sur la nuit du 16/08/2026** : pluie finie à 05:52, garde encore vraie à 06:20 par la
mesure. Avant, l'averse était horodatée 06:20 et le ressuyage courait jusqu'à 09:20 ; désormais
elle est horodatée 05:52 et il s'arrête à 08:52.

## 0.54.0

1110 tests verts. **La garde « il pleut en ce moment » reçoit enfin une MESURE.** Jusqu'ici
elle ne lisait qu'une entité de *prévision* — et son second bras (`weather_precipitation_probability ≥ 80`)
est toujours nul, la 0.44.0 l'avait déjà noté. Elle n'avait donc, en pratique, qu'une entrée.

Nuit du 16/08/2026, mesurée à la seconde :

```
00:12      pluviomètre 0,1 mm — la pluie COMMENCE     météo : partlycloudy
02:05:42   1,2 mm, il pleut toujours                  météo : clear-night
           └→ 45 ms plus tard : 5 mm AUTORISÉS, execution_autorisee: true
03:59:47   2,4 mm                                     météo : rainy → la garde mord enfin
```

**3 h 47 d'aveuglement**, et c'est la prévision qui a *débloqué* pendant qu'une mesure disait le
contraire. Rien n'a été versé cette nuit-là, mais rien grâce à la garde : c'est le bilan
hydrique qui a compté la pluie réelle, et l'horaire — la fenêtre n'ouvre qu'à 03:45.

- **La mesure passe en premier**, avant les deux bras météo. Ceux-ci sont conservés tels quels :
  le correctif *ajoute* une entrée, il n'en retire aucune.
- **⚠️ C'est la HAUSSE du pluviomètre qui signe une averse, jamais sa valeur.** Le capteur
  configuré est un cumul 24 h : 3,2 mm restent affichés une journée entière après la pluie.
  Le suivi garde la dernière lecture et l'instant de la dernière hausse, et ne conclut que sur
  la fraîcheur de cette hausse (30 min).
- **⚠️ Une BAISSE n'est pas une pluie négative** : c'est la remise à zéro du capteur, mesurée
  10 fois le 04/08/2026 en une seule journée. On se recale sans horodater, et l'averse
  précédente garde sa fraîcheur.
- **⚠️ L'absence reste une absence.** Sans capteur, sans lecture, ou au tout premier cycle, la
  réponse est `None` et non `False` — et la garde teste `is True`, jamais la valeur brute.
  Un `None` traité comme vrai bloquerait l'arrosage sur un capteur muet : on aurait remplacé
  un aveuglement par un autre.
- **Nourrie par le capteur, jamais par le repli prévision.** `pluie_24h` retombe sur la météo
  quand le capteur manque ; c'est `pluie_24h_sensor` qui alimente la garde. Une mutation le
  verrouille.
- **La garde devient visible** : `pluie_mesuree_active` et `pluie_mesuree_minutes_depuis_hausse`
  apparaissent dans `sensor_health`. Elle a bloqué et débloqué l'arrosage pendant des mois sans
  qu'aucune sortie ne dise sur quoi elle se fondait — un garde muet est indiscernable d'un
  garde cassé.
- Le suivi est persisté : sans quoi un redémarrage la ferait repartir aveugle en pleine averse.
- Les **14 mutations** du banc sont détectées, chacune par le test visé — dont la recopie clé
  par clé de `compute_advanced_context` (piège n°2), où la clé serait morte en silence.

## 0.53.2

1092 tests verts. **Le carnet de passes peut repartir de zéro** — nouveau service
`gazon_intelligent.reset_mower_passes`.

La 0.53.1 a changé la façon de classer la fin d'une passe. Les passes enregistrées **avant**
elle ne portent pas le fait brut (`tonte_autorisee_fin`) qui permettrait de les rejuger : elles
gardent une étiquette produite par des règles qui n'existent plus. Les rééditer serait inventer
un passé ; les garder, c'est nourrir les médianes apprises avec des mesures fausses.

- **Le service vide le journal ET la passe en cours.** Une passe ouverte sous les anciennes
  règles se refermerait avec elles — elle part aussi. Une mutation verrouille ce point.
- **Le vidage est écrit sur le disque immédiatement** (`_async_save_state`), sinon il serait
  défait au prochain redémarrage par l'état persisté. Une deuxième mutation le verrouille.
- **Rien d'autre n'est touché** : l'historique de tonte du cerveau, la fiabilité de la machine
  et les réglages restent en place. Ce service ne remet à zéro que le carnet.
- Après appel, `mower_passes_observed` repart à 0 et les médianes apprises disparaissent
  jusqu'à ce que trois nouvelles passes soient observées.
- **⚠️ Le piège de la liste blanche a mordu une fois de plus, sur ce service même.** Il était
  absent de `_ALL_SERVICES`, la liste qui dé-enregistre les services au retrait de la dernière
  instance : il aurait survécu à un rechargement et répondu « aucune instance configurée ».
  Le test existant comptait les enregistrements (14 → 15) et voyait juste — un compte ne
  contrôle pas une concordance. Nouveau test qui part de ce que le code enregistre
  **réellement** et exige l'égalité avec `_ALL_SERVICES` **et** avec `services.yaml` ;
  il couvre les quinze services, pas seulement celui du jour, et deux mutations le vérifient.

## 0.53.1

1087 tests verts. **Le carnet de passes appelait « décision de la tondeuse » un rappel commandé
par la coordination** — le défaut a été trouvé sur la toute première passe qu'il ait enregistrée.

Le 13/08/2026, mesuré à la seconde :

```
10:40:43,774   tonte_autorisee → off   (34,9 °C, seuil 30)
10:40:45,244   la tondeuse rentre      ← 1,5 seconde plus tard
```

Elle est rentrée avec **58 %** de batterie, rappelée par la coordination. Le carnet l'a
étiquetée `retour_autonome`, c'est-à-dire « elle a décidé toute seule que c'était fini ».

- **La quatrième fin manquait**, et c'est la plus fréquente sur cette installation : en
  canicule la chaleur fait tomber l'autorisation, Node-RED rappelle la machine. Nouveau motif
  `rappelee`, reconnu sur l'autorisation de tondre au dernier échantillon de la passe.
- **L'ordre des cas est le coeur de la méthode.** `batterie_vide` passe avant `rappelee` : une
  machine à 10 % rentre de toute façon, lui attribuer le rappel effacerait la cause réelle.
  À l'inverse, rentrer à 58 % pendant une interdiction n'est pas une décision de la machine.
- **⚠️ `None` reste une absence, pas une interdiction.** Sans décision publiée, la passe n'est
  pas requalifiée en rappel — c'est le test `is False`, pas `not …`, et une mutation le verrouille.
- **L'autorisation est lue sur le cycle PRÉCÉDENT** (`brain.last_result`) : le carnet tourne
  avant `compute_snapshot`. Ce n'est pas un pis-aller — c'est justement la décision publiée qui
  a provoqué le retour. Le motif est déjà utilisé ailleurs dans le cerveau pour le Kc.
- **Le fait brut est conservé** (`tonte_autorisee_fin` dans le journal) à côté de l'étiquette,
  comme les batteries et les durées : un classement qui se révèle mauvais se rejoue.
- **Ce que le défaut faussait** : `mower_autonomous_return_battery_median`, précisément la
  mesure censée dire à quel niveau la machine juge son travail terminé. Les rappels météo
  (~58 %) s'y mélangeaient aux vraies décisions (~96 %). Une passe rappelée continue en
  revanche de compter dans le rythme quotidien : elle a bien tondu 40 minutes.
- **Vérification** : 11 nouveaux tests, dont le rejeu de la journée du 13/08 et son **miroir**
  — même passe, même batterie, seule l'autorisation change, et le motif bascule. Les **15
  mutations** du banc sont détectées.


## 0.53.0

1076 tests verts. **La tondeuse tient un carnet de bord de ses passes** — et l'intégration
apprend, sur les faits, ce qu'est un cycle de tonte sur CE jardin.

Le cumul de minutes de la journée ne dit pas si le jardin a été tondu. Mesuré du 30/07 au
08/08/2026 :

| jour | passes | minutes | blocages |
|---|---|---|---|
| 30/07 | 1 | 49 | 0 |
| 02/08 | 2 | 130 | 1 |
| 05/08 | 4 | **302** | 3 |
| 08/08 | 2 | **127** | 0 |

**Plus la machine se bloque, plus elle repart, plus elle accumule de minutes.** Le pire jour
affiche le plus gros total, la journée parfaite en affiche moitié moins. N'importe quel seuil
calculé sur ces minutes hérite de la distorsion.

L'unité de travail réelle, c'est la **passe** : un aller-retour garage → garage. Et sa fin dit
ce qui s'est passé — rentrer à 10 % de batterie après 109 min n'a rien à voir avec rentrer à
96 % après 18 min, ce que la tondeuse a fait trois jours sur quatre avant de repartir 9 secondes
plus tard. Dans le second cas elle a décidé toute seule que c'était fini.

- **Carnet** : chaque passe est journalisée avec sa durée réellement tondue, son temps
  immobilisé, ses batteries de départ et d'arrivée, et son motif de fin — `batterie_vide`,
  `retour_autonome` (elle a décidé), `bloquee`, `inconnue`. Soixante passes conservées,
  persistées : un carnet qui s'accumule sur des semaines et repart vide à chaque redémarrage
  n'apprend jamais rien.
- **Profil appris** : durée médiane d'une passe pleine, batterie médiane des retours
  autonomes, nombre médian de passes abouties par jour. **Médiane et non moyenne** — une seule
  journée à trois blocages emporterait la moyenne. Rien n'est publié sous trois observations :
  une « valeur apprise » tirée de deux passes ressemble à une mesure sans en être une.
- **⚠️ Les faits bruts sont écrits, pas seulement leur interprétation.** `fin_motif` n'est
  qu'une étiquette de confort ; les durées et les batteries sont journalisées telles quelles.
  Si le seuil de classement se révèle mauvais, tout se rejoue sur le journal sans rien perdre.
  C'est la différence entre observer et présumer.
- **⚠️ CE CARNET N'ALIMENTE AUCUNE DÉCISION**, et un test le verrouille : aucune des clés
  apprises n'apparaît dans `decision_mowing.py`, `guidance.py` ni `decision.py`. Le seuil de
  déclaration reste celui réglé par l'utilisateur tant qu'on n'a pas mesuré ce qu'est un cycle
  complet ici. Le jour où une décision voudra lire ces clés, ce test tombera et forcera la
  discussion.
- **Facteur commun** : le plafond d'échantillon (au-delà, l'écart entre deux cycles est un
  arrêt de Home Assistant, pas une durée) est désormais partagé entre le cumul de fiabilité et
  le carnet. Deux implémentations de la même règle finiraient par diverger, et l'une des deux
  mentirait sans qu'on sache laquelle.
- **Vérification** : 20 nouveaux tests, dont le rejeu de la **vraie journée du 08/08** —
  deux passes, deux motifs de fin sans rapport. Les **14 mutations** du banc sont détectées.
  Le banc a trouvé deux vrais défauts pendant l'écriture : une garde qu'aucune mutation ne
  pouvait tuer (donc morte, supprimée), et un test de persistance qui sérialisait la valeur à
  la main au lieu de passer par `_serialized_runtime_state` — il survivait à la suppression de
  la clé de la liste blanche. Encore le piège « déclaration au lieu de câblage ».


## 0.52.0

1056 tests verts. **L'intégration déclare elle-même la tonte du jour, sans attendre 23:50** — et
un réglage utilisateur qui s'effaçait tout seul depuis sa livraison est réparé au passage.

Jusqu'ici la tonte n'était inscrite que par un flow Node-RED externe, une fois par jour à
23:50, qui resommait l'historique de Home Assistant. Deux défauts vécus sur cette
installation :

- **le fil se débranche en silence** : le nœud qui déclarait est resté désactivé du 30/07 au
  06/08/2026, soit sept jours de retard de tonte accumulés sans le moindre signal ;
- **onze heures d'écart entre le fait et sa prise en compte** : le 08/08/2026 la tondeuse a
  franchi le seuil vers 12 h, et l'intégration a continué d'afficher « 2 jours de retard »
  jusqu'au soir. Ce n'est pas cosmétique — `overdue_relaxed_baseline` (`decision_mowing.py`)
  ouvre une voie alternative vers `tonte_ok` **et** contourne les blocages agronomiques. Se
  croire en retard alors qu'on vient de tondre relâche des gardes qui devaient tenir.

Le compteur `mower_mowing_minutes_today` (0.50.0, persistant depuis 0.51.1) suffit : une fois
le seuil franchi, tondre davantage ne peut pas le dé-franchir, donc la fin de journée
n'apporte rien.

- **Tonte** : nouvelle auto-déclaration dans le cycle, placée **avant** `compute_snapshot` pour
  que le retard soit corrigé dès le cycle courant. Écriture synchrone dans le cerveau — jamais
  `async_record_mowing`, qui redemanderait un rafraîchissement depuis l'intérieur du cycle.
- **Gardes** : une déclaration est une **écriture**, et une fausse tonte inscrite est pire
  qu'une tonte manquante (elle remet le retard à zéro et endort la surveillance). Quatre
  gardes : interrupteur explicite, mesure réellement présente (`None` = tondeuse injoignable,
  ce n'est **pas** zéro minute — les booléens sont rejetés au passage), seuil franchi, journée
  pas déjà inscrite. La date est passée **explicitement** : le cumul est indexé sur
  `_current_date()` quand `record_mowing` retomberait sinon sur `dt_util.now().date()`, et deux
  horloges pour un même fait donnent une tonte déclarée le mauvais jour.
- **Historique** : `record_mowing` devient idempotent par journée. `_append_history` ne
  dédupliquait pas ; sans gravité pour `derniere_tonte`, mais **pas** neutre pour
  `_count_tonte_events_since_latest_phase_start` (`guidance.py`), qui **compte** les entrées
  pour décider de la transition de sursemis — un doublon y valait une tonte qui n'a jamais eu
  lieu. Le filet Node-RED de 23:50 peut donc rester en place sans dédoubler quoi que ce soit.
- **Réglages** : `switch.…_declaration_tonte_auto` (désactivé par défaut, comme les deux autres
  automatismes) et `number.…_seuil_declaration_tonte` (90 min par défaut, la valeur qu'appliquait
  Node-RED). Le seuil est un **plancher de crédibilité**, pas une durée normale : en dessous, le
  robot est sorti sans faire le tour et l'inscrire remettrait le retard à zéro pour rien.
- **⚠️ Le piège du projet s'est refermé une fois de plus, et sur le diagnostic.** Les trois clés
  s'appelaient d'abord `mowing_auto_*`. Elles étaient déclarées dans `_COORDINATOR_SNAPSHOT_KEYS`
  **et** dans la liste d'attributs du capteur — et elles n'arrivaient **jamais** : deux filtres
  successifs (`decision_mowing.py`, `decision.py`) ne recopient du contexte tondeuse que les
  préfixes `tondeuse_` et `mower_`. Tout ce qui commence par `mowing_` y meurt en silence.
  Renommées en `mower_auto_*`, vérifiées **du contexte jusqu'au snapshot publié**. Le test qui
  manquait suit désormais la sortie réelle du coordinator jusqu'au bout — un test qui se donne
  lui-même les noms de clés survivrait à un renommage, donc ne testerait plus rien.
- **Diagnostic** : `mower_auto_declaration_state` dit **pourquoi** rien n'a été inscrit
  (`desactivee` · `sans_mesure` · `sous_seuil` · `deja_declaree` · `declaree`), avec le seuil
  appliqué. Un automatisme muet qui n'agit pas est indiscernable d'un automatisme cassé.
- **Réglages effacés — défaut DISTINCT et PRÉEXISTANT, trouvé en câblant les deux nouveaux.**
  `compute_memory` **reconstruit** la mémoire à chaque cycle et `compute_snapshot` la
  **remplace** : tout réglage absent de ce dict est perdu au bout de deux minutes. La garde
  existait, avec son commentaire et son test — mais **elle ne couvrait que les booléens**
  (`assertIs(..., False)`). Résultat, le curseur **« Délai reprise tonte après arrosage »
  revenait à 180 min deux minutes après chaque réglage, depuis le jour de sa livraison**.
  Vérifié en exécution le 08/08/2026 avant et après correction. Les trois réglages
  (le délai de reprise, plus les deux nouveaux) sont désormais reconduits, via un helper
  `_reglage_entier` qui fait retomber une valeur illisible sur le défaut au lieu de la
  propager jusqu'au curseur.
- **Vérification** : 36 nouveaux tests, dont un test de **prémisse** (le montage déclare bien
  quand tout est réuni — sans lui, un montage qui n'atteint jamais le code rendrait les autres
  verts pour rien) et deux tests de **câblage** (l'appel existe dans le cycle, et il précède
  `compute_snapshot`). Les **15 mutations** du banc sont détectées. Le test de robustesse a
  trouvé un vrai trou pendant l'écriture : le seuil se lisait hors du `try`, donc un
  coordinator dégradé faisait remonter l'exception dans le cycle.

## 0.51.1

1020 tests verts. **Le cumul de fiabilité de la tondeuse survit enfin aux redémarrages.**

Découvert en relisant l'état persisté **juste après le déploiement de la 0.51.0** :
`mower_health` accumulait en mémoire et n'atteignait jamais le disque.
`_serialized_runtime_state` est une liste blanche clé par clé — une clé absente n'est jamais
persistée. Or c'est un cumul de la **journée**, et les redémarrages sont fréquents sur cette
installation : le compteur repartait de zéro à chaque fois, ce qui le rendait inutile
précisément les jours agités.

Sérialisation **et** restauration ajoutées, avec un test d'aller-retour complet : sérialiser
sans relire aurait été pire qu'absent, puisqu'invisible.

C'est le piège que ce projet documente depuis des semaines, et il s'est refermé sur le
correctif écrit une heure plus tôt. Vérifier après déploiement, pas seulement avant.

## 0.51.0

1016 tests verts. **Le pluviomètre baisse en cours de journée, et la réserve le suivait.**

Mesuré le 04/08/2026 sur le capteur journalier — **dix baisses intra-journée** :

```
00:48 1,0 → 03:11 2,6 → 04:08 2,5 → 04:20 3,5 → 04:44 2,7 → 17:17 4,2
      → 19:08 3,4 → 20:11 4,0 → 21:50 2,9 → 23:52 3,1
```

La réserve les suivait pas pour pas : entre 21:33 et 21:50 elle passe de 9,8 à 8,9 mm pour un
pluviomètre qui recule de 3,8 à 2,9 — pendant que l'ET0 horaire valait **0,04 mm/h**, quatre-
vingt-dix fois moins. Le bilan retenait la **dernière** lecture (3,1) quand le maximum du jour
valait **4,2** : 1,1 mm réellement tombé n'entrait jamais au bilan, un jour de rattrapage.

**L'objection qui avait fait refuser un `max()` reste respectée.** Le capteur se remet à zéro
plusieurs dizaines de minutes après minuit local : un maximum nu figerait le cumul de la veille
pour toute la journée. La différence, c'est qu'on détecte désormais la **remise à zéro** — une
chute vers ~0 — au lieu de se fier à l'heure. Le cliquet se relâche alors de lui-même et repart
de la nouvelle base.

Ça corrige du même coup la **marche de minuit**, vérifiée deux fois : 31/07, réserve 8,6 mm à
23:36:27 → **11,2 à 00:00:32** → retour à 8,6 à 00:44:32 ; et 05/08, 9,1 → **12,2** → 9,1.

Le maximum du jour est écrit dans le journal (`pluie_pic_mm`) **et** dans sa liste blanche de
normalisation — sans quoi le cliquet perdrait sa mémoire à chaque cycle et à chaque
rechargement du state persisté. C'est le piège que ce fichier documente lui-même.

Les 5 mutations correspondantes sont détectées, dont les deux bornes de la détection de remise
à zéro : « toute chute est un reset » et « aucune chute n'en est un ».

## 0.50.0

1010 tests verts. **L'intégration n'est plus aveugle aux blocages de la tondeuse.**

Elle voyait chaque erreur passer et n'en gardait aucune trace. Découvrir que le robot passait
plus de temps coincé qu'à tondre a demandé de rejouer l'historique de Home Assistant à la main :

```
jour     tondu     bloqué   épisodes
02/08    130 min   123 min      3
03/08    174 min   318 min      2      ← bloquée ~2× plus qu'elle ne tond
04/08    286 min   321 min      6
05/08    302 min    53 min      3
```

contre **zéro blocage** les 26, 28 et 30/07. Ce n'est pas de l'usure : c'est un changement, et
il faut pouvoir le voir sans requête d'historique.

Quatre attributs sur « État de tonte » : `mower_blocked_minutes_today`,
`mower_mowing_minutes_today`, `mower_block_count_today` et `mower_reliability_today`
(`normale` / `degradee` / `critique`). Le seuil critique est celui que les données désignent
elles-mêmes : **temps bloqué ≥ temps tondu**.

⚠️ **Une absence de mesure n'est PAS une absence de blocage.** Quand la tondeuse est
injoignable, l'horloge avance sans rien créditer — sinon une panne de liaison se lirait comme
une journée parfaite. Et au-delà de 15 minutes entre deux cycles, l'écart est traité comme un
trou (arrêt de Home Assistant) et non comme une durée : sans ce plafond, un redémarrage de
quatre heures aurait fabriqué quatre heures de blocage fictif.

Les 5 mutations correspondantes sont détectées, dont ces deux replis.

## 0.49.0

1002 tests verts. **Instrumentation — ce correctif ne corrige rien, il rend mesurable.**

Deux phénomènes de l'audit du 06/08/2026 restaient **inexpliqués**. Les corriger à l'aveugle
aurait reproduit exactement l'erreur commise la nuit précédente sur le réservoir : trancher sur
un diagnostic non vérifié. On mesure d'abord.

- **L'objectif d'arrosage n'est pas reproductible.** Le 06/08, il passe de **5,0 à 0,0** avec
  réserve, déficits, ETP, température, `depletion_ratio` et `block_reason` **tous identiques** —
  9 bascules en une heure, aucun `unavailable` dans la fenêtre, donc pas un redémarrage. Même
  signature *pendant* des sessions (04/08, 30/07). Aucune dose fausse n'en est résultée, et
  c'est vérifié : les vannes du 04/08 (33 / 33 / 27 min) donnent bien 7,7 mm. Mais c'est la
  variable de décision, et elle n'est pas reconstructible depuis ce que le système publie.

  Nouveau bloc `decision_cycle` : `cycle_origine` (`capteur:<entity_id>`, `vanne:<entity_id>`
  ou `intervalle`), `cycle_sequence`, `cycle_at`. Deux publications de la même seconde portant
  des origines différentes signeront la concurrence entre le rafraîchissement sur événement et
  le cycle périodique de 2 min — l'hypothèse à confirmer **ou à écarter**.

- **`configured_missing` publié sur une tondeuse présente et à la station**, sans un seul
  changement d'état de 13:40 à 13:47. La cause est interne, pas externe. En lisant le code :
  si la machine d'états de Home Assistant n'est pas interrogeable, `mower_state` vaut `None` —
  et **« je n'ai pas pu interroger » produisait le même verdict que « l'entité n'existe pas »**.
  C'est la signature exacte de la famille de défauts : une incapacité devient une affirmation.

  Nouveau champ `mower_resolution_probe` : `ok`, `entite_absente`,
  `machine_etats_injoignable`, `aucun_candidat`, `plusieurs_candidats`. Il traverse les deux
  listes blanches de clés tondeuse — le piège documenté du projet, vérifié de bout en bout.

Aucune décision ne dépend de ces traces, et les deux échouent en silence si quoi que ce soit
manque : une instrumentation qui casse un cycle de décision serait pire que le défaut qu'elle
observe. Les 4 mutations correspondantes sont détectées.

## 0.48.0

996 tests verts. **Quatre affichages qui rendaient le diagnostic faux.**

Aucun ne change une décision. Tous font perdre du temps au moment où quelque chose cloche —
c'est-à-dire au pire moment.

- **« Non requis » couvrait un blocage.** L'objectif tombe à 0 *parce qu'*un garde-fou retient
  l'eau : annoncer « aucun arrosage nécessaire » revient à dire que le gazon n'a besoin de rien
  alors qu'on lui refuse précisément ce dont il a besoin. Mesuré le 31/07/2026 à 10:46:50 :
  état « Non requis », résumé « Aucun arrosage nécessaire pour le moment », et dans ses propres
  attributs `block_reason: garde_fou_hebdomadaire`. **Le mensonge était l'état, pas le motif** —
  on garde donc le motif et l'état devient « Retenu », avec le résumé qui nomme la cause.

- **Une panne s'affichait « Au repos ».** Le robot annonce `idle` quand il est immobilisé en
  plein jardin ; l'état brut l'emportait sur le statut dérivé. Vérifié : du 02 au 05/08/2026,
  les 7 arrêts en jardin coïncident **à la seconde** avec un déclenchement d'erreur, et l'état
  du robot y vaut `idle`. Une panne prime désormais — sans perdre la précision de l'état brut
  hors panne.

- **Six codes de blocage n'avaient aucun libellé** et s'affichaient en `snake_case` brut :
  `machine_unavailable`, `mowing_window_blocked`, `recent_watering`, `soil_wet`,
  `upcoming_watering`, `wet_grass`. Un test parcourt désormais les modules de décision et
  **échoue si un code publié n'a pas de libellé**.

- **« Prochain arrosage : aujourd'hui » à 15 h**, pour une fenêtre fermée depuis cinq heures.
  Un plancher existait mais ne se déclenchait que si on avait *déjà arrosé* ; le cas qui compte
  est l'inverse — la fenêtre du matin s'est écoulée **sans** arrosage, retenu par un garde-fou
  ou par les conditions. La borne vient du profil publié, jamais d'un littéral : elle bouge avec
  la saison et la phase.

Les 6 mutations correspondantes sont détectées.

## 0.47.0

988 tests verts. **Le correctif d'horodatage n'était branché que sur une des trois voies.**

Le 04/08/2026, l'historique d'arrosage a été corrigé pour porter le **début** de la session et
non sa fin — l'affichage annonçait « arrosé à 05:18 » pour un cycle parti à **03:45:13**,
vérifié sur les vannes (Z1 03:45→04:18, Z2 04:18→04:51, Z3 04:51→05:18).

Ce correctif n'avait été appliqué qu'à la voie de **détection**. Trois voies enregistrent un
arrosage dans le coordinateur :

| voie | quand | avant |
|---|---|---|
| détection | session repérée sur les vannes | ✅ corrigée le 04/08 |
| **cycle piloté** | **l'arrosage automatique de tous les matins** | ❌ heure de fin |
| cycle interrompu | arrêt manuel en cours de cycle | ❌ heure de fin |

Autrement dit, le chemin qui compte — celui qu'emprunte l'arrosage automatique quotidien —
continuait d'enregistrer l'heure de fin. **Un correctif livré mais non exécuté est pire qu'un
correctif absent : on le croit fait.**

Les deux voies manquantes transmettent désormais le début de session, et un **invariant de
source** interdit qu'une quatrième apparaisse sans le faire — c'est exactement le mode de
défaillance de cette famille, le correctif à moitié appliqué. Les 4 mutations sont détectées.

## 0.46.0

986 tests verts. **Un arrosage manuel de secours ne réarme plus le blocage qu'il venait de
contourner.**

La retenue hebdomadaire combine deux termes par un `and` : le nombre d'arrosages récents et le
budget en millimètres. Ils portaient sur des fenêtres **différentes**.

| | fenêtre | arrosages manuels |
|---|---|---|
| budget mm (`water.py`) | `days=6` → **7 jours** | **exclus** depuis le 25/07/2026 |
| compteur (`guidance.py`) | `days=7` → **8 jours** | **comptés** |

Le filtre retient `delta <= days` : `days=N` couvre donc N+1 jours calendaires. `water.py`
documente cette règle et l'applique partout ailleurs (jour = 0, 3 j = 2, 7 j = 6) — le
compteur avait été oublié.

Et surtout, `compute_recent_watering_count` **n'avait pas de quoi exclure le manuel** : le
paramètre n'existait pas. Or c'est précisément cette exclusion qui avait supprimé, le
25/07/2026, un cercle vicieux documenté dans le code : réserve à sec → arrosage auto bloqué →
arrosage manuel de secours → budget plus haut → auto bloqué plus longtemps → jamais de reprise.
Le cercle pouvait donc se refermer par l'autre porte : le manuel faisait passer le compte de 2
à 3 et **réarmait la retenue**.

Le compteur accepte désormais `include_manual`, et l'appelant lui passe la même fenêtre et le
même filtre que le budget.

Deux niveaux de test, parce que le premier ne suffisait pas : les tests du helper seul
laissaient passer **deux mutations sur trois** — on peut très bien avoir une fonction correcte
et un appelant qui lui donne la mauvaise fenêtre, ce qui était exactement le cas. Le second
part de l'historique et lit ce que la chaîne **publie**. Les 4 mutations sont détectées.

## 0.45.0

978 tests verts. **Les voyants de santé tombent enfin quand le capteur tombe — et l'ET
réellement débitée devient visible.**

Sans ces deux points, aucun des défauts trouvés par l'audit du 06/08 n'aurait été observable
la prochaine fois. C'est de l'outillage, pas du confort.

- **Les drapeaux testaient la valeur RÉSOLUE, donc post-repli.** Trois voyants alimentés par
  la même station physique, sur 144 h : `pluie_valid` faux **2,19 h** (il teste bien son
  capteur), `temperature_valid` **0,08 h**, `humidity_valid` **0,08 h**. Instant citable :
  le 29/07/2026 à 17:57:46, `temperature_valid: true` alors que le capteur était indisponible
  depuis 17:52:53 et que l'ET0 tournait sur le repli météo. Les deux testent désormais leur
  source, comme `pluie_valid`.

- **Le vent n'avait aucun drapeau** — alors que c'est le levier majeur de l'ET0. Mesuré sur
  757 échantillons appariés : vent mesuré médiane 4,7 km/h contre vent **prévu** médiane 10,1,
  le prévu supérieur dans **97 %** des cas. En rejouant le calcul sur les entrées réelles du
  29/07 : capteurs 8,9 mm · **vent seul replié 12,1 (+36 %)** · température seule repliée 8,8
  (−1 %). Ce jour-là, **deux secondes** de repli ont posé le pic d'ET0 du jour à 12,4, et le
  cliquet l'a figé pour la journée entière. Nouveaux : `wind_measured` et `wind_valid`.

- **L'entité météo elle-même n'avait aucun voyant** : indisponible 64 min le 03/08 **hors
  redémarrage**, tous les drapeaux au vert pendant ce temps. Nouveau :
  `weather_profile_available`.

- **`etp_ecoulee_mm` et `etp_jour_estime_mm` sont exposés.** L'ET qui vide réellement la
  réserve n'était visible nulle part ; seule l'estimation pleine journée l'était. L'écart n'est
  pas anecdotique : sur 8 jours, **36,7 mm débités contre 49,1 mm estimés, +33,8 %, 8 jours sur
  8 dans le même sens**. C'est ce chiffre qui aurait montré d'un coup d'œil la marche du 29/07
  — +1,0 mm en 68 secondes, soit 53 mm/h, quand l'ET0 horaire réelle plafonne vers 0,6.

Le calcul des voyants est extrait dans `_build_sensor_health`, appelable directement : la
première version des tests **reproduisait l'expression** au lieu d'appeler le code, ce qui les
rendait aveugles à toute modification du coordinateur — le même piège déclaration/câblage que
celui qui a laissé vivre le défaut de condition météo. Les 6 mutations sont détectées.

La lecture du journal est défensive par construction : elle alimente `sensor_health`, et une
exception y priverait l'utilisateur de **tous** ses voyants. Sept formes dégradées sont testées.

## 0.44.0

971 tests verts. **Le garde « il pleut en ce moment » s'arme enfin — il n'avait jamais
fonctionné depuis le 18/03/2026.**

Chez Home Assistant, la condition d'une entité `weather.*` **EST son état** (`sunny`, `rainy`,
`pouring`…) et n'apparaît pas dans ses attributs. Le coordinateur ne transmettait que les
attributs : `weather_condition` valait donc **toujours `None`**, et avec lui tout le garde de
pluie active.

**Ce que ça a coûté, mesuré le 30/07/2026** : `weather.forecast_maison` valait `rainy` de
06:43 à 09:28, le pluviomètre montait de 1,1 à 2,2 mm — et à **07:38 l'arrosage automatique a
versé 5,1 mm sous la pluie**, le capteur de blocage affichant « Prêt ».

Preuve de durée, pas d'anecdote : la clé `derniere_pluie_active` n'apparaît nulle part dans
l'état persisté (37 clés de mémoire), et le libellé « Pluie active » n'apparaît sur **aucun**
des 208 états du capteur de blocage relevés sur la période auditée.

**Ce que le correctif rallume** — le garde alimente plus de chemins que le seul arrosage :

- blocage de l'arrosage pendant la pluie (`pluie_active`) ;
- blocage de la **fenêtre de tonte**, et surtout le **ressuyage après averse**, dont la 0.32.0
  annonçait la correction sans qu'il ait jamais pu s'appliquer ;
- rosée forcée à 1,0 sous pluie ou brouillard, côté coordinateur ;
- facteur de sol relevé à 0,95 sous la pluie ;
- et un **malus de confiance de −2 qui s'appliquait en permanence**, puisqu'il pénalisait une
  condition météo « manquante » qui ne pouvait pas arriver.

⚠️ **À déployer en connaissance de cause.** Ce garde n'a jamais tourné : personne ne sait
combien de fois il va bloquer. À mettre en service un matin où l'on peut observer, avec une
semaine de recul — pas en aveugle.

Le test qui manquait était un test de **câblage** : ceux qui existaient passaient à
`extract_weather_profile` un dictionnaire contenant `"condition"`, une forme que la production
ne produit jamais. Ils vérifiaient une déclaration, pas le chemin réel. Le nouveau part de
l'entité Home Assistant et va jusqu'au booléen. Les 4 mutations correspondantes sont détectées.

**Reste ouvert, non corrigé ici** : `weather_precipitation_probability` est lui aussi
toujours nul (la probabilité vit dans les prévisions, pas dans l'état), donc le second bras de
`is_active_rain_weather` (≥ 80 %) reste inerte, et le repli à 0,0 de `guidance.py` continue de
faire passer « inconnu » pour « 0 % de chances de pluie » — inoffensif en phase Normal,
permissif en Sursemis.

## 0.43.0

962 tests verts. **Une panne du robot ne transforme plus un « non » du gazon en « oui ».**

Mesuré sur l'installation le 06/08/2026, **douze millisecondes d'écart** :

```
13:41:44.040  tondeuse vue (1 candidat)  mowing_spacing       off  · prochaine 08/08
13:41:44.052  0 candidat                 machine_unavailable  ON   · prochaine 06/08
13:41:54.177  tondeuse revue             mowing_spacing       off  · prochaine 08/08
```

Sur la fenêtre auditée, `tonte_autorisee` a été à `on` **49,77 h sur 241,28 h (20,6 %)**, en
82 épisodes dont 58 sous la minute — et **99 % de ce temps sous `machine_unavailable`**.

**Trois mécanismes indépendants, tous les trois corrigés.** Le correctif part d'un bloc :
n'en appliquer qu'une partie laisserait une des deux défenses tomber seule.

- **La porte agronomique relisait un motif déjà réécrit.** Quand la machine tombe,
  `reason_code` est délibérément remplacé par `machine_unavailable` (une panne prime sur un
  délai à l'affichage — comportement voulu, conservé). Mais le test d'autorisation lisait ce
  code réécrit : comme `machine_unavailable` n'est pas dans `agronomic_block_codes`, la porte
  s'ouvrait. Un `mowing_spacing` ou un `mowing_night` valide était effacé par une seconde
  d'inattention du robot. Le test porte désormais sur `selected_reason_code`, capturé avant
  tout écrasement.

- **Le verdict de la fenêtre horaire était annulé par un autre blocage.**
  `mowing_window_blocked_by_schedule = ... and not mowing_blocked` : dès qu'une panne
  survenait, le « Nuit : attendre le lever du soleil » ne comptait plus. Le drapeau
  d'affichage est inchangé ; un drapeau distinct, `mowing_window_blocked_by_clock`, porte
  désormais le verdict de l'horloge pour l'autorisation.

- **Et ce verdict était écrasé avant même d'être lu** — l'état de la fenêtre est remplacé par
  le motif machine deux lignes plus haut. Il est maintenant capturé avant.

- **L'heure passe avant les verdicts « à éviter »** (`_resolve_mowing_window`). Les bornes
  horaires sont BLOQUANTES ; le vent soutenu et la chaleur ne font que déconseiller. Testées
  après, un simple « à éviter » l'emportait sur un refus ferme : par nuit d'été tiède la
  fenêtre publiait « Température élevée : à éviter » au lieu de « Nuit ». Relevé le 05/08 à
  21:38 et 21:40, soleil couché depuis 21:26. **Le défaut ne touchait pas que la nuit** : à
  3 h du matin par 27 °C, « Matin trop tôt » tombait pareillement — toute la plage 22 h → 10 h.

**Le contrat des deux axes est préservé, et testé dans les deux sens** : en pleine journée sur
un gazon prêt, une panne du robot ne fait PAS passer `tonte_autorisee` à non — c'est
`machine_permet_tonte` qui porte le matériel et `action_possible` qui combine.

Les quatre mutations correspondantes sont détectées par la suite, vérifié après purge des
caches de bytecode — une première passe donnait deux faux « non détecté » à cause de `.pyc`
périmés que les permutations de fichier n'invalidaient pas.

## 0.42.0

949 tests verts. **L'alerte ne s'éteint plus parce que le blocage s'allume.**

Deux sorties publiées se contredisaient exactement les jours où l'eau était retenue — donc
exactement les jours où il fallait pouvoir lire le diagnostic.

- **Risque du gazon** : le chemin « objectif ramené à 0 » posait `risque_gazon: faible` par
  LITTÉRAL, sans regarder le sol. Mesuré sur l'installation le 01/08/2026 : à 15:30:35, réserve
  2,8 mm → « eleve / critique » ; à 15:32:44, **même réserve, même `hydric_state: critique`**,
  mais `block_reason: garde_fou_hebdomadaire` → « faible / aucune_action ». Sur 239 h auditées,
  **19 h 34** d'`etat_hydrique: critique` coexistaient avec un risque annoncé faible. Et comme
  `risque_gazon` alimente `compute_next_reevaluation`, la cadence de réévaluation baissait en
  même temps que l'alerte se taisait — c'est ce qui a rendu invisibles les trois jours à 0 mm
  de réserve (31/07 → 02/08). Le risque est désormais calculé même sous blocage ; le niveau
  d'action, lui, reste `aucune_action` puisqu'il n'y a effectivement rien à faire.

- **Raisons du risque** : `_raisons_par_defaut` ajoutait « stress hydrique {niveau} » sans
  regarder le niveau qu'elle accompagnait, d'où l'impossible `risque_gazon: faible` justifié par
  `["stress hydrique eleve"]`, relevé deux fois. Une raison doit expliquer le niveau qu'elle
  accompagne, sinon le lecteur doit choisir laquelle des deux sorties croire.

- **Code mort retiré** : `_build_guidance_window_payload` lisait
  `block_reason=locals().get("block_reason")`, copié depuis une fonction où la variable existe
  vraiment. Cette fonction n'a pas ce paramètre : l'expression valait **toujours** `None`. Le
  motif réel n'arrivait donc jamais dans `risque_gazon_raisons`.

Les quatre mutations correspondantes ont été vérifiées : remettre le littéral, remettre la
raison contradictoire, ignorer le motif de blocage, autoriser une raison vide — chacune est
détectée par la suite.

## 0.41.1

942 tests verts. **Vérification que les desserrages de la semaine n'ont pas ouvert la porte au
sur-arrosage.**

Trois verrous ont été retirés entre le 01/08 et le 04/08 — prévision de pluie (0.37.0), retenue
hebdomadaire (0.38.0), réduction de dose par la pluie (0.39.0). Chacun avait ses tests ; aucun
ne vérifiait la propriété qui compte : **on n'a pas cassé le plafond en enlevant les blocages.**
C'est le risque exact qu'on prend à desserrer.

Balayage systématique de **2 100 combinaisons** — déplétion × cumul 7 jours × pluie annoncée ×
température/ET0 — sur deux invariants :

- **P1** — une dose n'est versée que si la déplétion **projetée** atteint le seuil MAD.
- **P2** — la dose ne dépasse jamais la marge hebdomadaire, hors secours documentés (survie
  canicule ≥ 32 °C, réserve réellement vide ≥ 90 %).

**Zéro violation.** Et le balayage prouve qu'il sait mordre avant de l'affirmer : neutraliser le
seuil MAD lève 75 violations de P1, neutraliser le plafond hebdomadaire en lève 560. Un
troisième test refuse de conclure si le balayage ne produit pas au moins 200 cas d'arrosage —
sans quoi P1 et P2 seraient vraies par vacuité.

## 0.41.0

939 tests verts. **L'horodatage affiché d'un arrosage est désormais son DÉBUT, pas sa fin.**

Signalé par Kévin le 04/08/2026, et vérifié sur les vannes :

    Zone 1  03:45:13 → 04:18:13      Zone 2  04:18:13 → 04:51:13      Zone 3  04:51:13 → 05:18:13

L'intégration annonçait « arrosé à **05:18** » — la fermeture de la dernière vanne. Le cycle
était en réalité parti **treize secondes** après l'ouverture de la fenêtre (03:45). L'écart
faisait croire à 1 h 30 de retard au déclenchement, retard qui n'a jamais existé — j'en avais
moi-même tiré un faux diagnostic avant que Kévin ne me corrige.

- La session **connaissait** son début : `started_at` servait à calculer la durée, puis était
  jeté. Il est maintenant enregistré dans l'historique, aux côtés de `ended_at`.
- L'affichage (`last_watering_when`, et la liste des sessions de la carte) lit le début.
  Les entrées antérieures n'ont pas ce champ : elles retombent sur la fin, comme avant.
- **Le calcul d'espacement ne bouge pas.** `water.resolve_history_moment` lit `ended_at` en
  premier — même instant qu'auparavant. Le cooldown 24 h garde sa référence, et une mutation
  qui inverse cet ordre fait tomber un test.

Trois mutations. La première série de tests ne vérifiait que la LECTURE : supprimer l'écriture
côté coordinateur passait au vert. Le trou a été comblé avant de conclure.

## 0.40.0

935 tests verts. **Le motif de blocage de la tonte est enfin le même partout.**

Constaté sur l'écran de Kévin le 03/08/2026 à 14 h 31, robot **en tonte** depuis 14 h 19 :

    binary_sensor.tonte_autorisee  → « Robot déjà en tonte : attendre la fin du cycle. »  juste
    sensor.hauteur_de_tonte        → « Robot indisponible : attendre qu'elle soit prête. » faux

Même attribut (`mowing_window_reason`), deux valeurs, même instant — vérifié par une lecture
indépendante côté Home Assistant. Et c'est la fausse que le bandeau de la carte affichait.

La décision publiait le libellé **générique** alors qu'elle calculait le libellé **précis** deux
lignes plus haut. Chaque plateforme d'entité le rafistolait ensuite de son côté — sauf qu'elles
ne le faisaient pas toutes. Le raffinement est remonté **à la source** : une seule fois, pour
tous les consommateurs. Le post-traitement des plateformes devient redondant, et inoffensif.

C'est le schéma du « correctif à moitié appliqué », pour la troisième fois de la semaine :
corriger là où c'est signalé, sans chercher les autres endroits qui affichent la même chose.

## 0.39.1

935 tests verts. **Les deux commutateurs de diagnostic n'apparaissaient toujours pas.**

Ajoutés en 0.36.0, `etp_connue` et `reserve_from_soil_ledger` étaient bien déclarés dans
`_objective_attrs_keys()` et bien présents dans le sous-dictionnaire `water_balance` — et
pourtant absents de l'entité, constaté sur l'installation le 02/08/2026.

**Il existe une CINQUIÈME liste blanche** : les clés du bilan hydrique ne remontent pas seules
au niveau racine du snapshot, elles y sont recopiées une par une dans `decision.py`. Déclarer
une clé côté capteur ne suffit donc pas.

Le test qui les couvrait vérifiait la *déclaration* (clé présente dans la liste du capteur, clé
présente dans `water_balance`) — deux affirmations vraies pendant que la valeur ne sortait pas.
Il vérifie désormais la *remontée*, au niveau où l'entité lit réellement.

## 0.39.0

935 tests verts. **La prévision de pluie ne rabote plus la dose d'un sol qui a soif — et le
blocage que la 0.37.0 croyait avoir supprimé venait en fait d'un SECOND endroit.**

Constaté sur l'installation le 02/08/2026 à 22 h 40, sol à **0,0 mm** : le profil calculait
12,0 mm — `besoin_mm: 12`, `mm_final: 12` jusque dans `evening_cooling_debug` — et l'entité
publiait **9,6**. Soit 12 × 0,8 : une réduction de 20 % déclenchée par 2,9 mm annoncés.

- **La réduction vit dans `decision_watering`, pas dans `guidance`.** Deux paliers : −60 %
  (« pluie compensatrice ») et −20 % (≥ 2 mm annoncés demain, ou ≥ 4 mm à J+2/J+3). Aucun des
  deux ne regardait l'état du sol.
- **Pire : ce bloc pose aussi `rain_floor_block_reason = "pluie_prevue_suffisante"`** quand la
  dose réduite passe sous la session minimale. C'est *exactement* le motif que la 0.37.0
  neutralisait — mais il venait d'ici, donc il subsistait. Un test du dépôt le documentait déjà
  sans que personne n'y voie un défaut : sol pile au seuil MAD (6/12), 2 mm annoncés, dose
  ramenée de 6 à 4,8 mm, sous le minimum de 5 → blocage. **Ce test vérifiait le défaut.**
  Il vérifie désormais l'inverse.
- Les deux paliers sont bornés au **seuil MAD**, comme les blocages amont. Sous le seuil, la
  réduction s'applique toujours : économiser un cycle quand le sol est confortable reste juste.

Contrepartie assumée, choisie par Kévin : si la pluie tombe pour de vrai, on aura versé un peu
trop — l'excédent draine sous les racines. Le sol reste borné par sa capacité.

Quatre mutations. La branche −60 % n'était couverte par aucun test sur sol assoiffé : le trou a
été comblé avant de conclure.

## 0.38.0

933 tests verts. **La retenue hebdomadaire ne laisse plus le sol passer sous son seuil.**

Deuxième moitié de l'enquête du 02/08 : le gazon n'a pas été arrosé pendant **trois matins**, et
ce n'est pas le même motif chaque jour.

    31/07 04:00 — réserve 8,6/12, ratio 0,28 → « confort · surveiller »        blocage LÉGITIME
    01/08 04:00 — réserve 5,4/12, ratio 0,55 → « depletion · arroser           blocage FAUTIF
                                                 profondément »
    02/08 03:20 — réserve 1,2/12, ratio 0,90 → « critique »                    pluie (0.37.0)

- **Le 01/08, la retenue jugeait sur la mauvaise grandeur.** Elle lit `deficit_mm_ajuste`, issu
  du modèle **legacy** (4,3 mm — sous le plancher de 21, donc « pas besoin »), alors que le
  déclenchement se fait sur la déplétion du **ledger** : 6,6 mm sur 12, soit un ratio de 0,55,
  **au-dessus du MAD de 0,50**. Le legacy sous-estimait de 2,3 mm. Le même cycle publiait
  `hydric_state: depletion` et `hydric_strategy: arroser profondément` — et rien n'est parti.
  Sans eau ce matin-là, le sol est arrivé au 02/08 à 1,2 mm, puis à **ZÉRO** à 12 h 09.
  La retenue ne s'applique donc plus au-delà du seuil de déclenchement.

**Le garde-fou n'est pas vidé de son sens**, et c'est vérifié par un test dédié : le
déclenchement se fait sur la déplétion **projetée** (réelle + ETc restante), la retenue sur la
déplétion **réelle**. Un sol encore confortable à l'aube mais qui aura soif le soir déclenche —
et reste retenable. C'est exactement le 31/07, dont le blocage reste légitime. Une mutation
remplaçant la déplétion réelle par la projetée fait tomber six tests.

Son intention écrite est de « plafonner un sur-arrosage HÉRITÉ » : un sol au-delà de son seuil
de déclenchement n'est pas du sur-arrosage.

Trois mutations, toutes détectées.

## 0.37.0

930 tests verts. **Une prévision de pluie ne bloque plus un sol qui a déjà soif.**

La nuit du 02/08/2026, le gazon a touché **zéro**. À 03 h 20, la prévision de pluie passe de
3,1 à 9,1 mm : `pluie_prevue_suffisante` se déclenche, l'objectif tombe de 8,6 à **0,0 mm** et y
reste jusqu'à 10 h 13 — **toute la fenêtre d'arrosage** (03:45–10:00). Au même instant,
l'intégration publiait `reserve_actuelle_mm: 1,2 sur 12`, `depletion_ratio: 0,90`,
`hydric_state: critique`, `hydric_strategy: arroser rapidement en profondeur`, et 34,5 °C
prévus. Il est tombé **3,2 mm effectifs pour 4,8 consommés** : la réserve a atteint 0,0 mm à
12 h 09 et n'en est pas ressortie. Dernier arrosage : le 30/07.

**La pluie était le seul des cinq blocages sans échappatoire sur l'état du sol** — et le seul
fondé sur une prévision, donc le moins fiable des cinq. Les quatre autres ont tous leur
`not _reserve_critique_reelle`, `not _ledger_demande_eau` ou `not _survie_canicule`.

- Le seuil retenu est le **MAD**, celui-là même qui déclenche l'arrosage : tant que le sol est
  confortable, une pluie annoncée fait encore économiser un cycle ; dès qu'il réclame, la
  prévision ne décide plus à sa place.
- **La pluie RÉELLEMENT tombée continue de bloquer** — c'est un fait, pas un pari. Seule la
  prévision est concernée.
- Le garde est volontairement **indépendant du ledger** : il ne peut que débloquer, jamais
  bloquer. Le faire dépendre d'une source qui peut manquer le rendrait inerte au pire moment.

Arbitrage de Kévin, 02/08/2026 : « la pluie prévue n'est jamais sûre, je préfère arroser ».
Quatre mutations, toutes détectées — dont le retour au blocage inconditionnel et un garde qui
supprimerait la pluie de tous les cas.

## 0.36.0

925 tests verts. **Un déficit inconnu n'est plus lu comme un déficit nul.**

- **`compute_water_balance` écrasait l'absence d'ET0 en zéro** (`etp or 0.0`). Tous les déficits
  qui en découlent tombaient alors à 0 — un « pas de besoin » rigoureusement indiscernable d'un
  vrai. Or la retenue hebdomadaire exige `deficit_mm_ajuste < plancher` : la condition devenait
  **automatiquement vraie sur du vide**. Mesuré le 01/08/2026, premier cycle d'un redémarrage
  (capteur de température pas encore là) : `bilan_hydrique_mm: 0`, `deficit_3j: 0`,
  `deficit_7j: 0`, motif `garde_fou_hebdomadaire` — pendant que la déplétion du ledger valait
  **8,2 mm** pour une réserve de 3,8 sur un seuil de 6,0. Sur une coupure plus longue du capteur,
  la même mécanique a supprimé l'objectif **20 minutes DANS la fenêtre d'arrosage** (30/07,
  08 h 13 → 08 h 33 ; l'arrosage n'est parti qu'à 08 h 40, dès le retour du capteur).
  La retenue exige désormais un déficit **mesuré**. Le repli à 0 reste pour le calcul — il n'y a
  rien de mieux — mais l'incertitude est publiée (`etp_connue`) et consommée.
- **Les deux commutateurs qui changent tout le calcul sont enfin visibles** sur
  `sensor.objectif_d_arrosage` : `reserve_from_soil_ledger` (quel modèle pilote — déplétion ou
  déficit legacy) et `etp_connue`. Ils décidaient en silence depuis toujours.

Montée de version couverte : un état persisté sans `etp_connue` garde l'ancien comportement
(défaut à *vrai*), sinon la retenue ne se déclencherait plus jamais — un sur-arrosage silencieux,
pire que le défaut corrigé. Sept mutations, toutes détectées.

### Note
Le signalement de la veille sur `et0_source: fallback_pm_location` contredisant
`eto_radiation_measured: true` était **erroné** : ce sont deux grandeurs distinctes — l'ET0
**journalière** (Penman-Monteith depuis la position, mode normal sans capteur ETP) et la chaîne
ET0 **horaire** (rayonnement mesuré). Aucun défaut de ce côté.

## 0.35.0

921 tests verts. **Le besoin du sol ne disparaît plus derrière un blocage.**

Signalé par Kévin : l'entité « Objectif d'arrosage » affichait **0,0 mm** pendant que ses
propres attributs annonçaient `depletion_mm: 7,8` et une réserve 1,8 mm SOUS le seuil de
déclenchement. Relevé **six fois en trois jours**, dont quatre retours à la valeur identique
(7,4 → 0,0 → 7,4) : un besoin réel ne disparaît pas pour revenir inchangé.

Cause : `if block_reason is not None: mm_cible = 0.0`, écrit dans les deux branches de calcul.
Zéro est **juste** pour la DOSE — un arrosage bloqué verse bien zéro, et cette valeur sert de
`target_cycle_mm` au plan d'arrosage. Il est **faux** pour le BESOIN, qu'aucun garde-fou ne
fait disparaître. Une seule variable portait les deux questions.

- **Nouvel attribut `besoin_mm`** sur `sensor.objectif_d_arrosage` : ce que le sol réclame,
  insensible aux blocages ET au plafond hebdomadaire (une politique n'est pas un besoin).
  `objectif_mm` garde son sens exact — aucun changement sur le déclenchement ni sur les doses.
- La carte (0.24.0) affiche « le sol réclame toujours X mm » sous un arrosage retenu.

Six mutations couvrent la chaîne complète — profil, deux assemblages de bundle, `decision.py`,
`to_snapshot`, attributs du capteur. Une première série ne vérifiait que les *déclarations* :
trois de ces mutations passaient au vert. Le test part désormais de `build_decision_snapshot`
et reproduit le cas réel du 01/08 (retenue hebdomadaire, branche déplétion).

## 0.34.0

913 tests verts. **Le gazon ne dé-pousse plus.** Signalé par Kévin sur l'historique du capteur
de hauteur : 09 h 10 → 6,0 cm, 11 h 40 → 5,9 cm, sans tonte entre les deux.

- **La pousse déjà acquise n'est plus recalculée.** `pousse_jour = taux × frein × fraction`
  appliquait le frein du MOMENT à toute la journée : dès que la chaleur montait, la pousse du
  matin était effacée et la hauteur redescendait. Sur l'installation, le 01/08 —
  09 h 10 : frein 0,87 × fraction 0,55 = 0,165 cm ; 11 h 40 : frein 0,50 × fraction 0,63 =
  0,109 cm. **Un tiers de la matinée effacé.** Le frein thermique étant un escalier
  (≤ 24 °C : 1,0 · > 24 °C : 0,65), franchir 24,0 °C suffisait à en perdre 35 % d'un coup.
  La pousse du jour s'**accumule** désormais : le frein ne pilote plus que l'incrément à venir.
  À conditions stables, le total de fin de journée est identique — c'est le chemin qui cesse de
  reculer, pas le modèle qui change. Même famille que la falaise de minuit (0.31.1) : le passé
  qu'on recalcule.
- **Eau inconnue ≠ eau à volonté.** Au redémarrage, le premier cycle tourne sans bilan
  hydrique : le frein d'eau était silencieusement sauté, donc un frein plus optimiste et une
  hauteur trop haute publiée pendant ~1 s (relevé : 12:39:34,5 → 6,0 cm puis 12:39:35,4 →
  5,9 cm, et le même doublet la veille). Sans bilan, le frein ne peut plus dépasser le dernier
  connu **du jour** — jamais celui d'hier, qui décrirait une autre météo. Même piège que le
  repli « soleil inconnu → 1.0 » de la 0.21.4.

Huit mutations vérifient les deux garde-fous, dont le retour au recalcul complet, un plafond
qui relèverait le frein au lieu de le borner, et le retrait du repli de migration. La montée
depuis 0.33.1 est couverte : l'état persisté n'a pas encore de `fraction`, le premier cycle
reprend donc la pousse mémorisée telle quelle — ni saut, ni chute — puis accumule.

## 0.33.1

902 tests verts. Deux défauts que la 0.33.0 a rendus VISIBLES en publiant
`application_constraints` — ils dormaient dans le payload depuis toujours.

- **Une date ISO brute s'affichait à l'écran.** Le libellé du délai de réapplication lisait
  `next_reapplication_display`… une clé produite par `_selection_details`, pas par le candidat
  évalué qui arrive là : le repli retombait donc **toujours** sur la date ISO. Résultat sur
  l'installation, une fois la contrainte affichée : « Réapplication attendue jusqu'au
  **2026-08-12** ». La date est formatée sur place, sans dépendre d'une clé venue d'ailleurs.
- **Le même motif bloquant s'affichait deux fois.** `blocked_reason` est un **récapitulatif** :
  chacune de ses parties (limite annuelle, délai de réapplication, température) a déjà sa propre
  contrainte. Republié tel quel, il donnait deux puces bloquantes pour un seul fait. Il n'est
  plus émis quand **toutes** ses parties sont déjà affichées séparément — et reste publié dès
  qu'une partie n'a pas de contrainte propre, ou qu'il vient d'ailleurs.
- **Une seule formulation par fait.** Le payload en portait trois pour la même date
  (« possible à partir du », « attendue jusqu'au », « possible depuis le »).

Note de méthode : le premier correctif dédoublonnait en comparant les **libellés**. Il est passé
au vert alors que le doublon était toujours là — parce que corriger la formulation avait rendu
les deux chaînes différentes pour un fait identique. Le garde-fou compare désormais les **codes**
de critères, et six mutations vérifient qu'il mord.

## 0.33.0

893 tests verts. Le tour complet de la carte : ce qui trompait sur une décision, corrigé
des deux côtés.

- **Le critère qui BLOQUE une intervention est enfin identifiable.** L'onglet Produits alignait
  quatre puces rigoureusement identiques — « Phase courante », « Mois compatibles »,
  « Réapplication possible à partir du 12/08/2026 », « Température compatible » — et rien ne
  disait laquelle retenait le produit. La polarité existait pourtant depuis toujours dans
  `constraints` (`met` / `blocking`) : elle n'était simplement jamais publiée, la carte ne
  recevant que `reason`, la concaténation « · » de tout. Nouvel attribut
  **`application_constraints`** sur `sensor.prochaine_intervention` : `code`, `label`, `met`,
  `blocking`, rien d'autre.
- **« Phase courante : entretien » donnait deux noms à une seule phase.** La phase du gazon est
  **Normal** ; « entretien » qualifie le PRODUIT, pas la phase. La carte affichait donc
  « PHASE / Normal » sur un onglet et « Phase courante : entretien » sur l'autre. Le libellé dit
  maintenant ce qu'il décrit : « Produit d'entretien, compatible en phase Normal ».
- **On sait enfin QUEL thermomètre a décidé.** L'intégration tranche sur le capteur extérieur,
  la carte affiche en en-tête l'entité météo : deux mesures justes, ~2 °C d'écart, et on lisait
  « 23,8 °C » en haut d'écran au-dessus d'un critère à « 25,8 °C », sans explication. Le critère
  nomme sa source : « 25,8 °C **au capteur** » (ou « selon la météo » / « selon la prévision »).
- **Ponctuation décimale unifiée.** `_format_temperature_value` sortait « 25.8 » au POINT — ces
  chaînes partent telles quelles à l'écran, au milieu de valeurs toutes à la virgule.

## 0.32.0

883 tests verts. Les quatre défauts de l'audit du 31/07, corrigés.

- **« Risque gazon élevé » ne se déclenche plus chaque nuit.** Le risque se décidait sur
  `bilan_hydrique_mm`, le bilan de la JOURNÉE (pluie + arrosage − ETc du jour) : à 2 h du matin,
  rien n'a encore été arrosé et l'ETc attendue vaut ~6 mm, donc le bilan est négatif
  MÉCANIQUEMENT. L'historique le prouvait — bascule sur « faible » à la seconde où l'arrosage
  du matin partait, trois nuits d'affilée. Ce n'était pas « ton gazon est en danger » mais
  « tu n'as pas encore arrosé aujourd'hui ». Le risque se décide désormais sur la **réserve du
  sol** quand le ledger en fournit une : même recentrage que celui appliqué à
  `hydric_balance_level` en 0.16.0, dont le correctif n'avait jamais été porté ici.
  Contradiction « bilan sain + risque élevé » mesurée : **25 % → 8 %** des scénarios.
  - Le chemin fautif était un `return` **anticipé** (`bilan <= -4.0`) qui sortait avant tous les
    blocs de finalisation — les trois premiers branchements n'y changeaient rien.
  - **Plancher de phase** : en Sursemis, la phase impose « au moins modéré ». Un semis n'a pas
    de réserve exploitable et ne doit jamais être annoncé sans risque. Un test l'a rattrapé.
- **Le capteur de risque explique enfin son niveau** — nouvel attribut `risque_gazon_raisons`.
  Il n'exposait que le risque fongique : un « élevé » était incompréhensible sans lire le code.
- **La pousse du gazon avance en continu**, plus par paliers d'une heure : `hour_of_day` passe
  de l'heure entière à l'heure décimale. Mesuré avant : `jour_cm` identique de 01 h 00 à 01 h 59,
  saut à 02 h. Aucune comparaison d'heure n'est une égalité, le flottant est sans effet de bord.
- **Délai de ressuyage après la pluie**, symétrique de celui après un arrosage (même réglage).
  `is_active_rain_weather` ne regarde que la météo de l'instant : il n'existait aucun délai après
  une averse, alors que le libellé promettait « pluie en cours ou récente ». Chaque constat de
  pluie est désormais horodaté dans la mémoire persistée, ce qui permet enfin de mesurer
  « récente ». Traverse minuit ; un horodatage de plus d'un jour est ignoré.

## 0.31.4

870 tests verts. L'attribut créé pour voir la pousse était arrondi au point de la masquer.

- **`gazon_pousse_jour_cm` affichait 0,0 pour 0,025 cm réellement poussés.** Une règle générique
  d'exposition arrondit toute clé finissant par `_cm` au dixième — sensé pour une hauteur, fatal
  pour une pousse journalière qui se compte en CENTIÈMES (0,02 à 0,05 par heure). L'attribut
  existait donc précisément pour rendre visible ce que l'arrondi de la hauteur masque, et il
  était masqué par le même mécanisme. Exception explicite au centième.
- **Constaté au passage, non corrigé** : la pousse avance par PALIERS D'UNE HEURE, le
  coordinateur passant `hour_of_day = current_dt.hour` (un entier). Corriger demanderait de
  transmettre l'heure décimale, ce qui touche toutes les comparaisons de fenêtres horaires
  (tonte, arrosage) — changement plus large, laissé à décider.

## 0.31.3

870 tests verts. Un saut de minuit revenu par une autre porte, refermé.

- **Le lendemain d'une tonte héritait d'une journée de pousse qui n'a jamais eu lieu.** Le report
  de la veille RECONSTITUAIT la pousse (`taux × frein`) au lieu de créditer celle réellement
  constatée. Or le jour de la tonte, la pousse est nulle par conception : le report lui créditait
  quand même une journée pleine, et la hauteur bondissait de 5,5 à 5,8 cm à minuit — exactement
  le défaut corrigé en 0.31.1, réintroduit sous une autre forme par le correctif lui-même.
- L'état mémorise désormais `jour_cm`, la pousse **constatée** du jour, et le report crédite cette
  valeur telle quelle. Repli sur l'ancienne reconstitution si l'état vient d'une version
  antérieure, pour ne pas perdre une journée à la montée de version.

## 0.31.2

869 tests verts. Trois défauts de fond, dont un que j'affirmais faussement dans un commentaire.

- **Le gazon pousse la nuit — et le modèle disait le contraire.** La pousse était bornée à
  7 h - 20 h au motif que « le gazon ne s'allonge pas la nuit ». C'était faux, par confusion
  entre deux mécanismes : la PHOTOSYNTHÈSE suit la lumière, mais l'ÉLONGATION cellulaire est
  poussée par la TURGESCENCE, maximale LA NUIT (le jour, la transpiration vide les cellules
  plus vite que les racines ne les remplissent). Sur graminées, l'élongation foliaire culmine
  en fin de nuit et s'effondre au zénith. La pousse est désormais étalée sur 24 h avec un pic
  vers 3 h ; le total du jour est inchangé (intégrale de la pondération = 1), seule la
  répartition horaire change. Effet visible : la hauteur n'est plus PLATE de 20 h à 7 h.
  Question de Kévin : « le gazon pousse la nuit ? ».
- **La reprise au démarrage ignorait l'arrosage automatique désactivé.** Un cycle interrompu
  repartait tout seul alors que l'auto avait été coupé avant le redémarrage. Une session
  MANUELLE, elle, reste légitime à reprendre : l'utilisateur l'a demandée.
- **L'exécuteur dormait en aveugle sur la vanne.** Pendant chaque segment il attendait la durée
  prévue sans jamais vérifier que le relais était resté ouvert : s'il retombait, la dose
  entière était comptée quand même — des millimètres fantômes crédités au bilan du sol pour de
  l'eau jamais versée. Un veilleur contrôle désormais l'état toutes les 15 s, relance UNE fois,
  puis abrège en ne comptant que le temps réellement ouvert (dose proratisée).
  - **Il n'agit que sur preuve** : avoir vu la vanne ouverte PUIS fermée. Sans preuve (état non
    rapporté, latence après la commande) il ne fait rien — sinon tous les segments seraient
    abrégés et plus rien ne serait arrosé.
  - **`unavailable` ne vaut pas `off`** : au redémarrage l'entité disparaît, pas le relais.
  - Toute lecture d'état qui échoue se lit « ouverte » : le veilleur ne peut pas casser un arrosage.
- **Libellé de blocage corrigé** : « pluie en cours ou RÉCENTE » promettait un délai de ressuyage
  qui n'existe pas — `is_active_rain_weather` ne regarde que la météo de l'instant. Devenu
  « il pleut ». Un vrai délai demanderait l'heure de fin de l'averse, absente du contexte.

## 0.31.1

864 tests verts. La hauteur de gazon monte enfin vraiment au fil de la journée.

- **Le frein de conditions ne saute plus à minuit.** Les journées révolues étaient recomptées
  au taux NOMINAL alors que la journée en cours était freinée par la chaleur : à 00 h 00, tout
  ce que la chaleur avait empêché était rendu d'un coup. Mesuré sur l'installation : **+0,30 cm
  par 30-35 °C, +0,40 cm au-delà de 35 °C**. Le frein — toute la raison d'être du modèle de
  pousse (0.29.0) — était donc annulé chaque nuit. Repéré par Kévin : « la hauteur ne bouge pas ».
- **La pousse réellement acquise est mémorisée**, jour par jour, dans la mémoire persistée du
  cerveau. La journée qui s'achève est créditée avec SON propre frein ; une journée entièrement
  manquée (intégration arrêtée > 24 h) retombe sur le taux nominal, faute de mieux.
- **Amorçage sans mémoire** (premier calcul, montée de version, nouvelle tonte) : repli sur
  l'estimation nominale des journées révolues, comme avant. Repartir de zéro aurait fait chuter
  la hauteur affichée d'un coup — 6,2 → 4,7 cm mesuré, un défaut pire que celui corrigé.
- **Nouvel attribut `gazon_pousse_jour_cm`** sur le capteur de hauteur. Par forte chaleur, la
  journée entière ne vaut que 0,10 cm, soit un seul cran d'arrondi au 0,1 cm : la pousse était
  réelle mais invisible. L'attribut la montre au centième.
- Aucune décision n'était affectée : `mowing_is_overdue` se calcule sur les jours écoulés depuis
  la dernière tonte, pas sur la hauteur estimée (vérifié). Le défaut ne faussait que l'affichage.

## 0.31.0

859 tests verts. Le seul manque avec une conséquence physique est comblé.

- **Nouveau service `stop_irrigation`** : arrête immédiatement le cycle en cours. Jusqu'ici,
  aucun des 13 services ne pouvait couper un arrosage — il ne restait que l'interrupteur
  physique ou le disjoncteur.
- **La vanne se referme** : acquis sans code nouveau, le `sleep` de chaque segment étant déjà
  enveloppé d'un `try/finally` appelant `_safe_turn_off_zone`, lui-même sous `asyncio.shield`.
- **La session est purgée**, contrairement à l'annulation d'un arrêt de Home Assistant. Le
  `finally` de l'exécuteur ne nettoie que `if not cancelled` — voulu, pour que la session
  survive et soit reprise au redémarrage. Un arrêt volontaire veut l'inverse : sans purge
  explicite, le cycle serait relancé au prochain démarrage.
- **L'eau déjà versée est enregistrée**, y compris la zone coupée en plein segment, créditée
  au prorata du temps réellement écoulé et bornée au segment planifié. Sans cela, le bilan du
  sol ne verrait pas cette eau et le système réarroserait — c'est la cause racine « le système
  ne voit pas ce qu'il vient d'arroser ».
- **Idempotent** : sans arrosage en cours, le service ne fait rien et le dit.
- Cause `arret_manuel` volontairement absente des listes techniques : cette eau compte au
  budget hebdomadaire et arme le cooldown, comme n'importe quelle autre.
- Traduit dans les cinq langues. 7 tests dédiés, dont la vérification qu'ils détectent bien
  quatre mutations de l'implémentation.
- **Bouton « Arrêter l'arrosage »** (`button.gazon_intelligent_arreter_arrosage`) : un arrêt
  qu'il faut aller chercher dans les Outils de développement n'est pas un arrêt d'urgence.
  Le bouton le met à portée sur n'importe quel tableau de bord, sans dépendre de la carte
  dont le catalogue de services est codé en dur.

## 0.30.2

852 tests verts. Un motif de blocage qui se contredisait lui-même.

- **Tonte** : le motif « trop chaud » affichait la température arrondie à l'entier. À 30,2 °C
  il donnait « Trop chaud pour tondre (30 °C, seuil 30 °C) » — un blocage parfaitement juste
  (30,2 > 30) qui se lit comme une erreur de comparaison. Vu en direct sur l'installation.
  Une décimale est désormais affichée, pour le trop-chaud comme pour le trop-froid.
- Aucun changement de comportement : seuls les libellés bougent.

## 0.30.1

851 tests verts. Correctif d'un garde-fou qui disparaissait avec son capteur.

- **Tonte** : le vent inconnu ne passe plus pour un air calme. `_resolve_mowing_window` lisait
  `float(context.vent or 0.0)` : capteur d'anémomètre indisponible → 0 km/h → la fenêtre
  remontait de « à éviter » à « idéal ». Elle consulte désormais le repli météo
  (`weather_wind_speed`), que `_resolve_mowing_block` utilisait **déjà** dans le même fichier —
  deux lectures du vent divergentes, celle qui pilote la fenêtre étant la plus aveugle.
- **Portée réelle** : jamais déclenché sur l'installation (le capteur Netatmo est tombé 9 fois
  en 4 jours, à chaque redémarrage, mais les entités météo ont tenu). Le défaut devenait
  toutefois actionnable depuis la 0.30.0, le flow Node-RED démarrant la tonte sur
  `mowing_window_state` ∈ {ideal, acceptable}.
- **Sans aucune source de vent** (ni capteur ni météo), le garde reste volontairement muet :
  une installation sans anémomètre doit pouvoir obtenir une fenêtre idéale.

## 0.30.0
La fenêtre de tonte du soir suit enfin le coucher du soleil — **850 tests verts**.
- **Le créneau du soir valait 17-19 h toute l'année (`decision_mowing.py`).** Demandé par Kévin : « il peut tondre plus tard, comme le soleil se couche plus tard ». Le défaut allait plus loin que ça : **en décembre, coucher à 16 h 55, la fenêtre 17-19 h tombait ENTIÈREMENT après la nuit** — seuls les autres garde-fous empêchaient une tonte dans le noir. Elle est désormais ancrée sur le coucher réel (`weather_profile["sunset_minute"]`, déjà calculé pour l'arrosage du soir) : elle se termine **90 min avant le coucher** — la même marge de ressuyage que l'arrosage, une herbe coupée puis laissée humide toute la nuit étant une porte ouverte aux maladies — et s'ouvre **3 h avant cette fin**.
- **Mesuré au fil de l'année** : 21 juin 17 h 28 – 20 h 28 · 30 juillet 17 h 00 – 20 h 00 (une heure de plus qu'avant) · 21 septembre 15 h 20 – 18 h 20 · 21 décembre 12 h 25 – 15 h 25. La fenêtre s'efface si elle descendrait sous le créneau idéal du matin, plutôt que de se chevaucher.
- **Repli conservateur** : sans coucher connu (`sun.sun` absent au démarrage), on garde les anciennes bornes fixes au lieu d'inventer une fenêtre. Choix délibéré — cf. la falaise de minuit, où un repli optimiste avait coûté 6,2 mm débités à 3 h du matin.
- Deux tests : 19 h devient tondable en juillet mais 21 h reste refusé (trop près du coucher), 18 h reste refusé en décembre, et le repli fixe est vérifié.

## 0.29.1
La projection de tonte annonçait le jour même où la tonte était bloquée — **848 tests verts**.
- **`temp_extreme` n'avait aucune branche de projection (`decision_mowing.py`).** Il tombait dans le repli, ancré sur l'instant courant, si bien que la carte affichait dans la MÊME phrase « Trop chaud pour tondre (30 °C, seuil 30 °C) » et « Prochaine tonte estimée le 30/07/2026 » — soit aujourd'hui, le jour où elle est justement refusée. Constaté sur l'install en relisant l'état après déploiement. Le code rejoint son voisin `stress_thermique`, qui projetait déjà au lendemain : quand c'est la température qui bloque, c'est le jour suivant qu'on retente, une fois redescendue. Vaut aussi pour le trop-froid, que ce même code couvre. **Mesuré sur 8 640 scénarios : 1 944 projections corrigées (22 %), exactement les cas chaud et froid ; aucun autre champ ne bouge.**
- Un test verrouille l'invariant dans les deux sens (38 °C et 4 °C) : la projection ne peut plus désigner un jour où la tonte est bloquée.

## 0.29.0
La hauteur du gazon monte enfin au fil de la journée, et s'arrête quand le gazon s'arrête — **847 tests verts**.
- **La pousse est répartie sur la journée au lieu de sauter à minuit (`decision_mowing.py`).** L'estimation valait `hauteur_de_coupe + jours × taux` : elle gagnait un cran d'un coup au changement de date, puis restait figée vingt-quatre heures. Elle progresse désormais sur la **fenêtre 7 h - 20 h** — le gazon ne s'allonge pas la nuit, la photosynthèse et l'élongation suivent la lumière. En fin de journée on retrouve exactement l'ancienne valeur : la courbe monte, elle ne se déplace pas.
- **La pousse tient compte des conditions réelles.** Demandé par Kévin : « à certain moment la hauteur peut ne pas bouger et c'est normal ». C'est agronomiquement exact, et le modèle l'ignorait : il ne regardait que la phase et le mois, donc il faisait pousser le gazon de 0,3 cm par jour **en pleine canicule sur un sol vide**. Deux freins multiplicatifs s'appliquent désormais à la journée en cours : la **température** (optimum 15-24 °C pour une graminée de saison fraîche, arrêt franc sous 5 et au-delà de 35, quasi-arrêt entre 30 et 35) et la **réserve du sol** (sous le seuil de déclenchement d'arrosage, la plante ferme ses stomates et privilégie la survie à l'élongation ; réserve nulle = pousse nulle). **Mesuré sur l'install** : gazon tondu à 5,5 cm le 27/07, relevé le 30/07 — à 22 °C il passe de 6,3 à 6,7 cm dans la journée, à 30 °C de 6,3 à 6,6, et **à 38 °C il reste à 6,3 toute la journée**.
- **Aucune pousse le jour même de la tonte.** L'heure de la coupe n'est pas connue : afficher « déjà 2 mm repoussés » quelques heures après être passé serait faux. Défaut trouvé par un test existant pendant la mise au point.
- Les jours révolus gardent le taux nominal — leurs conditions ne sont plus connues, les inventer serait pire que la moyenne mensuelle. Seule la journée en cours est modulée. Trois tests ajoutés : progression strictement croissante de 5 h à 23 h, plateau avant 7 h et après 20 h, et arrêt de la pousse à 38 °C.

## 0.28.1
Chaque redémarrage faisait chuter la réserve du sol — **845 tests verts**.
- **Un redémarrage de Home Assistant détruisait la mesure d'ET au profit de l'estimation (`soil_balance.py`).** Signalé par Kévin : « à chaque fois que je redémarre la réserve du sol descend ». Vérifié sur l'historique de l'install, et c'est exact. Tout redémarrage de Home Assistant rend le capteur d'ET horaire indisponible le temps du démarrage — c'est le redémarrage qui le prive de données, pas le capteur qui défaille ; le code le documentait déjà. Le repli faisait alors `max(prorata, cumul_mesuré)` : la mesure fine (chaîne FAO-56 horaire) était remplacée par l'estimation prorata, plus grossière et **systématiquement plus haute**. **Mesuré : −0,2 / −0,4 / −0,8 et jusqu'à −1,4 mm en un seul pas**, là où la dérive normale vaut 0,1 mm. Six redémarrages le 29/07 ont coûté 2 à 3 mm — **un quart de la réserve utile, effacé par de l'outillage et non par le gazon**.
- **Le correctif distingue le blip de la coupure.** Si le dernier cumul date de moins de 15 minutes (`_ACCUMULATION_FRESH_HOURS`), c'est un redémarrage ou un capteur qui cligne : on garde la mesure telle quelle, le temps réellement écoulé étant négligeable. Au-delà, du temps a vraiment été perdu et le prorata reprend la main — c'est la seule source qui connaisse la fraction de journée écoulée. Le seuil est volontairement bien plus court que celui des coupures (2 h) : il ne s'agit pas de tolérer une panne, seulement de ne pas jeter une mesure pour trois minutes d'absence.
- **Les deux propriétés d'origine sont conservées** : le débit ne recule jamais (l'eau évaporée ne revient pas) et une vraie coupure se resynchronise toujours, sans quoi l'erreur se figerait dans la réserve d'ouverture du lendemain. Deux tests encadrent les deux côtés : un redémarrage de 5 minutes ne débite rien de plus, une coupure de 6 heures est bien rattrapée.

## 0.28.0
L'arrosage reculait d'une heure par jour et allait sortir de la fenêtre du matin — **843 tests verts**.
- **Le garde « 24 h glissantes » devient « une fois par jour » (`guidance.py`).** Le compte à rebours partait de la **fin** du cycle. Comme le cycle dure environ une heure, l'heure autorisée reculait d'autant **chaque jour**. Constaté sur l'install : fin d'arrosage à 06:36 le 28/07, **07:36 le 29**, **08:40 le 30** — soit +1 h 02 par jour, exactement la durée du cycle. Projection : 09:42 le 31, puis **10:44 le 1er août**, c'est-à-dire **hors de la fenêtre du matin** qui ferme à 10:00. L'arrosage se serait bloqué un jour entier en pleine chaleur, serait reparti à l'aube le lendemain, et la dérive aurait recommencé — environ un jour sans arrosage par semaine.
- **La cause : une règle qui faisait deux métiers.** Empêcher un second arrosage dans la journée (voulu) ET fixer l'heure du suivant (effet secondaire dont personne n'avait décidé). Seul le premier est conservé : le garde s'arme si le dernier arrosage tombe le **même jour calendaire**, et se lève à minuit. La fenêtre du matin rouvrant à 04:00, l'arrosage revient à l'aube dès le lendemain — conforme à la règle de Kévin « toujours arroser à l'aube ».
- **Comparaison sur la date LOCALE, pas UTC.** En heure d'été, tout ce qui se produit entre minuit et 2 h porte la date de la veille en UTC : un arrosage matinal serait vu comme « hier » et le garde ne s'armerait pas, laissant passer un second cycle le jour même. C'est le même piège que la falaise de minuit, verrouillé par un test dédié.
- **Le libellé affiché suit la réalité, le code reste.** « Cooldown 24 h » devient « Déjà arrosé aujourd'hui ». Le code `cooldown_24h` est **inchangé** : c'est un contrat public consommé par la carte et les automatisations.
- **Portée mesurée, et ses limites dites.** L'empreinte de 8 640 scénarios ne montre **aucune** divergence — mais ses historiques ne contiennent pas d'arrosage du jour même, donc elle n'exerce pas ce chemin : c'est une limite de la grille, pas une preuve d'inocuité. Quatre tests ciblés couvrent le vrai comportement, dont la levée du garde à l'aube du lendemain (21 h 20 écoulées seulement — l'ancien garde bloquait encore) et sept jours consécutifs sans réapparition de la dérive.

## 0.27.0
La tondeuse se fie enfin à sa configuration — **839 tests verts**.
- **Les planchers/plafonds fixes de hauteur sont retirés (`decision_mowing.py`).** Ils valaient 4,0 et 6,5 cm, portaient un nom trompeur (`robot_min_height` / `robot_max_height`, comme s'il s'agissait de limites machine) et s'appliquaient **en plus** de la configuration : un réglage 3,0-6,0 devenait 4,0-6,0. Arbitrage de Kévin — « pour la tondeuse il devrait se fier au min max » : la config décrit la MACHINE de l'utilisateur, c'est elle qui borne. Le commentaire de `number.py` (« aucune valeur codée en dur, une tondeuse 0-100 mm fonctionne aussi ») redevient vrai de bout en bout.
- **Ce qui protège du scalp reste en place, et c'est mieux qu'un seuil figé : la règle du tiers.** `third_floor = hauteur_actuelle × 2/3` interdit d'ôter plus d'un tiers du limbe, et **suit l'herbe** au lieu de rester fixe — mesuré le 29/07/2026 : gazon à 5,9 cm → plancher dynamique à 3,93 cm, soit le même ordre que l'ancien 4,0, mais qui descend quand l'herbe est courte et monte quand elle est haute. Seul trou connu, documenté dans le code : si la hauteur du gazon est absente, il ne reste que la hauteur théorique (phase + saison) pour tenir le plancher.
- **Effet de bord non anticipé, et il va dans le bon sens.** **Mesuré sur 8 640 scénarios : 7 428 voient la consigne changer, toutes vers le HAUT** — 6,5 → 7,0 (3 049), 7,5 (2 214) ou 8,0 (2 165). L'ancien plafond de 6,5 cm bridait 86 % des cas juste sous la fourchette que la littérature recommande en été pour une graminée de saison fraîche (**7,5 à 10 cm**) : une herbe plus haute ombrage le sol, limite l'évaporation et enracine plus profond. Deux tests attendaient 6,5 — recalés à 8,0 et 7,5, avec la raison agronomique.
- **Sur une tondeuse plafonnée à 6 cm, rien ne bouge.** Vérifié sur la config réelle de Kévin (3,0-6,0) en cinq saisons, du plein été au gazon à 3 cm : la consigne vaut **6,0 cm partout**, avant comme après — la limite machine est toujours la contrainte qui mord. Seul le minimum publié passe de 4,0 à 3,0.
- **Le palier de 0,5 cm devient une garantie testée** (exigence de Kévin). Il l'était déjà en pratique — `_MOWER_STEP_CM = 0.5` dans le moteur, pas de 0,5 cm sur les deux réglages de hauteur, 5 mm sur le curseur de coupe — mais rien ne l'empêchait de dériver. Quatre tests le verrouillent désormais : le pas du moteur vaut bien 0,5 ; consigne et bornes tombent sur la grille pour sept hauteurs de gazon ; une config hors grille (2,3-7,8 cm) est ramenée dessus ; et la descente d'une tonte à l'autre ne saute **jamais plus d'un palier**. Le pas est volontairement unique et fixe : le faire dépendre de la tondeuse configurée laisserait une machine à pas fin produire des consignes hors grille.
- **Le libellé `hauteur_tonte_garde_fou_label` est réorienté.** Il annonçait un rognage de la config, qui n'existe plus. Il explique désormais la seule contrainte pouvant encore relever la consigne au-dessus de ce que la saison demanderait — la règle du tiers — en nommant la hauteur du gazon et ce que la saison seule aurait proposé. Vaut `None` quand c'est la saison qui pilote, cas courant.

## 0.26.1
Le libellé du garde-fou de hauteur n'atteignait pas le capteur que lit la carte — **834 tests verts**.
- **Quatrième liste blanche oubliée (`sensor.py`).** `hauteur_tonte_garde_fou_label`, ajouté en 0.25.0, avait été déclaré dans `decision_mowing`, `decision.py`, `coordinator` et `binary_sensor` — mais pas dans les deux listes de `sensor.py`. Il était donc absent de `sensor.gazon_intelligent_hauteur_de_tonte_conseillee`, précisément le capteur que la carte interroge. C'est le piège des listes blanches multiples, qui filtrent en silence : la clé existait, les tests passaient, et l'attribut n'arrivait nulle part où on pouvait le voir. Les quatre points d'assemblage la portent désormais.

## 0.26.0
Le niveau hydrique affichait « déficit » toute la saison, quoi qu'il arrive au gazon — **834 tests verts**.
- **Un veto par CUMUL écrasait le niveau hydrique (`sensor.py`).** Les quatre seuils (1 / 2 / 4 / 8) sont à l'échelle d'un déficit **journalier**, mais `deficit_3j` et `deficit_7j` sont des **cumuls** — 12 à 42 mm en pleine saison. Le veto était donc toujours armé. **Mesuré sur une grille ET0 2 à 7 mm/j : 2 niveaux sur 5 seulement étaient atteignables.** L'audit précédent annonçait « excédentaire et équilibré hors d'atteinte » : c'était optimiste, « léger déficit » l'était aussi. Un gazon au bilan +5 mm — soit gorgé d'eau — s'affichait « déficit ». L'attribut ne portait plus aucune information de toute la saison. Le niveau ne dérive désormais que du **bilan signé**, déjà recentré sur le seuil MAD par `_objective_display_balance` : les 5 niveaux redeviennent atteignables, et un gazon en forme s'affiche enfin « excédentaire ».
- **Deux correctifs partiels ont été mesurés puis écartés**, et la mesure est consignée dans le code pour qu'on ne les retente pas : normaliser les cumuls en taux journalier **seul** régresse le correctif 0.16.0 (« fort déficit » retombe sur « déficit », exactement ce que le commentaire d'audit annonçait — il avait raison) ; normaliser **et** aligner la dernière branche sur `and` au lieu de `or` donne 4 niveaux sur 5, mais le cas qui motivait le correctif affichait toujours « déficit ». Cause structurelle identifiée au passage : la dernière branche testait `bilan ≥ −2 **ou** stress ≤ 8` là où les trois autres utilisent `et` — ce `ou` ramenait n'importe quel bilan à « déficit ».
- **Un test verrouillait le défaut sans le savoir.** `test_objectif_sensor_shows_daily_balance_and_soil_reserve_separately` attendait « déficit » avec une réserve de 15,6 mm : cette valeur ne venait pas du bilan mais du veto (`deficit_7j = 8.0`, pile à la borne `stress <= 8.0`). Recalé sur « excédentaire », avec la raison écrite. Cinq tests d'atteignabilité ajoutés, dont un qui rejoue la grille ET0 complète.
- **La contradiction du curseur de hauteur est levée (`number.py`).** Le commentaire annonçait « aucune valeur codée en dur, donc une tondeuse 0-100 mm fonctionne aussi » — vrai pour ce curseur, trompeur pour le reste : la hauteur *conseillée* passe par les garde-fous agronomiques (plancher 4,0 cm, plafond 6,5 cm). Le commentaire le dit désormais et renvoie au resserrage rendu visible en 0.25.0.

## 0.25.0
Les trois arbitrages de tonte tranchés, sources agronomiques à l'appui — **829 tests verts**.
- **Les bornes de hauteur publiées annonçaient la config, pas la réalité (`decision_mowing.py`, `decision.py`, `binary_sensor.py`, `coordinator.py`).** Un plancher de 4,0 cm et un plafond de 6,5 cm s'appliquent **en plus** de la configuration et peuvent la rogner — mais `hauteur_tonte_min_cm` publiait quand même la valeur configurée. Sur l'install de Kévin, l'attribut annonçait un minimum de **3,0 cm** alors que le système ne descend jamais sous 4,0 ; avec une config 3-8 cm, il annonçait un maximum de 8,0 cm alors que la recommandation plafonnait déjà à 6,5. Les bornes exposées sont désormais celles **réellement appliquées**, un nouvel attribut `hauteur_tonte_garde_fou_label` dit en clair lequel des deux garde-fous a resserré la config, et les valeurs configurées restent consultables sous des clés privées. **Le garde-fou n'est PAS retiré** : le supprimer ferait descendre la hauteur conseillée jusqu'à 3 cm hors saison chaude, ce qui expose au scalp et au dessèchement — c'est un choix agronomique, pas un correctif. **Mesuré sur 8 640 scénarios : exactement trois champs touchés, tous des champs de compte-rendu ; `hauteur_tonte_recommandee_cm` est inchangée.** Le test qui existait verrouillait précisément l'ancien mensonge (il attendait un maximum de 8,0 avec une recommandation à 6,5) — recalé sur le contrat honnête, et cinq tests ajoutés.
- **Le seuil de tonte reste à 30 °C — vérifié contre la littérature, pas conservé par défaut.** Les graminées de saison fraîche entrent en stress dès que l'air dépasse durablement ~29 °C (85 °F), leur optimum se situant entre 15 et 24 °C. Relever le blocage à 32 °C ferait tondre un gazon déjà en souffrance, la coupe étant une blessure qui cicatrise mal par forte chaleur. La graduation existante est cohérente : déconseillé entre 25 et 30 °C, bloqué au-delà, plus un garde distinct « stress thermique » qui exige température ≥ 30 °C **et** ET0 ≥ 4.
- **Hauteur maximale de 6 cm : limite de la machine, rien à corriger dans le code.** La littérature conseille 7,5 à 10 cm en été pour une graminée de saison fraîche — une herbe plus haute ombrage le sol, limite l'évaporation et enracine plus profond. La tondeuse plafonne à 6 cm, et le système demande déjà ce maximum : le plafond agronomique de 6,5 cm est donc **inerte** sur cette install. Constat conservé dans la référence d'architecture comme information matérielle, pas comme dette de code.

## 0.24.0
Un même arrosage daté à 6 h d'écart selon qui le regardait — **824 tests verts**.
- **Arrosage et tonte dataient le MÊME événement différemment (`water.py`, `guidance.py`, `decision_mowing.py`).** Sur un arrosage déclaré à la main avec la date seule, la tonte le plaçait à 06:00 et l'arrosage à 00:00 : le cooldown 24 h expirait donc **six heures avant** que la tonte n'estime le gazon ressuyé. Pire, le côté tonte lisait `declared_at` **avant** la date déclarée — une déclaration rétroactive (« j'ai arrosé avant-hier ») était donc datée du jour de la saisie : mesuré à **93 h d'erreur** sur un arrosage vieux de trois jours. Les deux sous-systèmes passent désormais par un résolveur unique, `water.resolve_history_moment` : horodatage machine exact s'il existe, sinon l'heure réelle de la déclaration **si elle tombe le jour déclaré**, sinon 06:00. Arbitrage de Kévin — « le déclarer à l'heure où l'arrosage a été déclaré » —, l'information étant déjà enregistrée mais lue d'un seul côté. Repli à 06:00 et non minuit : la règle est d'arroser à l'aube, donc c'est à la fois plus proche du réel et plus prudent sur le cooldown. **Mesuré sur 8 640 scénarios : un seul champ touché (`raison_decision`), un seul historique sur cinq, écart de 6,0 h constant, aucune décision modifiée.** Sept tests verrouillent le contrat entre les deux sous-systèmes.
- **Le garde-fou `auto_irrigation_user_confirmed` est supprimé (`coordinator.py`).** Lu pour refuser l'arrosage automatique, mais jamais écrit ni stocké : il ne s'est jamais déclenché. L'interrupteur « arrosage automatique », lui bien câblé et vérifié en amont, joue déjà ce rôle. Les deux tests qui le « couvraient » fournissaient la clé à la main — ce que la production ne fait jamais — et validaient donc une branche morte ; ils sont remplacés par deux tests de non-régression qui échouent si la garde inerte réapparaît.
- **`decision.py` n'est pas une façade : son entête mentait (corrigé).** Un audit l'a soupçonné supprimable — il annonçait « garde l'API historique mais délègue la logique métier ». En réalité son tiers haut délègue, mais ses deux tiers bas sont **l'unique point d'assemblage** des ~210 clés du snapshot que lisent toutes les entités, dont `next_action_display` et `raison_blocage_tonte`, qui n'ont aucun autre producteur. Il est chargé à chaque cycle via `gazon_brain`. L'entête décrit désormais les deux moitiés, signale que `compute_subphase` ne se comporte PAS comme son homonyme de `phases.py`, et nomme les vraies façades legacy restantes.
- **Deux clés mortes retirées du snapshot** (`decision.py`, `binary_sensor.py`). `objectif_mm_executable` recopiait `objectif_mm` sans aucun consommateur dans le dépôt ni exposition sur les 74 entités gazon (vérifié sur l'install). `irrigation_need_mm` n'a **jamais eu de producteur** : elle valait toujours `None`, disparaissait du snapshot, et `besoin_hydrique_mm` retombait en silence sur `objectif_mm` — ce repli est désormais écrit franchement, valeur exposée strictement inchangée.

### Correction d'une analyse erronée
Un arbitrage a été soumis à Kévin sur une prémisse fausse : la clé `application_block_reason`, lue mais produite nulle part, avait été présentée comme « un nom qui a dérivé de `block_reason` », avec la conclusion que huit gardes du moteur de recommandation étaient inertes. **Les deux affirmations étaient fausses.** `block_reason` porte le motif de blocage de l'**arrosage** (`cooldown_24h`, `sol_deja_humide`…), pas celui d'une application produit : rebranché, le moteur aurait refusé toute recommandation dès que l'arrosage est en cooldown — l'état le plus courant — en affichant un code interne comme motif. Et les gardes ne sont pas inertes : les quatre conditions réelles (`application_block_active`, arrosage post-application en attente, délai en cours, statut bloqué) se déclenchent chacune avec sa phrase en clair — vérifié. Le rebranchement a été annulé, le piège documenté aux deux sites, et deux tests ajoutés pour qu'il ne soit pas retenté.

## 0.23.0
Arbitrages tranchés avec Kévin, sources agronomiques à l'appui — **815 tests verts**.
- **L'arrosage d'incorporation post-produit CRÉDITE désormais la réserve du sol** (`water.py`, `gazon_brain.py`). Ses 5 à 10 mm ont pour BUT de faire pénétrer le produit dans le sol : cette eau atteint la zone racinaire. Ne pas la compter sous-estimait la réserve d'autant et provoquait une recharge inutile le lendemain matin, en silence. Le motif historique — « les arrosages techniques ne rechargent pas » — reste vrai pour les 3 mm de rafraîchissement du soir, qui s'évaporent par fonction, mais ne l'était pas pour une incorporation. Les deux notions sont désormais séparées : l'incorporation entre dans le crédit de réserve, reste hors du garde-fou hebdomadaire (un produit ne grignote pas le budget d'arrosage du gazon), et le rafraîchissement reste exclu des deux.
- **Le facteur du plafond hebdomadaire est renommé et redocumenté, valeur inchangée.** Il s'appelait « marge de rattrapage » et le commentaire d'audit le disait annulé en pratique ; les deux étaient faux. Le plafond se calcule avec le Kc typique (0,80) alors que le Kc réel vaut 0,92 dès qu'une tonte de moins de 8 jours est enregistrée — et 0,80 × 1,15 = 0,92. Ce facteur **aligne** donc le plafond sur la demande réelle. Le retirer l'aurait serré SOUS le besoin du gazon (33,6 mm/sem au lieu de 38,6 à ET0 = 6) : vérifié, trois tests l'ont confirmé avant livraison.
- **L'exception « déficit critique » de l'arrosage du soir n'est PAS morte** — un audit l'avait crue telle. Sa condition se lit « le gazon n'a rien reçu de toute la semaine », pas « rien reçu aujourd'hui » : c'est un filet pour l'absence prolongée, l'arrosage coupé ou un blocage d'une semaine. Vérifié atteignable (déficit −5 mm, aucun arrosage depuis 7 jours, 26 °C), et verrouillé par cinq tests pour qu'un futur audit ne la déclare plus morte.
- **Fraction d'épuisement FAO-56 ajoutée mais NON branchée** (`water.py`), avec le constat qui explique pourquoi. `p = p_table + 0,04 × (5 − ETc)` ajuste le seuil à la demande du jour. Mais la FAO mesure la déplétion depuis la CAPACITÉ AU CHAMP, là où ce modèle la mesure depuis la réserve utile : tout stock au-dessus de 12 mm compte comme déplétion nulle (vérifié pour 24, 18, 15 et 12). Les deux grandeurs ne désignent pas la même chose. La brancher proprement suppose de changer aussi la cible de recharge — donc la dose, qui passerait de ~6 à ~9-12 mm — ce qui demande de savoir si le sol restitue réellement ses 24 mm aux racines.

### Correction d'une analyse erronée
Il avait été affirmé que le modèle était « plus prudent que la FAO ». **C'est l'inverse** : le sol travaille entre 6 et 12 mm sur un stock de 24, soit 25 à 50 % de la capacité, là où la FAO déclencherait à un stock de 15 mm. Le modèle laisse donc le sol devenir plus sec que la référence ne le recommande. Ce qui reste vrai : le rythme est plus fragmenté que le régime manuel éprouvé, et le volume hebdomadaire est bon.

## 0.22.3
Des heures UTC servaient d'heures murales — **806 tests verts**.
- **La projection de tonte annonçait le mauvais jour entre 18 h et 20 h (`decision_mowing.py`)**. « Pas de tonte après 18 h, report à 6 h le lendemain » sont des heures de la vie courante, mais elles étaient testées et écrites sur un instant **UTC** : en Europe/Paris l'été, le seuil se déclenchait en réalité à **20 h locales** et le « 6 h » écrit valait **8 h locales**. Toute projection tombant dans cette bande de deux heures désignait le jour d'avant sur la carte. La projection bascule désormais en heure murale avant tout test de borne — d'autant que la date renvoyée est comparée à la date du jour, qui est locale.
- **Deux comparaisons de dates mélangeaient les fuseaux (`coordinator.py`)** : `_parse_datetime_value` normalise tout en UTC, et son `.date()` était confronté à une date **locale**. En Europe/Paris l'été, tout ce qui se produit entre minuit et 2 h locales porte la date de la **veille** en UTC — un arrosage manuel à 00 h 20 était donc vu comme « hier », le motif `recent_watering` ne se posait pas, et l'arrosage automatique pouvait passer par-dessus le matin même.
- **Le stub `dt_util` des tests ne fournissait pas `as_local`** : le code de production qui convertit en heure murale retombait silencieusement sur son repli, et aucun test ne pouvait distinguer « converti » de « pas converti ». C'est précisément ce qui avait laissé passer la projection calée sur UTC. Stub complété, trois tests ajoutés dont la bande 18 h-20 h et un passage de minuit.

## 0.22.2
Suite des audits croisés — **803 tests verts**.
- **Un déficit ajusté légitimement NUL n'est plus écrasé par le déficit brut** (`memory.py`, `decision_watering.py`). `deficit_mm_ajuste = max(0, brut − pluie_support − …)` : zéro y est une valeur normale, pas une absence — c'est « il va pleuvoir demain, plus rien à combler ». La chaîne `or` le traitait comme absent et publiait le brut à sa place : l'attribut public annonçait 0,9 mm de déficit là où le moteur avait conclu à 0, et le message d'apprentissage disait « il reste 4,6 mm » après une décision de ne rien arroser. **Mesuré sur 8 640 scénarios : 192 corrigés, tous sur ce seul champ, aucune décision modifiée.** C'est le piège du `or` sur une valeur où zéro est significatif, déjà rencontré sur les débits de zone.
- **Incohérence d'unité SIGNALÉE et non corrigée** (`guidance.py`, arbitrage) : l'exception « déficit hydrique critique » de l'arrosage du soir compare `arrosage_recent` — un cumul **sept jours** — à un seuil de 0,25 mm qui n'a de sens que sur une valeur du jour. En saison, dès qu'un arrosage a eu lieu dans la semaine (donc en permanence), l'exception est morte et `watering_evening_allowed` est publié à False pour une raison fausse. Le biais est conservateur : capacité perdue, pas risque agronomique. La corriger autoriserait des arrosages du soir absents depuis des mois — choix d'arrosage, pas correctif technique.

## 0.22.1
Trois audits croisés en lecture seule ont sorti **quatre défauts silencieux** — **803 tests verts**.
- **Le fractionnement était lu avec un cycle de retard, et disparaissait au moment de déclencher (`coordinator.py`)**. L'ordonnanceur tourne À L'INTÉRIEUR de `_async_update_data`, donc avant que Home Assistant n'affecte le nouveau `self.data` : pendant tout le lancement, le plan lisait le cycle **précédent**, alors que la dose venait du snapshot frais. Le biais allait systématiquement dans le mauvais sens — le fractionnement n'existe qu'au-delà de 10 mm, et c'est précisément la transition « dose nulle → grosse dose » (expiration du cooldown 24 h dans la fenêtre du matin, cas **quotidien**) qui le perdait. Mesuré : 11,2 mm délivrés en un seul passage sans pause au lieu de 2 passages + 25 min. Le plan lit désormais le snapshot en priorité, `self.data` en repli. Deux tests, dont la reproduction exacte du scénario, avec échec vérifié sur l'ancien code.
- **Les refus d'arroser du MATIN n'étaient jamais tracés (`coordinator.py`)** : le filtre testait la valeur `"matin"`, qui **n'existe pas** — les fenêtres réelles sont `ce_matin` / `demain_matin` / `maintenant`. Seuls les refus du soir étaient enregistrés, et le diagnostic « derniers refus » laissait donc croire qu'aucun refus matinal n'avait eu lieu, sur la fenêtre la plus décisive. Trouvé indépendamment par **deux auditeurs sur deux chemins différents**.
- **Température absente = gel fictif à 0 °C (`decision_mowing.py`)** : la tonte était refusée en plein juillet avec le motif mensonger « Température trop basse pour tondre. », sans rien dans les journaux. Le correctif existait **déjà dans la fonction sœur**, commentaire à l'appui — il n'avait jamais été reporté. Trois comparaisons voisines, qui auraient levé une exception sur une mesure absente, ont été protégées au passage.
- **Humidité absente = 0 % HR (`guidance.py`)**, soit le palier le plus pénalisant : le score de stress thermique montait d'un cran et **armait les exemptions d'urgence** (dépassement du garde-fou hebdo et du cooldown 24 h). `_heat_stress_level` gardait pourtant explicitement le cas absent — mais les deux appelants forçaient la valeur à 0 en amont. Les **deux** points d'appel corrigés (la première tentative, sur un seul, était sans effet — constaté par mesure, pas supposé).

### Nettoyage issu des mêmes audits
- Recopie clé par clé remplacée par `update` dans `config_flow.py` — **la correction automatique proposée par l'outil aurait effacé la configuration existante** lors d'une reconfiguration.
- Deux branches mortes fusionnées dans la projection de tonte, une branche ternaire inatteignable retirée, deux gardes structurellement toujours vraies supprimées, une concaténation de tuples fragile passée en unpacking, deux imports `typing` dépréciés déplacés.
- **Trois chemins inertes SIGNALÉS et non modifiés** (arbitrage) : un garde-fou d'arrosage jamais écrit ni stocké, une clé fantôme rendant huit gardes toujours satisfaites, et trois paliers météo de la fenêtre de semis qui plafonnent à leur propre valeur par défaut.

## 0.22.0
**La totalité de l'intégration est désormais typée-vérifiée par la CI** : 39 fichiers sur 39, 29 800 lignes — **801 tests verts**.
- **`sensor.py` entre à son tour dans le périmètre** (24 erreurs restantes ramenées à zéro), et avec lui le dernier module. Il n'existe plus une seule ligne de l'intégration qu'une régression de typage pourrait traverser sans faire rougir la CI. Rappel de l'enjeu : c'est l'absence de ce contrôle qui avait laissé passer un `None + float` arrêtant le bilan sol **en silence**.
- **82 annotations `dict[str, object]` normalisées en `dict[str, Any]`** dans `sensor.py` et `entity_base.py`. Ces dictionnaires portent des instantanés hétérogènes — un état, un motif, une date, un flottant. `object` obligeait chaque lecture à être re-typée par l'appelant ; `Any` décrit honnêtement leur contenu, et c'est déjà la convention des 37 autres modules.
- **Cinq signatures alignées sur leur contrat réel** : `_hydric_state_from_depletion_ratio`, `_hydric_state_from_reserve_ratio`, `_score_level_and_tone`, `_datetime_from_date_and_minute` déclaraient `object` alors que leur corps convertit défensivement dans un `try/except` — elles acceptent par conception ce qui sort d'un instantané.
- **Une lecture dupliquée corrigée** : `session.get("last_activity_at")` était appelée **deux fois** sur la même ligne, le test `isinstance` portant donc sur une lecture différente de celle qu'on déréférençait. Sans conséquence observée (le dictionnaire ne change pas entre les deux appels), mais c'était fragile par construction.

### Vérification
Triple : les 801 tests, le vérificateur de types sur les 39 fichiers, et une **empreinte comportementale de 8 640 scénarios** recomparée en tenant compte des types — **zéro divergence, pas même de représentation**. Complétée par un test de fumée instanciant 35 capteurs et lisant leur état et leurs attributs.

## 0.21.10
Le cœur décisionnel entre dans le périmètre vérifié : **26 % → 69 % du code** — **801 tests verts**.
- **`mypy.ini` couvre désormais 37 fichiers sur 39** (20 621 lignes sur 29 778). Y entrent `guidance` et `intervention_recommendation`, c'est-à-dire le moteur d'arrosage et le moteur de recommandation, plus `coordinator` — les trois modules où une erreur coûte le plus cher. Seul `sensor.py` reste dehors (24 erreurs, contre 41 au départ).
- **Deux annotations qui MENTAIENT, corrigées (`guidance.py`)** : `_confidence` déclarait rendre un score flottant alors que `_confidence_assessment` le borne par `int(...)` — d'où six appels signalés à tort. Et `_morning_window_bounds` déclarait des minutes entières tout en renvoyant `225.0`, un flottant, parce que l'heure d'ouverture vaut 3,75 (03h45). La conversion à la source rend honnêtes sept signatures aval d'un coup ; **prouvé sans effet par comparaison d'empreinte sur 8 640 scénarios**, et l'affichage est identique au caractère près (`03:45–08:00`).
- **Deux noms réutilisés pour deux types dans la même fonction** (`weather_sources`, `intervention_recommendation`) : `forecast` y désignait tour à tour une valeur filtrée non nulle et une valeur optionnelle, `temperature_reason` une chaîne toujours définie puis une note optionnelle. Renommés — c'est une gêne à la lecture avant d'être un problème de typage.
- **Deux annotations de dictionnaire ont effacé 28 signalements à elles seules** : `recorded_watering` dans `coordinator` (15) et les snapshots `dict[str, object]` → `dict[str, Any]` dans `sensor`/`entity_base` (13). Ces dictionnaires sont hétérogènes par nature ; `object` obligeait chaque lecture à être re-typée par l'appelant.
- **Gardes rendues visibles plutôt que devinées** : bornes de température relues dans leurs branches, tâches d'arrosage relues dans des locales au lieu de `getattr(...) and self._attr.done()`, `return` nu devenu `return None`. Aucun comportement modifié — seulement des protections qui se voient.

### Méthode
Une **empreinte comportementale** de 8 640 scénarios (3 sols × 8 températures × 6 ET0 × 4 humidités × 3 pluies × 5 historiques) a été figée avant les corrections et recomparée après chaque module, en tenant compte des **types** et pas seulement des valeurs. Résultat final : **zéro divergence**, pas même de représentation.

## 0.21.9
L'angle mort de la CI réduit de moitié : **26 % → 54 % du code typé-vérifié** — **801 tests verts**.
- **Périmètre `mypy.ini` porté de 23 à 35 fichiers sur 39** (7 777 → 16 165 lignes). Ce n'est pas cosmétique : c'est l'absence de ce contrôle qui avait laissé passer un `None + float` dans `soil_balance.py`, lequel arrêtait le bilan sol **en silence** (corrigé en 0.21.2). Restent hors périmètre, par coût croissant : `guidance` (7 erreurs), `intervention_recommendation` (9), `coordinator` (24), `sensor` (41).
- **Douze modules nettoyés pour y entrer, sans le moindre changement de comportement.** Les erreurs étaient de trois natures : des gardes que le vérificateur ne sait pas affiner (`(x or 0) > 0`, booléen intermédiaire portant le `is not None`), des replis `try/except` volontaires pour tourner hors Home Assistant, et l'invariance de `dict` là où `Mapping` — covariant en lecture — convient.
- **Deux vraies maladresses corrigées au passage** : `gazon_brain.dump_state` appelait `_coerce_date` **deux fois** par sérialisation pour un seul résultat ; `weather_sources` réutilisait le nom `forecast` pour deux types différents dans la même fonction (`Mapping` filtré dans la première boucle, `Mapping | None` dans la seconde) — source de confusion à la lecture.
- **Trois champs du contrat public rendus honnêtes (`decision.py`)** : `watering_strategy`, `objective_scope` et `watering_stage` sont déclarés `str` sur `DecisionResult` mais recevaient un `.get()` nu, donc potentiellement `None`. Défaut vide désormais — les consommateurs traitaient déjà la chaîne vide comme « non renseigné », le contrat cesse simplement de se contredire.

## 0.21.8
La pause de 25 min est réservée aux grosses doses — **801 tests verts**.
- **Seuil de fractionnement en phase Normal porté de 6 à 10 mm (`guidance.py`)**, sur une base agronomique explicite : le régime manuel éprouvé appliquait **8,8 à 10,0 mm en un seul passage** (35-40 min par zone à 14/14/17 mm/h), 3 fois par semaine, gazon en pleine forme et sans ruissellement observé. Le seuil à 6 mm était donc plus prudent que la pratique démontrée : il coupait en deux des doses qui passent sans problème, doublant la durée de séance pour rien et repoussant la fin hors du créneau frais.
- **La pause dépend désormais de la DOSE, plus seulement du nombre de passages.** Elle existe pour laisser le premier passage s'infiltrer avant le second — un enjeu de ruissellement, qui ne se pose pas sur un petit volume. Or le fractionnement peut être imposé pour d'autres raisons (session maximale dépassée, budget hebdo saturé après deux arrosages récents) : 25 minutes d'attente s'appliquaient alors à des doses modestes. Sous `PAUSE_LONGUE_MIN_DOSE_MM`, les passages s'enchaînent sans attente.
- **Les trois valeurs sont nommées et verrouillées par un test** (`FRACTIONNEMENT_NORMAL_SEUIL_MM`, `PAUSE_LONGUE_MIN_DOSE_MM`, `PAUSE_ENTRE_PASSAGES_MIN`) : ce sont des choix agronomiques, les changer sans raison documentée doit faire rougir un test, pas passer inaperçu. Quatre tests au total, dont un invariant multi-profils (« une pause implique toujours une grosse dose ») et le cas concret des 9,5 mm — celui que l'ancienne règle coupait en deux. L'échec des deux sur l'ancien seuil a été vérifié.

## 0.21.7
Vérification mécanique des quatre chemins « qui cassent en silence » — **797 tests verts**.
- **Deux marqueurs de relevé aberrant vivaient 2 minutes (`soil_balance.py`)** : `pluie_suspect` et `arrosage_suspect` signalent une journée dont la pluie (> 100 mm) ou l'arrosage (> 50 mm) relevé est écrêté. Ils étaient écrits dans l'entrée du ledger mais absents de la liste blanche de `_normalize_ledger_entry` — or celle-ci tourne au début de **CHAQUE** cycle, pas seulement au rechargement. Le marqueur disparaissait donc au passage suivant, ~2 minutes plus tard : impossible à retrouver quand on en avait besoin. Le test existant ne pouvait pas le voir, il ne vérifiait que l'état frais ; les deux nouveaux tests contrôlent la survie à la normalisation.
- **Deux replis morts supprimés (`sensor.py`)** : `watering_target_display` n'est produite **nulle part** dans les 39 modules, ces branches ne se déclenchaient jamais. Retirées — ce genre de code fantôme a déjà égaré un audit sur ce projet.
- **Les quatre pièges silencieux vérifiés mécaniquement, pas sur parole** : les 67 clés lues dynamiquement par `_decision_value` sont toutes résolvables (une seule exception, corrigée ci-dessus) ; aucune clé du profil d'arrosage n'est perdue dans la recopie clé par clé vers `water_bundle` (les 5 candidates sont internes à la chaîne guidance → politique) ; `PUBLIC_ENTITY_KEYS` couvre toutes les identités utilisées ; les jumeaux `SOIL_RESERVE_BASE_MM` / `_SOIL_RESERVE_UTILE_MM` et les deux `_round_half_up_1` sont identiques (vérifié sur 8 valeurs pièges). Aucune table numérique n'est dupliquée entre modules.
- **Constat documenté** : le seuil de fractionnement **dépend de la phase** — 4 mm en Traitement et phases agro, 6 mm en Normal, 12 mm dans le profil générique de repli. Ce dernier est nettement plus laxiste que les autres et mérite un arbitrage. La pause reste de 25 min partout.

## 0.21.6
Passe sur les angles jamais contrôlés : couverture des tests, traductions, cohérence des services — **795 tests verts**.
- **Deux attributs publics se contredisaient le jour d'un arrosage (`decision_watering.py`)** : `block_reason_label` annonçait « Cooldown 24 h » pendant que `date_prochain_arrosage_estime` affichait **le jour même** (constaté le 29/07/2026 à 13 h, réserve 10,9 mm après l'arrosage de 06:36). `estimate_days_until_watering` ne raisonne que sur la réserve — elle répond « quand le sol aura-t-il soif », pas « quand aurai-je le droit » — et son `0` signifie « la projection d'aube franchit le seuil ». Or l'aube du jour est passée : le prochain déclenchement possible est celui de **demain**. Plancher à 1 jour dès qu'un arrosage a déjà eu lieu aujourd'hui, appliqué au compteur ET à la date pour qu'ils ne divergent pas.
- **Le capteur « Prochain arrosage » n'avait AUCUN test** — 120 lignes, alors que c'est l'entité en tête de la carte. Neuf tests couvrent désormais ses états publics (bloqué, non requis, maintenant, aujourd'hui), la priorité de la date cible sur le statut, les résumés dédiés (pluie prévue, ressuyage), et surtout deux règles de cohérence : le motif de blocage accompagne toujours l'état « Bloqué », et aucune date de cible n'est exposée pendant un blocage. `sensor.py` passe de 79 à 81 % de couverture.
- **Couverture mesurée pour la première fois : 82 %** (2 378 lignes non couvertes sur 13 287). Les points bas : `number.py` 68 %, `switch.py` 76 %, `shared_state.py` 77 %.
- **Contrôles de cohérence, tous verts** : parité parfaite des 210 clés de traduction entre `strings.json` et les 5 langues ; les 13 services concordent sur quatre dimensions (constantes, enregistrement, `_ALL_SERVICES`, `services.yaml`, handlers) et chacun accepte exactement les champs qu'il documente.

## 0.21.5
Le recalage de la réserve ne condamne plus la journée entière — **784 tests verts**.
- **Nouvelle option `figer_la_journee` sur `recalibrate_reserve`** (défaut : vrai, comportement historique inchangé). Le service n'avait qu'un seul comportement pour deux besoins opposés. Le gel est indispensable à l'usage prévu — « j'ai sondé mon sol ce soir, il est à 8 mm » : sans lui, le recalcul du cycle suivant (`ouverture + pluie + arrosage − ET`) écraserait la mesure deux minutes plus tard. Mais il est inadapté à l'autre besoin, corriger une comptabilité faussée en cours de journée : il arrête alors TOUT le calcul du jour — évapotranspiration non débitée, pluie et arrosage non crédités, jauge immobile jusqu'à minuit. Constaté le 29/07/2026 après la correction de la falaise de minuit : la réserve restait figée à 7,5 mm et l'arrosage d'aube n'apparaissait nulle part.
- **Sans gel, c'est la réserve d'OUVERTURE qui est réécrite**, pas la réserve courante — seule valeur que le recalcul relit. Elle est choisie telle que le recalcul retombe sur la valeur demandée compte tenu de ce qui s'est déjà passé aujourd'hui (`ouverture = valeur + ET écoulée − pluie − arrosage`). Ce qui a déjà coulé est donc **préservé** au lieu d'être effacé comme le fait l'ancre : demander 7,5 mm alors que 3 mm se sont déjà évaporés fixe l'ouverture à 10,5 et la réserve courante à 7,5. Cinq tests, dont le miroir « avec gel, la même ET ne bouge rien ».
- **Le stub voluptuous des tests acceptait `vol.Optional(...)` mais pas `default=`** : tout `async_setup` échouait dès qu'un schéma de service déclarait une valeur par défaut. Corrigé. Et le validateur booléen des schémas passe par un repli explicite, `cv` étant `None` hors Home Assistant.

## 0.21.4
La falaise de minuit revenue par une autre porte : **6,2 mm d'ETc débités à 3 h du matin** — **779 tests verts**.
- **La fraction d'ET écoulée ne retombe plus sur « journée finie » quand le soleil est inconnu (`coordinator.py`)** : `sun.sun` peut manquer du state machine pendant le démarrage de Home Assistant ; le contexte solaire revient vide, lever et coucher sont `None`, et l'ancien repli valait **1.0 — soit « toute la journée est écoulée »**. Le 29/07/2026 à 03:11, un redémarrage a ainsi débité l'**ETc pleine journée d'un seul coup**, faisant tomber la réserve de 8,0 à 1,8 mm alors que rien n'avait évaporé depuis minuit. Aggravant : l'accumulation horaire ne recule jamais (l'eau évaporée ne revient pas), donc l'erreur se fige pour toute la journée — et la dose de l'arrosage d'aube aurait été calculée sur une déplétion de 10,2 mm au lieu de ~4. Repli désormais sur une journée civile approximative (06:00-21:00) : grossière, mais elle n'a qu'à tenir le temps que `sun.sun` apparaisse, et toute valeur horaire vaut mieux qu'un « journée finie » à 3 h du matin.
- **Le commentaire qui a permis le défaut est corrigé** : la fonction se disait « affichage uniquement de la réserve, repli sans risque ». C'était faux — elle amorce `etp_prorata` dans le bilan sol, donc la réserve, donc la dose. Un repli qualifié « sans risque » a coûté 6,2 mm d'eau fantôme.
- **Six tests là où il n'y en avait aucun** : nuit avec soleil inconnu (le défaut), milieu de journée en repli civil, fin de journée, et les trois cas soleil connu. L'échec des deux tests du repli sur l'ancien code a été vérifié.

## 0.21.3
Une course au démarrage pouvait armer l'arrosage de détresse sur une tondeuse en parfait état — **773 tests verts**.
- **L'arrosage de détresse exige désormais un blocage tondeuse d'au moins 30 minutes (`coordinator.py`)** : le code de motif dit « ce genre de blocage ne se résout pas seul », **pas** « celui-ci dure depuis longtemps ». Au redémarrage de Home Assistant, l'intégration démarre AVANT celle de la tondeuse et lit son entité comme absente pendant quelques secondes — soit `configured_missing`, un motif classé persistant. Constaté le 29/07/2026 à 03:11:34 : l'exception s'est armée alors que le robot était **à la station, batterie à 100 %**. Or elle contourne à la fois le blocage tondeuse **et la fenêtre horaire** — un simple redémarrage nocturne avec un déficit critique pouvait donc déclencher un arrosage à 3 h du matin, à rebours de la règle « toujours arroser à l'aube ». Un robot réellement coincé dehors le reste des heures ; une course au démarrage dure des secondes. Le compteur d'ancienneté est volontairement **non persisté** : après un redémarrage il repart de zéro, ce qui referme la course — ne pas l'ajouter au stockage.
- **Le mécanisme est enfin testé** : ajouté en 0.20.0, l'arrosage de détresse n'avait **aucun test** malgré sa capacité à arroser hors fenêtre horaire. Cinq tests couvrent désormais le blocage tout juste apparu, le blocage persistant qui doit bien déclencher, le changement de motif qui remet le compteur à zéro, la purge du compteur au retour du robot, et le motif transitoire (« tonte en cours ») qui ne doit jamais être contourné, même après des heures. L'échec des deux tests du garde sur l'ancien code a été vérifié.
- **Le moteur de recommandation ne tombe plus sur un délai de réapplication négatif (`intervention_recommendation.py`)** : un garde interne refusait de calculer une échéance sur un délai négatif, mais le bloc de scoring ne testait que la présence du délai — `None.strftime(...)` levait une `AttributeError` et **plus aucun produit n'était proposé**. Le garde et son consommateur se contredisaient : l'un des deux avait forcément tort. Le service `register_product` refuse déjà un délai négatif (`vol.Range(min=0)`) ; un `.storage` retouché ou un catalogue importé à la main, non. Crash reproduit avant correction.

## 0.21.2
Un arrêt silencieux du bilan sol, trouvé par mypy là où la CI ne regarde pas — **766 tests verts**.
- **Le bilan sol ne peut plus s'arrêter sur une entrée du jour incomplète (`soil_balance.py`)** : quand le ledger contenait déjà une entrée pour aujourd'hui **sans réserve d'ouverture** (`previous_reserve_mm`) — entrée héritée d'une version antérieure à cette clé, ou `.storage` retouché — la réserve d'ouverture restait à `None` et le calcul levait un `TypeError` (`None + float`). Le bilan sol s'arrêtait alors **à chaque cycle**, sans rien signaler à l'utilisateur : réserve figée, dose d'arrosage calculée sur une réserve périmée. La branche « nouveau jour » possédait déjà la chaîne de replis complète ; la branche « même jour » s'aligne dessus. Le repli remonte à la **clôture de la veille** et non à `reserve_mm` du jour même, qui est la réserve de FIN de journée : la prendre pour ouverture ferait perdre l'ET0 déjà débitée. Crash reproduit avant correction, deux tests de non-régression (veille exploitable / entrée orpheline).
- **Portée réelle de la CI mesurée** : mypy ne couvre que **23 fichiers sur 39**, soit 7 777 lignes sur 29 479 — **74 % du code n'est pas typé-vérifié**, dont l'intégralité du cœur décisionnel (`coordinator`, `guidance`, `decision_watering`, `soil_balance`, `watering_policy`, `sensor`). Le défaut ci-dessus était invisible pour la CI comme pour les 764 tests. Six autres écarts de typage relevés sur les modules de logique pure, sans conséquence à l'exécution.

## 0.21.1
Derniers replis de robustesse issus des audits — **764 tests verts**.
- **Une valeur non finie n'est plus prise pour une mesure (`coordinator.py`)** : `float("nan")` et `float("inf")` **ne lèvent pas**, si bien qu'un capteur publiant `nan` propageait une valeur non finie dans TOUS les calculs (ET0, bilan sol, scores), où elle contamine silencieusement chaque opération sans jamais déclencher d'erreur. Une valeur non finie est désormais traitée comme une **absence de mesure**, au même titre que `unavailable`.
- **Les formateurs d'affichage ne restituent plus « unavailable » (`sensor.py`)** : `_human_datetime_text` et `_human_date_text` terminaient par `return text`, donc un état `unavailable`/`unknown` ressortait **littéralement** à la place d'une date. Filtré en amont côté coordinateur depuis la 0.20.0, mais ces fonctions restent atteignables depuis un état restauré ou un attribut. Verrouillé par un test (4 variantes de casse et d'espacement, plus une vraie date en non-régression).
- **Divergence d'horodatage documentée des DEUX côtés (`decision_mowing.py`, `guidance.py`)** — constat, **non corrigé volontairement**. Les deux modules datent le même arrosage différemment : la tonte lit en priorité `ended_at`/`started_at` et retombe sur **06:00 UTC** pour une entrée sans heure ; l'arrosage ignore ces champs et retombe sur **00:00 UTC**. Sur un arrosage déclaré à la main (date seule), les deux sous-systèmes le situent donc à **6 h d'écart** — le cooldown 24 h de l'arrosage expire avant que la tonte n'estime le gazon ressuyé. Unifier **déplace un cooldown** (plus permissif d'un côté, plus restrictif de l'autre) : c'est un arbitrage. Une note jumelle est posée dans chaque fonction pour qu'on ne corrige jamais un seul des deux côtés.

## 0.21.0
La **règle du tiers** protège enfin vraiment le gazon, et 65 lignes de plomberie inerte disparaissent — **763 tests verts**.
- **Règle du tiers et « hauteur trop faible » enfin ACTIVES (`decision_mowing.py`)** : ces deux protections ne lisaient que `capteur_hauteur_gazon`, un capteur physique que peu d'installations possèdent. Sans lui, la hauteur courante restait inconnue et **aucune protection de hauteur ne s'appliquait** — le capteur « hauteur de gazon estimée », pourtant calculé, exposé et affiché, était purement décoratif. Le calcul retombe désormais sur cette estimation, exactement comme le fait déjà `_recommended_mowing_height` pour la hauteur conseillée ; le capteur physique garde la priorité quand il existe (une mesure vaut mieux qu'une estimation). Rappel agronomique : couper plus d'un tiers du brin d'un coup retire trop de surface foliaire, le gazon jaunit et met des jours à repartir. Verrouillé par un test à double sens (gazon laissé longtemps sans tonte → blocage ; gazon tondu récemment → aucun blocage, la règle ne doit pas devenir permanente), dont l'échec sur l'ancien code a été vérifié.
- **Filtre par zones inerte supprimé (`decision_mowing.py`, `water.py`)** : `_configured_zone_ids` lisait une clé `configured_zone_ids` qui n'était **produite nulle part** — la liste autorisée était donc toujours vide et le filtre laissait systématiquement tout passer. Retrait de la fonction, de ses 4 sites d'appel, et de la chaîne de 3 helpers devenue orpheline dans `water.py` (`_watering_item_matches_zones`, `_normalize_allowed_zone_ids`, `_zone_ids_for_item`) : **65 lignes**. Ce code fantôme n'était pas neutre — un audit y avait vu la cause possible d'un blocage de tonte, et il a fallu le vérifier pour écarter la piste. À reconstruire proprement le jour où un vrai pilotage par zone sera voulu.
- **Deux écarts délibérément NON corrigés, documentés dans le code** : le seuil de blocage de tonte à 30 °C (alors que le reste de l'intégration place le vrai chaud à 32) et les bornes de hauteur 4,0-6,5 cm codées en dur qui rognent la configuration utilisateur. Les corriger autoriserait respectivement à tondre plus chaud et à couper plus court : ce sont des arbitrages agronomiques, pas des correctifs.

## 0.20.4
Correction du câblage de `survie_canicule_active`, ajouté en 0.20.3 mais **jamais arrivé jusqu'aux capteurs** — **762 tests verts**.
- **`water_bundle` recopie les clés du profil UNE PAR UNE (`decision_watering.py`)** — pas de `**watering_profile`. Une clé ajoutée dans `_profile_for_normal` sans être explicitement listée dans `decision_watering` n'atteint donc **jamais** les capteurs, **sans la moindre erreur ni le moindre avertissement**. C'est exactement ce qui est arrivé à `survie_canicule_active` : calculé, exposé côté guidance, absent en production. Détecté uniquement en vérifiant l'entité réelle après déploiement. La clé est maintenant listée, et un test de propagation **bout-en-bout** (snapshot complet) verrouille le chemin pour qu'il ne puisse plus se rompre en silence.

## 0.20.3
Deux informations que **rien n'exposait**, et sans lesquelles un affichage ne peut pas dire la vérité — **761 tests verts**.
- **Nouvel attribut `survie_canicule_active` (`guidance.py`, `decision.py`, `sensor.py`)** : jusqu'ici, aucun attribut ne portait l'information « c'est un arrosage de SURVIE » (≥ 32 °C réels **et** réserve quasi vide). Les codes d'action valent `aucune_action` / `surveiller` / `a_faire` / `critique`, et `heat_stress_level` est un score **composite** qui annonce déjà « severe » dès 30 °C via l'ET0 et l'air sec : s'y fier alarmerait pour rien. Un affichage n'avait donc aucun moyen de distinguer une recharge de routine d'une intervention d'urgence. Exposé sur le capteur `assistant`, verrouillé par un test (actif à 34 °C réserve vide, inactif à 30 °C dans les mêmes conditions — règle 0.16.0 préservée).
- **Qualité de l'ET0 horaire ajoutée à `sensor_health` (`coordinator.py`)** : `eto_radiation_measured`, `eto_pressure_measured` et `eto_hourly_available` rejoignent les voyants de santé existants. Depuis la 0.19.0, l'ET0 horaire **pilote le bilan du sol** : savoir si elle tourne sur des capteurs réels ou sur des replis n'est plus un détail (un vent **prévu** au lieu de mesuré donnait 9 mm/j au lieu de 6). Exposé au même endroit que le reste de la santé capteurs, donc lisible **sans activer les entités de diagnostic**.

## 0.20.2
Deux messages de blocage de tonte enfin exacts — **760 tests verts**.
- **Le message « Robot instable » était inatteignable (`decision_mowing.py`)** : la branche comparait `mower_reason_code` à `"mower_unreliable"`, or la coordination émet `"unreliable"` — `mower_unreliable` est le code côté **arrosage** (`decision_watering`), pas côté tonte. La comparaison portait donc sur une valeur qui n'arrive jamais, et les trois cas concernés (aucune tondeuse configurée, tondeuse injoignable, position réelle inconnue) retombaient tous sur le générique « Robot indisponible ». Signalé comme « code mort » par l'audit : c'était en fait une **erreur de nom**.
- **Trop chaud et trop froid ne se confondent plus (`decision_mowing.py`)** : les deux extrêmes renvoyaient le même libellé « Température extrême », impossible de savoir lequel ni à quel seuil. Le libellé précise désormais le sens, la valeur et le seuil. Le **code reste `temp_extreme`** — c'est du contrat public, consommé par la carte et les automatisations.
- **Seuil de tonte à 30 °C : constat documenté, non modifié.** C'est la porte la plus stricte de l'intégration, qui place le « vrai chaud » à **32 °C** partout ailleurs (survie canicule, rafraîchissement du soir). Combiné au ressuyage post-arrosage, il ne laisse en pratique qu'environ **1 h 30 exploitable par jour** en été. Le relever autoriserait à tondre plus chaud : c'est un arbitrage agronomique, pas un correctif.

## 0.20.1
Suite de l'audit tondeuse : **contrat public rendu cohérent** et 3 correctifs de coordination — **758 tests verts**.
- **`tonte_autorisee` et `mowing_blocked` ne se contredisent plus (`decision_mowing.py`)** : les deux divergeaient dans les DEUX sens. (a) `temp_extreme` manquait de `agronomic_block_codes` → `tonte_autorisee` restait à **ON à 35 °C** (et à 5 °C), donc une automatisation branchée sur le binary_sensor **lançait le robot en pleine canicule**. (b) `mowing_blocked` ne reflétait que les blocages machine/durs → il restait à **False** alors que la tonte était interdite (nuit, espacement, règle du tiers) ; inexploitable pour décider de laisser sortir le robot, alors que c'est l'attribut le plus « évident » pour une carte ou un flow Node-RED. La distinction VOULUE est préservée : `tonte_autorisee` reste le verdict du **gazon**, `machine_permet_tonte` celui de la **machine**, `action_possible` les deux — `machine_unavailable` n'est donc PAS un blocage agronomique (les tests existants protégeaient ce choix, ils ont attrapé une première version trop large).
- **La pause pluie ne bloque plus l'arrosage (`mower_coordination.py`)** : `rain_delayed` était classé « dehors » et jugé non fiable, alors que le robot est **rentré à sa station** — l'arrosage était donc bloqué (`mower_unreliable`) pour une machine parfaitement rangée. Comme la pause pluie s'arme sur quelques dixièmes de millimètre et dure 6 à 12 h, le lendemain d'une averse insignifiante la fenêtre d'arrosage du matin était perdue. La **tonte**, elle, reste bien bloquée (gazon mouillé) : vérifié par test dans les deux sens.
- **Une panne n'est plus masquée par un délai (`decision_mowing.py`)** : la branche « cooldown d'arrosage » passait avant le motif machine — un robot avec un moteur de lame bloqué affichait « Arrosage récent : attends encore 180 min » et la panne restait cachée jusqu'à 3 h dans un attribut secondaire. Un délai se résout seul, pas une panne : elle passe désormais en premier.
- **Garde-fous de hauteur documentés (`decision_mowing.py`)** — constat, **non corrigé volontairement**. Les bornes 4,0–6,5 cm ne sont pas des limites machine malgré leur nom : ce sont des garde-fous agronomiques qui **rognent la configuration** (un réglage 3,0–6,0 devient 4,0–6,0), en contradiction avec le commentaire de `number.py` qui annonce « aucune valeur codée en dur ». Les retirer ferait **descendre la hauteur conseillée** jusqu'à 3 cm hors saison chaude : c'est un arbitrage agronomique, pas un correctif.

## 0.20.0
Audit du sous-système **TONDEUSE** : 5 défauts confirmés et corrigés, dont un qui pouvait **laisser le gazon griller** — **755 tests verts**.
- **Le blocage par la tondeuse n'affame plus l'arrosage (`coordinator.py`)** — le plus grave. `watering_blocked_by_mower` n'avait **ni délai d'expiration ni porte de sortie** : robot coincé dehors, batterie à plat hors zone, API du fabricant en panne… le drapeau restait vrai indéfiniment et l'arrosage auto n'était **jamais** relancé, y compris réserve à sec en pleine canicule. Le drapeau `irrigation_blocked_but_critical`, prévu exactement pour ce cas, était calculé et exposé mais **consommé par personne** — ce qui répond enfin à la question laissée ouverte le 05/07/2026 (« réserve 0 mm à 32 °C pendant un blocage tondeuse : faut-il une exception critique ? » → oui, et elle n'existait pas). Un **arrosage de détresse** contourne désormais ce seul blocage quand le déficit est réellement critique, avec un avertissement dans les logs. L'exception est étroite : elle ne s'ouvre que sur les motifs **persistants** (robot non rangé, entité indisponible, tondeuse introuvable) — « tonte en cours » et « retour à la station » en sont exclus, ils se résolvent seuls et arroser alors tremperait le robot en plein cycle. Pluie, sol détrempé, sécurité et le switch « arrosage auto » de l'utilisateur restent **intégralement** bloquants.
- **Un capteur indisponible n'est plus lu comme une panne (`coordinator.py`, `mower_adapter.py`, `decision_mowing.py`)** : `unavailable`/`unknown` sont des ABSENCES de mesure, pas des valeurs. Le capteur d'erreur de la tondeuse devenu indisponible — cas courant, la plupart des intégrations republient leurs capteurs à chaque redémarrage de Home Assistant, et cette Mammotion en a plusieurs en permanence — était pris pour un **code d'erreur** : « Robot en erreur : défaut signalé, vérifier le robot » → **tonte bloquée** *et* arrosage bloqué (`mower_unreliable`), alors que le robot allait parfaitement bien. Filtré sur 4 niveaux (état brut, adaptateur, formateur d'affichage, listes de codes « pas d'erreur »). Effet secondaire réglé : l'attribut `tondeuse_prochain_depart` n'affiche plus le littéral « unavailable ».
- **Cooldown de tonte fantôme supprimé (`decision_mowing.py`)** : `_latest_watering_timestamp` fabrique un repli « aujourd'hui 06:00 UTC » quand aucun arrosage ne correspond, et le cooldown n'était pas gardé par l'historique. Sur une instance qui n'avait **jamais** arrosé, la tonte était donc refusée chaque matin de 08:00 à 11:00 locales — **exactement la fenêtre idéale** — avec le message mensonger « Arrosage récent : attends encore 180 min ». Verrouillé par un test (vérifié : il échoue sur l'ancien code).
- **Température absente ≠ 0 °C (`decision_mowing.py`)** : les trois sources (capteur, entité météo, prévision) peuvent tomber ensemble ; le `or 0.0` transformait l'absence de mesure en gel fictif → blocage « Température extrême ». On ne bloque plus sur une donnée qu'on n'a pas.
- **Position du soleil inconnue ≠ nuit (`coordinator.py`)** : `sun_above_horizon` valait `False` quand `sun.sun` était `unavailable`, au lieu de `None`. Les consommateurs testant `is None` pour activer leur repli horaire, le **garde-fou de nuit de la tonte était purement désactivé** dans ce cas.

## 0.19.3
Nettoyage et clarification issus de l'audit : **45 lignes mortes supprimées**, constante partagée, écarts connus documentés là où ils se lisent — **753 tests verts**, aucun changement de comportement.
- **Suppression de 11 attributs morts `mad_*` (`decision.py`, `sensor.py`)** : `mad_ratio_base`, `mad_ratio_effective`, `mad_band`, `mad_reason`, `mad_policy_*` (6 clés), `mad_hysteresis_state`, `mad_threshold_mm` étaient lus depuis le bilan et exposés sur trois capteurs, mais **aucun producteur ne les alimentait** — reliquat du sous-système `dose_policy` retiré en 0.18.3, donc toujours `None`. Seul `mad_ratio`, réellement produit, est conservé (et c'est le seul que lit la carte). Vérifié : aucun consommateur, ni dans l'intégration, ni dans les tests, ni dans la carte.
- **Kc de repli factorisé (`const.py`, `guidance.py`, `gazon_brain.py`)** : la valeur 0,8 (Kc gazon Normal FAO-56) existait en double, indépendamment, dans le repli du ledger et dans le dimensionnement du garde-fou — deux copies qui pouvaient diverger en silence. Elles pointent désormais vers `KC_GAZON_NORMAL_DEFAUT`.
- **Écart documenté : la marge de rattrapage du garde-fou hebdomadaire est en pratique ANNULÉE (`guidance.py`)** — constat d'audit, **volontairement non corrigé**. Le plafond vaut `7 × ET0 × 0,8 × 1,15`, mais le Kc RÉEL atteint 0,92 dès qu'une tonte de moins de 8 jours est enregistrée (bonus post-tonte de `compute_kc_gazon`), soit l'état **permanent** avec une tondeuse robot. Or 0,8 × 1,15 = 0,92 : le plafond correspond donc *exactement* à 7 jours d'ETc réelle, **sans marge** (38,6 mm/sem à ET0 = 6 au lieu de 44,4 annoncés). Élargir un plafond de sûreté autorise plus d'eau : c'est un arbitrage agronomique, pas un correctif — le comportement est inchangé, l'écart est désormais écrit à l'endroit où on le lit.
- **Échelles mixtes de `_hydric_balance_level` documentées (`sensor.py`)** — également **non corrigé volontairement**. Les seuils (1/2/4/8) ont l'allure d'un déficit journalier mais reçoivent des **cumuls** 3 j / 7 j (12 à 42 mm en saison) : « excédentaire » et « équilibré » sont donc hors d'atteinte et le niveau brut retombe sur « déficit ». En pratique masqué par `_harmonized_hydric_labels`. Le correctif « évident » (normaliser par l'horizon) a été essayé puis **abandonné** : il rendrait « fort déficit » quasi inatteignable et régresserait le correctif 0.16.0 (test dédié à l'appui). Un vrai correctif suppose de re-choisir les 4 seuils ensemble.
- **Documentation** : `docs/public-attribute-contract.md` complété des attributs `jours_avant_arrosage_estime` / `date_prochain_arrosage_estime` (exposés depuis la 0.18.0).

## 0.19.2
Durcissement de l'accumulation horaire introduite en 0.19.0, après un audit adversarial de ce code neuf : **5 défauts de robustesse confirmés et corrigés**, tous capables de fausser l'arrosage en silence — **753 tests verts**. La fidélité du calcul FAO-56 lui-même a été revérifiée sur **20 000 tirages aléatoires** contre la chaîne de référence : écart maximal **4,4e-16 mm/h** (bruit flottant) — le calcul était juste, seule sa robustesse ne l'était pas.
- **Un blip de capteur n'efface plus l'accumulation du jour (`soil_balance.py`)** : un seul cycle sans taux horaire (capteur `unavailable` — cas COURANT, tout redémarrage de Home Assistant rend la station météo indisponible le temps du démarrage) réécrivait l'entrée du ledger sans les clés de cumul, qui étaient alors purgées. Le cumul repartait du prorata au cycle suivant : mesuré **+22 % de sur-débit** quand un capteur clignote, l'intégration horaire étant en pratique remplacée par le prorata **sans aucun signe visible**. Le cumul et son horodatage sont désormais conservés en repli, et le mode de la journée est persisté dans un **drapeau explicite** (`etp_hourly`) au lieu d'être déduit de la présence des clés.
- **Une coupure ne laisse plus d'eau fantôme (`soil_balance.py`)** : le pas d'intégration est borné à 2 h pour éviter le sur-débit, mais les heures manquées étaient **définitivement perdues** — et la clôture de la veille figeait l'erreur dans la réserve d'ouverture du lendemain (**+2,6 mm** mesurés pour 8 h d'arrêt, jamais rattrapés). Sur un pas borné, le cumul se **resynchronise désormais sur le prorata**, seule estimation qui connaisse la fraction de journée écoulée pendant l'absence.
- **Une journée tronquée ne se clôture plus à 0 mm (`soil_balance.py`)** : si le seul cycle d'une journée tombait **avant l'aube**, la fraction écoulée valait 0 → cumul `0.0` mm, qui n'est pas `None` et l'emportait donc sur l'estimation à la clôture. Une journée entière d'ETc n'était jamais débitée (**~5 mm** d'eau fantôme) et le sol paraissait plein au réveil — précisément quand la décision d'arroser se prend. Une clôture dont le cumul est inférieur à la moitié de l'estimation journalière retient désormais l'estimation, plus sûre.
- **Un capteur publiant `nan` ne gèle plus le bilan (`water.py`, `coordinator.py`)** : `max(0.0, nan)` renvoie `0.0` (Python garde le premier argument), si bien qu'un NaN se propageait en « taux nul » — mode horaire toujours actif, réserve qui **cesse de descendre**, journée clôturée sur la valeur bloquée. La finitude de toutes les entrées est vérifiée et un taux non fini est traité comme **absent** (repli prorata), jamais comme zéro. Un taux **nul reste légitime** (la nuit, sans rayonnement) et n'est pas confondu avec une absence.
- **Unités des nouveaux capteurs contrôlées (`config_flow.py`, `coordinator.py`)** : rien n'empêchait de sélectionner un rayonnement en kW/m² ou une pression en Pa. Impact mesuré : rayonnement en kW/m² → **ET0 −81 %**, le sol ne sèche plus et **l'arrosage ne part jamais, même en canicule**. Les sélecteurs filtrent désormais par `device_class`, et des **bornes de plausibilité** (0-1400 W/m², 800-1100 hPa) ignorent une valeur aberrante avec un avertissement dans les logs, au lieu de l'appliquer.
- **Sans rayonnement NI nébulosité, on rend la main au modèle (`coordinator.py`)** : le calcul supposait alors un ciel à 50 % (soit quasi clair) et vidait la réserve à ce rythme **tous les jours, pluie comprise**. Il retombe désormais sur le prorata de l'ET0 journalière, qui tient compte de la météo du jour.
- **Robustesse annexe** : horodatage persisté naïf face à un `now` aware (`TypeError` dans un chemin exécuté toutes les 2 min) traité comme illisible ; `ZeroDivisionError`/`OverflowError` sur températures absurdes rattrapées ; unité de vent normalisée aussi dans le calcul HORAIRE (un vent en m/s était divisé par 3,6 en trop → **ET0 −12 %**), via une fonction partagée avec l'ET0 journalière.
- **Estimation du prochain arrosage recalée (`water.py`)** : elle comparait la réserve au seuil MAD sans tenir compte du **déclenchement à l'aube** (qui part le matin du jour où la réserve VA franchir le seuil). Elle annonçait donc « demain » le matin même où l'arrosage partait. Affichage seul, aucune décision modifiée.
- **Commentaires et documentation remis en accord avec le code** : plusieurs commentaires affirmaient que l'ET0 horaire « n'entre dans aucune décision » (faux depuis la 0.19.0) ou que le ledger débitait l'ET0 brute (faux depuis la 0.17.3) — ils invitaient à supprimer ou « re-corriger » du code vital. Les deux nouvelles entrées de configuration sont désormais **caviardées dans les diagnostics** (elles fuitaient en clair dans un rapport joint à une issue) et **documentées dans le README**. Un test de non-régression égaré dans le fichier supprimé en 0.18.3 (couverture du repli « pas de ledger sol → modèle déficit », protégé par le CLAUDE.md) a été relogé.

## 0.19.1
La **projection de déclenchement à l'aube** raisonne enfin dans la même unité que le bilan sol — **748 tests verts**.
- **Projection en ETc, plus en ET0 brute (`guidance.py`, `decision_watering.py`)** : le déclenchement compare « déplétion actuelle + ET qu'il reste à s'écouler aujourd'hui » au seuil MAD. Il projetait l'**ET0** alors que le sol perd son eau au rythme de l'**herbe** (ETc = ET0 × Kc) — l'unité que le ledger débite depuis la 0.17.3. La soif prévue était donc gonflée d'environ **25 %**. Cas concret vérifié par test : le **lendemain d'une recharge complète** (réserve pleine, déplétion 0) avec ET0 6,1 mm/j, le ratio projeté valait **0,51 > MAD 0,50** → l'intégration relançait **5 mm sur un sol plein** ; en ETc (4,9) le ratio tombe à **0,41** → pas d'arrosage. Le bilan expose désormais `etc_mm` et `kc_gazon`, avec repli sur le Kc typique (0,8) si l'ETc n'est pas fournie — pour rester en unité ETc plutôt que de retomber sur l'ET0. **Ni la dose, ni le seuil MAD, ni le plafond hebdo, ni les urgences ne changent** : seule l'unité de la projection est corrigée. Verrouillé par 2 tests (dont la preuve que l'ancien comportement arrosait bien 5 mm à tort, et qu'une vraie journée demandante déclenche toujours).
- **Mesuré sur l'historique réel avant correction** : sur les 4 aubes observables du 24 au 28/07/2026, les deux variantes (ET0 et ETc) déclenchaient à l'identique — ce qui espaçait réellement les arrosages était le `cooldown_24h` et le budget hebdomadaire, pas l'état du sol. Ce correctif est donc une **remise en cohérence d'unité** à effet immédiat faible, qui protège surtout le cas marginal du lendemain de recharge par forte demande.

## 0.19.0
Le bilan sol sèche désormais au **rythme RÉEL mesuré** : l'intégration calcule l'**ET0 de référence HORAIRE** (FAO-56 Eq. 53) depuis le **rayonnement et la pression mesurés**, et le ledger **intègre ce taux au fil du temps** au lieu d'étaler une estimation journalière — **746 tests verts**. Vérifié en marche réelle : l'ET0 horaire de l'intégration est tombée à **0,495 mm/h** contre **0,4948** pour une chaîne FAO-56 de référence indépendante (écart 0,04 %).
- **Le débit du sol suit l'ET mesurée heure par heure (`soil_balance.py`, `gazon_brain.py`)** : le ledger retranchait `ET0_journalière × fraction_écoulée`, où l'ET0 journalière est **extrapolée d'un instantané** (vent PRÉVU, ciel supposé dégagé). Constaté le 28/07/2026 : elle annonçait **9 mm/j** à 15 h puis **6,9** à 17 h, là où trois références indépendantes (chaîne FAO-56 sur capteurs, Open-Meteo, Hargreaves) convergeaient vers **~6** — le sol était donc asséché jusqu'à **50 % trop vite**, ce qui déclenchait des recharges prématurées. Quand un taux horaire mesuré est disponible, le ledger l'**intègre** (somme de Riemann : `taux × durée écoulée`) : le débit suit la demande réelle, et la « falaise de minuit » disparaît **par construction**. **Ni la dose, ni le seuil MAD, ni le plafond hebdo ne changent.**
- **Garde-fous de l'accumulation** : pas d'intégration **borné à 2 h** (une coupure de Home Assistant ne peut pas vider la réserve en appliquant le taux courant sur tout le trou) ; **amorçage au prorata** de l'ET0 journalière si l'accumulation démarre en cours de journée (démarrage à midi → les heures précédentes restent comptées) ; **horloge non monotone** (changement d'heure, resynchro NTP) sans effet ; cumul **plafonné** à `ETP_DAILY_CAP_MM` ; **repli intégral** sur le modèle prorata sans taux horaire. Le filet de **clôture de la veille** est préservé : une journée en repli prorata reste clôturée sur l'ET0 **pleine journée** (sinon un arrêt de Home Assistant à midi sous-débiterait la veille et l'erreur se propagerait) — seule une journée réellement pilotée à l'heure se clôture sur son cumul mesuré. Verrouillé par **7 tests** dédiés.
- **Clés persistées `etp_elapsed_mm` / `etp_last_ts` (`soil_balance.py`)** : `_normalize_ledger_entry` est une **liste blanche** — toute clé absente est perdue à chaque passage ET à chaque rechargement du state persisté. Sans leur ajout explicite, l'accumulation n'aurait **jamais** survécu d'un cycle à l'autre (aucun débit horaire, en silence). Défaut détecté par les tests avant tout déploiement.
- **Calcul horaire FAO-56 (`water.py`)** : trois fonctions pures — `_ra_hourly` (rayonnement extraterrestre, Eq. 28, 100 % astronomique donc jamais indisponible), `_rs_hourly` (rayonnement global : radiation **mesurée** prioritaire, repli modèle nuages Kasten-Czeplak, plafond d'absurdité 0,85·Ra) et `compute_eto_hourly` (Penman-Monteith horaire, Eq. 53 : γ sur la **pression mesurée**, Rns = 0,77·Rs, Rnl via σ horaire et le ratio Rs/Rso, G = 0,1·Rn le jour). Verrouillé par **5 tests dorés** calés sur des relevés réels : Rs à 756 W/m² = 2,7216 MJ/m²/h, ET0 à 34 °C/20 % d'humidité = 0,6116 mm/h, ET0 **nulle la nuit**, repli nuages sans capteur.
- **Passé mesuré ≠ futur estimé** : seul le **débit** du sol (ce qui s'est réellement évaporé) bascule sur l'horaire. Le **déclenchement à l'aube** et le **plafond hebdomadaire** continuent de s'appuyer sur l'ET0 **journalière**, car ils répondent à une question de *prévision* (« le sol va-t-il manquer d'eau aujourd'hui ? ») — une accumulation, nulle au lever du jour, y serait un contresens.
- **Pourquoi** : l'ET0 journalière estimée (`compute_etp`) part d'un **instantané** extrapolé à toute la journée, avec le **vent prévu** et une radiation déduite de la couverture nuageuse. Constaté le 28/07/2026 : elle annonçait **9 mm/j** (vent prévu 11,5 km/h, ciel supposé dégagé au maximum) là où trois références indépendantes — chaîne FAO-56 horaire sur capteurs, Open-Meteo et Hargreaves — convergeaient vers **~6 mm/j** (vent réel mesuré 5,2 km/h). Une ET0 surestimée de 50 % assèche le bilan sol trop vite et gonfle le plafond du garde-fou hebdomadaire.
- **Deux nouvelles entrées de configuration (`const.py`, `config_flow.py`, traductions)** : « Rayonnement global mesuré » (W/m²) et « Pression atmosphérique mesurée » (hPa), toutes deux **optionnelles**. Sans elles, le calcul retombe sur le modèle nuages et la pression standard (1013 hPa) — comportement inchangé. Elles rejoignent les entités suivies : une variation du rayonnement rafraîchit le calcul.
- **Longitude injectée (`coordinator.py`)** : la latitude seule suffisait au calcul journalier ; l'angle horaire solaire du pas de temps horaire exige aussi la longitude (lue depuis la configuration Home Assistant).
- **Nouveau capteur `eto_horaire` (`sensor.py`, `entity_ids.py`)** : expose l'ET0 horaire (mm/h) avec l'origine de chaque entrée (`radiation_source`, `pressure_source`, `wind_kmh`), ce qui permet de vérifier d'un coup d'œil que le calcul tourne bien sur des valeurs **mesurées** et non sur les replis.

## 0.18.4
Correction du **budget hebdomadaire qui se refermait sur l'arrosage du jour** — **732 tests verts**.
- **Garde-fou hebdo : la somme 7 j n'est plus écrasée par l'arrosage du jour (`water.py`)** : les jours d'arrosage, `retour_arrosage` (l'eau du JOUR) **remplaçait** la somme 7 j au lieu de la **plancher** — le compteur `arrosage_recent_7j` se refermait alors sur le seul arrosage du jour. Constaté le 28/07/2026 : **12 mm décomptés** alors que **36 mm** d'arrosage AUTO (3 × 12 mm les 22, 23 et 28) avaient été appliqués sur 7 j → budget affiché « 27 % » au lieu de « 81 % », et garde-fou trop permissif les jours d'arrosage (il croyait ~32 mm de marge au lieu de ~8). La vraie somme 7 j est désormais **toujours calculée depuis l'historique** ; `retour_arrosage` et le capteur « retour arrosage » externe ne servent plus que de **plancher** (garantir que l'eau du jour, parfois pas encore dans l'historique, est comptée), sans jamais réduire la somme. Bug **pré-existant** (depuis la 0.7.0), révélé par l'analyse de l'arrosage du 28/07 ; il se « soignait » de lui-même les jours SANS arrosage (`retour_arrosage`=None), d'où son invisibilité. **Ni la dose, ni le seuil MAD, ni le plafond du garde-fou ne changent** — seul le décompte de l'eau déjà reçue est corrigé. Verrouillé par 2 tests (accumulation multi-jours non écrasée par l'arrosage du jour ; plancher fonctionnel sans rien inventer quand l'historique est vide).

## 0.18.3
Nettoyage & clarté : suppression du sous-système `dose_policy` mort + renommage des clés internes de stress hydrique (le mot « canicule » quitte les valeurs brutes) — **730 tests verts**. Aucun changement de comportement ni d'affichage.
- **Suppression du code mort `dose_policy` (`watering_policy.py`, `decision.py`, `decision_models.py`, `sensor.py`)** : ce sous-système (bandes de dose saisonnières) n'était **jamais alimenté** en production — `water_bundle["dose_policy"]` restait toujours vide, donc toutes les clés `dose_*` du snapshot valaient `None`. Retiré entièrement (~490 lignes, dont le fichier de test `test_dose_policy.py`). Le pilotage MAD (`mad_*`) et le reste sont intacts.
- **Renommage interne des valeurs de stress hydrique (`guidance.py`, `sensor.py`, `decision_watering.py`)** : les VALEURS brutes de `heat_stress_level` employaient un vocabulaire de chaleur alors que c'est un score de **stress hydrique composite** (une ET0 élevée à 24 °C n'est PAS une canicule). `"canicule"` → `"eleve"`, `"extreme"` → `"severe"` ; phases `"canicule_courte/prolongee/sortie_de_canicule"` → `"stress_court/prolonge/sortie_de_stress"` ; libellé de raison « Stress thermique » → « Stress hydrique ». **L'affichage utilisateur est INCHANGÉ** (déjà « Stress hydrique élevé/sévère »). Les NOMS de constantes désignant la VRAIE canicule (`SURVIE_CANICULE_MIN_TEMP` ≥ 32 °C, etc.) sont préservés — survie et rafraîchissement du soir restent gardés à ≥ 32 °C réels.

## 0.18.2
Modernisation du garde-fou hebdomadaire : le plafond suit la **demande réelle (ETc)** en continu, plus des paliers « canicule » — **737 tests verts**.
- **Plafond hebdo piloté par la demande ETc, en continu (`guidance.py`)** : le plafond du garde-fou ne saute plus par **paliers** (26 → 42 → 50 selon un score thermique via `_heat_stress_phase`) mais suit la **demande réelle du gazon** — `plafond = 7 × ET0 × Kc × marge_de_rattrapage`, planché sur la **base saisonnière** et borné à un **plafond de sûreté** (50 mm). Conséquences : (a) fini le **yo-yo 26↔42** quand le score de stress bascule (constaté le 27/07 : budget « 145 % bloqué » puis « 64 % » à quelques minutes d'intervalle) ; (b) une **forte demande évaporative** (ET0 haute, air sec) relève le plafond **à n'importe quelle température** — une ET0 élevée à 24 °C n'est PAS une canicule, juste une forte demande ; (c) un plafond figé à 28 n'étrangle plus l'arrosage quand la demande grimpe. **La dose, le seuil MAD, la survie canicule (≥ 32 °C réels) et le secours réserve ne changent pas** — seule la **largeur** du plafond suit désormais la demande. Verrouillé par 2 tests (le plafond croît avec l'ET0, borné au plafond de sûreté, plancher saisonnier préservé).

## 0.18.1
Correction du **décalage d'un jour** de la fenêtre du garde-fou hebdomadaire — **735 tests verts**.
- **Fenêtres 3 j / 7 j : de vraies fenêtres (`water.py`)** : le filtre retient `delta <= days`, donc `days=N` couvrait **N+1 jours** calendaires. La fenêtre journalière avait déjà été ramenée à `days=0` (0.17.x), mais 3 j / 7 j étaient restées à `days=3/7` = **4 et 8 jours**. Conséquence concrète (constatée le 27/07 : réserve à sec, gazon en attente) : `arrosage_recent_7j` gardait un arrosage **un jour de trop** dans le décompte → le budget mettait un jour de plus à retomber sous le plafond, prolongeant d'autant le blocage de l'arrosage auto. Corrigé en alignant sur la fenêtre journalière : `days=6` (7 jours pile) et `days=2` (3 jours pile), idem pour `arrosage_applique_7j`. **La dose, le seuil MAD et le plafond hebdo ne changent pas** — seule la largeur de la fenêtre de décompte est corrigée. Verrouillé par un test de bord (un arrosage à J‑7 sort désormais du décompte 7 j, à J‑3 du décompte 3 j).

## 0.18.0
Nouveau : l'intégration estime et expose le **prochain jour d'arrosage** (pour affichage sur la carte) — **734 tests verts**. Fonctionnalité de **lecture/affichage seule** : aucune décision d'arrosage n'est modifiée.
- **Estimation du prochain jour d'arrosage (`water.py`, `decision_watering.py`, `sensor.py`, `decision.py`)** : nouvelle fonction pure `estimate_days_until_watering(réserve, seuil MAD, ETc)` qui projette dans combien de jours la réserve du sol atteindra le seuil de déclenchement (MAD), au rythme de séchage ~ETc/jour (le sol perd son eau au rythme de l'herbe — cohérent avec le ledger débité en ETc depuis 0.17.3). Le capteur `prochain_arrosage` expose deux nouveaux attributs : `jours_avant_arrosage_estime` (entier, `0` = imminent, `1` = demain, …) et `date_prochain_arrosage_estime` (date ISO = aujourd'hui + jours). Purement **indicatif** : la météo réelle des prochains jours n'étant pas connue, la pluie prévue n'est PAS déduite et l'estimation se recale d'elle-même à chaque cycle. **N'entre dans AUCUNE décision d'arrosage** — le déclenchement réel reste piloté à l'aube sur la soif projetée. Couvert par 7 tests (fonction pure + propagation bout-en-bout jusqu'au snapshot).

## 0.17.3
Bilan sol recalé sur la vraie consommation de l'herbe + garde-fous d'arrosage plus justes — **727 tests verts**. Déployé et vérifié en marche sur l'installation réelle (réserve affichée « 0 / critique » alors qu'elle était en réalité ~10 mm : cause identifiée et corrigée).
- **Le bilan sol débite l'ETc, plus l'ET0 brute (`gazon_brain.py`, `water.py`)** : le ledger retranchait l'**ET0** (évapotranspiration de référence) alors que le sol perd son eau au rythme de l'**herbe** = ETc = ET0 × Kc (FAO-56, Kc ≈ 0,8 en phase Normal). Il asséchait donc le bilan **~20 % trop vite** : réserve tombée à « 0 » alors qu'il restait ~10 mm (constaté 25/07 : ~52 mm reçus sur 7 j, réserve à 0 ; recalcul en ETc → ~10 mm). Le ledger applique désormais le Kc **déjà calculé par le modèle** (repris du cycle précédent, `last_result` — la phase évolue sur des jours, jamais entre deux cycles de 2 min ; repli 0,8 au démarrage). Le **calcul de l'ET0 lui-même n'est pas touché** (on applique juste le Kc avant de débiter le sol). Prouvé par test (ET0 10 + Kc 0,55 → ledger reçoit 5,5).
- **Arrosages manuels exclus du garde-fou hebdomadaire (`water.py`)** : un arrosage manuel (`start_manual_irrigation`) créditait la réserve MAIS gonflait aussi le budget hebdo — d'où un cercle vicieux (réserve basse → auto bloqué → arrosage manuel de secours → budget plus haut → auto bloqué plus longtemps → jamais de reprise auto). Le manuel reste dans la réserve (l'eau est bien tombée) mais **ne compte plus dans le budget de l'auto**, comme l'externe. Nouveau paramètre `include_manual` sur `compute_recent_watering_mm` (défaut `True` = eau réellement reçue).
- **Fenêtre du soir — le profil fait foi dans les deux sens (`decision_watering.py`)** : le soir doit être un **rafraîchissement** (~3 mm), jamais une recharge complète (`_profile_for_normal` : « LE SOIR = UNIQUEMENT LE RAFRAÎCHISSEMENT, JAMAIS UNE RECHARGE »). L'arbitrage de la fenêtre ne laissait le profil qu'**ajouter** « soir », jamais le retirer : quand le rafraîchissement était inactif (switch éteint, < 32 °C) et que le profil reportait la recharge au matin, le « soir » du risk bundle reprenait le dessus → 11 mm de recharge planifiés à 21 h, fin ~1 h 45 après le coucher du soleil, gazon trempé la nuit (risque fongique). Le profil fait désormais autorité pour « soir » **dans les deux sens** (fonction `_resolve_optimal_window`, factorisée depuis deux copies dupliquées).
- **Exemption « réserve réellement vide » (`guidance.py`)** : filet de sécurité. Si la réserve est genuinement quasi vide (déplétion réelle ≥ 90 %, ledger au prorata → pas la « falaise de minuit ») ET la journée demandante (`heat_stress` ≠ « normal »), un **arrosage de secours modéré** (~min_session) est débloqué même sous 32 °C — sinon un sol réellement à sec restait bloqué par le garde-fou hebdo ou le cooldown d'un petit arrosage manuel. La **recharge complète** reste réservée à la survie canicule (≥ 32 °C) et **aucun arrosage** par temps frais (règles 0.16.0 préservées, prouvé par tests).

## 0.17.2
Correction d'une **régression introduite en 0.16.0** : le logo de l'intégration ne s'affichait plus dans Home Assistant (vignette « icon not available »). Aucun changement fonctionnel — **722 tests verts**, inchangés.
- **Restauration de `custom_components/gazon_intelligent/brand/` (`icon.png`, `logo.png`)** : ce dossier avait été supprimé en 0.16.0, à tort, sous le motif « images identiques à la racine, non référencées ». Il l'était en réalité par Home Assistant lui-même : depuis **HA 2026.3** ([annonce](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api)), une intégration custom fournit ses images de marque dans un dossier `brand/`, et **ces images locales sont prioritaires sur le CDN** `brands.home-assistant.io`. Sans ce dossier, HA retombait sur le CDN, où le domaine `gazon_intelligent` n'est pas enregistré — d'où la vignette grise. Le dossier est restauré avec la nouvelle identité visuelle (256×256, détourées et compressées sans perte).
- **Note pour l'avenir** : le dépôt `home-assistant/brands` **n'accepte plus** de nouvelles intégrations custom (cf. la même annonce) ; le dossier `brand/` local est désormais la seule voie. Ne pas le supprimer.

## 0.17.1
Nouveau logo (identité visuelle retravaillée). Aucun changement fonctionnel — **722 tests verts**, inchangés.
- **Identité visuelle (`icon.png`, `logo.png`)** : nouvelle version du blason (bandeau « INTELLIGENT » doré, contour retravaillé). Ces images servent au README et à la vitrine du dépôt : Home Assistant ne les lit pas — l'icône affichée dans HA provient du dépôt officiel [home-assistant/brands](https://github.com/home-assistant/brands), où le domaine `gazon_intelligent` n'est pas encore enregistré (d'où la vignette « icon not available » dans la liste des mises à jour).

## 0.17.0
Fin du sur-arrosage : le gazon recevait **~59 mm/semaine pour un besoin réel de ~33 mm** (+80 %), constaté sur l'historique réel du 17 au 23/07. Cause racine identifiée et corrigée dans le bilan sol, plus 3 correctifs de comptabilité et d'affichage — **722 tests verts**. Déployé et **vérifié en marche sur l'installation réelle** : réserve qui descend enfin progressivement dans la journée (8,4 → 4,6 mm), falaise de minuit disparue, recharge du matin annulée à juste titre.
- **Sur-arrosage — l'ET0 du jour n'est plus débitée d'un coup à minuit (`soil_balance.py`, `gazon_brain.py`)** : `update_soil_balance` faisait `delta = pluie + arrosage − etp` avec l'ET0 de la journée ENTIÈRE dès le premier passage après minuit. La réserve tombait donc à ~0 à 00h01 **et se faisait écraser au plancher** — information perdue pour de bon. Au lever du jour, le pilotage voyait un sol « vide » et commandait une recharge pleine (12 mm) sur un sol encore rempli à 70 % : le surplus drainait sous les racines, chaque matin. L'ET0 est désormais débitée **au prorata de la journée réellement écoulée** (`et_elapsed_fraction`, 0 au lever → 1 au coucher, déjà calculée et jusque-là inutilisée par le ledger) ; le total débité en fin de journée est identique, seule la RÉPARTITION change. Effet mesuré en simulation sur les conditions réelles : **~30 mm/semaine au lieu de 59**, en arrosages **profonds et espacés** (≈ 12 mm tous les 2 jours au lieu de 12 mm/jour), ce qui favorise l'enracinement profond. Garde-fou ajouté : au changement de date, le solde d'ouverture est reconstruit avec l'ET0 **pleine journée** de la veille — sinon un Home Assistant éteint le soir laisserait la veille sous-débitée et l'erreur se propagerait de jour en jour. Repli sûr si la position du soleil est inconnue (→ comportement historique).
- **L'arrosage part toujours à l'aube (`guidance.py`)** : effet de bord du correctif précédent, rattrapé avant déploiement. En pilotant sur la déplétion réelle, le seuil MAD n'était plus franchi qu'une fois la soif installée — donc souvent en milieu de journée, le pire moment (évaporation). Le **déclenchement** se base désormais sur la déplétion **projetée en fin de journée** (`déplétion + ET0 restant à s'écouler`) : à l'aube, cela répond à la bonne question — « le sol va-t-il manquer d'eau aujourd'hui ? ». La **dose**, elle, reste calée sur la déplétion **réelle**, c'est-à-dire la place réellement disponible dans le sol : verser au-delà ne ferait que drainer. Les overrides d'urgence (survie canicule, déplétion critique) gardent la déplétion réelle, pour ne pas s'armer la nuit. La reconstruction en aval introduite en 0.16.0 est retirée : la correction vit maintenant à la source, une double correction sous-arrosait.
- **Bilan journalier — la fenêtre « jour » comptait 2 jours (`water.py`)** : le filtre retient `delta <= days`, donc `days=1` ramassait aussi la veille. `arrosage_recent_jour` créditait ainsi **2 jours d'arrosage contre 1 seul jour d'ET0** (`_horizon_balance(horizon_days=1)`) → bilan surestimé d'un arrosage entier (constaté : 24 mm affichés pour 12 mm réellement appliqués, bilan +17,7 au lieu de −9,6 le lendemain). Aligné sur `days=0` (aujourd'hui seul), ce que le ledger sol utilisait déjà de son côté (`arrosage_reel_jour`). Les fenêtres 3j/7j gardent leur sémantique (budget hebdomadaire) et ne sont pas touchées.
- **Incorporation post-produit — un sol humide ne la bloque plus (`coordinator.py`)** : l'arrosage d'incorporation est TECHNIQUE — il fait pénétrer le produit dans le sol via l'eau (cf. fertigation). Le motif « sol déjà humide » le refusait pourtant au lancement, alors que c'est justement dans l'eau que le produit descend. L'incorporation **auto** est désormais exemptée de ce **seul** motif ; tous les autres (pluie, tondeuse, sécurité, type bloqué) restent bloquants, et un arrosage hydrique normal reste, lui, bloqué par un sol humide.
- **Message « attendre encore 0 min » (`decision_watering.py`)** : en mode `suggestion`, le drapeau `post_watering_ready` est TOUJOURS faux (par conception : pas de lancement automatique), si bien que la branche « attendre encore {délai} min » se déclenchait même avec un délai à **0**, et que la vraie branche « arrosage technique suggéré, sans lancement automatique » était inatteignable. La branche « attendre » n'est plus prise que s'il reste un délai réel (> 0).
- **Nouvel attribut `arrosage_applique_7j` (`water.py`, `decision.py`, `sensor.py`)** : `arrosage_recent_7j` sert au garde-fou hebdomadaire et **exclut** les arrosages techniques (rafraîchissement du soir, incorporation post-produit) ; l'eau réellement reçue par le gazon est donc supérieure, et l'écart était invisible — ce qui a longtemps masqué le sur-arrosage. Le nouvel attribut expose ce total réel (technique inclus) sur la vraie fenêtre 7 jours. `compute_recent_watering_mm` gagne un paramètre `include_technical` (défaut `False` = comportement inchangé).

## 0.16.0
Nouveau switch « Rafraîchissement du soir » et grand audit multi-passes (22-23/07) : **52 correctifs** vérifiés adversarialement (dont 3 bloquants et 6 régressions rattrapées en cours de route), tous couverts par des tests de non-régression — **714 tests verts**, `ruff` (famille pyflakes complète) + `mypy` (23 modules) + `unittest`. Déployé et **vérifié en marche sur le matériel réel** : cycle d'arrosage fractionné complet (2 passages, 3 zones), réserve créditée correctement (12 mm, pas de double-comptage).
- **Nouveau switch `rafraichissement_soir` (`switch.py`, `entity_ids.py`, `memory.py`, `const.py`, traductions)** : active/désactive le rafraîchissement du soir de canicule, avec seuil de température réelle `EVENING_COOLING_MIN_TEMP = 32 °C` (ne se déclenche qu'en vraie canicule). Correctifs bloquants : le suffixe manquait dans `PUBLIC_ENTITY_KEYS` → `KeyError` qui faisait échouer **toute la plateforme switch** au démarrage ; l'état du switch n'était pas reconduit par `compute_memory` → il se réinitialisait à chaque cycle.
- **Fenêtre du soir fiabilisée (`guidance.py`)** : en canicule, une recharge complète ne part plus le soir sans marge de séchage (réservé aux 3 mm de cooling) ; le blocage « sol détrempé » n'est plus effacé par le cooling ; la marge de séchage et le garde anti-fongique sont enfin transmis aux **deux** chemins de calcul (`_build_watering_ctx` et `compute_action_guidance`) ; en phase produit, la fenêtre « soir » ne s'annonce plus dès minuit.
- **Config flow — zones protégées (`config_flow.py`, `coordinator.py`)** : l'options flow n'efface plus les zones 2 à 5 ; la résolution du débit distingue « zone désactivée à 0 » de « absent » (un débit à 0 ne réactive plus l'ancienne valeur — une instance de test pouvait ouvrir la vanne de la pelouse principale).
- **Services — cible en liste (`__init__.py`)** : une cible `entity_id` fournie en liste (cas normal de l'UI) n'est plus transformée en chaîne illisible ; `device_id`/`area_id` sont pris en compte.
- **Bilan hydrique (`water.py`, `soil_balance.py`, `gazon_brain.py`)** : arrondi correct des valeurs négatives ; plafond de réserve dérivé du type de sol ; le ledger ne comptabilise que la pluie **mesurée** (plus la prévision quand le capteur tombe) ; protection de bord de journée sur la pluie (sans figer le cumul de la veille).
- **Tonte (`decision_mowing.py`, `mower_coordination.py`, `scores.py`)** : cooldown et ressuyage en **UTC réel** (fin du décalage de fuseau qui les faisait expirer 1-2 h trop tôt) ; l'état brut « en tonte » prime sur « en charge » ; la pluie n'est plus présentée comme une erreur tondeuse ; scores hydrique/tonte corrigés (un palier se déclenchait en permanence) ; blocage par score seul débloquable en cas de retard.
- **Exécution d'arrosage (`coordinator.py`)** : une vanne indisponible n'est plus créditée sans arroser (garde de disponibilité au lancement) ; température capteur (et prévision) validée avant de piloter l'ET0 ; fractionnement (`watering_passages`) publié correctement au lieu d'un repli silencieux sur 1 passage ; `zones_pending` stocke la dose par passage (piège de double-dose refermé).
- **Robustesse inter-instances (`shared_state.py`, `coordinator.py`)** : le catalogue produits partagé par les deux pelouses ne peut plus être chargé deux fois en parallèle au démarrage (verrou + double-vérification → plus de catalogue orphelin) ; garde d'exclusion mutuelle en **lecture seule** sur une vanne physique partagée (Sonoff 4CH) — si une instance arrose déjà la vanne, l'autre ne relance pas (au pire elle refuse, jamais de double-arrosage). Dormant en config réelle où la vanne partagée du Potager est neutralisée (débit 0).
- **Interventions & entités (`intervention_recommendation.py`, `select.py`, `diagnostics.py`, `number.py`, `sensor.py`)** : bloc « produit sélectionné » plus vidé à tort ; désélection de produit possible ; entity_id de la tondeuse caviardés dans les diagnostics ; bornes de hauteur de coupe ordonnées et repli borné ; voyant de validité du capteur pluie corrigé (tautologie).
- **Sécurité CI (`create_release.yml`)** : injection de script corrigée (`tag`/`target_sha` passés par `env`, plus interpolés dans le JavaScript).
- **Outillage** : `ruff` élargi à toute la famille pyflakes (paquet propre, 8 défauts de tests corrigés dont 2 tests dupliqués jamais exécutés) ; `mypy` passé de 4 à **23 modules** ; dépendances de dev bornées ; `test_translations.py` ajouté ; traductions resynchronisées (doublon `reconfigure`, 7 champs tondeuse, service `recalibrate_reserve`).
- **Nettoyage interne** : doublon `_is_application_*` fusionné (+ garde de robustesse), code mort retiré (fonctions/paramètres/clés jamais utilisés), contrat d'attributs publics corrigé (6 attributs fantômes retirés).
- **« Canicule » à 30 °C — garde-fou de vraie chaleur + libellés honnêtes (`guidance.py`, `sensor.py`, `decision_watering.py`)** : le `heat_stress_level` est un score COMPOSITE de stress hydrique (température, ET0, humidité, vent, pluie, déficit), pas une mesure de canicule — il pouvait atteindre « extrême » dès 30 °C par l'ET0 + l'air sec + le déficit (30 °C ne pesant que 2 points sur 7). La **survie canicule** (le seul override qui court-circuite le budget hebdomadaire) exige désormais une **température réelle ≥ 32 °C** en plus du stress et de la déplétion réelle — un arrosage de secours ne se déclenche plus sur une journée d'été sèche mais normale. Les **textes affichés** « canicule / stress extrême / arrosage de survie » sont reformulés en « stress hydrique / forte chaleur / arrosage de secours » (clés internes inchangées). Nouvel attribut d'affichage `stress_hydrique` (libellé honnête dérivé du niveau, source unique — la carte peut l'afficher au lieu de la clé technique). Prouvé par test (survie à 34 °C oui, à 30 °C non).
- **Falaise de minuit — urgences recentrées sur l'ET réellement écoulée (`guidance.py`)** : le ledger débite tout l'ET0 du jour dès minuit, donc `depletion_ratio` saturait à 00h01 (« falaise de minuit ») alors qu'aucune évapotranspiration n'avait eu lieu — armant à tort la « survie canicule » et l'outrepassement du garde-fou hebdomadaire. Les deux **overrides d'urgence** (survie canicule, dépassement du cooldown 24 h) se basent désormais sur la déplétion **réelle** (`depletion − ET0·(1−et_elapsed_fraction)`, cette fraction 0→1 étant déjà calculée mais jusque-là inutilisée). Résultat : plus de fausse urgence nocturne, l'urgence ne s'arme que quand le sol est vraiment épuisé (fin de journée). Le pilotage NORMAL reste anticipatif (planifie toujours l'arrosage du matin) ; la jauge affichée est inchangée ; repli sûr si le soleil est inconnu (→ comportement historique). Prouvé par test (minuit : dose bridée au budget ; journée écoulée : recharge de survie délivrée).
- **Passe « findings mineurs » de l'audit** : les 41 findings mineurs revérifiés un par un contre le code réel (la majorité déjà corrigés lors des passes précédentes). Retirés : blocs et paramètres morts confirmés inatteignables (`recovery_interrupted`, `last_watering_completed_at`, branche no-op de `_morning_window_bounds`, champ `_WateringCtx.transition_ready`, candidat tonte `phase` inatteignable, `phase_override` sans writer, param `allowed_zone_ids`, no-op `previous_state`, clé `reserve_utile_max_mm`) et le dossier `brand/` (images identiques à la racine, non référencées). Corrigés (façade/affichage, avec tests) : `type_arrosage` des phases produit suit désormais `auto_ok` au lieu d'être figé à « auto » ; le message de coordination tonte n'affiche plus « ce matin » le soir ; `raison_blocage_tonte` n'affiche plus le motif POSITIF de tonte quand le blocage vient en réalité de l'arrosage ; le niveau hydrique affiché est recentré sur le seuil d'épuisement MAD (`reserve_minimale_mm`) — « fort déficit » redevient atteignable et une réserve pile au seuil ne s'affiche plus « excédentaire ». Table de réserve utile du sol dupliquée épinglée par un test-jumeau anti-divergence. Écriture d'état immédiate (transitions d'arrosage) documentée comme volontaire (durabilité anti-crash > debounce).

## 0.15.0
Affinage canicule, corrections de bugs, grand nettoyage interne et README repensé (547 tests verts) :
- **Rafraîchissement du soir affiné (`guidance.py`, `coordinator.py`, `decision_watering.py`)** : le cycle de refroidissement part désormais **30 min avant le coucher du soleil** (au plus frais → moins d'évaporation) au lieu de la fenêtre fixe 18-20 h, en **un seul passage**, dose **3 mm** (`EVENING_COOLING_MM`). En canicule, la marge de séchage de 90 min ne s'applique plus (le timing au coucher la remplace). Post-application et rafraîchissement du soir sont des **arrosages techniques exemptés des cooldowns**, avec garde « une seule fois par soir ». Correctif : la fenêtre du soir (coucher−30 → coucher) est désormais bien lue par le coordinateur via `evening_cooling_debug` (la clé `watering_evening_*_minute` se perdait dans la chaîne → blocage à tort vers 21 h).
- **Suivi temps réel corrigé (`sensor.py`)** : `live_surplus_mm` / `live_reserve_mm` n'étaient plus alimentés pendant l'arrosage (mauvaise source de lecture) — corrigé.
- **Corrections de bugs** :
  - **`assistant.py`** : lisait une clé inexistante (`reason_decision` au lieu de `raison_decision`) → lignes mortes retirées (l'assistant utilisait déjà le bon texte de repli).
  - **`intervention_recommendation.py`** : comparaison du type de produit fiabilisée (insensible à la casse, ex. « Agent Mouillant ») ; une réserve sol réellement **0 mm** n'est plus ignorée à tort au profit du bilan glissant (**+3 tests**).
  - **`binary_sensor.py`** : défaut `auto_irrigation_enabled` rendu cohérent (inconnu = activé, plus de divergence absent/None).
- **Libellés de blocage unifiés (`const.py`, `sensor.py`, `binary_sensor.py`)** : les libellés (`BLOCK_REASON_DISPLAY_LABELS`) sont désormais **partagés** par les deux plateformes — fini les divergences (joli d'un côté, brut `snake_case` de l'autre) ; ajout du libellé « Robot en erreur » côté binary_sensor.
- **Hauteur de coupe générique (`number.py`)** : les bornes du `number` hauteur de coupe ne sont plus codées en dur (0-100 mm) mais **dérivées des réglages Hauteur min/max tondeuse** (ex. 3-6 cm → curseur 30-60 mm) → s'adapte à n'importe quelle tondeuse.
- **Référentiel arrosage simplifié (`watering_policy.py`)** : le garde météo « light » du Biostimulant était une **copie exacte** de celui de la Fertilisation → fusionné (comportement inchangé) ; champs de garde-fous jamais câblés retirés.
- **Grand nettoyage interne (audit complet)** : ~50 éléments de **code mort** retirés (imports/variables inutilisés, une feature « MAD » jamais branchée, doublons, branches no-op) — **sans changement de comportement**, vérifié par les tests. Rapport dans `AUDIT.md`.
- **README repensé** : sommaire, section « Fonctionnalités » claire, fenêtre de tonte documentée, service `recalibrate_reserve` ajouté ; l'historique des versions vit maintenant dans ce `CHANGELOG.md`.

## 0.14.0
Rafraîchissement du soir découplé du déficit : le cycle du soir refroidit le gazon même réserve saine (526 tests verts) :
- **Rafraîchissement du soir (`guidance.py`)** : le cycle du soir vise désormais le **refroidissement**, pas la recharge. En **canicule ou chaleur extrême**, un petit arrosage (`EVENING_COOLING_MM = 5 mm`) part entre **18 h et 20 h même quand la réserve est saine** : il court-circuite volontairement le garde-fou « pas d'arrosage du soir en saison de végétation », le cooldown 24 h et le plafond hebdomadaire — mais **jamais** une vraie pluie. Avant, ce garde-fou saison était évalué **avant** la branche canicule, donc le rafraîchissement n'était jamais atteint dès que le bilan sol dépassait −3 mm (réserve saine = pas de cooling, même en pleine chaleur).
- **Déclenchement sur canicule ET extrême** : le soir, la chaleur redescend souvent d'« extrême » à « canicule » — exiger « extrême » au moment du soir ne se serait quasiment jamais déclenché. Garde-fous anti-maladies **inchangés** : fin **≥ 90 min avant le coucher du soleil réel** (`sun.sun`), **air sec (humidité ≤ 60 %)**, **aucun risque fongique** ; la saturation du sol n'empêche pas ce léger arrosage d'évaporation.
- **Anti-boucle (`coordinator.py`)** : la fenêtre du soir n'est **plus exemptée du cooldown de relance** (ce qui empêche le rafraîchissement de se relancer en boucle dans la fenêtre 18-20 h) ; comme l'écart matin→soir dépasse 6 h, le premier cycle du soir passe toujours. Le soir est en revanche **exempté** de la garde « eau déjà appliquée aujourd'hui » (son objet n'est pas de combler un déficit). Le snapshot relaie la fenêtre « soir » décidée par le profil d'arrosage (seul à recevoir le coucher du soleil).
- **+7 tests** (rafraîchissement réserve saine, cas canicule, hors fenêtre, coucher trop proche, pluie imminente, anti-boucle de relance, lancement du soir après le cycle du matin).

## 0.13.5
Correctif majeur de comptage : la réserve et le budget ne sous-estiment plus les cycles multi-passages (518 tests verts) :
- **`water.py` (`_watering_item_mm`)** : les mm d'un arrosage étaient calculés en faisant la **moyenne de la liste `zones`**. Or pour un cycle **multi-passages**, cette liste contient une entrée par **passage × zone** → la moyenne renvoyait la dose d'**un seul passage** au lieu du cumul du cycle (**sous-comptage ≈ ×nombre de passages**). Exemple réel : un cycle de **5,2 mm en 3 passages n'était crédité que ~1,7 mm**.
- **Conséquences corrigées** : la **réserve hydrique restait coincée** (ne remontait jamais, affichée « Critique » à tort) et le **budget hebdomadaire était sous-estimé**. Désormais le comptage utilise en priorité le **total surface canonique** (`total_mm` / `session_total_mm`, déjà calculé correctement à l'enregistrement) ; la dérivation depuis `zones` n'est plus qu'un repli pour les records sans total. +2 tests de régression.

## 0.13.4
Cadence d'arrosage maîtrisée : fin des relances en boucle (516 tests verts) :
- **Cooldown anti-relance** : après la fin d'un cycle d'arrosage **auto**, aucun nouveau gros cycle ne peut repartir avant **6 h** (`AUTO_IRRIGATION_RELAUNCH_COOLDOWN`). Corrige le **sur-arrosage** observé en canicule, où le déclencheur relançait un cycle ~10 s après la fin du précédent (la garde existante était purement **volumétrique** — elle se rouvrait dès que l'objectif recalculé remontait). La **fenêtre du soir** (petit rafraîchissement canicule) en est **exemptée** et garde sa propre logique.
- **Fiable et persistant** : le cooldown s'appuie sur la **fin du dernier cycle (état runtime persisté)**, pas sur l'historique écrit en différé → correct même juste après la clôture du cycle, et conservé au redémarrage. La survie canicule respecte désormais ce cooldown. Nouveau motif de blocage `relaunch_cooldown`. +4 tests.

## 0.13.3
Suivi d'arrosage en temps réel, zone par zone (512 tests verts) :
- **Comptage live** : pendant un cycle, le capteur `arrosage_en_cours` expose désormais `zone_mm_applied` (mm **par zone** : segments terminés + segment en cours = durée écoulée × débit), `surface_mm_applied`, `total_mm_applied`, `target_mm`, ainsi que la **réserve/surplus projetés** (`live_reserve_mm`, `live_surplus_mm`) intégrant l'eau en cours d'application. Logique isolée dans la fonction pure `compute_live_session_water` (`water.py`), testable hors Home Assistant.
- **Affichage seulement** : aucun changement du comportement d'arrosage à ce stade — c'est la 1ʳᵉ étape (visibilité + vérification) avant de brancher ce crédit live dans les décisions (cooldown/réserve). +4 tests.

## 0.13.2
Correctif : fin du double-comptage d'arrosage en fin de cycle auto (508 tests verts) :
- **`coordinator.py`** : à la fin d'un cycle piloté, le OFF du **dernier passage** arrivait une fraction de seconde **après** la levée de la garde anti-doublon (course entre le `finally` qui décrémente la garde et la livraison de l'événement d'état). Le moniteur passif rattrapait ce OFF traînant, reconstruisait le passage via son `last_changed` et le **réenregistrait en `zone_session` doublon** — sur-créditant la réserve et le budget hebdomadaire (et faussant l'affichage). Le correctif 0.10.2 avait supprimé le doublon **entre** les passages ; celui-ci supprime le dernier doublon résiduel, **en fin de cycle**. Désormais tout OFF dont le segment a **démarré pendant la fenêtre gelée** (≤ instant de reprise du moniteur) est ignoré ; un arrosage manuel/externe postérieur reste tracé normalement. +2 tests anti-régression.

## 0.13.1
Correctif : une pluie de trace ne bloque plus l'arrosage (506 tests verts) :
- **`decision_watering.py`** : une 2ᵉ logique pluie (« rain floor », distincte de `_rain_signals`) réduisait l'arrosage **dès la moindre pluie prévue (> 0 mm, même 0,8 mm à J+2)**. Quand l'objectif était déjà plafonné (garde-fou hebdomadaire), la réduction le faisait passer **sous la dose minimale → blocage total « pluie prévue suffisante »**, laissant le sol à sec en pleine canicule. Désormais la réduction/le report ne s'applique que pour une **pluie réellement significative** (≥ 2 mm demain, ≥ 4 mm à J+2, ou ≥ 4 mm de cumul sur 3 jours). +1 test anti-régression.

## 0.13.0
Gestion canicule (survie + rafraîchissement du soir) et correctif pluie (505 tests verts) :
- **Pluie « trace » ne bloque plus l'arrosage** : une forte probabilité de pluie ne met l'arrosage en pause que si le **cumul prévu sur 3 jours est ≥ 4 mm**. Avant, ~0,8 mm annoncés à 80-100 % déclenchaient un faux « pluie prévue suffisante » et laissaient le sol à sec.
- **Survie canicule** : quand la réserve est **≥ 90 % épuisée ET** qu'on est en **canicule/chaleur extrême** (et qu'il ne pleut pas vraiment / sol non gorgé), un **petit cycle de survie** (dose minimale) est autorisé **le matin malgré le garde-fou hebdomadaire** — laisser le gazon à 0 mm en pleine canicule dépasse le « stress bénéfique ». Auto-limité (dose mini, espacé par le cooldown 24 h).
- **Rafraîchissement du soir en chaleur extrême** : un petit arrosage du soir pour faire baisser la température du gazon est désormais possible, **uniquement si l'herbe peut sécher avant la nuit** — fin **≥ 90 min avant le coucher du soleil réel** (`sun.sun`), air assez sec (humidité ≤ 60 %) et aucun risque fongique. Si le coucher est inconnu ou trop proche → on s'abstient (priorité au séchage pour éviter les maladies fongiques).

## 0.12.2
Affichage honnête du plafonnement hebdomadaire (497 tests verts) :
- **Garde-fou hebdomadaire** : quand le budget d'arrosage de la semaine est atteint **alors que le sol a réellement besoin d'eau** (réserve sous le seuil MAD), le capteur d'arrosage affiche désormais le statut **« bloqué »** avec « Arrosage plafonné cette semaine (garde-fou hebdomadaire) » au lieu de « Aucun arrosage nécessaire » (qui masquait le vrai motif, notamment en canicule). Quand il n'y a réellement aucun besoin, le message « Aucun arrosage nécessaire » est conservé (pas d'alarme inutile).

## 0.12.1
Cohérence carte ↔ intégration : l'audit croisé a révélé que la carte Lovelace attendait des données non exposées par l'intégration (496 tests verts) :
- **Motif de blocage arrosage** : l'entité `fenetre_optimale` expose désormais aussi `block_reason_label` (libellé prêt à afficher), comme `prochain_arrosage` — la carte n'a plus à re-formater localement (et affiche enfin proprement « pluie prévue suffisante », « garde-fou hebdomadaire », etc.).
- **Libellés de blocage complétés** : `application_foliaire`, `temperature_trop_basse_germination`, `semis_cycle_daily_target_reached`, `semis_cycle_pending` ont désormais un libellé dédié (au lieu d'un texte brut).
- **Sélection de produit** : l'entité `select` du produit d'intervention expose les valeurs **brutes** `selected_product_months` / `selected_product_usage_mode` / `selected_product_max_applications_per_year` (en plus des libellés), consommées par la carte (omises quand vides).

## 0.12.0
Lot de correctifs issus d'un audit complet — sécurité runtime, cohérence, propreté (493 tests verts) :
- **Sécurité runtime** : plus de session « fantôme » bloquant tout arrosage après un redémarrage en plein cycle ; la reprise après redémarrage **respecte le verrou de sécurité** (ne ré-arrose pas après un incident de vanne) ; timer de finalisation de session annulé proprement à l'arrêt ; les 5 plateformes d'entités ne plantent plus si le coordinator n'est pas encore prêt.
- **Arrosage** : en **déplétion critique** (réserve ≥ 80 % épuisée), l'arrosage peut désormais outrepasser le cooldown 24 h pour éviter un stress sévère (les blocages pluie / sol détrempé restent prioritaires).
- **Cohérence / Home Assistant** : le capteur `arrosage_auto_blocage` signale `bloque=True` sur un motif inconnu (ne laisse plus croire à tort que l'arrosage est opérationnel) ; un **changement de capteur dans les options recharge** automatiquement l'intégration (pas de reload sur un simple réglage de débit/hauteur) ; les **services sont dé-enregistrés** à la désinstallation de la dernière instance.
- **Propreté** : retrait de l'attribut trompeur `resume_requires_full_battery` (jamais appliqué) ; avertissements de log sur valeurs pluie/arrosage aberrantes clampées ; suppression de code mort ; commentaires corrigés (le bilan sol soustrait l'ET0, documenté).

## 0.11.0
Nouveau service de calibration manuelle de la réserve hydrique du sol (492 tests verts) :
- **Calibration** : nouveau service `gazon_intelligent.recalibrate_reserve` (cible + champ `reserve_mm`) qui **fixe la réserve hydrique du sol à une valeur connue**. Utile pour recaler la réserve après un écart (ex. un ancien arrosage mal compté avant le correctif 0.10.2), ou pour calibrer au premier démarrage. Le recalage est **persistant** (survit au redémarrage) grâce à une entrée « ancre » que le bilan sol ne recalcule pas. **Note** : la valeur est figée pour le reste de la journée du recalage (pluie / arrosage / ETc du jour ignorés ce jour-là) ; l'évolution normale reprend dès le lendemain — à appeler de préférence le soir, hors pluie ou arrosage important.

## 0.10.2
Correction d'un double-comptage des arrosages pilotés (réserve et budget hebdo sur-crédités) (488 tests verts) :
- **Arrosage** : pendant un cycle d'arrosage piloté par l'intégration (auto ou manuel), le **moniteur passif** de sessions (qui surveille l'état des vannes) enregistrait un doublon `zone_session` **à chaque pause inter-passage** — en plus de l'enregistrement du cycle lui-même. Le garde-fou prévu pour ça (`_zone_tracking_suspended`) était **déclaré et testé mais jamais armé** (code mort). Conséquence : l'arrosage du jour était **sur-compté** (ex. 14,8 mm pour ~11 mm réellement délivrés), ce qui **sur-créditait la réserve hydrique et le budget hebdomadaire** → l'intégration croyait le sol plus arrosé qu'il ne l'était et **retardait l'arrosage suivant** (tendance au sous-arrosage). Le garde-fou est désormais **armé pendant tout le cycle** (passages + pauses) dans `_execute_canonical_watering_plan` ; les arrosages réellement externes/manuels (vanne ouverte hors intégration) restent enregistrés normalement. Les éventuels doublons déjà inscrits s'effacent d'eux-mêmes en sortant de la fenêtre de 7 jours glissants.

## 0.10.1
Capteur de blocage d'arrosage : affiche le vrai motif au lieu de « réserve suffisante » (487 tests verts) :
- **Diagnostic** : le capteur `arrosage_auto_blocage` indiquait « Aucun besoin — réserve hydrique suffisante » dès que l'objectif était à 0, **y compris quand l'objectif était à 0 à cause d'un blocage** (cooldown 24 h, pluie prévue, sol déjà humide, conditions trop humides, garde-fou hebdomadaire) alors que la réserve pouvait être basse — message trompeur. Désormais, quand l'objectif est nul **à cause d'un blocage de décision**, le capteur remonte le **vrai motif** (« Repos après arrosage », « Pluie prévue suffisante », « Sol déjà humide », « Conditions trop humides », « Budget hebdo atteint ») avec un `pourquoi` et un `comment_debloquer` fidèles. Le cas réellement « aucun besoin » (réserve au-dessus du seuil, sans blocage) reste « Aucun besoin ». **Correctif d'affichage uniquement — aucun impact sur le comportement d'arrosage.**

## 0.10.0
Pilotage de l'arrosage par épuisement de la réserve en mode Normal, pour un arrosage profond et espacé (485 tests verts) :
- **Arrosage** : en mode Normal (pelouse établie), l'arrosage est désormais piloté par l'**épuisement de la réserve utile** plutôt que par le déficit cumulé. Le gazon n'est plus arrosé tant que la réserve reste au-dessus du **seuil MAD (50 %)** ; une fois ce seuil atteint, une **recharge profonde** ramène la réserve au plein utile (jamais au-delà), bornée par le garde-fou hebdomadaire et le cooldown. Résultat : arrosages **plus espacés et plus profonds** (favorisant l'enracinement, avec un léger stress bénéfique) au lieu de petits apports fréquents. La logique de dépletion (implémentée mais désactivée jusqu'ici) est **réactivée uniquement en phase Normal ET quand le bilan sol interne fournit une réserve réelle** (`reserve_from_soil_ledger`, alimenté par le ledger `soil_balance.py` tenu par l'intégration) ; sinon repli automatique sur le modèle déficit (legacy, inchangé), utile au tout premier cycle avant que le bilan sol soit établi.
- **Anti-régression** : la dépletion reste **exclue de la phase Sursemis** (recharge profonde inadaptée au semis — cause historique de la surestimation qui avait fait désactiver la logique), désormais verrouillée par un test dédié. Les autres phases (`_profile_for_sursemis`, agro…) sont inchangées.
- **Observabilité** : le drapeau `use_depletion_logic` reflète l'état réel (Normal + réserve interne), et `reserve_from_soil_ledger` distingue la réserve réelle du repli dérivé du bilan court.

## 0.9.5
Déblocage de l'arrosage automatique (qui ne se déclenchait jamais) + diagnostic (481 tests verts) :
- **Arrosage** : corrige un bug où l'arrosage **automatique ne se déclenchait jamais**. La garde de démarrage `startup_guard` (qui empêche d'agir pendant le boot de HA quand les capteurs sont encore `unavailable`) n'était **jamais levée** : le flag `auto_irrigation_bootstrap_complete` était lu mais écrit nulle part → `_should_launch_auto_irrigation` retournait toujours `(False, "startup_guard")`. Le flag est désormais armé au **premier cycle de données sain** (température + objectif présents), et reste volatil (se réarme à chaque redémarrage, pour ne pas agir avant que les capteurs soient prêts).
- **Arrosage** : le verrou de sécurité `safety_lock` — qui s'arme quand une vanne ne se confirme pas fermée en fin d'arrosage et bloque tout arrosage auto — n'avait **aucun moyen d'être levé** (latence définitive). Le bouton **« Retour au mode normal »** (et le service `reset_mode`) le lèvent désormais.
- **Diagnostic** : nouveau capteur `sensor.gazon_intelligent_arrosage_auto_blocage` qui indique **explicitement pourquoi l'arrosage auto ne part pas** (état lisible) et, en attributs, `bloque` (action requise ou non), `pourquoi` et `comment_debloquer`.

## 0.9.4
Libellé d'erreur tondeuse précis pour la carte, compatible toutes tondeuses HA (474 tests verts) :
- **Tonte** : quand la tonte est bloquée parce que le robot est en faute (lame bloquée, soulevé, défaut…), l'intégration expose désormais un libellé précis « **Robot en erreur : …** » (au lieu de « hors ligne » ou d'un libellé générique). La détection est posée dans la résolution de `machine_unavailable_label` (`decision_mowing` + le fallback de `sensor`), prioritaire sur les autres motifs machine. Elle s'appuie sur l'**état standard `error` du domaine `lawn_mower`** (mappé en statut « erreur ») → **compatible avec n'importe quelle tondeuse Home Assistant**, le capteur d'erreur dédié (enum Husqvarna…) n'ajoutant que la précision du texte. Garde anti faux positif : les sentinelles `no_error`/`none`/`ok`/`aucune` ne déclenchent jamais le libellé. Aucun nouvel attribut public (réutilise `machine_unavailable_label` / `machine_unavailable_detail`) ; la carte affiche le nouveau libellé automatiquement.

## 0.9.3
Arrosage technique post-application limité au jour même de l'épandage (472 tests verts) :
- **Interventions** : l'arrosage technique d'incorporation après une application au sol (conseil, override d'objectif, arrosage auto, blocage tonte associé) ne se déclenche désormais que si le produit a été appliqué **le jour même**. Pour une application plus ancienne — ex. déclarée rétroactivement à J-4 — l'incorporation est présumée faite : ni conseil, ni override, ni objectif mm, et le coordinator refuse tout lancement. La règle est posée **à la source** (`compute_application_state`) en comparant la date d'application au `today` de la **décision** (et non à l'horloge murale `dt_util.now()`), ce qui éteint conseil + override + arrosage + capteur d'un seul point ; tous les appelants du chemin de décision (`build_water_bundle`, mowing, `compute_memory`) propagent ce `today`. Le comportement du cas « jour même » reste strictement inchangé.

## 0.9.2
Correction de la surestimation de l'ET0 sans capteur (470 tests verts) :
- **Hydrique** : le calcul Penman-Monteith de secours (sans capteur ETP dédié) surestimait l'ET0 d'un facteur ~1,5-2 — ~8 mm/jour à 20 °C au lieu de ~5 —, ce qui vidait artificiellement la réserve hydrique et déclenchait des arrosages inutiles. Deux causes corrigées dans `compute_etp` : (1) le rayonnement net grandes longueurs d'onde `Rnl` était approximé à ~0,7 MJ/m²/j (≈7× trop bas), gonflant le rayonnement net `Rn` — remplacé par la formule FAO-56 (Stefan-Boltzmann pondérée par l'humidité et la couverture nuageuse) ; (2) le vent des entités météo HA, fourni en km/h, était utilisé tel quel comme des m/s dans le terme aérodynamique (~3,6× trop) — désormais converti selon l'unité réelle (`weather_wind_speed_unit`). Résultat : 20 °C ciel clair → ~5,4 mm, couvert → ~2,4 mm, vraie canicule 35 °C → reste élevé. Le calcul fonctionne correctement **même sans capteur ETP** ; le capteur dédié reste prioritaire s'il est configuré.

## 0.9.1
Cohérence conseil/exécution de l'arrosage sous pluie + fix de progression terminale (467 tests verts) :
- **Arrosage** : la réduction de dose liée à la pluie annoncée est désormais propagée aux valeurs réellement exécutées. En mode Normal avec pluie prévue, le moteur calculait bien une dose réduite (×0.8, ou ×0.4 si pluie compensatrice) mais ne l'écrivait que dans le texte `action_recommandee` : `objectif_mm` / `mm_final` / `mm_applied` restaient à la dose pleine. Résultat en production : conseil « Réduis l'apport à 6.1 mm » pendant que le plan canonique et le scheduler arrosaient 7.6 mm. Conseil et exécution sont maintenant alignés sur la même valeur.
- **Arrosage** : plancher de session utile. Si la dose réduite par la pluie tombe sous `min_session_mm` (5.0 mm en Normal), l'objectif bascule à 0 au lieu de publier une dose agronomiquement inutile, et l'arrosage n'est plus marqué « recommandé ».
- **Arrosage** : ce blocage par la pluie porte désormais un motif explicite (`block_reason = "pluie_prevue_suffisante"`), affiché en « Motif exact » dans `raison_decision` — cohérent avec les autres motifs de blocage du système (plus de « bloqué » muet).
- **Arrosage** : corrige le libellé obsolète « seuil utile minimal 10 mm » de `raison_decision` (la valeur effective est 5.0 mm depuis le passage de `min_session_mm` à la politique), remplacé par « déclenché sur déficit utile » (texte neutre, sans valeur codée en dur).
- **Phases** : corrige la progression de sous-phase terminale bloquée à ~1 %. Dans `compute_subphase`, la sentinelle `999` de la dernière règle de `SUBPHASE_RULES` était prise pour une durée réelle (dénominateur ~965 jours pour la Stabilisation d'un Sursemis). La sous-phase terminale est désormais bornée par `PHASE_DURATIONS_DAYS` quand `0 < durée < 999`. Exemple : Stabilisation d'un Sursemis de 45 j au jour 44 → ~85 % au lieu de ~1 %. L'Hivernage (durée `999`) reste volontairement ouvert.

## 0.9.0
Nettoyage et déduplication suite à l'audit des domaines (aucun changement de comportement, 462 tests verts) :
- **Tonte** : restructure la cascade de résolution du motif de blocage (`raison_code`) en `if/elif` à priorité explicite (phase agronomique > post-application > arrosage en cours > cooldown > blocage générique), au lieu du motif fragile « affecter puis écraser ». Ajoute un test verrouillant la priorité phase > arrosage.
- **Météo** : supprime 7 clés mortes du résumé de prévisions (`forecast_condition_*`, `forecast_date_*`, `forecast_days`) qui étaient calculées mais jamais consommées par la décision ou les capteurs.
- **Interventions** : factorise 2 blocs « unavailable » quasi-identiques (~120 lignes) dans `_build_unavailable_response()`. Unifie les 3 branches dupliquées de `_temperature_evaluation()` et supprime le champ `band` jamais lu (105 → 38 lignes).
- **Arrosage** : extrait `_hydraulic_pressure()` pour dédupliquer le calcul `besoin_court`/`besoin_tendance`/`pression_hydrique` présent à deux endroits de `guidance.py`.
- **Tonte** : fusionne le double bloc « nuit » et supprime un bloc de candidats Sursemis/Traitement/Hivernage inatteignable (déjà couvert par les retours anticipés).

## 0.8.9
- Corrige l'incohérence `arrosage_recent_3j > arrosage_recent_7j` : quand `recent_watering_mm_override` ne s'appliquait qu'à la fenêtre 7 jours alors que la fenêtre 3 jours était calculée depuis l'historique, on pouvait afficher un cumul 3j supérieur au cumul 7j. La monotonie `jour ≤ 3j ≤ 7j` est désormais garantie (une fenêtre plus large ne peut contenir moins d'eau qu'une fenêtre incluse).
- Supprime le champ `bilan_hydrique_precedent_mm` (mal nommé : c'était une réserve, pas un bilan) qui faisait doublon avec `sol_reserve_precedente_mm`. Le capteur `objectif_d_arrosage` expose désormais uniquement `sol_reserve_precedente_mm`.
- Documente explicitement `mm_cible_depletion` / `objective_from_depletion_mm` comme champs diagnostic-only (capteur `objectif_depletion`), non câblés dans la décision tant que `use_depletion_logic` est `False`.

## 0.8.8
- Corrige la surestimation de l'objectif d'arrosage en phase Normal quand le sol n'est pas encore au seuil MAD : `mm_cible` est désormais plafonné à la capacité d'absorption restante du sol (`reserve_stock_max_mm - reserve_stock_mm`). Exemple : sol à 70 % de remplissage → objectif réduit de 23.1 mm à 7.3 mm au lieu d'arroser au-delà de ce que le sol peut absorber.

## 0.8.7
- Supprime le paramètre `temperature` inutilisé (code mort) dans `compute_dominant_phase()` et `compute_phase_active()` dans `phases.py`, ainsi que dans tous les appelants (tests inclus).
- Rend `compute_subphase()` robuste à un ordre incorrect des règles dans `SUBPHASE_RULES` : tri défensif par limite croissante au moment du calcul.

## 0.8.6
- Corrige `sensor.gazon_intelligent_hauteur_gazon_estimee` qui restait `unknown` malgré une tonte déclarée : `gazon_hauteur_estimee_cm` était calculé dans `mowing_bundle` mais n'était jamais transféré dans `result.extra` dans `_build_decision_extra`. Même correctif pour `mowing_is_overdue`, `mowing_overdue_days`, `mowing_overdue_factor` qui souffraient du même oubli.

## 0.8.5
- Corrige `declare_mowing` : le champ `hauteur_coupe_mm` était rejeté par le schéma voluptuous du service (« extra keys not allowed ») car il n'avait pas été ajouté au schéma de validation dans `__init__.py`. Le champ est maintenant accepté (float, 10–120 mm).

## 0.8.4
- Corrige `sensor.gazon_intelligent_hauteur_gazon_estimee` qui restait "Inconnu" après `declare_mowing` quand la tondeuse est hors ligne et que `number.gazon_intelligent_hauteur_coupe_tondeuse` n'avait jamais été configuré : la valeur par défaut de l'entité passe de `None` à `50 mm`, ce qui garantit un calcul d'estimation fonctionnel dès l'installation sans configuration supplémentaire.

## 0.8.3
- Améliore l'estimation de la hauteur du gazon (`sensor.gazon_intelligent_hauteur_gazon_estimee`) : `declare_mowing` stocke désormais la hauteur de coupe effective au moment de la tonte (`hauteur_coupe_mm`) dans l'historique. `_estimated_grass_height_cm` préfère cette valeur sur la hauteur courante de la tondeuse, ce qui rend l'estimation fiable même si la tondeuse est hors ligne ou si la hauteur de coupe a changé depuis la dernière tonte.
- Le coordinateur capture automatiquement `tondeuse_hauteur_coupe_mm` au moment de `declare_mowing` si aucune hauteur n'est fournie explicitement.
- Expose `hauteur_coupe_mm` comme champ optionnel du service `declare_mowing` pour permettre aux automatisations (ex. Node-RED) de passer la hauteur de coupe lors de la déclaration.

## 0.8.2
- Corrige un bug où la tonte restait bloquée (`gazon_permet_tonte: false`) après expiration du délai de ressuyage post-arrosage : `_select_mowing_block_reason` vérifiait `arrosage_recent_jour > 0.5` de façon permanente (sur 7 jours) avec le label hardcodé "attendre 24 h", court-circuitant le ressuyage dynamique déjà expiré. Supprime ce bloc redondant — `_watering_related_mowing_block` est désormais l'unique autorité sur les blocages post-arrosage.

## 0.8.1
- Corrige la sémantique des attributs hydriques exposés par les capteurs HA :
  - `bilan_hydrique_mm` représente désormais le **bilan ET0 journalier** (négatif = déficit du jour, positif = surplus).
  - `reserve_hydrique_sol_mm` est le nouveau champ dédié à la **réserve réelle stockée dans le sol**.
  - Supprime `bilan_hydrique_journalier_mm` (doublon de `bilan_hydrique_mm` avant cette correction).
  - Supprime les 5 alias legacy (`reserve_utile_max_mm`, `reserve_utile_actuelle_mm`, `reserve_totale_sol_mm`, `reserve_totale_sol_max_mm`, `surplus_hydrique_mm`).
  - Renomme `soil_balance_previous_reserve_mm` → `sol_reserve_precedente_mm` et `soil_balance_delta_mm` → `sol_delta_mm`.
- Met à jour `intervention_recommendation.py` pour utiliser `reserve_hydrique_sol_mm` (seuils de réserve réelle) plutôt que le bilan journalier pour évaluer l'excédent/équilibre hydrique.

## 0.8.0
- Ajoute la détection de retard de tonte (`mowing_is_overdue`, `mowing_overdue_days`, `mowing_overdue_factor`) avec un soft override sur les conditions borderline (`conditions_defavorables`, `stress_thermique`) pour ne pas bloquer indéfiniment une tonte urgente.
- Ajoute l'estimation de la hauteur du gazon sans capteur physique (`sensor.gazon_intelligent_hauteur_gazon_estimee`) calculée depuis la date et hauteur de dernière coupe et le taux de croissance mensuel.
- Remplace les littéraux hardcodés dans la fenêtre de tonte par les constantes de seuil existantes.
- Clarifie les messages de blocage de fenêtre horaire : le motif agronomique est conservé et la raison horaire lui est annexée, plutôt que remplacée.
- Ajoute la coordination arrosage/tonte : bloque la tonte si l'arrosage est imminent (< 30 min), la décourage si prévu dans < 2 h.
- Remplace le délai de ressuyage post-arrosage fixe (24 h) par un calcul dynamique selon le type de sol : 1 h (sableux), 2 h (limoneux), 4 h (argileux), avec ajustements humidité, pluie et température. Le message indique le temps restant précis.

## 0.7.3
- Corrige `strings.json` pour remettre les clés de sélecteurs au format attendu par Hassfest.
- Restaure une publication GitHub propre après l'échec de validation de `0.7.0`.
- Aucun changement de logique métier runtime.

## 0.7.0
- Refonte majeure du moteur tonte / arrosage et de la façade publique de l'intégration.
- Clarifie la hiérarchie entre phase, météo, humidité, machine et action réellement possible.
- Renforce le support multi-pelouse avec `instance_slug`, une meilleure isolation par gazon et des entités publiques plus stables.
- Ajoute une couche de coordination tondeuse structurée avec états machine normalisés et meilleure distinction entre gazon, machine et exécution.
- Revoit les projections publiques `prochain_arrosage`, `prochaine_tonte`, `assistant` et les capteurs de synthèse pour Home Assistant.
- Rend les libellés publics plus compréhensibles pour la pluie, les attentes météo, les blocages post-produit et les phases sensibles comme `Sursemis`.
- Étend les traductions, les services, la documentation et la couverture de tests pour accompagner la refonte.

## 0.6.1
- Corrections de publication sans changement du moteur métier.
- Correction du workflow Hassfest.
- Correction d'erreurs mypy dans la couche de structure.
- Aucun changement de logique runtime publique.

## 0.5.0
- Stabilise les `entity_id` publics de l'intégration et ajoute une migration pour réaligner le registre Home Assistant.
- Renforce fortement le moteur d'irrigation, la structuration des plans d'arrosage et le suivi runtime des sessions et des zones.
- Améliore la recommandation d'intervention avec un meilleur filtrage par score, opportunité, contexte produit et debug métier.
- Rend les capteurs de synthèse plus utiles et plus cohérents pour Home Assistant, les dashboards et les automatisations.
- Étend nettement la couverture de tests sur les entités, la mémoire, les chaînes de résultat et le suivi d'arrosage.

## 0.4.6
- Aligne la façade `sensor.gazon_intelligent_assistant` avec le comportement réel et les nouveaux attributs publics.
- Ajoute `next_action_date` et `next_action_display` pour rendre la prochaine action estimée plus lisible dans Home Assistant.
- Consolide les diagnostics intégrés et la cohérence des libellés public-facing autour de la décision d'arrosage.
- Clarifie la documentation pour refléter l'état actuel du moteur, des entités et des services exposés.

## 0.4.5
- Ajoute une projection de reprise de tonte avec `next_mowing_date` et `next_mowing_display`.
- Structure les attributs visibles pour mieux séparer décision, exécution, plan calculé et session détectée.
- Nettoie les libellés UI et les champs exposés pour supprimer les doublons et clarifier les automatisations.

## 0.4.4
- Finalise la V2 du moteur d'arrosage avec une observabilité renforcée.
- Harmonise les libellés UI, les traductions et la documentation autour du profil d'arrosage, du cycle calculé et des sessions détectées.
- Conserve la compatibilité Home Assistant sans nouvelle entité obligatoire.

## 0.4.3
- Finalise la V2 du moteur d'arrosage avec une observabilité renforcée.
- Ajoute un score de confiance, un stress thermique détaillé et un garde-fou hebdomadaire dynamique.
- Clarifie le résumé hydrique et la traçabilité des blocages dans les décisions.
- Conserve la compatibilité Home Assistant sans nouvelle entité obligatoire.

## 0.4.2
- Nettoie le moteur interne en supprimant du code mort et des helpers devenus redondants.
- Stabilise le calcul et le déclenchement de l'arrosage automatique avec des gardes métier plus lisibles.
- Simplifie les docs utilisateur en retirant le blueprint historique au profit du flux interne de l'intégration.
- Clarifie le README et les entités exposées pour refléter l'état réel de la release.

## 0.4.1
- Clarifie l'UX des boutons et des capteurs affichés dans Home Assistant.
- Ajoute un résumé lisible du plan d'arrosage et supprime les valeurs vides ambiguës.
- Conserve l'automatisme comme source de vérité tout en simplifiant l'action manuelle visible.

## 0.4.0
- Bump de version pour la nouvelle release.

## 0.3.28
- Expose des valeurs explicites pour les capteurs d'arrosage quand aucune donnée réelle n'est encore disponible.
- Ajoute des attributs hydriques lisibles sur l'objectif d'arrosage pour faciliter le debug dans Home Assistant.
- Améliore la lisibilité des états `Plan d'arrosage` et `Dernier arrosage détecté`.

## 0.3.27
- Bump de version pour la nouvelle release.

## 0.3.26
- Expose la hauteur de tonte conseillée comme entité dédiée et exploitable dans Home Assistant.
- Simplifie et stabilise les réglages de hauteur de tondeuse avec une logique générique et arrondie au pas réel.
- Renforce la cohérence des messages utilisateur et la lisibilité des décisions métier.

## 0.3.23
- Bump de version pour la nouvelle release.

## 0.3.20
- Ajout de l'attribut `possible_values` sur certaines entités métier pour aider à comprendre les valeurs possibles dans Home Assistant.

## 0.3.18
- Version bump to `0.3.18`.

## 0.3.17
- Corrige le crash au premier chargement du `config_flow` quand `current` vaut `None`.
- Sécurise le rendu initial du formulaire de configuration pour éviter l'erreur `500` sur une première installation.
- Ajoute une couverture de test dédiée pour le premier affichage du flux de configuration.

## 0.3.16
- Remet la configuration initiale sur les zones, les débits et le type de sol.
- Déplace l'entité `weather` et les capteurs météo complémentaires dans les options avancées.
- Exploite l'entité `weather` comme source de secours pour la pluie, la température, l'humidité, le vent et l'ETP.
- Reconstruit l'arrosage réel à partir des changements d'état des zones.
- Simplifie l'UI et aligne le README, les traductions et les calculs internes sur la même structure.
- Simplifie l'automatisation d'arrosage de l'époque et clarifie l'expérience utilisateur.

## 0.3.13
- Corrige le bouton `Date action = aujourd'hui` pour enregistrer une date même sans intervention déjà présente.
- Harmonise le `Mode expert` avec le device commun de l'intégration.
- Durcit l'automatisation d'arrosage historique pour ignorer les capteurs `unknown` / `unavailable` et éviter les déclenchements sur objectif nul.
- Ajoute des notifications persistantes quand cette automatisation historique bloque volontairement l'arrosage ou n'exécute aucune branche.
- Nettoie le README et ajoute `tests/__init__.py` pour rendre la découverte automatique des tests fonctionnelle.

## 0.3.11
- Extraction du moteur de décision dans un module pur pour le rendre testable sans Home Assistant.
- Ajout d'une base de tests unitaires sur les règles métier principales.
- Nettoyage du coordinateur pour le recentrer sur l'orchestration HA.
- Alignement des libellés README / entités et ajout de `single_config_entry` au manifest.

## 0.3.10
- Refonte du moteur de décision avec scores internes (`score_hydrique`, `score_stress`, `score_tonte`).
- Calcul d'arrosage recentré sur bilan hydrique + scores, avec profils par phase.
- Conseils rendus contextuels (météo, stress, humidité, pluie J+1, phase).
- Ajout des capteurs `Bilan hydrique`, `Score hydrique` et `Score stress gazon`.
- Correction d'une incohérence dans `services.yaml` (doublon `Hivernage`).
- Refonte complète du README et amélioration de la lisibilité.

## 0.3.9
- Ajoute un moteur décisionnel V1 basé sur l'historique, la météo, le type de sol et la phase dominante.
- Ajoute l'historique persistant des actions (interventions, tonte, arrosage).
- Ajoute les services `declare_intervention`, `declare_mowing`, `declare_watering`.
- Ajoute des capteurs de décision/conseil (`phase active`, `raison`, `conseil`, `niveau_action`, `fenetre_optimale`, `risque_gazon`, etc.).
- Ajoute les binaires `arrosage auto autorisé` et `arrosage recommandé`.
- Empêche les lancements concurrents de `start_auto_irrigation`.
- Annule proprement l'arrosage auto en cours au déchargement de l'intégration.
- Harmonise les unités de débit en `mm/h` dans les textes (conversion interne en `mm/min`).
- Aligne `set_date_action` en optionnel dans la documentation service.
- Met `integration_type` à `hub`.
- Supprime le binaire `Arrosage automatique autorisé` devenu inutile.
- Nettoie le calcul interne `arrosage_auto_autorise` associé.
- Rend la conversion capteurs plus tolérante (`12,3` accepté en float).
- Force l'extinction de chaque zone en mode bloquant pour une séquence plus fiable.
- Retourne une erreur explicite si aucune zone/débit valide n'est configurée.
- Ajoute le paramètre `type de sol` (`sableux` / `limoneux` / `argileux`) pour ajuster l'objectif.
- Utilise la pluie prévue demain pour réduire ou annuler automatiquement l'objectif du jour.
- Ajoute une entité météo `weather` optionnelle pour récupérer automatiquement la pluie J+1 via `weather.get_forecasts` si `capteur_pluie_demain` n'est pas configuré.

## 0.3.7
- Persistance du mode et de la date d'action entre redémarrages.
- Service `set_date_action` : date optionnelle (par défaut aujourd'hui).
- Clean imports mineurs.
- Gestion d'erreurs améliorée pour `set_date_action`.
- Capteur arrosage simplifié : valeurs `auto` ou `personnalise` uniquement.

## 0.3.6
- Remplace le binaire spécial par un capteur texte "Arrosage conseillé" (auto / personnalise / interdit).

## 0.3.5
- Binaire "Arrosage modes spéciaux" pour Sursemis, Fertilisation, Biostimulant, Agent Mouillant, Scarification.

## 0.3.4
- Tonte autorisée uniquement en Normal; arrosage interdit en Traitement/Hivernage.

## 0.3.3
- Ajout du logo/icon pour HACS.

## 0.3.2
- Ajuste l'objectif du mode Normal à 8.3 mm (3 arrosages/sem ~25 mm/sem).

## 0.3.1
- Objectif mode Normal relevé à 3.5 mm/j (≈25 mm/sem).
- Ajout bouton `Date action = aujourd'hui`.
- Corrections d'UX (options avec valeurs vides sûres).

## 0.3.0
- Débits zones saisis en mm/h (conversion interne mm/min).
- Options flow : modification des entités après installation.
- Clarifications pluie J+1, humidité extérieure.

## 0.2.0
- Intégration HA 2026.3.x, device info, unique_id.
- Ajout arrosage auto séquentiel, services bornés.
- ETP estimée si pas de capteur.
- Extension à 5 zones.

## 0.1.0
- Version initiale.
