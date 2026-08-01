import io
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


def test_post_export_midi_returns_smf():
    grid = make_template_grid(100.0, 1)
    r = _client().post("/export/midi", json=grid)
    assert r.status_code == 200
    assert r.data[:4] == b"MThd"
    assert "drums.mid" in r.headers["Content-Disposition"]
    assert r.mimetype == "audio/midi"


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


def test_auto_draft_400_when_separation_calls_sys_exit(monkeypatch, tmp_path):
    # Demucs失敗時 separate_stems は sys.exit(1)＝SystemExit。500ではなく400を返すこと
    def bail(*a, **k):
        raise SystemExit(1)

    monkeypatch.setattr("app.server.transcribe_drums", bail)
    stem_path = tmp_path / "drums.wav"
    stem_path.write_bytes(b"RIFF0000WAVE")
    state = {"grid": {"tempo": 120.0, "bars": 1, "steps_per_bar": 16, "lanes": {}},
             "stem_path": str(stem_path), "audio_path": None}
    res = create_app(state).test_client().post("/auto-draft")
    assert res.status_code == 400
    assert "自動採譜に失敗しました" in res.get_json()["error"]


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


def test_upload_html_disables_submit_button_during_request():
    """多重送信防止：送信中はボタンをdisabledにし、失敗時は再度押せるように戻すこと"""
    html = Path("app/templates/upload.html").read_text()
    assert "submitBtn.disabled = true" in html
    assert "submitBtn.disabled = false" in html


def test_index_shows_upload_page_when_no_grid_loaded():
    state = {"grid": None, "stem_path": None}
    r = create_app(state).test_client().get("/")
    assert "アップロード" in r.get_data(as_text=True)


def test_index_shows_editor_page_when_grid_loaded():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": None}
    r = create_app(state).test_client().get("/")
    assert "ドラムエディタ" in r.get_data(as_text=True)
    assert "アップロード" not in r.get_data(as_text=True)


