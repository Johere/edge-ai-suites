"""Per-source video stream pipeline.

Each registered source gets its own StreamPipeline running in a background thread.
Pipeline: RTSP read → motion detect → segment extract → webhook POST.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

import cv2

from ..config import (
    MotionConfig,
    SegmentConfig,
    RecordingConfig,
    PrefilterConfig,
    SourceConfig,
    DefaultsConfig,
    expand_path,
)
from ..webhook import WebhookClient
from .motion_detector import MotionDetector
from .segment_extractor import SegmentExtractor
from .prefilter import YoloPrefilter, FramePrefilter

logger = logging.getLogger(__name__)


class StreamPipeline:
    """Manages a single RTSP source: connect, detect motion, extract clips, post webhooks."""

    def __init__(
        self,
        source: SourceConfig,
        defaults: DefaultsConfig,
        data_dir: str,
        webhook: WebhookClient,
    ):
        self.source = source
        self.source_id = source.source_id
        self.rtsp_url = source.rtsp_url
        self.webhook = webhook

        # Merge per-source config with defaults
        self._motion_cfg = source.motion or defaults.motion
        self._segment_cfg = source.segment or defaults.segment
        self._recording_cfg = source.recording or defaults.recording
        self._prefilter_cfg = source.prefilter or defaults.prefilter

        self._data_dir = os.path.join(expand_path(data_dir), self.source_id)
        os.makedirs(self._data_dir, exist_ok=True)

        # Initialize prefilter if enabled
        self._prefilter: FramePrefilter | None = None
        if self._prefilter_cfg.enabled and self._prefilter_cfg.model_path:
            try:
                yolo = YoloPrefilter(
                    model_path=self._prefilter_cfg.model_path,
                    target_classes=self._prefilter_cfg.target_classes,
                    min_confidence=self._prefilter_cfg.min_confidence,
                    device=self._prefilter_cfg.device,
                )
                self._prefilter = FramePrefilter(
                    yolo=yolo,
                    detect_fps=self._prefilter_cfg.detect_fps,
                    min_frames_hit=self._prefilter_cfg.min_frames_hit,
                )
                logger.info("[%s] Prefilter enabled: classes=%s", self.source_id, self._prefilter_cfg.target_classes)
            except Exception as e:
                logger.warning("[%s] Prefilter init failed, running without: %s", self.source_id, e)
                self._prefilter = None

        self._thread: threading.Thread | None = None
        self._running = False
        self._status = "stopped"
        self._cap: cv2.VideoCapture | None = None
        self._frame_count = 0
        self._fps: float = 15.0

    @property
    def status(self) -> str:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name=f"pipeline-{self.source_id}", daemon=True
        )
        self._thread.start()
        logger.info("[%s] Pipeline started", self.source_id)

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self._status = "stopped"
        logger.info("[%s] Pipeline stopped", self.source_id)

    def _run(self):
        """Main pipeline loop with reconnection."""
        while self._running:
            try:
                self._connect()
                if self._cap and self._cap.isOpened():
                    self._status = "online"
                    self.webhook.send_status_event(self.source_id, "online")
                    self._process_loop()
            except Exception as e:
                logger.error("[%s] Pipeline error: %s", self.source_id, e)
                self._status = "error"

            if self._cap:
                self._cap.release()
                self._cap = None

            if self._running:
                self._status = "reconnecting"
                self.webhook.send_status_event(self.source_id, "reconnecting")
                logger.info("[%s] Reconnecting in 10s...", self.source_id)
                time.sleep(10)

        self.webhook.send_status_event(self.source_id, "stopped")

    def _connect(self):
        """Connect to RTSP stream."""
        self._status = "connecting"
        logger.info("[%s] Connecting to %s", self.source_id, self.rtsp_url)

        self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not self._cap.isOpened():
            raise ConnectionError(f"Cannot open RTSP: {self.rtsp_url}")

        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 15.0
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        logger.info("[%s] Connected: %dx%d @ %.1f fps", self.source_id, w, h, self._fps)

    def _process_loop(self):
        """Read frames, detect motion, extract segments."""
        detector = MotionDetector(self._motion_cfg)
        motion_dir = os.path.join(self._data_dir, "motion_events")
        extractor = SegmentExtractor(
            config=self._segment_cfg,
            output_dir=motion_dir,
            source_id=self.source_id,
            fps=self._fps,
            frame_size=self._get_frame_size(),
        )

        in_motion = False
        in_gap = False
        gap_frames = 0
        merge_gap_frames = int(self._segment_cfg.merge_gap * self._fps)
        consecutive_failures = 0
        max_failures = 100

        while self._running:
            ret, frame = self._cap.read()  # type: ignore
            if not ret:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    logger.warning(
                        "[%s] %d consecutive read failures, reconnecting",
                        self.source_id,
                        consecutive_failures,
                    )
                    break
                time.sleep(0.01)
                continue

            consecutive_failures = 0
            self._frame_count += 1

            # Motion detection
            motion_detected = detector.detect(frame)

            if motion_detected and not in_motion and not in_gap:
                in_motion = True
                extractor.start_segment()
                if self._prefilter:
                    self._prefilter.reset()
            elif motion_detected and in_gap:
                in_gap = False
                in_motion = True
                gap_frames = 0
            elif not motion_detected and detector.is_static and in_motion:
                in_motion = False
                in_gap = True
                gap_frames = 0

            if in_gap:
                gap_frames += 1
                if gap_frames >= merge_gap_frames:
                    in_gap = False
                    result = extractor.finish()
                    if result:
                        self._maybe_emit(result)
            elif in_motion:
                if self._prefilter:
                    self._prefilter.accumulate(frame, self._fps)
                result = extractor.add_frame(frame)
                if result:
                    self._maybe_emit(result)
                    extractor.start_segment()
                    if self._prefilter:
                        self._prefilter.reset()

        if in_motion or in_gap:
            result = extractor.finish()
            if result:
                self._maybe_emit(result)
        extractor.close()

    def _maybe_emit(self, result):
        """Check prefilter and emit or discard segment."""
        if self._prefilter:
            pf_result = self._prefilter.result()
            if not pf_result.passed:
                if os.path.exists(result.path):
                    os.remove(result.path)
                logger.debug("[%s] Segment discarded by prefilter: %s", self.source_id, result.path)
                return
        self._emit_segment(result)

    def _emit_segment(self, result):
        """Post segment to webhook as motion event."""
        self.webhook.send_motion_event(
            source_id=self.source_id,
            start_time=result.start_time,
            end_time=result.end_time,
            duration_seconds=result.duration_s,
            clip_path=result.path,
            clip_size_bytes=result.file_size,
        )
        logger.debug(
            "[%s] Emitted segment: %.1fs, %s",
            self.source_id,
            result.duration_s,
            result.path,
        )

    def _get_frame_size(self) -> tuple[int, int]:
        if self._cap:
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
            return (w, h)
        return (640, 480)
