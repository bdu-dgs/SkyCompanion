"""Evidence-limited camera-relative warnings; no metric distance/free-space claim.

A user-confirmed image corridor is a test region, not a calibrated walking path.
Classes absent from the detector remain absent: the rules below do not create
boxes for potholes, stairs or overhead objects that the model has missed.
"""
import math
import uuid

import cv2
import numpy as np

from .obstacle_attention import prioritize_obstacles

LOW_CLASSES = frozenset({"rock", "boulder", "stone barrier", "stone block", "concrete block",
                         "concrete barrier", "curb", "traffic cone"})
SURFACE_CLASSES = frozenset({"stairs", "step", "steps", "pothole", "hole", "drop-off"})
# Reserved input labels for validated future detectors, not new learned classes.
ELEVATED_CLASSES = frozenset({"overhead obstacle", "hanging sign", "low hanging branch", "awning"})
EXCLUDED_CLASSES = frozenset({"sidewalk", "traffic light", "tree"})
TRACK_GAP = .8
SUMMARY_MAX_AGE = 1.5


def validate_corridor(value):
    if value is None:
        return None
    if not isinstance(value, list) or not 3 <= len(value) <= 8:
        raise ValueError("Corridor requires 3-8 normalized coordinate points")
    if any(not isinstance(p, list) or len(p) != 2 or any(type(v) not in (int, float) or
           not math.isfinite(v) or not 0 <= v <= 1 for v in p) for p in value):
        raise ValueError("Invalid corridor coordinates")
    contour = np.array(value, np.float32)
    if not cv2.isContourConvex(contour) or cv2.contourArea(contour) < .02:
        raise ValueError("Corridor requires a convex polygon with sufficient area")
    return value


def valid_box(box):
    try:
        return (isinstance(box, dict) and isinstance(box.get("label"), str)
                and all(math.isfinite(box[k]) for k in ("x", "y", "w", "h", "confidence"))
                and 0 <= box["x"] < 1 and 0 <= box["y"] < 1
                and 0 < box["w"] <= 1 and 0 < box["h"] <= 1
                and 0 <= box["confidence"] <= 1)
    except (KeyError, TypeError, ValueError):
        return False


def intersection(box, corridor, lower_fraction=.35):
    """Visible object fraction intersecting a region; masks preserve gaps.

    Lower-body overlap is only an image-space proxy. Surface irregularities use
    their complete visible mask, since a thin stair/pothole has no standing base.
    """
    canvas = np.zeros((90, 160), np.uint8)
    path = np.zeros_like(canvas)
    scale = np.array([159, 89])
    polygon = box.get("polygon")
    try:
        polygon = np.asarray(polygon, dtype=np.float32)
        valid_polygon = (polygon.ndim == 2 and polygon.shape[1] == 2 and len(polygon) >= 3
                         and np.isfinite(polygon).all())
    except (TypeError, ValueError):
        valid_polygon = False
    if not valid_polygon:
        x, y, w, h = (box[k] for k in ("x", "y", "w", "h"))
        polygon = np.array([[x, y], [x+w, y], [x+w, y+h], [x, y+h]])
    cv2.fillPoly(canvas, [(np.clip(polygon, 0, 1)*scale).astype(np.int32)], 1)
    cutoff = max(0, min(90, int((box["y"] + box["h"]*(1-lower_fraction))*89)))
    canvas[:cutoff] = 0
    cv2.fillPoly(path, [(np.array(corridor)*scale).astype(np.int32)], 1)
    area = int(canvas.sum())
    return float((canvas & path).sum()/area) if area else 0.


def iou(a, b):
    x1, y1 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x2, y2 = min(a["x"]+a["w"], b["x"]+b["w"]), min(a["y"]+a["h"], b["y"]+b["h"])
    intersect = max(0., x2-x1)*max(0., y2-y1)
    return intersect/max(1e-9, a["w"]*a["h"]+b["w"]*b["h"]-intersect)


def direction_for(box):
    center = box["x"]+box["w"]/2
    return "left" if center < .4 else "right" if center > .6 else "ahead"


