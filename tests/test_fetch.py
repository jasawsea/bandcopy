"""URL取り込み（app/fetch.py）のテスト。

みんな用Gradioとドラムエディタの両方がこのモジュールを使うので、
壊すと2画面同時に壊れる。ここは厚めに固めておく。
"""
from pathlib import Path

import pytest

from app.fetch import build_fetch_options, fetch_audio_from_url


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
