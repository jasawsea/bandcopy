# アプリ統合（1URL・独立タブ）＋ ドラム再生/MIDI書き出し Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** みんな用Gradio（`/`）とドラムエディタ（`/editor`）を1つのFastAPIサーバ・1URLに同居させ、エディタに「グリッド再生（Web Audio）」と「MIDI書き出し（ドラム）」を追加する。

**Architecture:** 既存の Flask エディタ（`app/server.py`）はそのまま WSGI アプリとして FastAPI に `/editor` でマウントする。エディタの全URL（静的アセット・API fetch）を `<base>` タグ経由の相対パスに変え、単体起動（`run_editor.py`）でもマウント起動（`serve_all.py`）でも同じテンプレート／JSが動くようにする。MIDI書き出しは `app/grid.py` に純関数 `grid_to_midi` を追加し既存の `/export/musicxml` と同じ様式のルートで配線する。Web Audio再生はフロントエンドのみで完結する追加機能。

**Tech Stack:** Python 3.12 / Flask（エディタ） / FastAPI・uvicorn・starlette（新エントリ `serve_all.py`、gradio依存として既に導入済み） / Gradio（みんな用UI） / 素のJS + Web Audio API（ブラウザ標準） / 自前SMF（MIDI）書き出し。

## Global Constraints

- 新規依存ゼロ（fastapi/uvicorn/starlette/httpxはgradio依存で導入済み、MIDIは自前SMF実装、Web Audioはブラウザ標準）
- 単一利用者前提（サーバ内 state は単一 dict のまま。多人数同時編集は将来課題）
- タブは独立（B）：Gradio側とエディタ側で1曲を共有しない
- ②はドラムのみ（KK/SN/HH/HT/MT/FT）。ピッチ系パートのアプリ内再生・MIDI統合書き出しは対象外
- 既存の82テストを常に緑に保つ（後方互換：`create_app(state)` は `base` キーが無い state でも従来どおり動く）
- Colab公開トンネルの`/editor`到達可否はこの計画のスコープ外（設計書どおり別途実機検証）

---

## File Structure

- Modify: `app/templates/editor.html` — `<base>`対応・相対URL化・戻るリンク・再生/MIDIボタン追加
- Create: `app/templates/upload.html` — エディタの「音源アップロード」入口画面
- Modify: `app/static/editor.js` — fetch呼び出しの相対化・Web Audio再生ロジック・MIDI書き出しボタン
- Modify: `app/server.py` — `create_app`のbase対応・`GET /`のアップロード/編集分岐・`POST /load`・`POST /export/midi`
- Modify: `app/grid.py` — `grid_to_midi(grid) -> bytes`（純関数）追加
- Create: `serve_all.py` — FastAPIエントリ（`/`=Gradio、`/editor`=Flaskエディタをマウント）
- Modify: `app/webapp.py` — Gradio側にエディタへのリンクを追加
- Modify: `tests/test_server.py` — base対応・`/load`・`/export/midi`のテスト追加
- Modify: `tests/test_grid.py` — `grid_to_midi`のテスト追加
- Create: `tests/test_serve_all.py` — `serve_all.build_app()`のsmokeテスト

---

### Task 1: エディタのURLをbase-path対応にする

**Files:**
- Modify: `app/templates/editor.html`
- Modify: `app/static/editor.js`
- Modify: `app/server.py:24-26`（`create_app`内の`index()`ルート）
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: なし（既存の`create_app(state: dict) -> Flask`のstateに任意キー`base: str`が追加されるだけ）
- Produces: `create_app(state)`は`state.get("base", "/")`をテンプレートへ`base`変数として渡す。以降のタスクはこの`base`キーの規約（既定`"/"`、マウント時`"/editor/"`）に従う。

- [ ] **Step 1: `editor.html`を書き換える（`<base>`追加・相対URL化・戻るリンク）**

`app/templates/editor.html` を以下の内容に全面置換する：

