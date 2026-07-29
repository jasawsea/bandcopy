# bandcopy プロジェクト

## これは何か

バンドでコピーしたい曲の音源から、パート別の練習音源と「演奏しやすい難易度に落とした楽譜」を自動生成するツール。

近年の楽曲は音が重なりすぎ・技巧的すぎてバンドコピーが困難なケースが多い。市販ツール（Moises、Klangio）は分離と採譜まではできるが、**難易度を下げる機能がない**。そこが本プロジェクトの独自部分。

## 構成

| ファイル | 役割 |
|---|---|
| `getaudio.py` | yt-dlp で動画URLから音声抽出（補助ツール、単体で動く） |
| `bandcopy.py` | メインCLI。分離→採譜→簡略化→楽譜出力の統合パイプライン |
| `simplify.py` | **中核**。MIDIの難易度を下げるロジック |
| `requirements.txt` | 依存ライブラリ |
| `手順書.md` | エンドユーザー（非エンジニア）向けの操作手順 |

## パイプライン

```
音源(MP3)
  ↓ librosa            テンポ検出
  ↓ Demucs (htdemucs)  4パート分離（drums/bass/other/vocals）
  ↓ Basic Pitch        採譜（MIDI化）※ドラムは音程がないため除外
  ↓ simplify.py        難易度レベル1〜5に簡略化
  ↓ music21            MusicXML出力
楽譜 + パート別音源
```

## 簡略化ロジック（simplify.py）

レベル1〜5（1が最も簡単、5が原曲どおり）。各レベルは `PROFILES` 辞書でパラメータ定義。

処理順序：
1. **グリッド吸着** — 音符の開始/終了を8分または16分グリッドにクオンタイズ
2. **短音削除** — 閾値未満の音符を除去（装飾音・ゴーストノート対策）
3. **和音削減** — 同時発音数を制限。残す音の優先方針はパートごとに変える
   - bass → `low`（ルート音優先）
   - other → `outer`（最低音と最高音）
   - vocals → `high`（主旋律優先）
4. **連打統合** — 同じ音高の連続を1音にまとめる（レベル1〜2のみ）

## 環境制約

- **Python 3.10〜3.12 必須**。basic-pitch が 3.13 未対応
- ffmpeg が必要（getaudio.py の MP3 変換）
- Demucs は初回実行時にモデル（数百MB）を自動ダウンロード
- CPU のみだと1曲あたり5〜15分。GPU があれば1分程度

## 開発上の注意

- **日本語ファイル名は避ける。** Demucs のパス処理で稀に失敗する（`--ascii-name` オプションを用意済み）
- テンポ検出は半分/2倍にズレることがある。楽譜のリズムが崩れる主因はここ
- 採譜精度は7〜8割が上限。完璧を目指さず「AIが8割、人が2割直す」前提の設計
- 動作確認は**短い音源（30秒程度）× 単一パート**で回すこと。フル尺は待ち時間が長く試行錯誤に向かない

## 想定利用者

非エンジニアのバンドメンバーも含む。エラーメッセージと `手順書.md` は平易な日本語で書くこと。

## 権利面の設計方針

- 個人の練習利用が前提
- 将来アプリ化する場合、**入力は各自が手持ちの音源をアップロードする方式**にする（サーバー側で動画サイトから取得する設計にはしない）

## セットアップ状況（2026-07-24 タスク0完了）

実環境で動作確認済み。以下がこのMac（arm64・Python 3.12.13）の状態。

- 仮想環境：このフォルダ内の `venv/`（`python3.12 -m venv venv` で作成）
- 実行コマンド例：
  ```
  ./venv/bin/python bandcopy.py test30.wav --parts bass --level 3
  ```
- 依存は `requirements.txt`（動作確認版にピン）／完全再現は `requirements.lock.txt`
- 検証用音源：`test30.wav`（30秒の合成音・110Hz＝A2。エンドツーエンド確認用）

### 実環境で直した3点（コードは元の設計を尊重し最小修正）
1. **採譜バックエンドをONNXに固定** — TensorFlow 2.16(Keras3)が同梱TFモデルを
   読めないため。`bandcopy.py transcribe()` で ONNX版モデルを明示指定。
2. **テンポ0.0のガード** — 検出失敗時は120BPMを仮定（ゼロ除算防止）。
3. **scipy互換シム** — scipy1.13+で削除された `scipy.signal.gaussian` を
   `windows.gaussian` から復元（basic-pitchが内部参照するため）。

