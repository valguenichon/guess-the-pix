# Changelog — v0.13.2

## Fixed

- Hardened Discord interaction handling to prevent "The application did not respond" errors when commands perform slower API or database work.
- `/passe` now acknowledges the interaction before participant lookup, leader reassignment, DM delivery, and scoreboard refresh.
- Added an atomic leader handoff for `/passe` so two near-simultaneous requests cannot select two different leaders.
- `/designer` now acknowledges the command before sending the new leader's private instructions.
- The `/lancer` modal now acknowledges submission before reading or downloading the round image, including external URLs that may take several seconds to respond.
- `/periodes` now acknowledges immediately and retrieves period progress in a single aggregated query instead of one query per period.
- The destructive `/reinitialiser` confirmation button now acknowledges the click before performing the database reset.

## Changed

- `/passe` now publishes a clear public **New leader** message naming the randomly selected participant.
- The selected leader still receives the usual private `/lancer` and `/passe` instructions.

## Compatibility

- No database schema migration is required when upgrading from v0.13.1.
- No `.env` changes are required.
- Replace both `bot.py` and `database.py`, then restart the container.

---

# Changelog — v0.13.1

## Fixed

- Reworked screenshot handling for delayed round messages after the v0.13.0 URL refresh approach proved unreliable.
- Hint messages, accelerated-mode messages, and end-of-round results now receive a **new Discord file upload** containing the original round screenshot.
- Embeds now reference the freshly uploaded file through `attachment://...` instead of depending on a Discord CDN attachment URL.
- The bot fetches the original round message and downloads its attachment bytes immediately before reposting the screenshot.
- Added a media-proxy fallback if the direct attachment download fails.
- Improved recovery for active rounds by searching channel history whenever the stored original message ID is missing or no longer resolves.
- The previous stored attachment URL remains only as a last-resort compatibility fallback.

## Compatibility

- No database migration is required when upgrading from v0.13.0.
- No `.env` changes are required.
- The fix works with screenshots originally uploaded directly and screenshots originally supplied through an external URL.

---

# Changelog — v0.13.0

## Added

- Correct answers from **4th place onward now award 1 point**.
- Private correct-answer confirmations now report the player's position and the awarded point for positions beyond the podium.
- Added a persistent reference to the original round message.

## Changed

- The scoring summary in `/aide` explicitly states that every correct answer from 4th place onward is worth 1 point.
- Hint messages remind players that positions from 4th onward award 1 point.
- End-of-round results indicate that correct answers beyond the podium receive 1 point each.

## Database

- Added `round_message_id` to the `rounds` table.
- Existing databases are migrated automatically.
