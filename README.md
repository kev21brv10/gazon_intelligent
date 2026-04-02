# 🌱 Gazon Intelligent

<p align="center">
  <img src="https://raw.githubusercontent.com/kev21brv10/gazon_intelligent/main/logo.png" width="120">
</p>

![Version](https://img.shields.io/github/v/release/kev21brv10/gazon_intelligent?color=green)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3.2+-blue)
![License](https://img.shields.io/github/license/kev21brv10/gazon_intelligent?style=flat-square)


> Gazon Intelligent transforme vos données météo et d’arrosage en décisions simples, fiables et automatisables, avec une façade canonique lisible dans `sensor.gazon_intelligent_assistant`.

---

## En bref

- une seule intégration, un seul moteur
- une décision lisible à la fois
- Sursemis strict plafonné à `0.5 mm`
- une façade canonique: `sensor.gazon_intelligent_assistant`
- des entités complémentaires pour le contexte, l’historique, la tonte et le debug

En clair:

- l’intégration regarde les données utiles
- elle dit quoi faire, quand le faire, et combien appliquer
- Home Assistant affiche la décision de façon simple

---

## 🚀 Démarrage rapide

1. Installer l’intégration `gazon_intelligent`
2. Configurer le type de sol et les zones
3. Consulter `sensor.gazon_intelligent_assistant`
4. Ouvrir `sensor.gazon_intelligent_conseil_principal`, `sensor.gazon_intelligent_fenetre_optimale` et `sensor.gazon_intelligent_objectif_d_arrosage` si besoin

👉 Vous obtenez immédiatement :
- quoi faire
- quand le faire
- combien appliquer

La façade canonique est `sensor.gazon_intelligent_assistant`.
Les autres entités détaillent le contexte, l'historique, la tonte et le debug.

---

## ✨ Release 0.4.6

Cette version apporte surtout trois choses:

- un Sursemis plus sensible aux sous-phases
- une façade publique plus lisible et cohérente
- des diagnostics plus utiles pour comprendre les décisions et les blocages

---

## 🧠 Ce que fait l’intégration

Gazon Intelligent centralise le calcul dans l’intégration et transforme ces données en décision:

- météo
- arrosage récent
- type de sol
- phase dominante et sous-phase
- historique des interventions

Il répond ensuite à des questions simples:

- quoi faire
- quand le faire
- combien appliquer
- pourquoi
- quoi éviter

En pratique, l’intégration gère:

- l’arrosage
- la tonte
- les blocages météo ou applicatifs
- la mémoire métier
- les diagnostics

---

## 📸 Aperçu

*Capture prochainement.*

---
## 👀 Entités principales

### Façade canonique

- `sensor.gazon_intelligent_assistant`
  - c’est l’entité à regarder en premier
  - elle dit ce qu’il faut faire
  - elle affiche aussi la prochaine date estimée
  - quand il n’y a rien à faire, elle affiche `aucune_action`

### Entités de lecture

- `sensor.gazon_intelligent_conseil_principal`
  - petit résumé facile à lire
  - utile pour comprendre pourquoi la décision a été prise
- `sensor.gazon_intelligent_fenetre_optimale`
  - indique le meilleur moment pour agir
- `sensor.gazon_intelligent_objectif_d_arrosage`
  - indique combien arroser
- `sensor.gazon_intelligent_plan_d_arrosage`
  - détaille le cycle d’arrosage calculé
- `sensor.gazon_intelligent_niveau_d_action`
  - indique si on peut attendre, surveiller, agir ou traiter en priorité
- `sensor.gazon_intelligent_type_d_arrosage`
  - indique le profil d’arrosage retenu

### Entités métier complémentaires

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

### Interface utilisateur

- `button.gazon_intelligent_arroser_maintenant`
- `button.gazon_intelligent_noter_la_date_du_jour`
- `button.gazon_intelligent_retour_au_mode_normal`
- `switch.gazon_intelligent_arrosage_automatique_autorise`
- `select.gazon_intelligent_mode_du_gazon`

### Debug

- diagnostics téléchargeables via l’intégration
- logs du module `custom_components.gazon_intelligent`
- `sensor.gazon_intelligent_catalogue_produits` pour voir rapidement les produits enregistrés

---

## 🔎 Comment lire les états

Les libellés restent simples à lire:

- `assistant`
  - la décision principale
- `conseil_principal`
  - l’explication courte
- `fenetre_optimale`
  - quand agir si besoin
- `objectif_d_arrosage`
  - combien arroser
- `next_action_date`
  - la date estimée de la prochaine action
- `next_action_display`
  - la même date en format lisible
- `Dernière exécution`
  - ce que l’intégration a réellement lancé
- `Dernière session détectée`
  - la dernière session d’arrosage observée
- `Dernière application`
  - le dernier traitement enregistré
- `niveau_d_action`
  - le niveau d’urgence

### Valeurs à retenir

- `aucune_action` = rien à faire pour l’instant
- `attendre` = on réévalue plus tard
- `surveiller` = pas d’action immédiate, mais contexte à suivre
- `a_faire` = action utile à exécuter
- `critique` = action à traiter en priorité

---

## ✂️ Gestion de la tonte

L'entité **État de tonte** expose :

- `hauteur_tonte_recommandee_cm`  
- `hauteur_tonte_min_cm`  
- `hauteur_tonte_max_cm`  

L'entité **Hauteur de tonte conseillée** affiche directement la hauteur recommandée.

En pratique:

- si la tonte est autorisée, tu peux t’en servir comme repère
- si la tonte est interdite, le gazon a besoin de temps ou les conditions ne sont pas bonnes

### ⚙️ Réglages tondeuse

Configurables dans Home Assistant :

- Hauteur min tondeuse  
- Hauteur max tondeuse  

Le système :

- respecte les limites de ta machine  
- applique un pas réel de **0.5 cm**  
- adapte la hauteur selon la saison, la météo et le stress du gazon  

---

## 💧 Détails avancés sur l’arrosage

### Comment l’intégration décide

L’intégration essaie d’arroser:

- tôt le matin quand c’est possible
- un peu plus souvent en Sursemis
- plus profondément et moins souvent en mode Normal
- seulement quand le sol a vraiment besoin d’eau
- jamais si une pluie importante ou un blocage l’empêche

Elle peut aussi:

- attendre après une application
- empêcher un arrosage trop proche du précédent
- fractionner un arrosage si un seul passage serait trop important

### Exemple de comportement

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

### 🔍 Informations utiles

Le moteur expose aussi quelques champs utiles pour comprendre la décision:

- `deficit_brut_mm`
- `deficit_mm_ajuste`
- `mm_cible`
- `mm_final`
- `heat_stress_level`
- `confidence_level`
- `block_reason`

Le résumé hydrique affiché dans `raison_decision` suit le format:

- `Déficit: brut=X mm, ajusté=Y mm, final=Z mm`

### 🧮 Comment le plan est construit

- `plan_type = single_zone` quand une seule zone compose le plan
- `plan_type = multi_zone` quand le plan couvre plusieurs zones
- `fractionation = true` seulement si l’arrosage est vraiment découpé en plusieurs passages
- `zone_count` indique le nombre de zones
- `passages` indique le nombre de passages

### 🧪 Produits et applications

Cette partie sert à mémoriser un produit ou un traitement une seule fois, puis à laisser l’intégration réutiliser ces réglages automatiquement au moment de déclarer une intervention.

#### Deux types d’application

- `sol`
  - produit appliqué sur le sol
  - peut demander un arrosage technique après application
- `foliaire`
  - produit appliqué sur le feuillage
  - bloque temporairement l’arrosage automatique pendant la protection

#### Champs à enregistrer une seule fois

Les réglages produits se déclarent dans `register_product`:

- `type`
  - catégorie du produit, choisie dans une liste
  - exemple: `Biostimulant`
- `dose_conseillee`
  - dosage conseillé au m²
  - exemple: `1.2 ml / m²`
- `application_type`
- `application_requires_watering_after`
- `application_post_watering_mm`
- `application_irrigation_block_hours`
- `application_irrigation_delay_minutes`
- `application_irrigation_mode`
- `application_label_notes`
- `application_months`
  - mois ou périodes d’application recommandés
  - critère souple pour guider la recommandation, pas un blocage absolu
  - exemple: `3,4,5,9,10` ou `mars à mai + septembre à octobre`

Tu peux aussi y enregistrer:

- `reapplication_after_days`
- `delai_avant_tonte_jours`
- `phase_compatible`
  - sélection multiple possible
  - exemple: `Sursemis`, `Croissance`, `Entretien`

#### Ce que l’intégration affiche

- `Dernière application`
  - le dernier produit ou traitement enregistré
- `Dernière exécution`
  - ce que l’intégration a réellement lancé
- `Catalogue produits`
  - le nombre de produits enregistrés et leurs détails
- `Prochaine intervention`
  - la recommandation calculée par l’algorithme à partir du catalogue, de la phase, du mois et de l’historique
- `Produit d’intervention`
  - le produit actuellement choisi pour une prochaine intervention
  - la liste est remplie automatiquement à partir des produits enregistrés
  - si un seul produit existe, il peut être repris automatiquement
- `Cycle calculé`
  - le plan d’arrosage calculé si un arrosage est nécessaire
- `Arrosage après application autorisé`
  - indique si un arrosage est permis après une application

#### Choisir un produit pour une intervention

Le plus simple est de:

1. Enregistrer d’abord le produit avec `register_product`
2. Le choisir ensuite dans `select.gazon_intelligent_produit_d_intervention`
3. Déclarer l’intervention réelle avec `declare_intervention`

Le sélecteur affiche les noms lisibles. Si plusieurs produits ont le même nom, le libellé devient `Nom — product_id` pour éviter toute ambiguïté.
Quand aucun produit ne correspond plus, la sélection se vide proprement.

Les états de `Dernière exécution` sont simples:

- `ok` = action acceptée
- `en_attente` = action reconnue mais différée
- `bloque` = action refusée pour sécurité ou timing
- `refuse` = action impossible ou incohérente

#### Comment ajouter un produit

1. Utilise le service `gazon_intelligent.register_product`
2. Donne un `product_id` unique
3. Renseigne le nom, la catégorie et le dosage au m², puis tous les réglages utiles du produit
4. Lors d’une intervention réelle, choisis le produit dans `select.gazon_intelligent_produit_d_intervention` ou précise son ID exact
5. Lance `gazon_intelligent.declare_intervention` avec la date d'action (`date_action`), la zone et une note si besoin
6. S’il n’y a qu’un seul produit enregistré, l’intégration peut le reprendre automatiquement
7. Si plusieurs produits existent, il faut une sélection claire: le sélecteur ou un ID / nom exact
8. Si le produit n’est plus utile, retire-le avec `gazon_intelligent.remove_product`

#### Quand utiliser un produit enregistré

Un produit enregistré sert à:

- réutiliser les mêmes réglages à chaque fois
- éviter de retaper les paramètres à la main
- garder une trace claire dans l’historique
- simplifier la déclaration d’intervention

#### Exemples simples

- un produit de sol peut demander un arrosage léger après application
- un produit foliaire peut bloquer l’arrosage pendant quelques heures
- un produit inconnu ne déclenche rien d’automatique

#### Ce qu’il faut retenir

- le produit se mémorise avec `register_product`
- le choix du produit pour l’intervention se fait avec `select.gazon_intelligent_produit_d_intervention`
- la prochaine intervention recommandée est exposée par `sensor.gazon_intelligent_prochaine_intervention`
- ce capteur expose un `payload` structuré et versionné (`schema_version: 3`) qui devient la source de vérité pour la carte
- le contrat conserve toujours les mêmes champs racine, avec `null`, `[]` ou `{}` quand une donnée n’est pas disponible
- `status` vaut `recommended`, `possible`, `blocked` ou `unavailable`
- `score` est un entier borné entre `0` et `100`
- `constraints` et `missing_requirements` sont des listes d’objets structurés, jamais des listes de chaînes
- `unavailable` couvre le cas catalogue vide, sans ajouter de statut fantôme
- l’intervention réelle se déclare avec `declare_intervention`
- `declare_intervention` reste simple: produit choisi, date d'action (`date_action`), zone, note
- `remove_product` nettoie la base locale
- le moteur garde la main sur les garde-fous d’arrosage

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

Notes:

- `set_mode` et `reset_mode` restent les raccourcis stables pour piloter le mode du gazon.
- `set_date_action` enregistre la date métier réelle.
- `start_manual_irrigation` lance un arrosage manuel contrôlé à partir d’un objectif explicite.
- `start_auto_irrigation` exécute le cycle calculé ou un objectif fourni, sans contourner les garde-fous.
- `declare_intervention` reste le point d’entrée principal pour les interventions.
- `declare_intervention` reste volontairement simple: on choisit le produit dans le sélecteur dédié, puis la date, la zone et une note si besoin.
- si plusieurs produits sont enregistrés, il faut une sélection claire: le sélecteur, ou un ID / nom exact, sinon le moteur renvoie une erreur explicite.
- tous les réglages du produit se trouvent dans `register_product`.
- si une application a été enregistrée par erreur, `remove_last_application` supprime la dernière application de l’historique local.
- `declare_mowing` et `declare_watering` sont des raccourcis de compatibilité utiles.

---

## 🧭 Utilisation au quotidien

Le principe est simple:

1. L’intégration calcule la décision
2. Tu lis la façade `assistant`
3. Tu appliques ou tu laisses faire

### À consulter en priorité

- `sensor.gazon_intelligent_assistant`
- `sensor.gazon_intelligent_conseil_principal`
- `sensor.gazon_intelligent_fenetre_optimale`
- `sensor.gazon_intelligent_objectif_d_arrosage`
- `sensor.gazon_intelligent_etat_de_tonte`
- `binary_sensor.gazon_intelligent_arrosage_recommande`
- `binary_sensor.gazon_intelligent_tonte_autorisee`

### Lecture rapide

- si `assistant = aucune_action`, il n’y a rien à faire
- si `fenetre_optimale = attendre`, le moteur réévalue plus tard
- si `objectif_d_arrosage > 0`, un arrosage est potentiellement utile
- si `tonte_autorisee = off`, la tonte est bloquée pour une bonne raison

### Ce que le système automatise

- bilan hydrique complet
- comparaison pluie / arrosage / ETP
- gestion des phases et sous-phases
- décisions arrosage / tonte
- mémoire des actions
- suivi des interventions
- verrou global d'arrosage automatique

---

## 🌿 Produits personnalisés

Si tu utilises souvent les mêmes produits:

1. `register_product` sert à enregistrer la fiche produit
2. `select.gazon_intelligent_produit_d_intervention` sert à choisir le produit pour la prochaine intervention
3. `declare_intervention` sert à déclarer l’action réelle
4. le moteur reprend automatiquement tous les réglages enregistrés pour ce produit
5. `remove_product` retire le produit s’il n’est plus utile
6. `remove_last_application` supprime la dernière application si elle a été déclarée par erreur
7. si plusieurs instances Gazon Intelligent existent, la carte transmet automatiquement `entity_id` pour viser la bonne instance

Si plusieurs produits existent, utilise l’ID ou le nom exact du produit voulu. Sinon, l’intégration refuse de deviner.

👉 Cela évite de retaper les mêmes paramètres à chaque fois.

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

- manifest : `0.4.6`
- README : `0.4.6`
- changelog : `0.4.6`


## 📄 Licence

Ce projet est sous licence MIT.
