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


def test_hihat_varies_between_bars(tmp_path):
    """ハイハットが小節ごとに変化すること。

    旧来は密度から決めた規則パターンを全小節に敷いていたため、157小節すべてが
    同じ8分になり「譜面が音源と違う」状態だった（2026-08-09 やっさん指摘）。
    """
    import soundfile as sf
    wav = tmp_path / "vary.wav"
    sr, tempo, bars = 22050, 120.0, 8
    bar_sec = 4 * 60.0 / tempo
    x = np.zeros(int(sr * bar_sec * bars))

    def tick(t0):
        i0 = int(t0 * sr)
        env = np.exp(-np.linspace(0, 60, int(0.03 * sr)))
        seg = np.random.RandomState(1).randn(len(env)) * env * 0.6
        # 高域だけ残す（ハイハット相当）
        seg = np.diff(seg, prepend=seg[0])
        n = min(len(seg), len(x) - i0)
        if n > 0:
            x[i0:i0 + n] += seg[:n]

    for b in range(bars):
        t = b * bar_sec
        # 偶数小節は8分、奇数小節は4分だけ＝小節ごとに違う型にする
        step = bar_sec / 8 if b % 2 == 0 else bar_sec / 4
        k = 8 if b % 2 == 0 else 4
        for i in range(k):
            tick(t + i * step)
    sf.write(str(wav), x.astype(np.float32), sr)

    grid = transcribe_drums(str(wav), tempo=tempo, bars=bars)
    spb = grid["steps_per_bar"]
    hh = grid["lanes"]["HH"]
    patterns = {tuple(hh[b * spb:(b + 1) * spb]) for b in range(bars)}
    assert len(patterns) > 1, f"全小節が同じ型になっている: {patterns}"


def test_regular_hihat_option_restores_old_behaviour(tmp_path):
    """規則パターンに戻す選択肢は残す（下書きとして扱いやすい場面がある）。"""
    wav = tmp_path / "groove.wav"
    _write_rock_groove(str(wav))
    grid = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS, regular_hihat=True)
    spb = grid["steps_per_bar"]
    hh = grid["lanes"]["HH"]
    patterns = {tuple(hh[b * spb:(b + 1) * spb]) for b in range(BARS)}
    assert len(patterns) == 1        # 規則パターンなので全小節同じ


def test_lower_threshold_captures_more(tmp_path):
    """しきい値を下げると打点が増えること（原曲に忠実にするための調整口）。"""
    wav = tmp_path / "groove.wav"
    _write_rock_groove(str(wav))
    coarse = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS, threshold=0.7)
    fine = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS, threshold=0.2)

    def total(g):
        return sum(sum(v) for v in g["lanes"].values())
    assert total(fine) >= total(coarse)


def test_suppress_bleed_drops_the_weaker_lane():
    """同じステップで両方鳴ったら、明確に弱い方を落とす（倍音の混信対策）。"""
    from app.drum_transcribe import suppress_bleed
    #      step0: KKが圧倒的  step1: SNが圧倒的  step2: 同じくらい
    kk_v = [10.0, 1.0, 10.0]
    sn_v = [1.0, 10.0, 10.0]
    kk, sn = suppress_bleed([1, 1, 1], [1, 1, 1], kk_v, sn_v, ratio=0.8)
    assert (kk[0], sn[0]) == (1, 0)      # KKだけ残る
    assert (kk[1], sn[1]) == (0, 1)      # SNだけ残る
    assert (kk[2], sn[2]) == (1, 1)      # 同時に叩いたとみなして両方残す


def test_suppress_bleed_leaves_single_lane_hits_alone():
    from app.drum_transcribe import suppress_bleed
    kk, sn = suppress_bleed([1, 0], [0, 1], [10.0, 1.0], [1.0, 10.0], ratio=0.8)
    assert kk == [1, 0] and sn == [0, 1]


def test_suppression_reduces_overlap_on_real_material(tmp_path):
    """抑制を入れると、同じステップを両方が主張する率が下がること。"""
    wav = tmp_path / "groove.wav"
    _write_rock_groove(str(wav))

    def overlap(grid):
        kk, sn = grid["lanes"]["KK"], grid["lanes"]["SN"]
        both = sum(1 for a, b in zip(kk, sn) if a and b)
        return both / max(sum(kk), 1)

    off = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS, suppress_ratio=0)
    on = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS)
    assert overlap(on) <= overlap(off)


def test_hihat_is_not_suppressed(tmp_path):
    """ハイハットはKK/SNと同時に鳴るのが普通なので、抑制の対象にしない。"""
    wav = tmp_path / "groove.wav"
    _write_rock_groove(str(wav))
    off = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS, suppress_ratio=0)
    on = transcribe_drums(str(wav), tempo=TEMPO, bars=BARS)
    assert sum(on["lanes"]["HH"]) == sum(off["lanes"]["HH"])
