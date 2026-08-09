"""ドラム音源 → グリッドの自動下書き（帯域フラックス＋拍同期グリッド）。

KK/SN/HH の3レーンだけ自動で埋める。タム(HT/MT/FT)は全0で返し人が手入力する。
どのレーンが自動対象かは app/lanes.py の auto フラグが単一ソース。

**2026-08-05 に方式を入れ替えた。** 旧方式（固定テンプレートのNMF＋成分ごとの
独立オンセット検出＋t=0起点の固定グリッド）は実曲で譜面にならなかった。切り分けた
結果、原因は2つあり、どちらもここで直している：

1. **グリッドが t=0 起点だった。** 実際の1拍目は無音や息継ぎの後に来るので、
   打点は小節内のでたらめな位置に落ちる。実測で「拍がグリッドの拍位置に乗る割合
   17%（偶然25%を下回る）」。
   → ビート追従で拍を取り、拍列を線形補間してステップ時刻を作る。テンポ揺れにも
     追従する。小節の位相（どの拍が小節頭か）はキックが小節頭に集まる向きを選ぶ。

2. **楽器の判別が活性の「大きさ」に対する独立ピーク検出だった。** 低域の残響で
   活性が常に高く、キックとスネアが同じ瞬間を87〜94%も同時主張していた。
   → 帯域の「立ち上がり」（半波整流微分＝フラックス）を、グリッドの各ステップの
     窓内で見る方式に変えた。オンセット起点ではなくグリッド起点なので、1ステップ
     1レーンにつき最大1打点になり、過検出が構造的に起きない。

※ 2026-08-02 の再開メモが挙げていた候補（floor除去・残差成分の追加・勝者総取り）は
   実測で全て外れだった。どれもスネアの2拍4拍占有率を10〜12%から動かせなかった。
   重複率は症状であって原因ではなかった。

検証は実曲での `adt_check.py` で行う。**合成音の合格は根拠にしない**（2026-08-02 の教訓）。
"""
import numpy as np

from app import lanes as lane_defs

# 打点と見なすしきい値。その帯域の「上位の強さ」に対する比で決める（曲の音量に依らない）。
# **2026-08-09 に 0.5 → 0.25 へ下げた**（やっさん「一旦は原曲通りに」）。
# 下げると細部を拾える一方で倍音の混信が増えるので、下の SUPPRESS_BLEED_RATIO と対で使う。
HIT_THRESHOLD_FRAC = 0.25
HIT_REFERENCE_PCT = 95

# 倍音による混信の抑制。同じステップでKKとSNが両方立ったとき、相手より明確に
# 弱い方を落とす（弱い方 < 強い方 * この比 なら落とす）。
# キックの倍音がスネア帯域に、スネアの低域成分がキック帯域に届くため、
# 1打点が2レーンで鳴る。実測では 0.25+抑制で重複67%→15%・2拍4拍33%→53%。
# **HHは対象外**：ハイハットはKK/SNと同時に鳴るのが普通で、落とすと譜面が壊れる。
SUPPRESS_BLEED_RATIO = 0.8

# 各レーンが使う帯域（Hz）。スネアは胴とノイズの2帯域を足す。
KICK_BAND = (30, 120)
SNARE_BANDS = ((150, 400), (2000, 8000))
HIHAT_BAND = (6000, None)          # None＝ナイキストまで


def band_flux(S, freqs, lo, hi):
    """帯域エネルギーの半波整流微分（＝立ち上がりだけ）を返す。

    「大きさ」ではなく「立ち上がり」を見るのが要点。低域は残響で大きさが常に高く、
    大きさを見ると打点でない場所でも反応してしまう（旧方式の失敗原因）。
    """
    if hi is None:
        sel = freqs >= lo
    else:
        sel = (freqs >= lo) & (freqs <= hi)
    e = S[sel].sum(axis=0)
    d = np.diff(e, prepend=e[0])
    d[d < 0] = 0.0
    return d


