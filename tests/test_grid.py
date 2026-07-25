from app.grid import make_template_grid, grid_to_musicxml


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
