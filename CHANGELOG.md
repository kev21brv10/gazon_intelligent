# Changelog

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
