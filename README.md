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
- Le podium rapporte 6/5/4, puis 5/4/3, 4/3/2 et 3/2/1 selon les indices révélés.
- **À partir de la 4e place, toute bonne réponse rapporte 1 point.**
- Si personne ne trouve, le meneur gagne 4 points.
- Le classement est organisé par périodes et le nombre d’essais peut être illimité ou limité par l’administration.

## Nouveautés v0.13.x

### 1 point à partir de la 4e place

Le podium conserve son barème progressif en fonction des indices. Tous les joueurs classés à partir de la 4e position reçoivent 1 point lorsqu’ils trouvent le jeu.


### Fiabilité des interactions — v0.13.2

Les interactions susceptibles d’effectuer des opérations plus lentes sont maintenant acquittées immédiatement auprès de Discord. Cela concerne `/passe`, `/designer`, la validation du formulaire `/lancer`, `/periodes` et la confirmation de `/reinitialiser`.

`/passe` utilise en plus un changement de meneur atomique afin d’éviter un double tirage si deux interactions arrivent presque simultanément. Le nouveau meneur tiré au sort est annoncé publiquement dans le salon et reçoit toujours ses instructions en message privé.

`/periodes` calcule désormais la progression de toutes les périodes avec une seule requête agrégée.

### Captures dans les messages de manche — v0.13.1

Les messages différés ne dépendent plus d’une URL CDN Discord pour afficher la capture. Avant de publier un indice, le mode accéléré ou le résultat final, le bot récupère la pièce jointe du message initial puis **réuploade réellement l’image dans le nouveau message**. L’embed référence cette nouvelle pièce jointe avec `attachment://...`.

Le mécanisme est identique pour une capture envoyée directement et pour une image fournie initialement par URL. Pour les manches existantes, le bot peut retrouver le message de lancement dans l’historique du salon lorsque sa référence n’est pas disponible.

## Aide et paramètres

`/aide` affiche les paramètres réellement appliqués : limite d’essais de la manche en cours (ou valeur par défaut), période active et progression, durée maximale de 7 jours, accélération à 24 h et nouveau barème à 1 point à partir de la 4e place.

La version du bot est indiquée discrètement en bas de l’aide.

## Mise à jour

### Depuis v0.13.1

1. Remplacer `bot.py` **et** `database.py`.
2. Redémarrer le conteneur.
3. Vérifier dans les logs :

```text
Scoreboard bot version 0.13.2-interaction-timeouts
```

Aucune migration du schéma SQLite et aucune modification de `.env` ne sont nécessaires. `database.py` doit tout de même être remplacé car cette version ajoute les opérations atomiques et la requête optimisée utilisées par le bot.

### Depuis v0.12.1 ou une version antérieure

Remplacer `bot.py` **et** `database.py`, puis redémarrer le conteneur. Les migrations SQLite introduites par les versions intermédiaires seront appliquées automatiquement.

## Synology

Avec les bind mounts déjà utilisés sur le NAS, aucune reconstruction de l’image n’est nécessaire : remplacez les fichiers Python puis redémarrez simplement le conteneur.
