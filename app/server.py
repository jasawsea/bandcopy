"""ローカルWebエディタのFlaskアプリ。HTTPの配線のみ。"""
import os

from flask import Flask, jsonify, request, Response, send_file, render_template

from app.grid import grid_to_musicxml
from app.render import musicxml_to_svg


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
