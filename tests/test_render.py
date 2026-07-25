from app.grid import make_template_grid, grid_to_musicxml
from app.render import musicxml_to_svg


def test_musicxml_to_svg_returns_svg():
    xml = grid_to_musicxml(make_template_grid(tempo=100.0, bars=1))
    svg = musicxml_to_svg(xml)
    assert svg.lstrip().startswith("<") and "svg" in svg[:200].lower()
