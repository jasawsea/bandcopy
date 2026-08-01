from app import lanes


def test_six_drum_lanes_defined():
    keys = lanes.keys()
    assert set(keys) == {"HH", "HT", "MT", "FT", "SN", "KK"}
    assert len(keys) == 6


def test_notation_map_matches_staff_positions():
    # 記譜位置（displayStep, displayOctave, notehead）。ハイハットのみ×符頭
    m = lanes.notation_map()
    assert m["HH"] == ("G", 5, "x")
    assert m["HT"] == ("E", 5, None)
    assert m["MT"] == ("D", 5, None)
    assert m["SN"] == ("C", 5, None)
    assert m["FT"] == ("A", 4, None)
    assert m["KK"] == ("F", 4, None)


def test_midi_note_map_uses_general_midi_numbers():
    m = lanes.midi_note_map()
    assert m == {"KK": 36, "SN": 38, "HH": 42, "HT": 50, "MT": 47, "FT": 43}


def test_notation_order_is_high_to_low_on_staff():
    # grid_to_score が声部を積む順＝五線上の高い位置から順に並ぶこと
    order = lanes.keys()
    assert order == ["HH", "HT", "MT", "SN", "FT", "KK"]


def test_editor_order_groups_toms_together():
    # エディタの表示順は上からHH→タム3種→SN→KK（タムを隣接させる）
    assert [s.key for s in lanes.editor_specs()] == ["HH", "HT", "MT", "FT", "SN", "KK"]


def test_editor_specs_carry_japanese_labels_and_css_class():
    by_key = {s.key: s for s in lanes.editor_specs()}
    assert by_key["HH"].label == "ハイハット"
    assert by_key["KK"].label == "キック"
    assert by_key["HH"].css == "hh"
    assert by_key["HT"].css == "tom" and by_key["FT"].css == "tom"
    assert by_key["KK"].css == ""


def test_auto_keys_are_only_the_lanes_adt_detects():
    # 自動採譜(ADT)が埋めるのは KK/SN/HH のみ。タムは人が手入力する
    assert set(lanes.auto_keys()) == {"KK", "SN", "HH"}


def test_editor_payload_is_json_serialisable_for_the_browser():
    import json
    payload = lanes.editor_payload()
    round_tripped = json.loads(json.dumps(payload))
    assert [d["key"] for d in round_tripped] == ["HH", "HT", "MT", "FT", "SN", "KK"]
    assert round_tripped[0]["label"] == "ハイハット"
    assert round_tripped[0]["css"] == "hh"
