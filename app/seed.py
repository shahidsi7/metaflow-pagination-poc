import os
import asyncio
import asyncpg
from faker import Faker
import random

fake = Faker()

DB_HOST = os.getenv("DB_HOST", "db")
DB_NAME = os.getenv("DB_NAME", "metaflow")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

async def seed():
    conn = await asyncpg.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )

    for _ in range(1000):
        await conn.execute("""
            INSERT INTO runs (flow_id, created_at, tags)
            VALUES ($1, NOW(), $2)
        """,
            fake.word(),
            random.sample(["prod", "test", "staging", "urgent", "nightly"], 2)
        )

    await conn.close()
    print("Inserted 1000 records.")

if __name__ == "__main__":
    asyncio.run(seed())
