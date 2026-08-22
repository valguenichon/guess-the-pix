# Scoreboard Discord — jeu de capture d’écran

Bot Discord pour un jeu hebdomadaire de découverte de jeux vidéo à partir d’une capture d’écran.

## Configuration de ce serveur

Le projet est préconfiguré pour :

- serveur Discord : `719108810081304617`
- canal du jeu : `1539974418590339103`
- rôles participants : `766634696645804062` et `766635095905796096`
- rôle **Admin du jeu** : `1540752051783475372`
- durée d’une manche : exactement `7 × 24 h` après son lancement

Ces valeurs sont dans `.env.example`. Le token du bot n’est volontairement pas inclus.

## Règles implémentées

- Le meneur lance une manche avec `/lancer` et joint une capture d’écran.
- Il saisit le nom du jeu dans un formulaire privé au lancement.
- La manche reste ouverte exactement 7 jours (168 heures).
- Seuls les membres possédant au moins un des deux rôles participants peuvent répondre.
- Les joueurs répondent directement avec `/reponse réponse:` ; le texte de la réponse n’est jamais publié dans le canal.
- Chaque tentative déclenche immédiatement un message privé au meneur avec les boutons **Valider** et **Invalider**.
- Le joueur sait seulement que sa réponse a été examinée ; le verdict reste secret jusqu’à la clôture.
- Plusieurs tentatives sont possibles.
- Pour chaque joueur, l’heure de sa première tentative validée correcte détermine son rang.
- À J+7, les nouvelles réponses sont bloquées.
- S’il reste des réponses en attente de validation à J+7, le résultat attend leur arbitrage par le meneur.
- À la fin : 3 points au premier, 2 au deuxième et 1 au troisième.
- Si personne ne trouve, le meneur gagne 2 points.
- Le premier devient le prochain meneur.
- S’il utilise `/passe`, un membre est tiré au sort parmi les deux rôles participants en excluant le gagnant et le meneur de la manche précédente.
- Si personne n’a trouvé, le prochain meneur est tiré automatiquement en excluant le meneur sortant.
- Les comptes bots sont toujours exclus des tirages.

## Commandes

### Joueurs

- `/aide` — afficher les commandes disponibles
- `/reponse réponse:` — envoyer une réponse secrète au meneur
- `/score` — afficher le classement général
- `/score @joueur` — afficher le score d’un joueur
- `/meneur` — afficher le meneur actuel
- `/historique` — afficher les dix dernières manches terminées

### Meneur

- `/lancer capture:` — lancer une manche avec une capture d’écran
- `/passe` — passer la main avant le lancement de sa manche et déclencher un tirage

### Administration

Ces commandes sont accessibles aux membres possédant le rôle **Admin du jeu** (`1540752051783475372`). Par sécurité, les membres ayant la permission Discord **Administrateur** ou **Gérer le serveur** y ont également accès :

- `/designer @joueur` — désigner manuellement le prochain meneur ; le membre doit avoir un rôle participant
- `/corriger @joueur points:` — ajouter ou retirer des points
- `/cloturer` — fermer immédiatement les réponses ; les résultats ne sont publiés qu’après validation des réponses encore en attente

## Installation

Python 3.11 ou plus récent est recommandé.

### 1. Créer le bot Discord

Dans le Discord Developer Portal :

1. créer ou ouvrir l’application du bot ;
2. dans **Bot**, activer **Server Members Intent** ; cet intent est nécessaire pour que le tirage puisse lire de manière fiable les membres portant les rôles participants ;
3. récupérer le token du bot ;
4. ne jamais publier ou partager ce token.

### 2. Inviter le bot sur le serveur

Le bot doit disposer au minimum de :

- Voir le canal
- Envoyer des messages
- Intégrer des liens
- Lire l’historique des messages
- Utiliser les commandes d’application

Le bot doit aussi pouvoir envoyer des messages privés au meneur. Si les DM du meneur sont fermés, le canal signale seulement qu’une réponse attend une validation, sans en révéler le contenu.

### 3. Installer le projet

Sous Linux/macOS :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Sous Windows PowerShell :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 4. Ajouter le token

Ouvrir `.env` et remplacer uniquement :

```text
DISCORD_TOKEN=collez_ici_le_token_du_bot
```

par le vrai token.

Les autres paramètres sont déjà renseignés :

