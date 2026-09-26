# SkyCompanion 本地原型

## 手机事件接入（下一阶段接口已实现）

当前 Python 视频检测与本地语音仍是 Windows 原型。Photon agent 已改为从 `POST /v1/events` 接收手机上传的**播报事件**，按手机观察时间记录，并另记电脑接收时间；离线补传事件可用于汇报，但不会被当作实时 iMessage 提醒。iPhone 检测和语音程序尚未实现，因此不能把目前的 Windows 运行结果视为手机端验收。接口契约和启动方式见 [skycompanion/README.md](skycompanion/README.md)。

从 `walking video.mp4` 按原视频时间播放与抽帧，使用项目里的 `yolo11n.pt` 做 COCO 目标检测和 ByteTrack 跟踪。每个实际处理的帧写一条 JSONL；程序可同时显示调试画面并播放本机离线英文提示。原视频与模型都只读。项目依赖已安装在 `.deps`，预生成语音在 `assets/tts/en_short`。

在此文件夹打开 PowerShell，启动完整视频：

```powershell
.\start_sky.cmd
```

本机 Conda 的 PyTorch 与跟踪求解器会加载两份 Intel OpenMP runtime，因此启动脚本设置了 `KMP_DUPLICATE_LIB_OK`。这是 Intel 所标注的临时兼容办法；后续应改用干净的 Python 环境消除冲突。按 `q` 可退出画面。不需要画面时可用 `$env:KMP_DUPLICATE_LIB_OK='TRUE'; python sky_companion.py` 减少图形开销。`--no-audio` 只写 JSON；`--stdout` 会实时将同样的 JSONL 发到标准输出，供其他进程订阅。默认输出为 `run/frames.jsonl`、`run/audio_events.jsonl`、`run/report.json`。

常用参数：

```powershell
python sky_companion.py --fps 10 --imgsz 416 --speed 1 --conf 0.35 --cooldown 5 --display
```

`--fps` 是视频时间轴上的抽样率，默认 10；源视频是 20 FPS，所以默认隔一帧处理一帧。`--imgsz` 默认 416，以减少本机 CPU 推理时间；需要看更小目标时可设 640，但处理延迟会增加。`--speed 0.5` 仅用于观察，不用于实时延迟验收。`--corridor TLX TLY TRX TRY BRX BRY BLX BLY` 用 0–1 归一化坐标指定行走梯形四角；应针对实际摄像头视角校准。`--limit-video-seconds` 和 `--simulate-inference-ms` 只供短程及超载诊断。

## 输出契约（schema_version = 1.0）

每条 JSON 对应一个完成处理的帧，原视频 `frame_id` 不因抽帧或丢帧而重新编号。时间戳 `entered_at_ms`、`inference_completed_at_ms`、`processed_at_ms` 为 Unix 毫秒；`video_timestamp_ms` 是原视频播放时间。`latency_ms` 用单调时钟测量收帧到 JSON 准备写出的耗时。`stage_ms` 包含本帧 YOLO 与规则耗时、视频帧相对预定播放时刻的进入滞后；取帧和 JSON 实际写入耗时的 P50/P95 在 `report.json`。`processed_at_ms` 在调用文件写入前记录，因此与落盘完成有毫秒级差别。

- `detections[]`：`class`、`confidence`、`bbox_xyxy`（原视频像素）、`track_id`、`direction`、`relative_distance`、`in_walking_corridor`；灯框还有 `visual_signal_color`。
- `scene`：`walking_corridor` 的配置及状态、`roadway_proximity`、道路边界候选、`traffic_light_state`、`traffic_light_relevance`、`about_to_turn_red`、`camera_motion`。道路边界候选只来自图像直线，未验证为真实路缘，因此车道邻近一律为 `unknown`。即使在灯框内看到颜色，若不能确认对应用户通行方向，场景信号仍为 `unknown`。
- `hazards[]`：`target_id`、`type`、`in_path`、`approaching`、`risk_level`、`evidence`。`near/medium/far` 仅由检测框下缘所处的画面带定义：下缘占图高 ≥0.82 为 near，≥0.62 为 medium，其余 far；它们不是米数。
- `warning`：`speak`、`text`、`priority`、`target_id`、`avoid_direction`、`reason`。文本来自固定模板。连续 2 帧确认、置信度达到阈值、目标在梯形内且不属于 far 才能触发。相同目标及全局都有 5 秒 cooldown，防止 ID 改变后连续播报。没有可靠可通行区域验证时，`avoid_direction=unknown`，提示停下。

`unknown` 是明确的不确定结果，不表示否定。此视频来自移动摄像头，默认行人 `approaching=unknown`；只有在固定摄像头场景显式传入 `--fixed-camera`，且背景光流稳定、同一行人的框连续明显放大与下移时，才可能写 `true`。YOLO11n 是 COCO 80 类检测器，不能依赖它识别树、杆、坑洞或道路边界。程序不会建议跨入车道，也不会生成“可以过马路”。

## 台阶检测接口

原有 `yolo11n.pt` 没有台阶类别，当前文件夹也没有台阶专用权重。因此默认每帧 `scene.stairs.status=unknown`、`reason=no_stairs_model`，不会声称已识别台阶。拿到包含 `stair`、`stairs`、`step`、`steps` 或 `staircase` 类别的 YOLO 检测权重后，可运行：

```powershell
python sky_companion.py --stairs-model path\to\stairs.pt --display
```

专用模型的检测框会进入原有 `detections`，`source=stairs_model`；对应 `hazards` 的 `type=stairs`、`track_id=stairs:<id>`。仅在目标落入行走梯形、连续两帧跟踪确认且相对位置不是 `far` 时才提醒，`avoid_direction` 保持 `unknown`。台阶高度、上下方向和真实距离无法由检测框可靠推断。为保持离线语音可用，现阶段复用已缓存的 `Stop. Obstacle ahead.`，JSON 仍明确写 `stairs`。没有真实台阶视频和专用权重，尚不能宣称台阶识别准确率或实测延迟；启用第二个 YOLO 后请查看 `stage_ms.stairs_yolo` 并在 1× 视频上重新验收。

## 音频与延迟

`LocalSpeechSink` 是可替换的 `WarningSink` 实现；下一阶段可把同一帧 JSON 或其中的 `warning` 发往手机端。15 条常用英文提示使用 Windows 离线英语语音提前生成 WAV，并裁去无声前后缀；播放线程只保留当前待播最高优先级提示，超过 900 ms 未发出的提示作废。提示模板为 `Stop. Pedestrian ahead/left/right.`、`Stop. Car ahead/left/right.`、`Stop. Vehicle ahead/left/right.` 等，不含多余解释。`audio_events.jsonl` 记录播放 API、WASAPI 回环检测到的实际输出起点和终点。回环观测的是声卡输出信号，不是麦克风对扬声器声波的测量；设备若不可用，报告会明确写无法测量。

预录视频的两个时段分别报告：`intake_lag` 是视频帧计划出现到程序取得该帧，`actual_onset` 是取得帧到音频回环出现；把二者相加才接近“画面事件到本机声音”，但抽帧本身还有最多约 100 ms 的采样等待。1× 数据才可用于该目标。程序不会把音频 API 返回时间称为发声时间。

运行检查：

```powershell
python -m unittest -v test_sky_companion.py
$env:KMP_DUPLICATE_LIB_OK='TRUE'; python sky_companion.py --no-audio --limit-video-seconds 5 --simulate-inference-ms 180 --output run\overload\frames.jsonl
```

第二条令处理慢于 10 FPS，确认旧的待处理帧被覆盖、程序能正常结束；与真实推理性能无关。
