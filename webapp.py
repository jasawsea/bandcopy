"""bandcopy Web UI をローカル起動する。

使い方: ./venv/bin/python webapp.py
（ブラウザで http://127.0.0.1:7860 を開く。PORT環境変数で変更可）
Colab では app/webapp.py の build_ui().launch(share=True) を使う。
"""
import os

from app.webapp import build_ui

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"http://127.0.0.1:{port} を開いてください")
    build_ui().launch(server_name="127.0.0.1", server_port=port, share=False)
