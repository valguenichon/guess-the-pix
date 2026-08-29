# Guess the Pix — Discord bot v0.13.2

Bot Discord mono-serveur pour un jeu de découverte de jeux vidéo à partir de captures d’écran.

## Principales règles

- Les joueurs s’inscrivent avec `/participer`.
- Le meneur lance une manche avec `/lancer` et fournit une capture, la réponse et 3 indices.
- Une manche dure 7 jours maximum.
- Les indices sont initialement prévus à J+2, J+4 et J+6.
- La première bonne réponse validée déclenche le mode accéléré : 24 h maximum restantes, sans dépasser la fin initiale.
- Les réponses sont privées et arbitrées par le meneur.
- Le verdict est communiqué immédiatement au joueur après validation.
- Le scoring du podium reste 6/5/4, puis 5/4/3, 4/3/2 et 3/2/1 selon les indices révélés.
- Si personne ne trouve, le meneur gagne 4 points.

## Nouveautés v0.12.1

### Périodes de classement

Le classement est maintenant organisé par périodes. Par défaut, la période ne se termine jamais automatiquement.

Commandes publiques :

- `/score` — période actuelle
- `/score periode:N` — période choisie
- `/score joueur:@membre periode:N` — statistiques d’un joueur sur une période
- `/score-global` — classement toutes périodes confondues
- `/periodes` — liste des périodes

Commandes admin :

- `/periode statut`
- `/periode config` → **Jamais** ou **Nombre de manches**

Lorsqu’une période limitée se termine, son classement final est publié puis la période suivante commence à zéro. L’historique n’est jamais supprimé.

### Nombre d’essais

Commandes admin :

- `/essais statut`
- `/essais config` → **Illimité** ou **Nombre d’essais**

La valeur est copiée dans la manche au moment de `/lancer`. Une modification ultérieure ne change donc pas une manche en cours.

### Verdict des réponses

Après arbitrage :

- une mauvaise réponse indique le nombre d’essais restants si la limite est active ;
- une bonne réponse confirme que le jeu a été trouvé ;
- dès que les réponses antérieures sont arbitrées et que le rang ne peut plus changer, le bot confirme la position et les points du joueur en privé.

Les points ne deviennent visibles sur le classement public qu’à la clôture de la manche.

### Meneur

Chaque nouveau meneur reçoit un DM indiquant dynamiquement le nom du salon du jeu et les deux options :

- `/lancer`
- `/passe`

## Mise à jour depuis v0.11.x

1. Sauvegarder `data/scoreboard.db` par précaution.
2. Remplacer `bot.py` et `database.py`.
3. Redémarrer le conteneur.
4. Vérifier dans les logs :

```text
Scoreboard bot version 0.12.1-periods-attempts
```

La migration SQLite est automatique. Aucune modification de `.env` n’est nécessaire.

## Synology

Avec les bind mounts déjà utilisés sur le NAS, aucune reconstruction de l’image n’est nécessaire : remplacez les fichiers Python puis redémarrez simplement le conteneur.


## Aide dynamique

`/aide` affiche désormais les paramètres réellement appliqués : limite d’essais de la manche en cours (ou valeur par défaut), période active et progression, durée maximale de 7 jours et accélération à 24 h. La version du bot est indiquée discrètement en bas de l’aide.
