"""全パートを1枚のスコア譜に統合する。"""

from app.parts import specs


def _pitched_order(six: bool):
    """段（上→下）の (キー, 音部記号タイプ, 楽器名)。ドラムは別途 grid から積む。"""
    return [(s.key, s.clef, s.name) for s in specs(six) if s.transcribe]


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


def build_full_score(parts: list, tempo: float):
    """Part のリストを順に段として積んだ Score を返す。

    テンポ標語はスコアでは最上段に1つあれば足りるため、各パートが持つ
    重複を全て除き、先頭段にだけ付け直す。
    """
    from music21 import stream
    from music21 import tempo as m21tempo
    sc = stream.Score()
    for p in parts:
        for mm in list(p.recurse().getElementsByClass(m21tempo.MetronomeMark)):
            mm.activeSite.remove(mm)
        sc.insert(0, p)
    if parts:
        first = parts[0]
        target = first.recurse().getElementsByClass("Measure").first() or first
        target.insert(0, m21tempo.MetronomeMark(number=round(tempo)))
    return sc


def score_to_musicxml(sc) -> str:
    """統合スコアを MusicXML 文字列に変換する。"""
    from music21.musicxml.m21ToXml import GeneralObjectExporter
    return GeneralObjectExporter(sc).parse().decode("utf-8")


def assemble_full_score(midi_paths: dict, drum_grid: dict, tempo: float,
                        chords: list = None, six: bool = False):
    """音程段（存在するもの）＋ドラム段を組み立てて Score を返す。

    six=True で 6分離（Vocal/Guitar/Keys/Other/Bass）の段順・音部記号を使う。
    """
    from music21 import harmony
    from app.grid import grid_to_score

    parts = []
    for key, clef_type, name in _pitched_order(six):
        path = midi_paths.get(key)
        if not path:
            continue
        part = pitched_part_from_midi(path, clef_type, name)
        if key == "vocals" and chords:
            measures = list(part.recurse().getElementsByClass("Measure"))
            for i, fig in enumerate(chords):
                if fig and i < len(measures):
                    try:
                        measures[i].insert(0.0, harmony.ChordSymbol(fig))
                    except Exception:
                        pass  # 解釈できないコード表記はスキップ
        parts.append(part)

    # ドラム段（最下段）
    drum_part = grid_to_score(drum_grid).parts[0]
    drum_part.partName = "Drums"
    drum_part.partAbbreviation = "Drums"
    parts.append(drum_part)

    return build_full_score(parts, tempo)
