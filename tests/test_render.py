from app.grid import make_template_grid, grid_to_musicxml
from app.render import musicxml_to_svg, musicxml_to_pdf


def test_musicxml_to_svg_returns_svg():
    xml = grid_to_musicxml(make_template_grid(tempo=100.0, bars=1))
    svg = musicxml_to_svg(xml)
    assert svg.lstrip().startswith("<") and "svg" in svg[:200].lower()


def test_musicxml_to_pdf_returns_pdf_bytes():
    xml = grid_to_musicxml(make_template_grid(tempo=100.0, bars=1))
    pdf = musicxml_to_pdf(xml)
    assert isinstance(pdf, (bytes, bytearray))
    assert pdf[:5] == b"%PDF-"


def test_bundled_music_font_is_valid():
    # テンポ♩・コード♯を描くための同梱フォントが存在し、TTFとして妥当であること
    from app.render import _BUNDLED_FONT
    assert _BUNDLED_FONT.exists()
    # TrueType(0x00010000)/'true'/OpenType('OTTO') のいずれかで始まる
    assert _BUNDLED_FONT.read_bytes()[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO")


def test_musicxml_to_pdf_paginates_long_score():
    # 多小節＝複数ページになる素材でも全ページが1つのPDFに束ねられる
    from pypdf import PdfReader
    import io
    xml = grid_to_musicxml(make_template_grid(tempo=100.0, bars=40))
    pdf = musicxml_to_pdf(xml)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) >= 2