def snare_flux(S, freqs):
    """スネアの帯域フラックス（胴 150-400Hz ＋ ノイズ 2-8kHz）。"""
    return sum(band_flux(S, freqs, lo, hi) for lo, hi in SNARE_BANDS)


def _subdivide(beats, k):
    """隣り合う拍の間を k 等分して拍を細かくする（テンポ揺れは保つ）。"""
    out = []
    for a, b in zip(beats[:-1], beats[1:]):
        out.extend(a + (b - a) * np.arange(k) / k)
    out.append(beats[-1])
    return np.asarray(out, dtype=float)


def reconcile_beats(beats, tempo, tol=0.15):
    """ビート追従が倍・半分のテンポを掴んだときに、指定テンポの拍に直す。

    ビート追従はテンポのオクターブ誤り（2倍・半分）を起こしやすい。曲のテンポは
    呼び出し側が渡してくる値を正とし、拍の**間隔**はそちらに合わせる。一方で拍の
    **位置**（位相とテンポ揺れ）は追従結果を活かす。
    """
    beats = np.asarray(beats, dtype=float)
    if len(beats) < 2 or tempo <= 0:
        return beats
    want = 60.0 / tempo
    got = float(np.median(np.diff(beats)))
    if got <= 0:
        return beats
    ratio = got / want
    k = int(round(ratio))
    if k >= 2 and abs(ratio - k) <= tol * k:            # 粗すぎた → 分割する
        return _subdivide(beats, k)
    inv = int(round(1 / ratio))
    if inv >= 2 and abs(1 / ratio - inv) <= tol * inv:  # 細かすぎた → 間引く
        return beats[::inv]
    return beats


def repair_beat_runs(beats, floor=0.85):
    """間隔が中央値より明らかに詰まった区間だけ、本来の拍数で等分に引き直す。

    **なぜ必要か（2026-08-09 MOONで判明）**：ビート追従は曲の途中で拍を余分に
    挿入することがある。MOONでは2箇所で**3拍分の時間に4拍**が置かれていた
    （間隔0.75倍が4連続）。`beat_step_times` は拍を**番号で**辿るので、
    余分な拍が1つ入るとそこから先の小節位相が丸ごと1拍ずれる。
    実際にキックが1拍3拍→2拍4拍、スネアが2拍4拍→1拍3拍へ40小節ぶん反転し、
    挿入が2箇所あったため後半で元に戻る、という形で現れていた
    （スネアの2拍4拍占有率 39%＝他5曲の62〜73%に対して極端に低い）。

    詰まった区間の前後の拍は正しいので、その間を中央値で割った本数に引き直す。
    **異常が無ければ入力をそのまま返す。** 全体を予測値で引き直す案も測ったが、
    テンポ揺れ追従を壊して他4曲が悪化した（MOON 39→47%・GLAMOROUS_SKY 66→57%）。
    区間限定なら他5曲の数字は1つも動かず、MOONだけ 39→50% に上がる。
    """
    beats = np.asarray(beats, dtype=float)
    if len(beats) < 3:
        return beats
    d = np.diff(beats)
    med = float(np.median(d))
    if med <= 0:
        return beats

    out, i = [float(beats[0])], 0
    while i < len(d):
        if d[i] >= med * floor:
            out.append(float(beats[i + 1]))
            i += 1
            continue
        j = i
        while j < len(d) and d[j] < med * floor:     # 詰まった区間の終わりを探す
            j += 1
        span = float(beats[j] - beats[i])
        n = max(1, int(round(span / med)))           # 本来あるべき拍数
        for k in range(1, n + 1):
            out.append(float(beats[i]) + span * k / n)
        i = j
    return np.asarray(out)


def anchor_beats(beats, phase):
    """小節の位相をずらす。phase 拍ぶんだけ手前に拍を継ぎ足す。

    phase=1 なら「最初に検出した拍は小節の2拍目だった」と解釈することになる。
    """
    beats = np.asarray(beats, dtype=float)
    if phase <= 0 or len(beats) < 2:
        return beats
    interval = float(np.median(np.diff(beats)))
    head = beats[0] - interval * np.arange(phase, 0, -1)
    return np.concatenate([head, beats])


