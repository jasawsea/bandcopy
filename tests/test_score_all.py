import pretty_midi
from score_all import resolve_parts


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
