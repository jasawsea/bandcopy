from app.drum_transcribe import (
    quantize_onsets_to_grid,
    remove_ghost,
    infer_hihat_subdivision,
    fill_regular_hihat,
)


def test_quantize_snaps_to_nearest_step():
    step_times = [i * 0.25 for i in range(8)]      # 0,0.25,...,1.75
    onsets = [0.02, 0.26, 0.70]                    # →0, 1, 3(0.75に近い)
    assert quantize_onsets_to_grid(onsets, step_times) == [0, 1, 3]


def test_quantize_dedupes_same_step():
    step_times = [0.0, 0.25, 0.5]
    assert quantize_onsets_to_grid([0.01, 0.02], step_times) == [0]


def test_remove_ghost_drops_below_threshold():
    peaks = [0, 4, 8]
    strengths = [1.0, 0.1, 0.8]
    assert remove_ghost(peaks, strengths, 0.5) == [0, 8]


def test_infer_hihat_subdivision():
    bar_sec = 2.0                                  # 120BPM・4拍
    # 16分＝1小節16打点
    sixteenths = [i * bar_sec / 16 for i in range(16)]
    assert infer_hihat_subdivision(sixteenths, 1, bar_sec) == 16
    # 8分＝1小節8打点
    eighths = [i * bar_sec / 8 for i in range(8)]
    assert infer_hihat_subdivision(eighths, 1, bar_sec) == 8
    # ほぼ無音
    assert infer_hihat_subdivision([], 1, bar_sec) is None


def test_fill_regular_hihat():
    assert fill_regular_hihat(8, 1) == [1 if s % 2 == 0 else 0 for s in range(16)]
    assert fill_regular_hihat(16, 1) == [1] * 16
    assert fill_regular_hihat(None, 2) == [0] * 32