### 実曲テスト（2026-07-24）
- 素材：Josh Woodward「The Best Song」(VideoSong) の35秒。CC-BY・本人公式YouTube。
  `getaudio.py --start 1:00 --end 1:35 --quality 320 --ascii-name` で取得。
- 結果：テンポ実測117.5BPM／分離4パート／採譜 ベース123・ギター249・ボーカル97音。
- 採譜品質の客観指標＝各パートが正しい音域に収まっている
  （ベース中央値G2・ギターG3・ボーカルF3）。デタラメではない。
- **既知の不具合**：MuseScore 4 の CLI（mscore -o out.pdf in.musicxml）が
  この macOS(Darwin 25.5) でクラッシュしPDF書き出し不可。GUIで.musicxmlを
  開くのは正常。→ タスク2のPDF自動化は別解が要る（LilyPond等の検討）。

### タスク2の一部を先行実装（2026-07-25）
楽譜が読めない主因を修正済み。
- **テンポ・拍子をMIDIに埋め込み**（`write_midi_with_tempo`）。従来はBasic Pitch
  既定の120BPMのままで、簡略化グリッド（実テンポ）と食い違いリズムが崩壊していた。
- **パート別の音部記号・楽器名を設定**（`midi_to_musicxml` に clef_type/instrument_name
  引数追加、`CLEF_STRATEGY`）。bass=ヘ音記号、other/vocals=ト音記号。
- 効果：Rebound35秒で、24連符・32分の混沌 → 8分16分中心の読める楽譜に。
  楽器名も Electric Piano → Vocal/Guitar/Bass に。
- 残る粗さ：ギター/ベースの音符が下加線に沈みがち（オクターブ記号clefで改善余地）。
- 楽譜画像化の手段：verovio + cairosvg（venv導入済み）で musicxml→PNG。
  MuseScore CLI は Darwin 25.5 でクラッシュするため、確認用はこちらを使う。

### オクターブ音部記号を追加（2026-07-25）
ギター/ベースの音符が下加線に沈む問題を、楽器の慣習どおりのオクターブ移調
音部記号で解消。
- `CLEF_STRATEGY`：bass=`bass8vb`（ヘ音記号＋下8）／other=`treble8vb`
  （ト音記号＋下8）／vocals=`treble`（音域的に沈まないため据え置き）。
- `midi_to_musicxml` に clef_map を追加（treble/bass/treble8vb/bass8vb）。
  music21 の `Bass8vbClef` / `Treble8vbClef` を使用（octaveChange=-1）。
- 効果：既存Lv3 MIDIから再描画して確認。ギター（中央値G3）・ベース（G2）とも
  記譜が実音の1オクターブ上になり、音符がほぼ五線内に収まった。
- 確認画像：`output/Yvv4RVQzIFk/_render/other_Lv3_8vb.png`・`bass_Lv3_8vb.png`
- 残課題：Lv3は依然16分＋臨時記号が多く密。密度は簡略化レベルの領域（clefと別問題）。

### コードネーム自動付与を実装（2026-07-25）
伴奏パート（other＝ギター・キーボード）の楽譜に、小節ごとのコードを表示。
- **方式**：採譜MIDIの音は使わず、原曲の響き（librosa chroma_cqt）から小節単位で
  コードテンプレート照合し丸める。採譜の臨時記号ノイズに引きずられないため。
- **語彙**：基本三和音（maj/min/sus4）を優先し、7th（7/maj7/m7）は三和音より
  明確に良いときだけ採用（`CHORD_SEVEN_MARGIN=0.04`）。テンションは扱わない。
- **実装**：`detect_chords(audio, tempo)` 新設。`midi_to_musicxml` に chords 引数追加
  （music21 `harmony.ChordSymbol` を各小節先頭に挿入）。main で伴奏パートのみ付与。
  `--no-chords` で無効化可。新規依存なし（librosa・music21は既存）。
- **検証結果**：Reboundクリップで B7｜E｜Emaj7｜C#maj7｜F#sus4｜Emaj7｜C#m7｜
  F#m7｜F#m7｜Bmaj7｜Amaj7｜Esus4｜Bmaj7。Eメジャー系で音楽的に整合。
- 確認画像：`output/Yvv4RVQzIFk/_render/guitar_Lv3_chords.png`
- **注意（表示のみ）**：確認用PNG（verovio+cairosvg）はシャープ字形フォントを
  持たず、`C#maj7` が `C□Maj7` と□表示になる（テンポの♩が□になるのと同因）。
  MusicXMLデータは正しく、MuseScoreで開けば正常表示。

