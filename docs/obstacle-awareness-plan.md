# SkyCompanion Obstacle Recognition and Voice Alert Improvement Plan

Date: 2026-09-25 (America/Chicago). This document retains the initial research and proposals. Sampling, candidate models, partially labeled assessment, and experimental alerts have since been implemented; see the [implementation report](obstacle-test-report.md) for current status and measurements. Dedicated fine-tuning and full accuracy acceptance remain incomplete.

Reference repository: AI-FanGe/OpenAIglasses_for_Navigation, reviewed at `46d90ab778e7503559a4d165e6659f7426207d95`. Source was read through the user-specified GitHub plugin; installation scripts were not run and models were not downloaded.

## 1. Problems Exposed by the Screenshot

The screenshot clearly shows construction crash barrels, several traffic cones, thin caution tape or temporary separation equipment, and roadside poles; current output primarily identifies people and vehicles. The large orange foreground barrel is construction equipment and should not be treated as a trash can. Trash cans, complete fences, and traffic lights should be included in testing, but this screenshot does not establish that each is clearly visible.

Reading `model.names` from local `backend/data/models/yolo11n.pt` confirmed a COCO 80-class model. Current `backend/app/live.py` inference parameters are `imgsz=640, conf=0.35, device=cpu`. The phone image is compressed to a 960-pixel long edge and cropped to remove black borders, producing 790×443 before model input.

| Target | Current model coverage | Next step |
| --- | --- | --- |
| People, cars, bicycles, motorcycles, buses, trucks | Covered | Continue assessing occlusion, misclassification, and small-object recall |
| Traffic lights | `traffic light` exists | Separate light localization from color/pedestrian-signal interpretation; a light box does not imply permission to proceed |
| Cones, construction barrels, construction barriers, fences | No corresponding classes | Add open-vocabulary detection and train dedicated classes if needed |
| Trash cans, streetlight poles, utility poles, posts, bollards | No corresponding classes | Add prompts and segmentation masks; merge synonyms |
| Caution tape, thin rope, step edges, potholes | No reliable coverage | Treat as dedicated difficult cases; generic boxes alone cannot guarantee detection |

