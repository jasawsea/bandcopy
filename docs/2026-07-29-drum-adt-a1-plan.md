# ドラム自動採譜(ADT) A1 ＋ タム3レーン 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ドラム音源からKK/SN/HHのグルーヴ骨格を自動採譜してエディタに下書きとして読み込み、加えてタム3レーン(HT/MT/FT)を手入力できるようにする。

**Architecture:** 中核は `app/drum_transcribe.py`（音源＋tempo＋bars→6レーングリッド、依存はnumpy/librosaのみ）。KK/SNは固定スペクトルテンプレートWを基底にしたNMF（numpy乗算更新）でオンセット抽出→16分量子化。HHは密度から8分/16分を判定し規則パターンを敷く。タムは全0で出力し人がエディタで足す。Flaskの `/auto-draft` が既存の分離済みドラム音源とテンプレグリッドのtempo/barsを使って中核を呼ぶ。

**Tech Stack:** Python 3.12 / numpy 1.26 / librosa 0.11 / soundfile / Flask / music21 / pytest。フロントは素のJS。

## Global Constraints

- **新規依存を追加しない**（numpy/scipy/librosa/soundfile/music21/Flask は既存venvに在り）。
- **Python 3.10〜3.12**（basic-pitchが3.13未対応）。
- グリッド模型は `{"tempo","bars","steps_per_bar":16,"lanes":{...}}`。レーンは6本 `HH/HT/MT/FT/SN/KK`、各レーンはステップごとの 0/1 リスト。
- ADTが自動で埋めるのは **KK/SN/HH の3レーンのみ**。**タム(HT/MT/FT)は常に全0**（人が手入力）。
- 差し替えは常に非破壊（エディタの履歴スタック経由）。
- コミット著者は既存に合わせる：`git -c user.name="鴫原康" -c user.email="shigiharayasushi@shigiharayasushinoMacBook-Air.local" commit ...`。
- テスト実行は `./venv/bin/python -m pytest`。全既存66テストは緑を維持。
- 純関数の断定テストのみ書く。採譜の当たり外れ自体はテストで縛らない（実機評価で判断）。

---

### Task 1: タム3レーンをグリッド模型に追加（grid.py）

**Files:**
- Modify: `app/grid.py`（`make_template_grid` / `LANE_NOTATION` / `grid_to_score`）
- Test: `tests/test_grid.py`

**Interfaces:**
- Consumes: なし（既存 music21）
- Produces:
  - `make_template_grid(tempo, bars, steps_per_bar=16) -> dict`（`lanes` に `HH,HT,MT,FT,SN,KK` の6キー。HT/MT/FT は全0）
  - `LANE_NOTATION`：6キーの辞書 `{lane: (displayStep, displayOctave, notehead)}`
  - `grid_to_score(grid) -> music21.stream.Score`（`grid["lanes"]` にキーが欠けても KeyError しない）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_grid.py` の末尾に追記：

```python
from app.grid import make_template_grid, LANE_NOTATION, grid_to_musicxml


def test_template_has_six_lanes_with_empty_toms():
    g = make_template_grid(120.0, 2)
    assert set(g["lanes"].keys()) == {"HH", "HT", "MT", "FT", "SN", "KK"}
    for lane in ("HT", "MT", "FT"):
        assert g["lanes"][lane] == [0] * 32          # 2小節*16、タムは空


def test_lane_notation_has_tom_positions():
    assert LANE_NOTATION["HT"] == ("E", 5, None)
    assert LANE_NOTATION["MT"] == ("D", 5, None)
    assert LANE_NOTATION["FT"] == ("A", 4, None)


def test_grid_to_score_renders_tom_hit():
    g = make_template_grid(120.0, 1)
    g["lanes"]["FT"][0] = 1                            # フロアタムを1発置く
    xml = grid_to_musicxml(g)
    assert "unpitched" in xml.lower()                 # 打点が書き出される
    assert "<display-step>A</display-step>" in xml    # フロアタムの位置


