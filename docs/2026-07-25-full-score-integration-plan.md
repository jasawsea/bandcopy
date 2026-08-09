# 全パートScore統合 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 各パート（ボーカル・ギター/鍵盤・ベース・ドラム）を1枚の普通のスコア譜に統合し、MusicXML＋SVGで出力する。

**Architecture:** music21 で各パートを Part（段）にし、上から ボーカル→ギター→ベース→ドラム の順に積む。音程パートは既存の簡略化MIDIから、ドラムは既存の grid から Part を作る。描画は既存の verovio 経由。

**Tech Stack:** Python 3.12, music21, pretty_midi（テスト用MIDI生成）, verovio, pytest（すべてvenv導入済み。新規依存なし）。

## Global Constraints

- 作業ディレクトリ：`/Users/shigiharayasushi/Documents/Yasushi/40_遊ぶ/43_bandcopy/`。パスはここからの相対。実行は `./venv/bin/python`。
- gitブランチは `master`（このフォルダで初期化済み）。各タスク末尾でコミット。
- 段の並び順（上→下）：**ボーカル → ギター/鍵盤 → ベース → ドラム**。
- 段ごとの音部記号・楽器名：ボーカル=treble/"Vocal"、ギター=treble8vb/"Guitar"、ベース=bass8vb/"Bass"、ドラム=percussion/"Drums"（既存 `bandcopy.CLEF_STRATEGY` と一致）。
- コードはボーカル段（最上段）の各小節先頭に `harmony.ChordSymbol` で載せる（コード列が渡された時のみ）。
- テストは pytest。外部の `output/` は .gitignore 対象なので依存しない。テスト用MIDIは pretty_midi でその場生成する。
- 4/4固定。テンポは各パートの簡略化MIDIに埋め込み済みのものを使う（CLIは未指定時にMIDIから読む）。

---

## ファイル構成

```
bandcopy/
  app/
    score.py         # 段の生成・統合（build_full_score 他）
  score_all.py       # CLIエントリ（出力フォルダから統合スコアを書き出す）
  tests/
    test_score.py    # score.py の単体テスト（pretty_midiで生成した素材を使用）
```

責務：`app/score.py`＝統合ロジック（純粋関数・テスト容易）、`score_all.py`＝既存出力からの配線のみ。

---

### Task 1: 簡略化MIDIから段（Part）を作る

**Files:**
- Create: `app/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `pitched_part_from_midi(midi_path: str, clef_type: str, name: str) -> music21.stream.Part`
    音部記号（treble/treble8vb/bass/bass8vb）と楽器名を設定した Part を返す。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_score.py`:
```python
import pretty_midi


def _tiny_midi(tmp_path, name="t.mid"):
    """テスト用に2音だけの小さなMIDIを生成してパスを返す。"""
    pm = pretty_midi.PrettyMIDI(initial_tempo=100.0)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=48, start=0.0, end=0.5))
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=50, start=0.5, end=1.0))
    pm.instruments.append(inst)
    p = tmp_path / name
    pm.write(str(p))
    return str(p)


def test_pitched_part_from_midi_sets_clef_and_name(tmp_path):
    from app.score import pitched_part_from_midi
    from music21 import clef
    part = pitched_part_from_midi(_tiny_midi(tmp_path), "bass8vb", "Bass")
    assert part.partName == "Bass"
    clefs = list(part.recurse().getElementsByClass(clef.Clef))
    assert any(isinstance(c, clef.Bass8vbClef) for c in clefs)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_score.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.score'`）

- [ ] **Step 3: 最小実装を書く**

`app/score.py`:
```python
"""全パートを1枚のスコア譜に統合する。"""

# 段（上→下）の (キー, 音部記号タイプ, 楽器名)。ドラムは別途 grid から積む。
PITCHED_ORDER = [
    ("vocals", "treble", "Vocal"),
    ("other", "treble8vb", "Guitar"),
    ("bass", "bass8vb", "Bass"),
]


def _clef_for(clef_type: str):
    from music21 import clef as m21clef
    return {
        "treble": m21clef.TrebleClef,
        "treble8vb": m21clef.Treble8vbClef,
        "bass": m21clef.BassClef,
        "bass8vb": m21clef.Bass8vbClef,
    }.get(clef_type, m21clef.TrebleClef)()


def pitched_part_from_midi(midi_path: str, clef_type: str, name: str):
    """簡略化MIDIを読み、音部記号・楽器名を設定した Part を返す。"""
    from music21 import converter
    from music21 import clef as m21clef
    score = converter.parse(str(midi_path))
    part = score.parts[0]
    for c in list(part.recurse().getElementsByClass(m21clef.Clef)):
        c.activeSite.remove(c)
    target = part.recurse().getElementsByClass("Measure").first() or part
    target.insert(0, _clef_for(clef_type))
    part.partName = name
    part.partAbbreviation = name
    return part
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_score.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/score.py tests/test_score.py
git commit -m "feat: build a notation part from a simplified MIDI"
```

