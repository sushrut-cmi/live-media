import csv
import glob
import json
import os
import re
import time
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VIDEOS_DIR = DATA_DIR / "videos_mp4"
CSV_FILE = DATA_DIR / "segment_metadata.csv"
LATEST_JSON = DATA_DIR / "latest_metadata.json"
CURRENT_INGEST_FILE = DATA_DIR / "current_ingest.json"

# ---- AWS Bedrock (Amazon Nova) ----
# Nova Lite and Nova Pro are multimodal (video-capable); Nova Micro is text-only.
# Lite is the sensible default for high-volume per-segment analysis; override
# with BEDROCK_METADATA_MODEL_ID (e.g. us.amazon.nova-pro-v1:0) if you want more
# accuracy at higher cost.
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("BEDROCK_METADATA_MODEL_ID", "us.amazon.nova-lite-v1:0")

# Bedrock Converse accepts inline video bytes only up to a request-size limit.
# Larger segments fall back to placeholder metadata (or route via S3 — see note
# in process_segment). 30s "copy"-codec chunks are normally well under this.
MAX_INLINE_MB = int(os.getenv("MAX_INLINE_VIDEO_MB", "24"))

POLL_INTERVAL = 5
STABILITY_WAIT = 2
STABILITY_CHECKS = 5

SPORT_PROMPTS = {
    "football": """
Analyze this football segment and output ONLY valid JSON.

{
  "Headline": "",
  "tags": [],
  "description": "",
  "people_recognition": [],
  "transcription": "",
  "Priority": ""
}

Football-specific guidance:
- Focus on goals, assists, shots, saves, fouls, cards, substitutions, possession, build-up, set pieces, crowd reaction, and scoreline.
- Recognize players, teams, referee actions, and commentary.
- Put the most important event in Headline.
- Priority should be a highlight importance score from 1 to 10.
- 1 means most important highlight, 10 means least important.
- Output ONLY valid JSON.
""",
    "cricket": """
Analyze this cricket segment and output ONLY valid JSON.

{
  "Headline": "",
  "tags": [],
  "description": "",
  "people_recognition": [],
  "transcription": "",
  "Priority": ""
}

Cricket-specific guidance:
- Focus on wickets, boundaries, sixes, dot balls, over number, innings, run rate, partnership, batsman, bowler, umpire, fielding, and crowd reaction.
- Recognize players, teams, and spoken commentary.
- Put the most important event in Headline.
- Priority should be a highlight importance score from 1 to 10.
- 1 means most important highlight, 10 means least important.
- Output ONLY valid JSON.
""",
    "horse_racing": """
Analyze this horse racing segment and output ONLY valid JSON.

{
  "Headline": "",
  "tags": [],
  "description": "",
  "people_recognition": [],
  "transcription": "",
  "Priority": ""
}

Horse racing-specific guidance:
- Focus on race start, horse positions, leader changes, finish, jockeys, track conditions, lane position, odds movement, and winning margin.
- Recognize horses, jockeys, trainers, and commentary.
- Put the most important event in Headline.
- Priority should be a highlight importance score from 1 to 10.
- 1 means most important highlight, 10 means least important.
- Output ONLY valid JSON.
""",
    "generic": """
Analyze this sports/media segment and output ONLY valid JSON.

{
  "Headline": "",
  "tags": [],
  "description": "",
  "people_recognition": [],
  "transcription": "",
  "Priority": ""
}

Guidance:
- Extract the key event, important tags, visible people, and spoken commentary.
- Put the most important event in Headline.
- Priority should be a highlight importance score from 1 to 10.
- 1 means most important highlight, 10 means least important.
- Output ONLY valid JSON.
""",
}


def normalize_sport(value: str) -> str:
    s = (value or "football").strip().lower()
    s = s.replace("-", "_").replace(" ", "_")
    if s in {"football", "soccer"}:
        return "football"
    if s in {"cricket"}:
        return "cricket"
    if s in {"horse_racing", "horseracing", "horse_race"}:
        return "horse_racing"
    return "generic"


def load_current_config() -> dict:
    if not CURRENT_INGEST_FILE.exists():
        return {"sport_type": "football"}
    try:
        with open(CURRENT_INGEST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {"sport_type": "football"}
    except Exception:
        return {"sport_type": "football"}


def build_prompt(sport_type: str) -> str:
    return SPORT_PROMPTS.get(sport_type, SPORT_PROMPTS["generic"])


def build_client():
    try:
        # Credentials come from the standard AWS chain (env vars, profile, or
        # an attached IAM role). Long read timeout because video analysis can
        # take a while per segment.
        return boto3.client(
            "bedrock-runtime",
            region_name=AWS_REGION,
            config=BotoConfig(read_timeout=300, retries={"max_attempts": 3}),
        )
    except Exception as exc:
        print("Bedrock client unavailable; using fallback metadata:", exc)
        return None


client = build_client()


def wait_until_complete(path, wait=2, checks=5):
    last_size = -1
    for _ in range(checks):
        try:
            size = os.path.getsize(path)
            if size == last_size:
                return True
            last_size = size
            time.sleep(wait)
        except FileNotFoundError:
            return False
    return False


def extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None


def ensure_csv():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Always create a fresh CSV
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["index", "segment_name", "metadata"])