Lowering the threshold therefore only changes tradeoffs among existing classes. A larger COCO YOLO11 still would not add these classes. The measured local processing speed of 15 fps is not a measure of detection completeness. [Official COCO classes](https://docs.ultralytics.com/datasets/detect/coco/), [YOLO11](https://docs.ultralytics.com/models/yolo11/).

### The `train` Misclassification and Earlier Acceptance Gaps

The user also identified an ordinary roadside object labeled `train`. This false positive needs investigation; model labels are not facts. The supplied screenshot did not preserve the original frame for that `train` prediction, so the specific triggering texture is not yet known.

The backend directly reads `result.names[int(cls)]`, with no handwritten class-index mismatch found in this output path. Reproduction still requires that original frame, box, frame ID, and actual loaded weights to rule out issues such as displaying results from an old frame. Possible factors include local appearance similarity, occlusion, compression, insufficient small-object pixels, and differences between training scenes and pedestrian streets. These are hypotheses, not established causes of this error.

Three current defect types need separate fixes:

- **Missing classes:** Cones, construction barrels, poles, fences, and similar objects were not learned as output classes. They are usually missed and sometimes assigned existing classes; not every unknown object is forcibly assigned a label.
- **Class confusion/background false positives:** Incorrect predictions for existing classes require correctly annotated confusing examples, background negatives, and an independent validation set. A score is not a calibrated probability of correctness.
- **Missing risk understanding:** Even a correct class does not prove the object blocks the user's walking corridor, much less that an adjacent detour is passable.

Earlier acceptance focused on screen orientation, transport, and 15 fps without first completing obstacle-class coverage and per-class accuracy checks. This cannot support a claim of obstacle recognition suitable for guidance. Misses, false alerts, and risk prompts must become independent acceptance items.

Removing `train` from display, renaming categories to “obstacle,” lowering thresholds, increasing FPS, or correcting the assistant in chat is not training repair. Training requires updated data, actual weight optimization, and regression checks. Multi-frame voting reduces some flicker but cannot correct persistent misclassification.

## 2. What the Reference Project Actually Does

### Recognition and Guidance

- Uses dedicated `yolo-seg.pt` segmentation for tactile paving/crosswalks, then generates alignment prompts from path center and orientation.
- Its obstacle module uses `YOLOE` to load `yoloe-11l-seg.pt`, precomputes text features, and outputs segmentation masks. Text classes are configurable, but configuration is not evidence of reliable recall. [Detector source](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/obstacle_detector_client.py#L50-L70)
- The default obstacle allowlist includes vehicles, bicycles, motorcycles, animals/dogs, scooter, stroller, many pole names (pole, post, column, pillar, bollard, utility pole, light pole, signpost, etc.), plus bench, chair, potted plant, hydrant, cone, stone, and box.
- The allowlist does not explicitly include trash cans, construction barrels, fences, or caution tape. Although `person` appears in the speech mapping, it is absent from the default obstacle allowlist. Speech wording does not establish a configured detection class.
- Given a path mask, it filters targets with insufficient path overlap. It then estimates proximity from the target's bottom-image position and mask area. In the tactile-paving workflow, the threshold is a bottom beyond 75% of image height **or** an area above 12%. This is not a distance measurement in meters. [Spatial filtering](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/obstacle_detector_client.py#L141-L176), [Proximity decision](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/workflow_blindpath.py#L2014-L2054)
- Traffic lights have a separate `trafficlight.pt` module and multi-frame stability checks with stop/go/countdown labels; the orchestrator also has color logic. A single COCO light box does not perform the entire crossing decision. [Traffic-light code](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/trafficlight_detection.py#L513-L578)

### How It Notifies the Wearer

Navigation workflows generate short Chinese-language prompts. The tactile-paving workflow prioritizes obstacle warnings and throttles repeated speech. The main application passes prompts to `audio_player`, which matches prerecorded WAV files; an ESP32 receives audio from `/stream.wav` and plays it through I2S and MAX98357A to a speaker. The README also describes cloud speech recognition and multimodal conversation, a separate path from fixed local navigation prompts. The inspected navigation notification implementation is primarily speech; it does not establish vibration guidance.

Evidence: [Workflow priority](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/workflow_blindpath.py#L645-L682), [Main App playback](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/app_main.py#L978-L986), [Text-to-audio mapping](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/audio_player.py#L326-L389), [Device audio reception](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/compile/compile.ino#L551-L560).

### Aspects That Need Improvement Before Reuse

1. The README describes full obstacle avoidance, but the current ordinary navigation branch explicitly produces warnings only, without entering full avoidance. Retained side-step, forward, and return states are not evidence of integrated, validated avoidance. [Actual branch](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/workflow_blindpath.py#L1479-L1507)
2. Retained detour planning chooses movement to the opposite side solely from whether the target is left or right in the image. That function does not verify the other side is passable. SkyCompanion cannot directly adopt this rule. [Planning function](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/workflow_blindpath.py#L2095-L2110)
3. Default obstacle detection runs every 15 frames with a 10-frame cache; parameter comments are inconsistent. Copied to our 15 fps input, this branch would update about once per second. Use elapsed time and actual detection timestamps for all validity limits.
4. The wrapper substitutes `0.5` when confidence is missing. SkyCompanion should preserve actual model scores and mark missing values unknown rather than displaying fabricated confidence. [Relevant code](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/workflow_blindpath.py#L1981-L1983)
5. Some project wording proceeds directly from stable green to crossing. SkyCompanion should first report signal observations only, distinguishing pedestrian lights facing the user, vehicle lights, direction, and field-of-view coverage. Detecting green is not proof of a safe road.

This is static source review, not field performance testing of the reference project. Its own README describes it as a prototype for learning and discussion. [README](https://github.com/AI-FanGe/OpenAIglasses_for_Navigation/blob/46d90ab778e7503559a4d165e6659f7426207d95/README.md)

### Can the Authors' Training Be Reproduced?

The pinned GitHub tree, relevant model-loading code, and authors' linked [ModelScope repository](https://www.modelscope.cn/models/archifancy/AIGlasses_for_navigation) were inspected. Public files include `yolo-seg.pt`, `trafficlight.pt`, `yoloe-11l-seg.pt`, and `shoppingbest5.pt`, but corresponding datasets, annotation rules, training scripts, parameters, and independent assessment reports were not found. These external weights were not downloaded or executed.

| Module | Established usage | Evidence limits for training provenance |
| --- | --- | --- |
| Obstacle YOLOE | Loads weights, then sets detection classes with `get_text_pe` / `set_classes` | Inference configuration, not fine-tuning; filenames alone cannot establish whether the authors additionally trained these weights |
| Tactile paving/crosswalk | Loads dedicated segmentation weights | No reproducible training recipe published; data volume, epochs, and generalization cannot be inferred |
| Traffic lights | Loads separate weights and applies temporal decisions | Corresponding data/training records not found; light-color decisions require separate assessment |

Module responsibilities, class prompts, and short-speech workflows can be borrowed directly. Reproduction of the authors' training cannot be claimed. Section 5 gives more complete training references.

## 3. Recommended SkyCompanion Implementation

### Detection Classes and Path Occupancy

First compare current YOLO11n against `YOLOE-11s-seg` through an independent assessment entry point; the latter matches the locally installed Ultralytics API. Test larger models only if needed. Consolidate prompts into the following semantic groups rather than making many synonyms compete as separate classes:

| Unified label | Candidate English prompts to select through assessment |
| --- | --- |
| People, cyclists, vehicles | person, bicycle, motorcycle, car, bus, truck |
| Traffic cones | traffic cone |
| Construction barrels | construction barrel / traffic barrel |
| Separation equipment | construction barrier, barricade, fence, railing |
| Trash cans | trash can / garbage bin |
| Poles and bollards | pole, streetlight pole, utility pole, bollard |
| Other path obstructions | box, bench, potted plant |
| Dedicated difficult cases | caution tape, rope, stairs, curb, pothole |

YOLOE prompts describe candidate capabilities to test. Record failures such as thin rope and potholes and assess dedicated data/models; adding strings alone is not support. [Official YOLOE documentation](https://docs.ultralytics.com/models/yoloe/)

Also add sidewalk/walkable-surface segmentation, road boundaries, and obstacle occupancy. This video has no obvious tactile paving, so a tactile-paving mask cannot cover every scene. Allow a path buffer and retain hazards such as head-height protrusions that do not intersect a ground mask. Unclassified regions can also be marked unknown obstacles/unconfirmed regions.

Generate alerts jointly from target score, persistence, image direction, walking-corridor intrusion, and observation time. Monocular bottom position/area is only a proximity cue; do not report uncalibrated meters. Relative depth is not actual distance either.

### Speed and Freshness

- Retain the currently validated 15 fps capture and bounded newest-frame queue.
- Remeasure the new model's inference rate rather than inheriting YOLO11n's 15 fps result. At lower inference rates, separately display preview FPS, actual detection FPS, and result age. Tracking predictions are not new model recognitions.
- Heavy models must not compete without bounds for CPU with existing inference or accumulate stale frames. Measure one model first, then decide whether to retain two-model responsibilities.
- Use milliseconds for multi-frame confirmation, debouncing, and alert validity. Revoke old tracks, regions, and pending speech on rotation, reconnection, and analysis pause.
- Add an end-to-end metric from target appearance in the valid field of view to phone speech onset. Web drawing acknowledgements do not substitute for audio latency.

### Alert Content and Audio Channel

At this review, the iOS project only uploads the screen; return speech and background playback must be added.

Test prompts describe the image, such as “Construction obstacle toward the left-front of the camera view.” Only after validating the worn-use scenario should output become direction + obstacle + short action, such as “The path ahead is blocked; stop and check.” Do not read every box/confidence score, or direct a right detour merely because the right side looks empty.

Schedule urgent obstacles > blocked path > heading prompts > scene descriptions. Deduplicate the same target, allow danger escalation to interrupt low-priority speech, and discard expired prompts. Unknown results, frozen images, or disconnected streams must explicitly report perception unavailable, never “The way ahead is safe.” Do not enable automatic crossing instructions in the first round.

Implementation order:

1. Mac backend generates structured events with at least session, frame, track, category, direction, priority, expiry, and wording; the webpage displays the current prompt and evidence.
2. First integrate offline clips using Mac local speech to verify wording, throttling, and interruption. This is not delivery to the worn endpoint.
3. Add audio/event reception and playback to the iPhone main App, protected by the same pairing mechanism; the user enables speech before switching players. Use AVFoundation/AVFAudio and assess local `AVSpeechSynthesizer` or prerecorded audio streams. ReplayKit continues to handle video capture only.
4. Configure background modes/audio sessions for actual playback. Test mixing with Bilibili/DJI Fly, Bluetooth headset routing, new prompts after background silence, incoming-call interruption, and recovery. Background audio does not guarantee an arbitrary permanent WebSocket; silent loops are not completion evidence.
5. If the main App cannot reliably resume intermittent alerts across Apps, assess a dedicated audio receiver. Mac-only speech cannot be described as phone alerts reaching the wearer.

Apple references: [Speech synthesis](https://developer.apple.com/documentation/avfaudio/avspeechsynthesizer), [Background playback](https://developer.apple.com/documentation/avfaudio/avaudiosession/category-swift.struct/playback), [Mixing with other audio](https://developer.apple.com/documentation/avfaudio/avaudiosession/categoryoptions-swift.struct/mixwithothers). These APIs still need combined acceptance on the local iOS 18 device.

Future drone integration also requires the relationship among drone camera, user position, and heading. Image-left is not necessarily user-left; first-person glasses rules cannot be applied directly to overhead drone views.

## 4. Development and Acceptance Sequence

| Stage | Development and location | Deliverable and acceptance |
| --- | --- | --- |
| A: Fixed assessment set | New `scripts/evaluate_obstacles.py`, class configuration, manual labels | Extract construction, trash-can, pole, fence, and light clips from original video; split by video to prevent adjacent-frame leakage. User screenshots illustrate problems; page UI and old boxes are not original model input |
| B: Extended detection | Detector interface in `backend/app/live.py`, independent YOLOE implementation | Compare YOLO11n on identical clips; report per-class misses, false detections, recall/precision, first-detection latency, actual FPS; retain failures, not just successful screenshots |
| B2: Targeted fine-tuning | Fixed class list, split manifest, training configuration, model versions | Train a candidate small model on manually reviewed missed/false-positive examples; accept on test videos unused for tuning, following Section 6 |
| C: Path and alerts | New path/occupancy, tracking, alert-policy modules | Test approach, departure, occlusion, false detections, unknown objects, escalation; detection scores and distance provenance remain traceable |
| D: Frontend and speech | Extend live protocol; show events in `LiveMonitor.jsx`; add iOS main-App audio reception/playback | See an alert on the webpage and hear the same one through headphones actually connected to the phone; measure latency, deduplication, interruption, expiry removal |
| E: Continuous real-device test | Same Wi-Fi, detached from cable, sustained cross-App playback | At least ten minutes recording recognition, temperature/errors, audio interruption/recovery; pass only with stable alerts throughout |

First-round A–D acceptance uses recorded videos and supervised fixed scenarios. Passable directions and crossing strategies in road scenes require separate validation, not inference from this round's detection scores.

This round only updates research and implementation plans; online detection remains the original YOLO11n. Engineering priority is **save failures and fix an assessment set → compare YOLOE with the current model → targeted labeling/fine-tuning → path occupancy and phone speech**.

## 5. Expanded Research: Other Projects' Training and Lessons for SkyCompanion

Research date: 2026-09-25. Used web search, GitHub-plugin training-file reads, and the official YOLOE project in the browser. Coverage includes guidance applications, open-vocabulary models, street-scene data, unknown obstacles, and alert generation, without claiming exhaustive coverage. External metrics are author-reported, not locally reproduced, and are not ranked directly across datasets.

### 5.1 BrailleGuard: Fine-Tuning Closest to the Existing YOLO11n

- **Data and training:** Collected/annotated Korean sidewalk data. v6 lists 1,359 images and 8 classes: bicycle, bollard, car, damaged_braille_block, kickboard, motorcycle, trash, utility_pole. The notebook actually starts from `yolo11n.pt` with 50 epochs, 640 input, and batch 8, using the corresponding Roboflow version's data path. Image count is not the same as independent-scene count.
- **Outcome evidence:** v6 records precision 0.80335, recall 0.54917, mAP50 0.6238. The README's v7 adds noise/motion blur and lowers mAP50, showing that more augmentation is not always better. These metrics are not successful road-traversal rates.
- **Reproduction gaps:** Static `models/configs/dataset.yaml` remains a 5-class placeholder inconsistent with v6's 8 classes, so it must not be used blindly. Actual training references YAML from downloaded data. This review did not independently verify avoidance of near-duplicate split leakage.
- **Lesson for SkyCompanion:** Preserve small-model speed and fine-tune on target-scene data; compare actual benefits from class cleanup and augmentation, retaining confusion matrices and failed frames. `trash` means waste, not a trash can, and the project does not cover all SkyCompanion requirements.

Evidence: [Training notebook](https://github.com/jhpark-1212/2026-OSS-Blind-Walk-Assistant/blob/e3b99764fe78caa963a8c06a97025dec0c2c122c/models/notebooks/BlindWalk_YOLO_Training_v6.ipynb), [v6 metrics](https://github.com/jhpark-1212/2026-OSS-Blind-Walk-Assistant/blob/e3b99764fe78caa963a8c06a97025dec0c2c122c/models/training_results/v6_flip_brightness_rotation/metrics.txt), [Placeholder configuration](https://github.com/jhpark-1212/2026-OSS-Blind-Walk-Assistant/blob/e3b99764fe78caa963a8c06a97025dec0c2c122c/models/configs/dataset.yaml), [Project comparison](https://github.com/jhpark-1212/2026-OSS-Blind-Walk-Assistant/blob/e3b99764fe78caa963a8c06a97025dec0c2c122c/README.md).

### 5.2 Official YOLOE: Main Basis for Class Expansion and Transfer Training

- **Pretraining data:** Objects365v1 detections plus GQA/Flickr30k image-text region labels, with scripts generating masks through SAM. Training combines datasets and validates on LVIS.
- **Training process:** Official instructions specify 30 epochs for text detection/segmentation, then 2 for the visual-prompt encoder and 1 for prompt-free specialized embeddings. `train_seg.py` defaults to batch 128, AdamW, and 8 GPUs. This reproduces the foundation model and cannot be applied unchanged to the current Mac CPU.
- **Transfer:** `train_pe.py` trains only the final classification layer; `train_pe_all.py` fine-tunes all parameters. The latter example actually uses existing weights, class-text embeddings, and labeled data, unlike simply calling `set_classes()`.
- **Lesson for SkyCompanion:** Validate new classes with official pretrained small models first, then decide supervised fine-tuning based on failing classes. SAM/open-vocabulary models can assist boxes/masks, but people must correct errors and omissions. Official GPU/CoreML speed is not local CPU speed.

Evidence: [Training instructions](https://github.com/THU-MIG/yoloe/blob/40cd606cabdbe2b566d6f14a6b162c89206e9a1b/README.md#training), [Actual pretraining entry](https://github.com/THU-MIG/yoloe/blob/40cd606cabdbe2b566d6f14a6b162c89206e9a1b/train_seg.py), [Full-parameter transfer](https://github.com/THU-MIG/yoloe/blob/40cd606cabdbe2b566d6f14a6b162c89206e9a1b/train_pe_all.py).

### 5.3 YOLOv7-tiny Walking Assistance: Define Sidewalk Classes Before Training

The authors describe transfer training YOLOv7-tiny on AI Hub sidewalk data, changing 80 classes to 29, including fixed obstacles such as barricades, bollards, poles, portable signs, electrical cabinets, and people/vehicles. TensorRT deployment on Jetson Nano then combines tracking, approach trends, and regions of interest to select spoken warnings.

The useful lessons are **environment-specific class lists and warnings only for relevant risks**. The README links training repositories and data, but this review did not find complete independent configurations/logs. It also notes restricted data access, so this is not an immediately downloadable source. TensorRT deployment does not apply to the current Mac. Approach is inferred from image-box changes, not directly measured distance.

Source: [Authors' training/deployment account](https://github.com/jayjmha/Assistance-System-for-the-Blind-using-Object-Detection/blob/fc7713741ca443feb8af792d4df4f656d91476e5/README.md).

### 5.4 YOLO-OD: Useful Small-Object Assessment, Not All-Obstacle Coverage

The paper uses 6,276 images and 4 classes (car, person, traffic cone, pothole), modifies YOLOv8 features/detection heads, and trains for 150 epochs on two RTX 3090 GPUs. Its MMYOLO branch uses 640×640 input, default batch 16, and SGD learning rate 0.01. Its dedicated small-object AP is relevant to distant cones and small targets.

It does not directly cover trash cans, fences, or poles. At inspection, the linked GitHub repository's top-level README remained generic MMYOLO documentation, and the reviewed entry points did not establish complete commands directly matching the paper's experiments. Therefore this is a **paper-method reference with reproduction entry points still unverified**, not the fastest SkyCompanion replacement.

Sources: [Paper §4.1–4.2](https://mdpi-res.com/d_attachment/sensors/sensors-24-07621/article_deploy/sensors-24-07621.pdf), [Linked repository](https://github.com/jjking00/YOLO-OD/tree/2739402bf90a4a00e8cba52297a69f68dbde1edb).

### 5.5 Mapillary Vistas: A Street-Scene Label Resource Close to Missing Classes

This is a dataset, not a ready-made guidance application. The 2017 paper version has 25,000 high-resolution street images and 66 densely annotated classes, with instance annotations for 37, collected across devices, regions, and weather. The authors' list explicitly includes fence, barrier, street light, pole, utility pole, traffic light, trash can, sidewalk, curb, and pothole.

SkyCompanion can train walkable-surface/street-scene segmentation or convert suitable instance masks into detection data. A large semantic region must not simply be treated as multiple separate objects. Dataset versions differ in classes/IDs; fix the version/mapping before merging and obtain data under the provider's actual download terms. Construction barrels and caution tape still require added first-person examples.

Sources: [Authors' paper](https://openaccess.thecvf.com/content_iccv_2017/html/Neuhold_The_Mapillary_Vistas_ICCV_2017_paper.html), [Authors' class list](https://openaccess.thecvf.com/content_ICCV_2017/supplemental/Neuhold_The_Mapillary_Vistas_ICCV_2017_supplemental.pdf), [Meta data entry](https://ai.meta.com/ai-for-good/datasets/mapillary-training-datasets/).

### 5.6 Unknown Obstacles: SegmentMeIfYouCan and PyTorch-OOD

SegmentMeIfYouCan provides RoadAnomaly21, RoadObstacle21, and pixel/connected-region metrics for unrecognized objects on roads. It is primarily a benchmark, not a guidance model ready after one download.

The public PyTorch-OOD example starts from ImageNet-pretrained ResNet50, trains FPN semantic segmentation on Cityscapes using cross-entropy and Adam, then assesses anomalies using EnergyBased scores. Its default is only 1 epoch, and it explicitly notes random numerical variation; this is not a complete production training recipe.

SkyCompanion should adopt the goal of **checking whether an obstruction is found even without an accurate category name**. Vehicle-view data still requires pedestrian/future-drone validation. Low category scores do not directly establish an obstacle, and empty detections do not establish an obstacle-free scene.

Sources: [Official benchmark](https://github.com/SegmentMeIfYouCan/road-anomaly-benchmark), [Readable training example](https://pytorch-ood.readthedocs.io/en/stable/auto_examples/segmentation/roadanomaly.html).

### 5.7 WalkVLM / WalkStream: Learning When and How to Warn

The WalkVLM paper uses approximately 12,000 walking-video/annotation pairs, covering scene, danger level, and timestamped brief warnings. Detic first generates boxes, followed by human review. The model builds on MiniCPM-V2.6 with rank-64 LoRA fine-tuning and temporal triggers to reduce repetition. Video sampling at 2 fps is not per-frame obstacle-detection performance.

At this search, the authors' repository lists **WalkStream** as the maintained reproduction path: GRPO trains warning generation and the temporal trigger is trained separately, with Qwen2-VL-2B and Linux/NVIDIA/CUDA/DeepSpeed training entry points. Old-paper parameters and the newer path are not one recipe. This round only read source/docs; training was not run or validated.

Initially borrow the separation of frequent perception from event-triggered short alerts; investigate VLM warning models later. More fluent language does not establish more reliable danger judgments. Human assessment must cover incorrect instructions, missed warnings, and actual speech timing. The current 15 fps local CPU detector cannot simply be replaced by this large-model pipeline.

Sources: [Original WalkVLM paper](https://arxiv.org/html/2412.20903v2), [Current author code](https://github.com/xiaoyuan1996/walkvlm/blob/1dc741ddcdedffbbc0a1c53c3f5e6294a1e0cc7a/README.md), [Maintained training entry](https://github.com/xiaoyuan1996/walkvlm/blob/1dc741ddcdedffbbc0a1c53c3f5e6294a1e0cc7a/WalkStream/README.md).

## 6. Concrete Corrections and Training Route for SkyCompanion (Proposed)

### 6.1 Make Errors Reproducible First

Add failure capture storing the exact original frame processed, ROI/rotation, frame ID, time, model-file digest, class list, input resolution, thresholds, and prediction JSON. Keep short surrounding clips to assess flicker and alert timing, saving only user-selected test content. The `train` false positive must enter this regression set; webpage screenshots only illustrate the issue.

First confirm that boxes correspond to the same frame, then reproduce the same model output offline to distinguish transport/display faults from model faults.

### 6.2 Define Annotation and Splits

1. Establish classes for people/vehicles, cones, construction barrels, barriers, fences, trash cans, and poles, with explicit boundaries: waste is not a trash can; construction barrels are not trash cans; streetlight fixtures and shafts may have a hierarchy. Separately label walkable surfaces, curbs, steps, potholes, and difficult cases such as caution tape.
2. Combine obtainable public labels with real iPhone first-person clips, adding night, backlight, occlusion, distant small targets, rotation/motion blur, and different cities. Establish a separate future-drone-view test subset.
3. Manually correct labels using tools such as CVAT; YOLOE/SAM provide preannotations only. Add objects the model did not box so its own misses do not become training truth. Save segmentation and detection-box labels separately.
4. Label objects mistaken for trains by their actual categories; similar streets with no targets become background negatives. Do not incorrectly label them `train` or hide the false positive by deleting the class. If trains remain in scope, include real trains in regression data too.
5. Split train/val/test by video, location, and collection batch before frame extraction/augmentation. Adjacent frames of one object and augmented versions of one original must not span training/test. Fix the test set and do not repeatedly use it to select prompts or thresholds.

### 6.3 Compare on a Small Scale Before Training

| Experiment | Purpose | Required input |
| --- | --- | --- |
| Original YOLO11n | Record current flaws; speed/existing-class baseline | Fixed test clips and human ground truth |
| YOLOE-11s-seg + consolidated prompts | Quickly check gains for cones, poles, trash cans, and other new classes | Same clips; choose prompts on validation data first |
| Fine-tuned YOLO11n / small segmentation model | Correct misses/confusion with dedicated data and measure speed benefit | Complete labels and fixed class IDs |
| Fine-tuned YOLOE | Compare when pretrained coverage exists but specific scenes still fail | Task-matched supervised labels and pinned trainer version |

Use Python, PyTorch, and Ultralytics, with appropriate segmentation training frameworks for segmentation/anomaly branches. Compare only a few candidates initially; simultaneous changes to model, resolution, data, and thresholds obscure the source of gains. Train in an independent environment. Arrange later GPU work according to actual resources; do not automatically purchase cloud compute.

An initial SkyCompanion experiment may start at 640 input and a 50-epoch maximum, with batch size fitting the device and validation early stopping. These are proposed starting values, not author-guaranteed configurations. Add a 960-input comparison, but benefits require source detail; enlarging compressed images does not restore lost information. Retain pretrained-weight source, data version, random seed, full parameters, and best validation weights. Retain representative old classes such as people/vehicles after class expansion to check forgetting.

For persistently missed ropes/potholes, first inspect visible pixels and label quality, then decide whether specialized models or better input are needed. More prompts alone do not establish completion.

### 6.4 Assess Misses, False Positives, and Timeliness Together

- Report per-class precision, recall, mAP, and confusion matrices, grouped by small objects, occlusion, lighting, and scene, rather than one aggregate score.
- Separately count `train` false positives, missed important path obstructions, false warnings per minute, first valid detection, and first speech latency. Eliminate known errors on the fixed problem set while validating independent videos to avoid memorizing one image.
- Tune thresholds only on validation data. Higher thresholds may reduce false positives while increasing misses; explicitly state that tradeoff for hazardous corridor targets. Use time thresholds for multi-frame confirmation, deduplication, and tracking, counting added latency.
- When category names are uncertain, say “Obstacle ahead; category unconfirmed” only with credible region/occupancy evidence. Do not invent an unknown-obstacle box. Misses still require independent testing; this is not a universal patch for semantic models.
- Record actual model FPS, dropped frames, result age, and phone speech latency. If accuracy improves but speed is insufficient, consider export/quantization and then retest small-object/thin-pole recall.
- The first goal is more reliable fixed-video tests, not proof that the system can independently guide users across roads or around obstacles.

Replace online weights only after this acceptance. The present deliverable is a sourced research plan: **a complete new dataset has not been collected, new weights have not been trained, and elimination of the `train` false positive has not been demonstrated**.
