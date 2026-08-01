"""1URL・独立タブでみんな用GradioとドラムエディタをまとめてサーブするFastAPIエントリ。

起動: ./venv/bin/python serve_all.py
      PORT環境変数でポート変更可（既定7860）。
"""
import os

from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware

from app.server import create_app
from app.webapp import build_ui


def build_app() -> FastAPI:
    """FastAPIアプリを組み立てて返す（起動はしない。テスト用に分離）。"""
    app = FastAPI()

    editor_state = {
        "grid": None,
        "stem_path": None,
        "audio_path": None,
        "grid_save_path": None,
        "base": "/editor/",
    }
    # starlette.middleware.wsgi.WSGIMiddleware はstarlette 1.x でDeprecated
    # （将来削除予定・現行では動作する）。新規依存を避けるためこのまま使用。
    app.mount("/editor", WSGIMiddleware(create_app(editor_state)))

    import gradio as gr
    gr.mount_gradio_app(app, build_ui(), path="/")

    return app


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(build_app(), host="0.0.0.0", port=port)