### アプリの本来の目的（2026-07-25 やっさんから確認）
**このアプリを作る動機＝ドラムの簡略化**。バンドのドラマーが最近の曲に多い
ダブルキック等の高難度技術を叩けず選曲を嫌がる。それを解消し「ドラムだけでも
簡潔に叩ける譜面」を出したいのが出発点。将来Webアプリ化する構想。
→ ドラム簡略化譜は"本丸"であり後回しの上乗せではない。ドラム単体音源を渡す
だけでは難易度が下がらず問題解決にならない点に注意。

### ドラム採譜PoCの結果＝素朴DIYは不可（2026-07-25）
既存 `stems/ドラム.wav`（Rebound35秒）で2手法を試した結論：**librosaの素朴な
手法ではキック/スネア/ハイハットを安定分離できない**。
- 手法1（帯域ごと独立オンセット検出）：強い一撃が全帯域に漏れ、3行がほぼ
  同一になる（＝「打点はあった」しか分からず楽器を振り分けられない）。
- 手法2（全体オンセット→打点ごとに低/中/高域エネルギー比で判定）：低域残響が
  強くほぼ全部キック判定（KK62/SN14/HH15）。閾値手調整は沼・曲依存で破綻。
- ADT（自動ドラム採譜）はMIR最難関。本丸がここなので方針決定が要る。
- **次の選択肢**：(A) NMF分解＋テンプレート（librosa内・依存増やさず正攻法）／
  (B) 専用ADTモデルを隔離venvで（精度高・環境は別プロセスで保護）／
  (C) 発想転換：原曲を厳密採譜せず、テンポに合う基本パターンを生成（＝最初から
  簡略化された叩ける譜面を作る。ADTの壁を回避し、アプリの目的と直結）。

### ドラム記譜PoC成功＋アプリ方針決定（2026-07-25）
- **ドラム記譜が描けることを実証**：music21で `clef.PercussionClef`＋`note.Unpitched`
  （displayStep/Octaveで位置指定、ハイハットは `notehead='x'`）→ MusicXML →
  verovio描画。キック下段/スネア中段/ハイハット上段×符頭の8ビートが正しく出た。
  確認画像：`output/Yvv4RVQzIFk/_render/drum_basic8.png`。最大の技術リスク解消。
- **アプリの方針決定（やっさん）**：全自動簡略化ではなく、**「自動で粗い下書きを
  出す → 人がグリッドで直す」対話型エディタ**にする。人が最後に直せる前提なので
  自動採譜（ADT）は粗くてよく、精度の壁が要求から外れる。B（専用モデル）は
  必須でなくなり、比較実験として後回し可。
- **想定アーキテクチャ（＝タスク4 Webアプリ本体）**：
  - バックエンド：今のPython（Demucs/テンポ/記譜/コード）がそのまま部品。粗い
    ドラム叩き台をグリッド（16分×KK/SN/HH）データで生成。
  - フロント：Reactでグリッド編集（升目クリックで打点ON/OFF）＋分離ドラム音源の
    再生で耳確認＋「キック間引き」等のまとめ簡略化コマンド＋verovio(WASM/または
    サーバ描画)でライブ譜面＋MusicXML/PDF書き出し。
  - 工数感：数週間規模の建て付け（平日1〜2h/休日3〜5h）。CLI資産は無駄にならない。
- **次の一手**：中核ループ（グリッド編集→ライブ譜面→音源再生）のクリック可能な
  試作を、既存Python＋verovioのサーバ往復方式でRebound素材に対して作る。
  ＝「できそう」を「触れる」に変える最小スライス。

### ドラムエディタMVP 完成（2026-07-25）
「グリッド編集→ドラム譜出力」のローカルWebエディタの核ループを実装・動作確認済み。
- gitブランチ `drum-editor-mvp`（このフォルダで `git init` 済み）。全9テスト緑。
- 設計書：`docs/2026-07-25-drum-editor-mvp-design.md`／計画：`docs/2026-07-25-drum-editor-mvp-plan.md`
- 構成：`app/grid.py`（グリッド模型・8ビート生成・grid→MusicXML）／`app/render.py`
  （MusicXML→SVG verovio）／`app/analyze.py`（テンポ・小節数・Demucs分離）／
  `app/server.py`（Flaskルート）／`app/templates`・`app/static`（UI）／`run_editor.py`（起動）
- **起動手順**：`./venv/bin/python run_editor.py <音源ファイル>` → http://127.0.0.1:5000
  - 分離済みドラムWAVがあれば `EDITOR_STEM=<wav> ./venv/bin/python run_editor.py <音源>`
    でDemucsを飛ばして即起動できる。
