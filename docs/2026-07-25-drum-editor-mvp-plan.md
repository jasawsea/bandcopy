# ドラム簡略化エディタ MVP 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Macローカルで動く「ドラムのグリッドを編集→ドラム譜を出力」する対話型エディタの核ループを作る。

**Architecture:** Python(Flask)バックエンド＋ブラウザUI。グリッドJSONを唯一の真実とし、UIが編集、サーバがgrid→MusicXML→verovio SVGで描画。ドラム分離音源は再生用に配信。

**Tech Stack:** Python 3.12, Flask, music21, verovio, cairosvg, librosa, demucs（すべてvenv導入済み。Flaskのみ新規）。フロントは素のHTML/CSS/JS。

## Global Constraints

- Python 3.12（venv：`06_アプリ開発/bandcopy/venv/`。実行は `./venv/bin/python`）。basic-pitchの制約で3.13不可。
- 作業ディレクトリ：`/Users/shigiharayasushi/Documents/Yasushi/06_アプリ開発/bandcopy/`。以降のパスはここからの相対。
- このフォルダは未gitリポジトリ。Task 0 で `git init`（このフォルダのみ）してからコミットを行う。
- グリッドは **16分固定**（steps_per_bar=16）。3連符・32分・ハネは対象外。
- ドラム3レーン固定：`KK`（キック）/`SN`（スネア）/`HH`（ハイハット）。
- 記譜位置：KK=displayStep F/octave 4、SN=C/5、HH=G/5（×符頭）。パーカッション音部記号。
- テストは pytest。テストで Demucs は動かさない（遅いため）。グリッド生成はテンポのみで完結させ、分離は別関数に隔離する。
- verovio描画オプション（既存踏襲）：`pageWidth 2100, pageHeight 2970, scale 45, adjustPageHeight True, header none, footer none`。

---

## ファイル構成

```
bandcopy/
  app/
    __init__.py        # パッケージ化
    grid.py            # グリッド模型・テンプレ生成・grid→music21→MusicXML
    render.py          # MusicXML文字列 → SVG（verovio）
    analyze.py         # 音源 → テンポ・小節数・ドラム分離音源
    server.py          # Flaskアプリ（ルート）
    templates/
      editor.html      # UIページ
    static/
      editor.js        # グリッド描画・操作・fetch
      editor.css       # 最小スタイル
  tests/
    __init__.py
    test_grid.py       # grid.py 単体テスト
    test_render.py     # render.py 単体テスト
    test_server.py     # Flaskルートのテスト（test client）
  requirements.txt     # Flask 追記
```

責務の分離：`grid.py`＝データと楽譜変換（純粋関数・テスト容易）、`render.py`＝描画のみ、`analyze.py`＝音源解析（副作用あり）、`server.py`＝HTTPの配線のみ。

---

### Task 0: プロジェクト雛形とFlask導入

**Files:**
- Create: `app/__init__.py`（空）
- Create: `tests/__init__.py`（空）
- Modify: `requirements.txt`（Flask・pytest追記）

**Interfaces:**
- Consumes: なし
- Produces: `app` パッケージ、テスト実行環境

- [ ] **Step 1: gitを初期化（このフォルダのみ）**

Run:
```bash
cd "/Users/shigiharayasushi/Documents/Yasushi/06_アプリ開発/bandcopy" && git init && printf "venv/\noutput/\n__pycache__/\n*.pyc\n.pytest_cache/\n" > .gitignore
```
Expected: `Initialized empty Git repository ...`

- [ ] **Step 2: Flaskとpytestをインストール**

Run:
```bash
./venv/bin/pip install flask==3.1.0 pytest==8.3.4
```
Expected: `Successfully installed flask ... pytest ...`

- [ ] **Step 3: requirements.txt に追記**

`requirements.txt` の末尾に追記：
```
# ローカルWebエディタ用
flask==3.1.0            # ローカルWebサーバ
pytest==8.3.4           # テスト
```

- [ ] **Step 4: パッケージ雛形を作成**

`app/__init__.py` と `tests/__init__.py` を空ファイルで作成。

- [ ] **Step 5: コミット**

```bash
git add .gitignore requirements.txt app/__init__.py tests/__init__.py
git commit -m "chore: scaffold app package and add Flask/pytest"
```

---

### Task 1: グリッド模型とテンプレート生成