def load_processed():
    processed = set()
    if not CSV_FILE.exists():
        return processed

    try:
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("segment_name"):
                    processed.add(row["segment_name"])
    except Exception:
        pass

    return processed


def append_to_csv(index, segment_name, metadata_json):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([index, segment_name, json.dumps(metadata_json, ensure_ascii=False)])


def write_latest_snapshot(record):
    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump({"updated_at": time.time(), "latest": record}, f, ensure_ascii=False, indent=2)


def fallback_metadata(segment_name: str, sport_type: str):
    if sport_type == "cricket":
        return {
            "Headline": f"Cricket segment: {segment_name}",
            "tags": ["cricket", "segment"],
            "description": "Fallback metadata generated without model response.",
            "people_recognition": [],
            "transcription": "",
            "Priority": 5,
        }
    if sport_type == "horse_racing":
        return {
            "Headline": f"Horse racing segment: {segment_name}",
            "tags": ["horse_racing", "segment"],
            "description": "Fallback metadata generated without model response.",
            "people_recognition": [],
            "transcription": "",
            "Priority": 5,
        }
    return {
        "Headline": f"Football segment: {segment_name}",
        "tags": ["football", "segment"],
        "description": "Fallback metadata generated without model response.",
        "people_recognition": [],
        "transcription": "",
        "Priority": 5,
    }


def process_segment(file_path, index, config):
    segment_name = os.path.basename(file_path)
    sport_type = normalize_sport(config.get("sport_type", "football"))

    print(f"Processing: {segment_name} | sport={sport_type}")

    if not wait_until_complete(file_path, STABILITY_WAIT, STABILITY_CHECKS):
        print("File still being written.")
        return

    try:
        with open(file_path, "rb") as f:
            video_bytes = f.read()

        prompt = build_prompt(sport_type)

        if client is None:
            metadata = fallback_metadata(segment_name, sport_type)
        elif len(video_bytes) > MAX_INLINE_MB * 1024 * 1024:
            # Too large to send inline. To handle big segments, upload to S3 and
            # replace the "source" below with:
            #   {"s3Location": {"uri": "s3://bucket/key.mp4"}}
            print(
                f"Segment {segment_name} is {len(video_bytes)} bytes "
                f"(> {MAX_INLINE_MB}MB); using fallback metadata."
            )
            metadata = fallback_metadata(segment_name, sport_type)
        else:
            # Bedrock Converse API: a video content block + the text prompt.
            response = client.converse(
                modelId=MODEL_ID,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"video": {"format": "mp4", "source": {"bytes": video_bytes}}},
                            {"text": prompt},
                        ],
                    }
                ],
                inferenceConfig={"temperature": 0.1, "maxTokens": 2048},
            )

            text = response["output"]["message"]["content"][0]["text"].strip()
            json_text = extract_json(text)

            if not json_text:
                print("No valid JSON found.")
                print(text)
                metadata = fallback_metadata(segment_name, sport_type)
            else:
                metadata = json.loads(json_text)

        metadata["sport_type"] = sport_type

        record = {
            "index": index,
            "segment_name": segment_name,
            "sport_type": sport_type,
            "metadata": metadata,
            "video_url": f"/video/{segment_name}",
        }

        append_to_csv(index=index, segment_name=segment_name, metadata_json=metadata)
        write_latest_snapshot(record)

        print("Metadata appended")
    except Exception as exc:
        print("Error processing segment:", exc)


def main():
    print("Watching for new MP4 segments:", str(VIDEOS_DIR))
    ensure_csv()
    processed = set()
    idx = 1

    while True:
        try:
            config = load_current_config()
            mp4_files = sorted(glob.glob(str(VIDEOS_DIR / "*.mp4")))

            for mp4_file in mp4_files:
                segment_name = os.path.basename(mp4_file)
                if segment_name not in processed:
                    process_segment(mp4_file, idx, config)
                    processed.add(segment_name)
                    idx += 1

            time.sleep(POLL_INTERVAL)

        except Exception as exc:
            print("Watcher error:", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
