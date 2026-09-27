# Named obstacle warnings

Historical implementation: the user subsequently requested removal of automatic class names. See [current alert policy](mobile-current-alert-policy.md).

Automatic obstacle warnings and the repeat command now include the detected label alongside the existing direction. Standard example: “Caution left. Person. Check your path.” Minimal preferences retain the name; detailed and urgent speech retain their context/actions.

Ordinary alerts use the selected event’s consistent detected label, not the unrelated dominant assessment or another detection. Missing or inconsistent labels fall back to “Obstacle”. Repeat uses the current assessment and its own label, preserving freshness checks.

Rear-following speech names only objects in the announced front/near-side region, excludes the selected wearer, and preserves the existing movement decision. Naming requires confidence at least 0.55 in this mode; lower-confidence detections continue to block routes but use the generic noun. Up to two distinct class names are spoken; larger sets add “and other obstacles”. Path-boundary warnings say “Path boundary”, rather than inventing an obstacle. Tracking loss retains its existing position message. Changing only an object name does not cut off a current walking instruction.

No detector weights, class order, preprocessing, inference thresholds, risk admission, direction geometry, cooldown or deduplication settings were changed. Recording/audio/crop/navigation components remain intact. Naming is a model prediction, not a separately verified object identity.

Validation: 139 CaptureCore tests, including direction/name pairing, ordinary/minimal/detailed/urgent speech, walking front/side labels, own-body exclusion, low-confidence fallback and legacy optional-field decoding. Release iPhone build and installation are tracked in report.json. Physical listening verification remains pending.
