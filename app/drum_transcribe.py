"""ドラム音源 → グリッドの自動下書き（A1: 依存ゼロNMF）。

KK/SN/HH の3レーンだけ自動で埋める。タム(HT/MT/FT)は全0で返し人が手入力する。
"""
import numpy as np


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
