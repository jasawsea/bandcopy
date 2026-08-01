"""ドラム音源 → グリッドの自動下書き（A1: 依存ゼロNMF）。

KK/SN/HH の3レーンだけ自動で埋める。タム(HT/MT/FT)は全0で返し人が手入力する。
どのレーンが自動対象かは app/lanes.py の auto フラグが単一ソース。
"""
import numpy as np

from app import lanes as lane_defs


def quantize_onsets_to_grid(onset_times, step_times):
    """各オンセット時刻を最近傍のグリッドステップに吸着し、昇順ユニークなインデックスを返す。"""
    steps = np.asarray(step_times, dtype=float)
    idxs = set()
    for t in onset_times:
        idxs.add(int(np.argmin(np.abs(steps - t))))
    return sorted(idxs)


def remove_ghost(peak_indices, strengths, threshold):
    """strength が threshold 未満の peak を除去する（装飾音・にじみ対策）。"""
    return [p for p, s in zip(peak_indices, strengths) if s >= threshold]


def infer_hihat_subdivision(hh_onset_times, bars, bar_sec):
    """ハイハットのオンセット密度から、優勢な刻みを 16 / 8 / None で返す。"""
    if not hh_onset_times or bars <= 0:
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


def resolve_hihat_subdivision(hh_onset_times, bars, bar_sec, hf_fraction, presence_floor=0.02):
    """HHの刻みを決める。密度で 16/8 を判定し、判定不能でも高域エネルギーが
    presence_floor 以上（ハットが鳴っている）なら 8分を既定として敷く。

    オンセット検出だけではハットを拾いきれない（NMFでスネアの高域成分に吸われる）
    ため、高域エネルギーの有無をフォールバックの手掛かりにする。
    """
    sub = infer_hihat_subdivision(hh_onset_times, bars, bar_sec)
    if sub is None and hf_fraction >= presence_floor:
        return 8
    return sub


def _band(freqs, lo, hi, floor=0.01):
    """[lo,hi]Hz を 1.0、外を floor にした非負の帯域ベクトル。"""
    v = np.full(freqs.shape, floor, dtype=float)
    v[(freqs >= lo) & (freqs <= hi)] = 1.0
    return v


def build_drum_templates(sr, n_fft):
    """KK/SN/HH の固定スペクトルテンプレート W（列＝各成分）を作る。"""
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    kk = _band(freqs, 30, 120)                       # キック：低域
    sn = _band(freqs, 150, 400) + 0.5 * _band(freqs, 2000, 8000)  # スネア：胴＋ノイズ
    hh = _band(freqs, 6000, sr / 2)                  # ハイハット：高域
    W = np.stack([kk, sn, hh], axis=1)
    W /= (W.sum(axis=0, keepdims=True) + 1e-9)       # 列を正規化
    return W


def nmf_activations(V, W, iters=50):
    """W を固定して活性 H のみを乗算更新で推定する（教師ありNMF）。"""
    eps = 1e-9
    H = np.full((W.shape[1], V.shape[1]), V.mean() + eps)
    Wt = W.T
    WtW = Wt @ W
    for _ in range(iters):
        H *= (Wt @ V) / (WtW @ H + eps)
    return H


def _onsets_from_activation(env, sr, hop, wait=2):
    """1成分の活性エンベロープからオンセット時刻と（0〜1正規化した）強度を返す。

    ピーク検出のみを行い、強度によるふるい分けは呼び出し側（remove_ghost）に任せる。
    """
    import librosa
    if env.max() <= 0:
        return [], []
    norm = env / env.max()
    peaks = librosa.util.peak_pick(
        norm, pre_max=2, post_max=2, pre_avg=3, post_avg=3, delta=0.05, wait=wait
    )
    peaks = [int(p) for p in peaks]
    times = [p * hop / sr for p in peaks]
    strengths = [float(norm[p]) for p in peaks]
    return times, strengths


def transcribe_drums(drum_wav_path, tempo, bars, steps_per_bar=16):
    """ドラム音源からKK/SN/HHを自動採譜した6レーングリッドを返す。タムは全0。"""
    import librosa

    n_fft, hop = 1024, 256
    y, sr = librosa.load(drum_wav_path, sr=None, mono=True)
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    W = build_drum_templates(sr, n_fft)
    H = nmf_activations(S, W)

    n = bars * steps_per_bar
    bar_sec = 4 * 60.0 / tempo
    step_sec = bar_sec / steps_per_bar
    step_times = [s * step_sec for s in range(n)]

    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    lanes = {lane: [0] * n for lane in lane_defs.keys()}

    # KK=行0, SN=行1：オンセットを拾い、弱い打点(ゴースト)を除いて量子化して置く
    for row, lane in ((0, "KK"), (1, "SN")):
        times, strengths = _onsets_from_activation(H[row], sr, hop, wait=3)
        kept = remove_ghost(list(range(len(times))), strengths, 0.4)
        times = [times[i] for i in kept]
        for idx in quantize_onsets_to_grid(times, step_times):
            if idx < n:
                lanes[lane][idx] = 1

    # HH=行2：密度で刻みを判定。弱くても高域エネルギーがあれば8分を既定にする
    hh_times, _ = _onsets_from_activation(H[2], sr, hop)
    hf = high_freq_fraction(S, freqs)
    sub = resolve_hihat_subdivision(hh_times, bars, bar_sec, hf)
    lanes["HH"] = fill_regular_hihat(sub, bars, steps_per_bar)

    return {"tempo": tempo, "bars": bars, "steps_per_bar": steps_per_bar, "lanes": lanes}
