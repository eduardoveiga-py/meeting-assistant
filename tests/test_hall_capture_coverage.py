import pytest

from meeting_assistant.services.hall_capture import require_full_coverage


@pytest.mark.parametrize('rect', [(-629, -1080, 1291, 0), (-637, -1088, 1299, 8)])
def test_full_monitor_coverage_accepts_negative_coordinates(rect):
    require_full_coverage(rect, (-629, -1080, 1291, 0))


@pytest.mark.parametrize('rect', [
    (-629, -1073, 1291, 0),  # seven-pixel desktop strip at top
    (-628, -1080, 1291, 0),
    (-629, -1080, 1290, 0),
    (-629, -1080, 1291, -1),
])
def test_any_exposed_edge_refuses_photo(rect):
    with pytest.raises(ValueError, match='borda exposta'):
        require_full_coverage(rect, (-629, -1080, 1291, 0))
