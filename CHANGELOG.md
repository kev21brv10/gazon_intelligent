# Changelog

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
