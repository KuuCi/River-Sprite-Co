import random
import re
import aiohttp
from collections import Counter
from typing import Optional
from bot.config import BLESSED_COUNT, CURSED_COUNT, BLESSED_BONUS, CURSED_PENALTY, THREE_STAR_BOUNTY, CURRENT_TFT_SET
from bot.helpers import clean_name
from bot import state


CDRAGON_URL = "https://raw.communitydragon.org/latest/cdragon/tft/en_us.json"
DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"


async def load_champion_pool() -> Optional[int]:
    """Load TFT champions. Tries CDragon first (accurate set data), falls back to DDragon."""
    detected_set = None

    # Try CDragon first — it has proper set separation
    detected_set = await _load_from_cdragon()

    # Fall back to DDragon if CDragon failed
    if not state.champion_pool:
        detected_set = await _load_from_ddragon()

    if not state.champion_pool:
        print("⚠️ No champions loaded — challenges will be disabled until next restart")

    return detected_set


async def _load_from_cdragon() -> Optional[int]:
    """Load from Community Dragon which separates champions by set."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CDRAGON_URL) as resp:
                if resp.status != 200:
                    print(f"⚠️ CDragon returned {resp.status}, falling back to DDragon")
                    return None
                data = await resp.json()

                # CDragon has setData array with per-set champion lists
                set_data = data.get("setData", [])
                if not set_data:
                    print("⚠️ CDragon has no setData")
                    return None

                # Find the target set (configured or highest available)
                target_set = None
                target_champs = None
                for s in set_data:
                    num = s.get("number") or s.get("mutator")
                    if num == CURRENT_TFT_SET:
                        target_set = num
                        target_champs = s.get("champions", [])
                        break

                # If configured set not found, use the highest numbered set
                if not target_champs:
                    best = max(set_data, key=lambda s: s.get("number", 0) or 0)
                    target_set = best.get("number")
                    target_champs = best.get("champions", [])

                if not target_champs:
                    print("⚠️ CDragon: no champions in set data")
                    return None

                state.champion_pool.clear()
                for champ in target_champs:
                    api_name = champ.get("apiName", "")
                    name = champ.get("name", clean_name(api_name))
                    if name and api_name:
                        state.champion_pool.append({"id": api_name, "name": name})

                print(f"✅ CDragon: Loaded {len(state.champion_pool)} Set {target_set} champions")
                return target_set
    except Exception as e:
        print(f"⚠️ CDragon error: {e}")
        return None


async def _load_from_ddragon() -> Optional[int]:
    """Fallback: load from Data Dragon, filtering by set prefix."""
    detected_set = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DDRAGON_VERSIONS_URL) as resp:
                if resp.status != 200:
                    print("❌ Failed to fetch DDragon versions")
                    return None
                versions = await resp.json()
                version = versions[0]
                print(f"📦 DDragon version: {version}")

            url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/tft-champion.json"
            async with session.get(url) as resp:
                if resp.status != 200:
                    print("❌ Failed to fetch DDragon TFT champions")
                    return None
                data = await resp.json()
                champs = data.get("data", {})

                # Use configured set number
                target_prefix = f"TFT{CURRENT_TFT_SET}_"

                state.champion_pool.clear()
                for champ_id, champ_data in champs.items():
                    if champ_id.startswith(target_prefix):
                        state.champion_pool.append({
                            "id": champ_id,
                            "name": champ_data.get("name", clean_name(champ_id)),
                        })

                detected_set = CURRENT_TFT_SET
                print(f"✅ DDragon: Loaded {len(state.champion_pool)} Set {detected_set} champions (filtered from {len(champs)} total)")
    except Exception as e:
        print(f"❌ DDragon error: {e}")

    return detected_set


def generate_challenges() -> dict:
    """Generate random blessed/cursed units and a 3-star bounty for a game."""
    pool = state.champion_pool
    needed = BLESSED_COUNT + CURSED_COUNT + 1
    if len(pool) < needed:
        return {"blessed": [], "cursed": [], "three_star_target": None}

    picks = random.sample(pool, needed)
    return {
        "blessed": picks[:BLESSED_COUNT],
        "cursed": picks[BLESSED_COUNT:BLESSED_COUNT + CURSED_COUNT],
        "three_star_target": picks[-1],
    }


def format_challenges(challenges: dict) -> str:
    lines = []
    if challenges.get("blessed"):
        names = ", ".join(f"**{c['name']}**" for c in challenges["blessed"])
        lines.append(f"😇 Blessed: {names} (+{BLESSED_BONUS} coins each)")
    if challenges.get("cursed"):
        names = ", ".join(f"**{c['name']}**" for c in challenges["cursed"])
        lines.append(f"😈 Cursed: {names} (-{CURSED_PENALTY} coins each)")
    if challenges.get("three_star_target"):
        lines.append(f"⭐⭐⭐ 3-Star Bounty: **{challenges['three_star_target']['name']}** (+{THREE_STAR_BOUNTY} coins)")
    return "\n".join(lines) if lines else "No challenges"


def evaluate_challenges(challenges: dict, player_data: dict) -> dict:
    """Check player's final board against challenges."""
    units = player_data.get("units", [])
    board_ids = {u.get("character_id", "").lower() for u in units}
    board_3stars = {u.get("character_id", "").lower() for u in units if u.get("tier", 1) >= 3}

    result = {"total": 0, "details": []}

    for champ in challenges.get("blessed", []):
        if champ["id"].lower() in board_ids:
            result["total"] += BLESSED_BONUS
            result["details"].append(f"😇 **{champ['name']}** on board → +{BLESSED_BONUS}")

    for champ in challenges.get("cursed", []):
        if champ["id"].lower() in board_ids:
            result["total"] -= CURSED_PENALTY
            result["details"].append(f"😈 **{champ['name']}** on board → -{CURSED_PENALTY}")

    target = challenges.get("three_star_target")
    if target and target["id"].lower() in board_3stars:
        result["total"] += THREE_STAR_BOUNTY
        result["details"].append(f"⭐⭐⭐ **{target['name']}** 3-STARRED! → +{THREE_STAR_BOUNTY}")

    return result