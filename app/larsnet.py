"""ドラム音源を キック/スネア/タム/ハイハット/シンバル の5本に分離する（LarsNet）。

**なぜ要るか**：フィル（タム）を譜面に載せるため。帯域だけではタム(60〜250Hz)が
キック(40〜80Hz)とスネアの胴(150〜400Hz)に挟まれて見分けられない。
drumsep（ONNX・HDemucsの追加学習）で一度試したが、**スネアをタム側に振り分けて**
2拍4拍が55%→21%に崩れ不採用になった（2026-08-09）。

LarsNet は楽器ごとに**専用のU-Netを並列に置く**構成で、1モデル4出力の drumsep とは
作りが違う。同じ失敗をするとは限らないので、もう一度だけ同じ評価にかける。

**モデル**：`polimi-ispl/larsnet`（Mezza et al., Pattern Recognition Letters 2024）。
重みは **CC BY-NC 4.0＝非商用限定**。個人のバンド練習は可だが、仕事に絡めるなら差し替えが要る。

**重みの読み方（重要）**：必ず `weights_only=True`。匿名配布のPyTorch重みは読み込み時に
コードが動きうる（demucs は `weights_only=False` 固定なので drumsep の PyTorch 版は避けた）。
LarsNet の5つは純粋な状態辞書であることを確認済み（`models/larsnet/取得メモ.md`）。
**公式の `separate.py` / `larsnet.py` はこの指定が無いので使わない。**
このモジュールが公式コードから借りるのは `unet.py` のモデル定義だけ。

他に公式コードをそのまま使わない理由が2つある：
  - `torchaudio` に依存しているが、この環境には入っていない（音源読み込みは librosa で足りる）
  - 曲を丸ごと1バッチでU-Netに通すので、4分の曲だと中間活性がGB級に膨らむ
    → ここでは 11.87秒の窓に切って重ね合わせる（`app/drumsep.py` と同じ考え方）
"""
import hashlib
from pathlib import Path

import numpy as np

MODEL_DIR = Path("models/larsnet")
WEIGHTS_SUBDIR = "pretrained_larsnet_models"

# 出力の並び。config.yaml の inference_models の順に合わせてある。
STEMS = ("kick", "snare", "toms", "hihat", "cymbals")
STEM_LABELS = {"kick": "キック", "snare": "スネア", "toms": "タム",
               "hihat": "ハイハット", "cymbals": "シンバル"}

# 配布元が差し替わったら検知するためのSHA-256（2026-08-09 取得時の実測値）。
WEIGHT_SHA256 = {
    "kick":    "ed821b6a69b1ef0413ac9ef7958ac9a37e5f4f056e66f0191496bf903ac2628d",
    "snare":   "78bd75001ff6c52b23de6245cecd1606adbd45348e0216f6d8c116553013e4fd",
    "toms":    "699112983948e14d805890a0723e5b402203a3a1db1cd0ccdd8a80058062ef77",
    "hihat":   "ac004ac24a26e77f6d39671ed8ba45c3f476e956900d469ebb402386dad11dd7",
    "cymbals": "889804c465e2c6fdbbe45febbd4daafef01d8d22f9f34fb968695ab9793858d0",
}

SAMPLE_RATE = 44100

# STFTの設定。unet.py の UNetUtils 既定値と揃っていないと重みが噛み合わない。
NFFT, HOP_LENGTH = 4096, 1024
F_BINS, T_FRAMES = 2048, 512          # config.yaml の F・T（5モデルとも同じ）

# 1回の推論で処理する長さ。center=True のとき frames = WINDOW/HOP_LENGTH + 1 なので、
# (T-1)*HOP ちょうどにすると **フレーム数が T にぴったり収まり**、U-Net内部の
# fold（Tごとの分割）でゼロ詰めの余りチャンクが出ない。
WINDOW = (T_FRAMES - 1) * HOP_LENGTH   # 523,264サンプル ≒ 11.87秒
HOP = WINDOW // 2                      # 半分ずつ進める＝各サンプルが2窓に入る


