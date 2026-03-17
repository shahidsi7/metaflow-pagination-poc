import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from app.main import create_app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    """
    Create a TestClient with a fresh app and server.
    Ensures the database pool is closed after the test to avoid connection leaks.
    """
    app = await create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()
    # Clean up the database pool
    if 'db' in app:
        await app['db'].close()


# ---------------------------------------------------------------------------
# Response body is always a flat array — no version header needed
# ---------------------------------------------------------------------------

async def test_response_body_is_flat_array(client):
    """All clients receive a flat JSON array — no envelope wrapping."""
    resp = await client.get("/runs")
    data = await resp.json()
    assert isinstance(data, list)


async def test_new_client_also_gets_flat_array(client):
    """Even if a client sends old version headers, body is still a flat array."""
    resp = await client.get("/runs", headers={"X-Metaflow-Client-Version": "2.0.0"})
    data = await resp.json()
    assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Pagination metadata is in response headers
# ---------------------------------------------------------------------------

async def test_pagination_headers_present(client):
    """Response must include X-Has-More, X-Next-Offset, X-Limit, X-Offset."""
    resp = await client.get("/runs")
    assert "X-Has-More" in resp.headers
    assert "X-Next-Offset" in resp.headers
    assert "X-Limit" in resp.headers
    assert "X-Offset" in resp.headers


async def test_default_limit_is_50(client):
    """Default page size should be 50 rows."""
    db = client.server.app["db"]
    async with db.acquire() as conn:
        await conn.execute("TRUNCATE TABLE runs RESTART IDENTITY")
        await conn.executemany(
            "INSERT INTO runs (flow_id, created_at, tags) VALUES ($1, NOW(), $2)",
            [("testflow", ["prod"]) for _ in range(60)]
        )

    resp = await client.get("/runs")
    data = await resp.json()
    assert len(data) == 50
    assert resp.headers["X-Limit"] == "50"


async def test_has_more_true_on_first_page(client):
    """When more rows exist than the limit, has_more must be true."""
    db = client.server.app["db"]
    async with db.acquire() as conn:
        await conn.execute("TRUNCATE TABLE runs RESTART IDENTITY")
        await conn.executemany(
            "INSERT INTO runs (flow_id, created_at, tags) VALUES ($1, NOW(), $2)",
            [("testflow", ["prod"]) for _ in range(10)]
        )

    resp = await client.get("/runs?limit=5&offset=0")
    assert resp.headers["X-Has-More"] == "true"
    assert resp.headers["X-Next-Offset"] == "5"


async def test_offset_skips_correctly(client):
    """Page 1 and page 2 should return different rows."""
    db = client.server.app["db"]
    async with db.acquire() as conn:
        await conn.execute("TRUNCATE TABLE runs RESTART IDENTITY")
        await conn.executemany(
            "INSERT INTO runs (flow_id, created_at, tags) VALUES ($1, NOW(), $2)",
            [("testflow", ["prod"]) for _ in range(30)]
        )

    resp1 = await client.get("/runs?limit=10&offset=0")
    resp2 = await client.get("/runs?limit=10&offset=10")
    data1 = await resp1.json()
    data2 = await resp2.json()
    assert len(data1) == 10
    assert len(data2) == 10
    assert data1[0]["id"] != data2[0]["id"]


async def test_last_page_has_more_false(client):
    """When limit exceeds total rows, has_more must be false."""
    db = client.server.app["db"]
    async with db.acquire() as conn:
        await conn.execute("TRUNCATE TABLE runs RESTART IDENTITY")
        await conn.executemany(
            "INSERT INTO runs (flow_id, created_at, tags) VALUES ($1, NOW(), $2)",
            [("testflow", ["prod"]) for _ in range(5)]
        )

    resp = await client.get("/runs?limit=100&offset=0")
    assert resp.headers["X-Has-More"] == "false"
    assert resp.headers["X-Next-Offset"] == ""


# ---------------------------------------------------------------------------
# Tag filtering uses @> containment (GIN-compatible), not ANY()
# ---------------------------------------------------------------------------

async def test_tag_filtering_returns_correct_rows(client):
    """All returned rows must contain the requested tag."""
    db = client.server.app["db"]
    async with db.acquire() as conn:
        await conn.execute("TRUNCATE TABLE runs RESTART IDENTITY")
        await conn.execute(
            "INSERT INTO runs (flow_id, created_at, tags) VALUES ($1, NOW(), $2)",
            "flow1", ["prod", "test"]
        )
        await conn.execute(
            "INSERT INTO runs (flow_id, created_at, tags) VALUES ($1, NOW(), $2)",
            "flow2", ["test"]
        )
        await conn.execute(
            "INSERT INTO runs (flow_id, created_at, tags) VALUES ($1, NOW(), $2)",
            "flow3", ["prod"]
        )

    resp = await client.get("/runs?tags=prod")
    data = await resp.json()
    assert len(data) == 2
    for run in data:
        assert "prod" in run["tags"]


async def test_tag_filtering_with_pagination_headers(client):
    """Tag-filtered responses must still include pagination headers."""
    db = client.server.app["db"]
    async with db.acquire() as conn:
        await conn.execute("TRUNCATE TABLE runs RESTART IDENTITY")
        await conn.executemany(
            "INSERT INTO runs (flow_id, created_at, tags) VALUES ($1, NOW(), $2)",
            [("flow", ["prod"]) for _ in range(20)]
        )

    resp = await client.get("/runs?tags=prod&limit=10")
    assert "X-Has-More" in resp.headers
    assert "X-Limit" in resp.headers
    assert resp.headers["X-Has-More"] == "true"
    assert resp.headers["X-Limit"] == "10"


# ---------------------------------------------------------------------------
# Limit capping and bad input
# ---------------------------------------------------------------------------

async def test_limit_is_capped_at_500(client):
    """limit=9999 should be silently capped to 500."""
    resp = await client.get("/runs?limit=9999")
    assert resp.headers["X-Limit"] == "500"


async def test_invalid_limit_returns_400(client):
    """Non-integer limit should return HTTP 400."""
    resp = await client.get("/runs?limit=abc")
    assert resp.status == 400