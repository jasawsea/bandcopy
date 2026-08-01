from fastapi.testclient import TestClient

from serve_all import build_app


def test_editor_route_mounted_and_returns_200():
    client = TestClient(build_app())
    r = client.get("/editor/")
    assert r.status_code == 200


def test_gradio_root_returns_200():
    client = TestClient(build_app())
    r = client.get("/")
    assert r.status_code == 200


def test_editor_grid_route_returns_json():
    client = TestClient(build_app())
    r = client.get("/editor/grid")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
