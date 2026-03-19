# Changelog

## 0.3.20
- Ajout de l'attribut `possible_values` sur certaines entités métier pour aider à comprendre les valeurs possibles dans Home Assistant.

## 0.3.18
- Version bump to `0.3.18`.

## 0.3.17
- Corrige le crash au premier chargement du `config_flow` quand `current` vaut `None`.
- Sécurise le rendu initial du formulaire de configuration pour éviter l’erreur `500` sur une première installation.
- Ajoute une couverture de test dédiée pour le premier affichage du flux de configuration.

## 0.3.16
- Remet la configuration initiale sur les zones, les débits et le type de sol.
- Déplace l'entité `weather` et les capteurs météo complémentaires dans les options avancées.
- Exploite l'entité `weather` comme source de secours pour la pluie, la température, l'humidité, le vent et l'ETP.
- Reconstruit l'arrosage réel à partir des changements d'état des zones.
- Simplifie l'UI et aligne le README, les traductions et les calculs internes sur la même structure.
- Simplifie le blueprint d'arrosage et clarifie l'expérience utilisateur.

## 0.3.13
- Corrige le bouton `Date action = aujourd'hui` pour enregistrer une date même sans intervention déjà présente.
- Harmonise le `Mode expert` avec le device commun de l'intégration.
- Durcit le blueprint d'arrosage pour ignorer les capteurs `unknown` / `unavailable` et éviter les déclenchements sur objectif nul.
- Ajoute des notifications persistantes quand le blueprint bloque volontairement l'arrosage ou n'exécute aucune branche.
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
- Remplace le binaire spécial par un capteur texte \"Arrosage conseillé\" (auto / personnalise / interdit).

## 0.3.5
- Binaire \"Arrosage modes spéciaux\" pour Sursemis, Fertilisation, Biostimulant, Agent Mouillant, Scarification.

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
