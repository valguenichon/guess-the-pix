# Changelog

## v0.11.1 — Boutons persistants

- Ajout de quatre boutons sous chaque nouveau message de manche : **🎮 Participer**, **💡 Répondre**, **🏆 Classement** et **❓ Aide**.
- **Participer** permet de s’inscrire sans connaître la commande `/participer` et indique « Tu participes déjà. » aux membres déjà inscrits.
- **Répondre** affiche en privé un accès à `/reponse` ; la réponse continue d’être saisie avec la commande slash.
- **Classement** affiche le classement général en réponse éphémère.
- **Aide** affiche la même aide que `/aide` en réponse éphémère.
- Les boutons sont persistants et restent fonctionnels après un redémarrage du bot.
- `/aide` documente désormais les actions disponibles via les boutons.

## v0.11.0 — Mode accéléré

- Une manche reste ouverte 7 jours maximum.
- La première bonne réponse validée déclenche automatiquement le mode accéléré.
- La nouvelle échéance est fixée à 24 heures maximum après cette validation, sans jamais dépasser la fin initiale à J+7.
- Les indices non encore révélés sont redistribués uniformément dans le temps restant.
- Un indice n’est jamais repoussé : son horaire normal J+2/J+4/J+6 est conservé s’il est plus proche.
- Le barème reste 6/5/4, 5/4/3, 4/3/2 puis 3/2/1 selon le nombre d’indices réellement publiés au moment de la réponse.
- Le classement reste basé sur l’heure d’envoi des réponses et non sur leur ordre de validation.
- Un message public anonyme annonce le passage en mode accéléré.
- Le scoreboard affiche le mode accéléré, la nouvelle échéance et le prochain indice recalculé.
- Les résultats indiquent si le mode accéléré a été déclenché.
