"""ドラム音源を キック/スネア/シンバル/タム の4本に分離する（drumsep・ONNX）。

**なぜ要るか**：帯域だけでキック・スネア・タムを見分けるのは原理的に無理がある。
タムの音域(60〜250Hz)がキック(40〜80Hz)とスネアの胴(150〜400Hz)に挟まれて重なるため、
帯域方式ではタム候補の8割がキックの二重検出になった（2026-08-09 実測）。
音源そのものを分けてしまえば、この重なりの問題が消える。

**モデル**：`gridshiftstudio/drumsep-onnx`（MIT・上流は inagoy/drumsep＝HDemucsの追加学習）。
PyTorch版ではなくONNX版を選んだのは、demucs のチェックポイント読み込みが
`weights_only=False` 固定で、素性の確かでない重みを読むとコードが動きうるため。
ONNXにその問題は無い。取得時はマニフェストのSHA-256で照合する。

**ONNX側は複素数を扱う STFT/ISTFT の手前で切られている**ので、その前後は
demucs 本体の実装（`HDemucs._spec` 等）をそのまま借りて繋ぐ。自前で書き直すと
微妙にズレたまま「それらしい音」が出てしまい、間違いに気付けない。
"""
import hashlib
import json
from pathlib import Path

import numpy as np

MODEL_REPO = "gridshiftstudio/drumsep-onnx"
MODEL_FILE = "drumsep.onnx"
MANIFEST_FILE = "drumsep_manifest.json"
MODEL_DIR = Path("models")

# ONNXグラフが固定で要求する形。マニフェスト由来（44.1kHz・ステレオ・40秒窓）。
SAMPLE_RATE = 44100
WINDOW = 1764000          # 1回の推論で処理する長さ（40秒）
HOP = 882000              # 窓を進める幅（20秒）＝各サンプルが2窓に含まれる
STEMS = ("kick", "snare", "cymbals", "toms")      # 出力の並び（マニフェスト準拠）
STEM_LABELS = {"kick": "キック", "snare": "スネア",
               "cymbals": "シンバル", "toms": "タム"}

# HDemucs の設定。mag が [1,4,2048,1723] になることから逆算した値。
#   nfft=4096 → 周波数ビン2049、最上位を捨てて2048
#   cac=True  → ステレオ2ch × 実部虚部 = 4ch
NFFT, HOP_LENGTH = 4096, 1024


class _SpecHelper:
    """demucs の STFT 前後処理だけを借りるための器。

    ネットワーク本体は ONNX 側にあるので、重みを持つ HDemucs を作らずに
    メソッドだけを束ねる（335MBのモデルを二重に抱えないため）。
    """
    nfft = NFFT
    hop_length = HOP_LENGTH
    hybrid = True
    hybrid_old = False
    cac = True
    wiener_iters = 0
    training = False

    def __init__(self):
        from demucs.hdemucs import HDemucs
        for name in ("_spec", "_magnitude", "_mask", "_ispec"):
            setattr(self, name, getattr(HDemucs, name).__get__(self))


def model_path(model_dir=MODEL_DIR):
    return Path(model_dir) / MODEL_FILE


def verify_model(path, manifest_path):
    """マニフェストのSHA-256と照合する。合わなければ例外。"""
    man = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    expected = _find_sha256(man)
    if not expected:
        raise ValueError("マニフェストにSHA-256が見つかりません")
    actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(
            f"モデルのSHA-256が一致しません（期待 {expected[:12]}… / 実際 {actual[:12]}…）")
    return actual


def _find_sha256(obj):
    """入れ子のdict/listから最初の64桁16進文字列を拾う。"""
    if isinstance(obj, dict):
        for v in obj.values():
            got = _find_sha256(v)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _find_sha256(v)
            if got:
                return got
    elif isinstance(obj, str) and len(obj) == 64:
        if all(c in "0123456789abcdef" for c in obj.lower()):
            return obj.lower()
    return None


