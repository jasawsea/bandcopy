import json
import pretty_midi
from score_all import resolve_parts, resolve_drum_grid
from app.grid import make_template_grid


def _midi(path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(0)
    inst.notes.append(pretty_midi.Note(90, 60, 0.0, 0.5))
    pm.instruments.append(inst)
    pm.write(str(path))


def test_resolve_parts_detects_four_stem(tmp_path):
    for label in ("ボーカル", "ギター・キーボード等", "ベース"):
        _midi(tmp_path / f"{label}_Lv3.mid")
    midi_paths, six = resolve_parts(tmp_path, level=3)
    assert six is False
    assert set(midi_paths) == {"vocals", "other", "bass"}


def test_resolve_parts_detects_six_stem(tmp_path):
    for label in ("ボーカル", "ギター", "キーボード", "その他", "ベース"):
        _midi(tmp_path / f"{label}_Lv3.mid")
    midi_paths, six = resolve_parts(tmp_path, level=3)
    assert six is True
    assert set(midi_paths) == {"vocals", "guitar", "piano", "other", "bass"}


def test_resolve_parts_skips_missing(tmp_path):
    # ベースだけ存在 → 4分離・そのキーだけ
    _midi(tmp_path / "ベース_Lv3.mid")
    midi_paths, six = resolve_parts(tmp_path, level=3)
    assert six is False
    assert set(midi_paths) == {"bass"}


def test_resolve_drum_grid_uses_template_when_no_saved(tmp_path):
    # 保存グリッドが無ければテンプレ（キック1・3拍）
    grid = resolve_drum_grid(tmp_path, tempo=120.0, bars=2)
    template = make_template_grid(120.0, 2)
    assert grid["lanes"]["KK"] == template["lanes"]["KK"]


def test_resolve_drum_grid_uses_saved_and_fits_bars(tmp_path):
    # 1小節ぶんの編集済みグリッドを保存 → 2小節スコアに合わせて延長される
    edited = make_template_grid(120.0, 1)
    edited["lanes"]["KK"] = [1, 1, 1, 0] + [0] * 12   # 連打を仕込む
    (tmp_path / "drum_grid.json").write_text(json.dumps(edited), encoding="utf-8")

    grid = resolve_drum_grid(tmp_path, tempo=120.0, bars=2)
    assert grid["bars"] == 2
    assert len(grid["lanes"]["KK"]) == 32
    assert grid["lanes"]["KK"][:16] == [1, 1, 1, 0] + [0] * 12
    assert grid["lanes"]["KK"][16:] == [0] * 16       # 増えた小節は空


def test_resolve_drum_grid_explicit_override(tmp_path):
    edited = make_template_grid(120.0, 1)
    edited["lanes"]["SN"] = [1] + [0] * 15
    p = tmp_path / "custom.json"
    p.write_text(json.dumps(edited), encoding="utf-8")
    grid = resolve_drum_grid(tmp_path, tempo=120.0, bars=1, override=str(p))
    assert grid["lanes"]["SN"] == [1] + [0] * 15


def test_find_source_audio_from_output_dir_name(tmp_path, monkeypatch):
    """出力フォルダ名から audio/<名前>.mp3 を自動で探せること。"""
    from score_all import find_source_audio
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "mysong.mp3").write_bytes(b"ID3")
    (tmp_path / "output" / "mysong").mkdir(parents=True)

    assert find_source_audio(tmp_path / "output" / "mysong") == \
        str(tmp_path / "audio" / "mysong.mp3")


def test_find_source_audio_accepts_other_extensions(tmp_path, monkeypatch):
    from score_all import find_source_audio
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "mysong.wav").write_bytes(b"RIFF")
    (tmp_path / "output" / "mysong").mkdir(parents=True)
    assert find_source_audio(tmp_path / "output" / "mysong").endswith("mysong.wav")


def test_find_source_audio_returns_none_when_absent(tmp_path, monkeypatch):
    from score_all import find_source_audio
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output" / "mysong").mkdir(parents=True)
    assert find_source_audio(tmp_path / "output" / "mysong") is None


def _make_song(tmp_path, name="mysong", with_audio=True):
    root = tmp_path / "output" / name
    (root / "midi").mkdir(parents=True)
    for label in ("ボーカル", "ギター・キーボード等", "ベース"):
        _midi(root / "midi" / f"{label}_Lv3.mid")
    if with_audio:
        (tmp_path / "audio").mkdir(exist_ok=True)
        (tmp_path / "audio" / f"{name}.mp3").write_bytes(b"ID3")
    return root


def test_full_score_detects_chords_without_audio_flag(tmp_path, monkeypatch):
    """--audio を渡し忘れてもコードが載ること（忘れると黙って消えるのを防ぐ）。"""
    import score_all
    monkeypatch.chdir(tmp_path)
    root = _make_song(tmp_path)
    seen = {}

    def fake_detect(path, tempo):
        seen["path"] = str(path)
        return ["C", "G"]

    monkeypatch.setattr("bandcopy.detect_chords", fake_detect)
    captured = {}
    real = score_all.assemble_full_score

    def spy(midi_paths, grid, tempo, chords=None, six=False):
        captured["chords"] = chords
        return real(midi_paths, grid, tempo, chords=chords, six=six)

    monkeypatch.setattr("score_all.assemble_full_score", spy)
    score_all.build_full_score_musicxml(root, level=3, tempo=120.0)

    assert captured["chords"] == ["C", "G"]
    assert seen["path"].endswith("mysong.mp3")


def test_full_score_no_chords_flag_skips_detection(tmp_path, monkeypatch):
    import score_all
    monkeypatch.chdir(tmp_path)
    root = _make_song(tmp_path)

    def boom(path, tempo):
        raise AssertionError("no_chords のときは呼んではいけない")

    monkeypatch.setattr("bandcopy.detect_chords", boom)
    captured = {}
    real = score_all.assemble_full_score

    def spy(midi_paths, grid, tempo, chords=None, six=False):
        captured["chords"] = chords
        return real(midi_paths, grid, tempo, chords=chords, six=six)

    monkeypatch.setattr("score_all.assemble_full_score", spy)
    score_all.build_full_score_musicxml(root, level=3, tempo=120.0, no_chords=True)
    assert captured["chords"] is None


def test_full_score_warns_when_source_audio_missing(tmp_path, monkeypatch, capsys):
    """音源が見つからないときは黙らず理由を出すこと。"""
    import score_all
    monkeypatch.chdir(tmp_path)
    root = _make_song(tmp_path, with_audio=False)
    score_all.build_full_score_musicxml(root, level=3, tempo=120.0)
    assert "コード記号を載せていません" in capsys.readouterr().out