def beat_step_times(beats, n_steps, steps_per_beat=4):
    """拍列を線形補間して各ステップの時刻を作る（テンポ揺れに追従する）。

    足りない分は最後の拍間隔で外挿する。
    """
    beats = np.asarray(beats, dtype=float)
    want = np.arange(n_steps, dtype=float) / steps_per_beat
    if len(beats) < 2:
        interval = 0.5 if len(beats) == 0 else 0.5
        origin = beats[0] if len(beats) else 0.0
        return origin + want * interval
    idx = np.arange(len(beats), dtype=float)
    interval = float(np.median(np.diff(beats)))
    out = np.interp(want, idx, beats)
    tail = want > idx[-1]                      # 拍列より先は等間隔で伸ばす
    out[tail] = beats[-1] + (want[tail] - idx[-1]) * interval
    return out


def step_peak_values(flux, step_times, sr, hop, half_win):
    """各ステップ時刻の ±half_win 秒の窓での flux 最大値を返す。

    窓は半ステップ幅にするので隙間なく・重なりなくタイル状に並ぶ。
    """
    frames = np.rint(np.asarray(step_times) * sr / hop).astype(int)
    w = max(1, int(round(half_win * sr / hop)))
    out = np.zeros(len(frames))
    for i, f in enumerate(frames):
        a, b = max(0, f - w), min(len(flux), f + w + 1)
        if a < b:
            out[i] = flux[a:b].max()
    return out


def hits_from_values(values, frac=HIT_THRESHOLD_FRAC, ref_pct=HIT_REFERENCE_PCT):
    """上位 ref_pct パーセンタイルの frac 倍を超えたステップを打点にする。

    曲ごとの音量差に左右されないよう、絶対値ではなくその帯域自身の分布で決める。
    """
    values = np.asarray(values, dtype=float)
    ref = float(np.percentile(values, ref_pct)) if len(values) else 0.0
    if ref <= 0:
        return [0] * len(values)
    return [1 if v > frac * ref else 0 for v in values]


def suppress_bleed(kk_hits, sn_hits, kk_values, sn_values,
                   ratio=SUPPRESS_BLEED_RATIO):
    """同じステップでKK/SNが両方立ったとき、相手より明確に弱い方を落とす。

    倍音の混信対策。1つの打点が2レーンで鳴るのを減らす。帯域どうしは絶対値を
    比べられないので、それぞれ自分の上位値で正規化してから比べる。

    ratio を大きくするほど強く抑制する（1.0で「弱い方は必ず落とす」）。
    同じくらいの強さで両方鳴っていれば、実際に同時に叩いたものとして両方残す。
    """
    kv, sv = np.asarray(kk_values, dtype=float), np.asarray(sn_values, dtype=float)
    kn = kv / (np.percentile(kv, HIT_REFERENCE_PCT) + 1e-9)
    sn = sv / (np.percentile(sv, HIT_REFERENCE_PCT) + 1e-9)
    kk_out, sn_out = list(kk_hits), list(sn_hits)
    for i, (a, b) in enumerate(zip(kk_out, sn_out)):
        if not (a and b):
            continue
        if kn[i] < sn[i] * ratio:
            kk_out[i] = 0
        elif sn[i] < kn[i] * ratio:
            sn_out[i] = 0
    return kk_out, sn_out


