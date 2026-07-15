import os
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SOURCE_URL = os.getenv("SOURCE_URL")
SEGMENT_TIME = int(os.getenv("SEGMENT_TIME", "30"))
VIDEOS_DIR = BASE_DIR / "data" / "videos_mp4"

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


def run_segmenter() -> int:
    if not SOURCE_URL:
        raise RuntimeError("SOURCE_URL is not set")

    output_pattern = str(VIDEOS_DIR / "segment_%Y%m%d_%H%M%S.mp4")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-i",
        SOURCE_URL,
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(SEGMENT_TIME),
        "-reset_timestamps",
        "1",
        "-strftime",
        "1",
        output_pattern,
    ]

    print(f"Starting segmenter on {SOURCE_URL}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    while True:
        try:
            rc = run_segmenter()
            print("FFmpeg exited with code:", rc)
        except Exception as exc:
            print("Segmenter crashed:", exc)

        time.sleep(5)
