"""全パートを1枚のスコアに統合して書き出す。
使い方: ./venv/bin/python score_all.py <出力フォルダ> [--level N] [--tempo N]
"""
import argparse
import json
from pathlib import Path

import pretty_midi

from app.score import assemble_full_score, score_to_musicxml
from app.render import musicxml_to_svg, musicxml_to_pdf
from app.grid import make_template_grid, fit_grid_to_bars
from app.analyze import count_bars
from app.parts import specs, spec_map


def resolve_drum_grid(root, tempo: float, bars: int, override: str = None):
    """ドラム段に使うグリッドを決める。

    エディタで保存した <root>/drum_grid.json（または override）があれば、それを
    スコアの小節数に合わせて使う。無ければ従来のテンプレート（基本8ビート）。
    """
    path = Path(override) if override else Path(root) / "drum_grid.json"
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        return fit_grid_to_bars(saved, bars)
    return make_template_grid(tempo, bars)


def resolve_parts(midi_dir, level: int):
    """MIDIフォルダを見て (key→MIDIパス, 6分離か) を返す。

    6分離のギター(「ギター」ラベル)のMIDIがあれば6分離と判定し、その段構成で
    存在するMIDIだけ集める。無ければ4分離の段構成で集める。
    """
    midi_dir = Path(midi_dir)

    def _collect(six: bool) -> dict:
        found = {}
        for s in specs(six):
            if not s.transcribe:
                continue
            p = midi_dir / f"{s.label}_Lv{level}.mid"
            if p.exists():
                found[s.key] = str(p)
        return found

    six = (midi_dir / f"{spec_map(True)['guitar'].label}_Lv{level}.mid").exists()
    return _collect(six), six


def build_full_score_musicxml(root, level, tempo=None, audio=None,
                              drum_grid_override=None):
    """出力フォルダから全パート統合スコアの MusicXML を組み立てて返す。

    CLI(main) と Web アプリ(app/webapp.py) の共通処理。戻り値は
    (xml, six, bars, tempo, part_count)。MIDIが無ければ xml=None。
    """
    root = Path(root)
    midi_dir = root / "midi"
    midi_paths, six = resolve_parts(midi_dir, level)
    if not midi_paths:
        return None, six, 0, tempo, 0

    if tempo is None:
        any_mid = next(iter(midi_paths.values()))
        _, tempi = pretty_midi.PrettyMIDI(any_mid).get_tempo_changes()
        tempo = float(tempi[0]) if len(tempi) else 120.0

    end = 0.0
    for p in midi_paths.values():
        end = max(end, pretty_midi.PrettyMIDI(p).get_end_time())
    bars = count_bars(end, tempo)
    drum_grid = resolve_drum_grid(root, tempo, bars, override=drum_grid_override)

    chords = None
    if audio:
        from bandcopy import detect_chords
        chords = detect_chords(Path(audio).expanduser().resolve(), tempo)

    sc = assemble_full_score(midi_paths, drum_grid, tempo, chords=chords, six=six)
    return score_to_musicxml(sc), six, bars, tempo, len(sc.parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", help="曲の出力フォルダ（例: output/Yvv4RVQzIFk）")
    ap.add_argument("--level", type=int, default=3)
    ap.add_argument("--tempo", type=float, default=None)
    ap.add_argument("--audio", default=None,
                    help="原曲の音源。指定するとコードを検出しボーカル段に載せる")
    ap.add_argument("--pdf", action="store_true",
                    help="印刷・共有用にPDFも書き出す")
    ap.add_argument("--drum-grid", default=None,
                    help="ドラム段に使うグリッドJSON。省略時は <出力フォルダ>/drum_grid.json "
                         "があればそれ、無ければテンプレート")
    args = ap.parse_args()

    root = Path(args.outdir).resolve()
    xml, six, bars, tempo, n_parts = build_full_score_musicxml(
        root, args.level, tempo=args.tempo, audio=args.audio,
        drum_grid_override=args.drum_grid)
    if xml is None:
        print(f"簡略化MIDIが見つかりません: {root / 'midi'}")
        return

    score_dir = root / "score"
    score_dir.mkdir(exist_ok=True)
    xml_path = score_dir / f"全パート_Lv{args.level}.musicxml"
    xml_path.write_text(xml, encoding="utf-8")

    render_dir = root / "_render"
    render_dir.mkdir(exist_ok=True)
    svg_path = render_dir / "full_score.svg"
    svg_path.write_text(musicxml_to_svg(xml), encoding="utf-8")

    grid_json = Path(args.drum_grid) if args.drum_grid else root / "drum_grid.json"
    drum_src = "編集グリッド" if grid_json.exists() else "テンプレート"
    mode = "6分離" if six else "4分離"
    print(f"テンポ {tempo:.1f} / {bars}小節 / 段数 {n_parts}（{mode}・ドラム:{drum_src}）")
    print(f"MusicXML: {xml_path}")
    print(f"SVG     : {svg_path}")

    if args.pdf:
        pdf_path = score_dir / f"全パート_Lv{args.level}.pdf"
        pdf_path.write_bytes(musicxml_to_pdf(xml))
        print(f"PDF     : {pdf_path}")


if __name__ == "__main__":
    main()
