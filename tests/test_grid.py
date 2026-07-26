from app.grid import make_template_grid, grid_to_musicxml, fit_grid_to_bars
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