- 動作確認：基本8ビート表示／升目クリックで打点トグル／「譜面にする」でドラム譜描画
  （編集が譜面に反映）／ドラム音源再生（/stem 200）／MusicXML書き出し。
- 割り切り（設計どおり）：16分固定・ドラムのみ編集・出発点はテンプレート・描画はサーバ往復。
- 次段（未着手）：自動採譜下書き／まとめ簡略化コマンド／全パートScore統合／PDF／アップロードUI。

### 全パートScore統合 完成（2026-07-25）
各パートを1枚のバンド譜（上→下：ボーカル/ギター/ベース/ドラム）に統合。
- gitブランチ `full-score-integration`。全12テスト緑。
- 設計書：`docs/2026-07-25-full-score-integration-design.md`／計画：`...-plan.md`
- 構成：`app/score.py`（`pitched_part_from_midi`＝簡略化MIDIから段を作る／
  `build_full_score`＝段を積む・テンポは最上段に1つ／`assemble_full_score`＝
  音程3段＋ドラム段を組立／`score_to_musicxml`）＋ `score_all.py`（CLI）。
- **使い方**：`./venv/bin/python score_all.py <出力フォルダ> [--level N] [--tempo N]`
  → `<フォルダ>/score/全パート_LvN.musicxml` と `_render/full_score.svg` を出力。
- 確認：Reboundで4段（Vocal=ト音/Guitar=ト音8vb/Bass=ヘ音8vb/Drums=パーカッション）が
  小節線を揃えて縦に並ぶことを目視確認（`output/Yvv4RVQzIFk/_render/full_score.png`）。
- 割り切り：ギター/鍵盤は1段（6音源分離htdemucs_6sで別段化は後）／ドラムはテンプレ／PDFは後。
- **コード表示**：`score_all.py --audio <音源>` で detect_chords を走らせ、ボーカル段の上に
  コードを載せる（例：B7｜E｜EMaj7｜C#Maj7｜F#sus4…）。音源未指定ならコードなし。

### PDF書き出しを実装（2026-07-26）
共有・印刷用に全パートスコアのPDF出力を追加。
- **経路**：verovioで各ページSVG化 → cairosvgでページごとにPDF化 → pypdfで結合。
  `app/render.py` に `musicxml_to_pdf(xml)->bytes` 新設（`_load_toolkit`で既存SVG関数と共通化）。
- **CLI**：`score_all.py --pdf` で `<フォルダ>/score/全パート_LvN.pdf` を出力。
- **検証**：Rebound Lv3 で3ページA4のPDF生成を確認。4段（Vocal/Guitar/Bass/Drums）が
  正しく描画される（`tests/` に単ページ・複数ページの2テスト追加、全15テスト緑）。
- **依存追記**：requirements.txt に verovio/cairosvg/pypdf を明記（従来は未記載だった）。
- **♩字形の□問題を解消**：以前は verovio がテンポ♩・コード♯を font-family="Leipzig" の
  `<text>` で描き、cairosvg にそのフォントが無く□になっていた。verovio同梱のLeipzig
  (base64 woff2)を ttf 化して `app/fonts/Leipzig.ttf` に同梱。`render.py` の
  `_ensure_music_font()` が初回だけユーザーフォント（mac: ~/Library/Fonts）へ入れて
  `fc-cache` する。cairosvg がフォントを引けるようになり ♩=86 と表示。生成PDFには
  Leipzig がサブセット埋め込みされるため、他PCでも♩で見える（可搬）。
  ※ ttf生成には fonttools＋brotli を使用（ttfは同梱済みなので実行時は不要）。
- gitブランチ `pdf-export`。

### ギター/鍵盤の別段化を実装（2026-07-26）
`--six`（htdemucs_6s＝6分離）で、従来1段だった「ギター・キーボード等(other)」を
**ギター/キーボード(piano)/その他(other残り)** の3段に分ける機能を追加。オプトイン。
- **パート定義を単一ソース化**：`app/parts.py` 新設（`PartSpec` に label/name/clef/keep/
  transcribe を集約）。4分離(`_FOUR_STEM`)と6分離(`_SIX_STEM`)の2テーブル。
  従来 bandcopy.py・app/score.py・score_all.py に散在していた PART_LABELS /
  KEEP_STRATEGY / CLEF_STRATEGY / NO_TRANSCRIBE / CHORD_PART / PITCHED_ORDER /
  LABEL_MAP を全廃し、ここを参照する形に統一。
