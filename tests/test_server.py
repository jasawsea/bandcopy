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
