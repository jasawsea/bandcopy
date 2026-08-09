import numpy as np
import soundfile as sf

from app.drum_transcribe import (
    band_flux,
    snare_flux,
    reconcile_beats,
    repair_beat_runs,
    anchor_beats,
    beat_step_times,
    step_peak_values,
    hits_from_values,
    choose_bar_phase,
    infer_hihat_subdivision,
    fill_regular_hihat,
    high_freq_fraction,
    resolve_hihat_subdivision,
    transcribe_drums,
)


def test_band_flux_only_counts_rises():
    """立ち上がりだけを拾う。減衰中は0（低域残響で反応しないための要）。"""
    freqs = np.array([50.0, 100.0, 5000.0])
    # 帯域30-120に該当するのは50/100Hzの2ビン。フレームごとに 1→5→2 と動かす
    S = np.array([[1.0, 5.0, 2.0],
                  [1.0, 5.0, 2.0],
                  [9.0, 9.0, 9.0]])          # 高域は帯域外なので効かない
    f = band_flux(S, freqs, 30, 120)
    assert f[0] == 0.0                        # 先頭は差分0
    assert f[1] > 0                           # 2→10 の立ち上がり
    assert f[2] == 0.0                        # 10→4 の減衰は0にする


def test_band_flux_hi_none_reaches_nyquist():
    freqs = np.array([100.0, 7000.0, 10000.0])
    S = np.array([[0.0, 0.0], [0.0, 3.0], [0.0, 4.0]])
    assert band_flux(S, freqs, 6000, None)[1] == 7.0     # 7k と 10k の両方を含む


def test_snare_flux_sums_shell_and_noise_bands():
    freqs = np.array([200.0, 3000.0, 12000.0])
    S = np.array([[0.0, 1.0], [0.0, 2.0], [0.0, 8.0]])
    # 150-400 の 1 と 2000-8000 の 2 を足した 3。12kHzは含めない
    assert snare_flux(S, freqs)[1] == 3.0


def test_reconcile_beats_subdivides_half_tempo():
    """ビート追従が半分のテンポ(オクターブ誤り)を掴んだら分割して直す。"""
    beats = np.arange(0, 8.1, 1.0)            # 1秒間隔＝60BPM
    fixed = reconcile_beats(beats, tempo=120.0)   # 本当は0.5秒間隔
    assert abs(np.median(np.diff(fixed)) - 0.5) < 1e-6


def test_reconcile_beats_thins_double_tempo():
    beats = np.arange(0, 8.1, 0.25)           # 0.25秒間隔＝240BPM
    fixed = reconcile_beats(beats, tempo=120.0)
    assert abs(np.median(np.diff(fixed)) - 0.5) < 1e-6


def test_reconcile_beats_leaves_correct_tempo_alone():
    beats = np.arange(0, 8.1, 0.5)
    assert np.allclose(reconcile_beats(beats, tempo=120.0), beats)


def test_reconcile_beats_keeps_drift_when_subdividing():
    """分割してもテンポ揺れは保つ（等間隔に均さない）。"""
    beats = np.array([0.0, 1.0, 2.4])         # 後半が伸びている
    fixed = reconcile_beats(beats, tempo=120.0)
    d = np.diff(fixed)
    assert d[0] < d[-1]                        # 揺れが残っている


def test_anchor_beats_prepends_phase_beats():
    beats = np.array([1.0, 1.5, 2.0])
    assert np.allclose(anchor_beats(beats, 0), beats)
    assert np.allclose(anchor_beats(beats, 2), [0.0, 0.5, 1.0, 1.5, 2.0])


def test_beat_step_times_interpolates_between_beats():
    beats = np.array([0.0, 1.0, 2.0])
    st = beat_step_times(beats, 8, steps_per_beat=4)
    assert np.allclose(st, [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75])


def test_beat_step_times_follows_tempo_drift():
    """拍が伸びればステップも伸びる（一定テンポで敷かない）。"""
    beats = np.array([0.0, 1.0, 3.0])          # 2拍目以降が2倍に伸びる
    st = beat_step_times(beats, 8, steps_per_beat=4)
    assert np.allclose(st[:5], [0.0, 0.25, 0.5, 0.75, 1.0])
    assert np.allclose(st[5:], [1.5, 2.0, 2.5])


def test_beat_step_times_extrapolates_past_last_beat():
    beats = np.array([0.0, 1.0])
    st = beat_step_times(beats, 8, steps_per_beat=4)
    assert np.allclose(st, np.arange(8) * 0.25)


def test_step_peak_values_takes_window_max():
    flux = np.array([0.0, 0.0, 7.0, 0.0, 0.0, 3.0, 0.0, 0.0])
    sr, hop = 100, 10                          # 1フレーム=0.1秒
    vals = step_peak_values(flux, [0.2, 0.5], sr, hop, half_win=0.1)
    assert vals[0] == 7.0                      # フレーム1〜3の最大
    assert vals[1] == 3.0                      # フレーム4〜6の最大


