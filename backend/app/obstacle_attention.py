"""Prioritize foreground candidates without changing detector evidence.

This is a screen-space heuristic for upright, first-person street video. It is
not depth estimation: object size, camera tilt and occlusion can defeat it.
Keep every prediction so the viewer can reveal distant objects and evidence
exports never lose them. Confidence remains the detector's unmodified score.
"""
from __future__ import annotations

ATTENTION_VERSION = 1


def prioritize_obstacles(boxes):
    ranked = []
    for original in boxes:
        box = dict(original)
        w, h = box["w"], box["h"]
        bottom = min(1., box["y"] + h)
        # Width matters for low stone blocks/tables; height matters for thin
        # poles. Area alone would incorrectly suppress a tall, narrow post.
        near = ((bottom >= .68 and (h >= .12 or w >= .10))
                or (bottom >= .82 and (h >= .04 or w >= .06))
                or (bottom >= .50 and (h >= .60 or (h >= .40 and w >= .15))))
        score = .55 * bottom + .30 * min(1., max(h / .6, w / .5)) + .15 * min(1., w * h / .25)
        box["attention"] = {"near": bool(near), "score": round(score, 4),
                            "basis": "image_geometry_not_metric_distance", "version": ATTENTION_VERSION}
        ranked.append(box)
    return sorted(ranked, key=lambda b: (b["attention"]["near"], b["attention"]["score"]), reverse=True)
