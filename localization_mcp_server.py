from mcp.server.fastmcp import FastMCP
import requests
import time
import subprocess
import logging
import os

# ---------------- LOGGER SETUP ---------------- #
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("mcp-debug")

# ---------------- MCP INIT ---------------- #
mcp = FastMCP("localization-tools")

API_KEY = "e5eb2e12-ec67-4513-a0bb-de1f9414354c"
if not API_KEY:
    raise ValueError("CAMB_API_KEY is not set")

HEADERS = {"x-api-key": API_KEY}
BASE = "https://client.camb.ai/apis"

LANGUAGE_MAP = {
    "english": 1,
    "spanish": 54,
    "hindi": 81,
    "tamil": 125,
}

VOICE_MAP = {
    "sushrut": 131875,
    "lekshmy": 144973,
}


def extract_audio(video_path: str, audio_path: str = "/tmp/extracted_audio.wav"):
    logger.info("Extracting audio from video...")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",  # change to libmp3lame if needed
            "-ar", "16000",
            "-ac", "1",
            audio_path,
        ]

        subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"Audio extracted → {audio_path}")

        return audio_path

    except subprocess.CalledProcessError as e:
        logger.exception("Audio extraction failed")
        raise


# ---------------- POLLING ---------------- #
# def _poll(url, task_id):
#     logger.info(f"Polling started → {url}/{task_id}")

#     while True:
#         try:
#             r = requests.get(
#                 f"{url}/{task_id}",
#                 headers=HEADERS,
#                 timeout=30
#             )
#             r.raise_for_status()

#             data = r.json()
#             logger.debug(f"Polling response: {data}")

#             status = data.get("status")
#             logger.info(f"Task {task_id} status: {status}")

#             if status in ["SUCCESS", "FAILED"]:
#                 return data

#         except Exception as e:
#             logger.exception(f"Polling error for task {task_id}: {e}")
#             return {"status": "FAILED", "error": str(e)}

#         time.sleep(2)

def _poll(url, task_id, max_attempts=50, sleep_sec=2):
    logger.info(f"Polling started → {url}/{task_id}")
    attempts = 0
    while attempts < max_attempts:
        try:
            r = requests.get(f"{url}/{task_id}", headers=HEADERS, timeout=60)
            r.raise_for_status()
            data = r.json()
            status = data.get("status")
            logger.info(f"Task {task_id} status: {status}")
            if status in ["SUCCESS", "FAILED"]:
                return data
        except requests.exceptions.RequestException as e:
            logger.warning(f"Transient polling error: {e}")
        attempts += 1
        time.sleep(sleep_sec)
    raise TimeoutError(f"Polling task {task_id} exceeded maximum attempts")
# ---------------- STEP 1: TRANSCRIBE ---------------- #
@mcp.tool(description="Step 1: Transcribe video (audio extracted automatically)")
# def transcribe_video(video_path: str, source_language: str):
#     logger.info("STEP 1: Transcription started")

#     try:
#         lang_code = LANGUAGE_MAP.get(source_language.lower())
#         if not lang_code:
#             raise ValueError(f"Unsupported language: {source_language}")

#         logger.debug(f"Language code resolved: {lang_code}")

#         # Extract audio first to avoid 413 error
#         audio_path = extract_audio(video_path)

#         with open(audio_path, "rb") as f:
#             logger.info("Uploading audio for transcription...")

#             r = requests.post(
#                 f"{BASE}/transcribe",
#                 files={"file": ("audio.wav", f, "audio/wav")},
#                 data={"language": str(lang_code)},
#                 headers=HEADERS,
#                 timeout=60
#             )

#         logger.debug(f"Response: {r.status_code} {r.text}")
#         r.raise_for_status()

#         task_id = r.json()["task_id"]
#         logger.info(f"Transcription task_id: {task_id}")

#         status = _poll(f"{BASE}/transcribe", task_id)

#         if status.get("status") != "SUCCESS":
#             raise RuntimeError(f"Transcription failed: {status}")

#         run_id = status["run_id"]

#         r = requests.get(
#             f"{BASE}/transcription-result/{run_id}",
#             headers=HEADERS,
#             timeout=120
#         )

#         logger.debug(f"Transcript response: {r.text}")
#         r.raise_for_status()

#         text = " ".join(seg["text"] for seg in r.json().get("transcript", []))

#         logger.info("Transcription completed successfully")

#         return {"transcription": text}

#     except Exception as e:
#         logger.exception("Transcription failed")
#         return {"error": str(e)}