def weight_path(stem, model_dir=MODEL_DIR):
    return Path(model_dir) / WEIGHTS_SUBDIR / stem / f"pretrained_{stem}_unet.pth"


def verify_weights(model_dir=MODEL_DIR, stems=None):
    """重みのSHA-256を照合する。合わなければ例外。"""
    actual = {}
    for stem in (stems or STEMS):
        p = weight_path(stem, model_dir)
        if not p.exists():
            raise FileNotFoundError(
                f"LarsNetの重みがありません: {p}\n"
                "models/larsnet/取得メモ.md の手順で取得してください。")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != WEIGHT_SHA256[stem]:
            raise ValueError(
                f"{stem} の重みのSHA-256が一致しません"
                f"（期待 {WEIGHT_SHA256[stem][:12]}… / 実際 {digest[:12]}…）")
        actual[stem] = digest
    return actual


def _import_unet(model_dir=MODEL_DIR):
    """公式の unet.py からモデル定義だけを読み込む。

    `models/` はgit管理外（重みが562MBあるため）。コードもそこに同居しているので、
    パッケージとしてではなくファイル指定で読む。
    """
    import importlib.util

    path = Path(model_dir) / "unet.py"
    if not path.exists():
        raise FileNotFoundError(
            f"LarsNetのモデル定義がありません: {path}\n"
            "models/larsnet/取得メモ.md の手順で取得してください。")
    spec = importlib.util.spec_from_file_location("larsnet_unet", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_models(model_dir=MODEL_DIR, device="cpu", verify=True, stems=None):
    """U-Netを読み込む。**weights_only=True 固定。**"""
    import torch

    if verify:
        verify_weights(model_dir, stems)

    unet = _import_unet(model_dir)
    models = {}
    for stem in (stems or STEMS):
        model = unet.UNet(input_size=(2, F_BINS, T_FRAMES), device=device)
        # ここを weights_only=False にしないこと（モジュール冒頭の説明を参照）
        ckpt = torch.load(str(weight_path(stem, model_dir)),
                          map_location=device, weights_only=True)
        model.load_state_dict(ckpt["model_state_dict"])
        model.eval()
        models[stem] = model
    return models, unet


def _overlap_weights(n, ramp):
    """重ね合わせ用の窓。両端を直線で立ち上げ・下げする。"""
    w = np.ones(n, dtype=np.float32)
    ramp = min(ramp, n // 2)
    if ramp > 0:
        edge = np.linspace(0, 1, ramp + 2, dtype=np.float32)[1:-1]
        w[:ramp] = edge
        w[-ramp:] = edge[::-1]
    return w


def separate(drum_wav, out_dir, model_dir=MODEL_DIR, wiener_exponent=1.0,
             device="cpu", progress=None, models=None, stems=None):
    """ドラム音源を5本に分離してWAVで書き出し、{名前: パス} を返す。

    `wiener_exponent` を指定すると α-Wiener フィルタで**マスクの合計が1になるよう
    正規化**する。楽器間の滲み（cross-talk）を抑えるための処理で、drumsepが失敗した
    「スネアがタムに漏れる」問題に直接効く可能性がある。None にすると各U-Netの
    マスクをそのまま使う（合計は1にならない＝5本の和は元音源に戻らない）。

    `stems` で書き出す楽器を絞れる（例：スネアだけ欲しいとき）。ただし**α-Wiener を
    使う場合は絞っても5モデル全部を動かす**：合計を1に正規化する計算に全員のマスクが
    要るため。Wienerを切ったときだけ実際に計算量が減る。
    """
    import librosa
    import soundfile as sf
    import torch

    if wiener_exponent is not None and wiener_exponent <= 0:
        raise ValueError("α-Wiener の指数は正の数にしてください")

    want = tuple(stems) if stems else STEMS
    unknown = set(want) - set(STEMS)
    if unknown:
        raise ValueError(f"知らない楽器名です: {sorted(unknown)}")
    # Wiener有効時は正規化に全員のマスクが要る（上のdocstring参照）
    run = STEMS if wiener_exponent is not None else want

    if models is None:
        models, unet = load_models(model_dir, device=device, stems=run)
    else:
        models, unet = models

    utils = unet.UNetUtils(F=F_BINS, T=T_FRAMES, n_fft=NFFT,
                           hop_length=HOP_LENGTH, device=device)

    y, _sr = librosa.load(str(drum_wav), sr=SAMPLE_RATE, mono=False)
    if y.ndim == 1:                       # モノラルはステレオに複製
        y = np.stack([y, y])
    y = y[:2].astype(np.float32)
    length = y.shape[-1]

    acc = np.zeros((len(run), 2, length), dtype=np.float32)
    wsum = np.zeros(length, dtype=np.float32)

    starts = list(range(0, max(length - WINDOW, 0) + 1, HOP)) or [0]
    if starts[-1] + WINDOW < length:
        starts.append(length - WINDOW)

    with torch.no_grad():
        for i, s0 in enumerate(starts):
            if progress:
                progress(i + 1, len(starts))

            chunk = np.zeros((2, WINDOW), dtype=np.float32)
            seg = y[:, s0:s0 + WINDOW]
            chunk[:, :seg.shape[-1]] = seg

            x = torch.from_numpy(chunk).unsqueeze(0).to(device)   # [1,2,WINDOW]
            mag, phase = utils.batch_stft(x)

            masked = []
            for stem in run:
                _, mask = models[stem](mag)
                if wiener_exponent is None:
                    masked.append(mask * mag)
                else:
                    masked.append((mask * mag) ** wiener_exponent)

            if wiener_exponent is not None:
                total = sum(masked)
                masked = [mag * (m / (total + 1e-7)) for m in masked]

            n = min(WINDOW, length - s0)
            w = _overlap_weights(n, ramp=HOP // 4)
            for k, m in enumerate(masked):
                wav = utils.batch_istft(m, phase, trim_length=WINDOW)
                out = wav.squeeze(0).cpu().numpy()
                acc[k, :, s0:s0 + n] += out[:, :n] * w
            wsum[s0:s0 + n] += w

    acc /= np.maximum(wsum, 1e-6)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for i, stem in enumerate(run):
        if stem not in want:
            continue
        p = out_dir / f"{STEM_LABELS[stem]}.wav"
        sf.write(str(p), acc[i].T, SAMPLE_RATE)
        paths[stem] = str(p)
    return paths


def snare_stem(drum_wav, out_dir, model_dir=MODEL_DIR, device="cpu",
               progress=None, notify=print):
    """スネアだけ分離してパスを返す。**使えない環境では None を返す。**

    重みは562MBあってgit管理外なので、新しいclone・Colab・他人の環境では
    無いのが普通。無いときにパイプラインを止めてはいけないので、ここで握って
    None を返し、呼び出し側は従来の帯域方式のまま動く。

    α-Wienerの正規化に5モデル全部のマスクが要るので計算量は5本ぶんかかるが、
    書き出すのはスネアだけ。**スネア1本だけ走らせる案は測って落とした**：
    滲みの激しい曲（The_Best_Song）で2拍4拍が73%→32%に崩れた。
    4分の曲で約30秒、Demucsの数分に対して誤差なので堅い方を取る。
    """
    try:
        return separate(drum_wav, out_dir, model_dir=model_dir, device=device,
                        progress=progress, stems=["snare"])["snare"]
    except FileNotFoundError:
        return None                       # 重みが無い＝想定内。黙って帯域方式へ
    except Exception as e:
        if notify:
            notify(f"      ! LarsNetのスネア分離に失敗（帯域方式で続行）: {e}")
        return None


def reconstruction_error(drum_wav, stem_paths):
    """5本を足し戻して元音源とどれだけ一致するかを返す（0に近いほど正しい）。

    **注意：drumsepのときほど強い検査ではない。**
    α-Wienerを使うとマスクの合計が構造的に1になるので、STFTの前後処理さえ合っていれば
    ほぼ自動的に小さくなる。前後処理の配線ミスは拾えるが、
    「分離の中身が正しいか」はこれでは分からない。そこは評価②③で見る。
    """
    from app.drumsep import reconstruction_error as _err
    return _err(drum_wav, stem_paths)