```text
GUILD_ID=719108810081304617
GAME_CHANNEL_ID=1539974418590339103
PARTICIPANT_ROLE_IDS=766634696645804062,766635095905796096
GAME_ADMIN_ROLE_ID=1540752051783475372
DATABASE_PATH=data/scoreboard.db
ROUND_DURATION_DAYS=7
```

### 5. Démarrer

```bash
python bot.py
```

Au démarrage, les slash commands sont synchronisées directement sur le serveur configuré.

## Premier test conseillé

1. Démarrer le bot.
2. Dans le canal du jeu, utiliser `/aide`.
3. Un membre ayant le rôle **Admin du jeu** utilise `/designer @joueur` pour choisir le premier meneur.
4. Le meneur utilise `/lancer` et joint une capture.
5. Un autre membre ayant l’un des rôles participants utilise `/reponse réponse:`.
6. Vérifier que le meneur reçoit bien le DM avec **Valider / Invalider**.
7. Pour tester sans attendre une semaine, un **Admin du jeu** peut utiliser `/cloturer`.

## Données

SQLite est utilisé automatiquement dans `data/scoreboard.db`. Le dossier `data/` est exclu de Git afin de ne pas écraser accidentellement les scores lors d’une mise à jour du code.


## Déploiement sur Synology avec Container Manager

Le projet contient maintenant `Dockerfile`, `compose.yaml` et `.dockerignore`. Aucun port entrant n'est nécessaire.

1. Dans File Station, créer un dossier par exemple `docker/discord-scoreboard`.
2. Décompresser/copier dans ce dossier : `bot.py`, `config.py`, `database.py`, `requirements.txt`, `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env` et le dossier `data`.
3. Copier `.env.example` en `.env`, puis remplacer seulement `DISCORD_TOKEN` par le token réel.
4. Dans Container Manager > Projet > Créer, choisir ce dossier comme chemin de travail et utiliser le fichier `compose.yaml` (ou le renommer `docker-compose.yml` si l'interface l'exige).
5. Construire puis démarrer le projet.
6. Consulter les journaux du conteneur `discord-scoreboard`. Au démarrage réussi, les commandes slash sont synchronisées sur le serveur configuré.

La base SQLite est persistée dans `./data/scoreboard.db` sur le NAS et survit aux reconstructions du conteneur.


## Scoreboard permanent

Un administrateur du jeu peut utiliser `/tableau` dans le canal configuré. Le bot crée un message de classement qui est ensuite modifié automatiquement quand le meneur change, qu’une manche démarre ou se termine, qu’une participation est enregistrée ou qu’un score est corrigé. Le message peut être épinglé manuellement dans Discord.


## Version 0.7.0 — statistiques

- `/score` affiche toujours le classement général.
- `/score joueur:@membre` affiche maintenant ses statistiques sur les manches clôturées : score, rang, participations, réponses trouvées, podiums, manches proposées et captures restées introuvables.
- Les statistiques n'utilisent jamais les réponses d'une manche encore ouverte ou en validation.
- Après validation d'une réponse, le DM du meneur est figé avec le statut **Validée** ou **Invalidée** et les boutons sont retirés.
- Aucun changement de schéma SQLite n'est nécessaire pour cette version.


## v0.7.0 — Résultats de manche

À la clôture, le bot publie désormais un résultat détaillé : jeu révélé, capture, podium 3/2/1, temps écoulé avant chaque bonne réponse du podium, nombre de participants, nombre de tentatives, nombre total de joueurs ayant trouvé et prochain meneur. Si personne ne trouve, le bonus de 2 points du meneur et le tirage du prochain meneur sont indiqués explicitement.


## Version 0.7.1 — terminologie

Le terme **meneur** est désormais utilisé dans toute l’interface et la documentation. La commande correspondante est `/meneur`. Les anciens noms techniques `master_id` restent uniquement dans le schéma SQLite interne afin d’éviter toute migration de la base existante.


## v0.7.3

La commande `/aide` affiche désormais un résumé court des règles du jeu.


## Réinitialisation complète

La commande admin `/reinitialiser` affiche une confirmation avant d'effacer les scores, l'historique, les manches, les tentatives et le meneur. Le scoreboard permanent est conservé et actualisé à vide. Lorsque les tables sont entièrement vides, la numérotation des manches repart à #1.
