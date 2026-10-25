"""Tests proving that brief silent pauses in videos do not prematurely cut to camera,

while silence exceeding the hold threshold properly transitions back to camera.
"""

from unittest.mock import patch

from meeting_assistant.services.audio_service import AudioService
from meeting_assistant.services.state_machine import MeetingState, MeetingStateMachine


def test_short_silence_does_not_cut_playing_video():
    svc = AudioService(audio_trigger_threshold=0.015, audio_silence_hold_seconds=4.5)
    sm = MeetingStateMachine()

    svc.media_audio_started.connect(sm.on_media_audio_started)
    svc.media_audio_stopped.connect(sm.on_media_audio_stopped)

    # 1. Start audio: 2 consecutive reads > threshold triggers PLAYING_VIDEO
    svc._evaluate_peak(0.02)
    assert sm.current_state != MeetingState.PLAYING_VIDEO  # Needs 2 reads
    svc._evaluate_peak(0.03)
    assert sm.current_state == MeetingState.PLAYING_VIDEO

    # 2. Dramatic speech pause: peak drops to 0.0 for 2 seconds
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 100.0
        svc._evaluate_peak(0.0)
        assert sm.current_state == MeetingState.PLAYING_VIDEO

        # Advance by 2.0s (< 4.5s threshold)
        mock_time.return_value = 102.0
        svc._evaluate_peak(0.0)
        assert sm.current_state == MeetingState.PLAYING_VIDEO, "Short 2s pause must NOT cut video!"

        # 3. Audio resumes within the hold window
        mock_time.return_value = 102.5
        svc._evaluate_peak(0.05)
        assert sm.current_state == MeetingState.PLAYING_VIDEO
        assert svc._silence_start_time is None, "Resume must clear silence timer"


def test_silence_exceeding_hold_transitions_to_camera_live():
    svc = AudioService(audio_trigger_threshold=0.015, audio_silence_hold_seconds=4.5)
    sm = MeetingStateMachine()

    svc.media_audio_started.connect(sm.on_media_audio_started)
    svc.media_audio_stopped.connect(sm.on_media_audio_stopped)

    # Trigger video playing
    svc._evaluate_peak(0.05)
    svc._evaluate_peak(0.05)
    assert sm.current_state == MeetingState.PLAYING_VIDEO

    # Silence starts at t=100.0
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 100.0
        svc._evaluate_peak(0.0)
        assert sm.current_state == MeetingState.PLAYING_VIDEO

        # Silence reaches 5.0 seconds (> 4.5s)
        mock_time.return_value = 105.0
        svc._evaluate_peak(0.0)
        assert sm.current_state == MeetingState.CAMERA_LIVE, "Silence > 4.5s must transition to CAMERA_LIVE"
