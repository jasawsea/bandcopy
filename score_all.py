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


AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg")


def find_source_audio(root):
    """出力フォルダ名から元音源を探す（`audio/<フォルダ名>.<拡張子>`）。

    **なぜ自動で探すか**：コード検出は `--audio` を渡したときだけ動く作りだった。
    渡し忘れると *警告も出ずに* コード記号ゼロのバンド譜が出る。バンド譜はコードが
    要のパートなので、忘れられる作りのままにしない（2026-08-08）。
    見つからなければ None（呼び出し側が明示的に知らせる）。
    """
    root = Path(root)
    candidates = [Path.cwd() / "audio", root.parent.parent / "audio", root]
    for base in candidates:
        for ext in AUDIO_EXTS:
            p = base / f"{root.name}{ext}"
            if p.exists():
                return str(p)
    return None


CHORDS_CACHE = "chords.json"


def load_cached_chords(root, tempo, tol=0.5):
    """フォルダに保存済みのコード進行を読む。無い/テンポが違うなら None。

    **なぜ保存するか**：以前は元音源を「出力フォルダ名と同じ名前のmp3」という
    慣習で探していた。そのため**フォルダを改名するとコードが消えた**。
    検出結果をフォルダ内に持たせれば、改名しても元音源を消しても残る（2026-08-08）。
    ついでに、検出は重い解析なので2回目以降が一瞬になる。
    """
    path = Path(root) / CHORDS_CACHE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None                       # 壊れていたら無視して取り直す
    # コードは小節単位なのでテンポが変わると位置がずれる。違えば使わない
    if abs(float(data.get("tempo", 0)) - float(tempo)) > tol:
        return None
    chords = data.get("chords")
    return chords if isinstance(chords, list) and chords else None


def save_chords(root, tempo, chords, source=None):
    """検出したコード進行をフォルダに保存する（改名・音源削除に耐えるため）。"""
    if not chords:
        return None
    path = Path(root) / CHORDS_CACHE
    path.write_text(json.dumps(
        {"tempo": tempo, "source": str(source) if source else None,
         "chords": chords}, ensure_ascii=False), encoding="utf-8")
    return path


def resolve_chords(root, tempo, audio=None, no_chords=False):
    """その曲のコード進行（小節順のリスト）を返す。載せないときは None。

    バンド譜とタブ譜の両方が使うので、ここを単一の入口にしている
    （別々に検出すると同じ解析を2回走らせることになる）。

    探す順番：
      ① --audio で明示された音源（指定されたら必ずそれを使い、結果を保存する）
      ② フォルダに保存済みの chords.json（**改名しても効く**・一瞬）
      ③ フォルダ名から推測した元音源（従来の慣習。古い出力フォルダ向け）
      ④ どれも無ければ、黙らず理由を伝えて None
    """
    if no_chords:
        return None
    from bandcopy import detect_chords

    if audio:                                        # ①
        chords = detect_chords(Path(audio).expanduser().resolve(), tempo)
        save_chords(root, tempo, chords, source=audio)
        return chords

    cached = load_cached_chords(root, tempo)         # ②
    if cached:
        return cached

    src = find_source_audio(root)                    # ③
    if src:
        chords = detect_chords(Path(src).expanduser().resolve(), tempo)
        save_chords(root, tempo, chords, source=src)
        return chords

    # ④ 黙ってコード無しにしない。何が起きたかを必ず伝える
    print("      ※ 元音源が見つからずコード記号を載せていません。"
          f"（{Path(root).name}.mp3 等を audio/ に置くか --audio で指定）")
    return None


def build_full_score_musicxml(root, level, tempo=None, audio=None,
                              drum_grid_override=None, no_chords=False,
                              chords=None):
    """出力フォルダから全パート統合スコアの MusicXML を組み立てて返す。

    CLI(main) と Web アプリ(app/webapp.py) の共通処理。戻り値は
    (xml, six, bars, tempo, part_count, chords)。MIDIが無ければ xml=None。

    audio 未指定でも元音源を自動で探してコードを載せる（no_chords=True で抑止）。
    **chords も返す**のは、タブ譜が同じコードを使い回せるようにするため
    （別々に検出すると重い解析が2回走る）。
    """
    root = Path(root)
    midi_dir = root / "midi"
    midi_paths, six = resolve_parts(midi_dir, level)
    if not midi_paths:
        return None, six, 0, tempo, 0, None

    if tempo is None:
        any_mid = next(iter(midi_paths.values()))
        _, tempi = pretty_midi.PrettyMIDI(any_mid).get_tempo_changes()
        tempo = float(tempi[0]) if len(tempi) else 120.0

    end = 0.0
    for p in midi_paths.values():
        end = max(end, pretty_midi.PrettyMIDI(p).get_end_time())
    bars = count_bars(end, tempo)
    drum_grid = resolve_drum_grid(root, tempo, bars, override=drum_grid_override)

    if chords is None:                      # 呼び出し側が検出済みなら使い回す
        chords = resolve_chords(root, tempo, audio=audio, no_chords=no_chords)

    sc = assemble_full_score(midi_paths, drum_grid, tempo, chords=chords, six=six)
    return score_to_musicxml(sc), six, bars, tempo, len(sc.parts), chords


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", help="曲の出力フォルダ（例: output/Yvv4RVQzIFk）")
    ap.add_argument("--level", type=int, default=3)
    ap.add_argument("--tempo", type=float, default=None)
    ap.add_argument("--audio", default=None,
                    help="原曲の音源。省略時は audio/<出力フォルダ名>.mp3 等を自動で探す")
    ap.add_argument("--no-chords", action="store_true",
                    help="コード検出を行わない（速く出したいとき）")
    ap.add_argument("--pdf", action="store_true",
                    help="印刷・共有用にPDFも書き出す")
    ap.add_argument("--drum-grid", default=None,
                    help="ドラム段に使うグリッドJSON。省略時は <出力フォルダ>/drum_grid.json "
                         "があればそれ、無ければテンプレート")
    args = ap.parse_args()

    root = Path(args.outdir).resolve()
    xml, six, bars, tempo, n_parts, _chords = build_full_score_musicxml(
        root, args.level, tempo=args.tempo, audio=args.audio,
        drum_grid_override=args.drum_grid, no_chords=args.no_chords)
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