@mcp.tool(description="Step 1: Transcribe video (audio extracted automatically)")
def transcribe_video(video_path: str, source_language: str):
    lang_code = LANGUAGE_MAP.get(source_language.lower())
    audio_path = extract_audio(video_path)

    # upload audio
    with open(audio_path, "rb") as f:
        r = requests.post(
            f"{BASE}/transcribe",
            files={"file": ("audio.wav", f, "audio/wav")},
            data={"language": str(lang_code)},
            headers=HEADERS,
            timeout=60
        )
    r.raise_for_status()
    task_id = r.json()["task_id"]

    # Return immediately, do not poll here
    return {"task_id": task_id}
@mcp.tool(description="Check transcription status")
def get_transcription_result(task_id: str):
    status = _poll(f"{BASE}/transcribe", task_id)
    if status.get("status") != "SUCCESS":
        return {"error": f"Transcription failed: {status}"}

    run_id = status["run_id"]
    r = requests.get(f"{BASE}/transcription-result/{run_id}", headers=HEADERS, timeout=120)
    r.raise_for_status()
    text = " ".join(seg["text"] for seg in r.json().get("transcript", []))
    return {"transcription": text}
# ---------------- STEP 2: TRANSLATE ---------------- #
@mcp.tool(description="Step 2: Translate text")
def translate_text(transcription: str, source_language: str, target_language: str):
    logger.info("STEP 2: Translation started")

    try:
        r = requests.post(
            f"{BASE}/translate",
            json={
                "source_language": LANGUAGE_MAP.get(source_language.lower()),
                "target_language": LANGUAGE_MAP.get(target_language.lower()),
                "texts": [transcription],
            },
            headers=HEADERS,
            timeout=60
        )

        logger.debug(f"Translate response: {r.status_code} {r.text}")
        r.raise_for_status()

        task_id = r.json()["task_id"]
        logger.info(f"Translation task_id: {task_id}")

        status = _poll(f"{BASE}/translate", task_id)

        if status.get("status") != "SUCCESS":
            raise RuntimeError(f"Translation failed: {status}")

        run_id = status["run_id"]

        r = requests.get(
            f"{BASE}/translation-result/{run_id}",
            headers=HEADERS,
            timeout=60
        )

        logger.debug(f"Translation result: {r.text}")
        r.raise_for_status()

        text = " ".join(r.json().get("texts", []))

        logger.info("Translation completed")

        return {"translated_text": text}

    except Exception as e:
        logger.exception("Translation failed")
        return {"error": str(e)}


# ---------------- STEP 3: TTS ---------------- #
@mcp.tool(description="Step 3: Generate TTS audio")
def generate_tts(translated_text: str, target_language: str, voice: str):
    logger.info("STEP 3: TTS started")

    try:
        audio_path = "/tmp/generated_audio.wav"

        r = requests.post(
            f"{BASE}/tts",
            json={
                "text": translated_text,
                "language": LANGUAGE_MAP.get(target_language.lower()),
                "voice_id": VOICE_MAP.get(voice.lower()),
            },
            headers=HEADERS,
            timeout=60
        )

        logger.debug(f"TTS response: {r.status_code} {r.text}")
        r.raise_for_status()

        task_id = r.json()["task_id"]
        logger.info(f"TTS task_id: {task_id}")

        status = _poll(f"{BASE}/tts", task_id)

        if status.get("status") != "SUCCESS":
            raise RuntimeError(f"TTS failed: {status}")

        run_id = status["run_id"]

        r = requests.get(
            f"{BASE}/tts-result/{run_id}",
            headers=HEADERS,
            stream=True,
            timeout=120
        )

        logger.debug("Downloading audio stream...")
        r.raise_for_status()

        with open(audio_path, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)

        logger.info(f"TTS completed → {audio_path}")

        return {"audio_path": audio_path}

    except Exception as e:
        logger.exception("TTS failed")
        return {"error": str(e)}


# ---------------- STEP 4: MERGE ---------------- #
@mcp.tool(description="Step 4: Merge audio with video")
def merge_audio_video(video_path: str, audio_path: str, output_video_path: str):
    logger.info("STEP 4: Merging audio and video")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            "-c:v", "copy",
            "-c:a", "aac",
            output_video_path,
        ]

        logger.debug(f"Running ffmpeg: {' '.join(cmd)}")

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)

        logger.debug(result.stdout)
        logger.debug(result.stderr)

        logger.info(f"Merging completed → {output_video_path}")

        return {"output_video_path": output_video_path}

    except subprocess.CalledProcessError as e:
        logger.exception("FFmpeg failed")
        return {"error": e.stderr}


# ---------------- MAIN ---------------- #
if __name__ == "__main__":
    logger.info("MCP Server Starting...")
    mcp.run(transport="sse")
