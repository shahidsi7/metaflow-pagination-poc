# Metaflow Pagination PoC

A minimal proof-of-concept demonstrating database-level pagination and server-side tag filtering for the Metaflow metadata service — built for the GSoC 2026 proposal.

The PoC reproduces the unbounded response problem that exists in the real service today, solves it, and measures the improvement. The entire setup runs with a single Docker Compose command.

**Goals:**
- Reproduce and benchmark the uncapped response problem at realistic scale (50k rows)
- Implement DB-level pagination using the `limit+1` trick (no `COUNT(*)`)
- Move tag filtering server-side using a GIN-indexed array containment operator
- Preserve full backwards compatibility — response body is always a flat array
- Expose pagination metadata via response headers, not the response body

---

## 📊 Before vs After (50,000 rows)

Benchmarked locally with `curl` against a Docker Compose stack on WSL2.

| Metric | Before (`/runs/all`, unbounded) | After (`/runs?limit=50`) |
|---|---|---|
| Response Size | 5,425,883 bytes (~5.4 MB) | 5,432 bytes (~5.4 KB) |
| Response Time | 1.420s | 0.020s |
| Improvement | — | **99.9% smaller, 71x faster** |

The `/runs/all` endpoint intentionally mimics the old unbounded behavior of the real Metaflow service — no limit, full table scan, entire result set serialized in one response. The `/runs` endpoint is the fix.

---

## 🚀 Quick Start (Under 5 Minutes)

### 1. Clone and start

```bash
git clone https://github.com/shahidsi7/metaflow-pagination-poc.git
cd metaflow-pagination-poc

docker compose down -v          # wipe any old DB volumes first
docker compose up --build -d    # build image and start both containers
```

This starts:
- PostgreSQL 15 on port `5432`
- aiohttp app on port `8080`

Confirm both containers are running:

```bash
docker ps
```

Expected output:

```
CONTAINER ID   IMAGE                         COMMAND          STATUS         PORTS                    NAMES
413f6c0aacc1   metaflow-pagination-poc-app   "python main.py" Up 4 minutes   0.0.0.0:8080->8080/tcp   metaflow-app
ab1b33a211aa   postgres:15                   "docker-entry…"  Up 10 minutes  0.0.0.0:5432->5432/tcp   metaflow-db
```

---

### 2. Copy the updated files into the container

The repository includes an updated `seed.py` (bulk COPY seeder) and `main.py` (adds the unbounded `/runs/all` benchmark endpoint). Copy both into the running app container:

```bash
docker cp app/seed.py metaflow-app:/app/seed.py
docker cp app/main.py metaflow-app:/app/main.py
```

Then restart the app to pick up the `main.py` change:

```bash
docker compose restart app
```

Confirm it is back up:

```bash
docker ps
```

> This step is required every time you rebuild the container from scratch, since the container filesystem resets on rebuild.

---

### 3. Seed the database

**Default — 10,000 rows:**

```bash
docker exec -it metaflow-app python seed.py
```

Expected output:

```
  Inserted 5,000 / 10,000 rows...
  Inserted 10,000 / 10,000 rows...

Done. 10,000 records inserted into 'runs'.
```

**Stress test — 50,000 rows:**

```bash
docker exec -e SEED_COUNT=50000 -it metaflow-app python seed.py
```

Expected output:

```
  Inserted 5,000 / 50,000 rows...
  ...
  Inserted 50,000 / 50,000 rows...

Done. 50,000 records inserted into 'runs'.
```

> The seeder uses PostgreSQL's binary `COPY` protocol via `copy_records_to_table` — not individual `INSERT` round-trips. 50k rows inserts in under 2 seconds. `SEED_COUNT` is configurable as an environment variable with no code changes required.

---

## 📈 Benchmarking

> **Important:** Always benchmark _before_ running `pytest`. The test suite truncates the table to isolate each test, so the table will be nearly empty after `pytest` finishes. Re-seed if needed.

### Before — unbounded response (the problem)

```bash
curl -w "\nSize: %{size_download} bytes\nTime: %{time_total}s\n" \
     -o /dev/null -s http://localhost:8080/runs/all
```

This hits `/runs/all` which mimics the old behavior — no limit, full table dump.

Expected output at 50k rows:

```
Size: 5425883 bytes
Time: 1.420762s
```

### After — paginated response (the fix)

```bash
curl -w "\nSize: %{size_download} bytes\nTime: %{time_total}s\n" \
     -o /dev/null -s "http://localhost:8080/runs?limit=50&offset=0"
```

Expected output:

```
Size: 5432 bytes
Time: 0.020718s
```

Response size stays at ~5KB regardless of how many rows are in the database.

---

## ✅ Pagination

### Basic paginated request

```bash
curl -i "http://localhost:8080/runs?limit=50&offset=0"
```

Pagination metadata is returned in **response headers**, not in the response body:

```
X-Has-More: true
X-Next-Offset: 50
X-Limit: 50
X-Offset: 0
```

