# Within

Local-first emotion journal with an on-device AI companion. Journal by text, voice, or photo; review mood over time; chat with a companion that searches your own entries—no cloud API at inference time.

**This repo is a web app MVP** — phone-layout UI in the browser, **not** a native iOS/Android or wearable app. FastAPI and Cactus run on your machine; you open `http://127.0.0.1:8765` (or the same host from a phone on your LAN). Stack: vanilla JS, SQLite, [Cactus](https://github.com/cactus-compute/cactus) (`google/gemma-4-E2B-it` + `nvidia/parakeet-tdt-0.6b-v3`).

**Docs:** [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) · [doc/writeup.md](doc/writeup.md) (Kaggle) · [doc/APP_GUIDE.md](doc/APP_GUIDE.md)

---

## Before you start

- **Python 3** and **ffmpeg** on your `PATH` (companion voice)
- Cactus at **`third_party/cactus`** — fixed path in `app/engine.py`
- Build tooling: [Cactus README](https://github.com/cactus-compute/cactus/blob/main/README.md)

`data/` and `corpus/` are empty placeholders in git; the app fills them at runtime.

---

## Setup

From the **Within repo root** unless noted.

### 1. Build the engine

```bash
git clone --depth 1 https://github.com/cactus-compute/cactus.git third_party/cactus
cd third_party/cactus
source ./setup
cactus build --python
```

### 2. Download weights

Still in `third_party/cactus` (Cactus venv active):

```bash
cactus download google/gemma-4-E2B-it
cactus download nvidia/parakeet-tdt-0.6b-v3
```

### 3. Run the web app

```bash
cd ../..
./sys_setup.sh
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8765
```

Open **http://127.0.0.1:8765/** on desktop or phone (same Wi‑Fi: `http://<your-lan-ip>:8765/`). Models and DB stay on the machine running `uvicorn`.

---

## Demo data (optional)

```bash
source .venv/bin/activate
python seed.py
```

Wipes and reloads sample rows in `data/journal.db`. **Restart uvicorn** after seed so Companion search and greetings see the corpus.

---

## Configuration

Optional env vars: `app/engine.py`, `app/transcribe.py` (`CACTUS_MODEL_ID`, `CACTUS_WEIGHTS_DIR`, `CACTUS_ASR_MODEL_ID`, …).

---

## If something breaks

| Issue | Fix |
|-------|-----|
| Stale `.venv` | `rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` |
| Companion misses new entries | Restart uvicorn (RAG index built at startup) |
| Journal voice empty | Wait ~2 min for background ASR |

**Tests:** `pytest` (needs built engine; see `test/`).