```html
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>bandcopy ドラムエディタ</title>
  <base href="{{ base }}">
  <link rel="stylesheet" href="static/editor.css">
</head>
<body>
  <h1>ドラムエディタ</h1>
  {% if base != '/' %}<p><a href="../">みんな用に戻る</a></p>{% endif %}
  <div id="controls">
    <button id="play">▶ ドラム音源を再生</button>
    <button id="play_grid">▶ グリッドを再生</button>
    <button id="stop_grid" disabled>■ 停止</button>
    <button id="render">譜面にする</button>
    <button id="export">MusicXML書き出し</button>
    <button id="export_midi">MIDI書き出し（ドラム）</button>
    <button id="save" title="編集したドラムを統合スコア(score_all)に反映するため保存">スコア用に保存</button>
    <span id="save-msg"></span>
  </div>
  <div id="draft">
    <button id="auto_draft" title="ドラム音源からグルーヴの下書きを自動生成（タムは手入力）">自動下書き（音源から）</button>
    <span id="auto-msg"></span>
  </div>
  <div id="commands">
    <span class="cmd-label">簡略化：</span>
    <button id="thin_kicks" title="連続キック（ダブルキック等）を単発にまとめる">キック間引き</button>
    <button id="thin_hihat" title="ハイハットを1段階粗く（16分→8分→4分）">ハイハットを軽く</button>
    <button id="undo" disabled>↩ 元に戻す</button>
  </div>
  <audio id="audio" src="stem" preload="none"></audio>
  <div id="grid"></div>
  <div id="score"></div>
  <script src="static/editor.js"></script>
</body>
</html>
```

（再生ボタン・MIDIボタンの配線はTask 6・7で行う。この時点ではボタンはあるがイベントリスナーはまだ無い＝押しても何も起きないが、これはTask 1完了時点では許容する。）

- [ ] **Step 2: `editor.js`のfetch呼び出しをすべて相対パスに変更する**

`app/static/editor.js` 内の以下6箇所を書き換える（`fetch("/...")` → `fetch("...")`）：

```javascript
grid = await (await fetch("grid")).json();
```
（`loadGrid()`内。元は`fetch("/grid")`）

```javascript
grid = await (await fetch("simplify", {
```
（`applyCommand()`内。元は`fetch("/simplify", {`）

```javascript
const svg = await (await fetch("render", {
```
（`renderScore()`内。元は`fetch("/render", {`）

```javascript
const res = await fetch("export/musicxml", {
```
（`exportXml()`内。元は`fetch("/export/musicxml", {`）

```javascript
const res = await fetch("save-grid", {
```
（`saveGrid()`内。元は`fetch("/save-grid", {`）

```javascript
const res = await fetch("auto-draft", { method: "POST" });
```
（`autoDraft()`内。元は`fetch("/auto-draft", { method: "POST" });`）

- [ ] **Step 3: `app/server.py`の`index()`を`base`対応にする**

`app/server.py`の`index()`関数を以下に置換する：

```python
    @app.get("/")
    def index():
        return render_template("editor.html", base=state.get("base", "/"))
```

- [ ] **Step 4: 回帰テストを書く（相対パス・base変数の反映を確認）**

`tests/test_server.py` の先頭に `from pathlib import Path` を追加し、ファイル末尾に以下を追記する：

```python
def test_index_default_base_uses_root_and_relative_asset_paths():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None}
    r = create_app(state).test_client().get("/")
    html = r.get_data(as_text=True)
    assert '<base href="/">' in html
    assert 'href="static/editor.css"' in html
    assert 'src="static/editor.js"' in html
    assert 'src="stem"' in html


def test_index_custom_base_shown_in_head_and_back_link_appears():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None, "base": "/editor/"}
    r = create_app(state).test_client().get("/")
    html = r.get_data(as_text=True)
    assert '<base href="/editor/">' in html
    assert 'href="../"' in html


def test_editor_html_source_has_no_absolute_asset_paths():
    html = Path("app/templates/editor.html").read_text()
    assert 'href="/static' not in html
    assert 'src="/static' not in html
    assert 'src="/stem"' not in html


def test_editor_js_source_has_no_absolute_fetch_paths():
    js = Path("app/static/editor.js").read_text()
    assert 'fetch("/' not in js
```

- [ ] **Step 5: テストを実行して確認する**

Run: `./venv/bin/python -m pytest tests/test_server.py -v`
Expected: 追加した4件を含め全件PASS（既存テストも壊れていないこと）

- [ ] **Step 6: 全体テストで既存回帰が無いことを確認しコミット**

Run: `./venv/bin/python -m pytest -q`
Expected: 全件PASS（82件＋今回追加分）

