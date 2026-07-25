"""グリッド（ドラム打点）の模型と、楽譜への変換。"""


def make_template_grid(tempo: float, bars: int, steps_per_bar: int = 16) -> dict:
    """テンポに合わせた基本8ビートのグリッドを生成する。

    キック=1・3拍、スネア=2・4拍、ハイハット=8分。編集の出発点。
    """
    n = bars * steps_per_bar
    kk = [0] * n
    sn = [0] * n
    hh = [0] * n
    for b in range(bars):
        base = b * steps_per_bar
        for s in range(0, steps_per_bar, 2):   # 8分＝2ステップおき
            hh[base + s] = 1
        kk[base + 0] = 1                        # 1拍
        kk[base + steps_per_bar // 2] = 1       # 3拍
        sn[base + steps_per_bar // 4] = 1       # 2拍
        sn[base + 3 * steps_per_bar // 4] = 1   # 4拍
    return {
        "tempo": tempo,
        "bars": bars,
        "steps_per_bar": steps_per_bar,
        "lanes": {"KK": kk, "SN": sn, "HH": hh},
    }
