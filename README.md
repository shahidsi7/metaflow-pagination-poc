# Metaflow Pagination PoC

A minimal proof-of-concept demonstrating database-level pagination and server-side tag filtering for the Metaflow metadata service — built for the GSoC 2026 proposal.

The PoC reproduces the unbounded response problem that exists in the real service today, solves it, and measures the improvement. The entire setup runs with a single Docker Compose command.

**Goals:**
- Benchmark the uncapped response problem
- Implement DB-level pagination using the `limit+1` trick (no `COUNT(*)`)
- Move tag filtering server-side using a GIN-indexed array containment operator
- Preserve full backwards compatibility — response body is always a flat array

---

## 📊 Before vs After (1000 rows)

| Metric        | Before (no pagination) | After (limit=50) |
| ------------- | ---------------------- | ---------------- |
| Response Size | ~780 KB                | ~39 KB           |
| Response Time | ~0.120s                | ~0.015s          |
| Improvement   | —                      | 95% smaller, 8x faster |

---

## 🚀 Quick Start (Under 5 Minutes)

### 1. Clone and start

```bash
git clone https://github.com/shahidsi7/metaflow-pagination-poc.git
cd metaflow-pagination-poc

docker compose down -v        # wipe any old DB volumes first
docker compose up --build -d  # build image and start both containers
```

This starts:
- PostgreSQL 15 on port `5432`
- aiohttp app on port `8080`

### 2. Seed the database

```bash
docker exec -it metaflow-app python seed.py
```

Expected output:
```
Inserted 1000 records.
```

### 3. Baseline — measure the uncapped response

```bash
curl -w "\nSize: %{size_download} bytes\nTime: %{time_total}s\n" \
     -o /dev/null -s http://localhost:8080/runs
```

This hits the endpoint with no limit — returns all 1000 rows in one response.

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
  { "id": 1, "flow_id": "MyFlow", "created_at": "...", "tags": ["prod", "test"] },
  { "id": 2, "flow_id": "OtherFlow", "created_at": "...", "tags": ["staging"] },
  ...
]
```

### Iterating pages

```bash
# Page 1
curl -i "http://localhost:8080/runs?limit=50&offset=0"

# Page 2 (use X-Next-Offset from previous response)
curl -i "http://localhost:8080/runs?limit=50&offset=50"

# Last page — X-Has-More will be "false" and X-Next-Offset will be empty
```

### Supported query parameters

| Parameter | Default | Max   | Description                        |
| --------- | ------- | ----- | ---------------------------------- |
| `limit`   | 50      | 500   | Rows per page (capped silently)    |
| `offset`  | 0       | —     | Row offset to start from           |
| `tags`    | —       | —     | Filter by tag (e.g. `?tags=prod`)  |

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
# Fetched 1000 total runs
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

```bash
docker exec -it metaflow-app pytest -v
```

Expected output: **11 passed**

| Test | What it verifies |
| ---- | ---------------- |
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

## 🏗 Architectural Notes

**What this PoC intentionally mimics from the real service:**
- Unbounded listing endpoint behavior
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

These three decisions were made in direct response to the mentor's review of the original PoC:

**1. Header-based pagination instead of version-threshold branching**

The original design used `X-Metaflow-Client-Version >= 2.0.0` to decide whether to return a paginated envelope or a flat array. The mentor asked about the tradeoffs. The simpler and more robust approach is to always return a flat array and put pagination metadata in response headers — no version parsing, no branching, no two code paths to maintain. This mirrors GitHub and GitLab's pagination design.

**2. `limit+1` trick instead of `COUNT(*)`**

The original design ran `SELECT COUNT(*)` on every request to populate a `total` field. The mentor flagged the performance cost of this, especially under tag filters where the DB must scan all matching rows to count them. The fix: request `limit+1` rows, check if the extra row exists to set `has_more`, then drop it. `COUNT(*)` is never run by default. Exact totals remain available as opt-in via `?include_total=true`.

**3. `@>` containment operator instead of `ANY()`**

The original design used `WHERE $1 = ANY(tags)`. The mentor asked about performance considerations. `ANY()` cannot use a GIN index and always performs a sequential scan. The array containment operator `tags @> ARRAY[$1::text]` uses the GIN index and performs an O(log n) lookup instead.

---

## 📁 File Structure

```
metaflow-pagination-poc/
├── app/
│   ├── main.py            ← aiohttp service: pagination, GIN index, header responses
│   ├── client.py          ← async client that iterates pages via response headers
│   ├── seed.py            ← inserts 1000 test rows with random tags
│   ├── requirements.txt
│   ├── Dockerfile
│   └── __init__.py
├── tests/
│   ├── test_runs.py       ← 11 pytest tests
│   └── __init__.py
├── docker-compose.yml
└── .gitignore
```

---

## 🔗 Related

- GSoC proposal: Metadata Service Request Improvements (Pagination + Server-side Filtering)
- PR #465 — [Unify Dockerfiles into a single multi-stage Dockerfile](https://github.com/Netflix/metaflow-service/pull/465)
