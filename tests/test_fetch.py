"""URL取り込み（app/fetch.py）のテスト。

みんな用Gradioとドラムエディタの両方がこのモジュールを使うので、
壊すと2画面同時に壊れる。ここは厚めに固めておく。
"""
from pathlib import Path

import pytest

from app.fetch import (build_fetch_options, fetch_audio_from_url,
                       parse_timestamp, validate_range)


def test_parse_timestamp_formats():
    assert parse_timestamp("95") == 95
    assert parse_timestamp("1:20") == 80
    assert parse_timestamp("01:02:03") == 3723
    assert parse_timestamp(" 1:20 ") == 80          # 前後の空白は許す


def test_parse_timestamp_blank_is_none():
    """欄を空のまま押されるのが普通なので、空は「指定なし」として扱う。"""
    for blank in (None, "", "   "):
        assert parse_timestamp(blank) is None


def test_parse_timestamp_rejects_garbage():
    with pytest.raises(ValueError):
        parse_timestamp("あとで")


def test_validate_range_rejects_end_before_start():
    with pytest.raises(ValueError):
        validate_range(120, 60)
    with pytest.raises(ValueError):
        validate_range(60, 60)                       # 長さ0も弾く


def test_validate_range_rejects_negative():
    with pytest.raises(ValueError):
        validate_range(-1, None)


def test_validate_range_allows_one_sided():
    assert validate_range(60, None) == (60, None)
    assert validate_range(None, 60) == (None, 60)


def test_fetch_options_without_range_have_no_trim(tmp_path):
    opts = build_fetch_options(tmp_path)
    assert "download_ranges" not in opts


def test_fetch_options_with_range_trim(tmp_path):
    opts = build_fetch_options(tmp_path, start=80, end=165)
    rng = opts["download_ranges"]({"duration": 300}, None)[0]
    assert rng == {"start_time": 80, "end_time": 165}
    assert opts["force_keyframes_at_cuts"] is True


def test_fetch_options_end_only_runs_to_end_of_video(tmp_path):
    opts = build_fetch_options(tmp_path, start=None, end=90)
    assert opts["download_ranges"]({"duration": 300}, None)[0]["start_time"] == 0


def test_fetch_options_start_only_runs_to_video_duration(tmp_path):
    opts = build_fetch_options(tmp_path, start=30, end=None)
    assert opts["download_ranges"]({"duration": 300}, None)[0]["end_time"] == 300


def test_fetch_options_use_video_id_as_filename(tmp_path):
    """日本語タイトルのままだとDemucsが失敗するので、必ず動画IDで保存する。"""
    opts = build_fetch_options(tmp_path)
    assert opts["outtmpl"] == str(tmp_path / "%(id)s.%(ext)s")


def test_fetch_options_never_grab_whole_playlist(tmp_path):
    """`&list=RD...` 付きURLを貼られても1曲だけにする。

    これを落とすと、YouTubeの自動生成ミックスを貼られたときに数十曲を
    ダウンロードしてしまう。
    """
    assert build_fetch_options(tmp_path)["noplaylist"] is True


def test_fetch_options_extract_mp3(tmp_path):
    keys = [p["key"] for p in build_fetch_options(tmp_path)["postprocessors"]]
    assert "FFmpegExtractAudio" in keys


class _FakeYDL:
    """yt-dlp の差し替え。呼ばれたURLを記録し、mp3を実際に置く。"""

    _DEFAULT = {"id": "abc123", "title": "テスト曲"}

    def __init__(self, opts, info=_DEFAULT):
        # 既定値と「空dict＝情報が取れなかった」を取り違えないよう or を使わない
        self.opts = opts
        self._info = info

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=True):
        self.url = url
        if self._info.get("id"):
            out = Path(self.opts["outtmpl"]).parent / f"{self._info['id']}.mp3"
            out.write_bytes(b"ID3fake")
        return self._info


def test_fetch_audio_from_url_returns_path_and_title(tmp_path):
    path, title = fetch_audio_from_url(
        "https://example.com/watch?v=abc123", outdir=tmp_path,
        ydl_factory=_FakeYDL)
    assert Path(path).name == "abc123.mp3" and Path(path).exists()
    assert title == "テスト曲"


def test_fetch_audio_from_url_falls_back_to_id_when_title_missing(tmp_path):
    def factory(opts):
        return _FakeYDL(opts, info={"id": "noTitle"})
    _path, title = fetch_audio_from_url("https://example.com/v", outdir=tmp_path,
                                        ydl_factory=factory)
    assert title == "noTitle"


def test_fetch_audio_from_url_raises_on_bad_url(tmp_path):
    def factory(opts):
        return _FakeYDL(opts, info={})           # 情報が取れなかった状況
    with pytest.raises(ValueError):
        fetch_audio_from_url("https://example.com/bad", outdir=tmp_path,
                             ydl_factory=factory)


def test_fetch_audio_from_url_raises_when_mp3_missing(tmp_path):
    class _NoFile(_FakeYDL):
        def extract_info(self, url, download=True):
            return {"id": "ghost", "title": "落ちなかった曲"}   # ファイルを作らない

    with pytest.raises(FileNotFoundError):
        fetch_audio_from_url("https://example.com/v", outdir=tmp_path,
                             ydl_factory=_NoFile)


def test_fetch_audio_from_url_creates_outdir(tmp_path):
    target = tmp_path / "まだ無いフォルダ"
    fetch_audio_from_url("https://example.com/v", outdir=target,
                         ydl_factory=_FakeYDL)
    assert target.is_dir()


def test_fetch_audio_from_url_passes_range_to_options(tmp_path):
    """'1:20' のような表記のまま渡しても秒に直して効くこと。"""
    seen = {}

    def factory(opts):
        seen["opts"] = opts
        return _FakeYDL(opts)

    fetch_audio_from_url("https://example.com/v", outdir=tmp_path,
                         start="1:20", end="2:45", ydl_factory=factory)
    rng = seen["opts"]["download_ranges"]({"duration": 300}, None)[0]
    assert rng == {"start_time": 80, "end_time": 165}


def test_fetch_audio_from_url_rejects_bad_range_before_downloading(tmp_path):
    """おかしな指定はダウンロードを始める前に弾く（無駄な通信をしない）。"""
    def factory(opts):
        raise AssertionError("ダウンロードを始めてはいけない")

    with pytest.raises(ValueError):
        fetch_audio_from_url("https://example.com/v", outdir=tmp_path,
                             start="2:45", end="1:20", ydl_factory=factory)
