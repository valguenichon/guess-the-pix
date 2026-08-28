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
