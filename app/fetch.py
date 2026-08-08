"""動画URLから音源を取り込む（yt-dlp）。

**2つの入口が同じ処理を使う**ので、ここを単一ソースにしている。
  - みんな用Gradio（`app/webapp.py`）
  - ドラムエディタ（`app/server.py` の `POST /load`）
CLI の `getaudio.py` は切り出し・音質指定など単体ツールとしての機能を持つので
別実装のまま（こちらはWeb UIが必要とする最小限だけを担う）。
"""
from pathlib import Path


def parse_timestamp(value):
    """'1:20' / '01:02:03' / '95' を秒数に変換する。空や None は None。

    ※ `getaudio.py`（CLI）にも同じ関数があったが、Web UI からも使うので
      こちらを単一ソースにして CLI 側から import している。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"時間の指定が不正です: {value}（例: 1:20 / 01:02:03 / 95）")
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"時間の指定が不正です: {value}")


def validate_range(start, end):
    """開始・終了（秒）の妥当性を見る。おかしければ日本語で例外を投げる。"""
    if start is not None and start < 0:
        raise ValueError("開始位置に負の数は指定できません。")
    if end is not None and end < 0:
        raise ValueError("終了位置に負の数は指定できません。")
    if start is not None and end is not None and end <= start:
        raise ValueError("終了位置は開始位置より後にしてください。")
    return start, end


def build_fetch_options(outdir, quality=192, start=None, end=None):
    """URL取り込み用の yt-dlp 設定を組み立てる（テスト容易性のため分離）。

    **ファイル名は動画ID**（`%(id)s`）にする。日本語タイトルのまま保存すると
    Demucs のパス処理で失敗することがあるため（CLAUDE.md の既知の注意点）。
    CLI の `getaudio.py --ascii-name` と同じ扱い。

    **noplaylist=True が要**：`&list=RD...` 付きのURL（YouTubeの自動生成
    ミックス等）をそのまま貼られたとき、外すと再生リスト全曲を落としてしまう。
    """
    opts = {
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
    # 部分だけ落とす（サビだけ練習したい等）。どちらか片方だけの指定も許す。
    if start is not None or end is not None:
        opts["download_ranges"] = lambda info, ydl: [{
            "start_time": start or 0,
            "end_time": end if end is not None else (info.get("duration") or 1e9),
        }]
        opts["force_keyframes_at_cuts"] = True
    return opts


def fetch_audio_from_url(url, outdir="audio", quality=192, start=None, end=None,
                         ydl_factory=None):
    """動画URLから音声を取り出し、(MP3のパス, タイトル) を返す。

    start / end は '1:20' 形式でも秒数でも可。指定するとその区間だけ落とす。
    ydl_factory はテスト用の差し替え口（既定は yt_dlp.YoutubeDL）。
    """
    start, end = validate_range(parse_timestamp(start), parse_timestamp(end))
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if ydl_factory is None:
        import yt_dlp
        ydl_factory = yt_dlp.YoutubeDL

    with ydl_factory(build_fetch_options(outdir, quality, start, end)) as ydl:
        info = ydl.extract_info(url, download=True)

    if not info or not info.get("id"):
        raise ValueError("動画の情報を取得できませんでした。URLを確認してください。")
    path = outdir / f"{info['id']}.mp3"
    if not path.exists():
        raise FileNotFoundError(
            "音声の取り出しに失敗しました（ffmpeg が入っているか確認してください）。")
    return str(path), info.get("title") or info["id"]
