import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import Optional
import json
import os
import re
import random

# ==================== CONFIGURATION ====================

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

user_data = {}
user_balances = {}
STARTING_BALANCE = 100
DAILY_BONUS = 50
VC_MINUTES_FOR_DAILY = 30

game_states = {}
active_bets = {}
BETTING_WINDOW = 180
announcement_channels = {}

MATCH_FETCH_DELAY = 60
MATCH_FETCH_RETRIES = 8
MATCH_FETCH_RETRY_INTERVAL = 20

PLACEMENT_MULTIPLIERS = {1: 1.5, 2: 1.3, 3: 1.15, 4: 1.0, 5: 1.0, 6: 1.15, 7: 1.3, 8: 1.5}
PLAYER_BONUSES = {1: (0.20, 30), 2: (0.15, 20), 3: (0.10, 15), 4: (0.05, 10), 5: (0, 0), 6: (0, 0), 7: (0, 0), 8: (0, 0)}
PLACEMENT_EMOJIS = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "💀"}
TRAIT_STYLE_EMOJIS = {0: "⬛", 1: "🟤", 2: "⚪", 3: "🟡", 4: "💎"}

TFT_ACTIVITY_NAMES = ["teamfighttactics", "teamfight tactics"]
IN_GAME_KEYWORDS = ["in game"]
NOT_IN_GAME_KEYWORDS = ["in queue", "queue", "matchmaking", "searching", "lobby", "menu", "idle", "in lobby"]

