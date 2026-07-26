"""タブ譜（弦・フレット）生成。MIDI→運指割当→タブMusicXML。

運指は最適保証のない heuristic（低フレット優先＋直前位置の近く）。アプリ方針
どおり「8割自動・人が2割直す」前提。MusicXML の TAB 音部記号＋技法記号
（string/fret）で出力し、verovio で描画する（新規依存なし）。
"""

# 弦番号 → 開放弦のMIDI音高（MusicXMLは1弦＝最高音）。
#   guitar: EADGBE（1弦=高E4=64 … 6弦=低E2=40）
#   bass:   EADG （1弦=G2=43 … 4弦=低E1=28）
TUNINGS = {
    "guitar": {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40},
    "bass": {1: 43, 2: 38, 3: 33, 4: 28},
}

DEFAULT_MAX_FRET = 24


def fret_positions(pitch, tuning, max_fret=DEFAULT_MAX_FRET):
    """そのピッチを押さえられる (弦, フレット) の候補一覧を返す。"""
    out = []
    for string, open_pitch in tuning.items():
        fret = pitch - open_pitch
        if 0 <= fret <= max_fret:
            out.append((string, fret))
    return out


def _shift_into_range(pitch, tuning, max_fret):
    """弦に乗らない音をオクターブ単位で弾ける範囲へ寄せる。"""
    lo = min(tuning.values())
    hi = max(tuning.values()) + max_fret
    while pitch < lo:
        pitch += 12
    while pitch > hi:
        pitch -= 12
    return pitch


def _cost(fret, prev_fret):
    """低フレットほど・直前位置に近いほど小さいコスト。"""
    c = fret
    if prev_fret is not None:
        c += abs(fret - prev_fret)
    return c


def choose_fingering(pitch, tuning, max_fret=DEFAULT_MAX_FRET, prev_fret=None):
    """単音の (弦, フレット) を選ぶ。音域外はオクターブ補正。置けなければ None。"""
    cands = fret_positions(pitch, tuning, max_fret)
    if not cands:
        cands = fret_positions(_shift_into_range(pitch, tuning, max_fret),
                               tuning, max_fret)
    if not cands:
        return None
    # コスト → フレット → 弦番号 の順で最小を選ぶ（決定的）
    return min(cands, key=lambda sf: (_cost(sf[1], prev_fret), sf[1], sf[0]))


# 音高名（0=C … 11=B）。alter=1 はシャープ。タブでは音名は表示されないが
# MusicXML の <pitch> は妥当である必要があるため、弦+フレットの実音から作る。
_PITCH_NAMES = [
    ("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
    ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0),
]
INSTRUMENT_NAMES = {"guitar": "Guitar", "bass": "Bass"}
_DIV = 480  # 4分音符あたりの分解能

# music21 の duration.type をそのまま MusicXML の <type> に使えないケースの保険
_SAFE_TYPES = {"whole", "half", "quarter", "eighth", "16th", "32nd", "64th",
               "breve", "long", "128th"}


def _pitch_xml(midi):
    step, alter = _PITCH_NAMES[midi % 12]
    octave = midi // 12 - 1
    alter_xml = f"<alter>{alter}</alter>" if alter else ""
    return f"<pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"


def _note_xml(midi, string, fret, dur, typ, dots, is_chord):
    chord = "<chord/>" if is_chord else ""
    return (f"<note>{chord}{_pitch_xml(midi)}"
            f"<duration>{dur}</duration><type>{typ}</type>{dots}"
            f"<notations><technical><string>{string}</string>"
            f"<fret>{fret}</fret></technical></notations></note>")


def _rest_xml(dur, typ, dots):
    return f"<note><rest/><duration>{dur}</duration><type>{typ}</type>{dots}</note>"


def _dur_type_dots(el):
    dur = max(1, int(round(el.quarterLength * _DIV)))
    typ = el.duration.type
    if typ not in _SAFE_TYPES:
        typ = "quarter"
    dots = "<dot/>" * el.duration.dots
    return dur, typ, dots