- **段構成（6分離）**：Vocal(ト音) / Guitar(ト音8vb) / Keys=piano(ト音) /
  Other=残り(ト音) / Bass(ヘ音8vb) / Drums。コードは Guitar 段に載せる
  （4分離時は従来どおり other、統合スコアは従来どおりボーカル段）。
- **bandcopy.py**：`--six` 追加。`demucs_cmd()`/`default_parts()` を関数化。
  `separate_stems(…, six)` でモデルとステム名を切替。
- **score_all.py**：`resolve_parts()` 新設。midi に「ギター_LvN.mid」があれば6分離と
  自動判定し段順を組む（フラグ不要）。`assemble_full_score(…, six)`。
- **テスト**：test_parts / test_score(6段) / test_score_all(自動判定) / test_bandcopy
  を追加。全27テスト緑。
- **実機検証**：Rebound35秒で `bandcopy.py --six` を通し、htdemucs_6s が
  guitar/piano/other を別ステム出力→5パート採譜→6段スコアを描画（段数6・段順・
  音部記号・コード・♩=86 を目視確認）。Other段は残りシンセで密＝簡略化レベルの領域。
- 割り切り：piano は単段（グランドスタッフ化はしない）。分離品質・空段リスクは
  オプトインで受容。gitブランチ `six-stem-guitar-piano`。

### ドラム簡略化コマンドを実装（2026-07-26）＝本丸の第一歩
エディタに「叩けない難所を軽くする」個別ボタンを追加。ドラマーが打ち込んだ／
下書きした忙しい譜面を軽くする編集ヘルパー。
- **中核ロジック**：`app/drum_simplify.py` 新設（純関数・グリッド→新グリッド、元は非破壊）。
  - `thin_kicks`＝キック間引き：**連続した打点の塊を先頭1発にまとめる**（[1,1,1]→[1,0,0]）。
    16分連打・ダブルキックを単発化＝本丸ど真ん中。単発キックは保持。
  - `thin_hihat`＝ハイハットを軽く：今の細かさを見て**1段階粗く**（16分→8分→4分）。
    押すたびに一段軽くなる。
- **サーバ**：`POST /simplify`（body `{command, grid}`）→ 変換後グリッドをJSONで返す。
  `app/server.py` の `SIMPLIFY_COMMANDS` に登録。不明コマンドは400。
- **エディタUI**：ボタン「キック間引き」「ハイハットを軽く」「↩元に戻す」を追加。
  コマンド→サーバ変換→グリッド差し替え→譜面自動再描画。元に戻すは履歴スタック
  （コマンド前を積む・空なら無効）。
- **run_editor.py**：`PORT` 環境変数対応（既定5000）。※このMacは5000をControlCenterが
  使用中のため、`PORT=5050 ./venv/bin/python run_editor.py <音源>` 推奨。
  `EDITOR_STEM=<ドラムwav>` でDemucsを飛ばして即起動。
- **テスト**：test_drum_simplify（10本：連打→単発/単発保持/複数塊/他レーン不変/非破壊、
  16→8→4分の各段/非破壊）＋ /simplify ルート3本。全40緑。
- **実機検証**：ブラウザで「ハイハットを軽く」（8分→4分・譜面自動再描画）、「元に戻す」
  （復元・ボタン有効/無効）、「キック間引き」ボタン発火（コンソールエラー無し）を確認。
  HTTPでも連打→単発化・8分→4分・不明→400 を確認。
- 割り切り：CLIパイプライン非接続（実ドラム簡略化はADT前提のためv1はエディタ内のみ。
  純関数なので将来CLIから再利用可）。キック間引きは連続ステップの塊が対象。
- gitブランチ `drum-simplify-commands`。

### エディタ→スコア連携を実装（2026-07-26）
エディタで編集したドラムを統合スコア(score_all)に反映（自動拾い方式・一方向）。
- **保存（エディタ側）**：ボタン「スコア用に保存」→ `POST /save-grid` →
  `output/<音源stem>/drum_grid.json` に書き出し（保存先は `run_editor.py` が音源名から算出）。
  保存後に画面へ保存先を表示。保存先未設定なら400。
- **自動拾い（score_all）**：`resolve_drum_grid()` 新設。`<出力フォルダ>/drum_grid.json`
  （または `--drum-grid <path>`）があればドラム段にそれを使い、無ければ従来テンプレ。
  出力に「ドラム:編集グリッド／テンプレート」を表示。
