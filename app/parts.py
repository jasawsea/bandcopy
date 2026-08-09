"""パート定義の単一ソース。

分離パートの (日本語ラベル / 段名 / 音部記号 / 和音削減方針 / 採譜するか) を
ここに集約し、bandcopy.py・app/score.py・score_all.py が参照する。
4分離(htdemucs) と 6分離(htdemucs_6s) の2モードを持つ。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PartSpec:
    key: str          # demucs が出すステム名
    label: str        # 日本語ラベル（stems/midi ファイル名・表示用）
    name: str         # 段名（英語・楽器名）
    clef: str         # treble / bass / treble8vb / bass8vb / percussion
    keep: str         # 和音削減で残す方針: low / outer / high
    transcribe: bool = True  # False は採譜せず分離音源のみ（ドラム）
    max_chord_notes: int = None  # 同時発音数の上限（None=難易度まかせ／1=単音楽器）


# 段の並びは上→下。ドラムは最下段（grid から積むため transcribe=False）。
_FOUR_STEM = [
    PartSpec("vocals", "ボーカル", "Vocal", "treble", "high"),
    PartSpec("other", "ギター・キーボード等", "Guitar", "treble8vb", "outer"),
    PartSpec("bass", "ベース", "Bass", "bass8vb", "low", max_chord_notes=1),
    PartSpec("drums", "ドラム", "Drums", "percussion", "outer", transcribe=False),
]

# 6分離では other をギター(guitar)・キーボード(piano)・その他(other残り)に分ける。
_SIX_STEM = [
    PartSpec("vocals", "ボーカル", "Vocal", "treble", "high"),
    PartSpec("guitar", "ギター", "Guitar", "treble8vb", "outer"),
    PartSpec("piano", "キーボード", "Keys", "treble", "outer"),
    PartSpec("other", "その他", "Other", "treble", "outer"),
    PartSpec("bass", "ベース", "Bass", "bass8vb", "low", max_chord_notes=1),
    PartSpec("drums", "ドラム", "Drums", "percussion", "outer", transcribe=False),
]

_MODEL = {False: "htdemucs", True: "htdemucs_6s"}
# コードネームを載せる段：4分離=伴奏の other、6分離=guitar
_CHORD_PART = {False: "other", True: "guitar"}


def specs(six: bool) -> list:
    """モードに応じたパート定義リスト（段の上→下順）を返す。"""
    return list(_SIX_STEM if six else _FOUR_STEM)


def spec_map(six: bool) -> dict:
    """key → PartSpec の辞書を返す。"""
    return {s.key: s for s in specs(six)}


def model_name(six: bool) -> str:
    """使う Demucs モデル名。"""
    return _MODEL[six]


def chord_part_key(six: bool) -> str:
    """コードネームを載せる段の key。"""
    return _CHORD_PART[six]
