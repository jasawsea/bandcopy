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


def test_build_full_score_stacks_in_order():
    from app.score import build_full_score
    from music21 import stream, note
    from music21 import tempo as m21tempo
    p1 = stream.Part(); p1.partName = "A"; p1.append(note.Note("C4"))
    p2 = stream.Part(); p2.partName = "B"; p2.append(note.Note("E4"))
    sc = build_full_score([p1, p2], 120.0)
    assert len(sc.parts) == 2
    assert sc.parts[0].partName == "A"
    assert sc.parts[1].partName == "B"
    assert list(sc.parts[0].recurse().getElementsByClass(m21tempo.MetronomeMark))


def test_assemble_full_score_order_and_clefs(tmp_path):
    from app.score import assemble_full_score
    from app.grid import make_template_grid
    from music21 import clef
    midi_paths = {
        "vocals": _tiny_midi(tmp_path, "v.mid"),
        "bass": _tiny_midi(tmp_path, "b.mid"),
    }
    grid = make_template_grid(100.0, 2)
    sc = assemble_full_score(midi_paths, grid, 100.0)
    # otherは無いので飛ばし、Vocal→Bass→Drums の順
    assert [p.partName for p in sc.parts] == ["Vocal", "Bass", "Drums"]
    # 最下段はパーカッション音部記号
    drum = sc.parts[-1]
    assert list(drum.recurse().getElementsByClass(clef.PercussionClef))


def test_assemble_full_score_inserts_chords_on_vocals(tmp_path):
    from app.score import assemble_full_score
    from app.grid import make_template_grid
    from music21 import harmony
    midi_paths = {"vocals": _tiny_midi(tmp_path, "v.mid")}
    grid = make_template_grid(100.0, 1)
    sc = assemble_full_score(midi_paths, grid, 100.0, chords=["C"])
    vocal = sc.parts[0]
    assert list(vocal.recurse().getElementsByClass(harmony.ChordSymbol))

