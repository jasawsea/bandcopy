from app.grid import make_template_grid, grid_to_musicxml, fit_grid_to_bars, grid_to_midi
from app.analyze import count_bars


def test_fit_grid_pads_with_empty_bars_when_shorter():
    g = make_template_grid(tempo=120.0, bars=1)   # 16ステップ
    out = fit_grid_to_bars(g, 3)
    assert out["bars"] == 3
    for lane in ("KK", "SN", "HH"):
        assert len(out["lanes"][lane]) == 48        # 3小節ぶん
        # 元の1小節目は保たれ、増えた分は空（0）
        assert out["lanes"][lane][:16] == g["lanes"][lane]
        assert out["lanes"][lane][16:] == [0] * 32


def test_fit_grid_truncates_when_longer():
    g = make_template_grid(tempo=120.0, bars=4)   # 64ステップ
    out = fit_grid_to_bars(g, 2)
    assert out["bars"] == 2
    for lane in ("KK", "SN", "HH"):
        assert len(out["lanes"][lane]) == 32
        assert out["lanes"][lane] == g["lanes"][lane][:32]


def test_fit_grid_same_bars_unchanged():
    g = make_template_grid(tempo=120.0, bars=2)
    out = fit_grid_to_bars(g, 2)
    assert out["lanes"] == g["lanes"] and out["bars"] == 2


def test_fit_grid_does_not_mutate_input():
    g = make_template_grid(tempo=120.0, bars=2)
    before = {k: list(v) for k, v in g["lanes"].items()}
    fit_grid_to_bars(g, 5)
    assert g["lanes"] == before and g["bars"] == 2


def test_template_grid_shape_and_backbeat():
    g = make_template_grid(tempo=120.0, bars=2)
    assert g["tempo"] == 120.0
    assert g["bars"] == 2
    assert g["steps_per_bar"] == 16
    for lane in ("KK", "SN", "HH"):
        assert len(g["lanes"][lane]) == 32  # 2小節 * 16

    kk, sn, hh = g["lanes"]["KK"], g["lanes"]["SN"], g["lanes"]["HH"]
    # 1小節目：キック=1・3拍(step0,8)、スネア=2・4拍(step4,12)
    assert kk[0] == 1 and kk[8] == 1
    assert sn[4] == 1 and sn[12] == 1
    # ハイハットは8分（偶数ステップ）に8個
    assert sum(hh[0:16]) == 8
    assert all(hh[s] == 1 for s in range(0, 16, 2))
    # 2小節目も同じパターンが繰り返される
    assert kk[16] == 1 and kk[24] == 1


def test_grid_to_musicxml_has_percussion_and_xhead():
    g = make_template_grid(tempo=100.0, bars=1)
    xml = grid_to_musicxml(g)
    assert "<score-partwise" in xml
    # パーカッション音部記号
    assert "percussion" in xml.lower()
    # ハイハットは×符頭
    assert "<notehead" in xml and ">x<" in xml
    # 1小節分の measure が存在する
    assert xml.count("<measure") == 1
    # 打楽器なので unpitched（音程なし）で書かれる
    assert "<unpitched" in xml


def test_count_bars_rounds_up():
    # テンポ120 → 1小節=2秒。7秒は3.5小節ぶん → 切り上げ4小節
    assert count_bars(duration_sec=7.0, tempo=120.0) == 4
    # ちょうど割り切れる場合
    assert count_bars(duration_sec=8.0, tempo=120.0) == 4


def test_template_has_six_lanes_with_empty_toms():
    g = make_template_grid(120.0, 2)
    assert set(g["lanes"].keys()) == {"HH", "HT", "MT", "FT", "SN", "KK"}
    for lane in ("HT", "MT", "FT"):
        assert g["lanes"][lane] == [0] * 32          # 2小節*16、タムは空


def test_lane_notation_has_tom_positions():
    from app.grid import LANE_NOTATION
    assert LANE_NOTATION["HT"] == ("E", 5, None)
    assert LANE_NOTATION["MT"] == ("D", 5, None)
    assert LANE_NOTATION["FT"] == ("A", 4, None)


def test_grid_to_score_renders_tom_hit():
    g = make_template_grid(120.0, 1)
    g["lanes"]["FT"][0] = 1                            # フロアタムを1発置く
    xml = grid_to_musicxml(g)
    assert "unpitched" in xml.lower()                 # 打点が書き出される
    assert "<display-step>A</display-step>" in xml    # フロアタムの位置


def test_grid_to_score_tolerates_missing_lane():
    g = make_template_grid(120.0, 1)
    del g["lanes"]["HT"]                               # レーン欠けでも落ちない
    grid_to_musicxml(g)                               # 例外が出なければ合格


def test_grid_to_midi_starts_with_mthd_and_contains_mtrk():
    from app.grid import grid_to_midi, make_template_grid
    grid = make_template_grid(120.0, 1)
    midi = grid_to_midi(grid)
    assert midi[:4] == b"MThd"
    assert b"MTrk" in midi


def test_grid_to_midi_only_active_lane_has_note_on():
    from app.grid import grid_to_midi
    grid = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 16,
        "lanes": {lane: [0] * 16 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    grid["lanes"]["KK"][0] = 1
    midi = grid_to_midi(grid)
    assert midi.count(bytes([0x99, 36, 100])) == 1  # KK=36のNote On が1つ
    assert midi.count(bytes([0x99, 38, 100])) == 0  # SNは打点なし


def test_grid_to_midi_empty_grid_has_zero_note_on():
    from app.grid import grid_to_midi
    grid = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 16,
        "lanes": {lane: [0] * 16 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    midi = grid_to_midi(grid)
    assert midi.count(bytes([0x99])) == 0


def test_grid_to_midi_toms_use_correct_gm_numbers():
    from app.grid import grid_to_midi
    grid = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 16,
        "lanes": {lane: [0] * 16 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    grid["lanes"]["HT"][0] = 1
    grid["lanes"]["MT"][1] = 1
    grid["lanes"]["FT"][2] = 1
    midi = grid_to_midi(grid)
    assert midi.count(bytes([0x99, 50, 100])) == 1  # HT
    assert midi.count(bytes([0x99, 47, 100])) == 1  # MT
    assert midi.count(bytes([0x99, 43, 100])) == 1  # FT