def ensure_model(model_dir=MODEL_DIR):
    """モデルを取得（既にあれば再利用）し、SHA-256を照合してパスを返す。"""
    from huggingface_hub import hf_hub_download
    model_dir = Path(model_dir)
    man = hf_hub_download(MODEL_REPO, MANIFEST_FILE, local_dir=model_dir)
    mdl = hf_hub_download(MODEL_REPO, MODEL_FILE, local_dir=model_dir)
    verify_model(mdl, man)
    return Path(mdl)


def overlap_weights(n, ramp):
    """重ね合わせ用の窓。両端を直線で立ち上げ・下げする（合計が1になる）。"""
    w = np.ones(n, dtype=np.float32)
    ramp = min(ramp, n // 2)
    if ramp > 0:
        edge = np.linspace(0, 1, ramp + 2, dtype=np.float32)[1:-1]
        w[:ramp] = edge
        w[-ramp:] = edge[::-1]
    return w


def separate(drum_wav, out_dir, model=None, progress=None):
    """ドラム音源を4本に分離してWAVで書き出し、{名前: パス} を返す。"""
    import soundfile as sf
    import torch
    import librosa
    import onnxruntime as ort

    model = Path(model) if model else model_path()
    if not model.exists():
        raise FileNotFoundError(
            f"分離モデルがありません: {model}\n"
            "app.drumsep.ensure_model() で取得してください。")

    y, _sr = librosa.load(str(drum_wav), sr=SAMPLE_RATE, mono=False)
    if y.ndim == 1:                       # モノラルはステレオに複製
        y = np.stack([y, y])
    y = y[:2].astype(np.float32)
    length = y.shape[-1]

    sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    helper = _SpecHelper()

    acc = np.zeros((len(STEMS), 2, length), dtype=np.float32)
    wsum = np.zeros(length, dtype=np.float32)
    starts = list(range(0, max(length - WINDOW, 0) + 1, HOP)) or [0]
    if starts[-1] + WINDOW < length:
        starts.append(length - WINDOW)

    for i, s0 in enumerate(starts):
        if progress:
            progress(i + 1, len(starts))
        chunk = np.zeros((2, WINDOW), dtype=np.float32)
        seg = y[:, s0:s0 + WINDOW]
        chunk[:, :seg.shape[-1]] = seg

        mix = torch.from_numpy(chunk)[None]              # [1,2,WINDOW]
        z = helper._spec(mix)                            # 複素スペクトログラム
        mag = helper._magnitude(z)                       # [1,4,2048,1723]

        freq_out, time_out = sess.run(
            None, {"mix": mix.numpy(), "mag": mag.numpy()})

        zout = helper._mask(z, torch.from_numpy(freq_out))
        x = helper._ispec(zout, WINDOW)                  # [1,4,2,WINDOW]
        out = (x + torch.from_numpy(time_out)).numpy()[0]

        n = min(WINDOW, length - s0)
        w = overlap_weights(n, ramp=HOP // 4)
        acc[..., s0:s0 + n] += out[..., :n] * w
        wsum[s0:s0 + n] += w

    acc /= np.maximum(wsum, 1e-6)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for i, name in enumerate(STEMS):
        p = out_dir / f"{STEM_LABELS[name]}.wav"
        sf.write(str(p), acc[i].T, SAMPLE_RATE)
        paths[name] = str(p)
    return paths


def reconstruction_error(drum_wav, stem_paths):
    """4本を足し戻して元音源とどれだけ一致するかを返す（0に近いほど正しい）。

    **前後処理の実装が正しいかを機械的に判定するための検査。**
    間違っていても「それらしいドラムの音」は出てしまうので、耳では気付けない。
    """
    import librosa
    y, _ = librosa.load(str(drum_wav), sr=SAMPLE_RATE, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    y = y[:2]
    total = None
    for p in stem_paths.values():
        s, _ = librosa.load(str(p), sr=SAMPLE_RATE, mono=False)
        if s.ndim == 1:
            s = np.stack([s, s])
        total = s[:2] if total is None else total + s[:2]
    n = min(y.shape[-1], total.shape[-1])
    diff = y[:, :n] - total[:, :n]
    denom = float(np.sqrt((y[:, :n] ** 2).mean())) + 1e-9
    return float(np.sqrt((diff ** 2).mean())) / denom
