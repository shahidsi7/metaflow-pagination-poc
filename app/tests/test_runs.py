import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from app.main import create_app
import pytest_asyncio

@pytest_asyncio.fixture
async def client(aiohttp_client):
    app = await create_app()
    return await aiohttp_client(app)

@pytest.mark.asyncio
async def test_default_limit(client):
    resp = await client.get("/runs", headers={"X-Metaflow-Client-Version": "2.0.0"})
    data = await resp.json()
    assert len(data["data"]) == 50


@pytest.mark.asyncio
async def test_offset_skips(client):
    resp1 = await client.get("/runs?limit=10&offset=0",
                             headers={"X-Metaflow-Client-Version": "2.0.0"})
    resp2 = await client.get("/runs?limit=10&offset=10",
                             headers={"X-Metaflow-Client-Version": "2.0.0"})

    data1 = await resp1.json()
    data2 = await resp2.json()

    assert data1["data"][0]["id"] != data2["data"][0]["id"]


@pytest.mark.asyncio
async def test_last_page_has_no_more(client):
    resp = await client.get("/runs?limit=1000&offset=0",
                            headers={"X-Metaflow-Client-Version": "2.0.0"})
    data = await resp.json()
    assert data["pagination"]["has_more"] is False


@pytest.mark.asyncio
async def test_tag_filtering(client):
    resp = await client.get("/runs?tags=prod",
                            headers={"X-Metaflow-Client-Version": "2.0.0"})
    data = await resp.json()
    for run in data["data"]:
        assert "prod" in run["tags"]


@pytest.mark.asyncio
async def test_legacy_client_gets_flat_response(client):
    resp = await client.get("/runs")
    data = await resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_new_client_gets_paginated_response(client):
    resp = await client.get("/runs",
                            headers={"X-Metaflow-Client-Version": "2.0.0"})
    data = await resp.json()
    assert "pagination" in data


@pytest.mark.asyncio
async def test_missing_limit_uses_default(client):
    resp = await client.get("/runs",
                            headers={"X-Metaflow-Client-Version": "2.0.0"})
    data = await resp.json()
    assert data["pagination"]["limit"] == 50
