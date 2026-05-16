"""Per-test HTTP client fixture."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from support import configure_app_dirs

# Re-export for tests that import from conftest
from support import collect_sse, small_png, small_webm  # noqa: F401


@pytest_asyncio.fixture
async def client(tmp_path):
    configure_app_dirs(tmp_path)
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
