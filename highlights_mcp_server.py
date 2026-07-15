from mcp.server.fastmcp import FastMCP
import pandas as pd
import json
import os
import logging
import time
import subprocess

# ---------------- LOGGER ---------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("highlights-mcp")

# ---------------- MCP ---------------- #
mcp = FastMCP("highlights-tools")

# ---------------- PATHS ---------------- #
METADATA_PATH = "/home/tummala_venkata/ai_for_live/new_backend/data/segment_metadata.csv"
VIDEO_DIR = "/home/tummala_venkata/ai_for_live/new_backend/data/videos_mp4"
OUTPUT_DIR = "/home/tummala_venkata/ai_for_live/new_backend/data/highlights_mp4"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================================================
# ✅ UTIL: Merge MP4 segments (FFMPEG)
# =========================================================
def merge_mp4_segments(segment_paths, output_file):
    list_file = os.path.join(OUTPUT_DIR, f"temp_{int(time.time())}.txt")

    with open(list_file, "w") as f:
        for path in segment_paths:
            f.write(f"file '{path}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_file
    ]

    subprocess.run(cmd, check=True)
    os.remove(list_file)


# =========================================================
# ✅ TOOL 1: Load Metadata
# =========================================================
@mcp.tool(description="Load all video segment metadata")
def load_metadata():
    try:
        df = pd.read_csv(METADATA_PATH)
        data = df.to_dict(orient="records")

        logger.info(f"Loaded {len(data)} segments")

        return {"segments": data}

    except Exception as e:
        logger.exception("Error loading metadata")
        return {"status": "error", "error": str(e)}


# =========================================================
# ✅ TOOL 2: Load Personas
# =========================================================
@mcp.tool(description="Load personas")
def load_personas():
    try:
        persona_path = METADATA_PATH.replace("segment_metadata.csv", "persona.json")

        with open(persona_path, "r") as f:
            personas = json.load(f)

        return personas

    except Exception as e:
        logger.exception("Error loading personas")
        return {"status": "error", "error": str(e)}


# =========================================================
# ✅ TOOL 3: Get Segments by Time Range
# =========================================================
@mcp.tool(description="Get segments between minutes")
def get_segments_by_time_range(start_minute: int, end_minute: int):
    try:
        df = pd.read_csv(METADATA_PATH)

        if start_minute < 0:
            start_minute = 0

        if end_minute < start_minute:
            return {"status": "error"}

        # 6 segments/min (10 sec each)
        start_idx = start_minute * 6
        end_idx = end_minute * 6

        selected = df.iloc[start_idx:end_idx + 1]

        return {
            "status": "success",
            "segments": selected.to_dict(orient="records"),
            "range": [start_minute, end_minute]
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}


# =========================================================
# ✅ TOOL 4: Get Recent Segments
# =========================================================
@mcp.tool(description="Get recent segments")
def get_recent_segments(minutes: int):
    try:
        df = pd.read_csv(METADATA_PATH)

        segments_needed = max(1, (minutes * 60) // 10)

        selected = df.tail(segments_needed)

        return {
            "status": "success",
            "segments": selected.to_dict(orient="records"),
            "count": len(selected)
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}


# =========================================================
# ✅ TOOL 5: Compose Highlight Video (MAIN TOOL for AGENT)
# =========================================================
@mcp.tool(
    description="""
    Compose highlight MP4 video with context expansion (±2).

    Input:
    {
        "selected_indices": [10, 20, 30]
    }

    Output:
    {
        "output_path": "...",
        "segments_used": [...],
        "status": "success"
    }
    """
)
def compose_highlight_playlist(selected_indices: list[int]):
    try:
        logger.info(f"Input indices: {selected_indices}")

        df = pd.read_csv(METADATA_PATH)

        # ✅ normalize
        normalized = []
        for item in selected_indices:
            if isinstance(item, int):
                normalized.append(item)
            elif isinstance(item, dict) and "index" in item:
                normalized.append(int(item["index"]))

        # ✅ expand ±2 context
        expanded = set()
        for idx in normalized:
            for i in range(idx - 2, idx + 3):
                if 0 <= i < len(df):
                    expanded.add(i)

        expanded = sorted(expanded)

        # ✅ collect paths
        segment_paths = []
        for idx in expanded:
            seg_name = df.iloc[idx]["segment_name"]
            seg_path = os.path.join(VIDEO_DIR, seg_name)
            logger.info(f"Path: {seg_path}")
            if os.path.exists(seg_path):
                segment_paths.append(seg_path)
            else:
                logger.warning(f"Missing segment: {seg_path}")

        if not segment_paths:
            return {"status": "error", "error": "No valid segments found"}

        # ✅ output file
        output_file = os.path.join(
            OUTPUT_DIR,
            f"highlight_{int(time.time())}.mp4"
        )

        merge_mp4_segments(segment_paths, output_file)

        logger.info(f"Highlight created: {output_file}")

        return {
            "status": "success",
            "output_path": output_file,
            "segments_used": expanded
        }

    except Exception as e:
        logger.exception("Error composing highlight video")
        return {"status": "error", "error": str(e)}


# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    mcp.run()

