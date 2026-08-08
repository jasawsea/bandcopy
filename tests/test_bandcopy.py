from pathlib import Path
from bandcopy import demucs_cmd, default_parts


def test_demucs_cmd_uses_four_stem_model_by_default():
    cmd = demucs_cmd(Path("song.mp3"), Path("/work"), six=False)
    assert "-n" in cmd and cmd[cmd.index("-n") + 1] == "htdemucs"


def test_demucs_cmd_uses_six_stem_model():
    cmd = demucs_cmd(Path("song.mp3"), Path("/work"), six=True)
    assert cmd[cmd.index("-n") + 1] == "htdemucs_6s"


def test_default_parts_by_mode():
    # 採譜する段（ドラム除く）が既定。4分離と6分離で変わる
    assert default_parts(six=False) == ["vocals", "other", "bass"]
    assert default_parts(six=True) == ["vocals", "guitar", "piano", "other", "bass"]


def _synth_drum_wav(path, sr=22050, tempo=120.0, bars=4):
    """キック=1拍3拍 / スネア=2拍4拍 の合成ドラム（テスト用）。"""
    import numpy as np
    import soundfile as sf
    bar_sec = 4 * 60.0 / tempo
    x = np.zeros(int(sr * bar_sec * bars))
    rs = np.random.RandomState(0)

    def add(t0, seg):
        i0 = int(t0 * sr)
        n = min(len(seg), len(x) - i0)
        if n > 0:
            x[i0:i0 + n] += seg[:n]

    for b in range(bars):
        t = b * bar_sec
        env_k = np.exp(-np.linspace(0, 25, int(0.12 * sr)))
        kick = np.sin(2 * np.pi * 55 * np.arange(len(env_k)) / sr) * env_k
        env_s = np.exp(-np.linspace(0, 20, int(0.15 * sr)))
        snare = rs.randn(len(env_s)) * env_s * 0.5
        add(t, kick)
        add(t + bar_sec / 4, snare)
        add(t + bar_sec / 2, kick)
        add(t + 3 * bar_sec / 4, snare)
    sf.write(str(path), x.astype(np.float32), sr)


def test_transcribe_drums_to_outputs_writes_grid_and_midi(tmp_path):
    """音源を投げた時点でドラムのグリッドJSONとMIDIが出ること。"""
    import json
    from bandcopy import transcribe_drums_to_outputs

    wav = tmp_path / "drums.wav"
    _synth_drum_wav(wav)
    midi_dir = tmp_path / "midi"
    midi_dir.mkdir()

    grid_path, midi_path = transcribe_drums_to_outputs(
        wav, tmp_path, midi_dir, tempo=120.0)

    assert grid_path.exists() and grid_path.name == "drum_grid.json"
    assert midi_path.exists() and midi_path.name == "ドラム.mid"
    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    assert set(grid["lanes"]) == {"HH", "HT", "MT", "FT", "SN", "KK"}
    assert sum(grid["lanes"]["KK"]) > 0
    assert midi_path.read_bytes().startswith(b"MThd")     # 妥当なSMF


def test_transcribe_drums_to_outputs_survives_bad_audio(tmp_path):
    """ドラムが採れなくても例外を投げない（他パートの成果を捨てないため）。"""
    from bandcopy import transcribe_drums_to_outputs
    bad = tmp_path / "notaudio.wav"
    bad.write_bytes(b"this is not audio")
    midi_dir = tmp_path / "midi"
    midi_dir.mkdir()

    assert transcribe_drums_to_outputs(bad, tmp_path, midi_dir, 120.0) == (None, None)


def test_drum_midi_is_parseable_as_gm_drums(tmp_path):
    """出したMIDIがドラムとして読めること（DAWで加工する前提）。"""
    from bandcopy import transcribe_drums_to_outputs
    import pretty_midi

    wav = tmp_path / "drums.wav"
    _synth_drum_wav(wav)
    midi_dir = tmp_path / "midi"
    midi_dir.mkdir()
    _g, midi_path = transcribe_drums_to_outputs(wav, tmp_path, midi_dir, 120.0)

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    assert any(inst.is_drum for inst in pm.instruments)
    assert sum(len(i.notes) for i in pm.instruments) > 0
