# ROADWork Public Construction-Obstacle Data Import (2026-09-26)

Purpose of this round: train a research candidate using public construction scenes annotated by their authors. This supplements construction barriers, construction fences, cones, and barrels; it does not establish that nearby pole, trunk, and rock issues are solved and is not phone/walking-risk acceptance.

## Sources, Licenses, and Exclusions

- Author repository: <https://github.com/anuragxel/roadwork-dataset>
- Original data: <https://huggingface.co/datasets/anuragxel/roadwork-dataset>
- Pinned HF revision: `397741364934749644e47fdc1a7bc670f830b65a`.
- The licensing README is pinned to Git commit `f32fd3ce00acf379862d6e6abd10a015c534644b`, with a local copy preserved.
- The author's README states ODC-By 1.0 for core data and MIT for code. Preserve the Ghosh et al., ROADWork, ICCV 2025 citation, official README, and provenance.
- **Exclude** `discovered_images.zip`, `discovered_subsets_with_annotations.zip` (BDD/Mapillary material has different licenses), and the `german/` extension (separately CC-BY-NC-SA 4.0).
- Read only `annotations.zip`, `roadwork_raw_meta.zip`, and selected ZIP members of `images.zip`. The full 10.6 GB image archive was not downloaded.

The annotation archive's local SHA256 was checked against the publisher's LFS digest:
`34d54b0a68648f901ac5f5e095b0e2fa82aa8177e80bb27b28c0f9b92efdde11`.

The publisher's full image-archive SHA256 is recorded only; because the entire archive was not downloaded, **no local full-archive verification was performed**. Each selected image was verified against ZIP CRC32, uncompressed size, and decoded dimensions, with a local SHA256 and original member name recorded.

## Classes and Annotation Scope

| Official ID / name | Training class for this round | Scope |
|---|---|---|
| 3 / Cone | `traffic_cone` | Cones, kept separate |
| 4 / Fence | `construction_fence` | Construction fences; no claim of complete ordinary roadside/park fence annotation |
| 5 / Drum | `construction_barrel` | Construction barrels; not merged into cones |
| 6 / Barricade | `construction_barricade` | Official barricade class, kept separate from barrier |
| 7 / Barrier | `construction_barrier` | Official barrier class |

The `Fence` scope correction comes from an actual spot check: ordinary black railings in `pgh04_1151.JPG` lack corresponding fence annotations, while construction facilities are annotated. Unannotated ordinary railings in this dataset cannot be treated as negatives for general `fence`. If the baseline lacks an exact `construction_fence` class, report the gap rather than arbitrarily renaming `fence` to manufacture a comparison.

Initial spot-check contact sheet: `backend/data/obstacle_dataset/public-roadwork-v1/publisher-label-spotcheck.png`. Only a few samples were viewed; **this does not mean the entire dataset was independently reviewed**. Training and evaluation still use author labels.

Vertical Panel / Tubular Marker were not renamed `pole`; source annotations for other official classes such as signs, lights, and workers are fully preserved but excluded from this round's five-class vocabulary. Poles, building columns, tree trunks, rocks, general fences, and similar classes are unknown labels in this import, so this data cannot directly become a fully annotated training set for them.

Each image has `review_status=published_annotations`. `reviewed_classes` indicates the publisher's five-class annotation scope, not SkyCompanion independent human review; `independent_review_status` is `not_independently_reviewed`. Do not change it to `human_verified`.

## Fixed Splits

First read the author's `instances_train_pittsburgh_only.json` / `instances_val_pittsburgh_only.json`. Training sources contain only Pittsburgh; the author's validation sources from other cities are divided by city into SkyCompanion val / test. Seed `20260926` is fixed, and splitting does not inspect model predictions or results.

- train: Pittsburgh, target 600 images.
- val: Boston, Chicago, Columbus, Indianapolis, Minneapolis, Philadelphia, Phoenix, San Francisco, Washington DC, target 120 images.
- test: Charlotte, Denver, Detroit, Houston, Jacksonville, Los Angeles, New York City, San Antonio, target 120 images.

