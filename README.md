# Gazon Intelligent

<p align="center">
  <img src="https://raw.githubusercontent.com/kev21brv10/gazon_intelligent/main/logo.png" width="120" alt="Logo Gazon Intelligent">
</p>

<p align="center">
  <strong>Une intégration Home Assistant orientée décision métier pour le gazon.</strong><br>
  Arrosage, tonte, phases, interventions produit et coordination optionnelle avec un robot tondeuse.
</p>

<p align="center">
  <img src="https://img.shields.io/github/v/release/kev21brv10/gazon_intelligent?color=2f9e44" alt="Version">
  <img src="https://img.shields.io/badge/HACS-Custom-f57c00" alt="HACS">
  <img src="https://img.shields.io/badge/Home%20Assistant-2026.3.2+-1e88e5" alt="Home Assistant">
  <img src="https://img.shields.io/github/license/kev21brv10/gazon_intelligent" alt="License">
</p>

## Pourquoi cette intégration

Gazon Intelligent ne se contente pas d’allumer des zones d’arrosage ou de remonter quelques capteurs.

L’intégration construit une lecture métier exploitable dans Home Assistant:

- que faut-il faire maintenant
- pourquoi faut-il agir ou attendre
- quand reconsidérer la tonte ou l’arrosage
- quel contexte explique la décision

Elle est conçue pour rester lisible côté UI, tout en gardant assez de structure pour les automatisations, le debug et les dashboards avancés.

## Ce que la version actuelle apporte

- une instance par pelouse, avec support multi-gazon propre
- une façade publique centrée sur `sensor.gazon_intelligent_assistant`
- une projection claire de:
  - `sensor.gazon_intelligent_prochain_arrosage`
  - `sensor.gazon_intelligent_prochaine_tonte`
  - `sensor.gazon_intelligent_prochaine_intervention`
- une séparation explicite entre:
  - état du gazon
  - décision d’arrosage
  - décision de tonte
  - disponibilité machine
  - action réellement possible
- une coordination tondeuse activable ou désactivable par pelouse
- une carte Lovelace dédiée en complément de l’intégration

## Philosophie

L’intégration sépare trois niveaux:

1. **Le gazon**
   - phase dominante
   - sous-phase
   - risque
   - réserve hydrique

2. **La décision métier**
   - tonte autorisée ou non
   - arrosage utile ou non
   - prochaine fenêtre
   - blocage ou attente

3. **L’exécution**
   - machine disponible ou non
   - coordination tondeuse active ou non
   - action réellement possible

Cette séparation évite les faux signaux du type:

- gazon autorisé mais machine indisponible
- machine prête mais tonte interdite par la phase
- arrosage bloqué sans explication lisible

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

1. Copie [`custom_components/gazon_intelligent`](/Users/kevin/vs%20code/Github/Gazon%20Intelligent/custom_components/gazon_intelligent) dans `config/custom_components`
2. Redémarre Home Assistant
3. Ajoute l’intégration depuis **Paramètres → Appareils et services**

## Compatibilité

- Home Assistant `2026.3.2+`
- installation recommandée via HACS

## Configuration

Aucune configuration YAML n’est requise.

### 1. Une configuration par pelouse

Chaque instance demande:

- `instance_slug`
- `zone_1` à `zone_5`
- `debit_zone_1` à `debit_zone_5`
- `type_sol`

`instance_slug` permet de séparer proprement plusieurs pelouses dans Home Assistant.

### 2. Météo et capteurs complémentaires

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

### 3. Robot tondeuse optionnel

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

Si la coordination tondeuse est désactivée, l’intégration continue de calculer la logique gazon, mais ne considère plus la machine comme pilotable.

## Les entités à lire en premier

### Assistant

- `sensor.gazon_intelligent_assistant`

C’est le point d’entrée le plus utile.  
Il résume l’action prioritaire ou la raison pour laquelle il faut attendre.

### Arrosage

