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


def test_grid_to_midi_step_timing_with_steps_per_bar_8():
    """異なる steps_per_bar でのステップ幅が正しく計算されることを検証。

    8ステップ/小節 の場合、1小節 = 4拍分のティック（division * 4 = 1920 ticks）
    ゆえに step_ticks = 1920 / 8 = 240 ticks、gate = 120 ticks。

    イベント：
    - tick 0: Note On (step 0)
    - tick 120: Note Off (gate終了)
    - tick 1680: Note On (step 7) ← delta = 1680 - 120 = 1560
    - tick 1800: Note Off
    """
    from app.grid import grid_to_midi, _var_len
    grid = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 8,
        "lanes": {lane: [0] * 8 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    # 小節内の最初と最後のステップにキック
    grid["lanes"]["KK"][0] = 1  # step 0 -> tick 0
    grid["lanes"]["KK"][7] = 1  # step 7 -> tick 1680 (7 * 240)

    midi = grid_to_midi(grid)

    # デルタタイムは前イベントからの差分：1680 - 120 = 1560
    # 1560 = 0x618 → _var_len should produce [0x8C, 0x18]（マルチバイト）
    var_len_1560 = _var_len(1560)
    assert var_len_1560 == b'\x8c\x18', f"Expected \\x8c\\x18, got {var_len_1560.hex()}"

    # MIDIデータ内にデルタタイム 1560 が含まれていることを確認
    assert var_len_1560 in midi, "Delta time 1560 (encoded as \\x8c\\x18) should be in MIDI"


def test_grid_to_midi_timing_division_4_vs_steps_per_bar():
    """steps_per_bar != 16 でも、1小節が同じティック幅（division * 4）を占めることを検証。

    デフォルト16分: step_ticks = 480/4 = 120, 1小節 = 16 * 120 = 1920
    8分設定:      step_ticks = 1920/8 = 240, 1小節 = 8 * 240 = 1920 ✓同じ

    両グリッドとも小節最後のステップに打点を置き、Note On/Offの実際のデルタタイム
    （_var_lenエンコード値）が期待どおりの絶対tickに対応することを検証する
    （test_grid_to_midi_step_timing_with_steps_per_bar_8 と同じ手法）。
    """
    from app.grid import grid_to_midi, _var_len

    # spb=16 の場合：最後のステップ(15) -> tick 15*120 = 1800、gate=60
    grid_16 = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 16,
        "lanes": {lane: [0] * 16 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    grid_16["lanes"]["KK"][15] = 1
    midi_16 = grid_to_midi(grid_16)
    # Note On のデルタ（最初のイベントなので絶対tickそのもの）= 1800
    assert _var_len(1800) in midi_16
    # Note Off のデルタ（gate分後）= 60
    assert _var_len(60) in midi_16

    # spb=8 の場合：最後のステップ(7) -> tick 7*240 = 1680、gate=120
    grid_8 = {
        "tempo": 120.0, "bars": 1, "steps_per_bar": 8,
        "lanes": {lane: [0] * 8 for lane in ("KK", "SN", "HH", "HT", "MT", "FT")},
    }
    grid_8["lanes"]["KK"][7] = 1
    midi_8 = grid_to_midi(grid_8)
    assert _var_len(1680) in midi_8
    assert _var_len(120) in midi_8

    # 取り違えの検出：spb=8 の出力に spb=16 のtick(1800)が現れてはいけない（逆も同様）
    assert _var_len(1800) not in midi_8
    assert _var_len(1680) not in midi_16


def test_var_len_encodes_multibyte_values_correctly():
    """_var_len がマルチバイトVLQ値（128以上）を正しくエンコードすることを検証。

    MIDI可変長数値：
    - 127以下 → 1バイト
    - 128-16383 → 2バイト（0x80-0xFF, 0x00-0x7F）
    - 16384-2097151 → 3バイト

    例：
    - 128 → 0x81 0x00
    - 1680 → 0x8D 0x10
    - 16383 → 0xFF 0x7F
    """
    from app.grid import _var_len

    # 1バイト値
    assert _var_len(0) == b'\x00'
    assert _var_len(127) == b'\x7f'

    # 2バイト値
    assert _var_len(128) == b'\x81\x00', f"Expected \\x81\\x00, got {_var_len(128).hex()}"
    assert _var_len(1680) == b'\x8d\x10', f"Expected \\x8d\\x10, got {_var_len(1680).hex()}"
    assert _var_len(16383) == b'\xff\x7f', f"Expected \\xff\\x7f, got {_var_len(16383).hex()}"

    # 3バイト値
    assert _var_len(16384) == b'\x81\x80\x00', f"Expected \\x81\\x80\\x00, got {_var_len(16384).hex()}"
