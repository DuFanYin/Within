"""Real on-device model tests. Skipped when Cactus is not built."""

import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from support import cactus_built, configure_app_dirs, log_step

if not cactus_built():
    pytest.skip("third_party/cactus not built", allow_module_level=True)


@pytest.fixture(scope="session")
def _model_ready():
    log_step("loading model (warmup)…")
    t0 = time.monotonic()
    from app.engine import warmup_sync

    warmup_sync()
    log_step(f"model ready ({time.monotonic() - t0:.1f}s)")


@pytest_asyncio.fixture
async def client(tmp_path, _model_ready):
    configure_app_dirs(tmp_path)
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
