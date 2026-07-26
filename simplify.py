"""
simplify.py
-----------
採譜したMIDIを「バンドで演奏できる難易度」に落とすためのロジック。

このファイルがこのツールの中核。
Demucs（分離）とBasic Pitch（採譜）は既存のオープンソースをそのまま使うが、
「難易度を下げる」処理は既製サービスにないため自前で実装する。

難易度レベル（1が最も簡単、5が原曲どおり）:
  5 : 無加工（原曲どおり）
  4 : 16分グリッドに整え、極端に短い音を削除。和音は最大4音
  3 : 16分グリッド。短い音を削除。和音は最大3音
  2 : 8分グリッド。細かい音を大きく間引く。和音は最大2音
  1 : 8分グリッド。単音のみ（メロディ/ルート音だけ残す）
"""

from dataclasses import dataclass


@dataclass
class SimplifyProfile:
    """難易度レベルごとの簡略化パラメータ"""
    grid_division: int      # 1拍を何分割したグリッドに吸着させるか（4=16分, 2=8分）
    min_duration_sec: float # この長さ未満の音符は削除する（装飾音・ゴーストノート対策）
    max_chord_notes: int    # 同時に鳴らす音の最大数
    merge_repeats: bool     # 同じ高さの音が連続する場合に1音にまとめるか
    label: str


PROFILES = {
    5: SimplifyProfile(8, 0.00, 99, False, "原曲どおり（無加工）"),
    4: SimplifyProfile(4, 0.06, 4, False, "やや簡略（16分グリッド）"),
    3: SimplifyProfile(4, 0.10, 3, False, "標準（16分グリッド・和音3音まで）"),
    2: SimplifyProfile(2, 0.15, 2, True, "かなり簡単（8分グリッド・和音2音まで）"),
    1: SimplifyProfile(2, 0.20, 1, True, "最も簡単（8分グリッド・単音のみ）"),
}


def _quantize(value_sec: float, beat_sec: float, division: int) -> float:
    """秒数をグリッドに吸着させる"""
    step = beat_sec / division
    if step <= 0:
        return value_sec
    return round(value_sec / step) * step


def _pick_chord_notes(notes, max_notes: int, keep: str):
    """
    同時に鳴っている音の中から、残す音を選ぶ。
    keep='low'  → 低い音を優先（ベース向け）
    keep='high' → 高い音を優先（メロディ・ギター向け）
    keep='outer'→ 最低音と最高音を優先（ピアノ・和音向け）
    """
    if len(notes) <= max_notes:
        return notes

    ordered = sorted(notes, key=lambda n: n.pitch)

    if keep == "low":
        return ordered[:max_notes]
    if keep == "high":
        return ordered[-max_notes:]

    # outer: 最低音と最高音から交互に拾う
    picked = []
    lo, hi = 0, len(ordered) - 1
    while len(picked) < max_notes and lo <= hi:
        picked.append(ordered[lo])
        lo += 1
        if len(picked) < max_notes and lo <= hi:
            picked.append(ordered[hi])
            hi -= 1
    return picked


def simplify_midi(pm, level: int, tempo_bpm: float, keep: str = "outer", verbose: bool = True):
    """
    pretty_midi.PrettyMIDI オブジェクトを受け取り、簡略化して返す。

    pm         : PrettyMIDI オブジェクト
    level      : 1〜5 の難易度レベル
    tempo_bpm  : 曲のテンポ（グリッド計算に使用）
    keep       : 和音を削るときにどの音を優先して残すか（low / high / outer）
    """
    if level not in PROFILES:
        raise ValueError(f"難易度レベルは1〜5で指定してください（指定値: {level}）")

    profile = PROFILES[level]
    if level == 5:
        if verbose:
            print("  [簡略化] レベル5のため無加工")
        return pm

    beat_sec = 60.0 / tempo_bpm
    total_before = 0
    total_after = 0

    for inst in pm.instruments:
        notes = list(inst.notes)
        total_before += len(notes)
        if not notes:
            continue

        # --- 1. グリッドに吸着させる ---
        for n in notes:
            start_q = _quantize(n.start, beat_sec, profile.grid_division)
            end_q = _quantize(n.end, beat_sec, profile.grid_division)
            # 吸着の結果、長さがゼロになった音は最小1グリッド分の長さを与える
            min_step = beat_sec / profile.grid_division
            if end_q - start_q < min_step:
                end_q = start_q + min_step
            n.start = max(0.0, start_q)
            n.end = end_q

        # --- 2. 短すぎる音符を削除（装飾音・ゴーストノート対策） ---
        notes = [n for n in notes if (n.end - n.start) >= profile.min_duration_sec]

        # --- 3. 同時発音数を制限（和音を減らす） ---
        grouped = {}
        for n in notes:
            key = round(n.start, 4)
            grouped.setdefault(key, []).append(n)

        reduced = []
        for start_time in sorted(grouped.keys()):
            reduced.extend(
                _pick_chord_notes(grouped[start_time], profile.max_chord_notes, keep)
            )

        # --- 4. 同じ高さの音の連打をまとめる ---
        if profile.merge_repeats:
            reduced.sort(key=lambda n: (n.pitch, n.start))
            merged = []
            for n in reduced:
                if merged and merged[-1].pitch == n.pitch and \
                   abs(merged[-1].end - n.start) < 1e-3:
                    merged[-1].end = n.end
                else:
                    merged.append(n)
            reduced = merged

        reduced.sort(key=lambda n: (n.start, n.pitch))
        inst.notes = reduced
        total_after += len(reduced)

    if verbose:
        removed = total_before - total_after
        rate = (removed / total_before * 100) if total_before else 0
        print(f"  [簡略化] {profile.label}")
        print(f"           音符数 {total_before} → {total_after} "
              f"（{removed}個削減 / {rate:.0f}%減）")

    return pm
