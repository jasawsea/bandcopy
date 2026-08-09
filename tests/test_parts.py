from app.parts import specs, spec_map, model_name, chord_part_key


def test_four_stem_specs():
    m = spec_map(six=False)
    assert set(m) == {"vocals", "other", "bass", "drums"}
    # 4分離の other は「ギター・キーボード等」1段（従来どおり）
    assert m["other"].label == "ギター・キーボード等"
    assert m["other"].name == "Guitar"
    assert m["other"].clef == "treble8vb"
    assert m["bass"].clef == "bass8vb" and m["bass"].keep == "low"
    assert m["vocals"].clef == "treble" and m["vocals"].keep == "high"
    # ドラムは採譜しない
    assert m["drums"].transcribe is False


def test_six_stem_specs_split_guitar_piano_other():
    m = spec_map(six=True)
    assert set(m) == {"vocals", "guitar", "piano", "other", "bass", "drums"}
    assert m["guitar"].label == "ギター" and m["guitar"].name == "Guitar"
    assert m["guitar"].clef == "treble8vb"
    assert m["piano"].label == "キーボード" and m["piano"].name == "Keys"
    assert m["piano"].clef == "treble"
    # 6分離では other は残り（その他）
    assert m["other"].label == "その他" and m["other"].name == "Other"
    assert m["other"].clef == "treble"


def test_pitched_order_top_to_bottom():
    # 段の並び（採譜対象のみ、ドラムを除く）：上→下
    order4 = [s.key for s in specs(six=False) if s.transcribe]
    assert order4 == ["vocals", "other", "bass"]
    order6 = [s.key for s in specs(six=True) if s.transcribe]
    assert order6 == ["vocals", "guitar", "piano", "other", "bass"]


def test_model_and_chord_part():
    assert model_name(six=False) == "htdemucs"
    assert model_name(six=True) == "htdemucs_6s"
    # コードを載せる段：4分離=other、6分離=guitar
    assert chord_part_key(six=False) == "other"
    assert chord_part_key(six=True) == "guitar"


def test_bass_is_monophonic():
    """ベースは単音楽器。難易度によらず同時発音1音に制限する。

    採譜モデルは1つの音に対して基音と倍音を別の音として出すことがあり、
    難易度3の「和音3音まで」では基音＋倍音2つがそのまま通ってしまう
    （2026-08-09 実測：同時刻のオクターブ重なりが71〜183箇所）。
    """
    for six in (False, True):
        assert spec_map(six)["bass"].max_chord_notes == 1


def test_other_parts_follow_the_difficulty_setting():
    """ベース以外は難易度側の設定に従う（和音を弾く楽器なので潰さない）。"""
    for six in (False, True):
        for key, spec in spec_map(six).items():
            if key != "bass":
                assert spec.max_chord_notes is None
