# SkyCompanion

仓库只保留三部分：iMessage 事件接收服务、YOLO-World 训练/标注、视频到 JSONL 与语音提醒的本地 pipeline。

## 1. 视频输入到结果输出

默认输入为仓库根目录的 `walking video.mp4`，默认模型是 `yolov8s-worldv2.pt`。在 PowerShell 中运行：

```powershell
.\start_sky.cmd
```

也可以指定视频、模型和采样参数：

```powershell
$env:KMP_DUPLICATE_LIB_OK='TRUE'
python sky_companion.py --video "walking video.mp4" --model yolov8s-worldv2.pt --display
```

程序逐帧处理视频，输出 `run/frames.jsonl`、`run/report.json`，并在启用语音时输出 `run/audio_events.jsonl`。按 `q` 退出；`--no-audio` 关闭语音，`--stdout` 将每帧 JSON 同时输出到终端。当前路况/距离结果是图像相对估计，不代表米制距离或安全通行保证。

完成训练后可指定训练得到的权重：

```powershell
python sky_companion.py --video "walking video.mp4" --model run/yolo_world_finetune/sidewalk_obstacles/weights/best.pt --display
```

## 2. YOLO-World 训练和标注

数据集、类别、标注按键、机动车道边界标注方式，以及从空白标注到训练的完整说明在 [datasets/yolo_world_sidewalk/README.md](datasets/yolo_world_sidewalk/README.md)。目前的 134 张抽帧图像保留，旧标签已清空，需要重新标注。YOLO-World 负责物体框；机动车道边界以独立多边形标注并由单独的分割模型训练。

训练 YOLO-World：

```powershell
$env:KMP_DUPLICATE_LIB_OK='TRUE'
python split_yolo_world_dataset.py
python train_yolo_world.py --weights .\yolov8s-worldv2.pt --epochs 50 --imgsz 640 --batch 4 --device cpu
```

有 NVIDIA CUDA 时将 `--device cpu` 改为 `--device 0`。机动车道边界分割训练命令和前提见数据集 README。

## 3. iMessage

iMessage 接口服务位于 [skycompanion/README.md](skycompanion/README.md)。它接收手机端事件；手机端视频识别和提醒仍需在手机端另行集成，Windows 视频 pipeline 不等于 iPhone 端部署。

## 目录

- `sky_companion.py`、`start_sky.cmd`：视频推理、场景规则、JSONL 和本地语音输出。
- `datasets/yolo_world_sidewalk/`：抽帧、框标注、道路边界标注与训练数据。
- `skycompanion/`：iMessage 事件 API。
- `assets/tts/en_short/`：离线英语提示音。
- `weights/clip/`：YOLO-World 所需 CLIP 文本编码权重缓存。