**Files:**
- Create: `app/grid.py`
- Test: `tests/test_grid.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `make_template_grid(tempo: float, bars: int, steps_per_bar: int = 16) -> dict`
    戻り値dict：`{"tempo": float, "bars": int, "steps_per_bar": int, "lanes": {"KK": list[int], "SN": list[int], "HH": list[int]}}`。各laneは長さ `bars*steps_per_bar` の0/1配列。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_grid.py`:
```python
from app.grid import make_template_grid


def test_template_grid_shape_and_backbeat():
    g = make_template_grid(tempo=120.0, bars=2)
    assert g["tempo"] == 120.0
    assert g["bars"] == 2
    assert g["steps_per_bar"] == 16
    for lane in ("KK", "SN", "HH"):
        assert len(g["lanes"][lane]) == 32  # 2小節 * 16

    kk, sn, hh = g["lanes"]["KK"], g["lanes"]["SN"], g["lanes"]["HH"]
    # 1小節目：キック=1・3拍(step0,8)、スネア=2・4拍(step4,12)
    assert kk[0] == 1 and kk[8] == 1
    assert sn[4] == 1 and sn[12] == 1
    # ハイハットは8分（偶数ステップ）に8個
    assert sum(hh[0:16]) == 8
    assert all(hh[s] == 1 for s in range(0, 16, 2))
    # 2小節目も同じパターンが繰り返される
    assert kk[16] == 1 and kk[24] == 1
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_grid.py -v`
Expected: FAIL（`ModuleNotFoundError` または `ImportError: cannot import name 'make_template_grid'`）

- [ ] **Step 3: 最小実装を書く**

`app/grid.py`:
```python
"""グリッド（ドラム打点）の模型と、楽譜への変換。"""


def make_template_grid(tempo: float, bars: int, steps_per_bar: int = 16) -> dict:
    """テンポに合わせた基本8ビートのグリッドを生成する。

    キック=1・3拍、スネア=2・4拍、ハイハット=8分。編集の出発点。
    """
    n = bars * steps_per_bar
    kk = [0] * n
    sn = [0] * n
    hh = [0] * n
    for b in range(bars):
        base = b * steps_per_bar
        for s in range(0, steps_per_bar, 2):   # 8分＝2ステップおき
            hh[base + s] = 1
        kk[base + 0] = 1                        # 1拍
        kk[base + steps_per_bar // 2] = 1       # 3拍
        sn[base + steps_per_bar // 4] = 1       # 2拍
        sn[base + 3 * steps_per_bar // 4] = 1   # 4拍
    return {
        "tempo": tempo,
        "bars": bars,
        "steps_per_bar": steps_per_bar,
        "lanes": {"KK": kk, "SN": sn, "HH": hh},
    }
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_grid.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/grid.py tests/test_grid.py
git commit -m "feat: grid model and 8-beat template generator"
```

---

### Task 2: グリッド → MusicXML 変換

**Files:**
- Modify: `app/grid.py`（関数追加）
- Test: `tests/test_grid.py`（テスト追加）

**Interfaces:**
- Consumes: `make_template_grid` の戻り値dict
- Produces:
  - `grid_to_score(grid: dict) -> music21.stream.Score`
  - `grid_to_musicxml(grid: dict) -> str`（MusicXML文字列）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_grid.py` に追記：
```python
from app.grid import grid_to_musicxml


def test_grid_to_musicxml_has_percussion_and_xhead():
    g = make_template_grid(tempo=100.0, bars=1)
    xml = grid_to_musicxml(g)
    assert "<score-partwise" in xml
    # パーカッション音部記号
    assert "percussion" in xml.lower()
    # ハイハットは×符頭
    assert "<notehead" in xml and ">x<" in xml
    # 1小節分の measure が存在する
    assert xml.count("<measure") == 1
    # 打楽器なので unpitched（音程なし）で書かれる
    assert "<unpitched" in xml
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_grid.py::test_grid_to_musicxml_has_percussion_and_xhead -v`
Expected: FAIL（`ImportError: cannot import name 'grid_to_musicxml'`）

- [ ] **Step 3: 最小実装を書く**

`app/grid.py` の末尾に追記：
```python
# レーンごとの記譜位置（displayStep, displayOctave, notehead）
LANE_NOTATION = {
    "KK": ("F", 4, None),   # キック：下第1間
    "SN": ("C", 5, None),   # スネア：第3間
    "HH": ("G", 5, "x"),    # ハイハット：上第1線上・×符頭
}


