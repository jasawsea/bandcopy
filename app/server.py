"""ローカルWebエディタのFlaskアプリ。HTTPの配線のみ。"""
import hashlib
import json
import logging
import os
import re
from pathlib import Path

from flask import Flask, jsonify, request, Response, send_file, render_template
from werkzeug.utils import secure_filename

from app import lanes
from app.grid import grid_to_musicxml, grid_to_midi
from app.render import musicxml_to_svg
from app.drum_simplify import thin_kicks, thin_hihat
from app.drum_transcribe import transcribe_drums
from app.analyze import transcribe_drum_from_audio, build_template_from_audio, separate_drum_stem
from app.fetch import fetch_audio_from_url

logger = logging.getLogger(__name__)

# エディタの簡略化コマンド名 → 変換関数
SIMPLIFY_COMMANDS = {
    "thin_kicks": thin_kicks,
    "thin_hihat": thin_hihat,
}

# 拡張子として許可する形（英数字のみ・最大10文字）。それ以外は捨てる。
_SAFE_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,10}$")


def _sanitize_upload_filename(original_name: str) -> str:
    """アップロードされたファイル名を、パストラバーサル対策をしつつ拡張子を保って安全化する。

    secure_filename は非ASCII文字を丸ごと落とすため、日本語ファイル名だと拡張子
    まで失われたり（例：'曲.mp3' -> 'mp3'）、複数の日本語名が同じ結果に潰れて
    衝突したりする（例：'サビ.wav' と '曲.wav' がどちらも 'wav' になり得る）。
    非ASCIIを含む場合は、元のファイル名のハッシュから一意な名前を作り、拡張子は
    元のファイル名から別途取り出して検証のうえ付け直す。
    """
    original_name = original_name or ""
    # パス区切りを含んでいてもファイル名部分だけを見る
    name_only = os.path.basename(original_name.replace("\\", "/"))
    stem_orig, ext_orig = os.path.splitext(name_only)
    ext = ext_orig if _SAFE_EXT_RE.fullmatch(ext_orig) else ""

    if stem_orig and not stem_orig.isascii():
        digest = hashlib.sha1(original_name.encode("utf-8")).hexdigest()[:10]
        return f"upload_{digest}{ext}"

    safe = secure_filename(name_only)
    return safe or "upload"


def create_app(state: dict) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        base = state.get("base", "/")
        if not state.get("grid"):
            return render_template("upload.html", base=base)
        # レーン定義はサーバ側（app/lanes.py）を単一ソースにしてJSへ渡す
        return render_template("editor.html", base=base, lanes=lanes.editor_payload())

    @app.get("/grid")
    def get_grid():
        return jsonify(state["grid"])

    @app.post("/load")
    def load_audio():
        upload_dir = Path("output") / "_upload"
        upload_dir.mkdir(parents=True, exist_ok=True)
        url = (request.form.get("url") or "").strip()
        f = request.files.get("audio")

        if url:
            # URLが入っていればURLを優先する（両方来たときの挙動を決め打ちにする）
            try:
                fetched, _title = fetch_audio_from_url(
                    url, outdir=str(upload_dir),
                    start=request.form.get("start"), end=request.form.get("end"))
            except ValueError as e:
                # 時刻の書式ミス・範囲の矛盾は、何が悪いか本人に返す
                return (jsonify({"error": str(e)}), 400)
            except Exception:
                logger.exception("URLからの取り込みに失敗しました: %s", url)
                return (jsonify({"error": "URLから音源を取り込めませんでした"}), 400)
            audio_path = Path(fetched)
        elif f is not None:
            # ファイル名を安全化（パストラバーサル対策＋日本語名の拡張子・一意性を保つ）
            audio_path = upload_dir / _sanitize_upload_filename(f.filename)
            f.save(str(audio_path))
        else:
            return (jsonify({"error": "音源ファイルまたはURLがありません"}), 400)
        try:
            grid = build_template_from_audio(str(audio_path))
            stem = separate_drum_stem(str(audio_path), str(Path("output") / "_editor"))
        except (Exception, SystemExit):
            # separate_drum_stem の先（Demucs呼び出し）は失敗時にsys.exit(1)する箇所が
            # あり、SystemExitはBaseException派生でExceptionだけでは捕まらない。
            # ユーザーには一般化した日本語メッセージのみ返し、詳細はログに残す。
            logger.exception("音源の解析に失敗しました: %s", audio_path)
            return (jsonify({"error": "音源の解析に失敗しました"}), 400)
        state["grid"] = grid
        state["stem_path"] = stem
        state["audio_path"] = str(audio_path)
        state["grid_save_path"] = str(Path("output") / audio_path.stem / "drum_grid.json")
        return jsonify({"loaded": True})

    @app.post("/reset")
    def reset():
        state["grid"] = None
        state["stem_path"] = None
        state["audio_path"] = None
        state["grid_save_path"] = None
        return jsonify({"reset": True})

    @app.post("/render")
    def render():
        grid = request.get_json(force=True)
        svg = musicxml_to_svg(grid_to_musicxml(grid))
        return Response(svg, mimetype="image/svg+xml")

    @app.post("/simplify")
    def simplify():
        body = request.get_json(force=True)
        fn = SIMPLIFY_COMMANDS.get(body.get("command"))
        if fn is None:
            return (jsonify({"error": "unknown command"}), 400)
        return jsonify(fn(body["grid"]))

    @app.post("/save-grid")
    def save_grid():
        path = state.get("grid_save_path")
        if not path:
            return (jsonify({"error": "保存先が設定されていません"}), 400)
        grid = request.get_json(force=True)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")
        return jsonify({"saved": str(p)})

    @app.post("/auto-draft")
    def auto_draft():
        g = state.get("grid") or {}
        stem = state.get("stem_path")
        if not (stem and Path(stem).exists()) and not state.get("audio_path"):
            return (jsonify({"error": "ドラム音源が見つかりません"}), 400)
        try:
            if stem and Path(stem).exists():
                grid = transcribe_drums(stem, g.get("tempo", 120.0), g.get("bars", 1))
            else:
                grid = transcribe_drum_from_audio(state["audio_path"])
        except (Exception, SystemExit):
            # Demucs失敗時に separate_stems が sys.exit(1) するため SystemExit も拾う
            logger.exception("自動採譜に失敗")
            return (jsonify({"error": "自動採譜に失敗しました"}), 400)
        return jsonify(grid)

    @app.post("/export/musicxml")
    def export_musicxml():
        grid = request.get_json(force=True)
        xml = grid_to_musicxml(grid)
        return Response(
            xml,
            mimetype="application/vnd.recordare.musicxml+xml",
            headers={"Content-Disposition": "attachment; filename=drums.musicxml"},
        )

    @app.post("/export/midi")
    def export_midi():
        grid = request.get_json(force=True)
        data = grid_to_midi(grid)
        return Response(
            data,
            mimetype="audio/midi",
            headers={"Content-Disposition": "attachment; filename=drums.mid"},
        )

    @app.get("/stem")
    def stem():
        if not state.get("stem_path"):
            return ("no stem", 404)
        # send_file は相対パスをappパッケージ基準で解決するため、絶対パスに直す
        return send_file(os.path.abspath(state["stem_path"]), mimetype="audio/wav")

    return app
