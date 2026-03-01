# Metaflow Pagination POC

This project demonstrates a minimal aiohttp + PostgreSQL service
that mimics the current Metaflow service behavior where all run
records are returned without pagination.

## Tech Stack

- aiohttp
- PostgreSQL
- asyncpg
- Docker Compose

## Database Schema

runs table:

- id (SERIAL PRIMARY KEY)
- flow_id (TEXT)
- created_at (TIMESTAMP)
- tags (TEXT[])

## Setup

docker compose up --build -d

docker exec -it metaflow-app python seed.py

## Endpoint

GET /runs

Returns all records without pagination.

## Baseline Measurement

Measured using:

curl -w "\nSize: %{size_download} bytes\nTime: %{time_total}s\n" \
-o /dev/null -s http://localhost:8080/runs

Size: XXXXX bytes
Time: XXXXX s

This serves as the baseline before implementing pagination.

## Pagination Improvement

Before Pagination:
Size: XXXXX bytes  
Time: XXXXX s  

After Pagination (limit=50):
Size: XXXXX bytes  
Time: XXXXX s  

This demonstrates significant reduction in response size
and improved response time.

## Advanced Features

### Tag Filtering
Supports filtering using PostgreSQL array column:

GET /runs?tags=prod

Uses:
WHERE $1 = ANY(tags)

### Version Detection
Uses X-Metaflow-Client-Version header.

- Clients >= 2.0.0 receive paginated response
- Older clients receive legacy flat response
- Ensures backward compatibility

### Pagination
Supports:
- limit (default 50)
- offset
- total count
- has_more
- next_offset

### Test Coverage
Includes pytest suite covering:
- Pagination behavior
- Offset correctness
- Tag filtering
- Legacy vs new client handling
- Default limit edge case
