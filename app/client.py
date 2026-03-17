import asyncio
import aiohttp

BASE_URL = "http://localhost:8080"


async def fetch_all_runs(limit=50, tag_filter=None):
    """
    Fetch all runs by following header-based pagination.

    Pagination metadata is returned in response headers:
      X-Has-More    : "true" or "false"
      X-Next-Offset : next offset value (empty string if no next page)

    The response body is always a flat JSON array — identical for all clients.
    This client reads the headers to decide whether to continue paginating.
    """
    all_data = []
    offset = 0

    params = {"limit": limit, "offset": offset}
    if tag_filter:
        params["tags"] = tag_filter

    async with aiohttp.ClientSession() as session:
        while True:
            params["offset"] = offset

            async with session.get(f"{BASE_URL}/runs", params=params) as resp:
                # Response body is always a flat array
                data = await resp.json()
                all_data.extend(data)

                # Pagination info is in headers — no response body change needed
                has_more = resp.headers.get("X-Has-More", "false").lower() == "true"
                next_offset = resp.headers.get("X-Next-Offset", "")

                if not has_more or not next_offset:
                    break

                offset = int(next_offset)

    return all_data


if __name__ == "__main__":
    runs = asyncio.run(fetch_all_runs())
    print(f"Fetched {len(runs)} total runs")
