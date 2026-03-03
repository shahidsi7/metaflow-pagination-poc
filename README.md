# Metaflow Pagination PoC

This repository demonstrates a minimal reproduction of the current Metaflow metadata service behavior and a safe, backwards-compatible pagination improvement.

The goal is to:

* Benchmark the **uncapped response problem**
* Implement **DB-level pagination**
* Preserve **backwards compatibility**
* Provide measurable **before/after comparison**

The entire setup runs using Docker.

---

# 🚀 Quick Start (Under 5 Minutes)

## 1️⃣ Clone the Repository

```bash
git clone https://github.com/shahidsi7/metaflow-pagination-poc.git
cd metaflow-pagination-poc/
```

---

## 2️⃣ Start Services

This project uses Docker Compose .

```bash
docker compose up --build -d
```

This starts:

* PostgreSQL (port 5432)
* aiohttp app (port 8080)

---

## 3️⃣ Seed the Database

Populate 1000 run records:

```bash
docker exec -it metaflow-app python seed.py
```

Seeder implementation: 

You should see:

```
Inserted 1000 records.
```

---

## 4️⃣ Baseline Test (Before Pagination)

Measure raw response size and latency:

```bash
curl -w "\nSize: %{size_download} bytes\nTime: %{time_total}s\n" -o /dev/null -s http://localhost:8080/runs
```

### 📊 Baseline Results (1000 rows)

Example benchmark on local machine:

| Metric        | Value          |
| ------------- | -------------- |
| Response Size | ~780,000 bytes |
| Response Time | ~0.120s        |

Problem:

* Entire dataset returned
* High memory usage
* No control over payload size

---

# ✅ Pagination Implementation

Pagination is implemented in `main.py` .

Features:

* `limit` (default 50)
* `offset`
* `total` count
* `has_more`
* `next_offset`
* Tag filtering
* Version-aware response format

---

## 5️⃣ After Pagination (New Client)

```bash
curl -H "X-Metaflow-Client-Version: 2.0.0" "http://localhost:8080/runs?limit=50&offset=0"
```

### 📊 After Pagination Results (limit=50)

| Metric        | Value         |
| ------------- | ------------- |
| Response Size | ~39,000 bytes |
| Response Time | ~0.015s       |

### 🔥 Improvement

* ~95% reduction in payload size
* ~8x faster response time
* Controlled DB-level pagination

---

# 📦 Response Formats

## Legacy Clients (No Header)

```bash
curl http://localhost:8080/runs
```

Response:

```json
[
  {...},
  {...}
]
```

Flat list — identical to original behavior.

---

## New Clients (Header ≥ 2.0.0)

```bash
curl -H "X-Metaflow-Client-Version: 2.0.0" http://localhost:8080/runs
```

Response:

```json
{
  "data": [...],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 1000,
    "has_more": true,
    "next_offset": 50
  }
}
```

---

# 🔄 Backwards Compatibility Design

This PoC preserves compatibility using **header-based version detection**:

Implemented in `main.py` .

Logic:

```
If X-Metaflow-Client-Version >= 2.0.0
    → return paginated envelope
Else
    → return legacy flat list
```

Why this works:

* Existing clients receive unchanged response
* No breaking changes
* Gradual migration possible
* Server controls rollout centrally

This ensures zero disruption for older Metaflow clients.

---

# 🧪 Test Coverage

Comprehensive pytest suite provided in .

Run tests:

```bash
docker exec -it metaflow-app pytest
```

Test coverage includes:

* Default limit behavior
* Offset correctness
* Last page detection
* Tag filtering
* Legacy vs new client behavior
* Default limit edge case

---

# 🔎 Advanced Features

## Tag Filtering

```bash
curl -H "X-Metaflow-Client-Version: 2.0.0" "http://localhost:8080/runs?tags=prod"
```

Uses PostgreSQL array filtering:

```sql
WHERE $1 = ANY(tags)
```

---

## Full Client Pagination Example

An async client implementation is included in .

Run:

```bash
docker exec -it metaflow-app python client.py
```

Output:

```
Fetched 1000 total runs
```

Demonstrates proper use of:

* `has_more`
* `next_offset`

---

# 🏗 Architectural Notes

This PoC intentionally mimics:

* Unbounded listing endpoint behavior
* Database-backed metadata service
* Realistic filtering & ordering

But simplifies:

* No DB abstraction layer
* No decorator-based response wrapping
* No composite keys

The real Metaflow service uses layered abstractions, which informed the design decisions in this proposal.

---

# 📈 Before vs After Summary

| Feature             | Before                 | After                |
| ------------------- | ---------------------- | -------------------- |
| Payload Size        | Large (entire dataset) | Controlled via limit |
| Memory Usage        | High                   | Bounded              |
| Latency             | Scales with table size | Constant per page    |
| Backward Compatible | N/A                    | Yes                  |
| Total Count         | No                     | Yes                  |
| Client Migration    | N/A                    | Header-controlled    |

---

# 🎯 Conclusion

This PoC demonstrates:

* DB-level pagination is essential for scalability
* Backwards compatibility can be preserved safely
* Performance improves significantly
* Design integrates cleanly with version detection

The repository can be cloned and executed in under 5 minutes using only Docker and this README.

---

If extending this to production:

* Enforce maximum limit cap
* Add index optimizations
* Evaluate COUNT(*) cost on large datasets
* Consider gradual rollout strategy

---

**End of README**
