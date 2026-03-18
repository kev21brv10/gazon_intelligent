# Gazon Intelligent

Version `0.3.15`

Gazon Intelligent est une intégration Home Assistant pour piloter un gazon de manière simple et autonome.
Elle analyse la météo, l'arrosage, les phases du gazon et l'historique des actions, puis propose une décision claire:
quoi faire, quand le faire, pourquoi, et quoi éviter.

L'objectif est simple:
- vous laisser un écran lisible
- garder la logique complexe dans le moteur
- fonctionner avec ou sans capteurs avancés

## Ce que fait l'intégration

- calcule un bilan hydrique persistant
- adapte les conseils selon la phase du gazon
- prend en compte la météo du jour et de demain
- mémorise les arrosages, tontes et interventions
- gère un catalogue local de produits personnalisés
- garde l'interface Home Assistant simple pour l'utilisateur

## Ce que vous voyez dans Home Assistant

### Entités principales

- `Mode du gazon`
- `Phase dominante`
- `Sous-phase`
- `Conseil principal`
- `Action recommandée`
- `Action à éviter`
- `Niveau d'action`
- `Fenêtre optimale`
- `Risque gazon`
- `État de tonte`
- `Tonte autorisée`
- `Arrosage recommandé`
- `Objectif d'arrosage`
- `Type d'arrosage`

### Boutons utiles

- `Retour au mode normal`
- `Noter la date du jour`

Les détails techniques restent dans les attributs et la mémoire interne pour éviter de charger l'écran principal.

## Installation

### Via HACS

1. Ouvrez HACS.
2. Ajoutez ce dépôt dans les intégrations personnalisées.
3. Installez **Gazon Intelligent**.
4. Redémarrez Home Assistant.
5. Ajoutez l'intégration depuis `Paramètres > Appareils et services`.

### Manuelle

1. Copiez `custom_components/gazon_intelligent` dans `config/custom_components`.
2. Redémarrez Home Assistant.
3. Ajoutez l'intégration depuis `Paramètres > Appareils et services`.

## Configuration

L'intégration se configure via formulaire.

### Configuration principale

- `zone_1` à `zone_5`
- `debit_zone_1` à `debit_zone_5`
- `type_sol`

### Options avancées

- `entite_meteo`
- `capteur_pluie_24h`
- `capteur_pluie_demain`
- `capteur_temperature`
- `capteur_etp`
- `capteur_humidite`
- `capteur_humidite_sol`
- `capteur_hauteur_gazon`
- `capteur_vent`
- `capteur_rosee`
- `capteur_retour_arrosage`

Règles simples:
- si un capteur météo est vide, l'entité `weather` prend le relais
- si `capteur_etp` est vide, l'ETP est estimée automatiquement
- si `capteur_retour_arrosage` est vide, l'historique de la journée sert de secours

## Utilisation au quotidien

Vous n'avez pas besoin de comprendre les calculs.

Chaque jour, regardez surtout:
- `Conseil principal`
- `Action recommandée`
- `Action à éviter`
- `État de tonte`
- `Arrosage recommandé`

Ensuite:
- si l'intégration dit d'arroser, lancez l'action proposée
- si elle dit d'attendre, laissez passer
- si elle dit de ne pas tondre, attendez la prochaine fenêtre

## Actions avancées

### Services

- `gazon_intelligent.set_mode`
- `gazon_intelligent.set_date_action`
- `gazon_intelligent.reset_mode`
- `gazon_intelligent.start_manual_irrigation`
- `gazon_intelligent.start_auto_irrigation`
- `gazon_intelligent.declare_intervention`
- `gazon_intelligent.declare_mowing`
- `gazon_intelligent.declare_watering`
- `gazon_intelligent.register_product`
- `gazon_intelligent.remove_product`

### Produits personnalisés

Le plus simple est:

1. enregistrer un produit une seule fois avec `register_product`
2. déclarer ensuite l'intervention réelle avec `declare_intervention`
3. fournir `produit_id` seulement si vous voulez une réapplication plus précise

Si vous ne connaissez pas le produit exact:
- le mode suffit
- les règles par défaut du mode continuent de fonctionner

## Ce que le système automatise

- le bilan hydrique
- la comparaison pluie / arrosage / ETP
- la phase active et la sous-phase
- la décision arrosage / tonte
- la mémoire des dernières actions
- la prochaine réapplication d'un produit

## Ce que vous devez faire au minimum

- renseigner les zones
- renseigner les débits
- choisir le type de sol
- renseigner l'entité météo

Le reste peut rester vide si vous n'avez pas de capteurs avancés.

## Blueprint

Un blueprint d'arrosage intelligent est inclus:

- `blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml`

## Fichiers utiles

- `custom_components/gazon_intelligent/manifest.json`
- `custom_components/gazon_intelligent/config_flow.py`
- `custom_components/gazon_intelligent/coordinator.py`
- `custom_components/gazon_intelligent/gazon_brain.py`
- `custom_components/gazon_intelligent/decision.py`
- `custom_components/gazon_intelligent/water.py`
- `custom_components/gazon_intelligent/soil_balance.py`

## Version

- `manifest.json`: `0.3.15`
- `README.md`: `0.3.15`
- `CHANGELOG.md`: `0.3.15`
