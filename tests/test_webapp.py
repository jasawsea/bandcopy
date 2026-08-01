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
