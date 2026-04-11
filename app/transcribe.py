"""
ASR via Cactus — nvidia/parakeet-tdt-0.6b-v3 (English).

Separate model handle from the chat model; loaded lazily on first request.
Switch model: set CACTUS_ASR_MODEL_ID env var before starting the server.
"""

from __future__ import annotations

import importlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .gemma_cactus import _load_cactus, _resolve_weights

_asr_lock = threading.Lock()
_asr_model: int | None = None


def _get_asr_model() -> tuple[Any, Any, Any]:
    global _asr_model
    if _asr_model is not None:
        _, _, _, cactus_get_last_error, _ = _load_cactus()
        cactus_mod = importlib.import_module("src.cactus")
        return cactus_mod.cactus_transcribe, cactus_mod.cactus_destroy, _asr_model

    with _asr_lock:
        if _asr_model is not None:
            cactus_mod = importlib.import_module("src.cactus")
            return cactus_mod.cactus_transcribe, cactus_mod.cactus_destroy, _asr_model

        cactus_init, _, _, cactus_get_last_error, ensure_model = _load_cactus()
        cactus_mod = importlib.import_module("src.cactus")

        model_id = os.environ.get("CACTUS_ASR_MODEL_ID", "nvidia/parakeet-tdt-0.6b-v3")
        weights = ensure_model(model_id)

        handle = cactus_init(str(weights), None, False)
        if not handle:
            err = cactus_get_last_error() or "unknown"
            raise RuntimeError(f"ASR cactus_init failed: {err}")

        _asr_model = handle

    return cactus_mod.cactus_transcribe, cactus_mod.cactus_destroy, _asr_model


def transcribe_bytes_sync(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """
    Write audio bytes to a temp file, transcribe, return text string.
    Thread-safe; shares the ASR model handle across requests.
    """
    cactus_transcribe, _, model = _get_asr_model()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        with _asr_lock:
            text = cactus_transcribe(model, tmp_path, None, None, None, None)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return (text or "").strip()