def test_grid_to_score_tolerates_missing_lane():
    g = make_template_grid(120.0, 1)
    del g["lanes"]["HT"]                               # レーン欠けでも落ちない
    grid_to_musicxml(g)                               # 例外が出なければ合格
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_grid.py -q`
Expected: FAIL（`test_template_has_six_lanes...` で KeyError/AssertionError、`test_grid_to_score_tolerates_missing_lane` で KeyError）

- [ ] **Step 3: 実装**

`app/grid.py` の `make_template_grid` の `return` を差し替え（タム3本を全0で追加）：

```python
    n = bars * steps_per_bar
    return {
        "tempo": tempo,
        "bars": bars,
        "steps_per_bar": steps_per_bar,
        "lanes": {
            "HH": hh,
            "HT": [0] * n,   # ハイタム（人が手入力）
            "MT": [0] * n,   # ミッドタム
            "FT": [0] * n,   # フロアタム
            "SN": sn,
            "KK": kk,
        },
    }
```

`LANE_NOTATION` を6本に差し替え（上から音の高い順）：

```python
# レーンごとの記譜位置（displayStep, displayOctave, notehead）
LANE_NOTATION = {
    "HH": ("G", 5, "x"),    # ハイハット：上第1線上・×符頭
    "HT": ("E", 5, None),   # ハイタム：第4間
    "MT": ("D", 5, None),   # ミッドタム：第4線
    "SN": ("C", 5, None),   # スネア：第3間
    "FT": ("A", 4, None),   # フロアタム：第2間
    "KK": ("F", 4, None),   # キック：下第1間
}
```

`grid_to_score` のレーン取得をレーン欠けに寛容化（`grid["lanes"][lane]` → `.get`）：

```python
        for lane, (dstep, doct, head) in LANE_NOTATION.items():
            arr = grid["lanes"].get(lane)
            if not arr:
                continue
            v = stream.Voice()
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_grid.py -q`
Expected: PASS（既存 test_grid も含め全緑）

- [ ] **Step 5: コミット**

```bash
git add app/grid.py tests/test_grid.py
git -c user.name="鴫原康" -c user.email="shigiharayasushi@shigiharayasushinoMacBook-Air.local" commit -m "feat(grid): タム3レーン(HT/MT/FT)を追加、grid_to_scoreをレーン欠けに寛容化"
```

---

### Task 2: ADT純関数ヘルパー（drum_transcribe.py）

**Files:**
- Create: `app/drum_transcribe.py`
- Test: `tests/test_drum_transcribe.py`

**Interfaces:**
- Produces:
  - `quantize_onsets_to_grid(onset_times: list[float], step_times: list[float]) -> list[int]`（各オンセットを最近傍ステップに吸着、昇順ユニークなインデックス）
  - `remove_ghost(peak_indices: list[int], strengths: list[float], threshold: float) -> list[int]`（strength >= threshold の peak だけ残す）
  - `infer_hihat_subdivision(hh_onset_times: list[float], bars: int, bar_sec: float) -> int | None`（16 / 8 / None）
  - `fill_regular_hihat(subdivision: int | None, bars: int, steps_per_bar: int = 16) -> list[int]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_drum_transcribe.py`：

```python
from app.drum_transcribe import (
    quantize_onsets_to_grid,
    remove_ghost,
    infer_hihat_subdivision,
    fill_regular_hihat,
)


def test_quantize_snaps_to_nearest_step():
    step_times = [i * 0.25 for i in range(8)]      # 0,0.25,...,1.75
    onsets = [0.02, 0.26, 0.70]                    # →0, 1, 3(0.75に近い)
    assert quantize_onsets_to_grid(onsets, step_times) == [0, 1, 3]


def test_quantize_dedupes_same_step():
    step_times = [0.0, 0.25, 0.5]
    assert quantize_onsets_to_grid([0.01, 0.02], step_times) == [0]


def test_remove_ghost_drops_below_threshold():
    peaks = [0, 4, 8]
    strengths = [1.0, 0.1, 0.8]
    assert remove_ghost(peaks, strengths, 0.5) == [0, 8]


def test_infer_hihat_subdivision():
    bar_sec = 2.0                                  # 120BPM・4拍
    # 16分＝1小節16打点
    sixteenths = [i * bar_sec / 16 for i in range(16)]
    assert infer_hihat_subdivision(sixteenths, 1, bar_sec) == 16
    # 8分＝1小節8打点
    eighths = [i * bar_sec / 8 for i in range(8)]
    assert infer_hihat_subdivision(eighths, 1, bar_sec) == 8
    # ほぼ無音
    assert infer_hihat_subdivision([], 1, bar_sec) is None


