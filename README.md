# Gazon Intelligent

Statut: projet en test. L'intégration peut encore évoluer et certains comportements peuvent changer.
Version: `0.3.14`

Gazon Intelligent est une intégration Home Assistant qui transforme les capteurs du jardin en décisions lisibles.
Elle analyse la météo, le sol, l'historique et les interventions déclarées, puis dit clairement quoi faire, quand agir, pourquoi et quoi éviter.
En pratique, le système garde la mémoire du terrain, hiérarchise les informations utiles et réduit le bruit technique.

Le dépôt est compatible HACS et prêt à être installé comme une intégration Home Assistant standard.
L'interface est traduite en français, anglais, espagnol, allemand et néerlandais.

## En bref

- décision principale claire pour l'arrosage et la tonte
- phase active et sous-phase pour garder le contexte agronomique
- mémoire des interventions pour affiner les recommandations
- diagnostics avancés disponibles sans polluer l'écran principal

## Ce que le produit donne

- une phase dominante qui garde le contexte actif
- un conseil principal directement exploitable
- une action recommandée et une action à éviter
- une priorité, une fenêtre optimale et un risque si on attend
- une mémoire des interventions réelles pour affiner les décisions
- une mémoire simple des dernières applications avec date de réapplication
- une base locale de produits personnalisés par utilisateur
- une sous-phase fine pour le sursemis et les phases spéciales

## Installation

### Via HACS, recommandé

1. Ajouter ce dépôt dans HACS, catégorie `Integration`.
2. Installer **Gazon Intelligent**.
3. Redémarrer Home Assistant.
4. Ajouter l'intégration depuis `Paramètres > Appareils et services`.

HACS s'appuie sur `hacs.json` à la racine du dépôt.

### Manuelle

1. Copier `custom_components/gazon_intelligent` dans `config/custom_components`.
2. Redémarrer Home Assistant.
3. Ajouter l'intégration depuis `Paramètres > Appareils et services`.

## Configuration

L'intégration se configure via formulaire.

Paramètres de base:
- zones d'arrosage `zone_1` à `zone_5`
- débit par zone `debit_zone_1` à `debit_zone_5` (`0` si non utilisé)
- `type_sol` obligatoire

Options avancées dans l'UI:
- `entite_meteo` obligatoire
- `capteur_pluie_24h` optionnel, pris depuis la météo si vide
- `capteur_pluie_demain` optionnel, pris depuis la météo si vide
- `capteur_temperature` optionnel, pris depuis la météo si vide
- `capteur_etp` optionnel, estimé automatiquement si vide
- `capteur_humidite` optionnel, pris depuis la météo si vide
- `capteur_humidite_sol` optionnel
- `capteur_hauteur_gazon` optionnel, recommandé si la hauteur change souvent
- `capteur_vent` optionnel, pris depuis la météo si vide
- `capteur_rosee` optionnel, pris depuis la météo si vide

Si un capteur pluie, température, ETP ou humidité est vide, l'entité météo prend le relais.
La température utilisée pour les calculs favorise la prévision du jour quand elle est disponible.

## Usage réel

Le chemin normal est simple:

1. l'intégration calcule ce qu'il faut faire,
2. tu utilises les boutons simples pour le quotidien,
3. tu passes par les services pour les actions avancées.

### Boutons

- `Retour au mode normal`
- `Noter la date du jour` met à jour la dernière intervention active avec la date du jour

### Services pour actions avancées

- `gazon_intelligent.declare_intervention`
- `gazon_intelligent.declare_mowing`
- `gazon_intelligent.declare_watering`

`gazon_intelligent.declare_intervention` enregistre l'intervention réelle et peut aussi prendre un produit, une dose, une zone et un délai de réapplication.
`gazon_intelligent.register_product` ajoute un produit personnalisé dans la base locale.
`gazon_intelligent.remove_product` en retire un.
Les dates saisies dans les services se font au format `JJ/MM/AAAA`.

## Lecture rapide

Pour lire l'écran vite, regarde dans cet ordre:

- `Phase dominante`: ce qui pilote vraiment le gazon
- `État de tonte`: tonte autorisée ou non
- `Conseil principal`: ce qu'il faut faire maintenant
- `Action à éviter`: ce qu'il vaut mieux ne pas faire
- `Niveau d'action`: priorité de l'action
- `Fenêtre optimale`: meilleur moment pour agir

