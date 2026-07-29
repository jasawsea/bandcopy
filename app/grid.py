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
        "lanes": {
            "HH": hh,
            "HT": [0] * n,   # ハイタム（人が手入力）
            "MT": [0] * n,   # ミッドタム
            "FT": [0] * n,   # フロアタム
            "SN": sn,
            "KK": kk,
        },
    }


def fit_grid_to_bars(grid: dict, bars: int) -> dict:
    """グリッドを指定小節数に合わせた新グリッドを返す（元は非破壊）。

    短ければ末尾を空小節（0）でパディング、長ければ切り詰める。統合スコアの
    小節数に揃えて、ドラム段が音程段と縦に並ぶようにするために使う。
    """
    spb = grid["steps_per_bar"]
    n = bars * spb
    lanes = {}
    for lane, arr in grid["lanes"].items():
        if len(arr) >= n:
            lanes[lane] = list(arr[:n])
        else:
            lanes[lane] = list(arr) + [0] * (n - len(arr))
    out = dict(grid)
    out["bars"] = bars
    out["lanes"] = lanes
    return out


# レーンごとの記譜位置（displayStep, displayOctave, notehead）
LANE_NOTATION = {
    "HH": ("G", 5, "x"),    # ハイハット：上第1線上・×符頭
    "HT": ("E", 5, None),   # ハイタム：第4間
    "MT": ("D", 5, None),   # ミッドタム：第4線
    "SN": ("C", 5, None),   # スネア：第3間
    "FT": ("A", 4, None),   # フロアタム：第2間
    "KK": ("F", 4, None),   # キック：下第1間
}


def grid_to_score(grid: dict):
    """グリッドを music21 の打楽器スコアに変換する。"""
    from music21 import stream, note, clef, meter, duration
    from music21 import tempo as m21tempo

    spb = grid["steps_per_bar"]
    bars = grid["bars"]
    step_ql = 4.0 / spb  # 16ステップ/小節なら0.25拍

    part = stream.Part()
    part.insert(0, clef.PercussionClef())
    part.insert(0, meter.TimeSignature("4/4"))
    part.insert(0, m21tempo.MetronomeMark(number=round(grid["tempo"])))

    for b in range(bars):
        m = stream.Measure(number=b + 1)
        for lane, (dstep, doct, head) in LANE_NOTATION.items():
            arr = grid["lanes"].get(lane)
            if not arr:
                continue
            v = stream.Voice()
            for s in range(spb):
                idx = b * spb + s
                if idx < len(arr) and arr[idx]:
                    n = note.Unpitched()
                    n.displayStep = dstep
                    n.displayOctave = doct
                    n.duration = duration.Duration(step_ql)
                    if head:
                        n.notehead = head
                    v.insert(s * step_ql, n)
            if list(v.notes):
                # 打点間の隙間を休符で埋める（そのレーン内で）
                v.makeRests(fillGaps=True, inPlace=True)
                m.insert(0, v)
        if not list(m.voices):
            m.insert(0, note.Rest(quarterLength=4.0))  # 空小節は全休符
        part.append(m)

    sc = stream.Score()
    sc.insert(0, part)
    return sc


def grid_to_musicxml(grid: dict) -> str:
    """グリッドを MusicXML 文字列に変換する。"""
    from music21.musicxml.m21ToXml import GeneralObjectExporter
    sc = grid_to_score(grid)
    return GeneralObjectExporter(sc).parse().decode("utf-8")