def test_fill_regular_hihat():
    assert fill_regular_hihat(8, 1) == [1 if s % 2 == 0 else 0 for s in range(16)]
    assert fill_regular_hihat(16, 1) == [1] * 16
    assert fill_regular_hihat(None, 2) == [0] * 32
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_drum_transcribe.py -q`
Expected: FAIL（`ModuleNotFoundError: app.drum_transcribe`）

- [ ] **Step 3: 実装**

`app/drum_transcribe.py`（ヘルパー部分）：

```python
"""ドラム音源 → グリッドの自動下書き（A1: 依存ゼロNMF）。

KK/SN/HH の3レーンだけ自動で埋める。タム(HT/MT/FT)は全0で返し人が手入力する。
"""
import numpy as np


def quantize_onsets_to_grid(onset_times, step_times):
    """各オンセット時刻を最近傍のグリッドステップに吸着し、昇順ユニークなインデックスを返す。"""
    steps = np.asarray(step_times, dtype=float)
    idxs = set()
    for t in onset_times:
        idxs.add(int(np.argmin(np.abs(steps - t))))
    return sorted(idxs)


def remove_ghost(peak_indices, strengths, threshold):
    """strength が threshold 未満の peak を除去する（装飾音・にじみ対策）。"""
    return [p for p, s in zip(peak_indices, strengths) if s >= threshold]


def infer_hihat_subdivision(hh_onset_times, bars, bar_sec):
    """ハイハットのオンセット密度から、優勢な刻みを 16 / 8 / None で返す。"""
    if not hh_onset_times or bars <= 0:
        return None
    per_bar = len(hh_onset_times) / bars
    if per_bar >= 12:      # 16分寄り（16打点の75%以上）
        return 16
    if per_bar >= 5:       # 8分寄り（8打点の60%以上）
        return 8
    return None