- `sensor.gazon_intelligent_prochain_arrosage`
- `sensor.gazon_intelligent_fenetre_optimale`
- `sensor.gazon_intelligent_plan_d_arrosage`
- `sensor.gazon_intelligent_objectif_d_arrosage`
- `binary_sensor.gazon_intelligent_arrosage_recommande`
- `binary_sensor.gazon_intelligent_signal_irrigation`
- `binary_sensor.gazon_intelligent_arrosage_apres_application_autorise`

### Tonte

- `binary_sensor.gazon_intelligent_tonte_autorisee`
- `sensor.gazon_intelligent_etat_de_tonte`
- `sensor.gazon_intelligent_prochaine_tonte`
- `sensor.gazon_intelligent_hauteur_de_tonte_conseillee`

Attributs utiles côté tonte:

- `gazon_permet_tonte`
- `machine_permet_tonte`
- `action_possible`
- `mowing_block_reason_code`
- `mowing_block_reason_label`

### Phase et contexte

- `sensor.gazon_intelligent_phase_dominante`
- `sensor.gazon_intelligent_sous_phase`
- `sensor.gazon_intelligent_risque_gazon`
- `sensor.gazon_intelligent_type_d_arrosage`

### Interventions produit

- `sensor.gazon_intelligent_prochaine_intervention`
- `sensor.gazon_intelligent_catalogue_produits`
- `sensor.gazon_intelligent_debug_intervention`
- `sensor.gazon_intelligent_niveau_de_pertinence`
- `binary_sensor.gazon_intelligent_signal_intervention`
- `select.gazon_intelligent_produit_d_intervention`

## Comment lire la décision

### Arrosage

`sensor.gazon_intelligent_prochain_arrosage` est la lecture publique la plus directe.

Exemples:

- `Bloqué` + `Attendre après la pluie`
- `Non requis` + `Aucun arrosage nécessaire`
- fenêtre utile le matin avec objectif calculé

### Tonte

`binary_sensor.gazon_intelligent_tonte_autorisee` exprime l’autorisation métier.

Mais l’action finale dépend aussi de la machine:

- gazon autorisé
- machine prête ou non
- coordination active ou non

`sensor.gazon_intelligent_prochaine_tonte` donne la prochaine reprise lisible.

### Phases sensibles

Certaines phases dominent naturellement la lecture publique:

- `Sursemis`
- `Traitement`
- `Hivernage`
- `Scarification`

Exemple attendu:

- `Phase Sursemis: tonte interdite pendant l'installation du gazon.`

## Entités de réglage et d’action

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

### Pilotage métier

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

Elle organise la lecture en onglets:

- synthèse
- irrigation
- tonte
- gazon
- produits
- intervention
- réglages

La carte ne remplace pas l’intégration.  
Elle lit les entités publiques et les structure pour une lecture rapide dans Home Assistant.

## Ce que l’intégration ne prétend pas faire

- elle ne remplace pas ton matériel d’arrosage
- elle ne remplace pas les sécurités natives de ta tondeuse
- elle ne garantit pas seule un déclenchement automatique sans automatisations autour

Son rôle est de fournir une base métier cohérente, lisible et exploitable.

## Développement

Le dépôt inclut:

- workflow de validation GitHub Actions
- Hassfest
- Ruff
- mypy
- tests unitaires

La logique principale est concentrée autour de:

- [`custom_components/gazon_intelligent/coordinator.py`](/Users/kevin/vs%20code/Github/Gazon%20Intelligent/custom_components/gazon_intelligent/coordinator.py)
- [`custom_components/gazon_intelligent/decision_watering.py`](/Users/kevin/vs%20code/Github/Gazon%20Intelligent/custom_components/gazon_intelligent/decision_watering.py)
- [`custom_components/gazon_intelligent/decision_mowing.py`](/Users/kevin/vs%20code/Github/Gazon%20Intelligent/custom_components/gazon_intelligent/decision_mowing.py)
- [`custom_components/gazon_intelligent/assistant.py`](/Users/kevin/vs%20code/Github/Gazon%20Intelligent/custom_components/gazon_intelligent/assistant.py)

## Licence

Projet publié sous licence MIT. Voir [`LICENSE`](https://github.com/kev21brv10/gazon_intelligent/blob/main/LICENSE).
