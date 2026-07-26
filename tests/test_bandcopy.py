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