The response body is always a flat JSON array — identical for all clients:

```json
[
  { "id": 1, "flow_id": "price", "created_at": "2026-03-24T21:02:37.426742", "tags": ["nightly", "staging", "prod"] },
  { "id": 2, "flow_id": "camera", "created_at": "2026-03-24T21:01:22.869093", "tags": ["prod", "staging", "nightly"] },
  ...
]
```

### Iterating pages

```bash
# Page 1
curl -i "http://localhost:8080/runs?limit=50&offset=0"

# Page 2 — use X-Next-Offset from previous response
curl -i "http://localhost:8080/runs?limit=50&offset=50"

# Last page — X-Has-More will be "false" and X-Next-Offset will be empty
```

### Supported query parameters

| Parameter | Default | Max | Description |
|---|---|---|---|
| `limit` | 50 | 500 | Rows per page (capped silently) |
| `offset` | 0 | — | Row offset to start from |
| `tags` | — | — | Filter by tag (e.g. `?tags=prod`) |

---

## 🔄 Backwards Compatibility

The response body is **always a flat JSON array** — no envelope, no version detection.

Old clients that do not know about pagination receive exactly the same response format they always did. New clients read the `X-Has-More` and `X-Next-Offset` headers to iterate pages automatically.

This removes the need for `X-Metaflow-Client-Version` header branching entirely — a design change made in response to the mentor's review (see [Design Decisions](#-design-decisions) below).

---

## 🔎 Tag Filtering

```bash
curl -i "http://localhost:8080/runs?tags=prod&limit=10"
```

All returned rows will contain `prod` in their `tags` array. Pagination headers are included as normal.

**Implementation detail:** tag filtering uses the PostgreSQL array containment operator with a GIN index, not `ANY()`:

```sql
-- This is what the service runs
WHERE tags @> ARRAY[$1::text]

-- NOT this (ANY cannot use a GIN index — sequential scan)
-- WHERE $1 = ANY(tags)
```

A GIN index is created on startup:

```sql
CREATE INDEX IF NOT EXISTS idx_runs_tags_gin ON runs USING GIN(tags);
```

This maps directly to the `idx_gin_tags_combined` index that already exists on `runs_v3` in the real Metaflow service schema.

---

## 🔁 Full Client Pagination Loop

`client.py` demonstrates how a caller iterates all pages transparently by reading response headers:

```bash
docker exec -it metaflow-app python client.py
```

Expected output (with 50k rows seeded):

```
Fetched 50000 total runs
```

The loop reads `X-Has-More` and `X-Next-Offset` from headers and accumulates results:

```python
has_more = resp.headers.get("X-Has-More", "false").lower() == "true"
next_offset = resp.headers.get("X-Next-Offset", "")
if not has_more or not next_offset:
    break
offset = int(next_offset)
```

Because the body is always a flat array, the loop simply extends a list on each iteration. No envelope unwrapping needed.

---

## 🧪 Tests

> **Note:** The test suite truncates the `runs` table to keep each test self-contained. Re-seed after running tests if you want to benchmark again.

```bash
docker exec -it metaflow-app pytest -v
```

Expected output — **11 passed**:

```
tests/test_runs.py::test_response_body_is_flat_array PASSED               [  9%]
tests/test_runs.py::test_new_client_also_gets_flat_array PASSED           [ 18%]
tests/test_runs.py::test_pagination_headers_present PASSED                [ 27%]
tests/test_runs.py::test_default_limit_is_50 PASSED                       [ 36%]
tests/test_runs.py::test_has_more_true_on_first_page PASSED               [ 45%]
tests/test_runs.py::test_offset_skips_correctly PASSED                    [ 54%]
tests/test_runs.py::test_last_page_has_more_false PASSED                  [ 63%]
tests/test_runs.py::test_tag_filtering_returns_correct_rows PASSED        [ 72%]
tests/test_runs.py::test_tag_filtering_with_pagination_headers PASSED     [ 81%]
tests/test_runs.py::test_limit_is_capped_at_500 PASSED                    [ 90%]
tests/test_runs.py::test_invalid_limit_returns_400 PASSED                 [100%]

11 passed in 35.17s
```

| Test | What it verifies |
|---|---|
| `test_response_body_is_flat_array` | Body is always a list, no envelope |
| `test_new_client_also_gets_flat_array` | Version headers do not change body format |
| `test_pagination_headers_present` | All four headers present on every response |
| `test_default_limit_is_50` | Default page size is 50 rows |
| `test_has_more_true_on_first_page` | has_more=true when more rows exist |
| `test_offset_skips_correctly` | Page 1 and page 2 return different rows |
| `test_last_page_has_more_false` | Last page reports has_more=false |
| `test_tag_filtering_returns_correct_rows` | Only matching rows returned for tag filter |
| `test_tag_filtering_with_pagination_headers` | Headers present on filtered responses |
| `test_limit_is_capped_at_500` | limit=9999 is silently capped to 500 |
| `test_invalid_limit_returns_400` | Non-integer limit returns HTTP 400 |

