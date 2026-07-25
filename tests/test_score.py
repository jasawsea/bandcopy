import pretty_midi


def _tiny_midi(tmp_path, name="t.mid"):
    """テスト用に2音だけの小さなMIDIを生成してパスを返す。"""
    pm = pretty_midi.PrettyMIDI(initial_tempo=100.0)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=48, start=0.0, end=0.5))
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=50, start=0.5, end=1.0))
    pm.instruments.append(inst)
    p = tmp_path / name
    pm.write(str(p))
    return str(p)


def test_pitched_part_from_midi_sets_clef_and_name(tmp_path):
    from app.score import pitched_part_from_midi
    from music21 import clef
    part = pitched_part_from_midi(_tiny_midi(tmp_path), "bass8vb", "Bass")
    assert part.partName == "Bass"
    clefs = list(part.recurse().getElementsByClass(clef.Clef))
    assert any(isinstance(c, clef.Bass8vbClef) for c in clefs)