def test_hits_from_values_uses_relative_threshold():
    """絶対値ではなく、その帯域自身の上位に対する比で決める。"""
    vals = [0.0, 10.0, 1.0, 9.0]
    assert hits_from_values(vals, frac=0.5, ref_pct=100) == [0, 1, 0, 1]
    # 全体を100倍しても結果は変わらない（曲の音量に依存しない）
    assert hits_from_values([v * 100 for v in vals], frac=0.5,
                            ref_pct=100) == [0, 1, 0, 1]


def test_hits_from_values_silent_lane_has_no_hits():
    assert hits_from_values([0.0] * 8) == [0] * 8


def test_choose_bar_phase_finds_the_downbeat():
    """4拍に1回だけ低域が立つ音源なら、その拍を小節頭にする位相を選ぶ。"""
    sr, hop = 100, 10
    flux = np.zeros(400)
    # 拍間隔1.0秒＝10フレーム。拍2,6,10... に強い低域を置く
    beats = np.arange(0, 40.0, 1.0)
    for b in range(2, 40, 4):
        flux[int(b * sr / hop)] = 1.0
    phase = choose_bar_phase(flux, beats, n_steps=16 * 8, sr=sr, hop=hop,
                             steps_per_bar=16)
    # 最初の拍(index0)から数えて2拍目が小節頭 → 手前に2拍継ぎ足す位相
    assert phase == 2


def test_high_freq_fraction():
    freqs = np.array([100.0, 1000.0, 6000.0, 8000.0])
    S = np.ones((4, 1))                       # 各ビン等エネルギー・1フレーム
    assert abs(high_freq_fraction(S, freqs) - 0.5) < 1e-9   # 4ビン中2ビンが5kHz以上
    assert high_freq_fraction(np.zeros((4, 1)), freqs) == 0.0


def test_resolve_hihat_subdivision_presence_fallback():
    bar_sec = 2.0
    # オンセットが弱くても高域エネルギーがあれば8分を既定に
    assert resolve_hihat_subdivision([], 1, bar_sec, 0.1) == 8
    # 高域エネルギーも無ければ空のまま（None）
    assert resolve_hihat_subdivision([], 1, bar_sec, 0.0) is None
    # 密なオンセットは密度判定が優先（高域の有無に依らず16）
    dense = [i * bar_sec / 16 for i in range(16)]
    assert resolve_hihat_subdivision(dense, 1, bar_sec, 0.0) == 16


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


def test_transcribe_drums_survives_audio_too_short_for_beat_tracking(tmp_path):
    """拍が2つも取れない極端に短い音源でも落ちない（保険のグリッドに落ちる）。"""
    wav = tmp_path / "tiny.wav"
    sf.write(str(wav), np.zeros(2205, dtype=np.float32), 22050)   # 0.1秒の無音
    grid = transcribe_drums(str(wav), tempo=120.0, bars=1)
    assert len(grid["lanes"]["KK"]) == 16


def test_repair_beat_runs_leaves_a_clean_beat_list_untouched():
    """異常が無ければ1つも動かさない。他の曲のテンポ揺れ追従を壊さないため。"""
    beats = np.arange(20) * 0.5
    assert np.array_equal(repair_beat_runs(beats), beats)


def test_repair_beat_runs_removes_an_inserted_beat():
    """3拍分の時間に4拍が入った区間を、3拍に引き直す（MOONで実際に起きた形）。

    ここを直さないと、余分な1拍のぶんだけ**そこから先の小節位相が丸ごとずれる**。
    実測ではキックとスネアが40小節にわたって1拍ぶん反転していた。
    """
    good = list(np.arange(10) * 0.5)                  # 0.0 〜 4.5
    bad = [4.5 + 0.375 * k for k in range(1, 5)]      # 1.5秒を4分割＝0.75倍が4連続
    tail = list(6.0 + np.arange(1, 10) * 0.5)
    got = repair_beat_runs(np.array(good + bad + tail))

    assert len(got) == len(good) + 3 + len(tail)      # 4拍が3拍になる
    assert np.allclose(np.diff(got), 0.5)             # 全体が等間隔に戻る


def test_repair_beat_runs_keeps_the_beats_around_the_damaged_run():
    """壊れた区間の外側の拍は1つも動かさない。"""
    good = list(np.arange(6) * 0.5)
    bad = [2.5 + 0.375 * k for k in range(1, 5)]
    tail = list(4.0 + np.arange(1, 6) * 0.5)
    got = repair_beat_runs(np.array(good + bad + tail))
    for t in good + tail:
        assert np.isclose(got, t).any()


def test_repair_beat_runs_survives_a_short_list():
    assert len(repair_beat_runs(np.array([1.0, 2.0]))) == 2
    assert len(repair_beat_runs(np.array([]))) == 0
