from meeting_assistant.services.obs_visual_probe_service import (
    VisualSample,
    classify_samples,
    pixel_difference,
)


def sample(elapsed_ms: int, changed_percent: float, mean_difference: float = 1.0) -> VisualSample:
    return VisualSample(
        elapsed_ms=elapsed_ms,
        changed_percent=changed_percent,
        mean_difference=mean_difference,
    )


def test_pixel_difference_identical_frames() -> None:
    changed, mean = pixel_difference(bytes([10, 20, 30, 40]), bytes([10, 20, 30, 40]))

    assert changed == 0.0
    assert mean == 0.0


def test_pixel_difference_reports_changed_pixels() -> None:
    changed, mean = pixel_difference(bytes([0, 0, 0, 0]), bytes([0, 20, 0, 20]))

    assert changed == 50.0
    assert mean == 10.0


def test_classify_samples_accepts_strong_signal_that_returns_to_baseline() -> None:
    samples = [
        sample(0, 0.2),
        sample(1000, 14.0, 20.0),
        sample(2000, 18.0, 25.0),
        sample(3000, 0.4),
        sample(4000, 0.3),
        sample(5000, 0.2),
        sample(6000, 0.2),
    ]

    assert classify_samples(samples).startswith("Sinal forte")


def test_classify_samples_rejects_nearly_static_scene() -> None:
    samples = [sample(0, 0.1), sample(1000, 0.4), sample(2000, 0.6)]

    assert classify_samples(samples).startswith("Pouca mudança")
