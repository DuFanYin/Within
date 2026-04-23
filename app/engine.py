"""
Cactus engine bootstrap — model loading, FFI path helpers, base options.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import queue
import sys
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_model: int | None = None
_weights_used: str | None = None


# ── path helpers ──────────────────────────────────────────────────────────────

def _app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _third_party_engine() -> Path:
    return _app_root() / "third_party" / "cactus"


def _repo_root() -> Path:
    env = os.environ.get("CACTUS_PROJECT_ROOT", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "python" / "src" / "cactus.py").is_file():
            return p
        raise RuntimeError(f"CACTUS_PROJECT_ROOT invalid: {p}")
    bundled = _third_party_engine()
    if (bundled / "python" / "src" / "cactus.py").is_file():
        return bundled
    start = _app_root()
    for candidate in [start, *start.parents]:
        if (candidate / "python" / "src" / "cactus.py").is_file():
            return candidate
    raise RuntimeError(
        "Could not find Cactus engine checkout. Clone/build into third_party/cactus "
        "or set CACTUS_PROJECT_ROOT to a tree containing python/src/cactus.py."
    )


def _ensure_python_path() -> Path:
    root = _repo_root()
    py = root / "python"
    if not py.is_dir():
        raise RuntimeError(f"Cactus python package not found at {py}")
    s = str(py)
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)
    os.environ.setdefault("CACTUS_PROJECT_ROOT", str(root))

    _libname = "libcactus.dylib" if platform.system() == "Darwin" else "libcactus.so"
    existing = os.environ.get("CACTUS_LIB_PATH", "").strip()
    if existing:
        lib_path = Path(existing).expanduser().resolve()
        if not lib_path.is_file():
            raise RuntimeError(f"CACTUS_LIB_PATH is not a file: {lib_path}")
        os.environ["CACTUS_LIB_PATH"] = str(lib_path)
        return root

    built = root / "cactus" / "build" / _libname
    if not built.is_file():
        raise RuntimeError(
            f"Cactus shared library not found at {built}. "
            "In the engine checkout run: source ./setup && cactus build --python"
        )
    os.environ["CACTUS_LIB_PATH"] = str(built)
    return root


def _load_cactus():
    _ensure_python_path()
    try:
        cactus_mod = importlib.import_module("src.cactus")
        downloads_mod = importlib.import_module("src.downloads")
    except (RuntimeError, OSError, ImportError, AttributeError) as e:
        raise RuntimeError(f"Failed to load Cactus Python FFI: {e!r}") from e
    return (
        cactus_mod.cactus_init,
        cactus_mod.cactus_complete,
        cactus_mod.cactus_destroy,
        cactus_mod.cactus_get_last_error,
        downloads_mod.ensure_model,
    )


def _resolve_weights(ensure_model) -> Path:
    override = os.environ.get("CACTUS_WEIGHTS_DIR", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if not (p / "config.txt").is_file():
            raise RuntimeError(f"CACTUS_WEIGHTS_DIR missing config.txt: {p}")
        return p
    model_id = os.environ.get("CACTUS_MODEL_ID", "google/gemma-4-E2B-it").strip()
    precision = os.environ.get("CACTUS_WEIGHTS_PRECISION", "INT4").strip()
    return ensure_model(model_id, precision=precision)


def _get_model() -> tuple[Any, Any, Any, Any]:
    global _model, _weights_used
    if _model is not None:
        cactus_init, cactus_complete, cactus_destroy, cactus_get_last_error, _ = _load_cactus()
        return cactus_complete, cactus_destroy, cactus_get_last_error, _model
    with _lock:
        if _model is not None:
            cactus_init, cactus_complete, cactus_destroy, cactus_get_last_error, _ = _load_cactus()
            return cactus_complete, cactus_destroy, cactus_get_last_error, _model
        cactus_init, cactus_complete, cactus_destroy, cactus_get_last_error, ensure_model = _load_cactus()
        weights = _resolve_weights(ensure_model)
        corpus = _app_root() / "corpus"
        corpus.mkdir(exist_ok=True)
        handle = cactus_init(str(weights), str(corpus), True)
        if not handle:
            err = cactus_get_last_error() or "unknown"
            raise RuntimeError(f"cactus_init failed: {err}")
        _model = handle
        _weights_used = str(weights)
    return cactus_complete, cactus_destroy, cactus_get_last_error, _model


def _base_options() -> dict[str, Any]:
    return {
        "max_tokens": int(os.environ.get("CACTUS_MAX_TOKENS", "512")),
        "temperature": float(os.environ.get("CACTUS_TEMPERATURE", "0.7")),
        "top_p": float(os.environ.get("CACTUS_TOP_P", "0.9")),
        "top_k": int(os.environ.get("CACTUS_TOP_K", "40")),
        "enable_thinking_if_supported": os.environ.get("CACTUS_ENABLE_THINKING", "false").lower() == "true",
    }


def _run_complete(
    messages: list[dict],
    options: dict,
    pcm_data: bytes | None = None,
) -> dict[str, Any]:
    cactus_complete, _, cactus_get_last_error, model = _get_model()
    with _lock:
        raw = cactus_complete(model, json.dumps(messages), json.dumps(options), None, None, pcm_data)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON from cactus_complete", "reply": raw[:2000]}
    if not result.get("success"):
        err = result.get("error") or cactus_get_last_error() or "completion failed"
        return {"error": str(err), "reply": ""}
    reply = result.get("response") or ""
    meta = {k: result[k] for k in (
        "time_to_first_token_ms", "total_time_ms",
        "prefill_tps", "decode_tps", "ram_usage_mb", "total_tokens",
    ) if k in result}
    out: dict[str, Any] = {"reply": reply}
    if meta:
        out["meta"] = meta
    return out


def warmup_sync() -> None:
    """
    Load the model and prefill the system prompt so the first real user
    request skips cold-start latency. Safe to call multiple times.
    """
    global _WARMUP_DONE
    if _WARMUP_DONE:
        return
    from .agent import _COMPANION_SYSTEM
    cactus_complete, _, cactus_get_last_error, model = _get_model()
    messages = [
        {"role": "system", "content": _COMPANION_SYSTEM},
        {"role": "user", "content": "Hello"},
    ]
    options = {**_base_options(), "max_tokens": 1}
    with _lock:
        cactus_complete(model, json.dumps(messages), json.dumps(options), None, None)
    _WARMUP_DONE = True


_WARMUP_DONE = False


def rag_query(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """
    Semantic vector search over corpus using Cactus RAG.
    Returns list of result dicts (containing 'document' key), or [] on failure.
    Uses the same Gemma 4 model for embedding — all on-device.
    """
    _ensure_python_path()
    try:
        from src.cactus import cactus_rag_query as _rag
    except ImportError as e:
        raise RuntimeError(f"Failed to import cactus_rag_query: {e}") from e

    _, _, _, model = _get_model()
    with _lock:
        raw = _rag(model, query, top_k)

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []

    if isinstance(parsed, list):
        return parsed
    return parsed.get("results", [])


def shutdown_model() -> None:
    global _model, _weights_used
    with _lock:
        if _model is None:
            return
        try:
            _, _, cactus_destroy, _, _ = _load_cactus()
            cactus_destroy(_model)
        finally:
            _model = None
            _weights_used = None