def grid_to_score(grid: dict):
    """グリッドを music21 の打楽器スコアに変換する。"""
    from music21 import stream, note, clef, meter, duration
    from music21 import tempo as m21tempo

    spb = grid["steps_per_bar"]
    bars = grid["bars"]
    step_ql = 4.0 / spb  # 16ステップ/小節なら0.25拍

    part = stream.Part()
    part.insert(0, clef.PercussionClef())
    part.insert(0, meter.TimeSignature("4/4"))
    part.insert(0, m21tempo.MetronomeMark(number=round(grid["tempo"])))

    for b in range(bars):
        m = stream.Measure(number=b + 1)
        for lane, (dstep, doct, head) in LANE_NOTATION.items():
            arr = grid["lanes"][lane]
            v = stream.Voice()
            for s in range(spb):
                idx = b * spb + s
                if idx < len(arr) and arr[idx]:
                    n = note.Unpitched()
                    n.displayStep = dstep
                    n.displayOctave = doct
                    n.duration = duration.Duration(step_ql)
                    if head:
                        n.notehead = head
                    v.insert(s * step_ql, n)
            if list(v.notes):
                # 打点間の隙間を休符で埋める（そのレーン内で）
                v.makeRests(fillGaps=True, inPlace=True)
                m.insert(0, v)
        if not list(m.voices):
            m.insert(0, note.Rest(quarterLength=4.0))  # 空小節は全休符
        part.append(m)

    sc = stream.Score()
    sc.insert(0, part)
    return sc


def grid_to_musicxml(grid: dict) -> str:
    """グリッドを MusicXML 文字列に変換する。"""
    from music21.musicxml.m21ToXml import GeneralObjectExporter
    sc = grid_to_score(grid)
    return GeneralObjectExporter(sc).parse().decode("utf-8")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_grid.py -v`
Expected: PASS（2テストとも）
補足：`>x<` が出ない場合、`note.notehead='x'` のMusicXML出力形が異なる可能性がある。その場合は生成XMLを一度 `print` し、実際の notehead 要素表記（例：`<notehead>x</notehead>`）に合わせてアサートを調整する。実装（`notehead='x'`）自体はPoCで描画確認済み。

- [ ] **Step 5: コミット**

```bash
git add app/grid.py tests/test_grid.py
git commit -m "feat: convert grid to percussion MusicXML"
```

---

### Task 3: MusicXML → SVG 描画

**Files:**
- Create: `app/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `grid_to_musicxml` の戻り値（MusicXML文字列）
- Produces:
  - `musicxml_to_svg(xml: str) -> str`（SVG文字列）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_render.py`:
```python
from app.grid import make_template_grid, grid_to_musicxml
from app.render import musicxml_to_svg


def test_musicxml_to_svg_returns_svg():
    xml = grid_to_musicxml(make_template_grid(tempo=100.0, bars=1))
    svg = musicxml_to_svg(xml)
    assert svg.lstrip().startswith("<") and "svg" in svg[:200].lower()
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_render.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.render'`）

- [ ] **Step 3: 最小実装を書く**

`app/render.py`:
```python
"""MusicXML文字列を verovio で SVG に描画する。"""

VEROVIO_OPTIONS = {
    "pageWidth": 2100,
    "pageHeight": 2970,
    "scale": 45,
    "adjustPageHeight": True,
    "header": "none",
    "footer": "none",
}


def musicxml_to_svg(xml: str) -> str:
    """MusicXML文字列を1ページ目のSVG文字列に変換する。"""
    import verovio
    tk = verovio.toolkit()
    tk.setOptions(VEROVIO_OPTIONS)
    tk.loadData(xml)
    return tk.renderToSVG(1)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_render.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/render.py tests/test_render.py
git commit -m "feat: render MusicXML to SVG via verovio"
```

---

### Task 4: 音源解析（テンポ・小節数・ドラム分離）

**Files:**
- Create: `app/analyze.py`
- Test: `tests/test_grid.py`（小節数計算のテストを追加。Demucsは動かさない）

**Interfaces:**
- Consumes: `bandcopy.py` の `detect_tempo`, `separate_stems`
- Produces:
  - `count_bars(duration_sec: float, tempo: float) -> int`
  - `build_template_from_audio(audio_path: str) -> dict`（テンポ検出→小節数→テンプレgrid。Demucs不要）
  - `separate_drum_stem(audio_path: str, out_dir: str) -> str`（ドラムWAVパスを返す。Demucs実行）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_grid.py` に追記：
```python
from app.analyze import count_bars


