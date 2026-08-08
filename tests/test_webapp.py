import zipfile


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
