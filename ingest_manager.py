from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
CURRENT_INGEST_FILE = DATA_DIR / "current_ingest.json"


class IngestManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.segmenter_proc: Optional[subprocess.Popen] = None
        self.metadata_proc: Optional[subprocess.Popen] = None
        self.current_config: Dict[str, Any] = {}

    def _start_process(self, script_name: str, env: Dict[str, str]) -> subprocess.Popen:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{Path(script_name).stem}.log"
        log_handle = open(log_path, "a", buffering=1)

        return subprocess.Popen(
            [sys.executable, str(BASE_DIR / script_name)],
            cwd=str(BASE_DIR),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _write_current_ingest(self, config: Dict[str, Any]) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CURRENT_INGEST_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def start_metadata_worker(self) -> Dict[str, Any]:
        with self._lock:
            if self.metadata_proc and self.metadata_proc.poll() is None:
                return {"running": True, "pid": self.metadata_proc.pid}

            env = os.environ.copy()
            self.metadata_proc = self._start_process("metadata_mp4_1.py", env)
            return {"running": True, "pid": self.metadata_proc.pid}
    
    def start_segmenter(
        self,
        source_url: str,
        protocol: str = "srt",
        sport_type: str = "football",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if self.segmenter_proc and self.segmenter_proc.poll() is None:
                self.stop_segmenter()

            config = {
                "source_url": source_url,
                "protocol": protocol,
                "sport_type": sport_type,
                "extra": extra or {},
            }
            self.current_config = config
            self._write_current_ingest(config)

            env = os.environ.copy()
            env["SOURCE_URL"] = source_url
            env["PROTOCOL"] = protocol
            env["SPORT_TYPE"] = sport_type
            env["SEGMENT_TIME"] = env.get("SEGMENT_TIME", "30")

            self.segmenter_proc = self._start_process("mp4_segmenter1.py", env)
            return {
                "running": True,
                "pid": self.segmenter_proc.pid,
                "source_url": source_url,
                "protocol": protocol,
                "sport_type": sport_type,
            }

    def stop_segmenter(self) -> Dict[str, Any]:
        with self._lock:
            if self.segmenter_proc and self.segmenter_proc.poll() is None:
                self._terminate(self.segmenter_proc)
            self.segmenter_proc = None
            return {"running": False}
        
    def stop_metadata_worker(self) -> Dict[str, Any]:
        with self._lock:
            if self.metadata_proc and self.metadata_proc.poll() is None:
                self._terminate(self.metadata_proc)
            self.metadata_proc = None
            return {"running": False}

    def status(self) -> Dict[str, Any]:
        return {
            "segmenter": {
                "running": bool(self.segmenter_proc and self.segmenter_proc.poll() is None),
                "pid": self.segmenter_proc.pid if self.segmenter_proc and self.segmenter_proc.poll() is None else None,
                "config": self.current_config,
            },
            "metadata_worker": {
                "running": bool(self.metadata_proc and self.metadata_proc.poll() is None),
                "pid": self.metadata_proc.pid if self.metadata_proc and self.metadata_proc.poll() is None else None,
            },
        }

    def _terminate(self, proc: subprocess.Popen) -> None:
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass


ingest_manager = IngestManager()