---

### Task 2: 段を積んでスコアにする

**Files:**
- Modify: `app/score.py`（関数追加）
- Test: `tests/test_score.py`（テスト追加）

**Interfaces:**
- Consumes: なし
- Produces:
  - `build_full_score(parts: list, tempo: float) -> music21.stream.Score`
    渡された Part を順に段として積み、先頭段にテンポ標語がなければ付ける。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_score.py` に追記：
```python
def test_build_full_score_stacks_in_order():
    from app.score import build_full_score
    from music21 import stream, note
    from music21 import tempo as m21tempo
    p1 = stream.Part(); p1.partName = "A"; p1.append(note.Note("C4"))
    p2 = stream.Part(); p2.partName = "B"; p2.append(note.Note("E4"))
    sc = build_full_score([p1, p2], 120.0)
    assert len(sc.parts) == 2
    assert sc.parts[0].partName == "A"
    assert sc.parts[1].partName == "B"
    assert list(sc.parts[0].recurse().getElementsByClass(m21tempo.MetronomeMark))
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_score.py::test_build_full_score_stacks_in_order -v`
Expected: FAIL（`ImportError: cannot import name 'build_full_score'`）

- [ ] **Step 3: 最小実装を書く**

`app/score.py` の末尾に追記：
```python
def build_full_score(parts: list, tempo: float):
    """Part のリストを順に段として積んだ Score を返す。"""
    from music21 import stream
    from music21 import tempo as m21tempo
    sc = stream.Score()
    for p in parts:
        sc.insert(0, p)
    if parts:
        first = parts[0]
        if not list(first.recurse().getElementsByClass(m21tempo.MetronomeMark)):
            target = first.recurse().getElementsByClass("Measure").first() or first
            target.insert(0, m21tempo.MetronomeMark(number=round(tempo)))
    return sc


def score_to_musicxml(sc) -> str:
    """統合スコアを MusicXML 文字列に変換する。"""
    from music21.musicxml.m21ToXml import GeneralObjectExporter
    return GeneralObjectExporter(sc).parse().decode("utf-8")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_score.py -v`
Expected: PASS（2テストとも）

- [ ] **Step 5: コミット**

```bash
git add app/score.py tests/test_score.py
git commit -m "feat: stack parts into a full score"
```

---

### Task 3: 全パートを組み立てる（音程3段＋ドラム段）

**Files:**
- Modify: `app/score.py`（関数追加）
- Test: `tests/test_score.py`（テスト追加）

**Interfaces:**
- Consumes: `pitched_part_from_midi`, `build_full_score`, `app.grid.grid_to_score`, `app.grid.make_template_grid`
- Produces:
  - `assemble_full_score(midi_paths: dict, drum_grid: dict, tempo: float, chords: list = None) -> music21.stream.Score`
    - `midi_paths`：`{"vocals": path, "other": path, "bass": path}`（存在するものだけ）
    - PITCHED_ORDER の順に音程段を作り、最後にドラム段（grid由来）を積む。
    - `chords` があればボーカル段の各小節先頭に ChordSymbol を挿入。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_score.py` に追記：
```python
def test_assemble_full_score_order_and_clefs(tmp_path):
    from app.score import assemble_full_score
    from app.grid import make_template_grid
    from music21 import clef
    midi_paths = {
        "vocals": _tiny_midi(tmp_path, "v.mid"),
        "bass": _tiny_midi(tmp_path, "b.mid"),
    }
    grid = make_template_grid(100.0, 2)
    sc = assemble_full_score(midi_paths, grid, 100.0)
    # otherは無いので飛ばし、Vocal→Bass→Drums の順
    assert [p.partName for p in sc.parts] == ["Vocal", "Bass", "Drums"]
    # 最下段はパーカッション音部記号
    drum = sc.parts[-1]
    assert list(drum.recurse().getElementsByClass(clef.PercussionClef))
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_score.py::test_assemble_full_score_order_and_clefs -v`
Expected: FAIL（`ImportError: cannot import name 'assemble_full_score'`）

- [ ] **Step 3: 最小実装を書く**