Each test seeds or truncates its own data so tests are fully self-contained and do not depend on each other's state.

---

## ⚠️ Recommended Order of Operations

```
docker compose up --build -d
        ↓
docker cp app/seed.py metaflow-app:/app/seed.py
docker cp app/main.py metaflow-app:/app/main.py
        ↓
docker compose restart app
        ↓
docker exec -e SEED_COUNT=50000 -it metaflow-app python seed.py
        ↓
BENCHMARK  ←  curl /runs/all  vs  curl /runs?limit=50
        ↓
docker exec -it metaflow-app pytest -v
        ↓
RE-SEED if benchmarking again  ←  tests wipe the table
```

---

## 🏗 Architectural Notes

**What this PoC intentionally mimics from the real service:**
- Unbounded listing endpoint behavior (`/runs/all`)
- PostgreSQL-backed metadata storage
- Realistic tag filtering and ordering
- GIN index strategy matching the real `runs_v3` schema

**What this PoC simplifies (intentionally):**
- No DB abstraction layer (`find_records()`, `DBPagination`, `DBResponse`)
- No decorator-based response wrapping
- No composite keys or cursor pagination
- Single-stage Dockerfile (multi-stage is demonstrated in PR #465)

---

## 🎯 Design Decisions

These decisions were made in direct response to the mentor's review of the original PoC:

**1. Header-based pagination instead of version-threshold branching**

The original design used `X-Metaflow-Client-Version >= 2.0.0` to decide whether to return a paginated envelope or a flat array. The simpler and more robust approach is to always return a flat array and put pagination metadata in response headers — no version parsing, no branching, no two code paths to maintain. This mirrors GitHub and GitLab's pagination design.

**2. `limit+1` trick instead of `COUNT(*)`**

The original design ran `SELECT COUNT(*)` on every request to populate a `total` field. The mentor flagged the performance cost of this, especially under tag filters where the DB must scan all matching rows to count them. The fix: request `limit+1` rows, check if the extra row exists to set `has_more`, then drop it. `COUNT(*)` is never run. Exact totals remain available as opt-in via `?include_total=true`.

**3. `@>` containment operator instead of `ANY()`**

The original design used `WHERE $1 = ANY(tags)`. `ANY()` cannot use a GIN index and always performs a sequential scan. The array containment operator `tags @> ARRAY[$1::text]` uses the GIN index and performs an O(log n) lookup instead.

**4. Bulk `COPY` seeding instead of individual `INSERT` round-trips**

The original `seed.py` made one DB round-trip per row — 50,000 network calls to insert 50k rows. The updated seeder uses `asyncpg`'s `copy_records_to_table`, which maps to PostgreSQL's binary `COPY` protocol and inserts 50k rows in under 2 seconds. Row count is configurable via `SEED_COUNT` with no code changes.

**5. Healthcheck-based container startup ordering**

The original `docker-compose.yml` used `depends_on: db` which only waits for the container to start, not for Postgres to be ready to accept connections. This caused a race condition where the app exhausted its retry loop before the DB finished initializing. The fix adds a `healthcheck` using `pg_isready` and `condition: service_healthy` so Docker guarantees the DB is accepting connections before the app starts.

---

## 📁 File Structure

```
metaflow-pagination-poc/
├── app/
│   ├── main.py            ← aiohttp service: paginated /runs, unbounded /runs/all, GIN index
│   ├── client.py          ← async client that iterates all pages via response headers
│   ├── seed.py            ← bulk COPY seeder, configurable via SEED_COUNT env var
│   ├── requirements.txt
│   ├── Dockerfile
│   └── __init__.py
├── tests/
│   ├── test_runs.py       ← 11 self-contained pytest tests
│   └── __init__.py
├── docker-compose.yml
└── .gitignore
```

---

## 🐳 Docker Compose

```yaml
version: "3.9"

services:
  db:
    image: postgres:15
    container_name: metaflow-db
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: metaflow
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d metaflow"]
      interval: 5s
      timeout: 5s
      retries: 10

  app:
    build: ./app
    container_name: metaflow-app
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8080:8080"
    environment:
      DB_HOST: db
      DB_NAME: metaflow
      DB_USER: postgres
      DB_PASSWORD: postgres

volumes:
  pgdata:
```

The `condition: service_healthy` ensures the app never starts before Postgres is ready — eliminating the race condition that causes `KeyError: 'db'` on first boot.

---

## 🔗 Related

- GSoC proposal: Metadata Service Request Improvements (Pagination + Server-side Filtering)
- PR #19 — [Unify Dockerfiles into a single multi-stage Dockerfile](https://github.com/saikonen/metaflow-service/pull/19)
- PR #17 - [Fix/autocomplete tag cache staleness](https://github.com/saikonen/metaflow-service/pull/17)
