# Changelog — v0.13.0

## Added

- Correct answers from **4th place onward now award 1 point**.
- Private correct-answer confirmations now report the player's position and the awarded point for positions beyond the podium.
- Added a persistent reference to the original round message so the bot can retrieve a fresh screenshot attachment URL when needed.

## Changed

- The scoring summary in `/aide` now explicitly states that every correct answer from 4th place onward is worth 1 point.
- Hint messages now remind players that positions from 4th onward award 1 point.
- End-of-round results now indicate that correct answers beyond the podium receive 1 point each.
- Round scoring is recalculated from the authoritative answer timestamps at closure, preserving the existing podium rules while applying the new 1-point rule from 4th place onward.

## Fixed

- Fixed round screenshots potentially disappearing from **hint messages**, **accelerated-mode messages**, and **end-of-round results** because stored Discord attachment URLs can expire.
- The bot now fetches the original round message before publishing these events and uses a fresh attachment URL.
- Rounds already in progress when upgrading from v0.12.x can automatically locate their original round message from channel history when possible.
- The image fix applies identically whether the original screenshot was uploaded directly or provided through an external image URL.
- If the original message or attachment is no longer accessible, the bot falls back to the previously stored image URL.

## Database

- Added `round_message_id` to the `rounds` table.
- Existing databases are migrated automatically.
- No existing scores, rounds, periods, attempts, or statistics are deleted.

## Compatibility

- Based on the single-server v0.12.1 branch.
- No multi-server changes are included.
- No `.env` changes are required.