- **整合**：`app/grid.py` に `fit_grid_to_bars(grid, bars)` 追加。保存グリッドをスコアの
  小節数に合わせ切り詰め／空小節パディング。テンポはスコアの単一テンポ。段が縦に揃う。
- **テスト**：fit_grid_to_bars 4本／/save-grid 2本／resolve_drum_grid 3本。全49緑。
- **実機検証**：エディタで「ハイハットを軽く」→「スコア用に保存」→ drum_grid.json に
  HH4分が保存 → score_all が「ドラム:編集グリッド」で自動拾い → 統合スコアの
  ドラム段が8分→4分に（他パートは不変）を before/after 描画で確認。
- 割り切り：一方向（エディタ→スコア）。保存は明示ボタン。
- gitブランチ `editor-score-link`。

### タブ譜出力を実装（2026-07-26）
ギター・ベースの弦/フレット表記（タブ譜）を出力。**PyGuitarProは不要**で、
verovioがMusicXMLのタブ（TAB音部記号＋technical string/fret）を描けるため既存
パイプラインに新規依存ゼロで乗せた。
- **中核（`app/tab.py`）**：`TUNINGS`（guitar=EADGBE/bass=EADG、弦番号→開放MIDI）。
  運指heuristic＝`choose_fingering`（低フレット優先＋直前位置の近く・音域外はオクターブ補正）、
  `assign_chord`（同時音を別々の弦へ）。`midi_to_tab_musicxml` で MIDI→タブMusicXML。
- **和音の要注意点**：music21の和音→タブ書き出しは複数和音で崩れる（string/fretを1音符に
  詰め込み、verovioが -2147483647 を描く）。→ `chordify()`で単一声部化＋**MusicXMLを自前生成**
  （music21のduration.type等は流用）して回避。maxs(technical内string数)=1で分配を確認。
- **CLI（`tab.py`）**：`./venv/bin/python tab.py <出力フォルダ> [--level N] [--pdf]`。
  ベース（ベース_LvN.mid）とギター（6分離ギター_LvN.mid を優先、無ければ4分離
  ギター・キーボード等）を検出し、`<フォルダ>/tab/<ラベル>_tab_LvN.musicxml` ＋
  `_render/<ラベル>_tab.svg`（--pdfでPDF）を出力。ピアノ/その他はタブ対象外。
- **テスト**：運指/和音/midi_to_tab/CLI検出 で14本。全63緑。
- **実機検証**：Rebound Lv3 で bass=4線タブ・guitar=6線タブ（和音は縦積みフレット）を描画。
  パート名Bass/Guitar・-2147483647なし。
- 既知：4分離の混在「ギター・キーボード等」は音域が広く高フレット(20超)が散見。6分離の
  クリーンなギターならより素直。運指は最適保証なしのheuristic（人が2割直す前提）。奏法記号なし。
- gitブランチ `tab-output`。

### Web公開化（Colab＋Gradio）を実装（2026-07-26）
非エンジニアが「音源アップロード→ボタン→楽譜/タブ/音源をDL」で使えるWeb UI。
段階A（各自が自分のColab無料GPUで自分の音源を処理）＝現方針「個人練習・手持ち音源」
の権利姿勢そのまま・固定費0・あなたのサーバに他人の音源を載せない。
- **パイプライン関数化**：`bandcopy.py` に `run_pipeline(audio, out_root, level, six...)` を
  抽出（main と webapp が共用）。`score_all.py` に `build_full_score_musicxml(root, level...)`
  を抽出（同上）。CLIの挙動は不変（回帰確認済み）。
- **Gradio UI（`app/webapp.py`）**：`build_ui()` が Blocks を返す。音源＋難易度＋6分離
  →`run_pipeline`→バンド譜PDF＋ギター/ベースのタブPDF＋分離音源zip＋プレビュー画像。
  `_zip_dir` で stems を zip 化。
- **起動**：ローカル `./venv/bin/python webapp.py`（http://127.0.0.1:7860）。
  Colab は `bandcopy_colab.ipynb`（①clone＋pip ②`build_ui().launch(share=True)`）。
  `share=True` の一時公開URLを配れば他人はColab操作なしでブラウザだけで使える
  （URLはセッション稼働中のみ）。ColabのGPUで分離は1曲1分級。
- **依存**：requirements に gradio==6.20.0 追加。
- **テスト**：_zip_dir 2本＋build_ui smoke 1本。全66緑。
- **実機検証**：`process('audio/Yvv4RVQzIFk.mp3')` 直接実行でバンド譜PDF(428KB)・
  タブ2種・分離音源zip(18.7MB)・プレビュー生成を確認。Gradio UIをローカル起動し
  フォーム描画を確認（アップロード欄・スライダー・6分離・楽譜を作るボタン）。
