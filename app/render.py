"""MusicXML文字列を verovio で SVG に描画する。"""

VEROVIO_OPTIONS = {
    "pageWidth": 2100,
    "pageHeight": 2970,
    "scale": 45,
    "adjustPageHeight": True,
    "header": "none",
    "footer": "none",
}


def musicxml_to_svg(xml: str) -> str:
    """MusicXML文字列を1ページ目のSVG文字列に変換する。"""
    import verovio
    tk = verovio.toolkit()
    tk.setOptions(VEROVIO_OPTIONS)
    tk.loadData(xml)
    return tk.renderToSVG(1)
