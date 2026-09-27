# Short alerts and rear-following mode

2026-09-26: Two-part prompts follow the user's deployment assumption: the drone stays behind the user and faces the user's walking direction.

| Current observation | Spoken prompt |
|---|---|
| Front obstacle, left corridor available | Caution front. Keep left. |
| Front obstacle, right corridor available | Caution front. Keep right. |
| Near-left obstacle, complete front corridor available | Caution left. Go straight. |
| Near-right obstacle, complete front corridor available | Caution right. Go straight. |
| Front obstacle, both alternatives blocked or insufficient evidence | Caution front. Check your path. |
| Person or region tracking unavailable | Position unknown. Check your path. |
| No currently relevant obstacle | No automatic announcement |

Open Settings → Depth and path testing → Select person and confirm path. Select the user, confirm the entire traversable region and confirm **Drone follows behind, facing my walking direction** before resuming. This option defaults on for a new setup in the requested deployment, but still requires explicit confirmation. Existing ordinary-region configurations are not silently upgraded.

Front and near-side zones are relative to the selected person's ground-contact approximation, rather than the whole image's left/center/right divisions. Person width defines image corridors with a margin. The entire candidate path from the feet must remain within the confirmed region and avoid detected obstacles. The followed user is excluded as their own obstacle; other people still block corridors. If both sides are available, retain the previous viable direction; initially prefer the larger boundary margin, with left as a tie-breaker.

Movement instructions require three fresh observations spanning at least 700 ms. Persistent states are not repeated. Corridor changes revoke the old movement instruction immediately, request a path check, and wait for confirmation before giving a new direction. Such changes bypass the ordinary eight-second interval. Ordinary descriptions and command replies retain their existing protection; an invalidated movement instruction can be cancelled while playing. Repeat rechecks fresh evidence.

Disappearing obstacles do not establish a clear corridor. Loss of a previously blocking target downgrades guidance to a path check and requires reselection/confirmation. Invalid boundaries, leaving the region or insufficient body-width clearance do not force a left/right instruction. Without confirmed rear-following mode, ordinary alerts are `Caution left/right/front. Check your path.` in camera coordinates.

## Limits and checks

This experimental logic uses manually confirmed regions and monocular images. It has no measured metric clearance, three-dimensional ground reconstruction or automatic body heading. The camera must remain unmirrored and behind the user; reconfirm after a turn, side view or camera-heading change. Registration requires global and within-region consistency; corner motion of roughly 10% of the reference frame causes degradation. Registration is not road-safety certification.

Unit coverage includes left/right alternatives, side-obstacle straight-ahead guidance, front priority, both sides blocked, narrow regions, wearer exclusion, stale/wrong frames, person loss, obstacle disappearance, repeat suppression and revoked instructions. Synthetic registration includes changed-ground rejection. Controlled drone-video tests with a helper are still needed for region choice, false alerts, turning and actual speech. Software tests do not establish independent street-crossing safety.
