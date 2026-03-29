import aiohttp
from typing import Optional


class RiotAPI:
    """Client for Riot's official TFT API — used only for match history after games end."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"X-Riot-Token": api_key}

    async def _get(self, url: str) -> tuple[int, Optional[dict]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 200:
                    return 200, await resp.json()
                if resp.status == 404:
                    return 404, None
                if resp.status == 429:
                    print(f"⚠️ Rate limited! Retry after {resp.headers.get('Retry-After', '?')}s")
                    return 429, None
                if resp.status == 403:
                    print(f"❌ Riot API key invalid/expired (403). Regenerate at developer.riotgames.com")
                    return 403, None
                print(f"❌ Riot API {resp.status}: {(await resp.text())[:200]}")
                return resp.status, None

    async def get_account(self, name: str, tag: str, region: str = "americas") -> Optional[dict]:
        print(f"🔍 Riot API: Looking up {name}#{tag}")
        status, data = await self._get(
            f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}"
        )
        if status == 200 and data:
            print(f"✅ Found: {data.get('gameName')}#{data.get('tagLine')} (puuid: {data['puuid'][:8]}...)")
            return data
        print(f"❌ Account not found: {name}#{tag}")
        return None

    async def get_match_ids(self, puuid: str, region: str = "americas", count: int = 5) -> Optional[list]:
        status, data = await self._get(
            f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?count={count}"
        )
        return data if status == 200 else None

    async def get_match(self, match_id: str, region: str = "americas") -> Optional[dict]:
        status, data = await self._get(
            f"https://{region}.api.riotgames.com/tft/match/v1/matches/{match_id}"
        )
        return data if status == 200 else None