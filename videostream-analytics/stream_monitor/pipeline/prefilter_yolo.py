"""YOLO prefilter for motion segments — skip clips with no target objects.

Uses OpenVINO for inference. When enabled, each motion segment is evaluated
per-frame during recording; clips without sufficient target class detections
are discarded instead of being sent to webhook.

Adapted from openclaw-smarthome-demo/stream_monitor/pipeline/prefilter_yolo.py.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]

_NMS_IOU_THRESH = 0.45


@dataclass
class PrefilterResult:
    passed: bool
    hit_classes: list[str] = field(default_factory=list)
    frame_hits: int = 0
    max_confidence: float = 0.0


def _preprocess(frame: np.ndarray) -> np.ndarray:
    """BGR→RGB + HWC→NCHW + normalize to [0,1] float32."""
    return frame[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0


def _postprocess(
    output: np.ndarray,
    infer_w: int,
    infer_h: int,
    conf_thresh: float,
    class_names: list,
    target_classes: set,
) -> list[dict]:
    """Decode YOLO output tensor into filtered detections."""
    pred = output[0].T  # [n_anchors, 4+nc]
    scores = pred[:, 4:]

    class_ids = np.argmax(scores, axis=1)
    confidences = scores[np.arange(len(scores)), class_ids]

    mask = confidences >= conf_thresh
    if not mask.any():
        return []

    boxes_cxcywh = pred[:, :4][mask]
    confidences = confidences[mask]
    class_ids = class_ids[mask]

    x1 = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
    y1 = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
    x2 = boxes_cxcywh[:, 0] + boxes_cxcywh[:, 2] / 2
    y2 = boxes_cxcywh[:, 1] + boxes_cxcywh[:, 3] / 2

    nms_boxes = [[float(x1[i]), float(y1[i]),
                  float(x2[i] - x1[i]), float(y2[i] - y1[i])]
                 for i in range(len(x1))]
    indices = cv2.dnn.NMSBoxes(
        nms_boxes, confidences.tolist(), conf_thresh, _NMS_IOU_THRESH
    )
    if len(indices) == 0:
        return []

    detections = []
    for idx in (indices.flatten() if hasattr(indices, "flatten") else indices):
        name = class_names[int(class_ids[idx])] if int(class_ids[idx]) < len(class_names) \
               else str(class_ids[idx])
        if target_classes and name not in target_classes:
            continue
        detections.append({"name": name, "conf": float(confidences[idx])})
    return detections


def _resize_long_side(frame: np.ndarray, long_side: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if long_side > 0:
        scale = long_side / max(h, w)
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
    else:
        new_w, new_h = w, h
    new_w = (new_w // 32) * 32
    new_h = (new_h // 32) * 32
    if new_w == w and new_h == h:
        return frame
    return cv2.resize(frame, (new_w, new_h))


class YoloPrefilter:
    """OpenVINO YOLO model wrapper."""

    def __init__(
        self,
        model_path: str,
        target_classes: list[str] | None = None,
        min_confidence: float = 0.4,
        device: str = "CPU",
    ):
        self.target_classes = set(target_classes or [])
        self.min_confidence = min_confidence

        import openvino as ov

        logger.info("Loading OpenVINO model: %s (device=%s)", model_path, device)
        core = ov.Core()
        cache_dir = os.environ.get("OV_CACHE_DIR", "/tmp/ov_cache")
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        core.set_property({"CACHE_DIR": cache_dir})
        ov_model = core.read_model(model_path)

        try:
            labels = ov_model.get_rt_info(["model_info", "labels"]).astype(str)
            self._class_names = labels.split() or list(_COCO_CLASSES)
        except Exception:
            self._class_names = list(_COCO_CLASSES)

        in_shape = ov_model.input(0).partial_shape
        self._is_dynamic = in_shape.is_dynamic
        self._static_h = 0
        self._static_w = 0

        if not self._is_dynamic:
            dims = [d.get_length() for d in in_shape]
            self._static_h = int(dims[2])
            self._static_w = int(dims[3])

        self._compiled = core.compile_model(ov_model, device.upper())
        self._infer_req = self._compiled.create_infer_request()
        logger.info("YoloPrefilter ready: classes=%d device=%s", len(self._class_names), device)

    def predict(self, frame: np.ndarray) -> list[dict]:
        """Run inference on a single BGR frame. Returns target-class detections."""
        if self._is_dynamic:
            infer_frame = _resize_long_side(frame, 0)
        else:
            infer_frame = cv2.resize(frame, (self._static_w, self._static_h))
        infer_h, infer_w = infer_frame.shape[:2]

        blob = _preprocess(infer_frame)
        result = self._infer_req.infer(blob)
        output = result[self._compiled.output(0)]
        return _postprocess(
            output, infer_w, infer_h,
            self.min_confidence, self._class_names, self.target_classes,
        )


class FramePrefilter:
    """Per-frame YOLO accumulator for the pipeline read loop.

    Lifecycle per motion event:
        pf.reset()                       # on motion_start
        pf.accumulate(frame, fps)        # each in-motion frame
        pf.reset_for_next_segment()      # on interval cut (preserves pass state)
        result = pf.result()             # when segment finalized

    Exit logic:
        After pass (person confirmed), exit only when YOLO stops detecting
        person for consecutive misses >= exit_miss_threshold.
    """

    def __init__(self, yolo: YoloPrefilter, detect_fps: float = 2.0, min_frames_hit: int = 2):
        self._yolo = yolo
        self.detect_fps = detect_fps
        self.min_frames_hit = min_frames_hit
        self._exit_miss_threshold = max(2, min_frames_hit * 2)
        self.reset()

    def reset(self):
        """Full reset — call on motion event start."""
        self._frame_idx = 0
        self._next_infer = 0
        self._frame_hits = 0
        self._samples_taken = 0
        self._hit_classes: set = set()
        self._pass_decided = False
        self._consecutive_misses = 0
        self._max_conf = 0.0

    def reset_for_next_segment(self):
        """Partial reset — call on interval cut within same motion event.

        Preserves pass_decided and consecutive_misses so exit logic works
        across segment boundaries.
        """
        self._frame_idx = 0
        self._next_infer = 0
        self._frame_hits = 0
        self._samples_taken = 0
        self._hit_classes: set = set()
        self._max_conf = 0.0

    @property
    def pass_decided(self) -> bool:
        return self._pass_decided

    @property
    def skip_decided(self) -> bool:
        return not self._pass_decided and self._samples_taken >= self.min_frames_hit

    @property
    def is_decided(self) -> bool:
        """Whether prefilter has reached a pass or skip decision."""
        return self._pass_decided or self.skip_decided

    @property
    def exit_decided(self) -> bool:
        """True when person has left the scene (consecutive YOLO misses after pass)."""
        return self._pass_decided and self._consecutive_misses >= self._exit_miss_threshold

    def accumulate(self, frame: np.ndarray, src_fps: float) -> bool:
        """Process one frame. Returns True once pass threshold is reached."""
        step = max(1, round(src_fps / self.detect_fps)) if src_fps > 0 else 1
        if self._frame_idx >= self._next_infer:
            dets = self._yolo.predict(frame)
            if not self._pass_decided:
                self._samples_taken += 1

            if dets:
                self._consecutive_misses = 0
                if not self._pass_decided:
                    self._frame_hits += 1
                for d in dets:
                    self._hit_classes.add(d["name"])
                    if d["conf"] > self._max_conf:
                        self._max_conf = d["conf"]
                if not self._pass_decided and self._frame_hits >= self.min_frames_hit:
                    self._pass_decided = True
            else:
                if self._pass_decided:
                    self._consecutive_misses += 1

            self._next_infer = self._frame_idx + step
        self._frame_idx += 1
        return self._pass_decided

    def result(self) -> PrefilterResult:
        """Return prefilter result for the current segment.

        A segment passes if it has its own hits OR if the motion event
        previously confirmed person presence AND this segment had at least
        one detection (avoids emitting pure-static tail segments).
        """
        if self._pass_decided and self._frame_hits == 0:
            # Tail segment with inherited pass but no own detections — skip
            passed = False
        else:
            passed = self._pass_decided or self._frame_hits >= self.min_frames_hit
        logger.info(
            "Prefilter %s: hits=%d classes=%s (need %d, pass_decided=%s)",
            "PASS" if passed else "SKIP",
            self._frame_hits, sorted(self._hit_classes), self.min_frames_hit,
            self._pass_decided,
        )
        return PrefilterResult(
            passed=passed,
            hit_classes=sorted(self._hit_classes),
            frame_hits=self._frame_hits,
            max_confidence=self._max_conf,
        )
