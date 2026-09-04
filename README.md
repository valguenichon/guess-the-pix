# Guess the Pix v1.0.2

Première version stable multi-serveurs de Guess the Pix.

## Fiabilité des annonces en v1.0.2

Les annonces d'accélération et d'indices utilisent un repli automatique si Discord refuse la capture : nouvel essai sans image, puis texte seul si nécessaire. Les annonces de fin de manche et de fin de période disposent également d'un mode de repli et leurs erreurs n'interrompent plus la finalisation, les scores ni le passage à la période suivante. La publication des indices est sérialisée pour éviter un doublon si le scheduler et une accélération se déclenchent simultanément.

## Autorisation des serveurs

La v1 contrôle désormais les nouvelles installations avant toute configuration :

1. le bot rejoint un nouveau serveur : statut `pending` ;
2. le propriétaire du bot reçoit une notification privée ;
3. `/configurer` reste bloqué tant que la demande n'est pas autorisée ;
4. `/proprietaire autoriser serveur_id:...` passe le serveur à `approved` ;
5. un administrateur du serveur exécute `/configurer` ;
6. le serveur passe alors à `configured`.

Commandes réservées au propriétaire du bot :

- `/proprietaire serveurs` : liste les serveurs connus et leur statut ;
- `/proprietaire autoriser` : autorise une demande en attente ;
- `/proprietaire refuser` : refuse la demande et retire le bot ;
- `/proprietaire bloquer` : bloque le serveur et retire le bot ;
- `/proprietaire debloquer` : permet au serveur de refaire une demande lors d'une future invitation.
- `/proprietaire nettoyer-commandes serveur_id:...` : supprime les anciennes commandes guild-specific héritées d'une version v0.x, sans toucher aux commandes globales ni aux données du jeu.

États enregistrés : `pending`, `approved`, `configured`, `refused`, `blocked`, `inactive`.
Un serveur retirant le bot devient `inactive` ; une demande explicitement refusée reste `refused` dans l’historique. Une nouvelle invitation d’un serveur `inactive` ou `refused` crée une nouvelle demande ; si le serveur avait déjà été refusé, le propriétaire du bot en est explicitement averti.
Les serveurs déjà configurés avant cette évolution sont automatiquement conservés en `configured`.

`BOT_OWNER_USER_ID` peut être renseigné dans `.env`. S'il est absent, le bot tente de déterminer automatiquement le propriétaire de l'application Discord.

## Architecture

Une instance peut servir plusieurs serveurs Discord. Chaque serveur dispose de sa propre configuration et de ses propres données : salon de jeu, rôle administrateur, participants, meneur, manches, périodes, scores, historique, limite d'essais et scoreboard.

Tous les messages privés liés à une partie indiquent explicitement le **nom du serveur d’origine**, afin qu’un même utilisateur puisse participer ou être meneur sur plusieurs serveurs sans ambiguïté.

Les captures de manches sont isolées sous :

```text
data/round_images/<guild_id>/round_<number>.<ext>
```

## Staging recommandé

Utiliser une seconde application Discord et un répertoire Synology séparé, par exemple :

```text
/volume1/docker/guess-the-pix-staging/
/volume1/docker/guess-the-pix-prod/
```

Chaque environnement doit posséder son propre `.env` et son propre dossier `data/`.

Exemple `.env` de staging :

```env
DISCORD_TOKEN=<token de l'application Discord staging>
DATABASE_PATH=data/scoreboard.db
ENVIRONMENT=staging
COMMAND_GUILD_IDS=
ROUND_DURATION_DAYS=7
```

En staging/development, `COMMAND_GUILD_IDS` est désormais **facultatif** : tout serveur effectivement rejoint reçoit automatiquement ses commandes guild-specific, au démarrage comme lors d’une nouvelle invitation. La variable peut encore contenir des IDs séparés par des virgules uniquement pour pré-synchroniser des serveurs connus. En production, elle est ignorée et les commandes sont enregistrées globalement. L’ancienne variable `COMMAND_GUILD_ID` reste acceptée comme pré-synchronisation de compatibilité avec les anciennes configurations de staging.

