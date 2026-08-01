"""ドラムレーン定義の単一ソース。

1レーン分の (日本語ラベル / 記譜位置 / GMノート番号 / エディタの見た目 / ADT対象か) を
ここに集約し、app/grid.py・app/drum_transcribe.py・エディタUI が参照する。
app/parts.py（音程パートの定義）のドラム版にあたる。

**レーンを増やすとき（クラッシュ・ライド等）はこのファイルだけ直せばよい。**
エディタのJSはサーバが埋め込む定義（editor_payload）を読むので、JS側の修正は不要。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LaneSpec:
    key: str                # グリッドのレーンキー（"HH" など）
    label: str              # 日本語ラベル（エディタ表示）
    step: str               # 記譜位置：displayStep
    octave: int             # 記譜位置：displayOctave
    notehead: str | None    # 符頭（ハイハットは "x"、他は None）
    midi: int               # GMドラムのノート番号（チャンネル10）
    css: str                # エディタのセル装飾クラス（"" なら装飾なし）
    auto: bool              # 自動採譜(ADT)が埋めるレーンか（タムは人が手入力）


# 並びは**五線上の高い位置から順**。grid_to_score が声部を積む順序になるため、
# ここを入れ替えると楽譜の声部順が変わる点に注意。
_LANES = [
    LaneSpec("HH", "ハイハット",   "G", 5, "x",  42, "hh",  True),   # 上第1線上
    LaneSpec("HT", "ハイタム",     "E", 5, None, 50, "tom", False),  # 第4間
    LaneSpec("MT", "ミッドタム",   "D", 5, None, 47, "tom", False),  # 第4線
    LaneSpec("SN", "スネア",       "C", 5, None, 38, "",    True),   # 第3間
    LaneSpec("FT", "フロアタム",   "A", 4, None, 43, "tom", False),  # 第2間
    LaneSpec("KK", "キック",       "F", 4, None, 36, "",    True),   # 下第1間
]

# エディタの表示順は上からHH→タム3種→SN→KK。記譜位置順(_LANES)と違い、
# タムを隣接させて打ち込みやすくするためのUI都合の並び。
_EDITOR_ORDER = ["HH", "HT", "MT", "FT", "SN", "KK"]


def specs() -> list:
    """レーン定義（記譜位置の高い順）を返す。"""
    return list(_LANES)


def keys() -> list:
    """レーンキー（記譜位置の高い順）を返す。"""
    return [s.key for s in _LANES]


def spec_map() -> dict:
    """key → LaneSpec の辞書を返す。"""
    return {s.key: s for s in _LANES}


def notation_map() -> dict:
    """key → (displayStep, displayOctave, notehead) を返す。"""
    return {s.key: (s.step, s.octave, s.notehead) for s in _LANES}


def midi_note_map() -> dict:
    """key → GMドラムのノート番号 を返す。"""
    return {s.key: s.midi for s in _LANES}


def auto_keys() -> list:
    """自動採譜(ADT)が埋めるレーンのキー。"""
    return [s.key for s in _LANES if s.auto]


def editor_specs() -> list:
    """エディタの表示順（上→下）でレーン定義を返す。"""
    by_key = spec_map()
    return [by_key[k] for k in _EDITOR_ORDER]


def editor_payload() -> list:
    """エディタのJSへ渡す定義（JSONにできる形）。表示順。"""
    return [{"key": s.key, "label": s.label, "css": s.css} for s in editor_specs()]
