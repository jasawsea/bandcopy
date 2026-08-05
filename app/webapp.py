"""bandcopy の Web UI（Gradio）。

音源をアップロードすると、分離→採譜→簡略化→楽譜/タブ/分離音源 を返す。
ローカルでも Google Colab でも同じ `build_ui()` を起動して使う。
非エンジニアのバンドメンバーが「アップロード→ボタン→ダウンロード」で完結する。
"""
import tempfile
import zipfile
from pathlib import Path


def _zip_dir(src_dir, dest_zip):
    """フォルダ直下のファイルを zip にまとめる。フォルダが無ければ None。"""
    src_dir = Path(src_dir)
    dest_zip = Path(dest_zip)
    if not src_dir.is_dir():
        return None
    files = [f for f in sorted(src_dir.iterdir()) if f.is_file()]
    if not files:
        return None
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, arcname=f.name)
    return str(dest_zip)


def build_fetch_options(outdir, quality=192):
    """URL取り込み用の yt-dlp 設定を組み立てる（テスト容易性のため分離）。

    **ファイル名は動画ID**（`%(id)s`）にする。日本語タイトルのまま保存すると
    Demucs のパス処理で失敗することがあるため（CLAUDE.md の既知の注意点）。
    CLI の `getaudio.py --ascii-name` と同じ扱い。

    **noplaylist=True が要**：`&list=RD...` 付きのURL（YouTubeの自動生成
    ミックス等）をそのまま貼られたとき、外すと再生リスト全曲を落としてしまう。
    """
    return {
        "format": "bestaudio/best",
        "outtmpl": str(Path(outdir) / "%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
             "preferredquality": str(quality)},
            {"key": "FFmpegMetadata"},
        ],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
    }


