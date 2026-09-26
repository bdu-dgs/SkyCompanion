"""OpenCV UI for object boxes and a separate motor-vehicle-road mask."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "datasets" / "yolo_world_sidewalk"
CLASSES = ["bicycle", "streetlight", "railing", "bus_stop_shelter", "tree",
           "traffic_light_red", "traffic_light_green", "utility_pole"]
WINDOW = "Labels | 1-8 class, click/drag box, M lane, U unknown, S save"


class Annotator:
    def __init__(self, image, scale, boxes, lane_polygons, unknown_polygons):
        self.image = image
        self.scale = scale
        self.boxes = boxes
        self.lane_polygons = lane_polygons
        self.unknown_polygons = unknown_polygons
        self.mode = "boxes"
        self.active_class = 0
        self.drag_start = None
        self.drag_point = None
        self.drag_class = None
        self.current_polygon = []
        self.polygon_type = "lane"
        self.dirty = False
        self.selected_box = None
        self.edit_mode = None
        self.edit_origin = None
        self.edit_box = None
        self.notice = ""

    def box_at(self, point):
        for index in range(len(self.boxes) - 1, -1, -1):
            _, x1, y1, x2, y2 = self.boxes[index]
            if x1 <= point[0] <= x2 and y1 <= point[1] <= y2:
                return index
        return None

    @staticmethod
    def polygon_contains(polygon, point):
        contour = np.asarray(polygon, dtype=np.int32)
        return cv2.pointPolygonTest(contour, point, False) >= 0

    def mouse(self, event, x, y, flags, _):
        point = (max(0, min(self.image.shape[1] - 1, round(x / self.scale))),
                 max(0, min(self.image.shape[0] - 1, round(y / self.scale))))
        if self.mode == "boxes":
            if event == cv2.EVENT_LBUTTONDOWN:
                hit = self.box_at(point)
                self.drag_start = point
                if hit is not None:
                    self.selected_box = hit
                    self.edit_mode = "move"
                    self.edit_origin = point
                    self.edit_box = self.boxes[hit][:]
                else:
                    self.selected_box = None
                    self.edit_mode = "draw"
                    self.drag_class = self.active_class
            elif event == cv2.EVENT_MOUSEMOVE and self.drag_start is not None:
                self.drag_point = point
                if self.edit_mode == "move" and self.selected_box is not None:
                    dx, dy = point[0] - self.edit_origin[0], point[1] - self.edit_origin[1]
                    cls, x1, y1, x2, y2 = self.edit_box
                    dx = max(-x1, min(self.image.shape[1] - 1 - x2, dx))
                    dy = max(-y1, min(self.image.shape[0] - 1 - y2, dy))
                    self.boxes[self.selected_box] = [cls, x1 + dx, y1 + dy, x2 + dx, y2 + dy]
                    self.dirty = self.dirty or dx != 0 or dy != 0
            elif event == cv2.EVENT_LBUTTONUP and self.drag_start is not None:
                if self.edit_mode == "draw":
                    x1, x2 = sorted((self.drag_start[0], point[0]))
                    y1, y2 = sorted((self.drag_start[1], point[1]))
                    if x2 - x1 >= 3 and y2 - y1 >= 3:
                        self.boxes.append([self.drag_class, x1, y1, x2, y2])
                        self.selected_box = len(self.boxes) - 1
                        self.dirty = True
                elif self.edit_mode == "move" and self.selected_box is not None:
                    cls, x1, y1, x2, y2 = self.edit_box
                    dx, dy = point[0] - self.edit_origin[0], point[1] - self.edit_origin[1]
                    dx = max(-x1, min(self.image.shape[1] - 1 - x2, dx))
                    dy = max(-y1, min(self.image.shape[0] - 1 - y2, dy))
                    self.boxes[self.selected_box] = [cls, x1 + dx, y1 + dy, x2 + dx, y2 + dy]
                self.drag_start = self.drag_point = self.edit_mode = None
            elif event == cv2.EVENT_RBUTTONDOWN:
                hit = self.box_at(point)
                if hit is not None:
                    self.boxes.pop(hit)
                    self.selected_box = None
                    self.dirty = True
        elif self.mode in {"lane", "unknown"}:
            if event == cv2.EVENT_LBUTTONDOWN:
                self.current_polygon.append(point)
                self.dirty = True
            elif event == cv2.EVENT_RBUTTONDOWN:
                if self.current_polygon:
                    self.finish_polygon()
                else:
                    polygons = self.lane_polygons if self.polygon_type == "lane" else self.unknown_polygons
                    for index in range(len(polygons) - 1, -1, -1):
                        if self.polygon_contains(polygons[index], point):
                            polygons.pop(index)
                            self.dirty = True
                            break

    def finish_polygon(self):
        if self.current_polygon and len(self.current_polygon) < 3:
            self.notice = "Need 3+ vertices for a region; line kept. Add points, or X to cancel."
            return False
        if len(self.current_polygon) >= 3:
            target = self.lane_polygons if self.polygon_type == "lane" else self.unknown_polygons
            target.append(self.current_polygon[:])
            self.dirty = True
            self.notice = "Region closed. Press S to save."
        self.current_polygon = []
        return True


def draw(image, state, filename, saved):
    canvas = cv2.resize(image, None, fx=state.scale, fy=state.scale)
    for index, (cls, x1, y1, x2, y2) in enumerate(state.boxes):
        p1 = (round(x1 * state.scale), round(y1 * state.scale))
        p2 = (round(x2 * state.scale), round(y2 * state.scale))
        color = (0, 80, 255) if index == state.selected_box else (0, 220, 40)
        cv2.rectangle(canvas, p1, p2, color, 3 if index == state.selected_box else 2)
        cv2.putText(canvas, CLASSES[cls], (p1[0], max(22, p1[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, color, 2, cv2.LINE_AA)
    tint = canvas.copy()
    for polygons, color in ((state.lane_polygons, (0, 200, 255)),
                            (state.unknown_polygons, (220, 0, 220))):
        for polygon in polygons:
            points = (np.asarray(polygon, np.float32) * state.scale).astype(np.int32)
            cv2.fillPoly(tint, [points], color)
    canvas = cv2.addWeighted(canvas, 0.72, tint, 0.28, 0)
    for polygons, color in ((state.lane_polygons, (0, 200, 255)),
                            (state.unknown_polygons, (220, 0, 220))):
        for polygon in polygons:
            points = (np.asarray(polygon, np.float32) * state.scale).astype(np.int32)
            cv2.polylines(canvas, [points], True, color, 3)
    if state.current_polygon:
        points = (np.asarray(state.current_polygon, np.float32) * state.scale).astype(np.int32)
        cv2.polylines(canvas, [points], False,
                      (0, 200, 255) if state.polygon_type == "lane" else (220, 0, 220), 2)
        for point in points:
            cv2.circle(canvas, tuple(point), 4, (255, 255, 255), -1)
    if state.drag_start and state.drag_point:
        cv2.rectangle(canvas, tuple(round(v * state.scale) for v in state.drag_start),
                      tuple(round(v * state.scale) for v in state.drag_point), (255, 255, 0), 2)
    mode = f"BOX {CLASSES[state.active_class]}" if state.mode == "boxes" else f"POLYGON {state.polygon_type}"
    selected = f" selected:{state.selected_box + 1}" if state.selected_box is not None else ""
    status = (f"{filename.name} | boxes:{len(state.boxes)}{selected} lane:{len(state.lane_polygons)} "
              f"unknown:{len(state.unknown_polygons)} | {mode} | {'SAVED' if saved else 'UNSAVED'}")
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 36), (25, 25, 25), -1)
    if state.dirty:
        status = status.rsplit("|", 1)[0] + "| UNSAVED"
    if state.notice:
        status += " | " + state.notice
    cv2.putText(canvas, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.57,
                (255, 255, 255), 1, cv2.LINE_AA)
    return canvas


def read_lane_annotations(path: Path):
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("lane", []), data.get("unknown", [])


def main() -> None:
    images = sorted((DATA / "images" / "pending").glob("*.jpg"))
    if not images:
        raise SystemExit("No pending frames. Run prepare_yolo_world_dataset.py first.")
    labels_dir = DATA / "labels" / "pending"
    lanes_dir = DATA / "lanes" / "pending"
    labels_dir.mkdir(parents=True, exist_ok=True)
    lanes_dir.mkdir(parents=True, exist_ok=True)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    index = 0
    try:
        while 0 <= index < len(images):
            image_path = images[index]
            image = cv2.imread(str(image_path))
            height, width = image.shape[:2]
            scale = min(1280 / width, 850 / height, 1.0)
            label_path = labels_dir / f"{image_path.stem}.txt"
            lane_path = lanes_dir / f"{image_path.stem}.json"
            lane_mask_path = lanes_dir / f"{image_path.stem}.png"
            boxes = []
            if label_path.exists():
                for line in label_path.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) == 5:
                        c, cx, cy, bw, bh = map(float, parts)
                        x1, x2 = (cx - bw / 2) * width, (cx + bw / 2) * width
                        y1, y2 = (cy - bh / 2) * height, (cy + bh / 2) * height
                        boxes.append([int(c), round(x1), round(y1), round(x2), round(y2)])
            lane_polygons, unknown_polygons = read_lane_annotations(lane_path)
            state = Annotator(image, scale, boxes, lane_polygons, unknown_polygons)
            saved = label_path.exists() and lane_path.exists() and lane_mask_path.exists()
            cv2.setMouseCallback(WINDOW, state.mouse)
            while True:
                cv2.imshow(WINDOW, draw(image, state, image_path, saved))
                key = cv2.waitKey(20) & 0xFF
                if ord("1") <= key <= ord(str(len(CLASSES))):
                    if not state.finish_polygon():
                        continue
                    class_id = key - ord("1")
                    if state.mode == "boxes" and state.selected_box is not None:
                        state.boxes[state.selected_box][0] = class_id
                        state.dirty = True
                    state.active_class = class_id
                    state.mode, state.selected_box = "boxes", None
                elif key == ord("b"):
                    if not state.finish_polygon():
                        continue
                    state.mode = "boxes"
                elif key == ord("m"):
                    if not state.finish_polygon():
                        continue
                    state.mode, state.polygon_type = "lane", "lane"
                elif key == ord("u"):
                    if not state.finish_polygon():
                        continue
                    state.mode, state.polygon_type = "unknown", "unknown"
                elif key in (13, 32) and state.mode in {"lane", "unknown"}:
                    state.finish_polygon()
                    saved = False
                elif key == ord("x") and state.current_polygon:
                    state.current_polygon = []
                    state.dirty = True
                    state.notice = "Unfinished line cancelled."
                elif key == ord("z"):
                    if state.current_polygon:
                        state.current_polygon.pop()
                    elif state.mode == "boxes" and state.boxes:
                        remove = state.selected_box if state.selected_box is not None else len(state.boxes) - 1
                        state.boxes.pop(remove)
                        state.selected_box = None
                        state.dirty = True
                    elif state.polygon_type == "lane" and state.lane_polygons:
                        state.lane_polygons.pop()
                        state.dirty = True
                    elif state.unknown_polygons:
                        state.unknown_polygons.pop()
                        state.dirty = True
                elif key == ord("s"):
                    if state.current_polygon and not state.finish_polygon():
                        continue
                    rows = []
                    for cls, x1, y1, x2, y2 in state.boxes:
                        cx, cy = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
                        bw, bh = (x2 - x1) / width, (y2 - y1) / height
                        rows.append(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
                    label_path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
                    lane_path.write_text(json.dumps({"lane": state.lane_polygons,
                                                     "unknown": state.unknown_polygons}), encoding="utf-8")
                    mask = np.zeros((height, width), dtype=np.uint8)
                    for polygon in state.lane_polygons:
                        cv2.fillPoly(mask, [np.asarray(polygon, dtype=np.int32)], 1)
                    for polygon in state.unknown_polygons:
                        cv2.fillPoly(mask, [np.asarray(polygon, dtype=np.int32)], 255)
                    if not cv2.imwrite(str(lane_mask_path), mask):
                        raise OSError(f"Could not write lane mask for {image_path.name}")
                    saved = True
                    state.dirty = False
                    state.notice = "Saved."
                elif key in (ord("n"), 13, 32):
                    if state.current_polygon:
                        state.notice = "Close the region and press S, or press X to cancel before leaving."
                        continue
                    if state.dirty:
                        state.notice = "Unsaved annotation edits. Press S to save before moving to another frame."
                        continue
                    index += 1
                    break
                elif key == ord("p"):
                    if state.current_polygon:
                        state.notice = "Close the region and press S, or press X to cancel before leaving."
                        continue
                    if state.dirty:
                        state.notice = "Unsaved annotation edits. Press S to save before moving to another frame."
                        continue
                    index = max(0, index - 1)
                    break
                elif key == ord("q") or key == 27:
                    return
    finally:
        cv2.destroyAllWindows()
    print(f"Finished {len(images)} frames. Object labels: {labels_dir}; lane polygons: {lanes_dir}")


if __name__ == "__main__":
    main()
