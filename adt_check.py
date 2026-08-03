"""自動ドラム採譜(ADT)が「音楽として正しいか」を検査する。

使い方:
    ./venv/bin/python adt_check.py <ドラム音源のwav> [--tempo 120]

**なぜ必要か**：打点の数（1小節あたり何発か）が妥当に見えても、打点の「位置」が
でたらめなら譜面として使えない。2026-08-02 の検証で、密度だけを見て採用判断した
ADT A1 が、実際には拍と噛み合っていなかったことが判明した。同じ失敗を繰り返さない
ための検査。

判定の考え方:
  ロック/ポップスならスネアは2拍・4拍に集中する。16ステップに均等（＝でたらめ）なら
  2拍4拍の占有率は 12.5%。ここが 12〜15% しかなければ採譜は音楽になっていない。
"""
import argparse
import sys

import numpy as np


def positional_stats(grid: dict, lane: str) -> dict:
    """打点が小節内のどの位置に落ちているかの統計を返す。"""
    spb = grid["steps_per_bar"]
    hist = [0] * spb
    for i, v in enumerate(grid["lanes"].get(lane, [])):
        if v:
            hist[i % spb] += 1
    total = sum(hist) or 1
    on_beat = sum(hist[i] for i in range(0, spb, spb // 4))
    backbeat = hist[spb // 4] + hist[3 * spb // 4]      # 2拍・4拍
    return {
        "total": sum(hist),
        "hist": hist,
        "on_beat_pct": on_beat / total * 100,
        "backbeat_pct": backbeat / total * 100,
        "chance_on_beat_pct": 25.0,                      # 4/16
        "chance_backbeat_pct": 2 / spb * 100,            # 2/16 = 12.5
    }


def separation_quality(drum_wav: str) -> dict:
    """キックとスネアを区別できているかを測る。

    同じ瞬間を両方の成分が主張していれば、それは「音が鳴った」しか分かっておらず
    楽器の判別ができていないということ。
    """
    import librosa
    from app.drum_transcribe import (build_drum_templates, nmf_activations,
                                     _onsets_from_activation)

    y, sr = librosa.load(drum_wav, sr=None, mono=True)
    hop, n_fft = 512, 2048
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    H = nmf_activations(S, build_drum_templates(sr, n_fft))
    kk, _ = _onsets_from_activation(H[0], sr, hop, wait=3)
    sn, _ = _onsets_from_activation(H[1], sr, hop, wait=3)
    raw = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop, units="time")

    sn_arr = np.asarray(sn)
    both = sum(1 for t in kk if len(sn_arr) and np.min(np.abs(sn_arr - t)) < 0.03)
    return {
        "raw_onsets": len(raw),
        "kick_onsets": len(kk),
        "snare_onsets": len(sn),
        "overlap": both,
        "overlap_pct": both / max(len(kk), 1) * 100,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("drum_wav", help="分離済みのドラム音源(wav)")
    ap.add_argument("--tempo", type=float, default=None, help="未指定なら自動検出")
    ap.add_argument("--bars", type=int, default=None)
    args = ap.parse_args()

    import librosa
    from app.drum_transcribe import transcribe_drums
    from app.analyze import count_bars

    tempo = args.tempo
    if tempo is None:
        from bandcopy import detect_tempo
        tempo = detect_tempo(args.drum_wav)
    bars = args.bars or count_bars(
        librosa.get_duration(path=args.drum_wav), tempo)

    print(f"素材: {args.drum_wav}")
    print(f"テンポ {tempo:.1f} / 小節数 {bars}")
    print()

    grid = transcribe_drums(args.drum_wav, tempo, bars)

    print("=" * 62)
    print("① 打点の位置は音楽的か（でたらめなら 拍頭25% / 2拍4拍12.5%）")
    print("=" * 62)
    verdict_pos = True
    for lane, name in (("KK", "キック"), ("SN", "スネア")):
        s = positional_stats(grid, lane)
        mark = ""
        if lane == "SN":
            ok = s["backbeat_pct"] > s["chance_backbeat_pct"] * 2
            verdict_pos = verdict_pos and ok
            mark = "  ← OK" if ok else "  ← 偶然と同じ＝音楽になっていない"
        print(f"  {name}: {s['total']:5d}打点  拍頭 {s['on_beat_pct']:.0f}%  "
              f"2拍4拍 {s['backbeat_pct']:.0f}%{mark}")
    print()

    print("=" * 62)
    print("② どの太鼓かを判別できているか")
    print("=" * 62)
    q = separation_quality(args.drum_wav)
    print(f"  素のオンセット {q['raw_onsets']}個 / "
          f"キック {q['kick_onsets']}個 / スネア {q['snare_onsets']}個")
    print(f"  同じ瞬間を両方が主張: {q['overlap']}個 = キックの {q['overlap_pct']:.0f}%")
    ok_sep = q["overlap_pct"] < 50
    print(f"  → {'判別できている' if ok_sep else '判別できていない（音が鳴ったことしか分かっていない）'}")
    print()

    print("=" * 62)
    if verdict_pos and ok_sep:
        print("判定: 実用に耐える可能性あり。ドラマーに見せてよい。")
        return 0
    print("判定: 譜面として使えない。ドラマーに見せる前に採譜の修正が必要。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
