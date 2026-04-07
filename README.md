# 🌱 Gazon Intelligent

<p align="center">
  <img src="https://raw.githubusercontent.com/kev21brv10/gazon_intelligent/main/logo.png" width="120">
</p>

![Version](https://img.shields.io/github/v/release/kev21brv10/gazon_intelligent?color=green)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3.2+-blue)
![License](https://img.shields.io/github/license/kev21brv10/gazon_intelligent?style=flat-square)

> Gazon Intelligent analyse ton gazon à ta place et te dit quoi faire, quand le faire et combien appliquer, directement dans Home Assistant.

> Une seule décision claire à la fois, avec le contexte utile quand tu veux aller plus loin.

---

## En 15 secondes

- une seule intégration, un seul moteur métier
- une entité principale très lisible : `sensor.gazon_intelligent_assistant`
- des entités complémentaires pour comprendre le contexte sans alourdir l’usage quotidien

Tu veux savoir quoi faire sur ton gazon ? L’intégration te donne directement l’action utile et le bon moment, avec la quantité seulement quand elle compte.

👉 Commence ici : [Démarrage rapide](#-démarrage-rapide)

---

## Pourquoi c’est différent

Gazon Intelligent n’est pas juste une collection de capteurs.

Il ne se contente pas d’afficher des données :

- il prend une décision à partir de la météo, de l’arrosage réel, de la phase du gazon et de l’historique
- il évite les actions inutiles ou mal synchronisées
- il remonte une seule action claire à la fois
- il garde les détails utiles dans des entités complémentaires, sans perdre la lisibilité du résultat principal

En clair : le produit ne te montre pas seulement l’état du gazon, il t’aide à décider.

---

## 👀 À regarder en premier

### `sensor.gazon_intelligent_assistant`

C’est l’entité centrale de l’intégration.
Elle remonte l’action prioritaire et le bon moment pour agir. Quand il n’y a rien à faire, elle l’indique explicitement.

---

## 🚀 Démarrage rapide

1. Installe l’intégration `gazon_intelligent`
2. Ajoute l’intégration dans Home Assistant
3. Renseigne le config flow : zones utilisées, débits d’arrosage et type de sol
4. Consulte `sensor.gazon_intelligent_assistant`
5. Ouvre `sensor.gazon_intelligent_conseil_principal`, `sensor.gazon_intelligent_fenetre_optimale` et `sensor.gazon_intelligent_objectif_d_arrosage` si tu veux plus de contexte

👉 En quelques secondes, tu sais si une action est utile, quand l’exécuter et si un arrosage doit être quantifié.

---

## 📦 Installation

### Via HACS (recommandé)

1. Ouvre **HACS → Intégrations → Menu → Dépôts personnalisés**
2. Ajoute le dépôt `https://github.com/kev21brv10/gazon_intelligent`
3. Choisis la catégorie **Intégration**
4. Installe `Gazon Intelligent`
5. Redémarre Home Assistant
6. Va dans **Paramètres → Appareils et services → Ajouter une intégration**
7. Recherche `Gazon Intelligent`

### Installation manuelle

1. Copie `custom_components/gazon_intelligent` dans `config/custom_components`
2. Redémarre Home Assistant
3. Va dans **Paramètres → Appareils et services → Ajouter une intégration**
4. Recherche `Gazon Intelligent`

### Compatibilité

- Home Assistant `2026.3.2+`
- installation recommandée via HACS

---

## ⚙️ Configuration

Aucune configuration YAML obligatoire.

### Configuration principale

Lors du config flow, renseigne au minimum :

- `zone_1` à `zone_5`
- `debit_zone_1` à `debit_zone_5`
- `type_sol`

### Options avancées

- `entite_meteo` : météo principale obligatoire
- `capteur_pluie_24h` : pluie locale 24h, prioritaire si fournie
- `capteur_pluie_demain` : pluie locale demain, prioritaire si fournie
- `capteur_temperature` : température locale, prioritaire si fournie
- `capteur_etp` : ETP du jour, calcul automatique si non renseigné
- `capteur_humidite` : humidité locale, prioritaire si fournie
- `capteur_humidite_sol`
- `capteur_hauteur_gazon`
- `capteur_vent` : vent local, prioritaire si fourni
- `capteur_rosee`
- `capteur_retour_arrosage`
- `hauteur_min_tondeuse_cm`
- `hauteur_max_tondeuse_cm`

### Règles de fonctionnement

- capteur absent → fallback météo
- ETP absent → estimation automatique
- retour arrosage absent ou à `0.0` → historique du jour
- tondeuse configurée → recommandation active

---

## 🧩 Carte Lovelace optionnelle

Une carte Lovelace dédiée peut être utilisée pour une interface plus lisible :

- `lovelace-gazon-intelligent-card`

L’intégration fonctionne seule avec ses entités natives.
La carte lit simplement les entités publiques et les met en forme pour l’interface.

---

## 🧭 Utilisation simple

Au quotidien, le principe est simple :

1. l’intégration calcule la décision
2. tu lis `sensor.gazon_intelligent_assistant`
3. tu ouvres les entités de contexte seulement si tu veux confirmer ou approfondir

### À consulter en priorité

- `sensor.gazon_intelligent_conseil_principal`
- `sensor.gazon_intelligent_fenetre_optimale`
- `sensor.gazon_intelligent_objectif_d_arrosage`

### Lecture rapide

- si `assistant = aucune_action`, il n’y a rien à faire
- si `fenetre_optimale = attendre`, le moteur réévalue plus tard
- si `objectif_d_arrosage > 0`, un arrosage est potentiellement utile
- si `tonte_autorisee = off`, la tonte est bloquée pour une bonne raison

---

## 👀 Entités

Avant de parcourir toute la liste :

1. regarde `sensor.gazon_intelligent_assistant`
2. vérifie `sensor.gazon_intelligent_conseil_principal`
3. ouvre `sensor.gazon_intelligent_fenetre_optimale` si une action est proposée
4. regarde `sensor.gazon_intelligent_objectif_d_arrosage` si l’action concerne l’irrigation

### Entités essentielles

- `sensor.gazon_intelligent_assistant`
- `sensor.gazon_intelligent_conseil_principal`
- `sensor.gazon_intelligent_fenetre_optimale`
- `sensor.gazon_intelligent_objectif_d_arrosage`

### Entités avancées

- `sensor.gazon_intelligent_plan_d_arrosage`
- `sensor.gazon_intelligent_niveau_d_action`
- `sensor.gazon_intelligent_type_d_arrosage`
- `sensor.gazon_intelligent_phase_dominante`
- `sensor.gazon_intelligent_sous_phase`
- `sensor.gazon_intelligent_risque_gazon`
- `sensor.gazon_intelligent_etat_de_tonte`
- `sensor.gazon_intelligent_hauteur_de_tonte_conseillee`
- `sensor.gazon_intelligent_dernier_arrosage_detecte`
- `sensor.gazon_intelligent_derniere_application`
- `sensor.gazon_intelligent_derniere_action_utilisateur`
- `sensor.gazon_intelligent_catalogue_produits`
- `binary_sensor.gazon_intelligent_arrosage_recommande`
- `binary_sensor.gazon_intelligent_tonte_autorisee`
- `binary_sensor.gazon_intelligent_arrosage_apres_application_autorise`

### Entités d’action

- `button.gazon_intelligent_arroser_maintenant`
- `button.gazon_intelligent_date_action_today`
- `button.gazon_intelligent_retour_mode_normal`
- `switch.gazon_intelligent_arrosage_automatique_autorise`
- `select.gazon_intelligent_mode_du_gazon`

### Diagnostic

- diagnostics téléchargeables via l’intégration
- logs du module `custom_components.gazon_intelligent`

---

## 🛠️ Services exposés

### Services métier principaux

- `gazon_intelligent.set_mode`
- `gazon_intelligent.reset_mode`
- `gazon_intelligent.set_date_action`
- `gazon_intelligent.start_auto_irrigation`
- `gazon_intelligent.start_manual_irrigation`
- `gazon_intelligent.start_application_irrigation`

### Services d’intervention et de mémoire

- `gazon_intelligent.declare_intervention`
- `gazon_intelligent.remove_last_application`
- `gazon_intelligent.declare_mowing`
- `gazon_intelligent.declare_watering`
- `gazon_intelligent.register_product`
- `gazon_intelligent.remove_product`

Notes :

- `set_mode` et `reset_mode` pilotent le mode du gazon
- `set_date_action` enregistre la date métier réelle
- `start_manual_irrigation` lance un arrosage manuel contrôlé à partir d’un objectif explicite
- `start_auto_irrigation` exécute le cycle calculé ou un objectif fourni, sans contourner les garde-fous
- `declare_intervention` reste le point d’entrée principal pour les interventions
- tous les réglages produit se trouvent dans `register_product`

---

## 📘 Approfondir

Cette partie est volontairement plus avancée.
Elle sert à comprendre le moteur sans alourdir le démarrage.

### Tonte

L’intégration expose :

- l’état de tonte
- la hauteur de tonte conseillée
- les limites min / max de la machine

### Arrosage

Le moteur essaie de produire une décision exploitable et réaliste :

- matin prioritaire quand c’est possible
- fréquence plus légère en Sursemis
- arrosage plus profond en mode Normal
- blocage si pluie importante ou contrainte applicative
- fractionnement si un seul passage serait trop important

### Produits et applications

Tu peux enregistrer un produit une seule fois, puis réutiliser ses réglages via :

1. `gazon_intelligent.register_product`
2. `select.gazon_intelligent_produit_d_intervention`
3. `gazon_intelligent.declare_intervention`

---

## ❤️ Support

Si le projet t’aide :

- ⭐ Mets une étoile
- 🐛 Remonte les bugs
- 💡 Propose des idées

---

## 🛠️ Développement local

Pour lancer la suite de tests :

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests
```

---

## 🧾 Version

- manifest : `0.5.1`
- README : `0.5.1`
- changelog : `0.5.1`

---

## 📄 Licence

Ce projet est sous licence MIT.
