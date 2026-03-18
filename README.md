# Gazon Intelligent

Statut: projet en test. L'intégration peut encore évoluer et certains comportements peuvent changer.
Version: `0.3.13`

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

- Zones d'arrosage `switch`:
  - `zone_1` à `zone_5`
- Débit par zone:
  - `debit_zone_1` obligatoire, défaut conseillé `60`
  - `debit_zone_2` à `debit_zone_5` si tu utilises plusieurs zones
- Capteurs météo et lecture du temps:
  - `capteur_pluie_24h` obligatoire
  - `capteur_pluie_demain`, `capteur_temperature`, `capteur_etp`, `capteur_humidite`, `capteur_vent`, `capteur_rosee` en option
  - si `entite_meteo` est renseignée, elle peut servir de secours pour la température, la température ressentie, l'humidité, le vent, la pression et la pluie J+1
- `type_sol`:
  - `sableux`, `limoneux`, `argileux`
- Capteurs utiles si tu les as:
  - `capteur_humidite_sol`, `capteur_hauteur_gazon`, `capteur_retour_arrosage`, `capteur_pluie_fine`
  - `capteur_hauteur_gazon` est recommandé si la hauteur change souvent

## Usage réel

Le chemin normal est simple:

1. l'intégration calcule ce qu'il faut faire,
2. tu utilises les boutons simples pour le quotidien et les services pour les actions avancées,
3. le système ajuste ses conseils.

### Boutons

- `Retour au mode normal`
- `Noter la date du jour` met à jour la dernière intervention active avec la date du jour

### Services pour actions avancées

- `gazon_intelligent.declare_intervention`
- `gazon_intelligent.declare_mowing`
- `gazon_intelligent.declare_watering`

Ces services servent à enregistrer les interventions réelles sans surcharger l'écran principal avec trop de boutons.

### Mode expert

- `Mode expert` reste disponible pour les cas spéciaux.
- Il n'est pas nécessaire à l'usage courant.

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
- `Sous-phase`
- `Objectif d'arrosage`
- `Jours restants de la phase`
- `Date d'action`
- `Date de fin de phase`

### Select

- `Mode expert`

### Diagnostics

- `Bilan hydrique`
- `ETP du jour`
- `Niveau de manque d'eau`
- `Niveau de stress du gazon`
- `Risque de tonte`
- `Humidité extérieure`
- `Pluie 24h`
- `Pluie prévue demain`
- `Température extérieure`
- `Niveau d'urgence`, `Arrosage conseillé` et `Mode d'arrosage` (compatibilité, masqués par défaut)

## Attributs utiles

Les attributs sont ciblés selon l'entité.

- `Décision principale`:
  - vue synthétique pour agir sans entrer dans la mécanique interne
- `Phase dominante`:
  - contexte de décision complet: entités utilisées, configuration, source de la pluie J+1, contexte avancé, état de la phase et état de tonte
- `Sous-phase`:
  - détail, âge et progression de la phase, avec `Germination`, `Enracinement` et `Reprise` pour le sursemis
- `État de tonte`:
  - statut lisible de la tonte: autorisée, à surveiller, déconseillée ou interdite
- `Arrosage recommandé` et `Arrosage auto autorisé`:
  - décision et autorisation technique séparées pour garder une hiérarchie claire
- `Pluie prévue demain`:
  - source de la valeur (`capteur`, `meteo_forecast`, `indisponible`)
- `Objectif d'arrosage` et `Bilan hydrique`:
  - métriques hydriques détaillées
- `Pourquoi ce choix`, `Conseil principal`, `Action recommandée`, `Risque gazon`:
  - contexte de décision et prochaine réévaluation
- `Mode expert`:
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
