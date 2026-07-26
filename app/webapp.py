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


def build_ui():
    """Gradio の Blocks を組み立てて返す（起動は別途 .launch()）。"""
    import gradio as gr

    with gr.Blocks(title="bandcopy") as demo:
        gr.Markdown(
            "# bandcopy — バンドコピー支援\n"
            "自分の手持ち音源をアップロードすると、**演奏しやすい難易度に落とした"
            "楽譜・タブ譜**と**パート別の練習音源**を作ります。個人練習用。")
        with gr.Row():
            audio = gr.Audio(type="filepath", label="音源をアップロード（MP3 / WAV / M4A）")
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

        def _run(audio_path, lv, s):
            if not audio_path:
                return "音源をアップロードしてください。", None, None, None, None
            r = process(audio_path, level=int(lv), six=bool(s))
            return (r["message"], r["preview"], r["band_pdf"],
                    r["tab_pdfs"], r["stems_zip"])

        run.click(_run, [audio, level, six],
                  [message, preview, band_file, tab_files, stems_file])

    return demo
