import zipfile
from pathlib import Path


def test_zip_dir_bundles_files(tmp_path):
    from app.webapp import _zip_dir
    src = tmp_path / "stems"
    src.mkdir()
    (src / "ベース.wav").write_bytes(b"RIFF0000WAVE")
    (src / "ドラム.wav").write_bytes(b"RIFF1111WAVE")
    (src / "_skip").mkdir()  # サブフォルダは含めない
    dest = tmp_path / "out.zip"

    result = _zip_dir(src, dest)

    assert result == str(dest) and dest.exists()
    with zipfile.ZipFile(dest) as z:
        assert set(z.namelist()) == {"ベース.wav", "ドラム.wav"}


def test_zip_dir_missing_source_returns_none(tmp_path):
    from app.webapp import _zip_dir
    assert _zip_dir(tmp_path / "nope", tmp_path / "o.zip") is None


def test_build_ui_returns_gradio_blocks():
    from app.webapp import build_ui
    import gradio as gr
    ui = build_ui()
    assert isinstance(ui, gr.Blocks)


def test_intro_markdown_omits_editor_link_by_default():
    from app.webapp import build_intro_markdown
    assert "editor/" not in build_intro_markdown()
    assert "editor/" not in build_intro_markdown(editor_link=False)


def test_intro_markdown_includes_editor_link_when_requested():
    from app.webapp import build_intro_markdown
    assert "editor/" in build_intro_markdown(editor_link=True)


def test_intro_markdown_mentions_url_input():
    """URLでも使えることが画面で分かること（貼る場所が無いと迷わせないため）。"""
    from app.webapp import build_intro_markdown
    assert "URL" in build_intro_markdown()


def test_fetch_options_use_video_id_as_filename(tmp_path):
    """日本語タイトルのままだとDemucsが失敗するので、必ず動画IDで保存する。"""
    from app.webapp import build_fetch_options
    opts = build_fetch_options(tmp_path)
    assert opts["outtmpl"] == str(tmp_path / "%(id)s.%(ext)s")


def test_fetch_options_never_grab_whole_playlist(tmp_path):
    """`&list=RD...` 付きURLを貼られても1曲だけにする。"""
    from app.webapp import build_fetch_options
    assert build_fetch_options(tmp_path)["noplaylist"] is True


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
    from app.webapp import fetch_audio_from_url
    path, title = fetch_audio_from_url(
        "https://example.com/watch?v=abc123", outdir=tmp_path,
        ydl_factory=_FakeYDL)
    assert Path(path).name == "abc123.mp3" and Path(path).exists()
    assert title == "テスト曲"


def test_fetch_audio_from_url_raises_on_bad_url(tmp_path):
    import pytest
    from app.webapp import fetch_audio_from_url

    def factory(opts):
        return _FakeYDL(opts, info={})           # 情報が取れなかった状況
    with pytest.raises(ValueError):
        fetch_audio_from_url("https://example.com/bad", outdir=tmp_path,
                             ydl_factory=factory)


def test_resolve_input_prefers_url_over_upload(tmp_path):
    from app.webapp import resolve_input
    up = tmp_path / "手持ち.mp3"
    up.write_bytes(b"x")

    def fake(url, outdir="audio"):
        return "/tmp/from_url.mp3", "URLの曲"

    path, note = resolve_input(str(up), " https://example.com/v ", fetcher=fake)
    assert path == "/tmp/from_url.mp3"
    assert "URLを優先" in note                     # どちらを使ったか画面で分かること


def test_resolve_input_uses_upload_when_url_blank(tmp_path):
    from app.webapp import resolve_input
    up = tmp_path / "手持ち.mp3"
    up.write_bytes(b"x")
    path, note = resolve_input(str(up), "   ", fetcher=lambda *a, **k: 1 / 0)
    assert path == str(up) and note == ""


def test_resolve_input_with_neither_asks_for_input():
    from app.webapp import resolve_input
    path, note = resolve_input(None, "", fetcher=lambda *a, **k: 1 / 0)
    assert path is None and "URL" in note