- **未了**：GitHub公開（Colabのclone元）。ノートの `REPO_URL` は公開時に差し替え要。
- 割り切り：認証/保存/課金なし（使い捨てColabセッション）。1曲ずつ。
- gitブランチ `web-publish`。

### GitHub公開 完了（2026-07-27）
Colabのclone元となるPublicリポジトリを公開した。
- **URL**：https://github.com/jasawsea/bandcopy （PUBLIC・ブランチ master）
- **アカウント**：GitHubユーザー名 `jasawsea`（新規作成）。認証は `gh`（GitHub CLI・brew導入）で
  `gh auth login`（ブラウザ認証）→ `gh repo create bandcopy --public --source=. --push`。
- **追加ファイル**：`README.md`（概要・セットアップ・使い方・権利注意）／`LICENSE`（MIT・著作者 鴫原康）。
- **ノート差し替え**：`bandcopy_colab.ipynb` の `REPO_URL` を実URLに更新済み＝そのままclone可能。
- **公開内容の安全確認**：46ファイル・コードのみ。音源(.wav/.mp3)・output・venvは.gitignoreで除外され混入なし。
  コミット著者は実名「鴫原康」（本人がリスク承知で実名公開を選択）。メールはローカル名で漏れなし。
- 今後の更新は `git add → commit → git push`（認証はkeyring保存済みトークンで自動）。

### 現在の中断ポイント（2026-07-27 更新・新チャット引き継ぎ用）
すべて `master` にマージ済み・**全66テスト緑**・ワーキングツリークリーン。検証素材は
`audio/Yvv4RVQzIFk.mp3`（Josh Woodward「Rebound」相当・CC-BY・35秒）。

