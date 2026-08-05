"""採譜が「音楽になっているか」を守るテスト。

2026-08-02 の実曲検証で、打点の数は妥当なのに位置がでたらめ（スネアの2拍4拍
占有率が偶然と同じ12%）という失敗をした。数や形だけを見るテストではその失敗を
検出できなかったので、**位置**を見るテストをここに置く。

なお合成音は実曲を代表しない（2026-08-02 の教訓）。ここは最低ラインの砦であって、
本番の合否は実曲での `adt_check.py` で判定する。
"""
import numpy as np
import soundfile as sf

from app.drum_transcribe import transcribe_drums

TEMPO = 120.0
BARS = 8
LEAD_IN = 0.31          # 1拍目は t=0 に来ない。わざと半端な位置から始める


def _write_rock_groove(path, sr=22050, tempo=TEMPO, bars=BARS, lead_in=LEAD_IN):
    """キック=1拍3拍 / スネア=2拍4拍 の8ビート。頭に半端な長さの無音を置く。"""
    bar_sec = 4 * 60.0 / tempo
    x = np.zeros(int(sr * (lead_in + bar_sec * bars + 0.5)))
    rs = np.random.RandomState(0)

    def add(t0, seg):
        i0 = int(t0 * sr)
        n = min(len(seg), len(x) - i0)
        if n > 0:
            x[i0:i0 + n] += seg[:n]

    def kick():
        env = np.exp(-np.linspace(0, 25, int(0.12 * sr)))
        return np.sin(2 * np.pi * 55 * np.arange(len(env)) / sr) * env

    def snare():
        env = np.exp(-np.linspace(0, 20, int(0.15 * sr)))
        n = len(env)
        return rs.randn(n) * env * 0.5 + \
            np.sin(2 * np.pi * 220 * np.arange(n) / sr) * env * 0.4

    for b in range(bars):
        t = lead_in + b * bar_sec
        add(t, kick())                       # 1拍
        add(t + bar_sec / 4, snare())        # 2拍
        add(t + bar_sec / 2, kick())         # 3拍
        add(t + 3 * bar_sec / 4, snare())    # 4拍
    sf.write(path, x.astype(np.float32), sr)


def _position_hist(grid, lane):
    spb = grid["steps_per_bar"]
    h = [0] * spb
    for i, v in enumerate(grid["lanes"][lane]):
        if v:
            h[i % spb] += 1
    return h


def test_snare_lands_on_backbeat_despite_lead_in(tmp_path):
    """スネアは2拍4拍(step 4・12)に集中しなければならない。

    グリッドを t=0 起点で敷くと、頭の無音(0.31s=2.48step)の分だけ全打点がずれ、
    占有率は偶然(12.5%)まで落ちる。拍に合わせて敷けば集中する。
    """
    wav = tmp_path / "groove.wav"
    _write_rock_groove(str(wav))
    grid = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS)

    h = _position_hist(grid, "SN")
    total = sum(h)
    assert total > 0, "スネアが1つも検出されていない"
    backbeat = (h[4] + h[12]) / total * 100
    assert backbeat >= 50, (
        f"スネアの2拍4拍占有率 {backbeat:.0f}% （偶然は12.5%）。"
        f"小節内ヒスト={h}")


def test_kick_lands_on_downbeat_despite_lead_in(tmp_path):
    """キックは1拍3拍(step 0・8)に集中しなければならない。"""
    wav = tmp_path / "groove.wav"
    _write_rock_groove(str(wav))
    grid = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS)

    h = _position_hist(grid, "KK")
    total = sum(h)
    assert total > 0, "キックが1つも検出されていない"
    on = (h[0] + h[8]) / total * 100
    assert on >= 50, (
        f"キックの1拍3拍占有率 {on:.0f}% （偶然は12.5%）。小節内ヒスト={h}")


def test_kick_and_snare_are_not_the_same_lane(tmp_path):
    """同じステップを両方が主張する率が高いなら、楽器を判別できていない。"""
    wav = tmp_path / "groove.wav"
    _write_rock_groove(str(wav))
    grid = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS)

    kk = grid["lanes"]["KK"]
    sn = grid["lanes"]["SN"]
    both = sum(1 for a, b in zip(kk, sn) if a and b)
    assert sum(kk) > 0
    overlap = both / sum(kk) * 100
    assert overlap < 50, f"キックの{overlap:.0f}%をスネアも主張している"