def test_count_bars_rounds_up():
    # テンポ120 → 1小節=2秒。7秒は3.5小節ぶん → 切り上げ4小節
    assert count_bars(duration_sec=7.0, tempo=120.0) == 4
    # ちょうど割り切れる場合
    assert count_bars(duration_sec=8.0, tempo=120.0) == 4
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_grid.py::test_count_bars_rounds_up -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.analyze'`）

- [ ] **Step 3: 最小実装を書く**

`app/analyze.py`:
```python
"""音源の解析。テンポ・小節数・ドラム分離を担う。"""
import math
import sys
from pathlib import Path

# 既存のパイプライン関数を再利用する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bandcopy import detect_tempo, separate_stems  # noqa: E402
from app.grid import make_template_grid  # noqa: E402


def count_bars(duration_sec: float, tempo: float) -> int:
    """4/4を前提に、曲尺を小節数（切り上げ）に換算する。"""
    bar_sec = 4 * 60.0 / tempo
    return int(math.ceil(duration_sec / bar_sec))


def build_template_from_audio(audio_path: str) -> dict:
    """音源からテンポと小節数を求め、テンプレートグリッドを返す（Demucs不要）。"""
    import librosa
    path = Path(audio_path).expanduser().resolve()
    tempo = detect_tempo(path)
    dur = librosa.get_duration(path=str(path))
    bars = count_bars(dur, tempo)
    return make_template_grid(tempo, bars)


def separate_drum_stem(audio_path: str, out_dir: str) -> str:
    """Demucsでドラムを分離し、ドラムWAVのパスを返す。"""
    path = Path(audio_path).expanduser().resolve()
    work = Path(out_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    stems = separate_stems(path, work)
    drum = stems.get("drums")
    if drum is None:
        raise RuntimeError("ドラムパートを分離できませんでした")
    return str(drum)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_grid.py::test_count_bars_rounds_up -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/analyze.py tests/test_grid.py
git commit -m "feat: audio analysis (tempo, bar count, drum separation)"
```

---

### Task 5: Flaskサーバのルート

**Files:**
- Create: `app/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `app.grid`（`grid_to_musicxml`）, `app.render`（`musicxml_to_svg`）
- Produces:
  - Flaskアプリ生成関数 `create_app(state: dict) -> Flask`
  - ルート：`GET /`（ページ）, `GET /grid`（初期グリッドJSON）, `POST /render`（grid→SVG）, `POST /export/musicxml`（grid→MusicXML添付）, `GET /stem`（ドラムWAV）
  - `state` dict：`{"grid": dict, "stem_path": str | None}`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_server.py`:
```python
import json
from app.grid import make_template_grid
from app.server import create_app


def _client():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None}
    return create_app(state).test_client()


def test_get_grid_returns_json():
    r = _client().get("/grid")
    assert r.status_code == 200
    data = r.get_json()
    assert data["bars"] == 1 and "KK" in data["lanes"]


def test_post_render_returns_svg():
    grid = make_template_grid(100.0, 1)
    r = _client().post("/render", json=grid)
    assert r.status_code == 200
    assert "svg" in r.get_data(as_text=True)[:200].lower()


def test_post_export_musicxml():
    grid = make_template_grid(100.0, 1)
    r = _client().post("/export/musicxml", json=grid)
    assert r.status_code == 200
    assert "<score-partwise" in r.get_data(as_text=True)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_server.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.server'`）

- [ ] **Step 3: 最小実装を書く**

