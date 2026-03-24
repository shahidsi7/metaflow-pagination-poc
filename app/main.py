import os
import asyncio
from aiohttp import web
import asyncpg

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

routes = web.RouteTableDef()

async def init_db(app):
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
        # Create runs table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id SERIAL PRIMARY KEY,
                flow_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                tags TEXT[]
            );
        """)

        # Create GIN index on tags so @> containment operator can use it.
        # ANY() cannot use this index — @> can.
        # CONCURRENTLY means it won't lock the table during creation.
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_tags_gin
            ON runs USING GIN(tags);
        """)


@routes.get("/runs")
async def get_runs(request):
    # -------- Query Parameters --------
    tag_filter = request.query.get("tags")

    try:
        limit = max(1, min(int(request.query.get("limit", 50)), 500))
        offset = max(0, int(request.query.get("offset", 0)))
    except ValueError:
        raise web.HTTPBadRequest(reason="limit and offset must be integers")

    # Fetch limit+1 rows. If the extra row exists, has_more=True.
    # This avoids running COUNT(*) entirely on every request.
    fetch_limit = limit + 1

    async with request.app["db"].acquire() as conn:

        if tag_filter:
            # Use array containment operator @> with ARRAY cast.
            # This allows the GIN index (idx_runs_tags_gin) to be used.
            # ANY() performs a sequential scan and cannot use GIN.
            rows = await conn.fetch("""
                SELECT * FROM runs
                WHERE tags @> ARRAY[$1::text]
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """, tag_filter, fetch_limit, offset)
        else:
            rows = await conn.fetch("""
                SELECT * FROM runs
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """, fetch_limit, offset)

    # Determine has_more from the extra row, then drop it
    has_more = len(rows) == fetch_limit
    rows = rows[:limit]

    data = []
    for row in rows:
        row_dict = dict(row)
        row_dict["created_at"] = row_dict["created_at"].isoformat()
        data.append(row_dict)

    # Pagination metadata goes in response headers — not in the response body.
    # This means all clients (old and new) receive the same flat array body.
    # Old clients ignore the headers. New clients read them.
    # No version detection or branching needed.
    next_offset = offset + limit if has_more else None

    headers = {
        "X-Has-More": str(has_more).lower(),       # "true" or "false"
        "X-Next-Offset": str(next_offset) if next_offset is not None else "",
        "X-Limit": str(limit),
        "X-Offset": str(offset),
    }

    return web.json_response(data, headers=headers)

@routes.get("/runs/all")
async def get_runs_unbounded(request):
    """
    Simulates the OLD unbounded behavior — no limit, dumps entire table.
    Used only for benchmarking the 'before' state.
    """
    tag_filter = request.query.get("tags")

    async with request.app["db"].acquire() as conn:
        if tag_filter:
            rows = await conn.fetch("""
                SELECT * FROM runs
                WHERE tags @> ARRAY[$1::text]
                ORDER BY created_at DESC
            """, tag_filter)
        else:
            rows = await conn.fetch("""
                SELECT * FROM runs
                ORDER BY created_at DESC
            """)

    data = []
    for row in rows:
        row_dict = dict(row)
        row_dict["created_at"] = row_dict["created_at"].isoformat()
        data.append(row_dict)

    return web.json_response(data)


async def create_app():
    app = web.Application()
    app.add_routes(routes)
    app.on_startup.append(init_db)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), port=8080)
