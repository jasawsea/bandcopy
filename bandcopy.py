#!/usr/bin/env python3
"""
bandcopy.py
-----------
曲のMP3を1本渡すと、以下を自動で行うツール。

  1. Demucs でパート分離（ドラム / ベース / ギター等 / ボーカル）
  2. Basic Pitch で各パートを採譜（MIDI化）
  3. 指定した難易度に簡略化
  4. MusicXML（楽譜ファイル）として書き出し

使い方:
    python bandcopy.py 曲.mp3
    python bandcopy.py 曲.mp3 --level 2
    python bandcopy.py 曲.mp3 --level 2 --parts bass other
    python bandcopy.py 曲.mp3 --level 3 --tempo 128

出力先:
    output/曲名/
        ├── stems/          分離した音源（練習用に単体で聴ける）
        ├── midi/           採譜したMIDI（原曲どおり / 簡略化後）
        └── score/          楽譜ファイル（MusicXML・MuseScoreで開ける）
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from simplify import PROFILES, simplify_midi
from app.parts import spec_map, specs, model_name, chord_part_key

# パート定義（ラベル/音部記号/楽器名/和音削減/採譜可否/モデル）は app/parts.py に集約。
# 4分離(htdemucs) と 6分離(htdemucs_6s=ギター・鍵盤を別段) の2モードを持つ。


def demucs_cmd(audio_path: Path, work_dir: Path, six: bool) -> list:
    """Demucs 実行コマンドを組み立てる（six で 4分離/6分離モデルを切替）。"""
    return [
        sys.executable, "-m", "demucs",
        "-n", model_name(six),
        "-o", str(work_dir),
        str(audio_path),
    ]


def default_parts(six: bool) -> list:
    """採譜する段（ドラム除く）の既定リスト。段の上→下順。"""
    return [s.key for s in specs(six) if s.transcribe]


# コードの語彙。基本の三和音を優先し、7th と sus4 まで。テンションは扱わない
# （採譜の誤差で複雑なコードが乱発するのを避け、実際に弾ける範囲に丸める）。
CHORD_TRIADS = {"": [0, 4, 7], "m": [0, 3, 7], "sus4": [0, 5, 7]}
CHORD_SEVEN = {"7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10]}
CHORD_NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# 7th を採用する最低優位差。三和音より明確に良いときだけ7thにする
CHORD_SEVEN_MARGIN = 0.04


def check_dependencies():
    """必要なライブラリが入っているか事前に確認する"""
    missing = []
    for module, package in [
        ("demucs", "demucs"),
        ("basic_pitch", "basic-pitch"),
        ("pretty_midi", "pretty_midi"),
        ("music21", "music21"),
        ("librosa", "librosa"),
    ]:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("必要なライブラリが不足しています。以下を実行してください:\n")
        print(f"    pip install {' '.join(missing)}\n")
        sys.exit(1)


def detect_tempo(audio_path: Path) -> float:
    """原曲からテンポ（BPM）を自動検出する"""
    import librosa
    print("[0/4] テンポを解析中...")
    y, sr = librosa.load(str(audio_path), mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(tempo) if not hasattr(tempo, "__len__") else float(tempo[0])
    # テンポ検出に失敗すると 0 が返ることがある。後段のグリッド計算で
    # ゼロ除算になるため、その場合は 120 BPM を仮定する（--tempo で上書き可）。
    if bpm <= 0:
        print("      ! テンポを自動検出できませんでした。120 BPM を仮定します"
              "（正しくない場合は --tempo で手動指定してください）")
        bpm = 120.0
    else:
        print(f"      推定テンポ: {bpm:.1f} BPM")
    return bpm


def detect_chords(audio_path: Path, tempo_bpm: float) -> list:
    """原曲の響き（chroma）から小節ごとのコードネームを推定する。

    採譜したMIDIの音を拾うのではなく音響から直接判定するのは、Basic Pitch の
    採譜が臨時記号だらけで、そのまま和音判定すると誰も弾けない複雑なコードが
    乱発するため。基本の三和音を優先し、7th が明確なときだけ7thにする。
    戻り値は小節順のコード表記リスト（例: ["", "Em", "G7", ...]）。None は無音。
    """
    import numpy as np
    import librosa

    print("[0/4] コードを解析中...")

    def _unit(pcs, root):
        v = np.zeros(12)
        for p in pcs:
            v[(p + root) % 12] = 1.0
        return v / np.linalg.norm(v)

    triads = [(s, r, _unit(p, r)) for s, p in CHORD_TRIADS.items() for r in range(12)]
    sevens = [(s, r, _unit(p, r)) for s, p in CHORD_SEVEN.items() for r in range(12)]

    y, sr = librosa.load(str(audio_path), mono=True)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    dur = librosa.get_duration(y=y, sr=sr)
    bar_sec = 4 * 60.0 / tempo_bpm  # 4/4・1小節の秒数
    n_bars = int(np.ceil(dur / bar_sec))
    times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr)

    prog = []
    for b in range(n_bars):
        mask = (times >= b * bar_sec) & (times < (b + 1) * bar_sec)
        if mask.sum() == 0:
            prog.append(None)
            continue
        prof = chroma[:, mask].mean(axis=1)
        if prof.max() < 1e-6:
            prog.append(None)
            continue
        prof = prof / np.linalg.norm(prof)
        bt = max(triads, key=lambda c: float(prof @ c[2]))
        bs = max(sevens, key=lambda c: float(prof @ c[2]))
        st, ss = float(prof @ bt[2]), float(prof @ bs[2])
        suf, root = (bs[0], bs[1]) if ss > st + CHORD_SEVEN_MARGIN else (bt[0], bt[1])
        prog.append(f"{CHORD_NOTE[root]}{suf}")
    print(f"      推定コード: {' | '.join(p or 'N.C.' for p in prog)}")
    return prog


def separate_stems(audio_path: Path, work_dir: Path, six: bool = False) -> dict:
    """Demucs を呼び出してパート分離する（six で 4分離/6分離を切替）"""
    print("[1/4] パート分離中（初回はモデルのダウンロードで数分かかります）...")

    result = subprocess.run(
        demucs_cmd(audio_path, work_dir, six), capture_output=True, text=True)
    if result.returncode != 0:
        print("パート分離に失敗しました:")
        print(result.stderr[-2000:])
        sys.exit(1)

    stem_dir = work_dir / model_name(six) / audio_path.stem
    labels = spec_map(six)
    stems = {}
    for part in labels:
        wav = stem_dir / f"{part}.wav"
        if wav.exists():
            stems[part] = wav
            print(f"      ✓ {labels[part].label}")
    return stems


def transcribe(wav_path: Path, part: str):
    """Basic Pitch で音源を MIDI に変換する"""
    # scipy 1.13 以降で削除された scipy.signal.gaussian を basic-pitch が
    # 内部で参照するため、windows.gaussian へのエイリアスとして復元する。
    import scipy.signal
    if not hasattr(scipy.signal, "gaussian"):
        from scipy.signal.windows import gaussian as _gaussian
        scipy.signal.gaussian = _gaussian

    from basic_pitch.inference import predict
    from basic_pitch import build_icassp_2022_model_path, FilenameSuffix

    # TensorFlow 2.16 以降は内部が Keras 3 になり、basic-pitch 同梱の
    # TF版モデル（Keras 2 形式）が読めない。OS非依存で安定して動く
    # ONNX 版モデルを明示的に指定する（onnxruntime が必要）。
    model_path = build_icassp_2022_model_path(FilenameSuffix.onnx)

    # onset_threshold: 音の立ち上がりの検出感度（高いほど拾う音が減る）
    # frame_threshold: 短い音を切り捨てる閾値
    _, midi_data, _ = predict(
        str(wav_path),
        model_path,
        onset_threshold=0.5,
        frame_threshold=0.3,
        minimum_note_length=80,  # ミリ秒。短すぎるノイズを最初から除外
    )
    return midi_data


def write_midi_with_tempo(pm, path: Path, tempo_bpm: float):
    """検出したテンポと拍子(4/4)を埋め込んで MIDI を書き出す。

    Basic Pitch が返す MIDI は既定120BPMのため、簡略化で使ったテンポと
    食い違い、music21 での楽譜化時にリズム表記が崩れる（音価がおかしくなる）。
    テンポを一致させると、グリッドに沿った素直な音価で書き出せる。
    """
    import pretty_midi
    out = pretty_midi.PrettyMIDI(initial_tempo=float(tempo_bpm), resolution=pm.resolution)
    out.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0.0))
    out.instruments = pm.instruments
    out.write(str(path))


def midi_to_musicxml(midi_path: Path, xml_path: Path,
                     clef_type: str = "treble", instrument_name: str = "",
                     chords: list = None) -> bool:
    """MIDI を MusicXML（楽譜ファイル）に変換する。

    パートに応じた音部記号と楽器名を設定する。既定のままだと全パートが
    「Electric Piano」になり、音部記号もピッチ任せで不適切になるため。
    clef_type: treble / bass / treble8vb / bass8vb のいずれか。
    8vb はギター・ベースの慣習に合わせたオクターブ移調記号付き音部記号。
    chords: 小節順のコード表記リスト（伴奏パートのみ。None なら付けない）。
    """
    try:
        from music21 import converter
        from music21 import clef as m21clef
        score = converter.parse(str(midi_path))
        clef_map = {
            "bass": m21clef.BassClef,
            "bass8vb": m21clef.Bass8vbClef,
            "treble8vb": m21clef.Treble8vbClef,
            "treble": m21clef.TrebleClef,
        }
        chosen = clef_map.get(clef_type, m21clef.TrebleClef)()
        for p in score.parts:
            # 既存の音部記号を除去し、正しいものを先頭に差し込む
            for c in list(p.recurse().getElementsByClass(m21clef.Clef)):
                c.activeSite.remove(c)
            target = p.recurse().getElementsByClass("Measure").first() or p
            target.insert(0, chosen)
            if instrument_name:
                p.partName = instrument_name
                p.partAbbreviation = instrument_name

        # コードネームを小節先頭に載せる（伴奏パートのみ）
        if chords:
            from music21 import harmony
            part = score.parts[0]
            measures = list(part.recurse().getElementsByClass("Measure"))
            for i, fig in enumerate(chords):
                if fig is None or i >= len(measures):
                    continue
                try:
                    measures[i].insert(0.0, harmony.ChordSymbol(fig))
                except Exception:
                    pass  # 解釈できない表記は黙ってスキップ

        score.write("musicxml", fp=str(xml_path))
        return True
    except Exception as e:
        print(f"      ! 楽譜変換に失敗: {e}")
        return False


def transcribe_drums_to_outputs(drum_wav, out_root, midi_dir, tempo):
    """ドラム音源を自動採譜し、グリッドJSONとドラムMIDIを書き出す。

    **なぜパイプラインに入れるか**：以前はエディタを開かないとドラム譜が
    作られず、バンド譜の最下段がテンプレートの8ビートで代用されていた。
    譜面が主役の道具で4段のうち1段だけ自動で埋まらないのは片手落ちなので、
    音源を投げた時点でここまで出す（2026-08-08）。

    エディタはこの下書きを「叩ける形に削る」道具として後段に残る。
    戻り値は (グリッドJSONのパス, MIDIのパス)。失敗時は (None, None)。
    """
    import librosa
    from app.analyze import count_bars
    from app.drum_transcribe import transcribe_drums
    from app.grid import grid_to_midi

    try:
        dur = librosa.get_duration(path=str(drum_wav))
        bars = count_bars(dur, tempo)
        grid = transcribe_drums(str(drum_wav), tempo, bars)
    except Exception as e:
        # ドラムが採れなくても他パートの成果は返したいので、ここで握って続行する
        print(f"      ! ドラムの自動下書きに失敗（他パートは続行）: {e}")
        return None, None

    grid_path = Path(out_root) / "drum_grid.json"
    grid_path.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")

    midi_path = Path(midi_dir) / "ドラム.mid"
    midi_path.write_bytes(grid_to_midi(grid))

    hits = {k: sum(v) for k, v in grid["lanes"].items() if sum(v)}
    print(f"      ✓ ドラム下書き: {bars}小節 / "
          + " ".join(f"{k}{n}" for k, n in hits.items()))
    return grid_path, midi_path


def run_pipeline(audio_path, out_root, level=3, six=False, parts=None,
                 tempo=None, keep_stems=True, no_chords=False, no_drums=False):
    """分離→採譜→簡略化→楽譜(MIDI/MusicXML) を実行し、出力パス一式を返す。

    CLI(main) と Web アプリ(app/webapp.py) の共通処理。out_root はこの曲の
    出力フォルダ（例 output/<曲名> や一時フォルダ）。戻り値は各出力の場所。
    """
    audio_path = Path(audio_path).expanduser().resolve()
    out_root = Path(out_root)
    spec = spec_map(six)
    if parts is None:
        parts = default_parts(six)

    work_dir = out_root / "_work"
    stems_dir = out_root / "stems"
    midi_dir = out_root / "midi"
    score_dir = out_root / "score"
    for d in (work_dir, stems_dir, midi_dir, score_dir):
        d.mkdir(parents=True, exist_ok=True)

    print("=" * 56)
    print(f"  対象曲   : {audio_path.name}")
    print(f"  難易度   : レベル{level}（{PROFILES[level].label}）")
    print(f"  分離     : {'6分離（ギター/鍵盤を別段）' if six else '4分離'}")
    print(f"  採譜対象 : {', '.join(spec[p].label for p in parts)}")
    print("=" * 56)

    # --- テンポ検出 ---
    if not tempo:
        tempo = detect_tempo(audio_path)

    # --- コード検出（伴奏パートを採譜する場合のみ）---
    chord_key = chord_part_key(six)
    chords = None
    if not no_chords and chord_key in parts:
        chords = detect_chords(audio_path, tempo)
        # フォルダに保存しておく。以後 score_all/tab.py は元音源が無くても
        # コードを載せられる（出力フォルダを改名しても消えない）
        from score_all import save_chords
        out_root.mkdir(parents=True, exist_ok=True)
        save_chords(out_root, tempo, chords, source=audio_path)

    # --- パート分離 ---
    stems = separate_stems(audio_path, work_dir, six)

    # 分離音源を練習用にコピー（ドラムは常に残す：耳コピの参考になるため）
    for part, wav in stems.items():
        if keep_stems or not spec[part].transcribe or part in parts:
            shutil.copy(wav, stems_dir / f"{spec[part].label}.wav")

    result = {
        "out_root": out_root, "stems_dir": stems_dir, "midi_dir": midi_dir,
        "score_dir": score_dir, "tempo": tempo, "level": level, "six": six,
        "parts": [], "drum_grid": None, "drum_midi": None,
    }

    # --- ドラムの自動下書き（グリッドJSON＋MIDI）---
    if not no_drums and "drums" in stems:
        print("[2/4] ドラムを自動採譜中...")
        g, m = transcribe_drums_to_outputs(
            stems["drums"], out_root, midi_dir, tempo)
        result["drum_grid"], result["drum_midi"] = g, m

    # --- 採譜 + 簡略化 + 楽譜化 ---
    import pretty_midi  # noqa: F401  （basic_pitch 経由で使用）

    targets = [p for p in parts if spec[p].transcribe and p in stems]
    if not targets:
        print("\n採譜できるパートがありませんでした。")
        return result

    print(f"[2/4] 採譜中（{len(targets)}パート）...")
    results = {}
    for part in targets:
        print(f"      → {spec[part].label} を採譜中...")
        try:
            results[part] = transcribe(stems[part], part)
        except Exception as e:
            print(f"      ! {spec[part].label} の採譜に失敗: {e}")

    print(f"[3/4] 難易度レベル{level}に簡略化中...")
    for part, pm in results.items():
        print(f"      → {spec[part].label}")
        raw_path = midi_dir / f"{spec[part].label}_原曲どおり.mid"
        write_midi_with_tempo(pm, raw_path, tempo)
        simplify_midi(pm, level, tempo, keep=spec[part].keep,
                      max_notes=spec[part].max_chord_notes)
        simple_path = midi_dir / f"{spec[part].label}_Lv{level}.mid"
        write_midi_with_tempo(pm, simple_path, tempo)

    print("[4/4] 楽譜（MusicXML）に変換中...")
    for part in results:
        mid = midi_dir / f"{spec[part].label}_Lv{level}.mid"
        xml = score_dir / f"{spec[part].label}_Lv{level}.musicxml"
        part_chords = chords if part == chord_key else None
        if midi_to_musicxml(mid, xml, spec[part].clef, spec[part].name, part_chords):
            print(f"      ✓ {xml.name}")

    shutil.rmtree(work_dir, ignore_errors=True)  # 中間ファイルを削除
    result["parts"] = list(results.keys())
    return result


def main():
    parser = argparse.ArgumentParser(
        description="曲を分離・採譜し、演奏しやすい難易度の楽譜にするツール"
    )
    parser.add_argument("audio", help="入力する音源ファイル（MP3 / WAV / M4A）")
    parser.add_argument(
        "--level", type=int, default=3, choices=[1, 2, 3, 4, 5],
        help="難易度（1=最も簡単, 5=原曲どおり）。既定は3"
    )
    parser.add_argument(
        "--six", action="store_true",
        help="ギターと鍵盤を別段に分ける（htdemucs_6s＝6分離）。"
             "無指定は従来の4分離（ギター・鍵盤は1段）"
    )
    _all_keys = sorted(set(spec_map(False)) | set(spec_map(True)))
    parser.add_argument(
        "--parts", nargs="+", default=None, choices=_all_keys,
        help="採譜するパート。省略時はモードの既定"
             "（4分離: vocals other bass ／ 6分離: vocals guitar piano other bass）"
    )
    parser.add_argument(
        "--tempo", type=float, default=None,
        help="テンポ（BPM）を手動指定。省略時は自動検出"
    )
    parser.add_argument(
        "--outdir", default="output", help="出力先フォルダ。既定は output"
    )
    parser.add_argument(
        "--keep-stems", action="store_true",
        help="分離した音源を残す（練習用に単体で聴きたい場合）"
    )
    parser.add_argument(
        "--no-chords", action="store_true",
        help="コードネームを楽譜に付けない"
    )
    parser.add_argument(
        "--no-drums", action="store_true",
        help="ドラムの自動下書き（drum_grid.json / ドラム.mid）を作らない"
    )
    args = parser.parse_args()

    check_dependencies()

    audio_path = Path(args.audio).expanduser().resolve()
    if not audio_path.exists():
        print(f"ファイルが見つかりません: {audio_path}")
        sys.exit(1)

    out_root = Path(args.outdir).resolve() / audio_path.stem
    result = run_pipeline(
        audio_path, out_root, level=args.level, six=args.six,
        parts=args.parts, tempo=args.tempo,
        keep_stems=args.keep_stems, no_chords=args.no_chords,
        no_drums=args.no_drums,
    )

    print("\n" + "=" * 56)
    print("完了しました。")
    print(f"  分離音源 : {result['stems_dir']}")
    print(f"  MIDI     : {result['midi_dir']}")
    print(f"  楽譜     : {result['score_dir']}")
    print("\n楽譜ファイル（.musicxml）は MuseScore で開けます。")
    print("難易度が合わない場合は --level の数字を変えて再実行してください。")
    print("=" * 56)


if __name__ == "__main__":
    main()
