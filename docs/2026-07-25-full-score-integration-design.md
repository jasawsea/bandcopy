# 全パートScore統合 設計書

作成日：2026-07-25

## 背景・目的

各パート（ベース・ギター/鍵盤・ボーカル・ドラム）を個別の楽譜として出せる状態になった。
これらを**1枚の普通のスコア譜**（全パートが上から縦に並び、最下段にドラム）に束ねる。

## スコープ

### やること
- 既存の各パートを1枚のスコアに統合する。
- 上から下の並び順：**ボーカル → ギター/鍵盤 → ベース → ドラム（最下段）**。
- 全段で小節・テンポ・拍子（4/4）を揃える。
- コードはボーカル段の上に表示（一般的なバンド譜と同じ）。
- 出力：統合スコアのMusicXML＋確認用のSVG/PNG。

### やらないこと（後回し）
- ギター/鍵盤/シンセの分離（現状Demucsは4パート分離。ギター・鍵盤・シンセは
  「その他」1段にまとまる。6音源モデル htdemucs_6s での分離は後の拡張）。
- PDF書き出し（まずMusicXML）。
- エディタUIへの「全パートScore」ボタン組み込み（まずは関数＋実行スクリプトで実証）。
- ドラムのエディタ編集内容との連携（当面はテンプレート／保存グリッドを使う）。

## アーキテクチャ

### 新モジュール `app/score.py`
- `build_full_score(parts: list, tempo: float) -> music21.stream.Score`
  - `parts`：**音部記号・楽器名を設定済みの `music21.stream.Part` のリスト**。
    渡された順に上から段として積む。先頭段にテンポと拍子（4/4）を置く。
  - 段の準備は呼び出し側が下記ヘルパで行う（build_full_score は積むだけ）。
- `pitched_part_from_midi(midi_path: str, clef_type: str, name: str) -> music21.stream.Part`
  - 簡略化MIDIを music21 Part に読み込み、音部記号・楽器名を設定して返す。
    （既存 `bandcopy.midi_to_musicxml` の音部記号設定ロジックと同じ方針）
- ドラム段は既存 `app.grid.grid_to_score(grid)` が返す Score から Part を取り出して使う。

### 段ごとの音部記号・楽器名（既存 `CLEF_STRATEGY` と一致）
| 段 | 音部記号 | 楽器名 |
|---|---|---|
| ボーカル | ト音（treble） | Vocal |
| ギター/鍵盤 | ト音8vb（treble8vb） | Guitar |
| ベース | ヘ音8vb（bass8vb） | Bass |
| ドラム | パーカッション | Drums |

### 実行スクリプト `score_all.py`
- 使い方：`./venv/bin/python score_all.py <出力フォルダ> [--tempo N]`
- 既存の簡略化MIDI（`<フォルダ>/midi/ベース_Lv*.mid` 等）とテンプレドラムグリッドから
  `build_full_score` を呼び、統合スコアの MusicXML と SVG を書き出す。

### 描画・書き出し
- 描画は既存 `app.render.musicxml_to_svg`（verovioは多段譜をそのまま描画）。
- MusicXML書き出しは music21 の標準機能。

## データフロー

```
既存の簡略化MIDI（ベース/ギター/ボーカル）＋ ドラムグリッド
  → pitched_part_from_midi ×3 ＋ grid_to_score のドラムPart
  → build_full_score（順に段を積む・音部記号/楽器名/テンポ/拍子を設定）
  → music21 Score
  → MusicXML書き出し ＋ verovioでSVG描画
```

## コード付与

コードはボーカル段（最上段）の先頭小節群に `harmony.ChordSymbol` を挿入する。
既存 `bandcopy.detect_chords(audio, tempo)` の結果を流用（音源があれば）。
音源が渡されない場合はコードなしで組む。

## エラー処理

- 一部パートのMIDIが欠けている → そのパートは段を省いて残りで組む（全滅時のみエラー）。
- パートごとに小節数が食い違う → 最大小節数に合わせ、短い段は空小節（休符）で埋める。
- テンポ未指定 → 既存の簡略化MIDIに埋め込まれたテンポを使う（なければ120）。

## テスト

- `build_full_score` が、渡した順どおりの段数・並びのScoreを返すこと。
- 各段の音部記号が仕様どおり（Vocal=treble / Guitar=treble8vb / Bass=bass8vb /
  Drums=percussion）であること。
- 統合MusicXMLに `<part-list>` が段数ぶんの `<score-part>` を持つこと。
- 素材は既存Rebound（`output/Yvv4RVQzIFk/`）。

## 将来の拡張（本設計の外）

- htdemucs_6s でギター/ピアノを分離し、段を追加（`build_full_score` に渡す段を足すだけ）。
- エディタに「全パートScore」ボタン（編集ドラムを反映した統合スコア）。
- PDF書き出し。