DATA_DIR = os.getenv("DATA_DIR", ".")
DATA_FILE = os.path.join(DATA_DIR, "user_data.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
BALANCES_FILE = os.path.join(DATA_DIR, "balances.json")

PLATFORM_MAP = {"na": "na1", "euw": "euw1", "eune": "eun1", "kr": "kr", "br": "br1", "oce": "oc1", "jp": "jp1", "tr": "tr1", "lan": "la1", "las": "la2", "ru": "ru"}
REGIONAL_MAP = {"na": "americas", "br": "americas", "lan": "americas", "las": "americas", "oce": "americas", "euw": "europe", "eune": "europe", "tr": "europe", "ru": "europe", "kr": "asia", "jp": "asia"}


# ==================== DATA PERSISTENCE ====================

def load_user_data():
    global user_data
    user_data = json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else {}

def save_user_data():
    with open(DATA_FILE, "w") as f: json.dump(user_data, f, indent=2)

def load_settings():
    global announcement_channels
    if os.path.exists(SETTINGS_FILE):
        data = json.load(open(SETTINGS_FILE))
        announcement_channels = {int(k): v for k, v in data.get("announcement_channels", {}).items()}
    else:
        announcement_channels = {}

def save_settings():
    with open(SETTINGS_FILE, "w") as f: json.dump({"announcement_channels": announcement_channels}, f, indent=2)

def load_balances():
    global user_balances
    user_balances = json.load(open(BALANCES_FILE)) if os.path.exists(BALANCES_FILE) else {}

def save_balances():
    with open(BALANCES_FILE, "w") as f: json.dump(user_balances, f, indent=2)


# ==================== BALANCE MANAGEMENT ====================

def get_balance(user_id: str) -> int:
    if user_id not in user_balances:
        user_balances[user_id] = {"balance": STARTING_BALANCE, "vc_minutes_today": 0, "vc_join_time": None, "daily_claimed": False, "last_daily_date": None}
        save_balances()
    return user_balances[user_id]["balance"]

def update_balance(user_id: str, amount: int) -> int:
    get_balance(user_id)
    user_balances[user_id]["balance"] = max(0, user_balances[user_id]["balance"] + amount)
    save_balances()
    return user_balances[user_id]["balance"]

def set_balance(user_id: str, amount: int) -> int:
    get_balance(user_id)
    user_balances[user_id]["balance"] = max(0, amount)
    save_balances()
    return user_balances[user_id]["balance"]


# ==================== RIOT API CLIENT ====================

class RiotAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"X-Riot-Token": api_key}

    async def _get(self, url: str) -> tuple[int, Optional[dict]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 200: return 200, await resp.json()
                if resp.status == 404: return 404, None
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
        status, data = await self._get(f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}")
        if status == 200 and data:
            print(f"✅ Found: {data.get('gameName')}#{data.get('tagLine')} (puuid: {data['puuid'][:8]}...)")
            return data
        print(f"❌ Account not found: {name}#{tag}")
        return None

    async def get_match_ids(self, puuid: str, region: str = "americas", count: int = 5) -> Optional[list]:
        status, data = await self._get(f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?count={count}")
        return data if status == 200 else None

    async def get_match(self, match_id: str, region: str = "americas") -> Optional[dict]:
        status, data = await self._get(f"https://{region}.api.riotgames.com/tft/match/v1/matches/{match_id}")
        return data if status == 200 else None

riot_api = RiotAPI(os.getenv("RIOT_API_KEY", ""))


# ==================== PRESENCE DETECTION ====================

def get_tft_activity(member: discord.Member) -> Optional[discord.Activity]:
    for activity in member.activities:
        name = getattr(activity, "name", None)
        if name and any(kw in name.lower() for kw in TFT_ACTIVITY_NAMES):
            return activity
    return None

def is_in_game(activity: Optional[discord.Activity]) -> bool:
    """Check if TFT presence indicates active game.
    Known format: name='TeamfightTactics(Ranked)', details/state has 'In Game' or 'In Queue'.
    """
    if not activity: return False
    name = (getattr(activity, "name", None) or "").lower()
    details = (getattr(activity, "details", None) or "").lower()
    state = (getattr(activity, "state", None) or "").lower()
    combined = f"{name} {details} {state}"

    if any(kw in combined for kw in IN_GAME_KEYWORDS): return True
    if any(kw in combined for kw in NOT_IN_GAME_KEYWORDS): return False
    return False

def log_activity(label: str, member: discord.Member):
    for activity in member.activities:
        name = getattr(activity, "name", None) or "?"
        details = getattr(activity, "details", None)
        state = getattr(activity, "state", None)
        parts = [f"[{label}] {type(activity).__name__}: {name}"]
        if details: parts.append(f"details={details}")
        if state: parts.append(f"state={state}")
        print(f"   🎮 {' | '.join(parts)}")
        if hasattr(activity, "to_dict"):
            try: print(f"      RAW: {activity.to_dict()}")
            except: pass


# ==================== DISPLAY HELPERS ====================

def clean_name(raw: str) -> str:
    n = re.sub(r"^(TFT\d+_|Set\d+_|TFT_Item_|TFT_Augment_)", "", raw)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n).replace("_", " ").strip()

def format_traits(traits: list) -> str:
    active = sorted([t for t in traits if t.get("style", 0) > 0], key=lambda t: t.get("style", 0), reverse=True)
    return " | ".join(f"{TRAIT_STYLE_EMOJIS.get(t.get('style', 0), '')} {clean_name(t['name'])} {t.get('num_units', 0)}" for t in active[:6]) or "No active traits"

def format_units(units: list) -> str:
    s = sorted(units, key=lambda u: (u.get("tier", 1), u.get("rarity", 0)), reverse=True)
    return ", ".join(f"{'⭐'*u.get('tier',1)}{clean_name(u.get('character_id','?'))}" for u in s[:8]) or "No units"

def format_augments(augments: list) -> str:
    return " | ".join(clean_name(a) for a in augments) if augments else "None"

def format_duration(s: float) -> str: return f"{int(s//60)}m {int(s%60)}s"

def queue_name(qid: int) -> str:
    return {1090: "Normal", 1100: "Ranked", 1130: "Hyper Roll", 1160: "Double Up", 1210: "Turbo"}.get(qid, "TFT")


# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():
    load_user_data(); load_settings(); load_balances()

    print(f"{'='*55}")
    print(f"✅ {bot.user} is online! (TFT Bot)")
    print(f"{'='*55}")
    print(f"📊 Registered: {len(user_data)} users")
    for uid, info in user_data.items():
        print(f"   └─ {uid}: {info.get('riot_name')}#{info.get('riot_tag')} ({info.get('region')})")
    print(f"📢 Channels: {len(announcement_channels)}")
    print(f"🔗 Guilds: {len(bot.guilds)}")
    for g in bot.guilds: print(f"   └─ {g.name} ({g.id})")
    print(f"{'='*55}")

    try:
        synced = await bot.tree.sync()
        print(f"🔄 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

    # Scan for users already in TFT
    print(f"🔍 Scanning for active TFT sessions...")
    for guild in bot.guilds:
        for member in guild.members:
            uid = str(member.id)
            if uid not in user_data: continue
            activity = get_tft_activity(member)
            if activity and is_in_game(activity):
                print(f"🎮 {member.display_name} already in TFT!")
                log_activity("STARTUP", member)
                game_states[uid] = {"in_game": True, "guild_id": guild.id}
                await open_betting(member, user_data[uid])

    print(f"✅ {sum(1 for s in game_states.values() if s.get('in_game'))} user(s) in TFT")
    print(f"{'='*55}")


@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    user_id = str(after.id)
    if user_id not in user_data: return

    before_tft = get_tft_activity(before)
    after_tft = get_tft_activity(after)
    before_ig = is_in_game(before_tft)
    after_ig = is_in_game(after_tft)

    if (before_tft is not None) != (after_tft is not None) or before_ig != after_ig:
        print(f"{'='*55}")
        print(f"👀 TFT PRESENCE: {after.display_name}")
        print(f"   Before: tft={'yes' if before_tft else 'no'} in_game={before_ig}")
        print(f"   After:  tft={'yes' if after_tft else 'no'} in_game={after_ig}")
        if after_tft: log_activity("AFTER", after)
        print(f"{'='*55}")

    # NOT in game → IN game
    if not before_ig and after_ig:
        print(f"🎮 GAME START: {after.display_name}")
        game_states[user_id] = {"in_game": True, "guild_id": after.guild.id}
        await open_betting(after, user_data[user_id])

    # IN game → NOT in game
    elif before_ig and not after_ig:
        if user_id in game_states and game_states[user_id].get("in_game"):
            game_states[user_id]["in_game"] = False
            print(f"🏁 GAME END: {after.display_name}")
            info = user_data[user_id]
            guild_id = game_states[user_id].get("guild_id", after.guild.id)
            asyncio.create_task(fetch_and_announce(user_id, info, guild_id))


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    user_id = str(member.id)
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    get_balance(user_id)
    ub = user_balances[user_id]

    if ub.get("last_daily_date") != today:
        ub["vc_minutes_today"] = 0; ub["daily_claimed"] = False; ub["last_daily_date"] = today

    if before.channel is None and after.channel is not None:
        ub["vc_join_time"] = now.isoformat(); save_balances()
    elif before.channel is not None and after.channel is None and ub.get("vc_join_time"):
        try:
            mins = int((now - datetime.fromisoformat(ub["vc_join_time"])).total_seconds() / 60)
            ub["vc_minutes_today"] = ub.get("vc_minutes_today", 0) + mins
            ub["vc_join_time"] = None; save_balances()
            if not ub.get("daily_claimed") and ub.get("vc_minutes_today", 0) >= VC_MINUTES_FOR_DAILY:
                ub["daily_claimed"] = True
                nb = update_balance(user_id, DAILY_BONUS)
                ch_id = announcement_channels.get(member.guild.id)
                if ch_id:
                    ch = member.guild.get_channel(ch_id)
                    if ch: await ch.send(f"🎁 **{member.display_name}** earned daily bonus! +**{DAILY_BONUS}** coins (Balance: {nb})")
        except: pass


# ==================== MATCH FETCHING ====================

async def fetch_and_announce(user_id: str, info: dict, guild_id: int):
    puuid, region = info["puuid"], info["region"]
    old_match_id = info.get("last_match_id")

    print(f"⏳ Waiting {MATCH_FETCH_DELAY}s for {info['riot_name']}'s match data...")
    await asyncio.sleep(MATCH_FETCH_DELAY)

    new_match_id = None; match_data = None
    for attempt in range(MATCH_FETCH_RETRIES):
        ids = await riot_api.get_match_ids(puuid, region, count=5)
        if ids:
            for mid in ids:
                if mid != old_match_id:
                    new_match_id = mid; break
        if new_match_id:
            match_data = await riot_api.get_match(new_match_id, region)
            if match_data and match_data.get("info", {}).get("tft_set_number") is not None:
                break
            new_match_id = None; match_data = None
        print(f"   └─ Attempt {attempt+1}/{MATCH_FETCH_RETRIES}: not ready...")
        await asyncio.sleep(MATCH_FETCH_RETRY_INTERVAL)

    if not match_data:
        print(f"❌ No match data for {info['riot_name']}")
        bk = (guild_id, user_id)
        if bk in active_bets: await cancel_bets(bk, "Match data unavailable — all bets refunded")
        return

    info["last_match_id"] = new_match_id; save_user_data()

    player_data = next((p for p in match_data.get("info", {}).get("participants", []) if p.get("puuid") == puuid), None)
    if not player_data:
        print(f"❌ Player not in participants"); return

    placement = player_data.get("placement", 0)
    print(f"📊 {info['riot_name']} placed #{placement}")

    guild = bot.get_guild(guild_id)
    if not guild: return
    member = guild.get_member(int(user_id))
    if not member: return

    await create_announcement(member, info, match_data, player_data, placement)
    await resolve_bets((guild_id, user_id), placement)


# ==================== ANNOUNCEMENTS ====================

async def create_announcement(member, info, match_data, player_data, placement):
    ch_id = announcement_channels.get(member.guild.id)
    if not ch_id: return
    channel = member.guild.get_channel(ch_id)
    if not channel: return

    mi = match_data.get("info", {})
    emoji = PLACEMENT_EMOJIS.get(placement, "❓")
    is_top4 = placement <= 4

    if placement == 1: color, title = discord.Color.gold(), f"{emoji} FIRST PLACE! {info['riot_name']}"
    elif is_top4: color, title = discord.Color.green(), f"{emoji} Top {placement} — {info['riot_name']}"
    elif placement == 8: color, title = discord.Color.dark_red(), f"{emoji} 8th Place... {info['riot_name']}"
    else: color, title = discord.Color.red(), f"{emoji} #{placement} — {info['riot_name']}"

    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Mode", value=queue_name(mi.get("queue_id", 0)), inline=True)
    embed.add_field(name="Duration", value=format_duration(mi.get("game_length", 0)), inline=True)
    embed.add_field(name="Level", value=str(player_data.get("level", "?")), inline=True)
    embed.add_field(name="Traits", value=format_traits(player_data.get("traits", [])), inline=False)
    embed.add_field(name="Board", value=format_units(player_data.get("units", [])), inline=False)
    embed.add_field(name="Augments", value=format_augments(player_data.get("augments", [])), inline=False)
    embed.set_footer(text=f"{info['riot_name']}#{info['riot_tag']} • Set {mi.get('tft_set_number','?')} • Dmg: {player_data.get('total_damage_to_players',0)}")

    await channel.send(embed=embed)
    print(f"✅ Announced {info['riot_name']} #{placement}")


# ==================== BETTING SYSTEM ====================

async def open_betting(member, user_info):
    ch_id = announcement_channels.get(member.guild.id)
    if not ch_id: return
    channel = member.guild.get_channel(ch_id)
    if not channel: return

    bk = (member.guild.id, str(member.id))
    if bk in active_bets: return

    closes_at = datetime.now(timezone.utc).timestamp() + BETTING_WINDOW
    active_bets[bk] = {"player_name": member.display_name, "player_riot_id": f"{user_info['riot_name']}#{user_info['riot_tag']}", "player_user_id": str(member.id), "bets": {"top4": {}, "bot4": {}}, "closes_at": closes_at, "message": None, "guild_id": member.guild.id, "closed": False}

    embed = discord.Embed(
        title=f"🎰 Betting Open: {member.display_name}",
        description=f"**{user_info['riot_name']}#{user_info['riot_tag']}** started a TFT game!\n\nUse `/bet` to place your bet\nBetting closes <t:{int(closes_at)}:R>",
        color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🏆 Top 4 Pool", value="0 coins (0 bets)", inline=True)
    embed.add_field(name="💀 Bot 4 Pool", value="0 coins (0 bets)", inline=True)
    embed.add_field(name="📊 Odds", value="-- / --", inline=True)
    embed.set_footer(text="1st/8th=1.5x • 2nd/7th=1.3x • 3rd/6th=1.15x • 4th/5th=1.0x profit")

    msg = await channel.send(embed=embed)
    active_bets[bk]["message"] = msg
    print(f"🎰 Betting opened: {member.display_name}")
    asyncio.create_task(close_betting_after_delay(bk, BETTING_WINDOW))

async def close_betting_after_delay(bk, delay):
    await asyncio.sleep(delay); await close_betting(bk)

async def close_betting(bk):
    if bk not in active_bets: return
    bd = active_bets[bk]; bd["closed"] = True
    if bd.get("message"):
        try:
            e = bd["message"].embeds[0]; e.title = f"🔒 Betting Closed: {bd['player_name']}"
            e.description = f"**{bd['player_riot_id']}** is in a TFT game!\n\nBetting closed — results when game ends."
            e.color = discord.Color.dark_gray(); await bd["message"].edit(embed=e)
        except: pass
    print(f"🔒 Betting closed: {bd['player_name']}")

async def update_betting_embed(bk):
    if bk not in active_bets: return
    bd = active_bets[bk]
    if not bd.get("message"): return
    t4 = sum(bd["bets"]["top4"].values()); b4 = sum(bd["bets"]["bot4"].values()); total = t4+b4
    hm = 0.95 if total >= 100 else 1.0
    t4o = f"{((total*hm)/t4):.2f}x" if t4>0 and total>0 else "--"
    b4o = f"{((total*hm)/b4):.2f}x" if b4>0 and total>0 else "--"
    try:
        e = bd["message"].embeds[0]
        e.set_field_at(0, name="🏆 Top 4 Pool", value=f"{t4} coins ({len(bd['bets']['top4'])} bets)", inline=True)
        e.set_field_at(1, name="💀 Bot 4 Pool", value=f"{b4} coins ({len(bd['bets']['bot4'])} bets)", inline=True)
        e.set_field_at(2, name="📊 Odds (T4/B4)", value=f"{t4o} / {b4o}", inline=True)
        await bd["message"].edit(embed=e)
    except: pass

async def cancel_bets(bk, reason):
    if bk not in active_bets: return
    bd = active_bets.pop(bk)
    for side in ["top4","bot4"]:
        for uid, amt in bd["bets"][side].items(): update_balance(uid, amt)
    g = bot.get_guild(bd["guild_id"]); ch_id = announcement_channels.get(bd["guild_id"])
    if g and ch_id:
        ch = g.get_channel(ch_id)
        if ch: await ch.send(f"⚠️ Bets cancelled for **{bd['player_name']}**: {reason}")

def calculate_payouts(bd, placement):
    is_top4 = placement <= 4
    ws = "top4" if is_top4 else "bot4"; ls = "bot4" if is_top4 else "top4"
    wb = bd["bets"][ws]; lb = bd["bets"][ls]
    wt = sum(wb.values()); lt = sum(lb.values()); total = wt + lt
    pm = PLACEMENT_MULTIPLIERS.get(placement, 1.0)
    results = {uid: {"payout": 0, "profit": -amt, "bet": amt, "side": ls, "multiplier": None} for uid, amt in lb.items()}

    if total == 0 or wt == 0: return results
    hc = 0.05 if total >= 100 else 0.0

    if lt == 0:
        for uid, amt in wb.items():
            bonus = max(1, int(amt * 0.20 * pm))
            results[uid] = {"payout": amt+bonus, "profit": bonus, "bet": amt, "side": ws, "multiplier": pm}
        return results

    if len(wb) + len(lb) == 1:
        for uid, amt in wb.items():
            bonus = max(1, int(amt * 0.25 * pm))
            results[uid] = {"payout": amt+bonus, "profit": bonus, "bet": amt, "side": ws, "multiplier": pm}
        return results

    pool = total - int(total * hc)
    for uid, amt in wb.items():
        base = int(pool * (amt / wt)); profit = int((base - amt) * pm)
        results[uid] = {"payout": max(0, amt + profit), "profit": profit, "bet": amt, "side": ws, "multiplier": pm}
    return results

async def resolve_bets(bk, placement):
    if bk not in active_bets: return
    bd = active_bets.pop(bk)
    is_top4 = placement <= 4
    total = sum(bd["bets"]["top4"].values()) + sum(bd["bets"]["bot4"].values())

    puid = bd["player_user_id"]
    pp, fb = PLAYER_BONUSES.get(placement, (0,0))
    pbonus = int(total * pp) + fb if (pp or fb) else 0
    if pbonus > 0: update_balance(puid, pbonus)

    g = bot.get_guild(bd["guild_id"]); ch_id = announcement_channels.get(bd["guild_id"])
    if not g or not ch_id: return
    ch = g.get_channel(ch_id)
    if not ch: return

    if total == 0:
        if pbonus > 0: await ch.send(f"🏆 **{bd['player_name']}** placed **#{placement}**! +**{pbonus}** coins")
        return

    payouts = calculate_payouts(bd, placement)
    for uid, r in payouts.items():
        if r["payout"] > 0: update_balance(uid, r["payout"])

    emoji = PLACEMENT_EMOJIS.get(placement, "❓")
    embed = discord.Embed(
        title=f"🎰 Bets Resolved: {bd['player_name']} {emoji} #{placement}",
        description=f"**{bd['player_riot_id']}** placed **#{placement}** ({'TOP 4' if is_top4 else 'BOTTOM 4'})",
        color=discord.Color.green() if is_top4 else discord.Color.red(), timestamp=datetime.now(timezone.utc))

    mult = PLACEMENT_MULTIPLIERS.get(placement, 1.0)
    embed.add_field(name="📊 Placement Bonus", value=f"**{mult}x** profit multiplier", inline=False)
    if pbonus > 0:
        embed.add_field(name="🏆 Player Bonus", value=f"**{bd['player_name']}** earned **+{pbonus}** coins", inline=False)

    sr = sorted(payouts.items(), key=lambda x: x[1]["profit"], reverse=True)
    wt, lt, mentions = [], [], []
    for uid, r in sr:
        try:
            m = g.get_member(int(uid)); name = m.display_name if m else f"User {uid[:8]}"
            if m: mentions.append(m.mention)
        except: name = f"User {uid[:8]}"
        mt = f" ({r['multiplier']}x)" if r.get("multiplier") else ""
        if r["profit"] > 0: wt.append(f"🤑 **{name}**: +{r['profit']} coins{mt} (bet {r['bet']} on {r['side']})")
        elif r["profit"] == 0: wt.append(f"😐 **{name}**: ±0 (bet {r['bet']} on {r['side']})")
        else: lt.append(f"😭 **{name}**: {r['profit']} coins (bet {r['bet']} on {r['side']})")
    if wt: embed.add_field(name="Winners", value="\n".join(wt[:10]), inline=False)
    if lt: embed.add_field(name="Losers", value="\n".join(lt[:10]), inline=False)

    embed.set_footer(text=f"Total pool: {total} coins" + (f" • House took: {int(total*0.05)}" if total >= 100 else ""))
    await ch.send(content=" ".join(mentions) if mentions else "", embed=embed)
    print(f"🎰 Resolved: {bd['player_name']} #{placement}")


# ==================== SLASH COMMANDS ====================

@bot.tree.command(name="register", description="Register your Riot ID to track TFT games")
@app_commands.describe(riot_name="Your Riot username", riot_tag="Your Riot tag (e.g. NA1)", region="Your region")
@app_commands.choices(region=[
    app_commands.Choice(name="North America", value="na"), app_commands.Choice(name="Europe West", value="euw"),
    app_commands.Choice(name="Europe Nordic & East", value="eune"), app_commands.Choice(name="Korea", value="kr"),
    app_commands.Choice(name="Brazil", value="br"), app_commands.Choice(name="Oceania", value="oce"),
    app_commands.Choice(name="Japan", value="jp"),
])
async def register(interaction: discord.Interaction, riot_name: str, riot_tag: str, region: str = "na"):
    await interaction.response.defer(ephemeral=True)
    regional = REGIONAL_MAP.get(region, "americas"); platform = PLATFORM_MAP.get(region, "na1")
    account = await riot_api.get_account(riot_name, riot_tag, regional)
    if not account:
        await interaction.followup.send(f"❌ Could not find **{riot_name}#{riot_tag}**.", ephemeral=True); return

    uid = str(interaction.user.id); puuid = account["puuid"]
    ids = await riot_api.get_match_ids(puuid, regional, count=1)
    user_data[uid] = {"riot_name": account.get("gameName", riot_name), "riot_tag": account.get("tagLine", riot_tag), "puuid": puuid, "platform": platform, "region": regional, "last_match_id": ids[0] if ids else None, "registered_at": datetime.now(timezone.utc).isoformat()}
    save_user_data()
    print(f"📝 Registered: {interaction.user.display_name} → {riot_name}#{riot_tag}")
    await interaction.followup.send(f"✅ Registered **{account.get('gameName')}#{account.get('tagLine')}** ({region.upper()})!\nI'll detect your TFT games via Discord presence and fetch results from Riot's API.", ephemeral=True)

@bot.tree.command(name="unregister", description="Stop tracking your TFT games")
async def unregister(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if uid in user_data: del user_data[uid]; save_user_data(); game_states.pop(uid, None); await interaction.response.send_message("✅ Unregistered.", ephemeral=True)
    else: await interaction.response.send_message("❌ Not registered.", ephemeral=True)

@bot.tree.command(name="setchannel", description="Set announcement channel (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    announcement_channels[interaction.guild.id] = channel.id; save_settings()
    await interaction.response.send_message(f"✅ TFT announcements → {channel.mention}")

@bot.tree.command(name="status", description="See who is tracked")
async def status(interaction: discord.Interaction):
    if not user_data: await interaction.response.send_message("No one registered.", ephemeral=True); return
    lines = [f"{'🎮' if game_states.get(uid,{}).get('in_game') else '💤'} **{info['riot_name']}#{info['riot_tag']}** — {'in game' if game_states.get(uid,{}).get('in_game') else 'idle'}" for uid, info in user_data.items()]
    await interaction.response.send_message(f"**Tracking {len(user_data)} player(s):**\n" + "\n".join(lines), ephemeral=True)

@bot.tree.command(name="stats", description="Your recent TFT stats")
async def stats(interaction: discord.Interaction):
    await interaction.response.defer()
    uid = str(interaction.user.id)
    if uid not in user_data: await interaction.followup.send("❌ `/register` first!"); return
    info = user_data[uid]; ids = await riot_api.get_match_ids(info["puuid"], info["region"], count=10)
    if not ids: await interaction.followup.send("❌ No match history."); return

    placements = []
    for mid in ids[:10]:
        m = await riot_api.get_match(mid, info["region"])
        if m:
            p = next((p for p in m.get("info",{}).get("participants",[]) if p.get("puuid")==info["puuid"]), None)
            if p: placements.append(p.get("placement", 0))
        await asyncio.sleep(0.4)
    if not placements: await interaction.followup.send("❌ No TFT matches."); return

    t4 = sum(1 for p in placements if p<=4); avg = sum(placements)/len(placements)
    embed = discord.Embed(title="📊 TFT Stats", description=f"**{info['riot_name']}#{info['riot_tag']}**", color=discord.Color.blurple())
    embed.add_field(name=f"Last {len(placements)}", value=f"Top 4: **{t4}** | Bot 4: **{len(placements)-t4}**", inline=True)
    embed.add_field(name="Avg", value=f"**{avg:.1f}**", inline=True)
    embed.add_field(name="1sts/8ths", value=f"🥇 {sum(1 for p in placements if p==1)} / 💀 {sum(1 for p in placements if p==8)}", inline=True)
    embed.add_field(name="Recent", value=" ".join(PLACEMENT_EMOJIS.get(p,"?") for p in placements), inline=False)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="bet", description="Bet on a player's TFT game")
@app_commands.describe(player="Player to bet on", outcome="Top 4 or Bottom 4", amount="Coins to bet")
@app_commands.choices(outcome=[app_commands.Choice(name="Top 4 (1st-4th)", value="top4"), app_commands.Choice(name="Bottom 4 (5th-8th)", value="bot4")])
async def bet(interaction: discord.Interaction, player: discord.Member, outcome: str, amount: int):
    uid = str(interaction.user.id); bk = (interaction.guild.id, str(player.id))
    if bk not in active_bets: await interaction.response.send_message(f"❌ No betting open for **{player.display_name}**.", ephemeral=True); return
    bd = active_bets[bk]
    if bd.get("closed") or datetime.now(timezone.utc).timestamp() > bd["closes_at"]:
        await interaction.response.send_message("❌ Betting is closed.", ephemeral=True); return
    if amount <= 0: await interaction.response.send_message("❌ Must be positive!", ephemeral=True); return
    bal = get_balance(uid)
    if amount > bal: await interaction.response.send_message(f"❌ You only have **{bal}** coins.", ephemeral=True); return
    for s in ["top4","bot4"]:
        if uid in bd["bets"][s]: await interaction.response.send_message(f"❌ Already bet **{bd['bets'][s][uid]}** on **{s}**.", ephemeral=True); return

    update_balance(uid, -amount); bd["bets"][outcome][uid] = amount; await update_betting_embed(bk)
    t4 = sum(bd["bets"]["top4"].values()); b4 = sum(bd["bets"]["bot4"].values()); total = t4+b4
    mp = t4 if outcome=="top4" else b4; hm = 0.95 if total>=100 else 1.0
    pot = int(amount*(total*hm)/mp) if mp>0 else amount
    await interaction.response.send_message(f"✅ **{amount}** coins on **{player.display_name}** → **{outcome.upper()}**\nPotential: ~**{pot}** coins (before placement bonus)\nBalance: **{get_balance(uid)}** coins", ephemeral=True)
    print(f"🎰 {interaction.user.display_name} bet {amount} on {player.display_name} → {outcome}")

@bot.tree.command(name="balance", description="Check your coins")
async def balance(interaction: discord.Interaction):
    uid = str(interaction.user.id); bal = get_balance(uid); ub = user_balances.get(uid, {})
    embed = discord.Embed(title=f"💰 {interaction.user.display_name}", color=discord.Color.gold())
    embed.add_field(name="Coins", value=f"**{bal}** 🪙", inline=True)
    embed.add_field(name="VC Today", value=f"{ub.get('vc_minutes_today',0)} min", inline=True)
    if ub.get("daily_claimed"): embed.add_field(name="Daily", value="✅", inline=True)
    else: embed.add_field(name="Daily", value=f"⏳ {max(0, VC_MINUTES_FOR_DAILY - ub.get('vc_minutes_today',0))} min left", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="leaderboard", description="Coin leaderboard")
async def leaderboard(interaction: discord.Interaction):
    if not user_balances: await interaction.response.send_message("No coins yet!", ephemeral=True); return
    su = sorted(user_balances.items(), key=lambda x: x[1].get("balance",0), reverse=True)[:10]
    embed = discord.Embed(title="🏆 Leaderboard", color=discord.Color.gold())
    lines = []
    for i, (uid, d) in enumerate(su, 1):
        try: m = interaction.guild.get_member(int(uid)); name = m.display_name if m else f"User {uid[:8]}"
        except: name = f"User {uid[:8]}"
        medal = ["🥇","🥈","🥉"][i-1] if i<=3 else f"{i}."
        lines.append(f"{medal} **{name}**: {d.get('balance',0)} coins")
    embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="set", description="Set a user's balance (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def set_coins(interaction: discord.Interaction, user: discord.Member, amount: int):
    nb = set_balance(str(user.id), amount)
    await interaction.response.send_message(f"✅ **{user.display_name}** → **{nb}** coins")

@bot.tree.command(name="resetcoins", description="Reset ALL users' coins to starting balance (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def reset_coins(interaction: discord.Interaction):
    count = len(user_balances)
    for uid in user_balances:
        user_balances[uid]["balance"] = STARTING_BALANCE
    save_balances()
    await interaction.response.send_message(f"🔄 Reset **{count}** user(s) to **{STARTING_BALANCE}** coins.")
    print(f"🔄 Admin {interaction.user.display_name} reset all balances ({count} users)")

@bot.tree.command(name="rules", description="Show rules and commands")
async def rules(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 TFT Betting Bot", color=discord.Color.blue())
    embed.add_field(name="🎮 Tracking", value="`/register` `/unregister` `/stats` `/status`", inline=False)
    embed.add_field(name="🎰 Betting", value="`/bet <player> <top4|bot4> <amount>`\n`/balance` `/leaderboard`", inline=False)
    embed.add_field(name="📊 Placement Multipliers", value="🥇1st/💀8th = **1.5x** • 🥈2nd/7th = **1.3x** • 🥉3rd/6th = **1.15x** • 4th/5th = **1.0x**", inline=False)
    embed.add_field(name="💰 Earning", value="**Top 4:** 5-20% pot + flat bonus\n**VC 30min:** 50 coins daily\n**Start:** 100 coins", inline=False)
    embed.add_field(name="🏠 House", value="5% cut only on pools ≥ 100 coins", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="debugpresence", description="Debug: show your current Discord activities")
async def debugpresence(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user; lines = []
    for a in target.activities:
        parts = [f"**{type(a).__name__}**: {getattr(a,'name','?')}"]
        if getattr(a,'details',None): parts.append(f"details=`{a.details}`")
        if getattr(a,'state',None): parts.append(f"state=`{a.state}`")
        if getattr(a,'application_id',None): parts.append(f"app_id=`{a.application_id}`")
        lines.append(" | ".join(parts))
        if hasattr(a,"to_dict"):
            try:
                raw = json.dumps(a.to_dict(), indent=2)[:500]
                lines.append(f"```json\n{raw}\n```")
            except: pass
    if not lines: lines = ["No activities"]
    tft = get_tft_activity(target); ig = is_in_game(tft)
    lines.append(f"\n**TFT:** {'✅' if tft else '❌'} | **In game:** {'✅' if ig else '❌'}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# ==================== RUN ====================

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token: print("❌ Set DISCORD_BOT_TOKEN in .env"); exit(1)
    rk = os.getenv("RIOT_API_KEY")
    if not rk: print("⚠️ No RIOT_API_KEY — match results won't work")
    else: print(f"🔑 Riot key: {rk[:12]}...")
    bot.run(token)