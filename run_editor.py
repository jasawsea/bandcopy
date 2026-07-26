"""ドラムエディタを起動する。使い方: ./venv/bin/python run_editor.py <音源ファイル>

環境変数 EDITOR_STEM に既存のドラムWAVを指定すると、Demucs分離を省略して
そのまま再生用に使う（再起動を速くするための近道）。
"""
import os
import sys
from pathlib import Path

from app.analyze import build_template_from_audio, separate_drum_stem
from app.server import create_app


def main():
    if len(sys.argv) < 2:
        print("使い方: ./venv/bin/python run_editor.py <音源ファイル>")
        sys.exit(1)
    audio = sys.argv[1]
    print("テンポ解析中...")
    grid = build_template_from_audio(audio)

    preset = os.environ.get("EDITOR_STEM")
    if preset and Path(preset).exists():
        print(f"既存のドラム音源を使用: {preset}")
        stem = preset
    else:
        print("ドラム分離中（初回はモデルDLで数分）...")
        try:
            stem = separate_drum_stem(audio, Path("output") / "_editor")
        except Exception as e:
            print(f"分離に失敗（再生なしで続行）: {e}")
            stem = None

    app = create_app({"grid": grid, "stem_path": stem})
    port = int(os.environ.get("PORT", 5000))
    print(f"http://127.0.0.1:{port} を開いてください")
    app.run(port=port, debug=False)


if __name__ == "__main__":
    main()