def choose_bar_phase(flux, beats, n_steps, sr, hop, steps_per_bar):
    """小節頭にキックが最も集まる位相(0〜3)を選ぶ。

    ビート追従は拍の位置は当てるが「どれが小節の1拍目か」は教えてくれないので、
    低域の立ち上がりが小節頭に集まる向きを選ぶ（小節頭はたいてい低域が張る）。
    """
    steps_per_beat = max(1, steps_per_bar // 4)
    best_phase, best_score = 0, -np.inf
    for phase in range(4):
        st = beat_step_times(anchor_beats(beats, phase), n_steps, steps_per_beat)
        half = _half_step(st)
        vals = step_peak_values(flux, st, sr, hop, half)
        mean = vals.mean()
        if mean <= 0:
            continue
        score = vals[0::steps_per_bar].mean() / mean
        if score > best_score:
            best_phase, best_score = phase, score
    return best_phase


def _half_step(step_times):
    """半ステップ幅（秒）。窓の半径に使う。"""
    if len(step_times) < 2:
        return 0.05
    return float(np.median(np.diff(step_times))) / 2


def _fixed_step_times(tempo, n_steps, steps_per_bar):
    """ビート追従が使えないときの保険＝t=0起点の等間隔グリッド。"""
    step_sec = (4 * 60.0 / tempo) / steps_per_bar
    return np.arange(n_steps, dtype=float) * step_sec


def infer_hihat_subdivision(hh_onset_times, bars, bar_sec):
    """ハイハットのオンセット密度から、優勢な刻みを 16 / 8 / None で返す。"""
    if not len(hh_onset_times) or bars <= 0:
        return None
    per_bar = len(hh_onset_times) / bars
    if per_bar >= 12:      # 16分寄り（16打点の75%以上）
        return 16
    if per_bar >= 5:       # 8分寄り（8打点の60%以上）
        return 8
    return None


def fill_regular_hihat(subdivision, bars, steps_per_bar=16):
    """判定した刻みで全小節に規則パターンを敷く。8分=2ステップおき、16分=毎ステップ。"""
    n = bars * steps_per_bar
    if subdivision == 16:
        return [1] * n
    if subdivision == 8:
        return [1 if s % 2 == 0 else 0 for s in range(n)]
    return [0] * n


def high_freq_fraction(S, freqs, floor_hz=5000.0):
    """スペクトル総エネルギーに占める floor_hz 以上の割合（ハット/シンバルの存在指標）。"""
    total = float(S.sum())
    if total <= 0:
        return 0.0
    return float(S[freqs >= floor_hz].sum()) / total


def resolve_hihat_subdivision(hh_onset_times, bars, bar_sec, hf_fraction,
                              presence_floor=0.02):
    """HHの刻みを決める。密度で 16/8 を判定し、判定不能でも高域エネルギーが
    presence_floor 以上（ハットが鳴っている）なら 8分を既定として敷く。
    """
    sub = infer_hihat_subdivision(hh_onset_times, bars, bar_sec)
    if sub is None and hf_fraction >= presence_floor:
        return 8
    return sub


# タムを3レーンに振り分ける境目（Hz）。drumsep で分離した後なら、
# 他の太鼓が混ざらないので高さだけで素直に切れる。
# 実測（MORE）：タムの主要周波数は 65〜215Hz・中央値151Hz。
TOM_SPLIT_HZ = (110, 175)
TOM_PITCH_BAND = (60, 400)


def tom_pitch(S, freqs, frame, lo=TOM_PITCH_BAND[0], hi=TOM_PITCH_BAND[1]):
    """その時刻でいちばん強い周波数を返す（タムの高さの判定用）。"""
    sel = (freqs >= lo) & (freqs <= hi)
    seg = S[:, max(0, frame - 1):frame + 3]
    if seg.shape[1] == 0:
        return None
    sub = seg.mean(axis=1)[sel]
    if sub.size == 0 or sub.max() <= 0:
        return None
    return float(freqs[sel][sub.argmax()])


def assign_tom_lane(pitch, split=TOM_SPLIT_HZ):
    """周波数から FT / MT / HT を決める（低いほどフロアタム）。"""
    if pitch is None:
        return None
    lo, hi = split
    if pitch < lo:
        return "FT"
    return "MT" if pitch < hi else "HT"


def transcribe_with_separation(drum_wav, tempo, bars, work_dir, **kwargs):
    """LarsNetでスネアを分離してから採譜する。重みが無ければ帯域方式のまま動く。

    **なぜスネアだけ分離を挟むか（2026-08-09 実測）**：帯域方式のスネアは
    過検出していた。分離音源から拾うと打点が減りながら2拍4拍の集中度が上がる
    ＝削れているのが拍から外れた偽の打点だということ。

        GLAMOROUS_SKY 55%→66% / MORE 53%→69% / RADIO_MAGIC 57%→63% /
        The_Best_Song 61%→73% / MOON 38%→39%（横ばい）

    打点数も6曲すべてで「1小節2発」に近づいた（例：506→322打点・期待342）。

    **タムは分離しても採れなかった**ので、ここでも渡さない。LarsNetのタム音源は
    いちばん強い成分がキック・スネアの位置にあり（同時率が偶然水準の1.4〜4.8倍）、
    フィルではなく滲みを拾う。帯域方式・drumsepと合わせて3方式とも同じ失敗。
    フィルはエディタで手入力する。
    """
    from app import larsnet

    snare = larsnet.snare_stem(drum_wav, work_dir)
    return transcribe_drums(drum_wav, tempo, bars, snare_wav=snare, **kwargs)


def separated_flux(wav_path, lo, hi, n_fft=1024, hop=256):
    """分離済みの単一楽器音源から立ち上がりを取る。

    帯域で楽器を選り分ける必要がないので、その楽器が占める範囲を広めに取る。
    戻り値は (flux, サンプリングレート, hop, スペクトログラム, 周波数軸)。
    """
    import librosa

    y, sr = librosa.load(wav_path, sr=None, mono=True)
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    return band_flux(S, freqs, lo, hi), sr, hop, S, freqs


def transcribe_drums(drum_wav_path, tempo, bars, steps_per_bar=16,
                     threshold=HIT_THRESHOLD_FRAC, regular_hihat=False,
                     suppress_ratio=SUPPRESS_BLEED_RATIO, kick_wav=None,
                     snare_wav=None, toms_wav=None, tom_threshold=None):
    """ドラム音源からKK/SN/HHを自動採譜した6レーングリッドを返す。タムは全0。

    kick_wav: drumsep で分離したキック音源。渡すと**キックの検出と小節の位相決めに
        こちらを使う**（混ざり物が無いぶん正確になる）。スネア・ハイハットは
        従来どおり drum_wav_path から拾う。

    snare_wav / toms_wav: LarsNet で分離したスネア／タム音源（評価中・既定は使わない）。
        toms_wav を渡したときだけ HT/MT/FT が埋まる。タムの高さは `tom_pitch` で
        測って `assign_tom_lane` で3レーンに振り分ける。

    threshold: 小さいほど細かい打点まで拾う（原曲に忠実／倍音の混信も増える）。
    suppress_ratio: 倍音による混信の抑制の強さ。0/None で抑制しない。
    regular_hihat: True にすると**ハイハットを実検出せず**、密度から決めた
        8分/16分の規則パターンを全小節に敷く（旧来の挙動）。

    **2026-08-09 にハイハットを実検出に変えた。** 旧来は規則パターンを敷いていたため、
    157小節すべてが同じ8分になり「譜面が音源と違う・細かなリフが入っていない」状態
    だった（やっさん指摘）。実検出にすると小節ごとの型が1種類→64〜92種類になる。
    """
    import librosa

    n_fft, hop = 1024, 256
    y, sr = librosa.load(drum_wav_path, sr=None, mono=True)
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)

    if snare_wav:
        sn_flux, sn_sr, sn_hop, _, _ = separated_flux(snare_wav, 100, None)
    else:
        sn_flux, sn_sr, sn_hop = snare_flux(S, freqs), sr, hop
    hh_flux = band_flux(S, freqs, *HIHAT_BAND)

    # キックは分離音源があればそちらを使う。混ざり物が無いぶん位置が正確になる
    # （実測：拍頭占有率 38% → 55%）。スネア/ハイハットは分離すると悪化したので
    # 従来どおり混合音源から拾う（下の「試して採用しなかったこと」を参照）。
    kk_sr, kk_hop = sr, hop
    if kick_wav:
        ky, kk_sr = librosa.load(kick_wav, sr=None, mono=True)
        Sk = np.abs(librosa.stft(ky, n_fft=n_fft, hop_length=hop))
        kk_flux = band_flux(Sk, np.fft.rfftfreq(n_fft, 1 / kk_sr), 20, 200)
    else:
        kk_flux = band_flux(S, freqs, *KICK_BAND)

    n = bars * steps_per_bar
    bar_sec = 4 * 60.0 / tempo
    steps_per_beat = max(1, steps_per_bar // 4)

    # --- グリッドを実際の拍に合わせる（ここが旧方式との最大の違い） ---
    _, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, hop_length=hop, start_bpm=tempo, tightness=100)
    beats = repair_beat_runs(reconcile_beats(
        librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop), tempo))
    if len(beats) >= 2:
        phase = choose_bar_phase(kk_flux, beats, n, kk_sr, kk_hop, steps_per_bar)
        step_times = beat_step_times(
            anchor_beats(beats, phase), n, steps_per_beat)
    else:
        step_times = _fixed_step_times(tempo, n, steps_per_bar)   # 保険

    half = _half_step(step_times)
    lanes = {lane: [0] * n for lane in lane_defs.keys()}
    kk_vals = step_peak_values(kk_flux, step_times, kk_sr, kk_hop, half)
    sn_vals = step_peak_values(sn_flux, step_times, sn_sr, sn_hop, half)
    kk_hits = hits_from_values(kk_vals, threshold)
    sn_hits = hits_from_values(sn_vals, threshold)
    if suppress_ratio:
        # 倍音の混信で1打点が2レーンで鳴るのを減らす
        kk_hits, sn_hits = suppress_bleed(
            kk_hits, sn_hits, kk_vals, sn_vals, suppress_ratio)
    lanes["KK"], lanes["SN"] = kk_hits, sn_hits

    hh_hits = hits_from_values(
        step_peak_values(hh_flux, step_times, sr, hop, half), threshold)
    if regular_hihat:
        # 旧来の挙動：密度から刻みを決めて規則パターンを敷く
        hh_times = [t for t, v in zip(step_times, hh_hits) if v]
        hf = high_freq_fraction(S, freqs)
        sub = resolve_hihat_subdivision(hh_times, bars, bar_sec, hf)
        lanes["HH"] = fill_regular_hihat(sub, bars, steps_per_bar)
    else:
        lanes["HH"] = hh_hits

    # タム(HT/MT/FT)。既定では全0のまま人が手入力する。
    # **帯域だけの自動検出は載せられなかった（2026-08-09）**：胴の帯域(90-320Hz)で
    # 高域ノイズが少ない打点をタムとみなす方式を実測したところ、候補の
    # 80〜85%がキックと同じステップだった＝キックの二重検出。
    # → 分離音源(toms_wav)を渡したときだけ埋める。
    if toms_wav:
        tm_flux, tm_sr, tm_hop, St, ft = separated_flux(toms_wav, 40, None)
        tm_vals = step_peak_values(tm_flux, step_times, tm_sr, tm_hop, half)
        # タムは鳴っている時間が短い（フィルのときだけ）ので、KK/SN と同じ
        # しきい値を当てると滲みまで拾ってしまう。既定は呼び出し側の threshold。
        for i, hit in enumerate(hits_from_values(
                tm_vals, tom_threshold if tom_threshold is not None else threshold)):
            if not hit:
                continue
            frame = int(round(step_times[i] * tm_sr / tm_hop))
            lane = assign_tom_lane(tom_pitch(St, ft, frame))
            if lane:
                lanes[lane][i] = 1

    return {"tempo": tempo, "bars": bars, "steps_per_bar": steps_per_bar,
            "lanes": lanes}