DROP_CLASSES = frozenset({"pothole", "hole", "drop-off"})
VEHICLE_CLASSES = frozenset({"car", "truck", "bus", "train", "motorcycle", "bicycle"})
MAX_TRACKS = 64
REASON_CODES = frozenset({
    "image_corridor_overlap", "persistent_observation", "apparent_near_image_proxy",
    "surface_change_candidate", "drop_candidate", "overhead_alignment_candidate",
    "vehicle_candidate", "camera_direction_only", "metric_distance_unknown",
    "occluded_unresolved", "image_conflict_resolved", "no_confirmed_conflict",
    "corridor_unconfigured", "evidence_stale", "validated_ttc_budget",
    "new_relevance", "risk_upgrade", "direction_change",
})
UNRESOLVED_TEXT = "The earlier obstacle is no longer visible. It has not been confirmed resolved."


def speech_text(code, direction):
    noun = {"camera_obstacle": "obstacle", "camera_surface": "ground change",
            "camera_overhead": "overhead obstruction", "camera_vehicle": "vehicle conflict"}[code]
    position = {"left": "on the left", "right": "on the right", "ahead": "ahead"}[direction]
    return f"Caution. Possible {noun} {position} in the camera view. Your direction is unverified."


class RiskMonitor:
    """Image conflict lifecycle, separate from hub-owned perception health.

    R0 means no confirmed conflict, never safe. R1/R2 are evidence-limited
    warnings. Only target-bound validated physical evidence can qualify for R3.
    Missing detections cannot prove resolution, distance or wearer passage.
    """
    def __init__(self, named_labels=(), ordinary_alert_gap_s=8.):
        if (type(ordinary_alert_gap_s) not in (int, float) or
                not math.isfinite(ordinary_alert_gap_s) or ordinary_alert_gap_s < 0):
            raise ValueError("ordinary_alert_gap_s must be a finite non-negative number")
        self.named_labels = frozenset(named_labels)
        # Configurable interaction pacing, not a calibrated safety threshold.
        # This permits fresh changes after a minimum gap; it never schedules repeats.
        self.ordinary_alert_gap_s = float(ordinary_alert_gap_s)
        self.last_automatic_alert = -math.inf
        self.last_automatic_level = "R0"
        self.quiet = False
        self.reset()

    def reset(self):
        self.tracks = {}
        self.unresolved_summary = None
        # At most 2 image risk levels × 4 fixed phrases × 3 camera directions.
        # Identity fragmentation must not create a new audible conflict episode.
        self.episode_spoken = set()
        self.active_track = None
        self.last_update = None
        self.last_result = None
        self.corridor = None

    @staticmethod
    def _candidate(box, corridor):
        if box["label"] in EXCLUDED_CLASSES or box["confidence"] < .25:
            return None
        label = box["label"]
        bottom = box["y"] + box["h"]
        kind, consequence = "lower_visible_body", "collision"
        if label in ELEVATED_CLASSES:
            xs = [p[0] for p in corridor]
            projected = [[min(xs), 0], [max(xs), 0], [max(xs), 1], [min(xs), 1]]
            overlap = intersection(box, projected, 1.)
            eligible = bottom >= .18 and box["w"] >= .15 and box["h"] >= .04
            kind, consequence = "elevated_image_alignment", "overhead"
        else:
            overlap = intersection(box, corridor, 1. if label in SURFACE_CLASSES else .35)
            eligible = bottom >= .55
            if label in DROP_CLASSES:
                kind, consequence = "surface_change_candidate", "drop"
            elif label in SURFACE_CLASSES:
                kind, consequence = "surface_change_candidate", "surface"
            elif label in LOW_CLASSES:
                kind, consequence = "low_object_candidate", "trip"
            elif label in VEHICLE_CLASSES:
                consequence = "vehicle"
        # Retain outside objects: entering the selected region is a state change.
        return {"box": dict(box), "overlap": overlap, "kind": kind,
                "consequence": consequence, "relevant": eligible and overlap >= .25,
                "attention": prioritize_obstacles([box])[0]["attention"]}

    @staticmethod
    def _stable(count, since, now):
        return count >= 3 and now - since >= .4 - 1e-9

    def _archive(self, key, track):
        if track.get("unresolved"):
            old = self.unresolved_summary
            if old is None or track["risk_level"] >= old["risk_level"]:
                self.unresolved_summary = {
                    "track_id": key, "risk_level": track["risk_level"],
                    "last_seen": track["last_seen"], "acknowledged": track.get("acknowledged", False),
                }

    def _associate(self, candidates, now):
        for key, track in list(self.tracks.items()):
            if now - track["last_seen"] > 5.:
                self._archive(key, track)
                del self.tracks[key]
        pairs = sorted(((iou(t["candidate"]["box"], c["box"]), key, idx)
                        for key, t in self.tracks.items() for idx, c in enumerate(candidates)
                        if now - t["last_seen"] <= TRACK_GAP), reverse=True)
        matched, assigned = set(), {}
        for score, key, idx in pairs:
            if score < .2:
                break
            if key not in matched and idx not in assigned:
                matched.add(key)
                assigned[idx] = key
        observed = []
        for idx, candidate in enumerate(candidates):
            key = assigned.get(idx)
            if key is None:
                key = uuid.uuid4().hex[:10]
                self.tracks[key] = {"first_seen": now, "last_seen": now, "observations": 0,
                    "candidate": candidate, "initial_area": candidate["box"]["w"]*candidate["box"]["h"],
                    "label_consistent": True, "relevant_count": 0, "relevant_since": now,
                    "outside_count": 0, "outside_since": now, "unresolved": False,
                    "risk_level": "R0", "announced_level": None, "announced_direction": None,
                    "direction_count": 0, "direction_since": now, "direction_candidate": None,
                    "acknowledged": False}
            track = self.tracks[key]
            track["label_consistent"] &= track["candidate"]["box"]["label"] == candidate["box"]["label"]
            track.update(candidate=candidate, last_seen=now, observations=track["observations"]+1)
            direction = direction_for(candidate["box"])
            if direction != track["direction_candidate"]:
                track.update(direction_candidate=direction, direction_since=now, direction_count=0)
            track["direction_count"] += 1
            if candidate["relevant"]:
                if not track["relevant_count"]:
                    track["relevant_since"] = now
                track["relevant_count"] += 1
                track["outside_count"] = 0
            else:
                track["relevant_count"] = 0
                # Only visible separation resolves an image conflict. Lack of
                # bottom/size eligibility or detector absence is not separation.
                if candidate["overlap"] < .1:
                    if not track["outside_count"]:
                        track["outside_since"] = now
                    track["outside_count"] += 1
                else:
                    track["outside_count"] = 0
            observed.append((key, track))
        seen = {key for key, _ in observed}
        for key, track in self.tracks.items():
            if key not in seen:
                # Missing frames interrupt confirmation/separation streaks;
                # they never remove an already established unresolved hazard.
                track.update(relevant_count=0, outside_count=0, direction_count=0)
        # Bounded working memory plus one conservative unresolved summary.
        if len(self.tracks) > MAX_TRACKS:
            ordered = sorted(self.tracks, key=lambda k: (self.tracks[k]["last_seen"],
                             self.tracks[k]["candidate"]["attention"]["score"]))
            for key in ordered[:len(self.tracks)-MAX_TRACKS]:
                self._archive(key, self.tracks[key])
                del self.tracks[key]
            observed = [(k, t) for k, t in observed if k in self.tracks]
        return observed

    @staticmethod
    def _physical_evidence(context, key, now):
        """Explicit future adapter contract; raw detector scores cannot satisfy it.

        The adapter must validate wearer heading, actual path and target-bound
        metric distance/closing speed. The full time budget is mandatory. Camera
        image growth is deliberately never used as closing speed or TTC.
        """
        if not isinstance(context, dict) or context.get("track_id") != key:
            return None
        required = ("wearer_heading_validated", "path_validated", "distance_validated", "closing_speed_validated")
        if not all(context.get(k) is True for k in required):
            return None
        numeric = ("observed_at_s", "distance_m", "closing_speed_m_s", "frame_age_s",
                   "processing_latency_s", "speech_latency_s", "reaction_time_s", "stopping_time_s")
        if any(type(context.get(k)) not in (int, float) or not math.isfinite(context[k]) for k in numeric):
            return None
        if not 0 <= now-context["observed_at_s"] < SUMMARY_MAX_AGE:
            return None
        if context["distance_m"] <= 0 or context["closing_speed_m_s"] <= 0:
            return None
        budget_keys = numeric[3:]
        if any(context[k] < 0 for k in budget_keys) or context["reaction_time_s"] <= 0 or context["stopping_time_s"] <= 0:
            return None
        # Account for measurement ageing even if a caller understates frame age.
        budget = max(context["frame_age_s"], now-context["observed_at_s"]) + sum(context[k] for k in budget_keys[1:])
        ttc = context["distance_m"] / context["closing_speed_m_s"]
        return {"metric_distance": context["distance_m"], "ttc_s": ttc,
                "ttc_budget_s": budget, "urgent": ttc <= budget}

    def _details(self, key, track, now, context):
        c, box = track["candidate"], track["candidate"]["box"]
        certain = box["label"] in self.named_labels and track["label_consistent"] and box["confidence"] >= .55
        physical = self._physical_evidence(context, key, now)
        reasons = ["image_corridor_overlap", "persistent_observation", "camera_direction_only"]
        if not physical:
            reasons.append("metric_distance_unknown")
        if c["attention"]["near"]:
            reasons.append("apparent_near_image_proxy")
        consequence_reason = {"surface": "surface_change_candidate", "drop": "drop_candidate",
                              "overhead": "overhead_alignment_candidate", "vehicle": "vehicle_candidate"}
        if c["consequence"] in consequence_reason:
            reasons.append(consequence_reason[c["consequence"]])
        risk = "R2" if c["attention"]["near"] or c["consequence"] in consequence_reason else "R1"
        if physical and physical["urgent"]:
            risk = "R3"
            reasons.append("validated_ttc_budget")
        code = ({"surface": "camera_surface", "drop": "camera_surface", "overhead": "camera_overhead",
                 "vehicle": "camera_vehicle"}.get(c["consequence"], "camera_obstacle")
                if certain else "camera_obstacle")
        evidence = {"overlap": round(c["overlap"], 3), "observations": track["observations"],
                    "duration_ms": round((now-track["first_seen"])*1000),
                    "basis": "user_confirmed_image_corridor", "metric_distance": None,
                    "direction_basis": "camera_image_not_wearer_heading", "kind": c["kind"],
                    "hazard_consequence": c["consequence"], "near_candidate": c["attention"]["near"],
                    "nearest_basis": "image_geometry_proxy_not_meters", "observed_at_s": track["last_seen"],
                    "apparent_area_ratio": round(box["w"]*box["h"]/max(1e-9, track["initial_area"]), 3),
                    "physical_height_known": False, "ground_contact_confirmed": False}
        if physical:
            evidence.update(physical)
        return {"risk_level": risk, "reason_codes": reasons, "speech_code": code,
                "category_naming_enabled": certain, "evidence": evidence,
                "evidence_confidence": {"presence": "supported", "path": "validated" if physical else "image_proxy",
                    "category": "validated" if certain else "unconfirmed", "distance": "validated" if physical else "unknown"}}

    def _base(self, now, state, text, risk="R0", lifecycle="unknown", reasons=()):
        return {"schema_version": 2, "state": state, "text": text, "event": None,
                "risk_level": risk, "lifecycle": lifecycle, "reason_codes": list(reasons),
                "evidence_confidence": {"presence": "unknown", "path": "unknown", "category": "unconfirmed", "distance": "unknown"},
                "direction_frame": "camera_image", "direction": None, "observed_at_s": now,
                "expires_at_s": now+SUMMARY_MAX_AGE, "quiet": self.quiet}

    def _remember(self, result, now):
        self.last_result, self.last_update = result, now
        return result

    def update(self, boxes, corridor, now, evidence_context=None):
        if self.last_update is not None and now <= self.last_update:
            if now == self.last_update:
                return {**self.last_result, "event": None}
            self.reset()
        if corridor != self.corridor:
            self.reset()
            self.corridor = corridor
        if corridor is None:
            return self._remember(self._base(now, "unconfigured", "Select a view corridor before obstacle alerts can start.",
                                  None, reasons=["corridor_unconfigured"]), now)
        candidates = [c for b in boxes if valid_box(b) if (c := self._candidate(b, corridor))]
        observed = self._associate(candidates, now)
        resolved, current, events = [], [], []
        for key, track in observed:
            c = track["candidate"]
            if track["unresolved"] and self._stable(track["outside_count"], track["outside_since"], now):
                track.update(unresolved=False, announced_level=None, announced_direction=None, risk_level="R0")
                resolved.append(key)
            if not c["relevant"] or not self._stable(track["relevant_count"], track["relevant_since"], now):
                continue
            detail = self._details(key, track, now, evidence_context)
            if detail["risk_level"] == "R1" and now-track["relevant_since"] < 1.2-1e-9:
                continue
            track.update(unresolved=True, risk_level=detail["risk_level"], detail=detail)
            direction = direction_for(c["box"])
            center = c["box"]["x"]+c["box"]["w"]/2
            trigger = None
            if track["announced_level"] is None:
                trigger = "new_relevance"
            elif detail["risk_level"] > track["announced_level"]:
                trigger = "risk_upgrade"
            elif (not track["acknowledged"] and direction != track["announced_direction"] and
                  abs(center-track.get("announced_center", center)) >= .18 and
                  self._stable(track["direction_count"], track["direction_since"], now)):
                trigger = "direction_change"
            current.append((key, track, detail))
            if trigger and not (self.quiet and detail["risk_level"] == "R1"):
                events.append((key, track, detail, trigger, direction, center))
        current_keys = {k for k, _, _ in current}
        missing = [(k, t) for k, t in self.tracks.items() if t["unresolved"] and k not in current_keys]
        pending_levels = [t["risk_level"] for _, t in missing]
        if self.unresolved_summary:
            pending_levels.append(self.unresolved_summary["risk_level"])
        chosen = None
        if current:
            chosen = max(current, key=lambda item: (item[2]["risk_level"], item[1]["candidate"]["attention"]["score"]))
            active = next((item for item in current if item[0] == self.active_track), None)
            if active and active[2]["risk_level"] == chosen[2]["risk_level"] and chosen[1]["candidate"]["attention"]["score"]-active[1]["candidate"]["attention"]["score"] <= .10:
                chosen = active
        # Speak only the stable most-relevant target; never serially narrate
        # every box or distract from a more urgent unresolved hazard.
        events = [e for e in events if chosen and e[0] == chosen[0]
                  and e[2]["risk_level"] >= max(pending_levels, default="R0")]
        # Retain the finite spatial speech signatures while any earlier
        # conflict is unresolved, including compressed lost-track summaries.
        # Only evidenced image separation of all conflicts (or context reset)
        # ends an episode; elapsed time and missing detections never do.
        if self.unresolved_summary is None and not any(t["unresolved"] for t in self.tracks.values()):
            self.episode_spoken.clear()
        events = [e for e in events if e[2]["risk_level"] == "R3" or e[3] == "risk_upgrade"
                  or (e[2]["risk_level"], e[2]["speech_code"], e[4]) not in self.episode_spoken]
        # Reevaluate only this frame's fresh primary candidate. A suppressed
        # ordinary event is not queued and consumes neither a signature nor a
        # timestamp. Escalation and validated urgent evidence bypass pacing.
        events = [e for e in events if e[2]["risk_level"] == "R3" or e[3] == "risk_upgrade"
                  or e[2]["risk_level"] > self.last_automatic_level
                  or now-self.last_automatic_alert >= self.ordinary_alert_gap_s]
        event = None
        if events:
            key, track, detail, trigger, direction, center = max(events, key=lambda e: (e[2]["risk_level"], e[1]["candidate"]["attention"]["score"]))
            # Validated R3 new-target events bypass episode dedup: suppressing
            # an actually new urgent conflict would conceal stronger evidence.
            if detail["risk_level"] != "R3":
                self.episode_spoken.add((detail["risk_level"], detail["speech_code"], direction))
            event = {**detail, "schema_version": 2, "id": uuid.uuid4().hex, "track_id": key,
                     "direction_frame": "camera_image", "direction": direction, "observed_at_s": now,
                     "expires_at_s": now+SUMMARY_MAX_AGE, "ttl_ms": 1500,
                     "priority": "urgent" if detail["risk_level"] == "R3" else "obstacle",
                     "reason_codes": detail["reason_codes"]+[trigger], "text": speech_text(detail["speech_code"], direction)}
            self.last_automatic_alert, self.last_automatic_level = now, detail["risk_level"]
            track.update(announced_level=detail["risk_level"], announced_direction=direction,
                         announced_center=center, acknowledged=False)
        if current:
            key, track, detail = chosen
            self.active_track = key
            direction = direction_for(track["candidate"]["box"])
            result = self._base(now, "occupied", speech_text(detail["speech_code"], direction), detail["risk_level"], "observed")
            result.update(detail, track_id=key, direction=direction, event=event,
                          acknowledged=track["acknowledged"], unresolved_count=len(missing)+int(self.unresolved_summary is not None))
            unresolved_risks = [t["risk_level"] for _, t in missing]
            if self.unresolved_summary:
                unresolved_risks.append(self.unresolved_summary["risk_level"])
            if unresolved_risks:
                result["unresolved_risk_level"] = max(unresolved_risks)
                if max(unresolved_risks) > result["risk_level"]:
                    # A lower-risk visible target cannot erase a higher-risk
                    # unresolved one from the primary status.
                    pending = [{"track_id": k, **t} for k, t in missing]
                    if self.unresolved_summary:
                        pending.append(self.unresolved_summary)
                    target = max(pending, key=lambda t: (t["risk_level"], t["last_seen"]))
                    result = self._base(now, "occupied", UNRESOLVED_TEXT, target["risk_level"],
                                        "occluded_unresolved", ["occluded_unresolved"])
                    result.update(track_id=target["track_id"], last_observed_at_s=target["last_seen"],
                                  acknowledged=target.get("acknowledged", False), unresolved_count=len(pending), event=event)
        elif missing or self.unresolved_summary:
            pending = [{"track_id": k, **t} for k, t in missing]
            if self.unresolved_summary:
                pending.append(self.unresolved_summary)
            target = max(pending, key=lambda t: (t["risk_level"], t["last_seen"]))
            result = self._base(now, "occupied", UNRESOLVED_TEXT, target["risk_level"], "occluded_unresolved", ["occluded_unresolved"])
            result.update(track_id=target["track_id"], last_observed_at_s=target["last_seen"],
                          acknowledged=target.get("acknowledged", False), unresolved_count=len(pending))
        else:
            relevant = any(c["relevant"] for c in candidates)
            result = self._base(now, "confirming" if relevant else "unconfirmed",
                "Confirming a possible image conflict." if relevant else "No confirmed image conflict. This does not mean the path is clear.",
                lifecycle="image_conflict_resolved" if resolved else "unknown",
                reasons=["image_conflict_resolved" if resolved else "no_confirmed_conflict"])
            if relevant:
                result["evidence_confidence"].update(presence="tentative", path="image_proxy")
        return self._remember(result, now)

    def describe(self, now, max_age=SUMMARY_MAX_AGE):
        max_age = max(0., min(SUMMARY_MAX_AGE, max_age))
        age = None if self.last_update is None else now-self.last_update
        if age is None or age < 0 or age >= max_age:
            unresolved = bool(self.unresolved_summary or any(t["unresolved"] for t in self.tracks.values()))
            return {"schema_version": 2, "state": "stale", "code": "risk_unresolved" if unresolved else "vision_unavailable",
                    "text": UNRESOLVED_TEXT if unresolved else "Live view is unavailable. Check your surroundings.",
                    "direction": None, "ttl_ms": 0, "reason_codes": ["occluded_unresolved"] if unresolved else ["evidence_stale"],
                    "risk_level": self.last_result["risk_level"] if unresolved and self.last_result else None}
        result = {k: v for k, v in self.last_result.items() if k != "event"}
        result["ttl_ms"] = max(0, int((max_age-age)*1000))
        if result["lifecycle"] == "occluded_unresolved":
            result.update(code="risk_unresolved", direction=None, text=UNRESOLVED_TEXT)
        elif result["state"] == "occupied":
            result.update(code=result["speech_code"], priority="urgent" if result["risk_level"] == "R3" else "obstacle")
        else:
            result["code"] = "no_recent_alert"
        return result

    def explain(self, now):
        result = self.describe(now)
        result["reason_codes"] = [r for r in result.get("reason_codes", []) if r in REASON_CODES]
        if result["code"].startswith("camera_"):
            result["code"] = "risk_explanation"
            result["text"] = "A persistent object overlaps the selected camera region. Distance and your direction are unverified."
        return result

    def acknowledge(self):
        for track in self.tracks.values():
            if track["unresolved"]:
                track["acknowledged"] = True
        if self.unresolved_summary:
            self.unresolved_summary["acknowledged"] = True
        if self.last_result:
            self.last_result["acknowledged"] = True
        return {"code": "risk_acknowledged", "text": "Acknowledged. The possible conflict remains unresolved."}

    def set_quiet(self, enabled):
        self.quiet = bool(enabled)
        return {"code": "quiet_enabled" if self.quiet else "quiet_disabled", "quiet": self.quiet}
