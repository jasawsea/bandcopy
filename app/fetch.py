"""動画URLから音源を取り込む（yt-dlp）。

**2つの入口が同じ処理を使う**ので、ここを単一ソースにしている。
  - みんな用Gradio（`app/webapp.py`）
  - ドラムエディタ（`app/server.py` の `POST /load`）
CLI の `getaudio.py` は切り出し・音質指定など単体ツールとしての機能を持つので
別実装のまま（こちらはWeb UIが必要とする最小限だけを担う）。
"""
from pathlib import Path


def build_fetch_options(outdir, quality=192):
    """URL取り込み用の yt-dlp 設定を組み立てる（テスト容易性のため分離）。

    **ファイル名は動画ID**（`%(id)s`）にする。日本語タイトルのまま保存すると
    Demucs のパス処理で失敗することがあるため（CLAUDE.md の既知の注意点）。
    CLI の `getaudio.py --ascii-name` と同じ扱い。

    **noplaylist=True が要**：`&list=RD...` 付きのURL（YouTubeの自動生成
    ミックス等）をそのまま貼られたとき、外すと再生リスト全曲を落としてしまう。
    """
    return {
        "format": "bestaudio/best",
        "outtmpl": str(Path(outdir) / "%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
             "preferredquality": str(quality)},
            {"key": "FFmpegMetadata"},
        ],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
    }


def fetch_audio_from_url(url, outdir="audio", quality=192, ydl_factory=None):
    """動画URLから音声を取り出し、(MP3のパス, タイトル) を返す。

    ydl_factory はテスト用の差し替え口（既定は yt_dlp.YoutubeDL）。
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if ydl_factory is None:
        import yt_dlp
        ydl_factory = yt_dlp.YoutubeDL

    with ydl_factory(build_fetch_options(outdir, quality)) as ydl:
        info = ydl.extract_info(url, download=True)

    if not info or not info.get("id"):
        raise ValueError("動画の情報を取得できませんでした。URLを確認してください。")
    path = outdir / f"{info['id']}.mp3"
    if not path.exists():
        raise FileNotFoundError(
            "音声の取り出しに失敗しました（ffmpeg が入っているか確認してください）。")
    return str(path), info.get("title") or info["id"]
