"""音源の解析。テンポ・小節数・ドラム分離を担う。"""
import math
import sys
from pathlib import Path

# 既存のパイプライン関数を再利用する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bandcopy import detect_tempo, separate_stems  # noqa: E402
from app.grid import make_template_grid  # noqa: E402


def count_bars(duration_sec: float, tempo: float) -> int:
    """4/4を前提に、曲尺を小節数（切り上げ）に換算する。"""
    bar_sec = 4 * 60.0 / tempo
    return int(math.ceil(duration_sec / bar_sec))


def build_template_from_audio(audio_path: str) -> dict:
    """音源からテンポと小節数を求め、テンプレートグリッドを返す（Demucs不要）。"""
    import librosa
    path = Path(audio_path).expanduser().resolve()
    tempo = detect_tempo(path)
    dur = librosa.get_duration(path=str(path))
    bars = count_bars(dur, tempo)
    return make_template_grid(tempo, bars)


def separate_drum_stem(audio_path: str, out_dir: str) -> str:
    """Demucsでドラムを分離し、ドラムWAVのパスを返す。"""
    path = Path(audio_path).expanduser().resolve()
    work = Path(out_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    stems = separate_stems(path, work)
    drum = stems.get("drums")
    if drum is None:
        raise RuntimeError("ドラムパートを分離できませんでした")
    return str(drum)


def transcribe_drum_from_audio(audio_path: str) -> dict:
    """音源を分離してドラムを自動採譜したグリッドを返す（分離済みstemが無いとき用）。"""
    from app.drum_transcribe import transcribe_with_separation
    path = Path(audio_path).expanduser().resolve()
    tempo = detect_tempo(path)
    import librosa
    dur = librosa.get_duration(path=str(path))
    bars = count_bars(dur, tempo)
    work = Path("output") / "_editor"
    stem = separate_drum_stem(str(path), str(work))
    return transcribe_with_separation(stem, tempo, bars, work / "larsnet")
