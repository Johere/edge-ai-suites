"""Full pipeline integration test — reads real video, produces clips and sink events."""

import os
import time
import threading
from unittest.mock import MagicMock, patch

import cv2
import pytest

from videostream_analytics.shared.config import (
    AppConfig,
    SourceConfig,
    DefaultsConfig,
    MotionConfig,
    SegmentConfig,
)
from videostream_analytics.stream_monitor.rtsp_monitor import StreamPipeline
from videostream_analytics.sinks import EventSink


class TestFullPipeline:
    @pytest.fixture
    def data_dir(self, tmp_path):
        return str(tmp_path / "pipeline_data")

    @pytest.fixture
    def mock_sink(self):
        """A mock EventSink that records all emit() calls."""
        sink = MagicMock(spec=EventSink)
        sink.emit.return_value = True
        return sink

    @pytest.fixture
    def pipeline(self, test_video_path, data_dir, mock_sink):
        source = SourceConfig(
            source_id="test_child",
            rtsp_url=test_video_path,  # OpenCV can open file paths directly
        )
        defaults = DefaultsConfig(
            motion=MotionConfig(diff_threshold=25, area_ratio=0.015, stable_frames=30),
            segment=SegmentConfig(interval=10.0, min_duration=1.0),
        )
        p = StreamPipeline(
            source=source,
            defaults=defaults,
            data_dir=data_dir,
            sink=mock_sink,
        )
        return p

    def test_pipeline_produces_motion_clips(self, pipeline, data_dir, mock_sink):
        """Pipeline should produce at least 1 motion clip from child_safety_demo.mp4."""
        pipeline.start()
        # Let it run for 20 seconds (enough for motion events to trigger)
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

    def test_clip_files_are_playable(self, pipeline, data_dir, mock_sink):
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
            assert frame_count > 20, f"Clip too short ({frame_count} frames): {clip_path}"

    def test_clip_duration_reasonable(self, pipeline, data_dir, mock_sink):
        """Clip duration should be within min_duration to interval range."""
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
            # Fixed interval: duration should be around interval (10s) or shorter for tail segments
            assert 1.0 <= duration <= 11.0, f"Clip duration {duration:.1f}s out of range"

    def test_sink_receives_status_online(self, pipeline, mock_sink):
        """Sink should receive a status='online' event when pipeline connects."""
        pipeline.start()
        time.sleep(3)
        pipeline.stop()

        status_events = [
            call.args[0] for call in mock_sink.emit.call_args_list
            if call.args[0].get("event_type") == "status"
        ]
        online_events = [e for e in status_events if e.get("status") == "online"]
        assert len(online_events) >= 1, f"Expected online status event, got: {status_events}"

    def test_sink_receives_motion_events(self, pipeline, data_dir, mock_sink):
        """Sink should receive motion events with correct payload fields."""
        pipeline.start()
        time.sleep(20)
        pipeline.stop()

        motion_events = [
            call.args[0] for call in mock_sink.emit.call_args_list
            if call.args[0].get("event_type") == "motion"
        ]
        assert len(motion_events) >= 1, "Expected at least 1 motion event"

        event = motion_events[0]
        assert event["source_id"] == "test_child"
        assert event["duration_seconds"] > 0
        assert event["clip_path"].endswith(".mp4")
        assert isinstance(event["start_time"], str)
        assert isinstance(event["end_time"], str)

    def test_pipeline_stops_cleanly(self, pipeline, mock_sink):
        """Pipeline should stop without errors and report stopped status."""
        pipeline.start()
        time.sleep(5)
        pipeline.stop()
        assert pipeline.is_running is False
        assert pipeline.status == "stopped"
