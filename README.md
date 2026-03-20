# 🌱 Gazon Intelligent

<p align="center">
  <img src="https://raw.githubusercontent.com/kev21brv10/gazon_intelligent/main/logo.png" width="120">
</p>

![Version](https://img.shields.io/github/v/release/kev21brv10/gazon_intelligent?color=green)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3.2+-blue)
![License](https://img.shields.io/github/license/kev21brv10/gazon_intelligent?style=flat-square)

> Un système autonome qui décide pour ton gazon à ta place.

Gazon Intelligent est une intégration Home Assistant qui transforme les données du jardin en décisions simples, claires et directement actionnables.

---

## 🧠 Fonctionnement

Gazon Intelligent analyse en permanence :

- la météo  
- l’arrosage  
- le type de sol  
- les phases du gazon  
- l’historique des actions  

Puis il te donne une seule chose :

👉 **une décision claire**

- quoi faire  
- quand le faire  
- pourquoi  
- quoi éviter  

👉 Tu ne calcules rien. Tu suis.

---

## 🚀 Ce que fait Gazon Intelligent

- 💧 Décide quand arroser (et combien)  
- ✂️ Recommande la hauteur de tonte idéale  
- 🌱 S’adapte aux phases du gazon (sursemis, reprise…)  
- 🌦️ Analyse météo + sol + historique  
- 🧠 Évite les erreurs (tonte trop basse, arrosage inutile…)  
- 📊 Simplifie les décisions dans Home Assistant  

---

## 📸 Aperçu

*(Ajoute ici une capture de ton dashboard Lovelace pour booster l’impact)*

---

## 👀 Ce que tu vois dans Home Assistant

### Entités principales

- Mode du gazon  
- Phase dominante  
- Sous-phase  
- Conseil principal  
- Action recommandée  
- Action à éviter  
- Niveau d'action  
- Fenêtre optimale  
- Risque gazon  
- État de tonte  
- Hauteur de tonte conseillée  
- Tonte autorisée  
- Arrosage recommandé  
- Objectif d'arrosage  
- Type d'arrosage  

---

## ✂️ Gestion de la tonte

L'entité **État de tonte** expose :

- `hauteur_tonte_recommandee_cm`  
- `hauteur_tonte_min_cm`  
- `hauteur_tonte_max_cm`  

L'entité **Hauteur de tonte conseillée** affiche directement la hauteur recommandée.

### ⚙️ Réglages tondeuse

Configurables dans Home Assistant :

- Hauteur min tondeuse  
- Hauteur max tondeuse  

Le système :

- respecte les limites de ta machine  
- applique un pas réel de **0.5 cm**  
- adapte la hauteur selon la saison, la météo et le stress du gazon  

---

## 💧 Gestion de l’arrosage

- calcul du besoin réel en eau  
- prise en compte pluie / ETP / humidité  
- adaptation selon la phase du gazon  
- gestion automatique ou personnalisée  

---

## 🚀 Installation

### Via HACS (recommandé)

1. Ajouter ce dépôt dans HACS (catégorie **Integration**)  
2. Installer **Gazon Intelligent**  
3. Redémarrer Home Assistant  
4. Ajouter l’intégration  

### Installation manuelle

1. Copier `custom_components/gazon_intelligent` dans `config/custom_components`  
2. Redémarrer Home Assistant  
3. Ajouter l’intégration  

### Compatibilité

- Home Assistant ≥ **2026.3.2**

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

### Règles de fonctionnement

- capteur absent → fallback météo  
- ETP absent → estimation automatique  
- retour arrosage absent → historique du jour  
- tondeuse configurée → recommandation active  

---

## 🧭 Utilisation au quotidien

1. Home Assistant calcule  
2. Tu regardes  
3. Tu agis  

### À consulter en priorité

- Conseil principal  
- Action recommandée  
- Action à éviter  
- État de tonte  
- Arrosage recommandé  

👉 Tu ne réfléchis pas. Tu appliques.

---

## 📊 Exemple concret

Le matin :

- Phase dominante = Sursemis  
- Conseil principal = Arroser demain matin en 2 passages courts  
- Action recommandée = Appliquer 1.1 mm fractionnés  
- État de tonte = interdite  

👉 Tu appliques. Le système s’adapte.

---

## 🤖 Ce que le système automatise

- bilan hydrique complet  
- comparaison pluie / arrosage / ETP  
- gestion des phases et sous-phases  
- décisions arrosage / tonte  
- mémoire des actions  
- suivi des interventions  

---

## 🛠️ Services avancés

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

## 🌿 Produits personnalisés

Flux recommandé :

1. `register_product`  
2. `declare_intervention`  

👉 Sinon : laisse le moteur décider.

---

## 📦 Blueprint

👉 Installation en un clic :

[![Importer le blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/kev21brv10/gazon_intelligent/blob/main/blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml)

### À quoi il sert

- déclencher l’arrosage automatiquement  
- bloquer selon le mode (Traitement, Hivernage, etc.)  
- s’appuyer sur le plan d’arrosage calculé par l’intégration
- lancer les zones en séquentiel avec les durées calculées
- laisser l’intégration enregistrer automatiquement la session réelle

---

## ❤️ Support

Si le projet t’aide :

- ⭐ Mets une étoile  
- 🐛 Remonte les bugs  
- 💡 Propose des idées  

---

## 🧾 Version

- manifest : `0.3.26`  
- README : `0.3.26`  
- changelog : `0.3.26`


## 📄 Licence

Ce projet est sous licence MIT.
