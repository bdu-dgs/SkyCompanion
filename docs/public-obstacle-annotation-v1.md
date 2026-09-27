# Public Close-Range Obstacle Dataset Specification v1

This round trains only on public material whose license permits the use. The user's currently playing video is retained as separate development regression material, excluded from public training and not presented as an unseen test. The goal is to improve nearby poles, column shafts, tree trunks, fences, construction obstacles, and rocks; public utility-pole scores cannot replace actual close-range acceptance checks.

The machine-readable specification is `schemas/public-obstacles-v1.json`. Top-level `classes` must accurately list the actual training subset; having six names does not mean usable data exists for all six. The full priority vocabulary is `pole / column / tree_trunk / fence / construction_barrier / rock`. Additional classes with clear source definitions and complete annotations may be retained, using snake_case names and documented source mappings. Tables, chairs, pavilions, and similar objects remain in the current general model and subsequent specifications; missing labels in this round do not make them obstacle-free background.

## Classes and Annotation Scope

| Class | Includes | Do not directly map to this class |
|---|---|---|
| pole | Visible shafts and attached bases of streetlights, signposts, utility poles, and scaffolding poles | Lamp heads, signs, crossarms, whole towers, tree trunks, building columns; bollards require separate review of source definitions |
| column | Visible building or canopy columns and attached bases, including very thick shafts extending outside the image | Overhead beams, wall corners, whole buildings |
| tree_trunk | Main trunk and visible roots; annotate normally even when only a nearby segment remains visible | Canopies, shrubs, whole-tree boxes, distant tangled branches |
| fence | One fence instance or a continuous visible section divided according to a fixed rule, including mesh and posts together | Railing/guardrail is not automatically equivalent; temporary construction barriers belong to construction_barrier |
| construction_barrier | Temporary solid construction enclosures and rigid barricades | Cones, construction barrels, warning tape, permanent walls; quarantine unclear source categories instead of forcing a merge |
| rock | Protruding natural rocks, boulders, and similar solid objects | Road texture, manhole covers, artificial concrete blocks, stone walls; gray color alone does not imply rock |

Model-output aliases (such as pillar→column and boulder→rock) are explicitly listed in the schema and used only to standardize comparisons. **Aliases are not a relabeling tool**: a publisher's `tree` box covering a canopy cannot be renamed `tree_trunk`; an original pole box including a lamp arm cannot be described as already meeting the shaft specification. Preserve `source_label`, original label files, conversion-script version, and `geometry_scope`.

## Geometry, Partial Annotation, and Attributes

- Standard boxes use normalized top-left `x,y,w,h`, taking the smallest bounding box around all **visible parts** of the target and clipping at image edges. Do not guess the complete outline outside the frame, behind walls, or behind pedestrians. A box spanning visible fragments across occlusion may still contain the occluder and is not an exact contour. Do not silently rename amodal source annotations as visible.
- `visible_instance_bbox` describes instance scope; `visible_component_bbox` generated from semantic-mask connected components describes only component scope and may merge multiple trees/poles. Component comparisons cannot claim instance-level detection accuracy. Use `publisher_bbox_unverified` when source scope has not been verified and report the limitation.
- `attributes` records `truncated / occluded / bottom_visible / near_in_image / low_in_image`, allowing null. `near_in_image` describes reviewed close-range image characteristics, not distance ground truth; do not automatically write "1 meter" from box bottom or area alone. Actual `distance_m` may be non-null only when measurement method, coordinate system, time, and source are complete.
- Set per-class, per-image `annotation_coverage` to `complete / partial / unknown`. `reviewed_classes` is a compatibility field listing only completely covered classes; original annotations claimed complete by their publisher still use `published_annotations`, not SkyCompanion human review.
- Use `ignore_regions` for heavy occlusion, unstable distinctions, or unreviewed regions, recording applicable classes and reasons. Do not add ignore regions retrospectively to erase real false positives. Match confirmed positives first during evaluation, then apply ignore to unmatched predictions.
- When some classes/regions are incompletely annotated, unknown predictions do not count as FP; annotated positives may be scored separately as selected-target recall, but full-frame precision must not be reported. Ordinary YOLO loss does not automatically understand ignore or partial status: these images must not be directly exported as complete six-class background training. Complete the annotations, use a validated ignore-aware training method, or isolate a genuinely complete training subset.
- Preserve `assistant_reviewed`, `human_verified`, and `published_annotations` separately; model pseudo-labels are drafts only. Two assistant visual review passes still do not become human_verified.

## Provenance, Grouping, and Freezing

