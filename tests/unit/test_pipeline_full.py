"""Full pipeline integration test — reads real video, produces clips and webhook calls."""

import os
import time
import threading
from unittest.mock import MagicMock, patch

import cv2
import pytest

from src.config import (
    AppConfig,
    SourceConfig,
    DefaultsConfig,
    MotionConfig,
    SegmentConfig,
)
from src.pipeline.stream_pipeline import StreamPipeline
from src.webhook import WebhookClient


class TestFullPipeline:
    @pytest.fixture
    def data_dir(self, tmp_path):
        return str(tmp_path / "pipeline_data")

    @pytest.fixture
    def mock_webhook(self):
        """A mock WebhookClient that records all calls."""
        webhook = MagicMock(spec=WebhookClient)
        webhook.send_event.return_value = True
        webhook.send_motion_event.return_value = True
        webhook.send_status_event.return_value = True
        return webhook

    @pytest.fixture
    def pipeline(self, test_video_path, data_dir, mock_webhook):
        source = SourceConfig(
            source_id="test_child",
            rtsp_url=test_video_path,  # OpenCV can open file paths directly
        )
        defaults = DefaultsConfig(
            motion=MotionConfig(diff_threshold=25, area_ratio=0.015, stable_frames=30),
            segment=SegmentConfig(interval=5.0, min_duration=1.0),
        )
        p = StreamPipeline(
            source=source,
            defaults=defaults,
            data_dir=data_dir,
            webhook=mock_webhook,
        )
        return p

    def test_pipeline_produces_motion_clips(self, pipeline, data_dir, mock_webhook):
        """Pipeline should produce at least 1 motion clip from child_safety_demo.mp4."""
        pipeline.start()
        # Let it run for 20 seconds (enough for ~2 segments at 5s interval)
        time.sleep(20)
        pipeline.stop()

        # Check clip files were produced
        motion_dir = os.path.join(data_dir, "test_child", "motion_events")
        clip_files = []
        if os.path.exists(motion_dir):
            for root, dirs, files in os.walk(motion_dir):
                for f in files:
                    if f.endswith(".mp4"):
                        clip_files.append(os.path.join(root, f))

        assert len(clip_files) >= 1, (
            f"Expected at least 1 clip file, found {len(clip_files)} in {motion_dir}"
        )

    def test_clip_files_are_playable(self, pipeline, data_dir, mock_webhook):
        """Produced clip files should be openable and contain frames."""
        pipeline.start()
        time.sleep(20)
        pipeline.stop()

        motion_dir = os.path.join(data_dir, "test_child", "motion_events")
        clip_files = []
        if os.path.exists(motion_dir):
            for root, dirs, files in os.walk(motion_dir):
                for f in files:
                    if f.endswith(".mp4"):
                        clip_files.append(os.path.join(root, f))

        assert len(clip_files) >= 1
        for clip_path in clip_files[:3]:  # Check first 3 clips
            cap = cv2.VideoCapture(clip_path)
            assert cap.isOpened(), f"Cannot open clip: {clip_path}"
            frame_count = 0
            while cap.read()[0]:
                frame_count += 1
            cap.release()
            assert frame_count > 0, f"Clip has no frames: {clip_path}"
            # At 30fps, 5s interval = ~150 frames (tolerance)
            assert frame_count > 20, f"Clip too short ({frame_count} frames): {clip_path}"

    def test_clip_duration_reasonable(self, pipeline, data_dir, mock_webhook):
        """Clip duration should be approximately the configured interval."""
        pipeline.start()
        time.sleep(20)
        pipeline.stop()

        motion_dir = os.path.join(data_dir, "test_child", "motion_events")
        clip_files = []
        if os.path.exists(motion_dir):
            for root, dirs, files in os.walk(motion_dir):
                for f in files:
                    if f.endswith(".mp4"):
                        clip_files.append(os.path.join(root, f))

        assert len(clip_files) >= 1
        for clip_path in clip_files[:3]:
            cap = cv2.VideoCapture(clip_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_count = 0
            while cap.read()[0]:
                frame_count += 1
            cap.release()
            duration = frame_count / fps
            # Should be within 1-6s (configured interval=5s, min_duration=1s)
            assert 1.0 <= duration <= 6.0, f"Clip duration {duration:.1f}s out of range"

    def test_webhook_receives_status_online(self, pipeline, mock_webhook):
        """Webhook should receive a status='online' event when pipeline connects."""
        pipeline.start()
        time.sleep(3)
        pipeline.stop()

        mock_webhook.send_status_event.assert_any_call("test_child", "online")

    def test_webhook_receives_motion_events(self, pipeline, data_dir, mock_webhook):
        """Webhook should receive motion events with correct payload fields."""
        pipeline.start()
        time.sleep(20)
        pipeline.stop()

        # Should have at least 1 motion event call
        assert mock_webhook.send_motion_event.call_count >= 1

        # Check the payload of the first motion event
        call_args = mock_webhook.send_motion_event.call_args_list[0]
        kwargs = call_args.kwargs if call_args.kwargs else {}
        args = call_args.args if call_args.args else ()

        # send_motion_event is called with keyword args
        if kwargs:
            assert kwargs["source_id"] == "test_child"
            assert kwargs["duration_seconds"] > 0
            assert kwargs["clip_path"].endswith(".mp4")
            assert isinstance(kwargs["start_time"], str)
            assert isinstance(kwargs["end_time"], str)
        else:
            # Positional args: source_id, start_time, end_time, duration_seconds, clip_path, ...
            assert args[0] == "test_child"

    def test_pipeline_stops_cleanly(self, pipeline, mock_webhook):
        """Pipeline should stop without errors and report stopped status."""
        pipeline.start()
        time.sleep(5)
        pipeline.stop()
        assert pipeline.is_running is False
        assert pipeline.status == "stopped"