def test_load_audio_without_file_returns_400():
    state = {"grid": None, "stem_path": None}
    r = create_app(state).test_client().post(
        "/load", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_load_audio_updates_state_and_returns_ok(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    fake_stem = tmp_path / "drums.wav"
    fake_stem.write_bytes(b"RIFF0000WAVE")
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)
    monkeypatch.setattr("app.server.separate_drum_stem", lambda p, d: str(fake_stem))
    state = {"grid": None, "stem_path": None, "audio_path": None}
    client = create_app(state).test_client()
    data = {"audio": (io.BytesIO(b"fake wav data"), "song.wav")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    assert state["grid"] == fake_grid
    assert state["stem_path"] == str(fake_stem)
    assert state["audio_path"].endswith("song.wav")
    assert state["grid_save_path"] is not None
    assert "song" in state["grid_save_path"]
    assert state["grid_save_path"].endswith("drum_grid.json")
    assert (tmp_path / "output" / "_upload" / "song.wav").exists()


def test_load_audio_failure_returns_400(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def boom(p):
        raise RuntimeError("解析エラー")

    monkeypatch.setattr("app.server.build_template_from_audio", boom)
    state = {"grid": None, "stem_path": None}
    client = create_app(state).test_client()
    data = {"audio": (io.BytesIO(b"x"), "a.wav")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_load_audio_systemexit_from_separation_returns_400(monkeypatch, tmp_path):
    """separate_drum_stem（Demucs呼び出し）がsys.exit(1)しても500ではなく400+日本語になること"""
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)

    def boom(*a, **k):
        raise SystemExit(1)

    monkeypatch.setattr("app.server.separate_drum_stem", boom)
    state = {"grid": None, "stem_path": None, "audio_path": None}
    client = create_app(state).test_client()
    data = {"audio": (io.BytesIO(b"fake wav data"), "song.wav")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_upload_html_uses_custom_base(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {"grid": None, "stem_path": None, "base": "/editor/"}
    r = create_app(state).test_client().get("/")
    html = r.get_data(as_text=True)
    assert '<base href="/editor/">' in html
    assert 'href="../"' in html


def test_load_audio_sanitizes_absolute_path_filename(monkeypatch, tmp_path):
    """絶対パスファイル名が upload_dir に留まること（パストラバーサル防止）"""
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    fake_stem = tmp_path / "drums.wav"
    fake_stem.write_bytes(b"RIFF0000WAVE")
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)
    monkeypatch.setattr("app.server.separate_drum_stem", lambda p, d: str(fake_stem))
    state = {"grid": None, "stem_path": None, "audio_path": None}
    client = create_app(state).test_client()
    # クライアントから /etc/passwd のような絶対パスが送られてくる（攻撃）
    data = {"audio": (io.BytesIO(b"fake wav data"), "/etc/passwd")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    # ファイルが output/_upload 配下に保存されていること、/etc 配下ではないこと
    saved_audio_path = state["audio_path"]
    upload_dir_resolved = (tmp_path / "output" / "_upload").resolve()
    saved_path_resolved = Path(saved_audio_path).resolve()
    # ファイルが upload_dir 内にあることを確認
    assert upload_dir_resolved in saved_path_resolved.parents
    # saved_path_resolved が /etc で始まっていないことを確認
    assert not str(saved_path_resolved).startswith("/etc")


def test_load_audio_sanitizes_dotdot_path_segment(monkeypatch, tmp_path):
    """.. セグメントがあるファイル名が上位ディレクトリにエスケープしないこと"""
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    fake_stem = tmp_path / "drums.wav"
    fake_stem.write_bytes(b"RIFF0000WAVE")
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)
    monkeypatch.setattr("app.server.separate_drum_stem", lambda p, d: str(fake_stem))
    state = {"grid": None, "stem_path": None, "audio_path": None}
    client = create_app(state).test_client()
    # ファイル名が .. を含む
    data = {"audio": (io.BytesIO(b"fake wav data"), "../../escaped.wav")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    # ファイルが output/_upload 配下に保存されていること
    saved_audio_path = state["audio_path"]
    assert (tmp_path / "output" / "_upload").resolve() in Path(saved_audio_path).resolve().parents


def test_load_audio_sanitizes_empty_filename_to_default(monkeypatch, tmp_path):
    """サニタイズ後に空になるファイル名がデフォルト名になること"""
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    fake_stem = tmp_path / "drums.wav"
    fake_stem.write_bytes(b"RIFF0000WAVE")
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)
    monkeypatch.setattr("app.server.separate_drum_stem", lambda p, d: str(fake_stem))
    state = {"grid": None, "stem_path": None, "audio_path": None}
    client = create_app(state).test_client()
    # ファイル名が .. や / だけ（サニタイズ後は空）
    data = {"audio": (io.BytesIO(b"fake wav data"), "..")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    # デフォルト名 "upload" が使われていること
    saved_audio_path = state["audio_path"]
    assert Path(saved_audio_path).name == "upload"
    assert (tmp_path / "output" / "_upload" / "upload").exists()


def test_reset_clears_loaded_song_state():
    state = {"grid": make_template_grid(100.0, 1), "stem_path": "/tmp/d.wav",
             "audio_path": "/tmp/song.wav", "grid_save_path": "/tmp/drum_grid.json"}
    client = create_app(state).test_client()
    r = client.post("/reset")
    assert r.status_code == 200
    assert state["grid"] is None
    assert state["stem_path"] is None
    assert state["audio_path"] is None
    assert state["grid_save_path"] is None
    # リセット後は / がアップロード画面を返す
    r2 = client.get("/")
    assert "アップロード" in r2.get_data(as_text=True)


def test_load_audio_japanese_filename_keeps_extension_and_distinct_path(monkeypatch, tmp_path):
    """日本語ファイル名でも拡張子が保たれ、他とは衝突しないパスになること"""
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    fake_stem = tmp_path / "drums.wav"
    fake_stem.write_bytes(b"RIFF0000WAVE")
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)
    monkeypatch.setattr("app.server.separate_drum_stem", lambda p, d: str(fake_stem))
    state = {"grid": None, "stem_path": None, "audio_path": None}
    client = create_app(state).test_client()
    data = {"audio": (io.BytesIO(b"fake wav data"), "リハ音源2026.m4a")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    saved_path = Path(state["audio_path"])
    assert saved_path.suffix == ".m4a"
    upload_dir_resolved = (tmp_path / "output" / "_upload").resolve()
    assert upload_dir_resolved in saved_path.resolve().parents


def test_load_audio_two_different_japanese_filenames_do_not_collide(monkeypatch, tmp_path):
    """異なる日本語ファイル名が同じ保存先に衝突しないこと"""
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    fake_stem = tmp_path / "drums.wav"
    fake_stem.write_bytes(b"RIFF0000WAVE")
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)
    monkeypatch.setattr("app.server.separate_drum_stem", lambda p, d: str(fake_stem))

    state1 = {"grid": None, "stem_path": None, "audio_path": None}
    client1 = create_app(state1).test_client()
    data1 = {"audio": (io.BytesIO(b"fake wav data 1"), "曲.mp3")}
    r1 = client1.post("/load", data=data1, content_type="multipart/form-data")
    assert r1.status_code == 200

    state2 = {"grid": None, "stem_path": None, "audio_path": None}
    client2 = create_app(state2).test_client()
    data2 = {"audio": (io.BytesIO(b"fake wav data 2"), "サビ.wav")}
    r2 = client2.post("/load", data=data2, content_type="multipart/form-data")
    assert r2.status_code == 200

    assert state1["audio_path"] != state2["audio_path"]
    assert Path(state1["audio_path"]).suffix == ".mp3"
    assert Path(state2["audio_path"]).suffix == ".wav"


def test_load_audio_sets_grid_save_path_from_sanitized_filename(monkeypatch, tmp_path):
    """grid_save_path が (サニタイズ後の) ファイル名の stem から導出されること"""
    monkeypatch.chdir(tmp_path)
    fake_grid = make_template_grid(100.0, 1)
    fake_stem = tmp_path / "drums.wav"
    fake_stem.write_bytes(b"RIFF0000WAVE")
    monkeypatch.setattr("app.server.build_template_from_audio", lambda p: fake_grid)
    monkeypatch.setattr("app.server.separate_drum_stem", lambda p, d: str(fake_stem))
    state = {"grid": None, "stem_path": None, "audio_path": None, "grid_save_path": None}
    client = create_app(state).test_client()
    data = {"audio": (io.BytesIO(b"fake wav data"), "song.wav")}
    r = client.post("/load", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    assert state["grid_save_path"] is not None
    assert "song" in state["grid_save_path"]
    assert state["grid_save_path"].endswith("drum_grid.json")