Les scores détaillés et les calculs internes restent dans les diagnostics. L'écran principal doit servir à décider, pas à décortiquer le moteur.

## Entités créées

### Décision principale

- `État de tonte`
- `Pourquoi ce choix`
- `Conseil principal`
- `Action recommandée`
- `Action à éviter`
- `Niveau d'action`
- `Fenêtre optimale`
- `Risque gazon`
- `Prochaine réévaluation`

### Binary sensors

- `Tonte autorisée`
- `Arrosage recommandé`
- `Arrosage auto autorisé`

### Contexte technique

- `Phase dominante`

### Select

- `Mode du gazon`

### Diagnostics

- `Bilan hydrique`
- `ETP du jour`
- `Dernière application`
- `Prochaine réapplication`
- `Catalogue produits`
- `Niveau de manque d'eau`
- `Niveau de stress du gazon`
- `Risque de tonte`
- `Humidité extérieure`
- `Pluie 24h`
- `Pluie prévue demain`
- `Température extérieure`
- `Niveau d'urgence`, `Arrosage conseillé` et `Mode d'arrosage` compatibles, masqués par défaut
- `Sous-phase`
- `Objectif d'arrosage`
- `Jours restants de la phase`
- `Date d'action`
- `Date de fin de phase`

## Attributs utiles

Les attributs sont ciblés selon l'entité.

- `Décision principale`:
  - vue synthétique pour agir sans entrer dans la mécanique interne
- `Phase dominante`:
  - contexte de décision compact: phase active, sous-phase, source de la pluie de demain, priorité et fenêtre optimale
- `État de tonte`:
  - statut lisible de la tonte: autorisée, à surveiller, déconseillée ou interdite
- `Arrosage recommandé` et `Arrosage auto autorisé`:
  - décision et autorisation technique séparées pour garder une hiérarchie claire
- `Pluie prévue demain`:
  - source de la valeur (`capteur`, `meteo_forecast`, `indisponible`)
- `Sous-phase`, `Objectif d'arrosage`, `Jours restants de la phase`, `Date d'action` et `Date de fin de phase`:
  - détails techniques et agronomiques, visibles dans les diagnostics
- `Bilan hydrique`:
  - métriques hydriques détaillées
- `Pourquoi ce choix`, `Conseil principal`, `Action recommandée`, `Risque gazon`:
  - contexte de décision et prochaine réévaluation
- `Catalogue produits`:
  - nombre de produits enregistrés, avec la liste compacte en attributs
- `Mode du gazon`:
  - vue système rapide pour diagnostic et pilotage

## Services disponibles

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

Les champs détaillés sont dans `custom_components/gazon_intelligent/services.yaml`.

## Événement Home Assistant

- `gazon_intelligent_manual_irrigation_requested`

Émis par `start_manual_irrigation` avec:
- `objectif_mm`
- `mode`
- `date_action`

## Blueprint

- Fichier:
  - `blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml`
- Nom:
  - `Gazon Intelligent - Arrosage intelligent (modes spéciaux hors Normal)`

[Importer le blueprint dans Home Assistant](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/kev21brv10/gazon_intelligent/blob/main/blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml)

## Glossaire rapide

- `ETP`: besoin en eau journalier, mesuré ou estimé en mm/j.
- `Phase dominante`: phase qui gouverne réellement le gazon.
- `Sous-phase`: étape fine à l'intérieur d'une phase dominante.
- `Bilan hydrique`: lecture hydrique de fond, pas seulement le manque du jour.
- `deficit_jour`, `deficit_3j`, `deficit_7j`: bilan hydrique court et moyen terme.
- `pluie_efficace`: pluie réellement retenue par le calcul.
- `arrosage_recent`: arrosage cumulé récent pris en compte par le moteur.
- `Arrosage recommandé`: verdict principal pour savoir s'il faut arroser.
- `Arrosage auto autorisé`: autorisation technique pour le mode automatique.
- `Niveau d'action`: priorité du moteur, de `aucune_action` à `critique`.
- `Fenêtre optimale`: meilleur moment pour agir.
- `Si on attend`: risque synthétique si l'action est retardée.
- `Prochaine réévaluation`: quand relancer le calcul du moteur.
