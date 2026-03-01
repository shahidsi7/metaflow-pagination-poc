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

@routes.get("/runs")
async def get_runs(request):
    # Read query params
    limit = int(request.query.get("limit", 50))
    offset = int(request.query.get("offset", 0))

    async with request.app["db"].acquire() as conn:
        # Get total count
        total = await conn.fetchval("SELECT COUNT(*) FROM runs")

        # Fetch paginated results
        rows = await conn.fetch(
            """
            SELECT * FROM runs
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset
        )

    data = []
    for row in rows:
        row_dict = dict(row)
        row_dict["created_at"] = row_dict["created_at"].isoformat()
        data.append(row_dict)

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
