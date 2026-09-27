# English-only app update — 2026-09-26

App-owned UI copy, speech feedback, voice-command help, source comments, legacy iOS connection messages and mobile documentation now use English. Bundle development/localization language is English. Swift identifiers were already English; stable bundle IDs, protocol keys, model metadata and stored user data retain their meanings.

## Commands

Start voice assistance first, then say:

- SkyCompanion, are you working? / SkyCompanion status
- SkyCompanion describe
- SkyCompanion repeat
- SkyCompanion mute / SkyCompanion unmute / SkyCompanion resume alerts
- SkyCompanion pause analysis / SkyCompanion resume analysis
- SkyCompanion path
- SkyCompanion stop listening
- SkyCompanion trip summary / SkyCompanion ask assistant why

Commands require the SkyCompanion or Sky Companion wake phrase and an accepted whole utterance. Previous Mandarin aliases are no longer offered or parsed by the mobile app. English recognition remains local; missing offline resources cause an explicit failure, never cloud fallback.

## Voice preferences

Settings → English voice lists installed non-novelty English voices. Automatic selection prefers available Premium, then Enhanced, then Standard. A saved non-English or no-longer-installed voice ID migrates to Automatic; a valid installed English selection remains. Existing speech-rate preferences remain unchanged. Migration does not download a new voice or change its acoustic quality.

## Scope and preserved records

Translations cover native app/extension source and resources, iOS README, current mobile guides and historical iOS/voice architecture documents. Historical measurements and validation boundaries are retained and labelled as milestone evidence. Desktop/backend work outside the mobile scope is unchanged. Existing messages, original feedback, evidence/log files and image attachments are not rewritten. Apple-owned permission dialogs, errors and external apps may follow system language; they are not app-authored translations.

## Verification

- 106 CaptureCore tests passed, including English status/recovery parsing, complete-utterance rejection and unchanged health/freshness behavior.
- Legacy iOS Swift files passed syntax parsing.
- Release signed iPhone build and Debug simulator build passed. The first Release attempt found an invalid `Self` stored-property initializer reference; this was corrected to the concrete class name before successful builds.
- Source/resource/document audit: 85 existing relevant files scanned, no Han text remaining. Both compiled bundles' English strings and app language declaration checked. See `validation/mobile-2026-09-26/english/report.json` and `bundle.json`.
- The simulator was launched with Chinese preferred language and the old `auto.zh-CN` voice setting. Actual Settings rendering showed English automatic voice and Samantha en-US; screenshot `validation/mobile-2026-09-26/english/settings.png`.
- Final signed build installed successfully on the connected iPhone 15 Plus. Open the app manually to use it.
- This update does not claim a new acoustic, voice-recognition-rate, drone, performance or accessibility field acceptance.

Build/test logs: `/tmp/sky-english-tests.log`, `/tmp/sky-english-build.log`, `/tmp/sky-english-simulator-build.log`. Physical installation receipt: `/tmp/sky-english-install.json`.
