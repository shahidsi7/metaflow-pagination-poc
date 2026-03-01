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
