import asyncio
import aiohttp

BASE_URL = "http://localhost:8080"

async def fetch_all_runs(limit=50):
    all_data = []
    offset = 0
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                f"{BASE_URL}/runs",
                params={"limit": limit, "offset": offset},
                headers={"X-Metaflow-Client-Version": "2.0.0"}
            ) as resp:
                result = await resp.json()
                all_data.extend(result["data"])
                if not result["pagination"]["has_more"]:
                    break
                offset = result["pagination"]["next_offset"]
    return all_data

if __name__ == "__main__":
    runs = asyncio.run(fetch_all_runs())
    print(f"Fetched {len(runs)} total runs")