"""全パートを1枚のスコア譜に統合する。"""

# 段（上→下）の (キー, 音部記号タイプ, 楽器名)。ドラムは別途 grid から積む。
PITCHED_ORDER = [
    ("vocals", "treble", "Vocal"),
    ("other", "treble8vb", "Guitar"),
    ("bass", "bass8vb", "Bass"),
]


def _clef_for(clef_type: str):
    from music21 import clef as m21clef
    return {
        "treble": m21clef.TrebleClef,
        "treble8vb": m21clef.Treble8vbClef,
        "bass": m21clef.BassClef,
        "bass8vb": m21clef.Bass8vbClef,
    }.get(clef_type, m21clef.TrebleClef)()


def pitched_part_from_midi(midi_path: str, clef_type: str, name: str):
    """簡略化MIDIを読み、音部記号・楽器名を設定した Part を返す。"""
    from music21 import converter
    from music21 import clef as m21clef
    score = converter.parse(str(midi_path))
    part = score.parts[0]
    for c in list(part.recurse().getElementsByClass(m21clef.Clef)):
        c.activeSite.remove(c)
    target = part.recurse().getElementsByClass("Measure").first() or part
    target.insert(0, _clef_for(clef_type))
    part.partName = name
    part.partAbbreviation = name
    return part
