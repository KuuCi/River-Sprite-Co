import random
import re
import aiohttp
from collections import Counter
from typing import Optional
from bot.config import BLESSED_COUNT, CURSED_COUNT, BLESSED_BONUS, CURSED_PENALTY, THREE_STAR_BOUNTY
from bot.helpers import clean_name
from bot import state


async def load_champion_pool() -> Optional[int]:
    """Fetch TFT champion list from Data Dragon. Returns detected set number or None."""
    detected_set = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://ddragon.leagueoflegends.com/api/versions.json") as resp:
                if resp.status != 200:
                    print("❌ Failed to fetch DDragon versions"); return None
                versions = await resp.json()
                version = versions[0]
                print(f"📦 Data Dragon version: {version}")

            url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/tft-champion.json"
            async with session.get(url) as resp:
                if resp.status != 200:
                    print("❌ Failed to fetch TFT champions"); return None
                data = await resp.json()
                champs = data.get("data", {})

                state.champion_pool.clear()
                set_numbers = Counter()
                for champ_id, champ_data in champs.items():
                    state.champion_pool.append({
                        "id": champ_id,
                        "name": champ_data.get("name", clean_name(champ_id)),
                    })
                    # Extract set number from ID like "TFT13_Ahri"
                    match = re.match(r"TFT(\d+)_", champ_id)
                    if match:
                        set_numbers[int(match.group(1))] += 1

                # Most common set number = current set
                if set_numbers:
                    detected_set = set_numbers.most_common(1)[0][0]

                print(f"✅ Loaded {len(state.champion_pool)} TFT champions (Set {detected_set})")
    except Exception as e:
        print(f"❌ Champion pool load error: {e}")

    if not state.champion_pool:
        print("⚠️ Using fallback champion pool")
        for name in ["Ahri", "Jinx", "Yasuo", "Lux", "Zed", "Sona", "Garen", "Darius", "Vi", "Ezreal",
                      "Morgana", "Warwick", "Fiora", "Shen", "Jax", "Kayle", "Irelia", "Yone", "Akali", "Viego"]:
            state.champion_pool.append({"id": f"TFT_Fallback_{name}", "name": name})

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