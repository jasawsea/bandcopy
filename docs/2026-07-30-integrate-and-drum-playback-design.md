# アプリ統合（1URL・独立タブ）＋ ドラム再生/MIDI書き出し 設計書

作成日：2026-07-30

2つの独立した機能を扱う。**①アプリ統合**（みんな用Gradio ＋ ドラムエディタ を1URLに同居）と、
**②ドラム再生＋MIDI書き出し**（編集グリッドをアプリ内で鳴らす＋MIDIファイルで配布）。
実装は独立に進められるが、②はエディタ内なので①でエディタが同居した後も同じコードで動く。

やっさん承認済みの方針：
- ①＝**統合**（行き来より配布重視）。タブは**独立（B）**：各タブが別々に音源を受け取る（1曲共有はしない）。
- ②＝**A（アプリ内Web Audio再生）＋ C（MIDIファイル書き出し）**。対象は**ドラム優先**（ピッチ系は
  MIDIが既にパイプライン出力済みなので配布は現状可能・アプリ内再生は後回し）。

---

## ① アプリ統合（1URL・独立タブ）

### ゴール
1つのサーバ・1つのURLで、`/`＝みんな用Gradio、`/editor`＝ドラムエディタ。両画面に相互リンク。
仲間には**URL1つ**（またはColabの共有1つ）を渡せば両方使える。

### 構成ユニット

1. **`serve_all.py`（新規エントリ）**
   - FastAPI アプリを作る（fastapi/uvicorn/starlette は gradio 依存で導入済み＝新規依存なし）。
   - Flaskエディタを `/editor` にマウント：`app.mount("/editor", WSGIMiddleware(create_app(state)))`
     （`starlette.middleware.wsgi.WSGIMiddleware`）。
   - Gradio を `/` にマウント：`gr.mount_gradio_app(app, build_ui(), path="/")`。
   - ローカル起動：`uvicorn` で単一ポート（既定7860）。`./venv/bin/python serve_all.py`。

2. **エディタのURLを base-path 対応にする**（`app/templates/editor.html` / `app/static/editor.js`）
   - 現状エディタは root絶対パスで自分のAPIを叩く（`fetch("/grid")`, `href="/static/..."`,
     `src="/stem"` など計8箇所）。`/editor` 配下にマウントすると壊れる。
   - 対応：`editor.html` の `<head>` に `<base href="{{ base }}">`（マウント時 `"/editor/"`、
     単体起動時 `"/"`）を置き、**エディタ内のURLをすべて相対（先頭スラッシュ無し）に変更**
     （`fetch("grid")`, `href="static/editor.css"`, `src="stem"` …）。相対URLは `<base>` を基準に
     解決されるので、同じ front-end が単体起動でも `/editor` マウントでも動く。
   - `create_app(state)` は `state["base"]`（既定 `"/"`）を受け取り、`render_template("editor.html", base=...)`。

3. **エディタの"入口"（アップロード）**（`app/server.py` に追加、`app/analyze.py` 再利用）
   - 現状エディタは `run_editor.py` で**1曲固定起動**。独立タブにするには**エディタ自身に
     「音源アップロード→ドラム分離→グリッド初期化」**の入口が要る。
   - 追加：`POST /editor/load`（multipart で音源受領）→ 一時保存 → `separate_drum_stem` でドラム分離
     → `build_template_from_audio` でテンプレグリッド → state を更新（grid/stem_path/audio_path/
     grid_save_path）。完了後、既存の編集画面へ。
   - `/editor` の初期表示：state が未ロードなら**アップロード案内**、ロード済みなら現在の編集画面。
   - **割り切り（MVP・単一利用者）**：state はサーバ内の単一 dict のまま（同時に複数人が別曲を編集する
     多重化はしない）。Colabは基本1人が動かす前提。多人数同時編集は将来課題として明記。

4. **相互ナビリンク**
   - Gradio（`/`）：`gr.Markdown` に「[ドラム編集を開く](editor/)」リンク。
   - エディタ（`/editor`）：ページ上部に「みんな用に戻る（`../`）」リンク。

### Colab配布（最大の技術リスク・実装時に実機検証）
- ローカルは uvicorn 単一ポートで問題なし。
- Colab の公開トンネルが `/editor`（マウントした Flask 経路）まで通すかが未知。
  - まず `gr.mount_gradio_app` した app を gradio の共有機構で公開できるか検証。
  - 通らなければ **cloudflared / ngrok 等の別トンネル**で単一ポートを丸ごと公開する代替に切替
    （どちらも1ポート全体をトンネルするので `/editor` も通る）。
- この検証結果と採用手段を実装時に記録する。

### テスト方針（①）
- `serve_all` の app 構築（`build_app()->FastAPI`）を smoke：`/editor/` が 200、`/`（Gradio）が 200、
  `/editor/grid` が JSON を返す（TestClient）。