```bash
git add app/templates/editor.html app/static/editor.js app/server.py tests/test_server.py
git commit -m "feat: エディタのURLをbase-path対応にする（相対URL化）"
```

---

### Task 2: エディタの入口（音源アップロード）を追加する

**Files:**
- Create: `app/templates/upload.html`
- Modify: `app/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `app.analyze.build_template_from_audio(audio_path: str) -> dict`（既存）、`app.analyze.separate_drum_stem(audio_path: str, out_dir: str) -> str`（既存）、Task 1の`base`規約
- Produces: `GET /` は `state.get("grid")` が falsy なら `upload.html` を、それ以外は `editor.html` を返す。`POST /load`（multipart, フィールド名`audio`）はロード成功で`state["grid"]`/`state["stem_path"]`/`state["audio_path"]`/`state["grid_save_path"]`を更新し`{"loaded": true}`を返す。以降のタスク（Task 3の`serve_all.py`）はこの`state`初期値（`grid=None`）とロード後の状態遷移を前提にできる。

- [ ] **Step 1: `upload.html`を作成する**

`app/templates/upload.html` を新規作成：

```html
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>bandcopy ドラムエディタ</title>
  <base href="{{ base }}">
</head>
<body>
  <h1>ドラムエディタ</h1>
  {% if base != '/' %}<p><a href="../">みんな用に戻る</a></p>{% endif %}
  <p>音源をアップロードするとドラムを分離してグリッド編集を開始します。</p>
  <form id="load-form">
    <input type="file" id="audio-file" accept="audio/*" required>
    <button type="submit">音源をアップロードして開始</button>
  </form>
  <p id="load-msg"></p>
  <script>
    document.getElementById("load-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = document.getElementById("load-msg");
      const file = document.getElementById("audio-file").files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("audio", file);
      msg.textContent = "解析中…（ドラム分離は数分かかることがあります）";
      const res = await fetch("load", { method: "POST", body: fd });
      if (res.ok) {
        location.reload();
      } else {
        const data = await res.json().catch(() => ({}));
        msg.textContent = "! " + (data.error || res.status);
      }
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: `app/server.py`に`/load`ルートと`index()`の分岐を実装する**

`create_app`内のimport文に以下を追加（ファイル冒頭のimport群に追記）：

```python
from app.analyze import build_template_from_audio, separate_drum_stem
```

`index()`を以下に置換する：

```python
    @app.get("/")
    def index():
        base = state.get("base", "/")
        if not state.get("grid"):
            return render_template("upload.html", base=base)
        return render_template("editor.html", base=base)
```

`get_grid()`の直後に`/load`ルートを追加する：

```python
    @app.post("/load")
    def load_audio():
        f = request.files.get("audio")
        if f is None:
            return (jsonify({"error": "音源ファイルがありません"}), 400)
        upload_dir = Path("output") / "_upload"
        upload_dir.mkdir(parents=True, exist_ok=True)
        audio_path = upload_dir / f.filename
        f.save(str(audio_path))
        try:
            grid = build_template_from_audio(str(audio_path))
            stem = separate_drum_stem(str(audio_path), str(Path("output") / "_editor"))
        except Exception:
            return (jsonify({"error": "音源の解析に失敗しました"}), 400)
        state["grid"] = grid
        state["stem_path"] = stem
        state["audio_path"] = str(audio_path)
        state["grid_save_path"] = str(Path("output") / audio_path.stem / "drum_grid.json")
        return jsonify({"loaded": True})
```

- [ ] **Step 3: テストを書く（アップロード成功/失敗/未指定・index分岐）**

`tests/test_server.py`の先頭に`import io`を追加し、ファイル末尾に追記する：

```python
def test_index_shows_upload_page_when_no_grid_loaded():
    state = {"grid": None, "stem_path": None}
    r = create_app(state).test_client().get("/")
    assert "アップロード" in r.get_data(as_text=True)


def test_index_shows_editor_page_when_grid_loaded():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None}
    r = create_app(state).test_client().get("/")
    assert "ドラムエディタ" in r.get_data(as_text=True)
    assert "アップロード" not in r.get_data(as_text=True)


def test_load_audio_without_file_returns_400():
    state = {"grid": None, "stem_path": None}
    r = create_app(state).test_client().post(
        "/load", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_load_audio_updates_state_and_returns_ok(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    fake_stem = tmp_path / "drums.wav"
    fake_stem.write_bytes(b"RIFF0000WAVE")
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)
    monkeypatch.setattr("app.server.separate_drum_stem", lambda p, d: str(fake_stem))
    state = {"grid": None, "stem_path": None, "audio_path": None}
    client = create_app(state).test_client()
    data = {"audio": (io.BytesIO(b"fake wav data"), "song.wav")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    assert state["grid"] == fake_grid
    assert state["stem_path"] == str(fake_stem)
    assert state["audio_path"].endswith("song.wav")
    assert (tmp_path / "output" / "_upload" / "song.wav").exists()


def test_load_audio_failure_returns_400(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def boom(p):
        raise RuntimeError("解析エラー")

    monkeypatch.setattr("app.server.build_template_from_audio", boom)
    state = {"grid": None, "stem_path": None}
    client = create_app(state).test_client()
    data = {"audio": (io.BytesIO(b"x"), "a.wav")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_upload_html_uses_custom_base(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {"grid": None, "stem_path": None, "base": "/editor/"}
    r = create_app(state).test_client().get("/")
    html = r.get_data(as_text=True)
    assert '<base href="/editor/">' in html
    assert 'href="../"' in html
```

- [ ] **Step 4: テストを実行して確認する**

Run: `./venv/bin/python -m pytest tests/test_server.py -v`
Expected: 追加分を含め全件PASS

- [ ] **Step 5: 全体テストとコミット**

Run: `./venv/bin/python -m pytest -q`
Expected: 全件PASS

```bash
git add app/templates/upload.html app/server.py tests/test_server.py
git commit -m "feat: エディタに音源アップロード入口を追加（POST /load）"
```

---

### Task 3: `serve_all.py`（1URL統合エントリ）を作成する

**Files:**
- Create: `serve_all.py`
- Test: `tests/test_serve_all.py`

**Interfaces:**
- Consumes: `app.server.create_app(state: dict) -> Flask`（Task 1/2で`base`・`grid=None`初期状態に対応済み）、`app.webapp.build_ui() -> gr.Blocks`（既存）
- Produces: `serve_all.build_app() -> fastapi.FastAPI`。`/editor`にFlaskエディタ、`/`にGradioをマウントした単一アプリ。`if __name__ == "__main__"`でuvicorn起動（既定ポート7860、環境変数`PORT`で上書き可）。

- [ ] **Step 1: `serve_all.py`を作成する**

```python
"""1URL・独立タブでみんな用GradioとドラムエディタをまとめてサーブするFastAPIエントリ。

起動: ./venv/bin/python serve_all.py
      PORT環境変数でポート変更可（既定7860）。
"""
import os

from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware

from app.server import create_app
from app.webapp import build_ui


def build_app() -> FastAPI:
    """FastAPIアプリを組み立てて返す（起動はしない。テスト用に分離）。"""
    app = FastAPI()

    editor_state = {
        "grid": None,
        "stem_path": None,
        "audio_path": None,
        "grid_save_path": None,
        "base": "/editor/",
    }
    # starlette.middleware.wsgi.WSGIMiddleware はstarlette 1.x でDeprecated
    # （将来削除予定・現行では動作する）。新規依存を避けるためこのまま使用。
    app.mount("/editor", WSGIMiddleware(create_app(editor_state)))

    import gradio as gr
    gr.mount_gradio_app(app, build_ui(), path="/")

    return app


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(build_app(), host="0.0.0.0", port=port)
```

- [ ] **Step 2: smokeテストを書く**

`tests/test_serve_all.py` を新規作成：

```python
from fastapi.testclient import TestClient

from serve_all import build_app


def test_editor_route_mounted_and_returns_200():
    client = TestClient(build_app())
    r = client.get("/editor/")
    assert r.status_code == 200


def test_gradio_root_returns_200():
    client = TestClient(build_app())
    r = client.get("/")
    assert r.status_code == 200


def test_editor_grid_route_returns_json():
    client = TestClient(build_app())
    r = client.get("/editor/grid")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
```

- [ ] **Step 3: テストを実行して確認する**

Run: `./venv/bin/python -m pytest tests/test_serve_all.py -v`
Expected: 3件PASS

- [ ] **Step 4: ローカルで実機起動確認する**

Run: `PORT=7861 ./venv/bin/python serve_all.py &` の後、別ターミナルで
`curl -sf http://127.0.0.1:7861/editor/ | head -c 200` と `curl -sf http://127.0.0.1:7861/ | head -c 200` を実行し、両方が200でHTMLを返すことを確認する。確認後 `kill %1` などでプロセスを止める。

- [ ] **Step 5: 全体テストとコミット**

Run: `./venv/bin/python -m pytest -q`
Expected: 全件PASS

```bash
git add serve_all.py tests/test_serve_all.py
git commit -m "feat: 1URL統合エントリserve_all.pyを追加（/=Gradio, /editor=エディタ）"
```

---

### Task 4: 相互ナビリンク（Gradio→エディタ）

**Files:**
- Modify: `app/webapp.py`

**Interfaces:**
- Consumes: なし（`build_ui()`の見出しMarkdown文字列を変更するのみ）
- Produces: `build_ui()`が返す`gr.Blocks`の冒頭Markdownに`/editor`への相対リンクを含む。Task 3で`/`にマウントされた際、リンクは`editor/`（相対）としてブラウザから`/editor/`に解決される。

- [ ] **Step 1: `app/webapp.py`の`build_ui()`冒頭Markdownにリンクを追加する**

`build_ui()`内の`gr.Markdown(...)`呼び出しを以下に置換する：

```python
        gr.Markdown(
            "# bandcopy — バンドコピー支援\n"
            "自分の手持ち音源をアップロードすると、**演奏しやすい難易度に落とした"
            "楽譜・タブ譜**と**パート別の練習音源**を作ります。個人練習用。\n\n"
            "ドラムだけをグリッドで編集したい場合は"
            "[ドラム編集を開く](editor/)。")
```

- [ ] **Step 2: 既存のwebapp smokeテストが壊れていないことを確認する**

Run: `./venv/bin/python -m pytest tests/test_webapp.py -v`
Expected: 既存テスト全件PASS（Markdown文字列を検査するテストが無ければそのままPASSするはず）

- [ ] **Step 3: `serve_all`経由で見た目を確認しコミット**

Run: `./venv/bin/python -m pytest -q`
Expected: 全件PASS

```bash
git add app/webapp.py
git commit -m "feat: Gradio側にドラムエディタへの相互リンクを追加"
```

---

### Task 5: `grid_to_midi`（グリッド→MIDI純関数）

**Files:**
- Modify: `app/grid.py`
- Test: `tests/test_grid.py`

**Interfaces:**
- Consumes: なし（`grid: dict`の既存構造 `{"tempo", "bars", "steps_per_bar", "lanes": {...}}` を使うのみ）
- Produces: `grid_to_midi(grid: dict) -> bytes`。GMドラム（チャンネル10）のStandard MIDI File(format 0)を返す。レーン→ノート番号：`KK=36, SN=38, HH=42, HT=50, MT=47, FT=43`。division=480固定・16分ステップ固定。Task 6の`/export/midi`ルートがこの関数をそのまま呼ぶ。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_grid.py` の末尾に追記する（既存のimportに`grid_to_midi`を含める必要があるため、ファイル冒頭の`from app.grid import ...`に`grid_to_midi`を追加する。既存のimport文の形はファイルを開いて確認し、無ければ以下のテスト内で都度importする）：

```python
def test_grid_to_midi_starts_with_mthd_and_contains_mtrk():
    from app.grid import grid_to_midi, make_template_grid
    grid = make_template_grid(120.0, 1)
    midi = grid_to_midi(grid)
    assert midi[:4] == b"MThd"
    assert b"MTrk" in midi


def test_grid_to_midi_only_active_lane_has_note_on():
    from app.grid import grid_to_midi
    grid = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 16,
        "lanes": {lane: [0] * 16 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    grid["lanes"]["KK"][0] = 1
    midi = grid_to_midi(grid)
    assert midi.count(bytes([0x99, 36, 100])) == 1  # KK=36のNote On が1つ
    assert midi.count(bytes([0x99, 38, 100])) == 0  # SNは打点なし


def test_grid_to_midi_empty_grid_has_zero_note_on():
    from app.grid import grid_to_midi
    grid = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 16,
        "lanes": {lane: [0] * 16 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    midi = grid_to_midi(grid)
    assert midi.count(bytes([0x99])) == 0


def test_grid_to_midi_toms_use_correct_gm_numbers():
    from app.grid import grid_to_midi
    grid = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 16,
        "lanes": {lane: [0] * 16 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    grid["lanes"]["HT"][0] = 1
    grid["lanes"]["MT"][1] = 1
    grid["lanes"]["FT"][2] = 1
    midi = grid_to_midi(grid)
    assert midi.count(bytes([0x99, 50, 100])) == 1  # HT
    assert midi.count(bytes([0x99, 47, 100])) == 1  # MT
    assert midi.count(bytes([0x99, 43, 100])) == 1  # FT
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `./venv/bin/python -m pytest tests/test_grid.py -k grid_to_midi -v`
Expected: `ImportError` または `AttributeError`（`grid_to_midi`が存在しない）でFAIL

- [ ] **Step 3: `app/grid.py`に`grid_to_midi`を実装する**

`app/grid.py`のファイル末尾に追記する：

```python
LANE_MIDI_NOTE = {
    "KK": 36,   # Bass Drum 1
    "SN": 38,   # Acoustic Snare
    "HH": 42,   # Closed Hi-Hat
    "HT": 50,   # High Tom
    "MT": 47,   # Low-Mid Tom
    "FT": 43,   # High Floor Tom
}


def _var_len(value: int) -> bytes:
    """整数をMIDI可変長数値（Variable Length Quantity）にエンコードする。"""
    buf = [value & 0x7F]
    value >>= 7
    while value:
        buf.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(buf)


def grid_to_midi(grid: dict) -> bytes:
    """グリッドをGMドラム（チャンネル10）のStandard MIDI File(format 0)に変換する。

    16分ステップ固定・division=480（1ステップ=120tick）。各打点は短い固定ゲート
    （60tick）でNote On/Offを打つ。ファイルI/Oは行わずbytesを返すのみ。
    """
    division = 480
    step_ticks = division // 4
    gate = step_ticks // 2
    spb = grid["steps_per_bar"]
    n = grid["bars"] * spb

    events = []  # (tick, is_note_on, note_num)
    for lane, note_num in LANE_MIDI_NOTE.items():
        arr = grid["lanes"].get(lane) or []
        for i in range(min(n, len(arr))):
            if arr[i]:
                on_tick = i * step_ticks
                events.append((on_tick, True, note_num))
                events.append((on_tick + gate, False, note_num))

    # 同tickではNote Offを先に処理する（不要な音の重なりを避ける）
    events.sort(key=lambda e: (e[0], 0 if not e[1] else 1))

    track = bytearray()
    usec_per_qn = round(60_000_000 / grid["tempo"])
    track += _var_len(0)
    track += bytes([0xFF, 0x51, 0x03]) + usec_per_qn.to_bytes(3, "big")

    prev_tick = 0
    for tick, is_on, note in events:
        track += _var_len(tick - prev_tick)
        prev_tick = tick
        status = 0x99 if is_on else 0x89  # チャンネル10（index 9）
        velocity = 100 if is_on else 0
        track += bytes([status, note, velocity])

    track += _var_len(0) + bytes([0xFF, 0x2F, 0x00])  # End of Track

    header = (
        b"MThd" + (6).to_bytes(4, "big")
        + (0).to_bytes(2, "big")   # format 0
        + (1).to_bytes(2, "big")   # ntrks
        + division.to_bytes(2, "big")
    )
    mtrk = b"MTrk" + len(track).to_bytes(4, "big") + bytes(track)
    return header + mtrk
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `./venv/bin/python -m pytest tests/test_grid.py -v`
Expected: 追加4件を含め全件PASS

- [ ] **Step 5: 全体テストとコミット**

Run: `./venv/bin/python -m pytest -q`
Expected: 全件PASS

```bash
git add app/grid.py tests/test_grid.py
git commit -m "feat: グリッド→MIDI純関数grid_to_midiを追加"
```

---

### Task 6: `/export/midi`ルート

**Files:**
- Modify: `app/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `app.grid.grid_to_midi(grid: dict) -> bytes`（Task 5）
- Produces: `POST /export/midi`（body=grid JSON）→ `audio/midi`・`Content-Disposition: attachment; filename=drums.mid`でMIDI bytesを返す。Task 7のUIボタンがこのエンドポイントを叩く。

- [ ] **Step 1: `app/server.py`のimportに`grid_to_midi`を追加する**

冒頭の`from app.grid import grid_to_musicxml`を以下に置換する：

```python
from app.grid import grid_to_musicxml, grid_to_midi
```

- [ ] **Step 2: `/export/midi`ルートを追加する**

`export_musicxml()`の直後に追加する：

```python
    @app.post("/export/midi")
    def export_midi():
        grid = request.get_json(force=True)
        data = grid_to_midi(grid)
        return Response(
            data,
            mimetype="audio/midi",
            headers={"Content-Disposition": "attachment; filename=drums.mid"},
        )
```

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_server.py`末尾に追記：

```python
def test_post_export_midi_returns_smf():
    grid = make_template_grid(100.0, 1)
    r = _client().post("/export/midi", json=grid)
    assert r.status_code == 200
    assert r.data[:4] == b"MThd"
    assert "drums.mid" in r.headers["Content-Disposition"]
    assert r.mimetype == "audio/midi"
```

- [ ] **Step 4: テストを実行して通ることを確認する**

Run: `./venv/bin/python -m pytest tests/test_server.py -k export_midi -v`
Expected: PASS

- [ ] **Step 5: 全体テストとコミット**

Run: `./venv/bin/python -m pytest -q`
Expected: 全件PASS

```bash
git add app/server.py tests/test_server.py
git commit -m "feat: POST /export/midiルートを追加（ドラムMIDI書き出し）"
```

---

### Task 7: MIDI書き出しボタン（UI配線）

**Files:**
- Modify: `app/static/editor.js`

**Interfaces:**
- Consumes: Task 6の`POST /export/midi`、Task 1で`editor.html`に追加済みの`<button id="export_midi">`
- Produces: クリックで`drums.mid`をダウンロードする`exportMidi()`関数とイベントリスナー登録

- [ ] **Step 1: `exportMidi()`を`editor.js`に追加する**

`exportXml()`関数の直後に追加：

```javascript
async function exportMidi() {
  const res = await fetch("export/midi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "drums.mid"; a.click();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 2: イベントリスナーを登録する**

ファイル末尾のリスナー登録群（`document.getElementById("export").addEventListener(...)`の直後）に追加：

```javascript
document.getElementById("export_midi").addEventListener("click", exportMidi);
```

- [ ] **Step 3: 既存の回帰テストを実行する（JS構文・絶対パス混入が無いことの間接確認）**

Run: `./venv/bin/python -m pytest tests/test_server.py -v`
Expected: Task 1で追加した`test_editor_js_source_has_no_absolute_fetch_paths`を含め全件PASS（`fetch("export/midi"...)`は相対のためこのガードに抵触しない）

- [ ] **Step 4: 手動確認**

`PORT=5050 EDITOR_STEM=<既存ドラムWAV> ./venv/bin/python run_editor.py <音源>` でエディタを起動し、ブラウザで「MIDI書き出し（ドラム）」ボタンを押して`drums.mid`がダウンロードされることを確認する。

- [ ] **Step 5: コミット**

```bash
git add app/static/editor.js
git commit -m "feat: エディタにMIDI書き出しボタンを配線"
```

---

### Task 8: グリッドのアプリ内再生（Web Audio）

**Files:**
- Modify: `app/static/editor.js`

**Interfaces:**
- Consumes: グローバル変数`grid`（既存。`loadGrid()`で読み込まれる現在編集中のグリッド）、Task 1で`editor.html`に追加済みの`<button id="play_grid">`・`<button id="stop_grid">`
- Produces: `playGrid()` / `stopGrid()`関数。手動確認のみ（JS単体テスト機構が無いため、設計書どおり断定テストは書かない）。

- [ ] **Step 1: 合成音・シーケンサを`editor.js`に追加する**

ファイル冒頭の`let history = [];`の直後に追加：

```javascript
let audioCtx = null;
let playTimers = [];
let playing = false;

function synthHit(lane, time) {
  const ctx = audioCtx;
  if (lane === "KK") {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(120, time);
    osc.frequency.exponentialRampToValueAtTime(40, time + 0.15);
    gain.gain.setValueAtTime(1, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + 0.15);
    osc.connect(gain).connect(ctx.destination);
    osc.start(time); osc.stop(time + 0.15);
  } else if (lane === "SN" || lane === "HH") {
    const dur = lane === "SN" ? 0.15 : 0.05;
    const bufferSize = Math.max(1, Math.floor(ctx.sampleRate * dur));
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;
    const noise = ctx.createBufferSource();
    noise.buffer = buffer;
    const filter = ctx.createBiquadFilter();
    filter.type = lane === "SN" ? "bandpass" : "highpass";
    filter.frequency.value = lane === "SN" ? 1800 : 8000;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(1, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + dur);
    noise.connect(filter).connect(gain).connect(ctx.destination);
    noise.start(time); noise.stop(time + dur);
  } else {
    const freqMap = { HT: 220, MT: 180, FT: 140 };
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    const f0 = freqMap[lane] || 160;
    osc.frequency.setValueAtTime(f0, time);
    osc.frequency.exponentialRampToValueAtTime(f0 * 0.6, time + 0.2);
    gain.gain.setValueAtTime(1, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + 0.2);
    osc.connect(gain).connect(ctx.destination);
    osc.start(time); osc.stop(time + 0.2);
  }
}

function playGrid() {
  if (playing || !grid) return;
  audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  playing = true;
  document.getElementById("play_grid").disabled = true;
  document.getElementById("stop_grid").disabled = false;
  const spb = grid.steps_per_bar;
  const n = grid.bars * spb;
  const stepSec = (60 / grid.tempo) / (spb / 4);
  const startTime = audioCtx.currentTime + 0.05;
  for (const lane of Object.keys(grid.lanes)) {
    grid.lanes[lane].forEach((v, i) => {
      if (v && i < n) synthHit(lane, startTime + i * stepSec);
    });
  }
  const totalMs = (n * stepSec + 0.3) * 1000;
  playTimers.push(setTimeout(stopGrid, totalMs));
}

function stopGrid() {
  playTimers.forEach(clearTimeout);
  playTimers = [];
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  playing = false;
  document.getElementById("play_grid").disabled = false;
  document.getElementById("stop_grid").disabled = true;
}
```

- [ ] **Step 2: イベントリスナーを登録する**

ファイル末尾のリスナー登録群に追加：

```javascript
document.getElementById("play_grid").addEventListener("click", playGrid);
document.getElementById("stop_grid").addEventListener("click", stopGrid);
```

- [ ] **Step 3: 回帰テストを実行する**

Run: `./venv/bin/python -m pytest -q`
Expected: 全件PASS（このタスクはJSのみの変更でPythonテストへの影響は無いはずだが、既存回帰が壊れていないことを確認する）

- [ ] **Step 4: 手動確認（設計書どおりJS単体テスト機構は無いため必須）**

`PORT=5050 EDITOR_STEM=<既存ドラムWAV> ./venv/bin/python run_editor.py <音源>` でエディタを起動し、ブラウザで：
1. 「▶ グリッドを再生」を押し、KK/SN/HHおよび（打点があれば）タムの合成音が再生されることを確認する
2. 再生中は「▶ グリッドを再生」がdisabled・「■ 停止」がenabledになることを確認する
3. 「■ 停止」を押すと音が止まり、ボタンの有効/無効が元に戻ることを確認する
4. グリッドを編集（升目クリック）した後に再生し、変更が反映されることを確認する（「再生時に現gridを読む」設計どおり）

- [ ] **Step 5: コミット**

```bash
git add app/static/editor.js
git commit -m "feat: エディタにグリッドのWeb Audio再生を追加"
```

---

## 完了確認（全タスク後）

- [ ] **最終確認: 全体テストとColabトンネル検証の申し送り**

Run: `./venv/bin/python -m pytest -q`
Expected: 全件PASS（Task開始時82件 + Task1(4) + Task2(6) + Task3(3) + Task5(4) + Task6(1) = 100件前後）

設計書に明記のとおり、Colab公開トンネルが`/editor`まで通るかは未検証のまま残る。実装完了後、別途Colabで`serve_all.py`相当の起動を実機確認し、通らなければ`cloudflared`/`ngrok`への切替を検討する（この計画のスコープ外・CLAUDE.mdに次の一手として記録する）。
