# Within

FastAPI app on the [Cactus](https://github.com/cactus-compute/cactus) engine (chat + transcription). The engine checkout path is **fixed** in code: **`third_party/cactus`** under this repo (`app/engine.py` sets `CACTUS_PROJECT_ROOT` at import time — there is no `setup.env`).

Default weights the app expects unless you override env vars: **`google/gemma-4-E2B-it`** (chat) and **`nvidia/parakeet-tdt-0.6b-v3`** (ASR). See `app/engine.py` and `app/transcribe.py` for optional `CACTUS_*` overrides.

## 1. Engine: clone, setup, build

From the **Within** repo root (paths are intentional — do not rename `third_party/cactus`):

```bash
mkdir -p third_party
git clone --depth 1 https://github.com/cactus-compute/cactus.git third_party/cactus
cd third_party/cactus
source ./setup
cactus build --python
```

Details and OS packages: [Cactus README](https://github.com/cactus-compute/cactus/blob/main/README.md).

## 2. Weights: two models

Still under `third_party/cactus` (with venv / `cactus` on `PATH` from `source ./setup`, or call `./venv/bin/cactus`):

```bash
cd third_party/cactus
cactus download google/gemma-4-E2B-it
cactus download nvidia/parakeet-tdt-0.6b-v3
```

Gated models: `huggingface-cli login` or `cactus download … --token …` (see `cactus download --help`).

## 3. App venv + run

From the Within repo root:

```bash
./sys_setup.sh
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8765
```

`sys_setup.sh` checks `third_party/cactus`, `libcactus`, and installs **`requirements.txt`** into **`.venv`**.

Open **http://127.0.0.1:8765/**.

## 4. Optional: demo journal data (`seed.py`)

Loads about a month of fake journal/companion/mood rows into **`data/journal.db`** so History and Insights have something to show. **Wipes** existing `journal_entries` and `mood_snapshots` each run (safe to re-run).

From the repo root, with the app venv active (after `./sys_setup.sh`):

```bash
source .venv/bin/activate
python seed.py
```