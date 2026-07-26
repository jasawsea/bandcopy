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
