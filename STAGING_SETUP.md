# Staging setup — v1.0.0

1. Create a separate Discord application/bot for staging and add it only to the test server(s).
2. Create `/volume1/docker/guess-the-pix-staging/` on the Synology NAS.
3. Copy the release files into that directory.
4. Create `.env` from `.env.example` with:

```env
COMPOSE_PROJECT_NAME=guess-the-pix-staging
CONTAINER_NAME=guess-the-pix-staging
DISCORD_TOKEN=<staging token>
DATABASE_PATH=data/scoreboard.db
ENVIRONMENT=staging
COMMAND_GUILD_IDS=
# Facultatif mais recommandé pour un staging déterministe :
BOT_OWNER_USER_ID=<your Discord user ID>
ROUND_DURATION_DAYS=7
```

5. Start the staging Compose project. Its project/container names will be `guess-the-pix-staging`; the image remains explicitly named `guess-the-pix:1.0.0` by `compose.yaml`.
6. Existing configured staging servers are preserved automatically. For a brand-new test server, verify the authorization workflow first:

```text
/proprietaire serveurs
/proprietaire autoriser serveur_id:<server ID>
```

Before authorization, `/configurer` must be refused. After authorization, an administrator of that server runs:

```text
/configurer salon:#guess-the-pix role_admin:@Game Admin
```

The admin role is optional. An existing role can be selected, or the bot can create its dedicated role with `creer_role_admin:Yes`. Roles created by the bot are always named exactly `Guess the Pix - admin`; manually selected roles keep their existing name. In staging, `COMMAND_GUILD_IDS` is optional. Every server the staging bot actually joins receives guild-specific commands automatically, including servers added after startup. You may still list IDs in `COMMAND_GUILD_IDS` to pre-sync known test servers, but adding a new server never requires editing `.env` or recreating the container.

7. Verify:

```text
/config statut
/aide
```

`/aide` should show `Guess the Pix • v1.0.0 • STAGING`.

## Recommended staging checks

- Register at least two participants.
- Designate a leader and launch a round.
- Submit/review correct and incorrect answers.
- Trigger accelerated mode.
- Verify hints and locally cached images.
- Close the round and verify score/period/history.
- Restart the container during a round and verify persistence.
- Add the staging bot to a second disposable server and confirm that participants, Round #1, scores and configuration are independent.

## Authorization workflow checks

- Add the bot to a new disposable server: it must become `pending`.
- Verify the bot owner receives the request DM when DMs are available.
- Verify the server owner receives the pending-status DM when DMs are available.
- Verify game commands are blocked before configuration.
- Run `/proprietaire autoriser`, then `/configurer`: status must become `configured`.
- On another disposable server, test `/proprietaire refuser`: the bot must leave and remain listed as `refused` / « refusé ». Reinvite it and verify the bot owner is warned that the server was previously refused.
- Reinvite it, then test `/proprietaire bloquer`: the bot must leave and immediately leave again on a new invite.
- Run `/proprietaire debloquer`, reinvite it, and verify a new `pending` request is created.