`app/score.py` の末尾に追記：
```python
def assemble_full_score(midi_paths: dict, drum_grid: dict, tempo: float,
                        chords: list = None):
    """音程3段（存在するもの）＋ドラム段を組み立てて Score を返す。"""
    from music21 import harmony
    from app.grid import grid_to_score

    parts = []
    for key, clef_type, name in PITCHED_ORDER:
        path = midi_paths.get(key)
        if not path:
            continue
        part = pitched_part_from_midi(path, clef_type, name)
        if key == "vocals" and chords:
            measures = list(part.recurse().getElementsByClass("Measure"))
            for i, fig in enumerate(chords):
                if fig and i < len(measures):
                    try:
                        measures[i].insert(0.0, harmony.ChordSymbol(fig))
                    except Exception:
                        pass  # 解釈できないコード表記はスキップ
        parts.append(part)

    # ドラム段（最下段）
    drum_part = grid_to_score(drum_grid).parts[0]
    drum_part.partName = "Drums"
    drum_part.partAbbreviation = "Drums"
    parts.append(drum_part)

    return build_full_score(parts, tempo)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_score.py -v`
Expected: PASS（3テストとも）

- [ ] **Step 5: コミット**

```bash
git add app/score.py tests/test_score.py
git commit -m "feat: assemble pitched parts and drums into ordered score"
```

---

### Task 4: CLI（score_all.py）と実素材での通し確認

**Files:**
- Create: `score_all.py`
- Modify: `CLAUDE.md`（起動手順を追記）

**Interfaces:**
- Consumes: `app.score.assemble_full_score`, `app.score.score_to_musicxml`, `app.render.musicxml_to_svg`, `app.grid.make_template_grid`, `app.analyze.count_bars`
- Produces: `python score_all.py <出力フォルダ>` で統合スコアを書き出す

- [ ] **Step 1: CLIを作成**

`score_all.py`:
```python
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
```

- [ ] **Step 2: 全テストを通す**

Run: `./venv/bin/python -m pytest -v`
Expected: PASS（既存9本＋score 3本）

- [ ] **Step 3: 実素材で統合スコアを生成**

Run: `./venv/bin/python score_all.py output/Yvv4RVQzIFk --level 3`
Expected: 段数4（Vocal/Guitar/Bass/Drums）でMusicXMLとSVGが書き出される。

- [ ] **Step 4: 目視確認**

生成された `output/Yvv4RVQzIFk/_render/full_score.svg`（またはPNG化して）を開き、
上から ボーカル→ギター→ベース→ドラム の4段が縦に揃い、小節線が合っていること、
ドラム段がパーカッション記号・×ハイハットで出ていることを確認する。

- [ ] **Step 5: CLAUDE.md追記してコミット**

`CLAUDE.md` に「### 全パートScore統合」節を追記（コマンド：`./venv/bin/python score_all.py <出力フォルダ>`）。

```bash
git add score_all.py CLAUDE.md
git commit -m "feat: full-score CLI and manual verification"
```

---

## Self-Review

**1. Spec coverage（設計書の各項目→対応タスク）**
- 段の統合・並び順（Vocal/Guitar/Bass/Drums）→ Task 3・Global Constraints ✓
- 音程段をMIDIから生成（音部記号・楽器名）→ Task 1 ✓
- 段を積む・テンポ/拍子 → Task 2 ✓
- ドラム段（grid由来・最下段）→ Task 3 ✓
- コードをボーカル段に → Task 3（chords引数）✓
- MusicXML出力・SVG描画 → Task 2（score_to_musicxml）・Task 4 ✓
- エラー処理（欠けたパートは段を省く）→ Task 3（midi_paths に無い段はskip）✓
- テスト（段数・並び・音部記号・素材はRebound/生成MIDI）→ Task 1-3・4 ✓
- 割り切り（ギター/鍵盤1段・ドラムはテンプレ・PDF後）→ Global Constraints・Task 4 ✓

**2. Placeholder scan**：TBD/TODO・曖昧表現なし。各stepに実コードあり。

**3. Type consistency**：`pitched_part_from_midi(path,clef_type,name)->Part`、`build_full_score(parts,tempo)->Score`、`score_to_musicxml(sc)->str`、`assemble_full_score(midi_paths,drum_grid,tempo,chords=None)->Score`。各タスクの Interfaces と本文で一致。`grid_to_score(grid)->Score`（既存）から `.parts[0]` を取る点も一致。

**懸念点（実装時に検証）**：小節数が段ごとに食い違う場合、verovioの多段描画で小節線が完全に揃わない可能性がある。Task 4 の目視確認で崩れが大きければ、各段を最大小節数に合わせて空小節で埋める処理を build_full_score に追加する（設計書のエラー処理方針どおり）。
