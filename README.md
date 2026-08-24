# Scoreboard Discord — jeu de capture d’écran

Bot Discord pour un jeu hebdomadaire de découverte de jeux vidéo à partir d’une capture d’écran.

## Règles implémentées

- Le meneur lance une manche avec `/lancer` en joignant une image ou en fournissant une URL publique d’image.
- Il saisit le nom du jeu et trois indices dans un formulaire privé au lancement.
- La manche reste ouverte **7 jours maximum** (168 heures).
- Les utilisateurs s’inscrivent avec `/participer`. Seuls les participants inscrits peuvent répondre et être tirés au sort.
- Chaque nouveau message de manche propose quatre boutons persistants : **🎮 Participer**, **💡 Répondre**, **🏆 Classement** et **❓ Aide**.
- **Participer** inscrit directement le membre ; si celui-ci est déjà inscrit, le bot le lui indique en privé.
- **Répondre** renvoie en privé vers la commande `/reponse` ; le texte de la réponse reste saisi via la commande slash.
- **Classement** et **Aide** affichent leurs informations en réponse éphémère sans encombrer le salon.
- Les joueurs répondent directement avec `/reponse` ; le texte de la réponse n’est jamais publié dans le canal.
- Chaque tentative déclenche immédiatement un message privé au meneur avec les boutons **Valider** et **Invalider**.
- Le joueur sait seulement que sa réponse a été examinée ; le verdict reste secret jusqu’à la clôture.
- Plusieurs tentatives sont possibles.
- Pour chaque joueur, l’heure de sa première tentative validée correcte détermine son rang.
- Tant qu’aucune bonne réponse n’est validée, les trois indices sont prévus à J+2, J+4 et J+6 et la manche se termine à J+7.
- Dès la **première bonne réponse validée**, le jeu passe en **mode accéléré** : la nouvelle échéance est fixée à 24 heures maximum après cette validation, sans jamais dépasser J+7.
- Les indices encore cachés sont alors répartis dans le temps restant et peuvent être publiés plus tôt ; un indice n’est jamais repoussé par l’accélération.
- Le déclenchement des 24 h repose sur l’heure de validation, tandis que le classement et le scoring conservent l’heure d’envoi réelle de chaque réponse.
- À l’échéance effective, les nouvelles réponses sont bloquées.
- S’il reste des réponses en attente de validation, le résultat attend leur arbitrage par le meneur.
- Le podium vaut **6/5/4** avant tout indice, puis **5/4/3**, **4/3/2** et enfin **3/2/1** après le troisième indice.
- Le barème appliqué dépend des indices réellement publiés au moment de la première bonne réponse de chaque joueur.
- Si personne ne trouve, le meneur gagne **4 points**.
- Le premier devient le prochain meneur.
- S’il utilise `/passe`, un participant inscrit est tiré au sort en excluant le gagnant et le meneur de la manche précédente.
- Si personne n’a trouvé, le prochain meneur est tiré automatiquement en excluant le meneur sortant.
- Les comptes bots sont toujours exclus des tirages.

## Commandes

### Joueurs

- `/aide` — afficher les commandes disponibles
- `/participer` — s’inscrire au jeu
- `/quitter` — se désinscrire du jeu sans effacer son historique ni ses scores
- `/participants` — afficher la liste des participants actifs ; le meneur actuel est identifié
- `/reponse` — envoyer une réponse secrète au meneur ; réservé aux participants inscrits
- `/score` — afficher le classement général
- `/score @joueur` — afficher le score d’un joueur
- `/meneur` — afficher le meneur actuel
- `/historique` — afficher les dix dernières manches terminées

### Meneur

- `/lancer image:...` ou `/lancer url:...` — lancer une manche et saisir les trois indices
- `/passe` — passer la main avant le lancement de sa manche et déclencher un tirage

### Administration

Ces commandes sont accessibles aux membres possédant le rôle **Admin du jeu** (`1540752051783475372`). Par sécurité, les membres ayant la permission Discord **Administrateur** ou **Gérer le serveur** y ont également accès :

- `/designer @joueur` — désigner manuellement le prochain meneur ; le membre doit être inscrit au jeu
- `/corriger @joueur points:` — ajouter ou retirer des points
- `/cloturer` — fermer immédiatement les réponses ; les résultats ne sont publiés qu’après validation des réponses encore en attente

### Boutons persistants des manches

Sous chaque nouveau message de manche :

- **🎮 Participer** — équivalent direct de `/participer`
- **💡 Répondre** — affiche en privé un lien vers `/reponse`
- **🏆 Classement** — affiche le classement général en privé
- **❓ Aide** — affiche `/aide` en privé

Les boutons utilisent des identifiants stables et leur vue est réenregistrée au démarrage du bot. Ils continuent donc à fonctionner après un redémarrage du conteneur.

## Installation

Python 3.11 ou plus récent est recommandé.

### 1. Créer le bot Discord

Dans le Discord Developer Portal :

