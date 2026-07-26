"""ローカルWebエディタのFlaskアプリ。HTTPの配線のみ。"""
import json
import os
from pathlib import Path

from flask import Flask, jsonify, request, Response, send_file, render_template

from app.grid import grid_to_musicxml
from app.render import musicxml_to_svg
from app.drum_simplify import thin_kicks, thin_hihat

# エディタの簡略化コマンド名 → 変換関数
SIMPLIFY_COMMANDS = {
    "thin_kicks": thin_kicks,
    "thin_hihat": thin_hihat,
}


def create_app(state: dict) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("editor.html")

    @app.get("/grid")
    def get_grid():
        return jsonify(state["grid"])

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

    @app.post("/export/musicxml")
    def export_musicxml():
        grid = request.get_json(force=True)
        xml = grid_to_musicxml(grid)
        return Response(
            xml,
            mimetype="application/vnd.recordare.musicxml+xml",
            headers={"Content-Disposition": "attachment; filename=drums.musicxml"},
        )

    @app.get("/stem")
    def stem():
        if not state.get("stem_path"):
            return ("no stem", 404)
        # send_file は相対パスをappパッケージ基準で解決するため、絶対パスに直す
        return send_file(os.path.abspath(state["stem_path"]), mimetype="audio/wav")

    return app
