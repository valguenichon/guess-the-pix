# v1.0.2 — Informations joueurs

- Une deuxième réponse est désormais refusée tant qu'une réponse précédente du même joueur attend la validation du meneur.
- L'annonce publique du mode accéléré est rendue plus robuste : si l'envoi avec la capture échoue, le bot retente sans image puis, si nécessaire, en texte seul.
- Les annonces d'indices utilisent désormais le même mécanisme de repli et ne sont marquées comme publiées qu'après un envoi réussi.
- Les annonces de fin de manche et de fin de période ne peuvent plus interrompre la finalisation si Discord refuse une image ou un embed.

---

# v1.0.1 — Informations joueurs

Correctif technique de maintenance : suppression possible des anciennes commandes Discord locales restées après une migration v0.13.3 → v1. Le fonctionnement du jeu et les données des joueurs ne changent pas.

---

# v1.0.0 — Informations joueurs

Cette version est principalement technique : Guess the Pix peut désormais fonctionner sur plusieurs serveurs Discord tout en gardant les parties, scores et réglages complètement séparés.

Pour les joueurs, le fonctionnement du jeu reste volontairement le même. La principale modification visible concerne l’aide : `/lancer` est maintenant expliqué plus simplement et la version de staging est clairement identifiée lorsqu’elle est utilisée sur le serveur de test.