1. créer ou ouvrir l’application du bot ;
2. récupérer le token du bot ;
3. ne jamais publier ou partager ce token.

Le bot n’utilise plus les rôles Discord pour gérer les participants et ne nécessite donc plus **Server Members Intent** pour cette fonction.

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
GUILD_ID=
GAME_CHANNEL_ID=
GAME_ADMIN_ROLE_ID=
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
3. Les joueurs souhaitant participer utilisent `/participer`.
4. Un membre ayant le rôle **Admin du jeu** utilise `/designer @joueur` pour choisir le premier meneur parmi les participants inscrits.
5. Le meneur utilise `/lancer`, fournit une image ou une URL, puis saisit le jeu et les trois indices. La manche dure 7 jours maximum et s’accélère à 24 h maximum dès la première bonne réponse validée.
6. Un autre participant utilise `/reponse`.
7. Vérifier que le meneur reçoit bien le DM avec **Valider / Invalider**.
8. Pour tester sans attendre une semaine, un **Admin du jeu** peut utiliser `/cloturer`.

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

Depuis la v0.7.0, la clôture publie un résultat détaillé : jeu révélé, capture, podium, temps écoulé avant chaque bonne réponse du podium, nombre de participants, nombre de tentatives, nombre total de joueurs ayant trouvé et prochain meneur. Le barème actuel est décrit dans la section de la version la plus récente ci-dessous.


## Version 0.7.1 — terminologie

Le terme **meneur** est désormais utilisé dans toute l’interface et la documentation. La commande correspondante est `/meneur`. Les anciens noms techniques `master_id` restent uniquement dans le schéma SQLite interne afin d’éviter toute migration de la base existante.


## v0.7.3

La commande `/aide` affiche désormais un résumé court des règles du jeu.


## Réinitialisation complète

La commande admin `/reinitialiser` affiche une confirmation avant d'effacer les scores, l'historique, les manches, les tentatives et le meneur. Le scoreboard permanent est conservé et actualisé à vide. Lorsque les tables sont entièrement vides, la numérotation des manches repart à #1.


## Version 0.9.0 — indices progressifs

- Le meneur saisit trois indices lors du lancement de la manche.
- Ils sont publiés automatiquement à J+2, J+4 et J+6.
- Le barème du podium évolue selon le nombre d’indices déjà révélés : 6/5/4, puis 5/4/3, 4/3/2 et 3/2/1.
- Le moment réellement enregistré de publication des indices sert au calcul, afin de rester équitable après une éventuelle indisponibilité du bot.
- Si personne ne trouve au bout de 7 jours, le meneur gagne 4 points.
- Le scoreboard indique le nombre d’indices révélés et le délai avant le prochain indice.


## Version 0.10.0 — inscription volontaire

- Le salon reste visible à tous, mais seuls les utilisateurs inscrits avec `/participer` peuvent utiliser `/reponse`.
- `/quitter` désactive la participation sans effacer les scores ni l’historique du joueur.
- Les tirages aléatoires utilisent uniquement les participants actuellement inscrits.
- Un meneur ne peut pas quitter le jeu pendant sa manche ; s’il est désigné pour la manche suivante, il doit d’abord utiliser `/passe`.
- `/designer` ne peut désigner qu’un participant inscrit.
- Le scoreboard affiche désormais le nombre de participants inscrits.
- `/aide` présente le parcours d’inscription et les nouvelles commandes.
- Les anciens `PARTICIPANT_ROLE_IDS` ne sont plus utilisés.


## Version 0.11.0 — mode accéléré

- Une manche conserve une durée maximale de 7 jours.
- La première réponse validée correcte déclenche automatiquement le **mode accéléré**.
- La nouvelle fin est fixée à **24 heures maximum après cette validation**, sans jamais dépasser la fin initiale à J+7.
- Les indices non encore révélés sont redistribués uniformément dans le temps restant ; leur horaire normal J+2/J+4/J+6 reste prioritaire s’il est plus proche.
- Les horaires réellement publiés des indices continuent de déterminer le barème 6/5/4 → 5/4/3 → 4/3/2 → 3/2/1.
- Le podium reste classé selon l’heure d’envoi des réponses, indépendamment de l’ordre dans lequel le meneur les valide.
- Un message public anonyme annonce le passage en mode accéléré et sa nouvelle échéance.
- Le scoreboard affiche le mode accéléré, la nouvelle fin et le prochain indice recalculé.

## Version 0.11.1 — boutons de manche

- Chaque nouveau message de manche affiche quatre boutons persistants : **Participer**, **Répondre**, **Classement** et **Aide**.
- **Participer** inscrit immédiatement le membre et répond « Tu participes déjà. » si nécessaire.
- **Répondre** renvoie en privé vers la commande `/reponse` tout en conservant la saisie via slash command.
- **Classement** affiche le scoreboard en réponse éphémère.
- **Aide** affiche la même aide que `/aide` en réponse éphémère.
- Les boutons restent actifs après un redémarrage du bot grâce aux vues persistantes Discord.