def fill_regular_hihat(subdivision, bars, steps_per_bar=16):
    """判定した刻みで全小節に規則パターンを敷く。8分=2ステップおき、16分=毎ステップ。"""
    n = bars * steps_per_bar
    if subdivision == 16:
        return [1] * n
    if subdivision == 8:
        return [1 if s % 2 == 0 else 0 for s in range(n)]
    return [0] * n
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_drum_transcribe.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/drum_transcribe.py tests/test_drum_transcribe.py
git -c user.name="鴫原康" -c user.email="shigiharayasushi@shigiharayasushinoMacBook-Air.local" commit -m "feat(adt): 純関数ヘルパー(量子化/ゴースト除去/HH刻み判定/HH規則化)"
```

---

### Task 3: NMFテンプレートと transcribe_drums 本体（drum_transcribe.py）

**Files:**
- Modify: `app/drum_transcribe.py`（`build_drum_templates` / `nmf_activations` / `transcribe_drums` を追記）
- Test: `tests/test_drum_transcribe.py`（合成ドラム音源での形状テストを追記）

**Interfaces:**
- Consumes: Task2 の `quantize_onsets_to_grid` / `remove_ghost` / `infer_hihat_subdivision` / `fill_regular_hihat`
- Produces:
  - `build_drum_templates(sr: int, n_fft: int) -> np.ndarray`（形 `(n_fft//2+1, 3)`、列は KK/SN/HH の非負テンプレート）
  - `nmf_activations(V: np.ndarray, W: np.ndarray, iters: int = 50) -> np.ndarray`（形 `(3, n_frames)`）
  - `transcribe_drums(drum_wav_path: str, tempo: float, bars: int, steps_per_bar: int = 16) -> dict`（6レーングリッド。HT/MT/FT は全0）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_drum_transcribe.py` に追記（合成音源は soundfile で一時ファイルに書く）：

```python
import numpy as np
import soundfile as sf
from app.drum_transcribe import build_drum_templates, transcribe_drums


def test_build_drum_templates_shape_and_bands():
    sr, n_fft = 22050, 1024
    W = build_drum_templates(sr, n_fft)
    assert W.shape == (n_fft // 2 + 1, 3)
    assert (W >= 0).all()
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    # KK列は低域が最大、HH列は高域が最大
    assert freqs[np.argmax(W[:, 0])] < 200
    assert freqs[np.argmax(W[:, 2])] > 4000


def _write_synth_drums(path, sr=22050, tempo=120.0, bars=2):
    """低域サム(4分)＋高域チッ(8分)の合成ドラム。KK/HHが立つはず。"""
    bar_sec = 4 * 60.0 / tempo
    dur = bar_sec * bars
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    x = np.zeros_like(t)
    # キック：各拍（4分）に低域60Hzの短い減衰音
    for b in range(bars):
        for beat in range(4):
            t0 = b * bar_sec + beat * (bar_sec / 4)
            i0 = int(t0 * sr)
            env = np.exp(-np.linspace(0, 30, int(0.08 * sr)))
            seg = np.sin(2 * np.pi * 60 * np.arange(len(env)) / sr) * env
            x[i0:i0 + len(seg)] += seg[:len(x) - i0]
    # ハイハット：8分ごとに高域ノイズの短い音
    for b in range(bars):
        for e in range(8):
            t0 = b * bar_sec + e * (bar_sec / 8)
            i0 = int(t0 * sr)
            env = np.exp(-np.linspace(0, 60, int(0.03 * sr)))
            noise = np.random.RandomState(0).randn(len(env)) * env * 0.3
            x[i0:i0 + len(noise)] += noise[:len(x) - i0]
    sf.write(path, x.astype(np.float32), sr)


def test_transcribe_drums_shape_and_empty_toms(tmp_path):
    wav = tmp_path / "synth.wav"
    _write_synth_drums(str(wav))
    grid = transcribe_drums(str(wav), tempo=120.0, bars=2)
    assert set(grid["lanes"].keys()) == {"HH", "HT", "MT", "FT", "SN", "KK"}
    for lane in grid["lanes"].values():
        assert len(lane) == 32                       # 2小節*16
        assert set(lane) <= {0, 1}
    for tom in ("HT", "MT", "FT"):
        assert grid["lanes"][tom] == [0] * 32        # タムは常に空
    assert sum(grid["lanes"]["KK"]) > 0              # 低域サムはキックとして拾える
    assert grid["bars"] == 2 and grid["steps_per_bar"] == 16
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_drum_transcribe.py -q`
Expected: FAIL（`ImportError: build_drum_templates` 等）

- [ ] **Step 3: 実装**

`app/drum_transcribe.py` に追記：

```python
def _band(freqs, lo, hi, floor=0.01):
    """[lo,hi]Hz を 1.0、外を floor にした非負の帯域ベクトル。"""
    v = np.full(freqs.shape, floor, dtype=float)
    v[(freqs >= lo) & (freqs <= hi)] = 1.0
    return v


def build_drum_templates(sr, n_fft):
    """KK/SN/HH の固定スペクトルテンプレート W（列＝各成分）を作る。"""
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    kk = _band(freqs, 30, 120)                       # キック：低域
    sn = _band(freqs, 150, 400) + 0.5 * _band(freqs, 2000, 8000)  # スネア：胴＋ノイズ
    hh = _band(freqs, 6000, sr / 2)                  # ハイハット：高域
    W = np.stack([kk, sn, hh], axis=1)
    W /= (W.sum(axis=0, keepdims=True) + 1e-9)       # 列を正規化
    return W


def nmf_activations(V, W, iters=50):
    """W を固定して活性 H のみを乗算更新で推定する（教師ありNMF）。"""
    eps = 1e-9
    H = np.full((W.shape[1], V.shape[1]), V.mean() + eps)
    Wt = W.T
    WtW = Wt @ W
    for _ in range(iters):
        H *= (Wt @ V) / (WtW @ H + eps)
    return H


def _onsets_from_activation(env, sr, hop, threshold_ratio=0.3):
    """1成分の活性エンベロープからオンセット時刻と強度を返す。"""
    import librosa
    if env.max() <= 0:
        return [], []
    norm = env / env.max()
    peaks = librosa.util.peak_pick(
        norm, pre_max=2, post_max=2, pre_avg=3, post_avg=3, delta=0.05, wait=2
    )
    peaks = [int(p) for p in peaks if norm[p] >= threshold_ratio]
    times = [p * hop / sr for p in peaks]
    strengths = [float(norm[p]) for p in peaks]
    return times, strengths


def transcribe_drums(drum_wav_path, tempo, bars, steps_per_bar=16):
    """ドラム音源からKK/SN/HHを自動採譜した6レーングリッドを返す。タムは全0。"""
    import librosa

    n_fft, hop = 1024, 256
    y, sr = librosa.load(drum_wav_path, sr=None, mono=True)
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    W = build_drum_templates(sr, n_fft)
    H = nmf_activations(S, W)

    n = bars * steps_per_bar
    bar_sec = 4 * 60.0 / tempo
    step_sec = bar_sec / steps_per_bar
    step_times = [s * step_sec for s in range(n)]

    lanes = {lane: [0] * n for lane in ("HH", "HT", "MT", "FT", "SN", "KK")}

    # KK=行0, SN=行1 はオンセットを量子化して置く
    for row, lane in ((0, "KK"), (1, "SN")):
        times, strengths = _onsets_from_activation(H[row], sr, hop)
        kept = remove_ghost(list(range(len(times))), strengths, 0.3)
        times = [times[i] for i in kept]
        for idx in quantize_onsets_to_grid(times, step_times):
            if idx < n:
                lanes[lane][idx] = 1

    # HH=行2 は密度から刻みを判定して規則パターンを敷く
    hh_times, _ = _onsets_from_activation(H[2], sr, hop)
    sub = infer_hihat_subdivision(hh_times, bars, bar_sec)
    lanes["HH"] = fill_regular_hihat(sub, bars, steps_per_bar)

    return {"tempo": tempo, "bars": bars, "steps_per_bar": steps_per_bar, "lanes": lanes}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_drum_transcribe.py -q`
Expected: PASS（合成キックがKKに立ち、全レーン0/1・タム空・長さ32）

- [ ] **Step 5: コミット**

```bash
git add app/drum_transcribe.py tests/test_drum_transcribe.py
git -c user.name="鴫原康" -c user.email="shigiharayasushi@shigiharayasushinoMacBook-Air.local" commit -m "feat(adt): NMFテンプレート+transcribe_drums本体（KK/SN/HH自動、タムは空）"
```

---

### Task 4: analyze.py 配線 ＋ /auto-draft ルート（server.py）

**Files:**
- Modify: `app/analyze.py`（`transcribe_drum_from_audio` を追記）
- Modify: `app/server.py`（`/auto-draft` ルート追加）
- Modify: `run_editor.py`（state に `audio_path` を追加）
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `transcribe_drums`（Task3）、`separate_drum_stem`/`detect_tempo`/`count_bars`（既存 analyze）
- Produces:
  - `transcribe_drum_from_audio(audio_path: str) -> dict`（分離→tempo/bars→`transcribe_drums`）
  - `POST /auto-draft -> {grid}`（分離済み stem があればそれを使い Demucs を回避。無ければ audio から。stem も audio も無ければ 400）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_server.py` に追記（`transcribe_drums` をモックして Demucs/librosa を回避）：

```python
from app.server import create_app


def _client(state):
    return create_app(state).test_client()


def test_auto_draft_uses_stem_and_returns_grid(monkeypatch):
    fake = {"tempo": 120.0, "bars": 1, "steps_per_bar": 16,
            "lanes": {k: [0] * 16 for k in ("HH", "HT", "MT", "FT", "SN", "KK")}}
    fake["lanes"]["KK"][0] = 1
    called = {}

    def fake_transcribe(stem, tempo, bars, steps_per_bar=16):
        called["stem"] = stem
        called["tempo"] = tempo
        called["bars"] = bars
        return fake

    monkeypatch.setattr("app.server.transcribe_drums", fake_transcribe)
    state = {
        "grid": {"tempo": 120.0, "bars": 1, "steps_per_bar": 16, "lanes": {}},
        "stem_path": "/tmp/drums.wav",
        "audio_path": "/tmp/song.mp3",
    }
    res = _client(state).post("/auto-draft")
    assert res.status_code == 200
    assert res.get_json()["lanes"]["KK"][0] == 1
    assert called["stem"] == "/tmp/drums.wav"        # 分離済みstemを使う
    assert called["tempo"] == 120.0 and called["bars"] == 1  # テンプレのtempo/barsを再利用


def test_auto_draft_400_when_no_stem_or_audio():
    state = {"grid": {"tempo": 120.0, "bars": 1, "steps_per_bar": 16, "lanes": {}},
             "stem_path": None, "audio_path": None}
    res = _client(state).post("/auto-draft")
    assert res.status_code == 400
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `./venv/bin/python -m pytest tests/test_server.py -q`
Expected: FAIL（`/auto-draft` が404、`app.server.transcribe_drums` 属性なし）

- [ ] **Step 3: 実装**

`app/analyze.py` に追記：

```python
def transcribe_drum_from_audio(audio_path: str) -> dict:
    """音源を分離してドラムを自動採譜したグリッドを返す（分離済みstemが無いとき用）。"""
    from app.drum_transcribe import transcribe_drums
    path = Path(audio_path).expanduser().resolve()
    tempo = detect_tempo(path)
    import librosa
    dur = librosa.get_duration(path=str(path))
    bars = count_bars(dur, tempo)
    stem = separate_drum_stem(str(path), str(Path("output") / "_editor"))
    return transcribe_drums(stem, tempo, bars)
```

`app/server.py`：import に追加（先頭付近）：

```python
from pathlib import Path
from app.drum_transcribe import transcribe_drums
from app.analyze import transcribe_drum_from_audio
```

`create_app` 内、`/save-grid` の後あたりにルート追加：

```python
    @app.post("/auto-draft")
    def auto_draft():
        g = state.get("grid") or {}
        stem = state.get("stem_path")
        if stem and Path(stem).exists():
            grid = transcribe_drums(stem, g.get("tempo", 120.0), g.get("bars", 1))
        elif state.get("audio_path"):
            grid = transcribe_drum_from_audio(state["audio_path"])
        else:
            return (jsonify({"error": "ドラム音源が見つかりません"}), 400)
        return jsonify(grid)
```

`run_editor.py`：`create_app({...})` に `audio_path` を追加：

```python
    app = create_app({
        "grid": grid,
        "stem_path": stem,
        "audio_path": audio,
        "grid_save_path": str(grid_save_path),
    })
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./venv/bin/python -m pytest tests/test_server.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add app/analyze.py app/server.py run_editor.py tests/test_server.py
git -c user.name="鴫原康" -c user.email="shigiharayasushi@shigiharayasushinoMacBook-Air.local" commit -m "feat(adt): /auto-draftルートとanalyze配線（分離済みstem優先）"
```

---

### Task 5: エディタUI（6レーン・日本語ラベル・自動下書きボタン）

**Files:**
- Modify: `app/static/editor.js`（LANES 6本・ラベル・自動下書きボタン処理）
- Modify: `app/templates/editor.html`（ボタン追加）
- Modify: `app/static/editor.css`（ラベル幅・タム色）

**Interfaces:**
- Consumes: `POST /auto-draft`（Task4）
- Produces: なし（フロントのみ・手動検証）

- [ ] **Step 1: editor.js を編集**

先頭の LANES とラベルを差し替え：

```javascript
const LANES = ["HH", "HT", "MT", "FT", "SN", "KK"];   // 上から表示
const LANE_LABELS = {
  HH: "ハイハット", HT: "ハイタム", MT: "ミッドタム",
  FT: "フロアタム", SN: "スネア", KK: "キック",
};
let grid = null;
const history = [];
```

`drawGrid` のラベルとセルのクラスを差し替え（ラベルは日本語、タムに `tom` クラス）：

```javascript
    label.className = "lane-label";
    label.textContent = LANE_LABELS[lane] || lane;
    row.appendChild(label);
    grid.lanes[lane].forEach((v, i) => {
      const cell = document.createElement("div");
      const extra = lane === "HH" ? " hh" : (["HT", "MT", "FT"].includes(lane) ? " tom" : "");
      cell.className = "cell" + (v ? " on" : "") + extra;
```

`autoDraft` 関数を追加（非破壊：現グリッドを履歴に積んでから差し替え）と、ボタン配線：

```javascript
async function autoDraft() {
  const btn = document.getElementById("auto_draft");
  const msg = document.getElementById("auto-msg");
  btn.disabled = true;
  msg.textContent = "解析中…";
  try {
    const res = await fetch("/auto-draft", { method: "POST" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      msg.textContent = "! " + (data.error || res.status);
      return;
    }
    history.push(JSON.parse(JSON.stringify(grid)));
    updateUndoButton();
    grid = await res.json();
    const hits = Object.values(grid.lanes).some((a) => a.some((v) => v));
    msg.textContent = hits ? "✓ 下書きを作成（元に戻せます）" : "打点を検出できませんでした";
    drawGrid();
    renderScore();
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("auto_draft").addEventListener("click", autoDraft);
```

- [ ] **Step 2: editor.html にボタン追加**

`#commands` の直前（`#controls` の後）に自動下書きの行を追加：

```html
  <div id="draft">
    <button id="auto_draft" title="ドラム音源からグルーヴの下書きを自動生成（タムは手入力）">自動下書き（音源から）</button>
    <span id="auto-msg"></span>
  </div>
```

- [ ] **Step 3: editor.css にラベル幅とタム色を追加**

`.lane-label` の幅を日本語に合わせ、タムの色を追加：

```css
.lane-label { width: 72px; font-weight: bold; font-size: 13px; }
.cell.on.tom { background: #2980b9; }          /* タムは青 */
```

- [ ] **Step 4: 手動検証（ブラウザ）**

分離済みドラム音源で起動（Demucs不要）：

```bash
PORT=5050 EDITOR_STEM="output/Yvv4RVQzIFk/stems/ドラム.wav" ./venv/bin/python run_editor.py audio/Yvv4RVQzIFk.mp3
```

ブラウザ `http://127.0.0.1:5050` で確認：
- 6行（ハイハット/ハイタム/ミッドタム/フロアタム/スネア/キック）が上から表示される
- タムの升目をクリック→青で点灯→「譜面にする」でタム位置に音符が出る
- 「自動下書き（音源から）」→「解析中…」→KK/SN/HHに下書きが入る（タムは空）→譜面自動更新
- 「↩元に戻す」で自動下書き前に戻る

Expected: 上記すべて動作。コンソールエラーなし。

- [ ] **Step 5: コミット**

```bash
git add app/static/editor.js app/templates/editor.html app/static/editor.css
git -c user.name="鴫原康" -c user.email="shigiharayasushi@shigiharayasushinoMacBook-Air.local" commit -m "feat(editor): 6レーン(タム3本)表示・日本語ラベル・自動下書きボタン"
```

---

### Task 6: 全テスト＆Rebound実機評価（判断ゲート）

**Files:**
- Modify: `CLAUDE.md`（結果を作業ログに記録）

**Interfaces:** なし

- [ ] **Step 1: 全テストを実行**

Run: `./venv/bin/python -m pytest -q`
Expected: 全緑（既存66＋新規：grid 4本・drum_transcribe 6本・server 2本 ＝ 計78前後）

- [ ] **Step 2: Rebound実機評価（記録・断定テストではない）**

```bash
PORT=5050 EDITOR_STEM="output/Yvv4RVQzIFk/stems/ドラム.wav" ./venv/bin/python run_editor.py audio/Yvv4RVQzIFk.mp3
```

「自動下書き」を押し、譜面と升目を見て評価：
- KK/SNの骨格が実際のグルーヴらしく出るか（1・3拍キック／2・4拍スネアの気配があるか）
- HHの刻み（8分/16分）が曲に合っているか
- 誤検出（余計な打点）が「人が2割直す」で済む範囲か

- [ ] **Step 3: 判断と記録**

評価結果を `CLAUDE.md` に「ADT A1 実機評価」として記録。骨格が使える→A1採用で完了。明らかに力不足→A2（専用ADTモデルを隔離venvで）へ上げる判断を記録。

- [ ] **Step 4: コミット**

```bash
git add CLAUDE.md
git -c user.name="鴫原康" -c user.email="shigiharayasushi@shigiharayasushinoMacBook-Air.local" commit -m "docs: ADT A1 実機評価の結果を記録"
```

---

## Self-Review（計画作成後の点検）

- **Spec coverage**：設計書の各節に対応タスクあり — グリッド6レーン化=Task1／NMF中核=Task2,3／配線・ルート=Task4／エディタUI=Task5／テスト方針・実機評価=各タスク＋Task6。欠けなし。
- **Placeholder scan**：TBD/TODO・曖昧指示なし。各コード手順は実コード掲載済み。
- **Type consistency**：`transcribe_drums(path, tempo, bars, steps_per_bar=16)` はTask3定義・Task4ルートで同シグネチャ使用。レーンキー `HH/HT/MT/FT/SN/KK` は全タスクで一致。`infer_hihat_subdivision(hh_onset_times, bars, bar_sec)` はTask2定義・Task3で同引数で呼ぶ。
