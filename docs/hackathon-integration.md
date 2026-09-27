# Hackathon integration

The native mobile application, real-time backend, web monitor, deployment helpers,
model conversion tools, tests, design assets and project documentation are now
contained in this checkout. The original development checkout was left unchanged.
The preparation phase did not commit or push. This handoff is now prepared for publication to `bdu-dgs/SkyCompanion` on `main`.

## Project identity and language

All application source paths, project identifiers, environment-variable prefixes,
local protocol names, service names and visible copy use SkyCompanion. The mobile
project is `ios/SkyCompanionCapture.xcodeproj`; its main scheme is `SkyCompanion`.
The default app bundle identifier is `com.stanley.skycompanion.capture`.

Documentation, comments, configuration descriptions and interface text are English.
The Photon preference parser and correction commands accept English commands.
Legacy locale fields remain readable for stored-record compatibility. The `zh`
field in historical class schemas remains as a compatibility key but contains an
English display label; model class IDs, class order and prompts are unchanged.

Renaming the bundle identifiers creates a separate app identity. Configure your
own signing team before installing. This task built without signing and did not
install, replace or launch the phone app. Existing phone pairing and account
credentials were not copied.

## Mobile build

The two currently selected Core ML packages have been copied locally with their
original bytes and verified against their manifests. They remain Git-ignored.

```sh
python3 scripts/prepare_mobile_app.py
xcodebuild -project ios/SkyCompanionCapture.xcodeproj \
  -scheme SkyCompanion -configuration Release \
  -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/skycompanion-build CODE_SIGNING_ALLOWED=NO build
```

Preparation generates a new private `ios/Shared/DevicePairing.json` and updates the
project references. This file is ignored by Git. Public clones need the matching
model packages before preparation; no model download release has been published.

## Backend and web

See [desktop and mobile setup](desktop-and-mobile-guide.md) and
[live testing](live-testing.md). Create a new `backend/.venv` and install the
requirements appropriate to the selected workflow. Reinstall frontend dependencies
with `npm ci` in `frontend/` and Photon dependencies in `skycompanion/`.

Local desktop model profiles and offline warning audio have also been copied.
Eleven desktop checkpoint archives contained old project paths in metadata. Their
archive names and metadata paths were normalized; every tensor-storage entry was
verified byte-for-byte unchanged. Updated artifact hashes are recorded in
`checkpoint-metadata-normalization.json`. Current mobile model packages were not
modified.
They do not depend on paths in the original checkout. Private cloud configuration,
model-provider caches and virtual environments were not transferred. Research
experiments that reference external screenshots or public datasets require those
inputs to be supplied separately; they are not runtime dependencies of the app.

## Training data and media

Raw training footage stays local and is excluded from Git, including `videos/`,
`local_training/`, `samples/local/` and raw video extensions. Intermediate
`local_predictions/` outputs also stay local; this includes older original-language
annotated images, duplicate renders and diagnostic dumps. Existing local files
were not deleted. Final English demo videos can be selected explicitly in a later
publication step; this task does not stage any video or publish any asset.

The 72-class training result remains the final epoch-15 checkpoint. No training,
held-out inference, accuracy evaluation or model replacement was performed here.
Translating display metadata changes schema-file hashes, so existing immutable
training exports must continue to use their own pinned schemas. Export a new
version when using the English source schema; do not rewrite old audit hashes.

## Historical evidence

Existing reports, logs and crash records are archival evidence from earlier
development. Their project references and human-readable messages were normalized
for this English handoff. They are not fresh measurements of this renamed build,
and historical source hashes are not hashes of the renamed source. Current copy
hashes are listed in `migration-manifest.json`; fresh checks are recorded separately
in `integration-verification.json`.

The original checkout, private runtime state, original training footage, archived
training runs and compiled model data were not rewritten. Ordinary English words
such as `evaluate`, third-party identifiers and cryptographic checksums retain
their original spelling.
