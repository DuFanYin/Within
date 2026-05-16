"""Shared test helpers (import as test.support, not conftest)."""

import base64
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path


def log_step(message: str) -> None:
    """Visible progress when pytest runs with -s (not a hang if lines keep appearing)."""
    print(f"[within] {message}", flush=True, file=sys.stderr)

ROOT = Path(__file__).resolve().parent.parent
CACTUS_PY = ROOT / "third_party/cactus/python/src/cactus.py"


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def patch_lifespan() -> None:
    import app.main as main_mod

    main_mod.app.router.lifespan_context = _noop_lifespan


patch_lifespan()


def collect_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def small_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )


def small_webm() -> bytes:
    return bytes([0x1A, 0x45, 0xDF, 0xA3, 0x84, 0x42, 0x86, 0x81, 0x01])


def cactus_built() -> bool:
    return CACTUS_PY.is_file()


def configure_app_dirs(base: Path) -> None:
    import app.corpus as corpus_mod
    import app.db as db_mod
    import app.main as main_mod

    corpus_dir = base / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    (base / "audio").mkdir(exist_ok=True)
    (base / "images").mkdir(exist_ok=True)

    db_mod._DB_PATH = base / "journal.db"
    main_mod.AUDIO_DIR = base / "audio"
    main_mod.IMAGE_DIR = base / "images"
    corpus_mod._corpus_cursor = 0
    corpus_mod.corpus_dir = lambda: corpus_dir
    db_mod.init_db()
