from unittest.mock import Mock

import pytest

from meeting_assistant.services.virtual_camera import (
    FRAME_BYTES,
    HEADER,
    HEIGHT,
    MAGIC,
    WIDTH,
    camera_support,
    decode_header,
    request,
)


def header(**changes):
    values = dict(
        magic=MAGIC,
        version=1,
        size=48,
        width=WIDTH,
        height=HEIGHT,
        payload=0,
        flags=3,
        reserved=0,
        sequence=30,
        tick_ms=1000,
    )
    values.update(changes)
    return HEADER.pack(*values.values())


@pytest.mark.parametrize(
    "change",
    [
        dict(magic=0),
        dict(version=2),
        dict(size=64),
        dict(width=9999),
        dict(payload=FRAME_BYTES + 1),
        dict(flags=2),
        dict(reserved=1),
    ],
)
def test_reject_bad_frame_protocol(change):
    with pytest.raises(ValueError):
        decode_header(header(**change))


def test_windows11_is_required():
    assert not camera_support("Windows", 19045, "AMD64")[0]
    assert camera_support("Windows", 22000, "AMD64")[0]
    assert not camera_support("Windows", 26100, "ARM64")[0]
    assert not camera_support("Linux", 22000, "AMD64")[0]


def test_request_closes_pipe_on_invalid_payload():
    pipe = Mock()
    pipe.transfer.side_effect = [b"", header(payload=FRAME_BYTES)]
    with pytest.raises(ValueError):
        request("I", lambda _: pipe)
    pipe.close.assert_called_once()


def test_stopped_frame_returns_no_stale_pixels_and_acknowledges():
    pipe = Mock()
    pipe.transfer.side_effect = [b"", header(flags=0), b""]
    status, pixels = request("F", lambda _: pipe)
    assert not status.enabled and not status.fresh and not pixels
    assert pipe.transfer.call_args.args == (1, b"A")
    pipe.close.assert_called_once()




def test_preview_reuses_connection_and_never_sends_camera_controls():
    from meeting_assistant.services.virtual_camera import PreviewConnection

    pipe = Mock()
    pipe.transfer.side_effect = [b"", header(flags=0), b"", b"", header(flags=0), b""]
    factory = Mock(return_value=pipe)
    connection = PreviewConnection(factory)
    connection.read()
    connection.read()
    connection.close()
    assert factory.call_count == 1
    assert factory.call_args.args[0].endswith("Preview.v1")
    assert [c.args[1] for c in pipe.transfer.call_args_list if len(c.args) > 1] == [b"F", b"A"] * 2
    pipe.close.assert_called_once()


def test_metrics_distinguish_bridge_from_slow_preview_and_reset():
    from meeting_assistant.services.video_metrics import VideoMetrics

    metrics = VideoMetrics()
    for i in range(5):
        bridge, preview = metrics.observe(i / 2, i * 15, rendered=True)
    assert bridge == 30.0 and preview == 2.0
    assert metrics.observe(2.1, 0, rendered=True) == (0.0, 0.0)
    for i in range(1, 11):
        bridge, preview = metrics.observe(2.1 + i / 10, 0, rendered=True)
    assert bridge == preview == 0.0