def fetch_audio_from_url(url, outdir="audio", quality=192, ydl_factory=None):
    """動画URLから音声を取り出し、(MP3のパス, タイトル) を返す。

    ydl_factory はテスト用の差し替え口（既定は yt_dlp.YoutubeDL）。
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if ydl_factory is None:
        import yt_dlp
        ydl_factory = yt_dlp.YoutubeDL

    with ydl_factory(build_fetch_options(outdir, quality)) as ydl:
        info = ydl.extract_info(url, download=True)

    if not info or not info.get("id"):
        raise ValueError("動画の情報を取得できませんでした。URLを確認してください。")
    path = outdir / f"{info['id']}.mp3"
    if not path.exists():
        raise FileNotFoundError(
            "音声の取り出しに失敗しました（ffmpeg が入っているか確認してください）。")
    return str(path), info.get("title") or info["id"]


def resolve_input(audio_path, url, outdir="audio", fetcher=None):
    """アップロードとURLのどちらを使うかを決め、(音源パス, 通知文) を返す。

    URLが入っていればURLを優先する（両方入っている場合の挙動を決め打ちにして
    「どっちが使われたか分からない」を避ける）。使えるものが無ければ (None, 案内文)。
    """
    fetcher = fetcher or fetch_audio_from_url
    url = (url or "").strip()
    if url:
        path, title = fetcher(url, outdir=outdir)
        note = f"「{title}」を取り込みました。"
        if audio_path:
            note += "（URLを優先し、アップロードした音源は使っていません）"
        return path, note
    if audio_path:
        return audio_path, ""
    return None, "音源をアップロードするか、動画URLを貼ってください。"


def process(audio_path, level=3, six=False, workdir=None):
    """1曲を処理し、ダウンロード用のファイル群を dict で返す。

    キー: message / preview(png) / band_pdf / tab_pdfs(list) / stems_zip
    （生成できなかったものは None / 空リスト）。
    """
    import cairosvg
    from bandcopy import run_pipeline
    from score_all import build_full_score_musicxml
    from app.render import musicxml_to_pdf, musicxml_to_svg
    from app.tab import midi_to_tab_musicxml
    from tab import resolve_tab_targets

    empty = {"message": "", "preview": None, "band_pdf": None,
             "tab_pdfs": [], "stems_zip": None}

    work = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="bandcopy_"))
    out_root = work / Path(audio_path).stem
    result = run_pipeline(audio_path, out_root, level=level, six=six)
    if not result["parts"]:
        return {**empty, "message": "採譜できるパートがありませんでした。"}

    web_dir = out_root / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    out = dict(empty)

    # バンド譜（PDF＋プレビュー画像）
    xml, _six, _bars, _tempo, _n = build_full_score_musicxml(
        out_root, level, audio=audio_path)
    if xml:
        band_pdf = web_dir / f"バンド譜_Lv{level}.pdf"
        band_pdf.write_bytes(musicxml_to_pdf(xml))
        out["band_pdf"] = str(band_pdf)
        preview = web_dir / "preview.png"
        cairosvg.svg2png(bytestring=musicxml_to_svg(xml).encode("utf-8"),
                         write_to=str(preview), output_width=1100)
        out["preview"] = str(preview)

    # タブ譜（ギター/ベース）
    for midi_path, instrument, label in resolve_tab_targets(out_root / "midi", level):
        txml = midi_to_tab_musicxml(midi_path, instrument)
        tab_pdf = web_dir / f"{label}_タブ_Lv{level}.pdf"
        tab_pdf.write_bytes(musicxml_to_pdf(txml))
        out["tab_pdfs"].append(str(tab_pdf))

    # 分離音源（練習用）zip
    out["stems_zip"] = _zip_dir(out_root / "stems", web_dir / "分離音源.zip")

    out["message"] = "✓ 完了しました。下のファイルをダウンロードしてください。"
    return out


def build_intro_markdown(editor_link: bool = False) -> str:
    """トップのMarkdown文言を組み立てる（テスト容易性のためbuild_uiから分離）。

    editor_link=True のときだけ /editor へのリンクを載せる。/editor がマウント
    されていない起動（standaloneのwebapp.py・Colabノート）ではリンクは404になる
    ため既定では出さない。
    """
    text = (
        "# bandcopy — バンドコピー支援\n"
        "**動画URLを貼る**か、**手持ちの音源をアップロード**すると、"
        "**演奏しやすい難易度に落とした楽譜・タブ譜**と"
        "**パート別の練習音源**を作ります。個人練習用。"
    )
    if editor_link:
        text += "\n\nドラムだけをグリッドで編集したい場合は[ドラム編集を開く](editor/)。"
    return text


def build_ui(editor_link: bool = False):
    """Gradio の Blocks を組み立てて返す（起動は別途 .launch()）。

    editor_link: Trueのとき、/editor マウント前提のリンク文言を載せる
    （serve_all.py が渡す）。standalone起動（webapp.py・Colab）は既定のFalseのまま。
    """
    import gradio as gr

    with gr.Blocks(title="bandcopy") as demo:
        gr.Markdown(build_intro_markdown(editor_link))
        url = gr.Textbox(
            label="動画URL（YouTube等）",
            placeholder="https://www.youtube.com/watch?v=... を貼り付け",
            info="URLを貼るとここから音源を取り込みます。手持ちのファイルを使うときは空のままで。")
        with gr.Row():
            audio = gr.Audio(type="filepath", label="または音源をアップロード（MP3 / WAV / M4A）")
            with gr.Column():
                level = gr.Slider(1, 5, value=3, step=1,
                                  label="難易度（1=最も簡単 / 5=原曲どおり）")
                six = gr.Checkbox(
                    label="ギターと鍵盤を別々の段に分ける（6分離・少し時間がかかる）")
                run = gr.Button("楽譜を作る", variant="primary")
        message = gr.Markdown()
        preview = gr.Image(label="バンド譜プレビュー", show_label=True)
        band_file = gr.File(label="バンド譜（PDF）")
        tab_files = gr.File(label="タブ譜（ギター/ベースのPDF）", file_count="multiple")
        stems_file = gr.File(label="パート別の練習音源（zip）")

        def _run(audio_path, url_text, lv, s):
            try:
                path, note = resolve_input(audio_path, url_text)
            except Exception as e:                       # 取り込み失敗は日本語で返す
                return f"取り込みに失敗しました: {e}", None, None, None, None
            if not path:
                return note, None, None, None, None
            r = process(path, level=int(lv), six=bool(s))
            msg = f"{note}\n\n{r['message']}" if note else r["message"]
            return (msg, r["preview"], r["band_pdf"],
                    r["tab_pdfs"], r["stems_zip"])

        run.click(_run, [audio, url, level, six],
                  [message, preview, band_file, tab_files, stems_file])

    return demo
