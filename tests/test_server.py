from pathlib import Path

from app.grid import make_template_grid
from app.server import create_app


def _client():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None}
    return create_app(state).test_client()


def test_get_grid_returns_json():
    r = _client().get("/grid")
    assert r.status_code == 200
    data = r.get_json()
    assert data["bars"] == 1 and "KK" in data["lanes"]


def test_post_render_returns_svg():
    grid = make_template_grid(100.0, 1)
    r = _client().post("/render", json=grid)
    assert r.status_code == 200
    assert "svg" in r.get_data(as_text=True)[:200].lower()


def test_post_export_musicxml():
    grid = make_template_grid(100.0, 1)
    r = _client().post("/export/musicxml", json=grid)
    assert r.status_code == 200
    assert "<score-partwise" in r.get_data(as_text=True)


def test_stem_serves_relative_path(tmp_path, monkeypatch):
    # 相対パスでも配信できること（send_fileはapp基準で解決するため絶対化が必要）
    (tmp_path / "d.wav").write_bytes(b"RIFF0000WAVE")
    monkeypatch.chdir(tmp_path)
    state = {"grid": make_template_grid(100.0, 1), "stem_path": "d.wav"}
    r = create_app(state).test_client().get("/stem")
    assert r.status_code == 200


def test_stem_missing_returns_404():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None}
    r = create_app(state).test_client().get("/stem")
    assert r.status_code == 404


def test_simplify_thin_kicks_returns_new_grid():
    grid = make_template_grid(100.0, 1)
    grid["lanes"]["KK"] = [1, 1, 1, 0] + [0] * 12
    r = _client().post("/simplify", json={"command": "thin_kicks", "grid": grid})
    assert r.status_code == 200
    assert r.get_json()["lanes"]["KK"][:4] == [1, 0, 0, 0]


def test_simplify_thin_hihat_returns_new_grid():
    grid = make_template_grid(100.0, 1)
    grid["lanes"]["HH"] = [1] * 16
    r = _client().post("/simplify", json={"command": "thin_hihat", "grid": grid})
    assert r.status_code == 200
    assert r.get_json()["lanes"]["HH"] == [1 if s % 2 == 0 else 0 for s in range(16)]


def test_simplify_unknown_command_returns_400():
    grid = make_template_grid(100.0, 1)
    r = _client().post("/simplify", json={"command": "nope", "grid": grid})
    assert r.status_code == 400


def test_save_grid_writes_json_file(tmp_path):
    import json
    save_path = tmp_path / "drum_grid.json"
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None,
             "grid_save_path": str(save_path)}
    grid = make_template_grid(100.0, 1)
    grid["lanes"]["KK"] = [1, 1, 0, 0] + [0] * 12
    r = create_app(state).test_client().post("/save-grid", json=grid)
    assert r.status_code == 200
    assert save_path.exists()
    saved = json.loads(save_path.read_text())
    assert saved["lanes"]["KK"] == [1, 1, 0, 0] + [0] * 12


def test_save_grid_without_configured_path_returns_400():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None}
    r = create_app(state).test_client().post("/save-grid",
                                             json=make_template_grid(100.0, 1))
    assert r.status_code == 400


def test_auto_draft_uses_stem_and_returns_grid(monkeypatch, tmp_path):
    fake = {"tempo": 120.0, "bars": 1, "steps_per_bar": 16,
            "lanes": {k: [0] * 16 for k in ("HH", "HT", "MT", "FT", "SN", "KK")}}
    fake["lanes"]["KK"][0] = 1
    called = {}

    def fake_transcribe(stem, tempo, bars, steps_per_bar=16):
        called["stem"] = stem
        called["tempo"] = tempo
        called["bars"] = bars
        return fake

    monkeypatch.setattr("app.server.transcribe_drums", fake_transcribe)
    stem_path = tmp_path / "drums.wav"
    stem_path.write_bytes(b"RIFF0000WAVE")
    state = {
        "grid": {"tempo": 120.0, "bars": 1, "steps_per_bar": 16, "lanes": {}},
        "stem_path": str(stem_path),
        "audio_path": "/tmp/song.mp3",
    }
    res = create_app(state).test_client().post("/auto-draft")
    assert res.status_code == 200
    assert res.get_json()["lanes"]["KK"][0] == 1
    assert called["stem"] == str(stem_path)        # 分離済みstemを使う
    assert called["tempo"] == 120.0 and called["bars"] == 1  # テンプレのtempo/barsを再利用


def test_auto_draft_400_when_no_stem_or_audio():
    state = {"grid": {"tempo": 120.0, "bars": 1, "steps_per_bar": 16, "lanes": {}},
             "stem_path": None, "audio_path": None}
    res = create_app(state).test_client().post("/auto-draft")
    assert res.status_code == 400


def test_auto_draft_400_when_transcription_fails(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("壊れた音源")

    monkeypatch.setattr("app.server.transcribe_drums", boom)
    stem_path = tmp_path / "drums.wav"
    stem_path.write_bytes(b"RIFF0000WAVE")
    state = {"grid": {"tempo": 120.0, "bars": 1, "steps_per_bar": 16, "lanes": {}},
             "stem_path": str(stem_path), "audio_path": None}
    res = create_app(state).test_client().post("/auto-draft")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_index_default_base_uses_root_and_relative_asset_paths():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None}
    r = create_app(state).test_client().get("/")
    html = r.get_data(as_text=True)
    assert '<base href="/">' in html
    assert 'href="static/editor.css"' in html
    assert 'src="static/editor.js"' in html
    assert 'src="stem"' in html


def test_index_custom_base_shown_in_head_and_back_link_appears():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None, "base": "/editor/"}
    r = create_app(state).test_client().get("/")
    html = r.get_data(as_text=True)
    assert '<base href="/editor/">' in html
    assert 'href="../"' in html


def test_editor_html_source_has_no_absolute_asset_paths():
    html = Path("app/templates/editor.html").read_text()
    assert 'href="/static' not in html
    assert 'src="/static' not in html
    assert 'src="/stem"' not in html


def test_editor_js_source_has_no_absolute_fetch_paths():
    js = Path("app/static/editor.js").read_text()
    assert 'fetch("/' not in js
