import os
import asyncio
from aiohttp import web
from packaging import version
import asyncpg

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

routes = web.RouteTableDef()

async def init_db(app):
    # Wait for DB to be ready
    for _ in range(10):
        try:
            app["db"] = await asyncpg.create_pool(
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
            )
            break
        except Exception:
            print("Waiting for DB...")
            await asyncio.sleep(2)

    async with app["db"].acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id SERIAL PRIMARY KEY,
                flow_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                tags TEXT[]
            );
        """)

VERSION_THRESHOLD = "2.0.0"  # clients >= 2.0.0 get paginated response


def is_new_client(client_version: str) -> bool:
    try:
        return version.parse(client_version) >= version.parse(VERSION_THRESHOLD)
    except Exception:
        return False

@routes.get("/runs")
async def get_runs(request):
    # -------- Version Detection --------
    client_version = request.headers.get("X-Metaflow-Client-Version")
    new_client = client_version and is_new_client(client_version)

    # -------- Query Parameters --------
    tag_filter = request.query.get("tags")
    limit = int(request.query.get("limit", 50))
    offset = int(request.query.get("offset", 0))

    async with request.app["db"].acquire() as conn:

        # -------- Filtering Logic --------
        if tag_filter:
            total_query = "SELECT COUNT(*) FROM runs WHERE $1 = ANY(tags)"
            data_query = """
                SELECT * FROM runs
                WHERE $1 = ANY(tags)
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
            total = await conn.fetchval(total_query, tag_filter)
            rows = await conn.fetch(data_query, tag_filter, limit, offset)

        else:
            total_query = "SELECT COUNT(*) FROM runs"
            data_query = """
                SELECT * FROM runs
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """
            total = await conn.fetchval(total_query)
            rows = await conn.fetch(data_query, limit, offset)

    data = []
    for row in rows:
        row_dict = dict(row)
        row_dict["created_at"] = row_dict["created_at"].isoformat()
        data.append(row_dict)

    # -------- Legacy Behavior --------
    if not new_client:
        return web.json_response(data)

    # -------- New Paginated Response --------
    has_more = offset + limit < total
    next_offset = offset + limit if has_more else None

    return web.json_response({
        "data": data,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": has_more,
            "next_offset": next_offset
        }
    })

async def create_app():
    app = web.Application()
    app.add_routes(routes)
    app.on_startup.append(init_db)
    return app

if __name__ == "__main__":
    web.run_app(create_app(), port=8080)
