import discord
from discord.ext import commands
import asyncio
from datetime import datetime, timezone

from bot.config import (
    MATCH_FETCH_DELAY, MATCH_FETCH_RETRIES, MATCH_FETCH_RETRY_INTERVAL,
    DAILY_BONUS, VC_MINUTES_FOR_DAILY,
)
from bot import state
from bot.storage import (
    load_user_data, load_settings, load_balances,
    save_user_data, save_balances, get_balance, update_balance,
)
from bot.presence import get_tft_activity, is_in_game, log_activity
from bot.challenges import load_champion_pool
from bot.betting import open_betting, cancel_bets, queue_result


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        load_user_data()
        load_settings()
        load_balances()
        await load_champion_pool()

        print(f"{'=' * 55}")
        print(f"✅ {self.bot.user} is online! (TFT Bot)")
        print(f"{'=' * 55}")
        print(f"📊 Registered: {len(state.user_data)} users")
        for uid, info in state.user_data.items():
            print(f"   └─ {uid}: {info.get('riot_name')}#{info.get('riot_tag')} ({info.get('region')})")
        print(f"📢 Channels: {len(state.announcement_channels)}")
        print(f"🔗 Guilds: {len(self.bot.guilds)}")
        for g in self.bot.guilds:
            print(f"   └─ {g.name} ({g.id})")
        print(f"{'=' * 55}")

        try:
            synced = await self.bot.tree.sync()
            print(f"🔄 Synced {len(synced)} slash commands")
        except Exception as e:
            print(f"❌ Sync failed: {e}")

        # Scan for active TFT sessions
        print("🔍 Scanning for active TFT sessions...")
        visible_count = 0
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                uid = str(member.id)
                if member.activities:
                    visible_count += 1
                    if uid in state.user_data:
                        acts = ", ".join(
                            f"{getattr(a, 'name', '?')}(details={getattr(a, 'details', None)}, state={getattr(a, 'state', None)})"
                            for a in member.activities
                        )
                        print(f"   👁️ {member.display_name}: {acts}")
                elif uid in state.user_data:
                    print(f"   ❌ {member.display_name}: registered but 0 activities visible (status={member.status})")
        print(f"   📊 Total: {visible_count} members with visible activities")

        for guild in self.bot.guilds:
            for member in guild.members:
                uid = str(member.id)
                if uid not in state.user_data:
                    continue
                activity = get_tft_activity(member)
                if activity and is_in_game(activity):
                    print(f"🎮 {member.display_name} already in TFT!")
                    log_activity("STARTUP", member)
                    state.game_states[uid] = {"in_game": True, "guild_id": guild.id}
                    await open_betting(self.bot, member, state.user_data[uid])

        print(f"✅ {sum(1 for s in state.game_states.values() if s.get('in_game'))} user(s) in TFT")
        print(f"{'=' * 55}")

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        user_id = str(after.id)

        # Debug logging for registered users
        if user_id in state.user_data:
            before_acts = [f"{getattr(a, 'name', '?')}" for a in before.activities]
            after_acts = [f"{getattr(a, 'name', '?')}" for a in after.activities]
            before_status = str(before.status)
            after_status = str(after.status)

            if before_status != after_status or before_acts != after_acts:
                print(f"🔔 PRESENCE EVENT: {after.display_name} (ID: {user_id})")
                if before_status != after_status:
                    print(f"   Status: {before_status} → {after_status}")
                if before_acts != after_acts:
                    print(f"   Activities before: {before_acts if before_acts else '(none)'}")
                    print(f"   Activities after:  {after_acts if after_acts else '(none)'}")
                for a in after.activities:
                    print(f"   └─ type={type(a).__name__} name={getattr(a, 'name', None)} details={getattr(a, 'details', None)} state={getattr(a, 'state', None)} app_id={getattr(a, 'application_id', None)}")
                    if hasattr(a, "to_dict"):
                        try:
                            print(f"      RAW: {a.to_dict()}")
                        except:
                            pass
                if not after.activities:
                    print("   └─ (no activities)")

        if user_id not in state.user_data:
            return

        before_tft = get_tft_activity(before)
        after_tft = get_tft_activity(after)
        before_ig = is_in_game(before_tft)
        after_ig = is_in_game(after_tft)

        if (before_tft is not None) != (after_tft is not None) or before_ig != after_ig:
            print(f"{'=' * 55}")
            print(f"👀 TFT PRESENCE: {after.display_name}")
            print(f"   Before: tft={'yes' if before_tft else 'no'} in_game={before_ig}")
            print(f"   After:  tft={'yes' if after_tft else 'no'} in_game={after_ig}")
            if after_tft:
                log_activity("AFTER", after)
            print(f"{'=' * 55}")

        # NOT in game → IN game
        if not before_ig and after_ig:
            print(f"🎮 GAME START: {after.display_name}")
            state.game_states[user_id] = {"in_game": True, "guild_id": after.guild.id}
            await open_betting(self.bot, after, state.user_data[user_id])

        # IN game → NOT in game
        elif before_ig and not after_ig:
            if user_id in state.game_states and state.game_states[user_id].get("in_game"):
                state.game_states[user_id]["in_game"] = False
                print(f"🏁 GAME END: {after.display_name}")
                info = state.user_data[user_id]
                guild_id = state.game_states[user_id].get("guild_id", after.guild.id)
                asyncio.create_task(self._fetch_and_announce(user_id, info, guild_id))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        user_id = str(member.id)
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        get_balance(user_id)
        ub = state.user_balances[user_id]

        if ub.get("last_daily_date") != today:
            ub["vc_minutes_today"] = 0
            ub["daily_claimed"] = False
            ub["last_daily_date"] = today

        if before.channel is None and after.channel is not None:
            ub["vc_join_time"] = now.isoformat()
            save_balances()
        elif before.channel is not None and after.channel is None and ub.get("vc_join_time"):
            try:
                mins = int((now - datetime.fromisoformat(ub["vc_join_time"])).total_seconds() / 60)
                ub["vc_minutes_today"] = ub.get("vc_minutes_today", 0) + mins
                ub["vc_join_time"] = None
                save_balances()
                if not ub.get("daily_claimed") and ub.get("vc_minutes_today", 0) >= VC_MINUTES_FOR_DAILY:
                    ub["daily_claimed"] = True
                    nb = update_balance(user_id, DAILY_BONUS)
                    ch_id = state.announcement_channels.get(member.guild.id)
                    if ch_id:
                        ch = member.guild.get_channel(ch_id)
                        if ch:
                            await ch.send(f"🎁 **{member.display_name}** earned daily bonus! +**{DAILY_BONUS}** coins (Balance: {nb})")
            except:
                pass

    async def _fetch_and_announce(self, user_id: str, info: dict, guild_id: int):
        """Wait for match data, then queue for grouped announcement."""
        from bot.riot_api import RiotAPI
        import os
        riot_api = RiotAPI(os.getenv("RIOT_API_KEY", ""))

        puuid, region = info["puuid"], info["region"]
        old_match_id = info.get("last_match_id")

        print(f"⏳ Waiting {MATCH_FETCH_DELAY}s for {info['riot_name']}'s match data...")
        await asyncio.sleep(MATCH_FETCH_DELAY)

        new_match_id = None
        match_data = None

        for attempt in range(MATCH_FETCH_RETRIES):
            ids = await riot_api.get_match_ids(puuid, region, count=5)
            if ids:
                for mid in ids:
                    if mid != old_match_id:
                        new_match_id = mid
                        break
            if new_match_id:
                match_data = await riot_api.get_match(new_match_id, region)
                if match_data and match_data.get("info", {}).get("tft_set_number") is not None:
                    break
                new_match_id = None
                match_data = None
            print(f"   └─ Attempt {attempt + 1}/{MATCH_FETCH_RETRIES}: not ready...")
            await asyncio.sleep(MATCH_FETCH_RETRY_INTERVAL)

        if not match_data:
            print(f"❌ No match data for {info['riot_name']}")
            bk = (guild_id, user_id)
            if bk in state.active_bets:
                await cancel_bets(self.bot, bk, "Match data unavailable — all bets refunded")
            return

        info["last_match_id"] = new_match_id
        save_user_data()

        player_data = next(
            (p for p in match_data.get("info", {}).get("participants", []) if p.get("puuid") == puuid),
            None,
        )
        if not player_data:
            print(f"❌ Player not in participants")
            return

        placement = player_data.get("placement", 0)
        print(f"📊 {info['riot_name']} placed #{placement}")

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        member = guild.get_member(int(user_id))
        if not member:
            return

        await queue_result(self.bot, guild_id, user_id, member, info, match_data, player_data, placement)


async def setup(bot):
    await bot.add_cog(Events(bot))