Actual import completed: 600 / 120 / 120 images; 840 originals total 1,194,662,917 bytes. Final manifest SHA256: `f9484422e513517bf613255514d096f534e40269d505ea4eadaa21c44bbc885c`.

| Class | train boxes | val boxes | test boxes |
|---|---:|---:|---:|
| traffic_cone | 1989 | 359 | 244 |
| construction_fence | 379 | 117 | 93 |
| construction_barrel | 410 | 295 | 349 |
| construction_barricade | 659 | 158 | 156 |
| construction_barrier | 566 | 142 | 131 |

Cities do not cross splits; different seq values from the same video still use the same `video_group`. Route groups for CMU's self-recorded pgh01..pgh04 are preserved using official naming rules. The 295 `IMG_*` images lacking traceable route IDs were excluded. The final manifest is written only after cross-checking train/val/test image hashes, video groups, and city groups.

This establishes geographic isolation for this ROADWork subset. Combining sources still requires new checks for location, duplicate images, and route leakage. New York scenes repeatedly observed during SkyCompanion development cannot be repackaged as unseen independent acceptance material merely because filenames differ.

Sampling cycles through class presence and cities, preserving all five source classes' targets within each image. This is a class-enriched research subset and cannot estimate false positives per minute in natural deployment. Source images are primarily driving views and include some nearby construction fences; this does not establish coverage of first-person close-range obstacle avoidance needs.

## Data Interface and Reproduction

- Import script: `scripts/import_roadwork_public.py`.
- Output: `backend/data/obstacle_dataset/public-roadwork-v1/dataset.json`.
- Per-image fields are compatible with `backend/app/obstacle_eval.py`: id / path / sha256 / split / video_group / location_group / review_status / reviewed_classes / annotations.
- annotations use normalized top-left `x,y,w,h`, additionally preserving `source_segmentation`, official annotation/category IDs, and attributes such as occlusion.
- `source_annotations/<split>/*.json` preserves complete original image metadata and annotations for every source class. Source masks are the authors' instance annotations; detection boxes still use author bbox values directly, with boundary clipping only. Current model predictions were not substituted for ground truth.
- Detailed actual counts and manifest SHA are in `import-report.json`; download progress is recorded in `import.log`.

First-time reproduction retrieves the official 67 MB `annotations.zip` at the pinned revision into the output directory's `source/`. The script checks its fixed size and the digest above before retrieving images. Run:

```sh
backend/.venv/bin/python scripts/import_roadwork_public.py --train-limit 600 --val-limit 120 --test-limit 120 --workers 4
```

The importer permits only train ≤ 1000, val/test ≤ 200, and individual HTTP Range requests ≤ 32 MB. It rejects servers that fall back to a 200 full-archive response rather than silently downloading the entire archive. Downloaded files can be reused, but CRC and dimensions are checked again.

Six unit checks cover class separation and source-mask preservation, complete-video grouping, ZIP validation, deterministic city splitting, rejection of full-archive downloads when Range is unsupported, and retries limited to bounded requests after truncated transfers.

The first download exited 1 after 839/840 images due to a truncated HTTP Range response; the failure remains in `import.log`. The importer added at most three retries for truncation. `import-retry.log` records reuse of verified cache, retrieval of the missing image, and rebuilding with the corrected vocabulary, without hiding the initial failure.

## Trainability and Acceptance Limits

After import, the project's explicit `--research-published` path can train a five-class research model as above; license, class-scope, and split-isolation checks cannot be skipped. The old live model is unchanged.

Full `validate_dataset` validation passed this round; source / license / complete coverage fields required for research mode are present. Ordinary `dataset_readiness` still reports 0/840 independently reviewed by a human or two assistants, an expected and preserved evidence limitation. The import retry finally exited 0, and six unit tests passed.

After independently checking detection performance in this round, close-range walking video and other classes are still needed. Metrics unsupported by this data must show "not measured": actual first-detection time, longest continuous miss, false positives per minute, walking-path occupancy, distance, phone frame rate, speech-onset latency, and interruptions per minute. Static box-detection scores cannot replace these metrics.
