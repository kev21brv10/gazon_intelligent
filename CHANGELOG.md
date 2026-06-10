# Changelog

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
