# Gazon Intelligent

<p align="center">
  <img src="https://raw.githubusercontent.com/kev21brv10/gazon_intelligent/main/logo.png" width="120" alt="Logo Gazon Intelligent">
</p>

![Version](https://img.shields.io/github/v/release/kev21brv10/gazon_intelligent?color=green)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3.2+-blue)
![License](https://img.shields.io/github/license/kev21brv10/gazon_intelligent?style=flat-square)

Intégration Home Assistant pour piloter la décision métier autour du gazon:

- arrosage
- tonte
- phases et sous-phases
- interventions produit
- coordination optionnelle avec une tondeuse

Le moteur remonte une décision publique lisible, puis expose les capteurs de contexte utiles pour comprendre pourquoi.

## Ce que fait la version actuelle

- une instance par pelouse, avec support multi-gazon
- une façade publique centrée sur `sensor.gazon_intelligent_assistant`
- séparation claire entre:
  - état du gazon
  - décision d’arrosage
  - décision de tonte
  - disponibilité machine
- projection lisible de:
  - `sensor.gazon_intelligent_prochain_arrosage`
  - `sensor.gazon_intelligent_prochaine_tonte`
  - `sensor.gazon_intelligent_prochaine_intervention`
- coordination tondeuse activable ou désactivable par instance
- carte Lovelace optionnelle dédiée

## Installation

### Via HACS

1. Ouvre **HACS → Intégrations → Dépôts personnalisés**
2. Ajoute `https://github.com/kev21brv10/gazon_intelligent`
3. Choisis la catégorie **Intégration**
4. Installe `Gazon Intelligent`
5. Redémarre Home Assistant
6. Va dans **Paramètres → Appareils et services**
7. Ajoute l’intégration `Gazon Intelligent`

### Installation manuelle

1. Copie `custom_components/gazon_intelligent` dans `config/custom_components`
2. Redémarre Home Assistant
3. Ajoute l’intégration depuis **Paramètres → Appareils et services**

## Compatibilité

- Home Assistant `2026.3.2+`
- installation recommandée via HACS

## Configuration

Aucune configuration YAML obligatoire.

### Étape 1: base par pelouse

Chaque instance demande:

- `instance_slug`
- `zone_1` à `zone_5`
- `debit_zone_1` à `debit_zone_5`
- `type_sol`

`instance_slug` sert à séparer proprement plusieurs pelouses dans Home Assistant.

### Étape 2: capteurs avancés optionnels

Tu peux ensuite renseigner:

- `entite_meteo`
- `capteur_pluie_24h`
- `capteur_pluie_demain`
- `capteur_temperature`
- `capteur_etp`
- `capteur_humidite`
- `capteur_humidite_sol`
- `capteur_vent`
- `capteur_rosee`
- `capteur_hauteur_gazon`
- `capteur_retour_arrosage`

### Tondeuse optionnelle

La coordination tondeuse est indépendante et configurable par pelouse:

- `entite_tondeuse`
- `capteur_tondeuse_erreur`
- `capteur_tondeuse_batterie`
- `capteur_tondeuse_pluie`
- `capteur_tondeuse_en_charge`
- `capteur_tondeuse_prochain_depart`
- `capteur_tondeuse_hauteur_coupe`
- `hauteur_min_tondeuse_cm`
- `hauteur_max_tondeuse_cm`

Si la coordination tondeuse est désactivée, l’intégration continue de calculer la logique gazon mais ne considère plus la machine comme pilotable.

## À lire en premier

### Décision centrale

- `sensor.gazon_intelligent_assistant`

C’est la façade publique la plus utile. Elle dit ce qu’il faut faire maintenant, ou pourquoi il faut attendre.

### Synthèse métier

- `sensor.gazon_intelligent_conseil_principal`
- `sensor.gazon_intelligent_action_recommandee`
- `sensor.gazon_intelligent_action_a_eviter`
- `sensor.gazon_intelligent_niveau_d_action`

### Arrosage

- `sensor.gazon_intelligent_fenetre_optimale`
- `sensor.gazon_intelligent_prochain_arrosage`
- `sensor.gazon_intelligent_plan_d_arrosage`
- `sensor.gazon_intelligent_objectif_d_arrosage`
- `sensor.gazon_intelligent_arrosage_en_cours`
- `binary_sensor.gazon_intelligent_arrosage_recommande`
- `binary_sensor.gazon_intelligent_signal_irrigation`
- `binary_sensor.gazon_intelligent_arrosage_apres_application_autorise`

### Tonte

- `binary_sensor.gazon_intelligent_tonte_autorisee`
- `sensor.gazon_intelligent_etat_de_tonte`
- `sensor.gazon_intelligent_prochaine_tonte`
- `sensor.gazon_intelligent_hauteur_de_tonte_conseillee`

Attributs importants côté tonte:

- `gazon_permet_tonte`
- `machine_permet_tonte`
- `action_possible`
- `mowing_block_reason_code`
- `mowing_block_reason_label`

### Phase, risque et contexte

- `sensor.gazon_intelligent_phase_dominante`
- `sensor.gazon_intelligent_sous_phase`
- `sensor.gazon_intelligent_risque_gazon`
- `sensor.gazon_intelligent_type_d_arrosage`

### Historique et traçabilité

- `sensor.gazon_intelligent_dernier_arrosage_detecte`
- `sensor.gazon_intelligent_dernier_arrosage_total_zones`
- `sensor.gazon_intelligent_derniere_application`
- `sensor.gazon_intelligent_derniere_action_utilisateur`

### Interventions produit

- `sensor.gazon_intelligent_prochaine_intervention`
- `sensor.gazon_intelligent_catalogue_produits`
- `sensor.gazon_intelligent_debug_intervention`
- `sensor.gazon_intelligent_niveau_de_pertinence`
- `binary_sensor.gazon_intelligent_signal_intervention`
- `select.gazon_intelligent_produit_d_intervention`

## Lecture métier

### Arrosage

- `sensor.gazon_intelligent_prochain_arrosage` donne la prochaine lecture publique d’exécution
- `sensor.gazon_intelligent_fenetre_optimale` garde la logique de fenêtre
- `binary_sensor.gazon_intelligent_signal_irrigation` sert de signal synthétique pour l’UI et les automatisations

### Tonte

- `binary_sensor.gazon_intelligent_tonte_autorisee` exprime l’autorisation métier
- `sensor.gazon_intelligent_etat_de_tonte` donne l’état public tonte
- `sensor.gazon_intelligent_prochaine_tonte` projette la prochaine reprise lisible

`tonte_autorisee` ne veut pas dire que la machine partira maintenant.  
La décision exécutable finale dépend aussi de `machine_permet_tonte` et de `action_possible`.

### Assistant

L’assistant ne remplace pas les capteurs spécialisés:

- il priorise une action
- il simplifie la lecture
- il n’efface pas les couches arrosage, tonte et intervention

## Entités de configuration et d’action

### Boutons

- `button.gazon_intelligent_arroser_maintenant`
- `button.gazon_intelligent_date_action_today`
- `button.gazon_intelligent_retour_mode_normal`

### Switches

- `switch.gazon_intelligent_arrosage_automatique_autorise`
- `switch.gazon_intelligent_coordination_tondeuse`

### Selects

- `select.gazon_intelligent_mode_du_gazon`
- `select.gazon_intelligent_produit_d_intervention`

### Numbers

- `number.gazon_intelligent_debit_zone_1` à `number.gazon_intelligent_debit_zone_5`
- `number.gazon_intelligent_hauteur_min_tondeuse`
- `number.gazon_intelligent_hauteur_max_tondeuse`
- `number.gazon_intelligent_hauteur_coupe_tondeuse`
- `number.gazon_intelligent_delai_reprise_tonte_apres_arrosage`

## Services exposés

### Configuration métier

- `gazon_intelligent.set_mode`
- `gazon_intelligent.reset_mode`
- `gazon_intelligent.set_date_action`

### Irrigation

- `gazon_intelligent.start_manual_irrigation`
- `gazon_intelligent.start_auto_irrigation`
- `gazon_intelligent.start_application_irrigation`
- `gazon_intelligent.declare_watering`

### Tonte

- `gazon_intelligent.declare_mowing`

### Interventions et produits

- `gazon_intelligent.declare_intervention`
- `gazon_intelligent.remove_last_application`
- `gazon_intelligent.register_product`
- `gazon_intelligent.remove_product`

## Carte Lovelace optionnelle

Une carte dédiée existe pour exploiter la façade publique de l’intégration:

- `lovelace-gazon-intelligent-card`

La carte ne remplace pas l’intégration.  
Elle lit les entités publiques et les organise en onglets:

- synthèse
- irrigation
- tonte
- gazon
- produits
- intervention
- réglages

## Diagnostic

- diagnostics téléchargeables via Home Assistant
- logs sur `custom_components.gazon_intelligent`
- capteurs hydriques avancés disponibles pour le debug, notamment:
  - `sensor.gazon_intelligent_et0`
  - `sensor.gazon_intelligent_etc`
  - `sensor.gazon_intelligent_reserve_actuelle`
  - `sensor.gazon_intelligent_depletion_ratio`
  - `sensor.gazon_intelligent_etat_hydrique`
  - `sensor.gazon_intelligent_objectif_legacy`
  - `sensor.gazon_intelligent_objectif_depletion`

## Développement

Le dépôt contient:

- intégration Home Assistant
- tests unitaires
- validation Hassfest
- lint Ruff
- typage mypy

Le workflow GitHub actuellement présent est un workflow de validation.  
La publication de release reste manuelle: bump de version, merge sur `main`, tag GitHub puis release.
