"""全パートを1枚のスコアに統合して書き出す。
使い方: ./venv/bin/python score_all.py <出力フォルダ> [--level N] [--tempo N]
"""
import argparse
from pathlib import Path

import pretty_midi

from app.score import assemble_full_score, score_to_musicxml
from app.render import musicxml_to_svg
from app.grid import make_template_grid
from app.analyze import count_bars

# 出力フォルダ内のMIDIファイル名（既存パイプラインの日本語ラベル）
LABEL_MAP = {
    "vocals": "ボーカル",
    "other": "ギター・キーボード等",
    "bass": "ベース",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", help="曲の出力フォルダ（例: output/Yvv4RVQzIFk）")
    ap.add_argument("--level", type=int, default=3)
    ap.add_argument("--tempo", type=float, default=None)
    args = ap.parse_args()

    root = Path(args.outdir).resolve()
    midi_dir = root / "midi"
    midi_paths = {}
    for key, label in LABEL_MAP.items():
        p = midi_dir / f"{label}_Lv{args.level}.mid"
        if p.exists():
            midi_paths[key] = str(p)
    if not midi_paths:
        print(f"簡略化MIDIが見つかりません: {midi_dir}")
        return

    # テンポ：未指定ならMIDIの先頭テンポを読む
    tempo = args.tempo
    if tempo is None:
        any_mid = next(iter(midi_paths.values()))
        _, tempi = pretty_midi.PrettyMIDI(any_mid).get_tempo_changes()
        tempo = float(tempi[0]) if len(tempi) else 120.0

    # 小節数：最長MIDIの終端から算出し、ドラムのテンプレを作る
    end = 0.0
    for p in midi_paths.values():
        end = max(end, pretty_midi.PrettyMIDI(p).get_end_time())
    bars = count_bars(end, tempo)
    drum_grid = make_template_grid(tempo, bars)

    sc = assemble_full_score(midi_paths, drum_grid, tempo)
    xml = score_to_musicxml(sc)

    score_dir = root / "score"
    score_dir.mkdir(exist_ok=True)
    xml_path = score_dir / f"全パート_Lv{args.level}.musicxml"
    xml_path.write_text(xml, encoding="utf-8")

    render_dir = root / "_render"
    render_dir.mkdir(exist_ok=True)
    svg_path = render_dir / "full_score.svg"
    svg_path.write_text(musicxml_to_svg(xml), encoding="utf-8")

    print(f"テンポ {tempo:.1f} / {bars}小節 / 段数 {len(sc.parts)}")
    print(f"MusicXML: {xml_path}")
    print(f"SVG     : {svg_path}")


if __name__ == "__main__":
    main()