`app/server.py`:
```python
"""ローカルWebエディタのFlaskアプリ。HTTPの配線のみ。"""
from flask import Flask, jsonify, request, Response, send_file, render_template

from app.grid import grid_to_musicxml
from app.render import musicxml_to_svg


def create_app(state: dict) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("editor.html")

    @app.get("/grid")
    def get_grid():
        return jsonify(state["grid"])

    @app.post("/render")
    def render():
        grid = request.get_json(force=True)
        svg = musicxml_to_svg(grid_to_musicxml(grid))
        return Response(svg, mimetype="image/svg+xml")

    @app.post("/export/musicxml")
    def export_musicxml():
        grid = request.get_json(force=True)
        xml = grid_to_musicxml(grid)
        return Response(
            xml,
            mimetype="application/vnd.recordare.musicxml+xml",
            headers={"Content-Disposition": "attachment; filename=drums.musicxml"},
        )

    @app.get("/stem")
    def stem():
        if not state.get("stem_path"):
            return ("no stem", 404)
        return send_file(state["stem_path"], mimetype="audio/wav")

    return app
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS（3テストとも）

- [ ] **Step 5: コミット**

```bash
git add app/server.py tests/test_server.py
git commit -m "feat: Flask routes for grid, render, export, stem"
```

---

### Task 6: エディタUI（HTML/CSS/JS）

**Files:**
- Create: `app/templates/editor.html`
- Create: `app/static/editor.css`
- Create: `app/static/editor.js`

**Interfaces:**
- Consumes: `GET /grid`, `POST /render`, `POST /export/musicxml`, `GET /stem`
- Produces: ブラウザで動くエディタ（手動確認）

- [ ] **Step 1: HTMLを作成**

`app/templates/editor.html`:
```html
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>bandcopy ドラムエディタ</title>
  <link rel="stylesheet" href="/static/editor.css">
</head>
<body>
  <h1>ドラムエディタ</h1>
  <div id="controls">
    <button id="play">▶ ドラム音源を再生</button>
    <button id="render">譜面にする</button>
    <button id="export">MusicXML書き出し</button>
  </div>
  <audio id="audio" src="/stem" preload="none"></audio>
  <div id="grid"></div>
  <div id="score"></div>
  <script src="/static/editor.js"></script>