## Installation du serveur de test

Après ajout du bot sur un nouveau serveur, celui-ci est d'abord placé en `pending`. Le propriétaire du bot autorise la demande avec :

```text
/proprietaire autoriser serveur_id:<ID_DU_SERVEUR>
```

Ensuite seulement, un membre du serveur ayant `Administrator` ou `Manage Guild` exécute :

```text
/configurer salon:#votre-salon role_admin:@Game Admin
```

Le rôle admin est facultatif. L’administrateur peut soit sélectionner un rôle existant avec `role_admin`, soit demander au bot de créer son rôle dédié :

```text
/configurer salon:#votre-salon creer_role_admin:Oui
```

Tout rôle créé automatiquement porte toujours exactement le nom **`Guess the Pix - admin`**. Un rôle existant choisi manuellement conserve son nom. Les deux options ne peuvent pas être utilisées simultanément. Tant que le serveur n'est pas `configured`, les commandes de jeu sont bloquées ; `/aide`, `/config`, `/configurer` et `/proprietaire` restent disponibles.

Commandes de configuration :

```text
/config statut
/config salon
/config role-admin
```

## Migration depuis v0.13.3

Pour migrer une installation v0.13.3, conserver temporairement dans `.env` les anciennes valeurs :

```env
GUILD_ID=...
GAME_CHANNEL_ID=...
GAME_ADMIN_ROLE_ID=...
```

Au premier démarrage, elles servent uniquement à créer la configuration du serveur historique. Les données existantes sont conservées.

Après vérification avec `/config statut`, ces trois variables legacy pourront être retirées d'un prochain déploiement.

Si Discord affiche encore certaines commandes en double sur le serveur historique après la migration, exécuter :

```text
/proprietaire nettoyer-commandes serveur_id:<ID_DU_SERVEUR>
```

Cette opération supprime uniquement les anciennes commandes locales (guild-specific) de l'application. Les commandes globales v1 et toutes les données SQLite restent intactes.

Toujours sauvegarder `data/scoreboard.db` avant une migration de production.

## Commandes de jeu

Les commandes existantes restent disponibles : `/participer`, `/quitter`, `/participants`, `/reponse`, `/meneur`, `/lancer`, `/passe`, `/score`, `/score-global`, `/periodes`, `/historique`, ainsi que les commandes d'administration.

`/lancer` accepte soit :

- `capture` : une image Discord ;
- `url` : une URL publique d'image.

Le nom du jeu et les trois indices sont ensuite demandés dans le formulaire.

## Docker / Synology

Le `compose.yaml` fourni utilise `guess-the-pix` comme nom par défaut pour le projet Compose, le service et le conteneur. L’image Docker est explicitement fixée dans le Compose à `guess-the-pix:1.0.2` afin que son nom ne dépende pas du nom du projet Compose.

Les valeurs par défaut sont :

```text
Projet Compose : guess-the-pix
Service         : guess-the-pix
Conteneur       : guess-the-pix
Image           : guess-the-pix:1.0.2
```

Le `compose.yaml` utilise également des chemins relatifs afin que le même paquet puisse être placé dans deux répertoires indépendants. Si production et staging tournent simultanément sur le même hôte Docker, le staging doit surcharger le nom du projet et du conteneur dans son `.env` :

```env
COMPOSE_PROJECT_NAME=guess-the-pix-staging
CONTAINER_NAME=guess-the-pix-staging
```

L’image reste `guess-the-pix:1.0.2` car son nom est volontairement fixé dans `compose.yaml`.

Pour une nouvelle instance staging, un build initial est nécessaire. Ensuite, comme `bot.py`, `config.py` et `database.py` sont montés directement, les mises à jour de ces fichiers ne nécessitent normalement qu'un redémarrage du conteneur tant que les dépendances ne changent pas.

## Tests fournis

`tests/test_multiguild.py` vérifie l'isolation de deux guildes dans une base commune. `tests/test_guild_authorization.py` vérifie le cycle pending/approved/configured/inactive/blocked/refused. `tests/test_migration_v0133.py` vérifie la conservation d'une base v0.13.3 représentative et l'idempotence de la migration.