For every image preserve original SHA256, source URL, dataset/version, license/attribution requirements, source split, original annotation digest, video ID, route/location group, and timestamp. Use `unknown:<source>` for unknown locations; do not invent independent locations from filenames. Data publishing only random train/test splits without route information may support public benchmark research, but cannot be described as proven location-independent.

Build connected groups by original video, route, and location before sampling frames. Adjacent frames, day/night versions of the same route, crops of the same target, copies of the same image from different sources, and augmented versions inherit one split. Preserve publisher test data and do not redistribute it into training. Check cross-source duplicates with SHA256 and perceptual-hash candidates; quarantine and record suspected duplicates without presenting hash similarity as confirmed duplication. If publisher splits and known route isolation cannot both be satisfied, quarantine conflicting material or build a new research split with explicit reasons rather than hiding the conflict.

Conservatively group New York development material by the same known route. It may be used for model/parameter selection, but not final blind testing. Freeze new test manifests before training; select input size and thresholds on validation, save the selection record, and only then run test. If the model changes after test inspection, that set becomes regression data and the next round requires new independent acceptance material.

## Separate Acceptance for Names and Path Occupancy

Detection labels answer only "what and where." Independent `path_occupancy` defaults to `unknown`; `image_corridor_overlap` describes only image-region overlap. Use `validated_user_path_conflict` only after validating user position, heading, passage width/margin, target association, and related evidence. Public static object boxes cannot automatically create collision-risk or "path ahead is safe" ground truth.

Study segmentation or depth separately: fix the same clips, path ground truth, and threshold-selection protocol, and record missed/false path-occupancy decisions separately. Adding a model alone is not evidence of improvement. Issue a generic obstacle warning for an unknown class only when valid path-occupancy evidence exists.

## Comparisons and Release Gates

`scripts/evaluate_public_candidate.py` compares current v7 with specialist candidates. First select per-class thresholds on val for classes with actual complete positive annotations, then select input size by macro-average F1 across the six classes with valid coverage. Evaluate test after locking both models and configurations. Comparing independently calibrated configurations differs from comparing identical parameters; report full configurations and weight SHA. `--sizes` specifies candidate sizes; `--baseline-sizes` defaults to the current 960. Fix the evaluation threshold list before running.

Report per-class TP/FP/FN, precision/recall, complete/partial/unknown coverage, misses among annotated nearby targets, truncation/occlusion strata, and publisher annotation scope. For partial images report only annotated-target hits; unknown predictions are not false positives. If near is unannotated, close-range metrics are unavailable; do not substitute all box areas automatically. Warmed-up static batch1 P50/P95/serial FPS exclude capture, transmission, UI, and audio.

Ordinary static public datasets cannot validate false positives per minute, actual first-detection time, longest continuous miss, actual phone processing FPS, actual speech-onset latency, or interruptions per minute. Keep these fields unverified and state the required evidence. Sampled clips with tracks can at most add sampled detection delay, not masquerade as complete continuous temporal acceptance.

This script never deploys. Replacement or controlled combination is a separate decision only after fixed comparisons for the six classes and retained general classes, independent-location close-range scenes, false-positive/miss thresholds, continuous video, and phone/speech field measurements all satisfy pre-agreed gates. If only two classes are covered, report two-class specialist research; do not directly replace the current 115-class model. Preserve old models, configurations, and rollback versions throughout.

## Compatible Manifest Example

```json
{
  "schema_version": "public-obstacles-v1",
  "classes": ["pole", "tree_trunk"],
  "split_provenance": {"kind": "publisher_split", "location_independence": "unknown"},
  "images": [{
    "id": "source:frame-001", "path": "images/frame-001.jpg", "sha256": "<actual-64-character-digest>",
    "split": "train", "source_split": "train", "source_dataset": "<source>",
    "source_revision": "<pinned-version>", "source_url": "<official-original-file>", "license": "<verified-license>",
    "video_group": "unknown:source", "route_group": "unknown:source", "location_group": "unknown:source",
    "review_status": "published_annotations", "reviewed_classes": ["pole"],
    "annotation_coverage": {"pole": "complete", "tree_trunk": "unknown"},
    "annotations": [{"label": "pole", "source_label": "pole", "x": 0.4, "y": 0.0, "w": 0.08, "h": 0.9,
      "geometry_scope": "publisher_bbox_unverified", "attributes": {"near_in_image": null, "truncated": true}, "path_occupancy": "unknown"}]
  }]
}
```

This example can participate in partial-coverage evaluation, but **cannot be exported directly as a complete two-class pole/tree_trunk YOLO training image**.
