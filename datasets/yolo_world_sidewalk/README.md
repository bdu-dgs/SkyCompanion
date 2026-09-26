# SkyCompanion 步行视频训练集

本目录用 `walking video.mp4` 制作训练数据。原视频保持不变，默认每秒抽取一帧。现在共有 134 张待标注图片。原有标注已清空；图片和 `classes.txt` 保留。

## 标注类别

| YOLO ID | 按键 | 类别 | 标注范围 |
|---:|---:|---|---|
| 0 | 1 | bicycle | 自行车整体，包括停放的自行车 |
| 1 | 2 | streetlight | 路灯杆和灯头作为一个目标 |
| 2 | 3 | railing | 人行道栏杆、护栏 |
| 3 | 4 | bus_stop_shelter | 公交站棚整体，不只标站牌 |
| 4 | 5 | tree | 可见的树木 |
| 5 | 6 | traffic_light_red | 红灯亮起时的机动车交通信号灯灯头 |
| 6 | 7 | traffic_light_green | 绿灯亮起时的机动车交通信号灯灯头 |
| 7 | 8 | utility_pole | 电线杆或通信杆，不是路灯的杆体 |

路灯和电线杆要按外观区分。已有类别 ID 0–6 保持不变，新加的 `utility_pole` 使用 ID 7，避免旧标签类别错位。

## 从头开始标注

在项目根目录打开 PowerShell。首次准备图片或补齐缺失抽帧时运行：

```powershell
python prepare_yolo_world_dataset.py --interval 1
```

该命令保留已存在的图片，不覆盖文件。然后启动标注器：

```powershell
python annotate_yolo_world.py
```

逐帧操作：

1. 在空白处按住鼠标左键拖动，给每个可见目标画框；按 `1`–`8` 选择类别。目标被挡住或只露出一部分时，仍按可见部分标框。
2. 按 `M` 标机动车道区域，在机动车道边界上逐点点击，右键或按 Enter 闭合多边形。只圈机动车道，不包括人行道、自行车道、停车场和 driveway。
3. 道路边界看不清或被遮挡时，按 `U` 圈出不确定区域；这些像素会在车道模型训练时忽略。
4. 按 `S` 保存当前帧，再按 `N` 进入下一帧。按 `P` 返回上一帧。若还有未保存修改，标注器会要求先保存。

更正框：拖动框可移动；单击框后按类别数字可改类别；右键删除框。`Z` 撤销最后一个框或多边形点，`X` 取消尚未闭合的多边形，`Q` 退出。

**每一帧都要按 `S` 保存**，即使该帧没有上述物体，也要保存空的物体标签，并标出可见机动车道区域。否则切分脚本会拒绝开始训练。YOLO-World 使用物体框学习自行车、路灯、电线杆、栏杆、公交站、树和红绿灯；机动车道是不规则区域，使用单独的多边形 mask 训练 SegFormer，不能用一个 YOLO 矩形框代替道路区域。

## 标注后：切分和训练

确认标注器已处理所有图片、每帧都按 `S` 保存后，在项目根目录 PowerShell 运行：

```powershell
$env:KMP_DUPLICATE_LIB_OK = 'TRUE'
python split_yolo_world_dataset.py
python train_yolo_world.py --weights .\yolov8s-worldv2.pt --epochs 50 --imgsz 640 --batch 4 --device cpu
python train_road_lane_segmenter.py --epochs 20 --batch 1 --device cpu
```

`split_yolo_world_dataset.py` 按完整的 10 秒视频片段划分 train/val，降低相邻帧同时进入训练集和验证集造成的泄漏。YOLO-World 权重输出到 `run/yolo_world_finetune/sidewalk_obstacles`；道路区域模型输出到 `run/road_lane_finetune/segformer_b0`。当前环境使用 CPU；若已安装匹配的 CUDA 版 PyTorch，可把 YOLO 命令中的 `--device cpu` 改为 `--device 0`，SegFormer 命令改为 `--device cuda`。

单个步行视频场景有限。先检查验证集结果和标注视频，再用其他街道、光照和视角的数据复核模型；红绿灯识别不代表可以安全过街。
