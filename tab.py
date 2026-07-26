"""ギター・ベースのタブ譜を書き出す。
使い方: ./venv/bin/python tab.py <出力フォルダ> [--level N] [--pdf]

フォルダ内の簡略化MIDI（ベース／ギター）を見つけ、それぞれ弦・フレットを
自動割当してタブ譜（MusicXML＋SVG、--pdfでPDFも）を出力する。
"""
import argparse
from pathlib import Path

from app.tab import midi_to_tab_musicxml
from app.render import musicxml_to_svg, musicxml_to_pdf

# ラベル → 楽器。ギターは6分離「ギター」を優先し、無ければ4分離の混在ラベル。
_BASS_LABEL = "ベース"
_GUITAR_LABELS = ["ギター", "ギター・キーボード等"]


def resolve_tab_targets(midi_dir, level: int):
    """(MIDIパス, 楽器, ラベル) のリストを返す。ベースとギターを1つずつ。"""
    midi_dir = Path(midi_dir)
    targets = []

    bass = midi_dir / f"{_BASS_LABEL}_Lv{level}.mid"
    if bass.exists():
        targets.append((str(bass), "bass", _BASS_LABEL))

    for label in _GUITAR_LABELS:  # 先頭（6分離ギター）を優先
        p = midi_dir / f"{label}_Lv{level}.mid"
        if p.exists():
            targets.append((str(p), "guitar", label))
            break

    return targets


def main():
    ap = argparse.ArgumentParser(description="ギター・ベースのタブ譜を書き出す")
    ap.add_argument("outdir", help="曲の出力フォルダ（例: output/Yvv4RVQzIFk）")
    ap.add_argument("--level", type=int, default=3)
    ap.add_argument("--pdf", action="store_true", help="PDFも書き出す")
    args = ap.parse_args()

    root = Path(args.outdir).resolve()
    targets = resolve_tab_targets(root / "midi", args.level)
    if not targets:
        print(f"タブ化できるMIDI（ベース／ギター）が見つかりません: {root / 'midi'}")
        return

    tab_dir = root / "tab"
    render_dir = root / "_render"
    tab_dir.mkdir(exist_ok=True)
    render_dir.mkdir(exist_ok=True)

    for midi_path, instrument, label in targets:
        xml = midi_to_tab_musicxml(midi_path, instrument)
        xml_path = tab_dir / f"{label}_tab_Lv{args.level}.musicxml"
        xml_path.write_text(xml, encoding="utf-8")
        svg_path = render_dir / f"{label}_tab.svg"
        svg_path.write_text(musicxml_to_svg(xml), encoding="utf-8")
        print(f"✓ {instrument}: {xml_path.name} / {svg_path.name}")
        if args.pdf:
            pdf_path = tab_dir / f"{label}_tab_Lv{args.level}.pdf"
            pdf_path.write_bytes(musicxml_to_pdf(xml))
            print(f"  PDF: {pdf_path.name}")


if __name__ == "__main__":
    main()
