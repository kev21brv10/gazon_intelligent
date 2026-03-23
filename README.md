# 🌱 Gazon Intelligent

<p align="center">
  <img src="https://raw.githubusercontent.com/kev21brv10/gazon_intelligent/main/logo.png" width="120">
</p>

![Version](https://img.shields.io/github/v/release/kev21brv10/gazon_intelligent?color=green)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3.2+-blue)
![License](https://img.shields.io/github/license/kev21brv10/gazon_intelligent?style=flat-square)

> Un système autonome qui décide pour ton gazon à ta place.

Gazon Intelligent est une intégration Home Assistant qui transforme les données du jardin en décisions claires, lisibles et directement actionnables.

---

## ✨ Version 0.4.5

Cette release finalise une passe de cohérence métier et d'UX:

- projection de reprise de tonte avec `next_mowing_date` et `next_mowing_display`
- structuration des attributs visibles pour séparer décision, exécution et plan
- nettoyage des libellés UI et suppression des doublons visibles

---

## 🧠 Fonctionnement

Gazon Intelligent analyse en permanence :

- la météo  
- l’arrosage  
- le type de sol  
- les phases du gazon  
- l’historique des actions  

Il fournit ensuite une décision claire :

- quoi faire  
- quand le faire  
- pourquoi  
- quoi éviter  

Aucun calcul manuel n’est nécessaire.

---

## 🚀 Ce que fait Gazon Intelligent

- 💧 Détermine quand arroser et quelle quantité appliquer
- ✂️ Recommande la hauteur de tonte idéale  
- 🌱 S’adapte aux phases du gazon (sursemis, reprise…)  
- 🌦️ Analyse météo + sol + historique  
- 🧠 Évite les erreurs (tonte trop basse, arrosage inutile…)  
- 📊 Rend les décisions lisibles dans Home Assistant

---

## 📸 Aperçu

*(Ajoute ici une capture de ton dashboard Lovelace pour booster l’impact)*

---

## 👀 Ce que tu vois dans Home Assistant

### 🧩 Entités clés

- 🎛️ Mode du gazon
- 🌱 Phase dominante
- 🌱 Sous-phase
- 💡 Conseil principal
- ✅ Action recommandée
- ⛔ Action à éviter
- 📶 Niveau d'action
- ⏱️ Fenêtre optimale
- 🛡️ Risque gazon
- ✂️ État de tonte
- 📏 Hauteur de tonte conseillée
- ✂️ Tonte autorisée
- 💧 Arrosage conseillé
- 🎯 Objectif d'arrosage
- 🧾 Cycle calculé
- 🕘 Dernière session détectée
- 🧴 Dernière application
- 👆 Dernière exécution
- 🔓 Arrosage après application autorisé
- 🔘 Arrosage auto autorisé
- 🚿 Profil d'arrosage
- 🖲️ Bouton `Arrosage manuel immédiat`

### 🔎 Sémantique des états

- `type_arrosage` décrit le **profil agronomique** retenu par le moteur
  - exemple: `manuel_frequent` pour un sursemis
- `Dernière exécution` décrit le **mode d'exécution réel**
  - exemple: `Arrosage automatique` si l'intégration a déclenché le cycle
  - exemple: `Arrosage manuel immédiat` si l'utilisateur a lancé l'action
- les attributs d'exécution utilisent des libellés explicites comme `execution_action`, `execution_state`, `execution_plan_type` et `executed_passages`
- `Dernière session détectée` décrit la **dernière session physique observée**
  - généralement la dernière sous-session ou zone réellement mesurée par l'historique
  - `total_mm` est l'attribut canonique; les doublons de volume ne sont plus exposés dans l'UI
- `Cycle calculé` décrit le **cycle complet calculé**
  - il peut couvrir plusieurs zones et plusieurs passages
- `next_action_date` donne la **date réelle** de la prochaine action
  - exemple: `2026-03-24`
- `next_action_display` donne la **date lisible**
  - exemple: `24/03/2026`
- `type_sol` est exposé directement sur `Phase dominante`
- `raison_blocage_tonte` explique pourquoi la tonte n'est pas autorisée
- `Conseil principal` garde `summary` comme texte humain principal et expose des attributs métiers comme `action_type`, `action_moment`, `objectif_mm` et `type_arrosage`
- `Dernière application` décrit le **dernier traitement ou produit enregistré**

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

### 📚 Règles agronomiques sourcées

Ces principes viennent des bonnes pratiques d'irrigation du gazon et du sursemis :

- arroser tôt le matin, avec une fenêtre optimale autour de `04:00–08:00`
- rester acceptable jusqu'à `10:00` si le contexte le permet
- éviter les arrosages tardifs en soirée ou juste avant la nuit, car l'humectation nocturne prolongée augmente le risque de maladies foliaires
- garder la couche superficielle humide pour le sursemis
- éviter la saturation du sol
- privilégier des apports légers et fréquents au démarrage
- espacer progressivement les arrosages à mesure que l'enracinement progresse
- en conditions chaudes, sèches ou venteuses, plusieurs petits arrosages peuvent être nécessaires
- en mode normal, viser une logique profonde et peu fréquente, avec un ordre de grandeur hebdomadaire d'environ `20 à 25 mm/semaine` selon le contexte
- certains produits de type sol peuvent nécessiter un arrosage technique après application
- certains traitements foliaires doivent au contraire rester protégés avant tout arrosage

### 🛠️ Conventions internes de l’intégration

Ce sont des choix d’implémentation propres à cette intégration, pas des vérités universelles :

- Sursemis plus restrictif que les autres modes
- fenêtre matinale dynamique selon la température
- fractionnement automatique au-delà d'un objectif jugé trop élevé pour un seul passage
- autorisation du soir seulement si la journée a été chaude, sèche et sans arrosage récent
- blocage d'un nouvel arrosage si une session réelle récente a déjà atteint l'objectif
- traitement applicatif séparé en `sol` et `foliaire`
- arrosage technique possible après certaines applications `sol`
- blocage automatique après certaines applications `foliaire`
- type d'application inconnu = aucun arrosage automatique
- délai applicatif configurable avant arrosage post-application
- mode applicatif configurable: `auto`, `manuel`, `suggestion`
- `plan_type` décrit la composition du plan: `single_zone` ou `multi_zone`
- `fractionation` décrit uniquement le fractionnement temporel réel: `true` seulement si `passages > 1`
- un plan multi-zone peut rester sans fractionnement temporel quand `passages = 1`
- la soirée n'est qu'un rattrapage exceptionnel, jamais un créneau par défaut

### 📋 Tableau de fonctionnement

| Mode | Fenêtre cible | Objectif mm | Fréquence | Fractionnement |
| --- | --- | --- | --- | --- |
| Sursemis / Germination | Matin prioritaire, tôt et régulier | Faible, léger et fréquent | Plusieurs petits apports si sec / chaud / venteux | Oui si l'objectif dépasse 1 à 2 mm |
| Sursemis / Enracinement | Matin prioritaire, puis plus souple | Faible à modéré | On espace progressivement et on augmente la profondeur | Oui si l'objectif dépasse 2 mm |
| Normal | Matin tôt prioritaire (`04:00–08:00`, acceptable jusqu'à `10:00`) | Plus profond | Plus rare, avec un vrai apport utile | Oui si l'objectif est élevé |
| Fertilisation / Biostimulant | Matin tôt, arrosage technique après application si requis | Technique, modéré | Ponctuel | Oui si le plan l'exige |
| Agent Mouillant / Scarification | Matin tôt prioritaire | Technique, modéré | Ponctuel | Oui si l'objectif l'exige |
| Application sol avec `application_irrigation_mode=manuel` | Après délai applicatif, via service ou bouton manuel interne | Technique, léger | Déclenchement manuel contrôlé | Oui selon le plan calculé |
| Application sol avec `application_irrigation_mode=suggestion` | Affichage seulement | Technique, léger | Aucune exécution automatique | Non |
| Application foliaire | Bloqué pendant la fenêtre de protection | 0 | 0 | Non |
| Type d'application inconnu | Bloqué | 0 | 0 | Non |

### 🔍 Traçabilité V2

Le moteur expose aussi des champs de debug lisibles pour comprendre la décision:

- `deficit_brut_mm`
- `deficit_mm_ajuste`
- `mm_cible`
- `mm_final`
- `heat_stress_level`
- `confidence_level`
- `block_reason`

Le résumé hydrique affiché dans `raison_decision` suit le format:

- `Déficit: brut=X mm, ajusté=Y mm, final=Z mm`

### 🧮 Cycle calculé: composition vs fractionnement

- `plan_type = single_zone` quand une seule zone compose le plan
- `plan_type = multi_zone` quand le plan couvre plusieurs zones
- `fractionation = true` uniquement quand l'arrosage est réellement découpé dans le temps
- `zone_count` indique le nombre de zones
- `passages` indique le nombre de cycles temporels

### 🧪 Arrosage applicatif

Le moteur distingue maintenant :

- `sol` : application pouvant nécessiter un arrosage technique juste après
- `foliaire` : application qui bloque l'arrosage automatique pendant une durée label-driven

Les champs applicatifs disponibles sont :

- `application_type`
- `application_requires_watering_after`
- `application_post_watering_mm`
- `application_irrigation_block_hours`
- `application_irrigation_delay_minutes`
- `application_irrigation_mode`
- `application_label_notes`

Les capteurs utiles :

- `Dernière application`
- `Dernière exécution`
- `Cycle calculé`
- `Arrosage après application autorisé`
- `application_block_remaining_minutes`
- `application_post_watering_ready_at`
- `application_post_watering_delay_remaining_minutes`
- `application_post_watering_ready`

Le capteur `Dernière exécution` utilise ces états lisibles :

- `ok` : action acceptée et envoyée au moteur
- `en_attente` : action reconnue mais différée
- `bloque` : action refusée par sécurité ou fenêtre invalide
- `refuse` : action impossible ou incohérente

Le champ `action` reprend le libellé utilisateur, par exemple :

- `Arrosage manuel immédiat`
- `Cycle calculé lancé`

À vide, `Dernière exécution` affiche `none` avec le résumé `Aucune action récente`.

Le bouton visible dans l'interface principale :

- `Arrosage manuel immédiat`
- déclenche un arrosage manuel immédiat contrôlé
- reste l'unique action manuelle visible pour l'utilisateur

Le cycle calculé reste géré automatiquement par le scheduler interne.

Le switch global :

- `Arrosage auto autorisé`
- bloque ou autorise l'exécution automatique
- laisse les calculs visibles même quand il est coupé
- le scheduler interne réévalue périodiquement le contexte via le coordinator; un léger décalage peut exister selon le cycle de refresh

Le capteur `Fenêtre optimale` expose aussi un contexte lisible :

- `status` : `auto`, `bloque`, `en_attente`
- `next_action` : prochaine action lisible
- `next_action_date` : prochaine date réelle
- `next_action_display` : date lisible
- `summary` : résumé utilisateur, par exemple `Arrosage prévu demain matin (auto)`

Le flux reste compatible avec :

- calcul du besoin réel en eau
- prise en compte pluie / ETP / humidité
- adaptation selon la phase du gazon
- conversion automatique du besoin en mm vers une durée par zone
- exécution séquentielle des zones configurées
- fractionnement en plusieurs passages si nécessaire
- détection automatique des sessions réelles d'arrosage
- historique lisible via `Cycle calculé`, `Dernière session détectée` et `Dernière application`
- blocage explicite si le type d'application est inconnu
- blocage / délai / suggestion pilotés par `application_irrigation_mode`

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

## 🧭 Utilisation au quotidien

1. Home Assistant calcule  
2. Tu regardes  
3. Tu agis  

### À consulter en priorité

- Conseil principal  
- Action recommandée  
- Action à éviter  
- État de tonte  
- Arrosage conseillé
- Arrosage auto autorisé

👉 Tu ne réfléchis pas. Tu appliques.

---

## 📊 Exemple concret

Le matin :

- Phase dominante = Sursemis
- Conseil principal = Arroser demain matin
- Action recommandée = Appliquer 1.1 mm en un ou plusieurs passages selon le plan
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
- verrou global d'arrosage automatique

---

## 🛠️ Services essentiels

- `gazon_intelligent.set_mode`
- `gazon_intelligent.reset_mode`
- `gazon_intelligent.start_auto_irrigation`
- `gazon_intelligent.start_application_irrigation`
- `gazon_intelligent.declare_intervention`
- `gazon_intelligent.register_product`

## 🛠️ Services avancés

- `gazon_intelligent.set_date_action`
- `gazon_intelligent.start_manual_irrigation`
- `gazon_intelligent.declare_mowing`
- `gazon_intelligent.declare_watering`
- `gazon_intelligent.remove_product`

Notes:

- `start_manual_irrigation` reste un outil avancé pour lancer un arrosage manuel contrôlé, mais ce n'est pas le chemin principal d'usage.
- `declare_mowing` et `declare_watering` sont des raccourcis de compatibilité qui restent utiles, mais `declare_intervention` est le point d'entrée principal pour les interventions.

---

## 🌿 Produits personnalisés

Flux recommandé :

1. `register_product`  
2. `declare_intervention`  

👉 Sinon : laisse le moteur décider.

---

## ❤️ Support

Si le projet t’aide :

- ⭐ Mets une étoile  
- 🐛 Remonte les bugs  
- 💡 Propose des idées  

---

## 🛠️ Développement local

Pour lancer la suite de tests avec `pytest`:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

---

## 🧾 Version

- manifest : `0.4.5`
- README : `0.4.5`
- changelog : `0.4.5`


## 📄 Licence

Ce projet est sous licence MIT.
