# 🌱 Gazon Intelligent

Version `0.3.15`

Gazon Intelligent est une intégration Home Assistant qui transforme les infos du jardin en décisions simples et actionnables.
Elle regarde la météo, l'arrosage, le type de sol, les phases du gazon et l'historique des actions, puis dit clairement:
- quoi faire
- quand le faire
- pourquoi
- quoi éviter

Le but est simple:
- vous laisser un écran lisible
- automatiser le raisonnement
- fonctionner avec ou sans capteurs avancés

## ✨ Ce que fait l'intégration

- calcule la décision d'arrosage et de tonte
- adapte le comportement selon la phase du gazon
- prend la météo du jour et de demain en compte
- mémorise les interventions réelles
- gère les produits personnalisés localement
- garde l'interface Home Assistant simple au quotidien

## 👀 Ce que vous voyez dans Home Assistant

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

### Boutons

- `Retour au mode normal`
- `Noter la date du jour`

👉 Les détails techniques restent internes pour éviter de surcharger l'écran principal.

## 🚀 Installation

### Via HACS

1. Ajoutez ce dépôt dans HACS, catégorie **Integration**.
2. Installez **Gazon Intelligent**.
3. Redémarrez Home Assistant.
4. Ajoutez l'intégration depuis `Paramètres > Appareils et services`.

### Manuelle

1. Copiez `custom_components/gazon_intelligent` dans `config/custom_components`.
2. Redémarrez Home Assistant.
3. Ajoutez l'intégration depuis `Paramètres > Appareils et services`.

## ⚙️ Configuration

L'intégration se configure via formulaire, sans YAML obligatoire.

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

## 🧭 Utilisation au quotidien

Le fonctionnement normal est très simple:

1. Home Assistant calcule la décision.
2. Vous regardez le conseil principal.
3. Vous lancez l'action proposée si besoin.

À consulter en priorité:
- `Conseil principal`
- `Action recommandée`
- `Action à éviter`
- `État de tonte`
- `Arrosage recommandé`

Exemple:
- si l'intégration dit d'arroser, vous lancez l'action
- si elle dit d'attendre, vous laissez passer
- si elle dit de ne pas tondre, vous reportez la tonte

### Exemple concret

Le matin, Home Assistant peut vous afficher:

- `Phase dominante` = `Sursemis`
- `Conseil principal` = `Arroser demain matin en 2 passages courts`
- `Action recommandée` = `Appliquer 1.1 mm fractionnés`
- `État de tonte` = `interdite`

Dans ce cas:
- vous ne recalculez rien
- vous suivez simplement la consigne
- l'intégration réévaluera la situation au prochain cycle

## 🛠️ Services avancés

### Actions disponibles

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

Le flux recommandé est simple:

1. enregistrez un produit une seule fois avec `register_product`
2. déclarez l'intervention réelle avec `declare_intervention`
3. fournissez `produit_id` seulement si vous voulez un suivi plus précis

Si vous ne connaissez pas le produit exact:
- le mode suffit
- les règles par défaut continuent de fonctionner

## 🤖 Ce que le système automatise

- le bilan hydrique
- la comparaison pluie / arrosage / ETP
- la phase active et la sous-phase
- la décision arrosage / tonte
- la mémoire des dernières actions
- la prochaine réapplication d'un produit

## ✅ Ce que vous devez renseigner au minimum

- les zones
- les débits
- le type de sol
- l'entité météo

Le reste peut rester vide si vous n'avez pas de capteurs avancés.

## 📦 Blueprint

Un blueprint d'arrosage intelligent est inclus pour automatiser les modes spéciaux hors `Normal`.

- `blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml`

### À quoi il sert

- lancer un arrosage automatique quand le mode du gazon l'autorise
- bloquer l'arrosage en `Traitement` et `Hivernage`
- ajuster le volume selon l'objectif calculé, la pluie prévue et l'humidité

### Comment l'utiliser

1. Sélectionnez votre entité `Mode du gazon`.
2. Sélectionnez `Objectif d'arrosage`.
3. Renseignez les capteurs météo si vous les avez.
4. Choisissez les horaires du matin, du midi et du soir.
5. Activez l'automation.

### Limites

- le blueprint ne remplace pas le moteur de décision
- il dépend des capteurs choisis dans Home Assistant
- il reste volontairement simple et ne gère pas tous les cas avancés

## 🔧 Fichiers utiles

- `custom_components/gazon_intelligent/manifest.json`
- `custom_components/gazon_intelligent/config_flow.py`
- `custom_components/gazon_intelligent/coordinator.py`
- `custom_components/gazon_intelligent/gazon_brain.py`
- `custom_components/gazon_intelligent/decision.py`
- `custom_components/gazon_intelligent/water.py`
- `custom_components/gazon_intelligent/soil_balance.py`

## 🧾 Cohérence de version

- `manifest.json`: `0.3.15`
- `README.md`: `0.3.15`
- `CHANGELOG.md`: `0.3.15`