- base-path：`create_app({"base":"/editor/"})` の `GET /` HTML に `<base href="/editor/">` と相対URLが
  含まれる。`create_app({})` 既定は `<base href="/">`。
- `/editor/load`：`separate_drum_stem`/`build_template_from_audio` をモックし、アップロード→state更新→
  200＋グリッド返却。実Demucsは呼ばない。

---

## ② ドラム再生 ＋ MIDI書き出し（エディタ内・ドラム優先）

### ゴール
編集中のドラムグリッドを **(A)** アプリ内でその場再生（Web Audio・設定ゼロ）し、**(C)** GMドラムの
MIDIファイルとして書き出して配布できるようにする。既存の「▶ ドラム音源を再生」（分離WAVの再生）とは別に、
**「編集したグリッド自体」を鳴らす／書き出す**。

### 構成ユニット

1. **アプリ内再生（`app/static/editor.js`・Web Audio）**
   - ボタン「▶ グリッドを再生」を追加（既存の分離WAV再生ボタンとは別物・明示的にラベル分け）。
   - Web Audio API で各レーンの音を**合成**（外部音源/サンプル不要・ネットワーク不要）：
     - KK＝短い低域サイン（〜120Hz・急減衰）／SN＝ノイズバースト（バンドパス）／
       HH＝高域ノイズの極短音／HT/MT/FT＝ピッチ付きサイン（高→低）。
   - シーケンサ：`tempo` と `steps_per_bar` からステップ間隔を算出し、`AudioContext` の時刻に沿って
     各レーンの「1」のステップで音を鳴らす。1回再生（ループは任意・MVPは1回通し）。停止ボタン。
   - グリッドが編集されたら次の再生から反映（再生時に現 grid を読む）。

2. **グリッド→MIDI（`app/grid.py` に純関数 `grid_to_midi(grid) -> bytes`）**
   - Standard MIDI File（SMF format 0）を**自前で書き出す**（新規依存なし。`mido` は使わない）。
     ヘッダ（MThd）＋1トラック（MTrk）。GM準拠でチャンネル10（index 9）＝パーカッション。
   - レーン→GMノート番号：KK=36 / SN=38 / HH(closed)=42 / HT(High Tom)=50 / MT(Mid Tom)=47 /
     FT(Low/Floor Tom)=43。
   - テンポ（set tempo meta）と、各ステップ（16分＝480/4 tick 等、division=480前提でstep=division/4）に
     Note On/Off を配置。各打点は短い固定ゲート。
   - 純関数＝bytesを返すのみ（ファイルI/O無し）。

3. **書き出しルート（`app/server.py`）**
   - `POST /export/midi`（body=grid JSON）→ `grid_to_midi` の bytes を
     `Content-Disposition: attachment; filename=drums.mid`・`audio/midi` で返す。既存
     `/export/musicxml` と同じ様式。base-path対応（相対URL）。
   - エディタUI（`editor.html`/`editor.js`）：ボタン「MIDI書き出し（ドラム）」を既存の
     「MusicXML書き出し」の隣に追加。

### テスト方針（②）
- `grid_to_midi`（純関数・断定テスト）：
  - 返り値が `b"MThd"` で始まり、`b"MTrk"` を含む（正しいSMF構造）。
  - 打点のあるレーンだけ Note On が出る（例：KKに1発→ノート番号36のNote Onが1つ）。空グリッド→
    Note Onゼロ。
  - タム3レーンが正しいGM番号（50/47/43）で出る。
- `/export/midi` ルート：grid をPOST→200・`Content-Disposition` に `.mid`・本文が `MThd` 始まり。
- 再生（Web Audio）は**手動確認**（ブラウザで「▶ グリッドを再生」→ドラムが鳴る／停止できる）。JS単体
  テスト機構は無いので断定テストは書かない（①②とも既存方針どおり）。

---

## 全体の非機能・割り切り
- **新規依存ゼロ**（fastapi/uvicorn/starlette は gradio 依存で導入済み。MIDIは自前SMF・Web Audioはブラウザ標準）。
- 単一利用者前提（サーバ内 state は単一）。多人数同時編集は将来課題。
- ②はドラムのみ。ピッチ系（ベース/ギター/ボーカル）の**アプリ内再生**とMIDI統合書き出しは将来課題
  （`.mid` はパイプラインが既に出力済みなので配布は現状可能）。
- ①のColab公開トンネルは実装時に実機検証（ダメなら cloudflared/ngrok）。

## やらないこと（スコープ外）
- 1曲を両タブで共有する密結合（今回は独立タブ B）。
- ピッチ系パートのアプリ内再生。
- リッチな音源（サウンドフォント/本物の楽器音）。MVPは合成音。
- 多人数同時編集・認証・保存の永続化。
