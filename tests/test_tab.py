from app.tab import (
    TUNINGS, fret_positions, choose_fingering, assign_chord,
)


# --- チューニング定義 ---

def test_tunings_open_pitches():
    # ギター6弦 EADGBE（1弦=高E4=64 … 6弦=低E2=40）
    assert TUNINGS["guitar"] == {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40}
    # ベース4弦 EADG（1弦=G2=43 … 4弦=低E1=28）
    assert TUNINGS["bass"] == {1: 43, 2: 38, 3: 33, 4: 28}


# --- フレット候補 ---

def test_fret_positions_lists_all_valid_strings():
    # ギターのE4(64)=1弦0fr / 2弦5fr / 3弦9fr …
    pos = dict(fret_positions(64, TUNINGS["guitar"], max_fret=12))
    assert pos[1] == 0 and pos[2] == 5 and pos[3] == 9


def test_fret_positions_excludes_out_of_range():
    # 低E2(40)は6弦0frのみ（他弦では負フレット）
    strings = [s for s, f in fret_positions(40, TUNINGS["guitar"], max_fret=12)]
    assert strings == [6]


# --- 単音の運指選択 ---

def test_choose_fingering_prefers_low_fret_first_note():
    # 最初の音は低フレット優先：G4(67)→1弦3fr
    s, f = choose_fingering(67, TUNINGS["guitar"], max_fret=12, prev_fret=None)
    assert (s, f) == (1, 3)


def test_choose_fingering_open_low_e():
    s, f = choose_fingering(40, TUNINGS["guitar"], max_fret=12, prev_fret=None)
    assert (s, f) == (6, 0)


def test_choose_fingering_stays_near_previous_position():
    # 直前が5fr付近なら、A4(69)は1弦5frを選ぶ（別弦の高fretより近い）
    s, f = choose_fingering(69, TUNINGS["guitar"], max_fret=12, prev_fret=5)
    assert (s, f) == (1, 5)


def test_choose_fingering_octave_shifts_when_below_range():
    # ギター最低音より下(F#1=30)はオクターブ上げて弾ける位置に
    s, f = choose_fingering(30, TUNINGS["guitar"], max_fret=12, prev_fret=None)
    assert 0 <= f <= 12 and s in TUNINGS["guitar"]


# --- 和音（同時発音を別々の弦へ）---

def test_assign_chord_uses_distinct_strings():
    # Cメジャー三和音 C4(60) E4(64) G4(67)
    result = assign_chord([60, 64, 67], TUNINGS["guitar"], max_fret=12, prev_fret=None)
    assert len(result) == 3
    strings = [s for s, f in result]
    assert len(set(strings)) == 3          # 全部別々の弦
    assert all(0 <= f <= 12 for s, f in result)


# --- MIDI → タブMusicXML ---

def _mono_midi(tmp_path, pitches, name="m.mid"):
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=33)
    t = 0.0
    for p in pitches:
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=p, start=t, end=t + 0.5))
        t += 0.5
    pm.instruments.append(inst)
    path = tmp_path / name
    pm.write(str(path))
    return str(path)


def test_midi_to_tab_musicxml_has_tab_clef_and_frets(tmp_path):
    from app.tab import midi_to_tab_musicxml
    # ベースの単音ライン E1(28) A1(33) D2(38) G2(43) = 各弦の開放
    xml = midi_to_tab_musicxml(_mono_midi(tmp_path, [28, 33, 38, 43]), "bass")
    assert "<sign>TAB</sign>" in xml
    assert "<string>" in xml and "<fret>" in xml
    import re
    assert "0" in re.findall(r"<fret>(\d+)</fret>", xml)  # 開放弦=0fr が出る


def test_midi_to_tab_musicxml_bass_has_four_staff_lines(tmp_path):
    from app.tab import midi_to_tab_musicxml
    xml = midi_to_tab_musicxml(_mono_midi(tmp_path, [28, 33]), "bass")
    assert "<staff-lines>4</staff-lines>" in xml


def test_midi_to_tab_musicxml_guitar_has_six_staff_lines(tmp_path):
    from app.tab import midi_to_tab_musicxml
    xml = midi_to_tab_musicxml(_mono_midi(tmp_path, [40, 45]), "guitar")
    assert "<staff-lines>6</staff-lines>" in xml


# --- CLI: 対象パートの検出 ---

def _touch_midi(path):
    import pretty_midi
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(0)
    inst.notes.append(pretty_midi.Note(90, 40, 0.0, 0.5))
    pm.instruments.append(inst)
    pm.write(str(path))


def test_tab_targets_four_stem(tmp_path):
    from tab import resolve_tab_targets
    _touch_midi(tmp_path / "ベース_Lv3.mid")
    _touch_midi(tmp_path / "ギター・キーボード等_Lv3.mid")
    targets = resolve_tab_targets(tmp_path, level=3)
    got = {(inst, label) for _, inst, label in targets}
    assert got == {("bass", "ベース"), ("guitar", "ギター・キーボード等")}


def test_tab_targets_six_stem_prefers_clean_guitar(tmp_path):
    from tab import resolve_tab_targets
    _touch_midi(tmp_path / "ベース_Lv3.mid")
    _touch_midi(tmp_path / "ギター_Lv3.mid")
    _touch_midi(tmp_path / "ギター・キーボード等_Lv3.mid")  # あっても6分離ギター優先
    targets = resolve_tab_targets(tmp_path, level=3)
    got = {(inst, label) for _, inst, label in targets}
    assert got == {("bass", "ベース"), ("guitar", "ギター")}


def test_tab_targets_empty_when_none(tmp_path):
    from tab import resolve_tab_targets
    assert resolve_tab_targets(tmp_path, level=3) == []
