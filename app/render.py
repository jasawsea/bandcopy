"""MusicXML文字列を verovio で SVG / PDF に描画する。"""
import sys
from pathlib import Path

VEROVIO_OPTIONS = {
    "pageWidth": 2100,
    "pageHeight": 2970,
    "scale": 45,
    "adjustPageHeight": True,
    "header": "none",
    "footer": "none",
}

# verovio が SMuFL 音楽記号（テンポの♩・コードの♯等）を font-family="Leipzig" の
# テキストで描く。cairosvg は fontconfig 経由でフォントを引くため、Leipzig が未導入だと
# それらが □ になる。同梱の ttf を初回だけユーザーのフォントへ入れて回避する。
_FONT_FAMILY = "Leipzig"
_BUNDLED_FONT = Path(__file__).parent / "fonts" / "Leipzig.ttf"
_font_checked = False


def _user_font_dir() -> Path:
    """OSごとのユーザーフォントディレクトリ（fontconfigが走査する場所）。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Fonts"
    return Path.home() / ".fonts"


def _ensure_music_font() -> None:
    """Leipzig が fontconfig から見えなければ同梱ttfを入れて fc-cache を更新する。

    初回のみ実行。失敗しても描画自体は続行する（テンポ記号が□になるだけ）。
    """
    global _font_checked
    if _font_checked:
        return
    _font_checked = True
    import shutil
    import subprocess

    try:
        listed = subprocess.run(
            ["fc-list"], capture_output=True, text=True, timeout=15
        ).stdout
        if _FONT_FAMILY.lower() in listed.lower():
            return  # 既に導入済み
        if not _BUNDLED_FONT.exists():
            return  # 同梱フォントが無い（想定外）— 黙って続行
        dest_dir = _user_font_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / _BUNDLED_FONT.name
        shutil.copyfile(_BUNDLED_FONT, dest)
        subprocess.run(["fc-cache", "-f", str(dest_dir)], timeout=30)
        print(f"楽譜フォント {_FONT_FAMILY} を導入しました: {dest}")
    except (OSError, subprocess.SubprocessError):
        pass  # fontconfig 未導入等。描画は続行（記号が□になる可能性）


def _load_toolkit(xml: str):
    """MusicXMLを読み込んだ verovio toolkit を返す。"""
    import verovio
    tk = verovio.toolkit()
    tk.setOptions(VEROVIO_OPTIONS)
    tk.loadData(xml)
    return tk


def musicxml_to_svg(xml: str) -> str:
    """MusicXML文字列を1ページ目のSVG文字列に変換する。"""
    return _load_toolkit(xml).renderToSVG(1)


def musicxml_to_pdf(xml: str) -> bytes:
    """MusicXML文字列を全ページ束ねたPDF(bytes)に変換する。

    verovioで各ページをSVG化 → cairosvgでページごとにPDF化 → pypdfで結合。
    MuseScore CLIがDarwin 25.5でクラッシュするため、印刷・共有用はこの経路を使う。
    """
    import io
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    _ensure_music_font()
    tk = _load_toolkit(xml)
    writer = PdfWriter()
    for page in range(1, tk.getPageCount() + 1):
        svg = tk.renderToSVG(page)
        page_pdf = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
        for p in PdfReader(io.BytesIO(page_pdf)).pages:
            writer.add_page(p)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