def midi_to_tab_musicxml(midi_path, instrument, max_fret=DEFAULT_MAX_FRET):
    """MIDI を、指定楽器のタブ譜 MusicXML 文字列に変換する。

    各音符/和音に運指（弦・フレット）を割り当て、TAB音部記号・弦数ぶんの五線で
    書き出す。ポリフォニックなMIDIは chordify で単一声部にまとめる。MusicXMLは
    自前で生成する（music21の和音タブ書き出しが複数和音で崩れるため）。
    """
    from music21 import converter

    tuning = TUNINGS[instrument]
    n_strings = len(tuning)

    score = converter.parse(str(midi_path))
    part = score.parts[0].chordify()  # 声部を1つにまとめる（同時音は和音に）

    ts = part.recurse().getElementsByClass("TimeSignature").first()
    beats = ts.numerator if ts else 4
    beat_type = ts.denominator if ts else 4

    prev_fret = None
    measures_xml = []
    measures = list(part.getElementsByClass("Measure")) or [part]
    for mi, m in enumerate(measures, start=1):
        chunk = []
        if mi == 1:
            chunk.append(
                f"<attributes><divisions>{_DIV}</divisions>"
                f"<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>"
                f"<clef><sign>TAB</sign><line>5</line></clef>"
                f"<staff-details><staff-lines>{n_strings}</staff-lines></staff-details>"
                "</attributes>")
        elems = list(m.notesAndRests)
        for el in elems:
            dur, typ, dots = _dur_type_dots(el)
            if el.isRest:
                chunk.append(_rest_xml(dur, typ, dots))
            elif el.isChord:
                pitches = sorted(p.midi for p in el.pitches)
                assigned = assign_chord(pitches, tuning, max_fret, prev_fret)
                if not assigned:
                    chunk.append(_rest_xml(dur, typ, dots))
                    continue
                for idx, (s, f) in enumerate(assigned):
                    chunk.append(_note_xml(tuning[s] + f, s, f, dur, typ, dots, idx > 0))
                prev_fret = min(f for _, f in assigned)
            else:
                sf = choose_fingering(el.pitch.midi, tuning, max_fret, prev_fret)
                if sf:
                    s, f = sf
                    chunk.append(_note_xml(tuning[s] + f, s, f, dur, typ, dots, False))
                    prev_fret = f
                else:
                    chunk.append(_rest_xml(dur, typ, dots))
        if not elems:  # 空小節は全休符で埋める
            chunk.append(_rest_xml(_DIV * 4 * beats // beat_type, "whole", ""))
        measures_xml.append(f'<measure number="{mi}">{"".join(chunk)}</measure>')

    name = INSTRUMENT_NAMES.get(instrument, instrument)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<score-partwise version="3.1"><part-list><score-part id="P1">'
            f"<part-name>{name}</part-name></score-part></part-list>"
            f'<part id="P1">{"".join(measures_xml)}</part></score-partwise>')


def assign_chord(pitches, tuning, max_fret=DEFAULT_MAX_FRET, prev_fret=None):
    """同時発音を別々の弦へ割り当てる。低音から順に、空いている弦で最小コスト。

    戻り値は入力順に並べた (弦, フレット) のリスト（置けなかった音は除外）。
    """
    used = set()
    result = [None] * len(pitches)
    for i in sorted(range(len(pitches)), key=lambda k: pitches[k]):
        p = pitches[i]
        cands = [sf for sf in fret_positions(p, tuning, max_fret)
                 if sf[0] not in used]
        if not cands:
            p2 = _shift_into_range(p, tuning, max_fret)
            cands = [sf for sf in fret_positions(p2, tuning, max_fret)
                     if sf[0] not in used]
        if not cands:
            continue  # 空き弦が無ければその音はスキップ
        s, f = min(cands, key=lambda sf: (_cost(sf[1], prev_fret), sf[1], sf[0]))
        used.add(s)
        result[i] = (s, f)
    return [r for r in result if r is not None]
