"""Unit tests verifying state machine behavior:
1. DISPLAYING_IMAGE leaves speaker mic UNMUTED for comments.
2. PLAYING_VIDEO mutes speaker mic to prevent feedback.
3. emergency_restore_on_exit un-mutes the mic unconditionally on exit.
4. ProfileManager atomic save and load with corruption recovery.
"""

from unittest.mock import MagicMock

from meeting_assistant.services.profile_manager import ProfileManager
from meeting_assistant.services.state_machine import MeetingState, MeetingStateMachine


def test_profile_manager_save_load_and_corrupt_recovery(tmp_path):
    prof_file = tmp_path / "test_profile.json"
    mgr = ProfileManager(prof_file)

    # Defaults when file doesn't exist
    profile = mgr.load()
    assert profile.scene_camera == "Palco"
    assert profile.mic_input_name == "Meeting Assistant - Mesa"

    # Modify and save
    profile.scene_camera = "Orador Principal"
    mgr.save(profile)
    loaded = mgr.load()
    assert loaded.scene_camera == "Orador Principal"

    # Corrupt the file
    prof_file.write_text("{broken json", encoding="utf-8")
    recovered = mgr.load()
    assert recovered.scene_camera == "Palco"
    assert mgr.recovery_message != ""
    assert (tmp_path / "test_profile.corrupt.bak").exists()


def test_displaying_image_keeps_mic_unmuted():
    mock_obs = MagicMock()
    sm = MeetingStateMachine(obs_service=mock_obs)

    # Secondary window appeared without audio -> DISPLAYING_IMAGE
    sm.on_secondary_window_appeared(has_audio=False)
    assert sm.current_state == MeetingState.DISPLAYING_IMAGE

    # Check that mic was NOT muted (muted=False)
    # calls to set_muted or set_input_mute
    calls = mock_obs.set_muted.call_args_list or mock_obs.set_input_mute.call_args_list
    assert len(calls) >= 1
    # Mic input must be muted=False
    mic_calls = [c for c in calls if c[0][0] == sm.profile.mic_input_name]
    assert len(mic_calls) >= 1
    assert mic_calls[-1][0][1] is False, "Speaker mic must be UNMUTED during DISPLAYING_IMAGE"


def test_playing_video_mutes_mic():
    mock_obs = MagicMock()
    sm = MeetingStateMachine(obs_service=mock_obs)

    # Audio started -> PLAYING_VIDEO
    sm.on_media_audio_started()
    assert sm.current_state == MeetingState.PLAYING_VIDEO

    calls = mock_obs.set_muted.call_args_list or mock_obs.set_input_mute.call_args_list
    mic_calls = [c for c in calls if c[0][0] == sm.profile.mic_input_name]
    assert len(mic_calls) >= 1
    assert mic_calls[-1][0][1] is True, "Speaker mic must be MUTED during PLAYING_VIDEO"


def test_emergency_restore_on_exit_unmutes_mic():
    mock_obs = MagicMock()
    sm = MeetingStateMachine(obs_service=mock_obs)

    # Put state in PLAYING_VIDEO (mic is muted)
    sm.transition_to(MeetingState.PLAYING_VIDEO)

    # App is closed -> emergency_restore_on_exit is called
    mock_obs.reset_mock()
    sm.emergency_restore_on_exit()

    calls = mock_obs.set_muted.call_args_list or mock_obs.set_input_mute.call_args_list
    mic_calls = [c for c in calls if c[0][0] == sm.profile.mic_input_name]
    assert len(mic_calls) >= 1
    assert mic_calls[-1][0][1] is False, "emergency_restore_on_exit must UNMUTE speaker mic"
