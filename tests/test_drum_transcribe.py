import numpy as np
import soundfile as sf

from app.drum_transcribe import (
    quantize_onsets_to_grid,
    remove_ghost,
    infer_hihat_subdivision,
    fill_regular_hihat,
    build_drum_templates,
    transcribe_drums,
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


def test_build_drum_templates_shape_and_bands():
    sr, n_fft = 22050, 1024
    W = build_drum_templates(sr, n_fft)
    assert W.shape == (n_fft // 2 + 1, 3)
    assert (W >= 0).all()
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    # KK列は低域が最大、HH列は高域が最大
    assert freqs[np.argmax(W[:, 0])] < 200
    assert freqs[np.argmax(W[:, 2])] > 4000


def _write_synth_drums(path, sr=22050, tempo=120.0, bars=2):
    """低域サム(4分)＋高域チッ(8分)の合成ドラム。KK/HHが立つはず。"""
    bar_sec = 4 * 60.0 / tempo
    dur = bar_sec * bars
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    x = np.zeros_like(t)
    # キック：各拍（4分）に低域60Hzの短い減衰音
    for b in range(bars):
        for beat in range(4):
            t0 = b * bar_sec + beat * (bar_sec / 4)
            i0 = int(t0 * sr)
            env = np.exp(-np.linspace(0, 30, int(0.08 * sr)))
            seg = np.sin(2 * np.pi * 60 * np.arange(len(env)) / sr) * env
            x[i0:i0 + len(seg)] += seg[:len(x) - i0]
    # ハイハット：8分ごとに高域ノイズの短い音
    for b in range(bars):
        for e in range(8):
            t0 = b * bar_sec + e * (bar_sec / 8)
            i0 = int(t0 * sr)
            env = np.exp(-np.linspace(0, 60, int(0.03 * sr)))
            noise = np.random.RandomState(0).randn(len(env)) * env * 0.3
            x[i0:i0 + len(noise)] += noise[:len(x) - i0]
    sf.write(path, x.astype(np.float32), sr)


def test_transcribe_drums_shape_and_empty_toms(tmp_path):
    wav = tmp_path / "synth.wav"
    _write_synth_drums(str(wav))
    grid = transcribe_drums(str(wav), tempo=120.0, bars=2)
    assert set(grid["lanes"].keys()) == {"HH", "HT", "MT", "FT", "SN", "KK"}
    for lane in grid["lanes"].values():
        assert len(lane) == 32                       # 2小節*16
        assert set(lane) <= {0, 1}
    for tom in ("HT", "MT", "FT"):
        assert grid["lanes"][tom] == [0] * 32        # タムは常に空
    assert sum(grid["lanes"]["KK"]) > 0              # 低域サムはキックとして拾える
    assert grid["bars"] == 2 and grid["steps_per_bar"] == 16
