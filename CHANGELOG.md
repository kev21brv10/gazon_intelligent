# Changelog

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
