#!/usr/bin/env python3
"""
getaudio.py
-----------
動画URLから音声だけを抜き出して MP3 にするツール。

内部で yt-dlp（オープンソース）を使っている。
bandcopy.py の入力素材を用意する用途を想定しているが、単体でも使える。

使い方:
    python getaudio.py "https://..."
    python getaudio.py "https://..." --quality 320
    python getaudio.py "https://..." --start 1:20 --end 2:45
    python getaudio.py --list urls.txt
    python getaudio.py "https://..." --info

出力先:
    audio/ フォルダ（--outdir で変更可）

前提:
    ffmpeg がインストールされていること
      Mac      : brew install ffmpeg
      Windows  : winget install ffmpeg
      Ubuntu   : sudo apt install ffmpeg
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

# 時刻のパースは Web UI と共通（app/fetch.py が単一ソース）。
# 二重に持つと片方だけ直す事故が起きるため、ここでは再公開するだけにする。
from app.fetch import parse_timestamp


def check_requirements():
    """yt-dlp と ffmpeg が使えるか確認する"""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print("yt-dlp が入っていません。以下を実行してください:\n")
        print("    pip install yt-dlp\n")
        sys.exit(1)

    if not shutil.which("ffmpeg"):
        print("ffmpeg が見つかりません。MP3変換に必要です。\n")
        print("    Mac     : brew install ffmpeg")
        print("    Windows : winget install ffmpeg")
        print("    Ubuntu  : sudo apt install ffmpeg\n")
        sys.exit(1)


def sanitize(name: str) -> str:
    """ファイル名に使えない文字を除去し、後段の処理で困らない名前にする"""
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:80] or "audio"


def show_info(url: str):
    """ダウンロードせずに動画の情報だけ表示する"""
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    if "entries" in info:
        entries = [e for e in info["entries"] if e]
        print(f"プレイリスト: {info.get('title', '(不明)')}")
        print(f"件数: {len(entries)}\n")
        for i, e in enumerate(entries[:30], 1):
            dur = e.get("duration") or 0
            print(f"  {i:3d}. {e.get('title', '(不明)')}  [{int(dur)//60}:{int(dur)%60:02d}]")
        if len(entries) > 30:
            print(f"  ... 他 {len(entries) - 30} 件")
    else:
        dur = info.get("duration") or 0
        print(f"タイトル : {info.get('title', '(不明)')}")
        print(f"投稿者   : {info.get('uploader', '(不明)')}")
        print(f"長さ     : {int(dur)//60}分{int(dur)%60:02d}秒")
        print(f"アップ日 : {info.get('upload_date', '(不明)')}")
        lic = info.get("license")
        if lic:
            print(f"ライセンス: {lic}")


def build_options(args, outdir: Path) -> dict:
    """yt-dlp に渡す設定を組み立てる"""
    postprocessors = [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": str(args.quality),
        },
        {"key": "FFmpegMetadata"},  # タイトル等をMP3のタグに埋め込む
    ]

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(outdir / "%(title)s.%(ext)s"),
        "postprocessors": postprocessors,
        "quiet": False,
        "no_warnings": False,
        "noplaylist": not args.playlist,
        "ignoreerrors": True,
        "retries": 3,
        "concurrent_fragment_downloads": 4,
    }

    # 部分切り出し（サビだけ欲しい、練習箇所だけ欲しい、など）
    start = parse_timestamp(args.start)
    end = parse_timestamp(args.end)
    if start is not None or end is not None:
        opts["download_ranges"] = lambda info, ydl: [{
            "start_time": start or 0,
            "end_time": end if end is not None else (info.get("duration") or 1e9),
        }]
        opts["force_keyframes_at_cuts"] = True

    if args.ascii_name:
        opts["outtmpl"] = str(outdir / "%(id)s.%(ext)s")

    return opts


def download(urls, args, outdir: Path):
    import yt_dlp

    before = set(outdir.glob("*.mp3"))
    opts = build_options(args, outdir)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(urls)

    after = set(outdir.glob("*.mp3"))
    new_files = sorted(after - before)

    if not new_files:
        print("\nMP3が作成されませんでした。URLと ffmpeg の状態を確認してください。")
        return []

    print(f"\n{'=' * 52}")
    print(f"完了: {len(new_files)}件")
    for f in new_files:
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  {f.name}  ({size_mb:.1f} MB)")
    print(f"\n保存先: {outdir}")
    print("=" * 52)
    return new_files


def main():
    parser = argparse.ArgumentParser(
        description="動画URLから音声を抜き出してMP3にする"
    )
    parser.add_argument("url", nargs="?", help="動画またはプレイリストのURL")
    parser.add_argument(
        "--list", metavar="FILE",
        help="URLを1行ずつ書いたテキストファイルを指定して一括処理"
    )
    parser.add_argument(
        "--quality", type=int, default=192, choices=[128, 192, 256, 320],
        help="MP3のビットレート（既定: 192）。分離・採譜用途なら 256 以上を推奨"
    )
    parser.add_argument("--start", help="切り出し開始位置（例: 1:20）")
    parser.add_argument("--end", help="切り出し終了位置（例: 2:45）")
    parser.add_argument(
        "--playlist", action="store_true",
        help="プレイリストURLの場合、全曲をダウンロードする"
    )
    parser.add_argument(
        "--ascii-name", action="store_true",
        help="ファイル名を動画IDにする（日本語名で後続処理がコケる場合に使用）"
    )
    parser.add_argument("--outdir", default="audio", help="出力先（既定: audio）")
    parser.add_argument(
        "--info", action="store_true",
        help="ダウンロードせず、動画の情報だけ表示する"
    )
    args = parser.parse_args()

    if not args.url and not args.list:
        parser.print_help()
        sys.exit(1)

    check_requirements()

    if args.info:
        show_info(args.url)
        return

    # 対象URLの収集
    if args.list:
        list_path = Path(args.list)
        if not list_path.exists():
            print(f"ファイルが見つかりません: {list_path}")
            sys.exit(1)
        urls = [
            line.strip() for line in list_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        print(f"リストから {len(urls)} 件のURLを読み込みました")
    else:
        urls = [args.url]

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"音質: {args.quality} kbps / 出力先: {outdir}\n")
    download(urls, args, outdir)


if __name__ == "__main__":
    main()
