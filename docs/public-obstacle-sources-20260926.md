# Public Obstacle Data Audit (2026-09-26)

Goal for this round: use genuine public boxes/masks to train specialists for poles, building columns, trunks, fences, construction obstacles, and rocks. Do not use user-recorded videos for training or present classifications, text prompts, or automatic predictions as manual boxes. This file records actual entry points, retrieval results, and limitations. Research experiments do not automatically pass product-deployment acceptance.

## Currently Actionable Sources

| Source | Verified annotations and targets | Access and license | Handling this round |
| --- | --- | --- | --- |
| [Original ForTrunkDet](https://zenodo.org/records/5213825) | Original VOC boxes for `trunk`; 2,029 visible-light and 866 thermal images among 2,895 | Official Zenodo API successfully accessed, CC BY 4.0; original ZIP 830,002,725 bytes | RGB only, split by whole forest; spot checks found partial annotation, now quarantined and blocked from ordinary YOLO training |
| [ROADWork](https://github.com/anuragxel/roadwork-dataset) | Manual instance segmentation of construction objects, including barrier, barricade, fence, cone, drum, etc. | Official [HF mirror](https://huggingface.co/datasets/anuragxel/roadwork-dataset/tree/main) directly accessible; core data ODC-By 1.0 | Construction-obstacle/fence supplement with geographic isolation; driving views are not sidewalk acceptance |
| [ADE20K](https://ade20k.csail.mit.edu/) | 150-class dense semantic masks include pole, column, fence, rock; `tree` is not `tree_trunk` | [Official terms](https://ade20k.csail.mit.edu/terms/): images only for noncommercial research/education; software and annotations BSD-3 | Suitable for isolated research-only four-class experiments; do not claim the entire dataset is commercially licensed |
| [Construction Site Safety](https://huggingface.co/datasets/keremberke/construction-safety-object-detection) | COCO boxes include barricade; 398 images, original 307/57/34 split, no pregenerated augmentation | HF data card actually read; CC BY 4.0, sourced from Roboflow Universe | Auxiliary candidate if ROADWork is insufficient; location/video grouping still needs audit |

### ForTrunkDet Download and Traceable Grouping

Actually accessible download URLs:

- Original ZIP: `https://zenodo.org/records/5213825/files/forest_dataset_original.zip?download=1`
- Metadata: `https://zenodo.org/api/records/5213825`
- Official MD5: `85b446b1561133e98d939288d0a1d4e1`.
- Do not download `forest_dataset_augmented.zip` (4.83 GB) or reuse randomized splits after augmentation.

After reading the ZIP directory and all 2,895 XML files, dimensions and counts exactly matched [Table 1 of the original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC8468268/):

| Location / camera | Dimensions | Original count | Fixed use this round |
| --- | --- | ---: | --- |
| Valongo / ZED Stereo | 1280×720 | 847 | train, maximum 800 |
| Lobão / GoPro Hero6 | 1920×1080 | 715 | val, maximum 150 |
| Vila do Conde / Allied Mako G-125 | 1292×964 | 467 | test, maximum 150 |
| Lobão / FLIR M232 | 640×512 | 866 | All excluded: thermal imaging |

Each forest enters only one split, keeping all potentially adjacent frames together. Lobao_GoPro / ViladoConde source paths in XML also support this mapping. Complete video IDs and timestamps were not public in the materials read, so `source_video_id=unknown`; image numbers cannot determine first-detection seconds. `video_group` uses the entire location/camera cohort, explicitly without pretending it is a known video ID. Both location and camera change across splits, so evaluation cannot separate their individual contributions.

This round's importer: `scripts/import_fortrunk_public.py`. It preserves original ZIP, XML, official license, and metadata, maps `trunk → tree_trunk`, and converts to normalized top-left xywh. It keeps `published_annotations`, not `human_verified`. There is no segmentation, distance, or path-occupancy ground truth, so those cannot be claimed accepted. The paper prefiltered excessive blur/glare, leaving those difficult conditions as data gaps.

### ROADWork Grouping and Exclusions

Official archives: `annotations.zip` 66,903,277 bytes; `images.zip` 10,595,098,610 bytes. The authors provide groupings including `gps_split` (no samples within 100m across the two sides) and `pittsburgh_only` (train Pittsburgh, validate other cities). City/video sources can further preserve independent test data; random frames from one video cannot be divided into three sets.

Imported ROADWork Fence should be named `construction_fence`: its annotation scope is construction fences, and ordinary black street railings may be unlabeled. It cannot provide complete supervision for general fence. See `docs/roadwork-import-20260926.md` for imported city groupings and class mappings.

`discovered_images.zip` and `discovered_subsets_with_annotations.zip` contain BDD100K/Mapillary sources with separate licensing; exclude them this round. The `german/` extension is separately CC BY-NC-SA 4.0 and does not inherit core ODC-By. Vehicle-path annotations cannot be described as the user's walkable passage.

### ADE20K Integration Limits

Official 150-class challenge archive: `https://data.csail.mit.edu/places/ADEchallenge/ADEChallengeData2016.zip`. Semantic masks contain class pixels and do not guarantee that each connected region is an independent object. If converted to boxes, mark `derived_from_semantic_mask` and review merges/fragments. Do not rename whole-tree masks as trunks or all general fences as construction barriers.

Full objects/parts data requires registration approval. The official GitHub repository has 3 street-scene sample JSON files, read in this audit; sample trees are labeled `tree` with no trunk subparts, so those 3 samples cannot supply trunk annotations. Image and annotation licenses must be preserved separately.

## Sources That Cannot Directly Serve as This Round's Detection Training Data

| Source | Finding in this audit | Handling |
| --- | --- | --- |
| [SideGuide](https://ytaek-oh.github.io/sideguide) | Officially describes boxes/instance masks/some stereo disparity, but downloading requires submitting a form, agreeing to terms, and approval | No application submitted or external contact made on the user's behalf; do not block currently downloadable data while waiting |
| [Mapillary Vistas](https://www.mapillary.com/dataset/vistas/) | Official entry point did not provide anonymously accessible downloads and fully verifiable terms | Do not bypass with third-party mirrors; list as awaiting authorization |
| [PEDESTRIAN](https://arxiv.org/html/2512.19190v1#A1.SS1) | Authors report 340 videos, 29 obstacles, Nicosia; paper experiments use classification and random-frame splits. Official DOI `10.5281/zenodo.10907945` and API actually returned 404 in this audit | Correct the previous impression of immediate availability. Even if restored, boxes would still be needed; 99% classification accuracy is not detection acceptance, and random-frame splits must not be reused |
| [Rubber-tree trunk segmentation](https://data.mendeley.com/datasets/n2g72z9k9z/1) | Subsequently retrieved the official listing, 10 MB small archive, full-archive directory, and 3 original train images/polygons; detailed evidence below | Original annotations still select foreground trunks without fully labeling background trunks; archive license/grouping inconsistencies also remain. Exclude from training this round |
| [FinnWoodlands](https://github.com/juanb09111/FinnForest) | Official README provides Google Drive with genuine trunk instance annotations; repository contains only README and no clear data license was found | Retain as a candidate; do not automatically apply a paper's open-access license to data |
| [TimberVision](https://github.com/timbervision/timbervision) | Boxes/segmentation support trunks and logging components, including live trees and cut logs; CC BY-NC-SA 4.0 | Separate live-tree/fallen-log classes and noncommercial limits; do not mix in this round |
| [Open Images V7](https://storage.googleapis.com/openimages/web/download_v7.html) | Official boxable CSV actually retrieved: Tree, Street light, Chair, Table included, but not the exact tree trunk/pole/column/fence/rock/barrier detection classes needed here | May retain general table/chair capabilities; do not treat the 9M image-level vocabulary as 600 boxed classes. Preserve per-image provenance/license and partial annotations |
| [COCO-Stuff](https://github.com/nightrome/cocostuff) | Dense semantic stuff labels, downloadable official PNG masks; image and annotation licenses differ | Suitable for environmental segmentation research; stuff regions are not reviewed independent-object boxes or close-range ground truth |

## Acceptance Items These Images Cannot Replace

These sources can support class-name and spatial-localization evaluation. Close-range targets need extra subset labels; box size is not actual meters. False positives per minute, first-detection time, and longest continuous miss require annotated continuous clips; phone FPS, actual speech-onset latency, and interruptions per minute require physical-device collection and listening. Static public images cannot produce those measurements.

Related download/metadata debugging originals are saved in `/tmp/skycompanion-public-source-audit/`; formal traceable ForTrunkDet originals are in `backend/data/obstacle_dataset/public-fortrunk-v1/source/`. No application emails or data applications were sent, and no live model changed in this audit.

## Actual ForTrunkDet Import Results This Round

The original ZIP was downloaded and passed official MD5 verification. The 1,100 RGB images split 800/150/150 train/val/test, with 5643/829/384 trunk boxes; no out-of-bounds boxes were clipped, and selected content has no duplicate SHA256. Five importer tests passed, covering ZIP/JPEG/XML pairing, thermal exclusion, and partial-annotation training gates. **No training or deployment ran; this data is quarantined and cannot enter current ordinary YOLO training.**

Six **train-only** visual spot checks confirmed correct box/image pairing, but some publisher boxes cover only lower trunk segments rather than the full visible trunk, and dense distant trunks are unlabeled. All 1,100 images are conservatively recorded as `annotation_coverage.tree_trunk=partial`, `reviewed_classes=[]`, while retaining `review_status=published_annotations`. This establishes authentic publisher provenance, not verified complete annotations. Ordinary YOLO treats unlabeled trunks as background, so the export gate was actually confirmed to reject them even with `--research-published`: `Standard YOLO export requires complete coverage for every trained class`.

- Current manifest SHA256: `0ce2402cae995eed603bdbec0fe76c4cf2a8f10d0b0b107a01a5223a25d7303a`.
- Initial manifest SHA256: `f0530c4aee6b3d1438bc8809f86c99d16a4141f6c05ffe834b14cecf5bb1a663`; original bytes are preserved in `dataset.initial-published.superseded.json` for traceability only. It is superseded and must not be used for training.
- Original images, XML, ZIP, publisher boxes, and forest splits are unchanged. Spot-check images and records are in `train-annotation-contact-sheet.png` and `train-visual-audit-inputs.json`; spot checking is not whole-dataset review, and test images were not viewed for tuning.

### Author Annotation-Scope Audit and Repair Requirements

[Section 3.2 of the author's paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC8468268/) describes removing heavily blurred/glare-affected images, then manually annotating Pascal VOC using CVAT. It also says 205 unannotated images were removed before augmentation because no suitable trunks were available for annotation. **This does not mean those images contain no visible trunks.** This audit found no directly implementable near/far threshold, minimum visible width, occlusion threshold, or top/bottom cutoff rule for trunk boxes. Unlabeled distant trees and empty XML therefore cannot be treated as tree-free negatives, nor can renaming the class "nearby trunks" justify complete coverage. The full audit is in `annotation-rule-audit.json`, with paper HTML and summary SHA preserved.

None of the six spot-check images received complete-annotation review, so no verified complete subset is currently established as directly trainable. A repair route is to create a separate version: select clear train originals/crops that can be exhaustively labeled, add every visible trunk meeting uniform rules, and correct trunk extent. Retained uncertain regions require an ignore-aware trainer; mark complete only after independent review. Validation/test must use independently reviewed images from their respective forests, never train crops moved to either side. The existing archive itself does not establish this acceptance conclusion.

## Independent ADE Known-Pixel v2 Audit

Audited objects: `scripts/import_ade_public.py --render-known-pixels` and `public-ade-visible-v2/dataset.json`, with manifest SHA256 `38d6692b280a3792497c5ea26de900ef40797a5a47383eca5de3ef66402fefcf`. Only train images were displayed; test images were not read to tune parameters. The preceding strict requirement of no void pixels in originals yielded 0 images; that result must be preserved and not described as "completely annotated originals."

Pixel conversion was measured on all 751 train images: every source mask=0 pixel becomes RGB 114; mask!=0 pixels equal the original decoded using the same OpenCV operation, with 0 mismatches. Four deterministically selected train original/derived/mask-box contact sheets also confirm that original unannotated object details were removed from derived inputs. `source_annotation_coverage=partial` and the derived input's `annotation_coverage=complete` describe different inputs and must remain distinct in records. This method can support a bounded research experiment; no pixel-implementation issue was found in which "actual content inside void regions is still trained as background."

However, this is a synthetic distribution preprocessed with ground-truth masks; real phone video has no ground-truth mask for preprocessing. Training and testing both use derived images and can compare only the identically transformed region task. Performance may exploit edges created by artificial fill and cannot be interpreted as clean-original performance. Current and candidate models must use the same derived inputs for this comparison, with separate transfer checks on independent clean frames. Five clean frames are only regression examples and insufficient for deployment acceptance.

Visual sampling revealed two other important task differences:

- Rock in `ADE_train_00003111` is an entire pebble beach, whose connected mask produces one large box. It does not annotate "each low rock obstructing passage." Results must be called rock semantic-region precision/recall, not low-rock instance recall.
- Among 751 train images, fence has 620 connected regions, including 210 with only 1–4 pixels; pole has 419 regions / 30 tiny regions, column 471 / 19, and rock 409 / 14. Tiny components affect region counts, AP, and training targets; boxes fragment under occlusion or merge when same-class regions touch. Small regions cannot simply be discarded while their visible pixels remain unlabeled background.

Two directly actionable corrections follow: retain this version as a region-research baseline and create a separate sparse-scene subset with complete instance review; or use original semantic masks for semantic segmentation with ignore-index=0 and report per-class non-void pixel metrics. Neither automatically supplies instance distance, walking-path occupancy, or nearby-rock ground truth. The current four-class specialist also cannot directly replace the full live model.

Independent audit evidence: `/tmp/skycompanion-public-source-audit/ade-audit.json`, `/tmp/skycompanion-public-source-audit/ade-train-known-pixels-audit.png`. The main importer was not modified, and no training or deployment occurred.

## Mendeley Trunk Data Retrieval Retry Results

The [official dataset](https://data.mendeley.com/datasets/n2g72z9k9z/1) anonymous file API now successfully returned HTTP 200 without an account. The actual endpoint is `/public-api/datasets/n2g72z9k9z/files?folder_id=root&version=1&$start=0&$limit=1000`, confirmed through the official page scripts; ordinary curl with the page Referer and official Accept content type can read it. The previous Python client's 403 and wrong endpoint's 404 do not mean the data was removed.

| Official file | Bytes | Official SHA256 | Actually retrieved this round |
| --- | ---: | --- | --- |
| all_datas.zip | 3,976,760,863 | `5e89a038fa618cf58bad701bc90ee7ecc256493489c1292fd40709230a44c8e2` | ZIP directory and 3 train images with labels only, approximately 3.65 MB in total range reads; full-archive SHA not verified |
| TrunkFormerLite_reproducible_data.zip | 10,206,281 | `d7edd49fc28e59fc6c1b53dbe98d7c7a94d0bd27f67d4db32cdf4073a8170806` | Full archive retrieved; official SHA matches exactly |

The full archive's central directory contains 10,000 JPGs, 10,000 YOLO polygon TXTs, and 3 caches; train/val/test image counts are 7000/1500/1500. camA and camB each have 5000 images, and left/right images sharing a numeric suffix do not cross splits: this verifies **stereo-pair isolation**. However, the directory has no individual-tree IDs or location mapping and cannot prove independence of every tree or route. Caches were not deserialized or executed.

The small archive contains only 3 examples per split, not all 10,000 images. Its README says LabelMe was converted from original YOLO polygons; binary masks merge rubber_trunk polygons, with 0 background and nonzero trunk. This round extracted train images `camA_000001`, `camA_001648`, and `camA_003309` plus original TXT files from the large archive using official Range access. Per-member CRC32 passed; each is 1080×1920, class 0, with one polygon per image. **Visual review confirms only the central foreground trunk is selected, with many background trunks unlabeled.** It therefore still does not replace dense complete-visible-tree_trunk annotation and cannot directly unlock ForTrunk's partial gate. It can support designated foreground-target segmentation or a subset after additional complete annotation.

Three further real limitations must be preserved:

1. The small archive's `tree_level_split.csv` sets tree_id to `camA` for all 9 images across train/val/test. This field does not actually support a claim of independent-tree splitting.
2. The official landing page says CC BY 4.0, while the small archive's `license.txt` still says the final license requires owner confirmation and describes an internal manuscript reproduction package; `data_availability_statement.txt` also retains prerelease TODOs. These may be outdated, but the inconsistency cannot be declared resolved without evidence.
3. The small archive's teacher soft-label script applies Gaussian blur to GT masks for format checks. It is not directly trustworthy teacher-model inference output and includes no complete training checkpoint.

All network transfers this round totaled less than 16 MB. The full 3.98 GB archive was not downloaded; source scripts were not run; no model was trained; test images were not viewed; and this round's frozen test set was unchanged. The evidence directory `/tmp/skycompanion-public-source-audit/` contains `mendeley-retry-audit.json`, the official file list, original ZIP directory, downloaded small archive, train material retrieved by Range, `mendeley-original-train-polygons.png`, and `mendeley-train-mask-audit.png`. The current conclusion is that **official data is retrievable, but it cannot directly be used as a completely annotated, location-isolated general trunk training set**.