**7/26に7本完了（詳細は上の各セクション）**
1. PDF書き出し（＋テンポ♩字形の□解消・Leipzigフォント同梱）
2. ギター/鍵盤の別段化（`--six`＝htdemucs_6s）＋パート定義を `app/parts.py` に単一ソース化
3. ドラム簡略化コマンド（キック間引き・ハイハットを軽く・元に戻す）＝エディタ内
4. 未追跡コアファイルの追跡整理（.gitignore に .DS_Store/audio/*.wav 追加）
5. エディタ→スコア連携（「スコア用に保存」→ drum_grid.json → score_all 自動拾い）
6. タブ譜出力（`tab.py`＝ギター/ベース、MusicXML→verovio。PyGuitarPro不要）
7. Web公開化（Colab＋Gradio。`webapp.py`ローカル／`bandcopy_colab.ipynb`）

**主なコマンド（現状）**
- CLI一括：`./venv/bin/python bandcopy.py <音源> --level 3 [--six]`（run_pipeline）
- 統合スコア：`./venv/bin/python score_all.py <出力フォルダ> --audio <音源> [--pdf]`
- タブ譜：`./venv/bin/python tab.py <出力フォルダ> --level 3 [--pdf]`
- ドラムエディタ：`PORT=5050 EDITOR_STEM=<ドラムwav> ./venv/bin/python run_editor.py <音源>`
- Web UI（ローカル）：`./venv/bin/python webapp.py` → http://127.0.0.1:7860

**未了・次の一手**
- ~~GitHub公開~~ → **完了**（2026-07-27・上記セクション参照。https://github.com/jasawsea/bandcopy ）。
- **ADT（自動ドラム採譜）＝着手中**。設計フェーズ完了、実装は次回（2026-07-29 水の夜に再開予定）。詳細は下の「ADT A1 再開ポイント」参照。
- **自動ドラム採譜(ADT)＝最後の大物**：素朴DIYは不可を確認済み（NMF分解 or 専用モデルを
  隔離venvで）。これが入ると「自動下書き→エディタで直す→スコア反映」の本命ループが完成。
  ドラム簡略化コマンド(#3)・エディタ→スコア連携(#5)は既に整備済みなので、ADTの下書きが
  刺されば直結する。

**既知の限界（引き継ぎ注意）**
- フル尺・多数の実曲での検証はまだ（35秒クリップ中心）。
- タブの運指は heuristic（最適保証なし）。4分離の混在ギターは高フレットが散見。
- 採譜精度7〜8割前提（AIが8割・人が2割直す設計）。

### ADT A1 ＋ タム3レーン 実装完了（2026-07-29）
自動ドラム採譜（A1）とタム3レーン(HT/MT/FT)を実装・実機評価・チューニングまで完了。
gitブランチ `drum-adt-a1`（全82テスト緑）。superpowers subagent-driven-developmentで実行。
- **設計書** `docs/2026-07-27-drum-adt-a1-design.md` ／ **計画** `docs/2026-07-29-drum-adt-a1-plan.md`
- **実装**：①`app/drum_transcribe.py`新設（NMF＋固定テンプレでKK/SN/HH採譜。純関数：quantize/
  remove_ghost/infer_hihat_subdivision/fill_regular_hihat/high_freq_fraction/resolve_hihat_subdivision）
  ②`app/analyze.py`に`transcribe_drum_from_audio` ③`app/server.py`に`POST /auto-draft`（分離済み
  stem優先でDemucs回避、失敗は400＋日本語）④エディタ6レーン表示・日本語ラベル・「自動下書き」ボタン
  （非破壊・履歴スタック）⑤`app/grid.py`にタム3レーン（記譜位置 HT=E5/MT=D5/FT=A4、grid_to_scoreは
  レーン欠けに寛容）。
- **タムは表現のみ**（人が手入力）。ADTの自動検出はKK/SN/HHの3レーンだけ。
- **実機評価（Rebound・チューニング後）**：SN 4.5→2.4/小節（過検出解消）、HH 空→8分復活、
  KK 4.8/小節（実キック活動・「キック間引き」で調整可）、タム空。**やっさん判断＝A1採用**（A2は保留）。
- **A1の限界（記録）**：HHはオンセット検出ではNMFでスネア高域に吸われ拾えない→高域エネルギーの
  有無で8分を既定に敷くフォールバックで対処。パラメータは曲ごとにばらつく（別曲yHMozkは打点が疎）。
  精度をさらに上げるならA2（専用ADTモデルを隔離venv）。
- **UI検証**：6レーン表示・自動下書き200・非破壊undo をブラウザ確認。※譜面描画はpreview起動の
  sandbox下でのみverovioリソース不可で空表示だったが、通常起動はPythonで945px確認済み（コード不具合
  ではない）。
- **追跡課題（follow-up・merge非ブロッカー）**：test_grid.pyのinline import／Task2ヘルパの境界テスト薄い
  ／librosaの重複import／pytest 3警告（既存ライブラリのDeprecation）／audio-only分岐(`transcribe_drum_from_audio`)
  未テスト／`infer_hihat_subdivision`と`resolve_hihat_subdivision`の未使用引数`bar_sec`。

<details><summary>旧・再開ポイント（設計フェーズ時点のメモ）</summary>

自動ドラム採譜の**設計フェーズまで完了**。次回は「設計書レビュー→実装計画→実装」から。
- **設計書**：`docs/2026-07-27-drum-adt-a1-design.md`（コミット済み b4a7c27）。superpowers brainstormingで作成。
- **決定事項（やっさん承認済み）**：
  - スコープ **A**＝グルーヴの土台だけ（KK/SNの骨格＋HHの粗さ8分/16分）。フィル・食いは狙わない。
  - 手法 **A1**＝依存ゼロ（librosa/numpy内のNMF＋固定ドラムテンプレートでKK/SN/HH分離）。
    素朴なスペクトル/帯域しきい値は既に失敗済み（本ファイル上部PoC参照）なのでNMF方式。
  - 発動 **1**＝エディタのボタン「自動下書き（音源から）」。非破壊（既存の履歴スタックに乗る）。
  - **段階戦略**：まずA1を作りRebound素材で評価→明らかに力不足ならA2（専用ADTモデル）に上げる判断。
  - CLIパイプライン接続は今回やらない（YAGNI・純関数なので後付け可）。
- **実装ユニット（設計書に詳細）**：①`app/drum_transcribe.py`新規（中核・純関数寄り
  `transcribe_drums(drum_wav, tempo, bars)->grid`）②`app/analyze.py`に`transcribe_drum_from_audio`
  ③`app/server.py`に`POST /auto-draft`④エディタUIにボタン＋ローディング。
- **評価用キャッシュ**：`output/Yvv4RVQzIFk/stems/ドラム.wav`（Rebound）が既にあるのでDemucs待ち不要。
- **次の具体アクション**：設計書をやっさんがレビュー→OKなら writing-plans スキルで実装計画→実装。
- **未pushの注意**：この時点のCLAUDE.md更新・設計書コミットはローカルのみ（公開リポジトリには
  未反映）。必要なら `git push`。

</details>