</body>
</html>
```

- [ ] **Step 2: CSSを作成**

`app/static/editor.css`:
```css
body { font-family: sans-serif; margin: 20px; }
#controls button { font-size: 15px; margin-right: 8px; padding: 6px 12px; }
#grid { margin: 16px 0; overflow-x: auto; }
.lane { display: flex; align-items: center; margin: 2px 0; }
.lane-label { width: 32px; font-weight: bold; }
.cell {
  width: 22px; height: 22px; margin: 1px;
  border: 1px solid #bbb; background: #fff; cursor: pointer; flex: 0 0 auto;
}
.cell.beat { border-left: 2px solid #888; }   /* 拍頭を強調 */
.cell.on { background: #333; }
.cell.on.hh { background: #c0392b; }           /* ハイハットは色分け */
#score svg { max-width: 100%; height: auto; }
```

- [ ] **Step 3: JSを作成**

`app/static/editor.js`:
```javascript
const LANES = ["HH", "SN", "KK"];   // 上から表示
let grid = null;

async function loadGrid() {
  grid = await (await fetch("/grid")).json();
  drawGrid();
}

function drawGrid() {
  const root = document.getElementById("grid");
  root.innerHTML = "";
  const spb = grid.steps_per_bar;
  for (const lane of LANES) {
    const row = document.createElement("div");
    row.className = "lane";
    const label = document.createElement("div");
    label.className = "lane-label";
    label.textContent = lane;
    row.appendChild(label);
    grid.lanes[lane].forEach((v, i) => {
      const cell = document.createElement("div");
      cell.className = "cell" + (v ? " on" : "") + (lane === "HH" ? " hh" : "");
      if (i % (spb / 4) === 0) cell.classList.add("beat");  // 拍頭
      cell.addEventListener("click", () => {
        grid.lanes[lane][i] = grid.lanes[lane][i] ? 0 : 1;
        cell.classList.toggle("on");
      });
      row.appendChild(cell);
    });
    root.appendChild(row);
  }
}

async function renderScore() {
  const svg = await (await fetch("/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  })).text();
  document.getElementById("score").innerHTML = svg;
}

async function exportXml() {
  const res = await fetch("/export/musicxml", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "drums.musicxml"; a.click();
  URL.revokeObjectURL(url);
}

function togglePlay() {
  const audio = document.getElementById("audio");
  if (audio.paused) audio.play(); else audio.pause();
}

document.getElementById("render").addEventListener("click", renderScore);
document.getElementById("export").addEventListener("click", exportXml);
document.getElementById("play").addEventListener("click", togglePlay);
loadGrid();
```

- [ ] **Step 4: コミット**

```bash
git add app/templates/editor.html app/static/editor.css app/static/editor.js
git commit -m "feat: browser editor UI (grid, play, render, export)"
```

---

### Task 7: 起動スクリプトと通しの手動確認

**Files:**
- Create: `run_editor.py`（サーバ起動エントリ）
- Create: `.claude/launch.json`（プレビュー用）
- Modify: `CLAUDE.md`（起動手順を追記）

**Interfaces:**
- Consumes: `app.server.create_app`, `app.analyze`
- Produces: `python run_editor.py <音源>` でエディタ起動

- [ ] **Step 1: 起動エントリを作成**

`run_editor.py`:
```python
"""ドラムエディタを起動する。使い方: ./venv/bin/python run_editor.py <音源ファイル>"""
import sys
from pathlib import Path

from app.analyze import build_template_from_audio, separate_drum_stem
from app.server import create_app


def main():
    if len(sys.argv) < 2:
        print("使い方: ./venv/bin/python run_editor.py <音源ファイル>")
        sys.exit(1)
    audio = sys.argv[1]
    print("テンポ解析中...")
    grid = build_template_from_audio(audio)
    print("ドラム分離中（初回はモデルDLで数分）...")
    try:
        stem = separate_drum_stem(audio, Path("output") / "_editor")
    except Exception as e:
        print(f"分離に失敗（再生なしで続行）: {e}")
        stem = None
    app = create_app({"grid": grid, "stem_path": stem})
    print("http://127.0.0.1:5000 を開いてください")
    app.run(port=5000, debug=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: launch.json を作成**

`.claude/launch.json`:
```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "drum-editor",
      "runtimeExecutable": "./venv/bin/python",
      "runtimeArgs": ["run_editor.py", "audio/Yvv4RVQzIFk.mp3"],
      "port": 5000
    }
  ]
}
```

- [ ] **Step 3: 全テストを通す**

Run: `./venv/bin/python -m pytest -v`
Expected: PASS（grid・render・server の全テスト）

- [ ] **Step 4: 手動確認（ブラウザ）**

`audio/Yvv4RVQzIFk.mp3`（既存Rebound素材）で起動し、ブラウザで以下を確認：
1. グリッドが基本8ビートで表示される
2. 升目クリックで打点がトグルする
3. 「▶ ドラム音源を再生」で分離ドラムが鳴る
4. 「譜面にする」でドラム譜（パーカッション記号・×ハイハット）が表示される
5. 「MusicXML書き出し」で落ちたファイルがMuseScoreで開ける

- [ ] **Step 5: CLAUDE.md に起動手順を追記してコミット**

`CLAUDE.md` に「### ドラムエディタMVP 起動手順」節を追記（コマンド：`./venv/bin/python run_editor.py <音源>`）。

```bash
git add run_editor.py .claude/launch.json CLAUDE.md
git commit -m "feat: editor launcher, preview config, manual verification"
```

---

## Self-Review

**1. Spec coverage（設計書の各項目→対応タスク）**
- ローカルWeb・grid唯一の真実 → Task 1・5 ✓
- 解析（テンポ/分離/テンプレ生成）→ Task 4 ✓
- サーバ（画面/grid/render/stem/export）→ Task 5 ✓
- UI（グリッド編集/再生/譜面化/書き出し）→ Task 6 ✓
- grid→MusicXML（パーカッション記号・×符頭）→ Task 2 ✓
- 描画＝サーバ往復verovio → Task 3 ✓
- エラー処理（分離失敗で継続）→ Task 4（例外）・Task 7（再生なし継続）✓
- テスト（grid→MusicXML単体・手動MuseScore）→ Task 2・7 ✓
- 16分固定・3レーン・記譜位置 → Global Constraints・Task 1/2 ✓
- 出発点＝テンプレート、自動採譜は後 → Task 1（テンプレのみ）✓ 将来差し込みはgrid JSON経由で無改修

**2. Placeholder scan**：TBD/TODO・曖昧な「適切に処理」等なし。各stepに実コードあり。

**3. Type consistency**：`make_template_grid`→dict、`grid_to_musicxml(grid)->str`、`musicxml_to_svg(xml)->str`、`create_app(state)`。各タスクの Interfaces と本文で一致。grid dictの鍵（tempo/bars/steps_per_bar/lanes.{KK,SN,HH}）は全タスクで統一。

**懸念点（実装時に検証）**：Task 2 の notehead 出力表記（`>x<` アサート）は music21 のバージョン差で表記が変わりうる。PoCで描画は確認済みなので、アサート不一致時は生成XMLを見て表記に合わせる旨を Step 4 補足に記載済み。
