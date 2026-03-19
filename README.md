# 🌱 Gazon Intelligent

Version `0.3.26`

> Un système autonome qui décide pour ton gazon à ta place.

Gazon Intelligent est une intégration Home Assistant qui transforme les données du jardin en décisions simples et actionnables.

Elle analyse la météo, l’arrosage, le type de sol, les phases du gazon et l’historique des actions, puis te dit clairement :
- quoi faire
- quand le faire
- pourquoi
- quoi éviter

Cette intégration nécessite Home Assistant `2026.3.2` ou plus récent.

Le but est simple :
- garder un écran lisible
- automatiser le raisonnement
- fonctionner avec ou sans capteurs avancés

---

## ✨ Ce que fait l’intégration

- calcule les décisions d’arrosage et de tonte
- adapte le comportement selon la phase du gazon
- prend en compte la météo du jour et du lendemain
- mémorise les interventions réelles
- gère les produits personnalisés localement
- garde l’interface Home Assistant simple au quotidien

---

## 👀 Ce que tu vois dans Home Assistant

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
- `Hauteur de tonte conseillée`
- `Tonte autorisée`
- `Arrosage recommandé`
- `Objectif d'arrosage`
- `Type d'arrosage`

### Tonte

L'entité `État de tonte` expose aussi une recommandation de hauteur de coupe adaptée à ta tondeuse :

- `hauteur_tonte_recommandee_cm`
- `hauteur_tonte_min_cm`
- `hauteur_tonte_max_cm`

L'entité `Hauteur de tonte conseillée` affiche directement la hauteur recommandée, avec les détails utiles en attributs.

Le moteur calcule cette hauteur pour rester compatible avec la machine configurée et avec l'état réel du gazon.

Les réglages de tondeuse sont aussi disponibles dans Home Assistant:

- `Hauteur min tondeuse`
- `Hauteur max tondeuse`

### Boutons

- `Retour au mode normal`
- `Noter la date du jour`

👉 Les détails techniques restent internes pour ne pas surcharger l’écran.

---

## 🚀 Installation

### Via HACS

1. Ajoute ce dépôt dans HACS (catégorie **Integration**)
2. Installe **Gazon Intelligent**
3. Redémarre Home Assistant
4. Ajoute l’intégration

### Manuelle

1. Copie `custom_components/gazon_intelligent` dans `config/custom_components`
2. Redémarre Home Assistant
3. Ajoute l’intégration

---

## ⚙️ Configuration

Aucune configuration YAML obligatoire.

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
- `hauteur_min_tondeuse_cm`
- `hauteur_max_tondeuse_cm`

Règles simples :
- si un capteur est vide → la météo prend le relais
- si `capteur_etp` est vide → estimation automatique
- si `capteur_retour_arrosage` est vide → historique du jour utilisé
- si la tondeuse est configurée → le moteur propose une hauteur de coupe recommandée
- le pas de réglage de la tondeuse est géré automatiquement par l'intégration

---

## 🧭 Utilisation au quotidien

Le fonctionnement est volontairement simple :

1. Home Assistant calcule
2. Tu regardes
3. Tu agis

À consulter en priorité :
- `Conseil principal`
- `Action recommandée`
- `Action à éviter`
- `État de tonte`
- `Arrosage recommandé`
- `hauteur_tonte_recommandee_cm` dans `État de tonte`

👉 Tu ne calcules rien. Tu suis.

---

### Exemple concret

Le matin, Home Assistant peut afficher :

- `Phase dominante` = `Sursemis`
- `Conseil principal` = `Arroser demain matin en 2 passages courts`
- `Action recommandée` = `Appliquer 1.1 mm fractionnés`
- `État de tonte` = `interdite`

Dans ce cas :
- tu ne réfléchis pas
- tu appliques
- le système s’ajuste seul ensuite

---

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

---

### Produits personnalisés

Flux recommandé :

1. enregistrer un produit (`register_product`)
2. déclarer l’intervention (`declare_intervention`)
3. utiliser `produit_id` uniquement si nécessaire

👉 Si tu ne sais pas :
- utilise le mode
- laisse le moteur décider

---

## 🤖 Ce que le système automatise

- bilan hydrique complet
- comparaison pluie / arrosage / ETP
- phase active et sous-phase
- décision arrosage / tonte
- mémoire des actions
- réapplication des produits

---

## ✅ Ce que tu dois faire

- configurer les zones
- renseigner les débits
- choisir le type de sol
- définir la météo

👉 Le reste est optionnel.

---

## 📦 Blueprint

Un blueprint est inclus pour automatiser l’arrosage en fonction du mode du gazon.

- `blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml`

[![Importer le blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/kev21brv10/gazon_intelligent/blob/main/blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml)

---

### À quoi il sert

- déclencher l’arrosage automatiquement
- bloquer selon le mode (`Traitement`, `Hivernage`, etc.)
- adapter le volume selon l’objectif calculé

---

### Comment l’utiliser

1. sélectionner `Mode du gazon`
2. sélectionner `Objectif d’arrosage`
3. configurer les horaires
4. activer

---

### Limites

- ne remplace pas le moteur de décision
- dépend des capteurs disponibles
- reste volontairement simple

---

## 🔧 Fichiers utiles

- `manifest.json`
- `config_flow.py`
- `coordinator.py`
- `gazon_brain.py`
- `decision.py`
- `water.py`
- `soil_balance.py`

---

## 🧾 Version

- `manifest.json`: `0.3.26`
- `README.md`: `0.3.26`
- `CHANGELOG.md`: `0.3.26`
