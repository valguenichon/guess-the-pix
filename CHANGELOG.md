# Changelog — v1.0.0

## Multi-server architecture

- Added controlled server authorization workflow: `pending` → `approved` → `configured`.
- Rejected guilds now keep a distinct `refused` status; a new request from a previously refused guild explicitly warns the bot owner.
- Added owner-only `/proprietaire` commands to list, approve, reject, block, and unblock guilds.
- New guilds cannot run `/configurer` before owner approval.
- Existing configured guilds are migrated automatically to `configured`.
- Leaving/removing the bot marks the guild inactive and disables its stored game configuration until a new approval/configuration cycle.
- Added first-class support for multiple Discord servers from one bot instance.
- Added per-server configuration for the game channel and optional Game Admin role.
- Added `/configurer` for initial server setup.
- Restored optional admin-role creation during `/configurer`; bot-created roles are always named exactly `Guess the Pix - admin`, while manually selected roles keep their existing name.
- Added `/config statut`, `/config salon`, and `/config role-admin` for server configuration management.
- Existing Administrator and Manage Guild permissions remain valid for game administration.
- Added per-server configuration caching with immediate refresh after configuration changes.

## Server isolation

- Added independent visible round numbering per server.
- SQLite round IDs remain internal while each server can independently have Round #1, #2, and so on.
- Score periods, participants, leaders, scores, attempts, history, and scoreboard state remain isolated by guild.
- Round image caches are now stored in per-server directories to prevent collisions between servers.
- Added feature-flag storage scoped by server for future controlled rollouts.

## Staging and production

- Added `ENVIRONMENT` with `production`, `staging`, and `development` modes.
- Added `COMMAND_GUILD_IDS` for instant guild-scoped command synchronization on one or more staging servers.
- `COMMAND_GUILD_IDS` is now optional in staging/development: every guild actually joined by the bot is synchronized automatically, so adding a test server no longer requires editing `.env` or recreating the container.
- In production, `COMMAND_GUILD_IDS` is ignored and application commands are always synchronized globally.
- Guild-scoped commands are synchronized automatically whenever the bot joins any staging/development server, including servers not pre-listed in the environment.
- A staging server ID may be prepared in `COMMAND_GUILD_IDS` before installation; an inaccessible guild no longer prevents the bot from starting, and synchronization is retried on join.
- Kept `COMMAND_GUILD_ID` as a backward-compatible fallback for older staging configurations.
- Guild-scoped command mentions are now tracked per server so multi-guild staging uses the correct Discord command IDs.
- Production always uses global Discord application commands, independently of `COMMAND_GUILD_IDS`.
- Staging is visibly identified in `/aide`.
- Updated Docker Compose to use relative bind mounts so the same package can run from separate production and staging directories with independent data.
- Standardized Docker naming: default Compose project/service/container name is `guess-the-pix`, and the image is explicitly fixed to `guess-the-pix:1.0.0` in `compose.yaml`; staging can override project/container names to avoid host-level collisions.

## Migration

- Added automatic migration support from the v0.13.x single-server configuration.
- Existing `GUILD_ID`, `GAME_CHANNEL_ID`, and `GAME_ADMIN_ROLE_ID` values are used once to seed the corresponding per-server configuration.
- Existing rounds receive sequential per-server `round_number` values without changing their internal IDs.
- Existing scores, periods, participants, attempts, leader state, history, and scoreboard references are preserved.
- Legacy v0.13.3 round-image cache files are migrated opportunistically into the new per-server cache layout.
- Migration is idempotent and safe to run again after a restart.

## Help

- Simplified `/lancer` documentation in `/aide`.
- Help now explains that `/lancer` accepts either `capture` or `url`, then opens the form for the game name and three hints.
- Unconfigured servers are told to run `/configurer`.

## Direct-message context

- Added the source server name to every game-related direct message.
- Answer-validation embeds now show an explicit `Serveur` field so a leader handling rounds on multiple servers can immediately identify the origin.
- Player verdicts, rank/points notifications, forced-closure notices, pending-review reminders, and new-leader instructions now include the source server.
- Pending-review reminders now use the server-local round number instead of the internal SQLite round ID.

## Validation

- Added a static DM-context test ensuring guild-scoped private notifications always receive a server context.
- Added a two-guild isolation test covering independent round numbering, participants, scores, and guild reset behavior.
- Added a v0.13.3 migration/idempotence test.

## Compatibility

- v1.0.0 is the first stable multi-server release.
- A separate Discord application/token and separate `/data` directory remain strongly recommended for staging.
