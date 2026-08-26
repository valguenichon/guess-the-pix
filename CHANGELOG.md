# Changelog — v0.12.1

## Added

- Added a dynamic **Current settings** section to `/aide`.
- Help now shows the attempt limit currently applied to the active round, or the configured default when no round is active.
- Help now shows the current scoring period and its progress when periods are limited by a number of rounds.
- Help now reminds players of the 7-day maximum round duration and the 24-hour accelerated phase.
- Added a discreet Guess the Pix version number at the bottom of `/aide`.

## Changed

- Slightly shortened the rules summary to keep the complete admin help within Discord's message size limit.
- The Help button uses the same dynamic help content as `/aide`.

## Technical

- No database migration is required.
- No `.env` changes are required.
