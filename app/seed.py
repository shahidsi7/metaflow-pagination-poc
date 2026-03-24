import os
import asyncio
import asyncpg
from faker import Faker
import random

fake = Faker()

DB_HOST     = os.getenv("DB_HOST", "db")
DB_NAME     = os.getenv("DB_NAME", "metaflow")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

# ── Change this to 1_000 / 10_000 / 50_000 as needed ──────────────────────────
SEED_COUNT  = int(os.getenv("SEED_COUNT", 10_000))

# How many rows to send to Postgres in a single COPY batch.
# Keeping this at 5 000 keeps memory usage flat even at 50 k rows.
BATCH_SIZE  = 5_000

TAG_POOL    = ["prod", "test", "staging", "urgent", "nightly"]


async def seed():
    conn = await asyncpg.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )

    # Optional: wipe existing rows so re-runs don't stack data.
    # Remove the line below if you want to accumulate across runs.
    await conn.execute("TRUNCATE TABLE runs RESTART IDENTITY")

    inserted = 0

    # Insert in batches using the COPY protocol — orders of magnitude faster
    # than individual INSERT round-trips (50 k rows in < 1 second vs minutes).
    while inserted < SEED_COUNT:
        batch_count = min(BATCH_SIZE, SEED_COUNT - inserted)

        records = [
            (
                fake.word(),                                        # flow_id
                fake.date_time_between(start_date="-1y", end_date="now"),  # created_at
                random.sample(TAG_POOL, k=random.randint(1, 3)),   # tags
            )
            for _ in range(batch_count)
        ]

        # asyncpg's copy_records_to_table uses PostgreSQL COPY binary protocol.
        # It bypasses the query planner and is the fastest way to bulk-load rows.
        await conn.copy_records_to_table(
            "runs",
            records=records,
            columns=["flow_id", "created_at", "tags"],
        )

        inserted += batch_count
        print(f"  Inserted {inserted:,} / {SEED_COUNT:,} rows...")

    await conn.close()
    print(f"\nDone. {inserted:,} records inserted into 'runs'.")


if __name__ == "__main__":
    asyncio.run(seed())
