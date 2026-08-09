"""LarsNet（ドラム5分離）の検査。

**重み562MBはgit管理外**なので、ここのテストは重み無しでも通るものだけを置く。
分離の精度そのものは実曲でしか測れない（合成音の合格は根拠にしない・2026-08-02の教訓）。
"""
import numpy as np
import pytest
import soundfile as sf

from app import larsnet


def test_window_holds_exactly_T_frames():
    """窓長がU-Netの時間方向のサイズTにぴったり収まること。

    ここがズレると内部の fold でゼロ詰めの余りチャンクが生まれ、無音を推論して
    重ね合わせに混ぜることになる。音は出てしまうので耳では気付けない。
    """
    frames = larsnet.WINDOW // larsnet.HOP_LENGTH + 1     # center=True のとき
    assert frames == larsnet.T_FRAMES


def test_stft_padding_is_not_needed_for_the_window():
    """窓長が hop の倍数＝STFT前の追加パディングが起きないこと。"""
    assert (larsnet.WINDOW - larsnet.NFFT) % larsnet.HOP_LENGTH == 0


def test_all_five_stems_have_recorded_hashes():
    assert set(larsnet.WEIGHT_SHA256) == set(larsnet.STEMS)
    assert all(len(h) == 64 for h in larsnet.WEIGHT_SHA256.values())


def test_every_stem_has_a_japanese_label():
    assert set(larsnet.STEM_LABELS) == set(larsnet.STEMS)


def test_verify_weights_says_where_to_get_them(tmp_path):
    """重みが無いときは日本語で取得先を案内する（非エンジニアも使うため）。"""
    with pytest.raises(FileNotFoundError) as e:
        larsnet.verify_weights(tmp_path)
    assert "取得メモ" in str(e.value)


def test_verify_weights_rejects_a_swapped_file(tmp_path):
    """配布元が差し替わったら気付けること。"""
    p = larsnet.weight_path("kick", tmp_path)
    p.parent.mkdir(parents=True)
    p.write_bytes("別のファイル".encode("utf-8"))
    with pytest.raises(ValueError) as e:
        larsnet.verify_weights(tmp_path, stems=["kick"])
    assert "SHA-256" in str(e.value)


def test_separate_rejects_unknown_stem_names(tmp_path):
    with pytest.raises(ValueError) as e:
        larsnet.separate("x.wav", tmp_path, stems=["ride"])
    assert "ride" in str(e.value)


def test_separate_rejects_non_positive_wiener_exponent(tmp_path):
    with pytest.raises(ValueError):
        larsnet.separate("x.wav", tmp_path, wiener_exponent=0)


def test_snare_stem_returns_none_when_weights_are_missing(tmp_path):
    """重みが無い環境（新しいclone・Colab）でも例外にせずNoneを返すこと。

    ここが例外だとパイプライン全体が止まる。帯域方式に落ちて動き続けるのが正。
    """
    assert larsnet.snare_stem("x.wav", tmp_path, model_dir=tmp_path) is None


def test_transcribe_with_separation_falls_back_to_band_method(tmp_path, monkeypatch):
    """LarsNetが使えないとき、従来の帯域方式と同じ結果になること。"""
    from app.drum_transcribe import transcribe_drums, transcribe_with_separation

    sr = 22050
    t = np.arange(sr * 2) / sr
    y = np.sin(2 * np.pi * 60 * t) * (np.sin(2 * np.pi * 2 * t) > 0)
    wav = tmp_path / "drums.wav"
    sf.write(str(wav), y.astype(np.float32), sr)

    monkeypatch.setattr(larsnet, "snare_stem", lambda *a, **k: None)
    got = transcribe_with_separation(str(wav), 120.0, 1, tmp_path / "ls")
    want = transcribe_drums(str(wav), 120.0, 1)
    assert got["lanes"] == want["lanes"]
