import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional

from bot.config import (
    STARTING_BALANCE, VC_MINUTES_FOR_DAILY, PLACEMENT_EMOJIS,
    PLATFORM_MAP, REGIONAL_MAP, BLESSED_BONUS, CURSED_PENALTY, THREE_STAR_BOUNTY,
)
from bot import state
from bot.storage import (
    save_user_data, save_settings, save_balances,
    get_balance, update_balance, set_balance,
)
from bot.riot_api import RiotAPI
from bot.presence import get_tft_activity, is_in_game
from bot.betting import update_betting_embed
from bot.helpers import queue_name

riot_api = RiotAPI(os.getenv("RIOT_API_KEY", ""))


class Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="register", description="Register your Riot ID to track TFT games")
    @app_commands.describe(riot_name="Your Riot username", riot_tag="Your Riot tag (e.g. NA1)", region="Your region")
    @app_commands.choices(region=[
        app_commands.Choice(name="North America", value="na"),
        app_commands.Choice(name="Europe West", value="euw"),
        app_commands.Choice(name="Europe Nordic & East", value="eune"),
        app_commands.Choice(name="Korea", value="kr"),
        app_commands.Choice(name="Brazil", value="br"),
        app_commands.Choice(name="Oceania", value="oce"),
        app_commands.Choice(name="Japan", value="jp"),
    ])
    async def register(self, interaction: discord.Interaction, riot_name: str, riot_tag: str, region: str = "na"):
        await interaction.response.defer(ephemeral=True)
        regional = REGIONAL_MAP.get(region, "americas")
        platform = PLATFORM_MAP.get(region, "na1")
        account = await riot_api.get_account(riot_name, riot_tag, regional)
        if not account:
            await interaction.followup.send(f"❌ Could not find **{riot_name}#{riot_tag}**.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        puuid = account["puuid"]
        ids = await riot_api.get_match_ids(puuid, regional, count=1)
        state.user_data[uid] = {
            "riot_name": account.get("gameName", riot_name),
            "riot_tag": account.get("tagLine", riot_tag),
            "puuid": puuid, "platform": platform, "region": regional,
            "last_match_id": ids[0] if ids else None,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        save_user_data()
        print(f"📝 Registered: {interaction.user.display_name} → {riot_name}#{riot_tag}")
        await interaction.followup.send(
            f"✅ Registered **{account.get('gameName')}#{account.get('tagLine')}** ({region.upper()})!\n"
            f"I'll detect your TFT games via Discord presence and fetch results from Riot's API.",
            ephemeral=True,
        )

    @app_commands.command(name="unregister", description="Stop tracking your TFT games")
    async def unregister(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid in state.user_data:
            del state.user_data[uid]
            save_user_data()
            state.game_states.pop(uid, None)
            await interaction.response.send_message("✅ Unregistered.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Not registered.", ephemeral=True)

    @app_commands.command(name="setchannel", description="Set announcement channel (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        state.announcement_channels[interaction.guild.id] = channel.id
        save_settings()
        await interaction.response.send_message(f"✅ TFT announcements → {channel.mention}")

    @app_commands.command(name="status", description="See who is tracked")
    async def status(self, interaction: discord.Interaction):
        if not state.user_data:
            await interaction.response.send_message("No one registered.", ephemeral=True)
            return
        lines = [
            f"{'🎮' if state.game_states.get(uid, {}).get('in_game') else '💤'} "
            f"**{info['riot_name']}#{info['riot_tag']}** — "
            f"{'in game' if state.game_states.get(uid, {}).get('in_game') else 'idle'}"
            for uid, info in state.user_data.items()
        ]
        await interaction.response.send_message(f"**Tracking {len(state.user_data)} player(s):**\n" + "\n".join(lines), ephemeral=True)

    @app_commands.command(name="stats", description="Your recent TFT stats")
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        if uid not in state.user_data:
            await interaction.followup.send("❌ `/register` first!")
            return
        info = state.user_data[uid]
        ids = await riot_api.get_match_ids(info["puuid"], info["region"], count=10)
        if not ids:
            await interaction.followup.send("❌ No match history.")
            return

        placements = []
        for mid in ids[:10]:
            m = await riot_api.get_match(mid, info["region"])
            if m:
                p = next((p for p in m.get("info", {}).get("participants", []) if p.get("puuid") == info["puuid"]), None)
                if p:
                    placements.append(p.get("placement", 0))
            await asyncio.sleep(0.4)
        if not placements:
            await interaction.followup.send("❌ No TFT matches.")
            return

        t4 = sum(1 for p in placements if p <= 4)
        avg = sum(placements) / len(placements)
        embed = discord.Embed(title="📊 TFT Stats", description=f"**{info['riot_name']}#{info['riot_tag']}**", color=discord.Color.blurple())
        embed.add_field(name=f"Last {len(placements)}", value=f"Top 4: **{t4}** | Bot 4: **{len(placements) - t4}**", inline=True)
        embed.add_field(name="Avg", value=f"**{avg:.1f}**", inline=True)
        embed.add_field(name="1sts/8ths", value=f"🥇 {sum(1 for p in placements if p == 1)} / 💀 {sum(1 for p in placements if p == 8)}", inline=True)
        embed.add_field(name="Recent", value=" ".join(PLACEMENT_EMOJIS.get(p, "?") for p in placements), inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="bet", description="Bet on a player's TFT game")
    @app_commands.describe(player="Player to bet on", outcome="Top 4 or Bottom 4", amount="Coins to bet")
    @app_commands.choices(outcome=[
        app_commands.Choice(name="Top 4 (1st-4th)", value="top4"),
        app_commands.Choice(name="Bottom 4 (5th-8th)", value="bot4"),
    ])
    async def bet(self, interaction: discord.Interaction, player: discord.Member, outcome: str, amount: int):
        uid = str(interaction.user.id)
        bk = (interaction.guild.id, str(player.id))
        if bk not in state.active_bets:
            await interaction.response.send_message(f"❌ No betting open for **{player.display_name}**.", ephemeral=True)
            return
        bd = state.active_bets[bk]
        group = state.bet_groups.get(interaction.guild.id, {})
        closes_at = group.get("closes_at", 0)
        if bd.get("closed") or group.get("closed") or datetime.now(timezone.utc).timestamp() > closes_at:
            await interaction.response.send_message("❌ Betting is closed.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.response.send_message("❌ Must be positive!", ephemeral=True)
            return
        bal = get_balance(uid)
        if amount > bal:
            await interaction.response.send_message(f"❌ You only have **{bal}** coins.", ephemeral=True)
            return
        for s in ["top4", "bot4"]:
            if uid in bd["bets"][s]:
                await interaction.response.send_message(f"❌ Already bet **{bd['bets'][s][uid]}** on **{s}**.", ephemeral=True)
                return

        update_balance(uid, -amount)
        bd["bets"][outcome][uid] = amount
        await update_betting_embed(self.bot, bk)
        t4 = sum(bd["bets"]["top4"].values())
        b4 = sum(bd["bets"]["bot4"].values())
        total = t4 + b4
        mp = t4 if outcome == "top4" else b4
        hm = 0.95 if total >= 100 else 1.0
        pot = int(amount * (total * hm) / mp) if mp > 0 else amount
        await interaction.response.send_message(
            f"✅ **{amount}** coins on **{player.display_name}** → **{outcome.upper()}**\n"
            f"Potential: ~**{pot}** coins (before placement bonus)\n"
            f"Balance: **{get_balance(uid)}** coins",
            ephemeral=True,
        )
        print(f"🎰 {interaction.user.display_name} bet {amount} on {player.display_name} → {outcome}")

    @app_commands.command(name="balance", description="Check your coins")
    async def balance(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        bal = get_balance(uid)
        ub = state.user_balances.get(uid, {})
        embed = discord.Embed(title=f"💰 {interaction.user.display_name}", color=discord.Color.gold())
        embed.add_field(name="Coins", value=f"**{bal}** 🪙", inline=True)
        embed.add_field(name="VC Today", value=f"{ub.get('vc_minutes_today', 0)} min", inline=True)
        if ub.get("daily_claimed"):
            embed.add_field(name="Daily", value="✅", inline=True)
        else:
            embed.add_field(name="Daily", value=f"⏳ {max(0, VC_MINUTES_FOR_DAILY - ub.get('vc_minutes_today', 0))} min left", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Coin leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        if not state.user_balances:
            await interaction.response.send_message("No coins yet!", ephemeral=True)
            return
        su = sorted(state.user_balances.items(), key=lambda x: x[1].get("balance", 0), reverse=True)[:10]
        embed = discord.Embed(title="🏆 Leaderboard", color=discord.Color.gold())
        lines = []
        for i, (uid, d) in enumerate(su, 1):
            try:
                m = interaction.guild.get_member(int(uid))
                name = m.display_name if m else f"User {uid[:8]}"
            except:
                name = f"User {uid[:8]}"
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
            lines.append(f"{medal} **{name}**: {d.get('balance', 0)} coins")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="set", description="Set a user's balance (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_coins(self, interaction: discord.Interaction, user: discord.Member, amount: int):
        nb = set_balance(str(user.id), amount)
        await interaction.response.send_message(f"✅ **{user.display_name}** → **{nb}** coins")

    @app_commands.command(name="resetcoins", description="Reset ALL coins to starting balance (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_coins(self, interaction: discord.Interaction):
        count = len(state.user_balances)
        for uid in state.user_balances:
            state.user_balances[uid]["balance"] = STARTING_BALANCE
        save_balances()
        await interaction.response.send_message(f"🔄 Reset **{count}** user(s) to **{STARTING_BALANCE}** coins.")
        print(f"🔄 Admin {interaction.user.display_name} reset all balances")

    @app_commands.command(name="rules", description="Show rules and commands")
    async def rules(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📜 TFT Betting Bot", color=discord.Color.blue())
        embed.add_field(name="🎮 Tracking", value="`/register` `/unregister` `/stats` `/status`", inline=False)
        embed.add_field(name="🎰 Betting", value="`/bet <player> <top4|bot4> <amount>`\n`/balance` `/leaderboard`", inline=False)
        embed.add_field(name="📊 Placement Multipliers", value="🥇1st/💀8th = **1.5x** • 🥈2nd/7th = **1.3x** • 🥉3rd/6th = **1.15x** • 4th/5th = **1.0x**", inline=False)
        embed.add_field(name="💰 Earning", value="**Top 4:** 5-20% pot + flat bonus\n**VC 30min:** 50 coins daily\n**Start:** 100 coins", inline=False)
        embed.add_field(name="🏠 House", value="5% cut only on pools ≥ 100 coins", inline=False)
        embed.add_field(name="🎲 Challenges (per game)", value=(
            "Each game randomizes:\n"
            f"😇 **Blessed units** — +{BLESSED_BONUS} coins each on your final board\n"
            f"😈 **Cursed units** — -{CURSED_PENALTY} coins each on your final board\n"
            f"⭐⭐⭐ **3-Star Bounty** — +{THREE_STAR_BOUNTY} coins if you 3-star the target\n"
            "Challenges shown when betting opens!"
        ), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="debugpresence", description="Debug: show current Discord activities")
    async def debugpresence(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target_id = user.id if user else interaction.user.id
        guild = self.bot.get_guild(interaction.guild_id) or interaction.guild
        target = next((m for m in guild.members if m.id == target_id), None)
        if not target:
            target = interaction.guild.get_member(target_id)
        if not target:
            await interaction.response.send_message("❌ Could not find member.", ephemeral=True)
            return

        lines = [
            f"**Member:** {target.display_name} (ID: {target.id})",
            f"**Status:** {target.status}",
            f"**Activity count:** {len(target.activities)}", "",
        ]
        for a in target.activities:
            parts = [f"**{type(a).__name__}**: `{getattr(a, 'name', '?')}`"]
            if getattr(a, "details", None):
                parts.append(f"details=`{a.details}`")
            if getattr(a, "state", None):
                parts.append(f"state=`{a.state}`")
            lines.append(" | ".join(parts))
            if hasattr(a, "to_dict"):
                try:
                    raw = json.dumps(a.to_dict(), indent=2)[:500]
                    lines.append(f"```json\n{raw}\n```")
                except:
                    pass
        if not target.activities:
            lines.append("⚠️ No activities detected")

        tft = get_tft_activity(target)
        ig = is_in_game(tft)
        lines.append(f"\n**TFT:** {'✅' if tft else '❌'} | **In game:** {'✅' if ig else '❌'}")

        vis = sum(1 for m in guild.members if m.activities)
        lines.append(f"\n**Guild scan:** {vis}/{guild.member_count} members have visible activities")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="debugscan", description="Debug: show which members have visible activities")
    async def debugscan(self, interaction: discord.Interaction):
        lines = []
        visible = []
        registered_visible = []

        for m in interaction.guild.members:
            if m.bot:
                continue
            if m.activities:
                acts = ", ".join(f"{getattr(a, 'name', '?')}" for a in m.activities)
                details = ", ".join(f"{getattr(a, 'details', '')}" for a in m.activities if getattr(a, "details", None))
                entry = f"✅ **{m.display_name}**: {acts}"
                if details:
                    entry += f" — `{details}`"
                visible.append(entry)
                if str(m.id) in state.user_data:
                    registered_visible.append(m.display_name)
            elif str(m.id) in state.user_data:
                lines.append(f"❌ **{m.display_name}** (registered but NO activities visible)")

        total = sum(1 for m in interaction.guild.members if not m.bot)
        header = f"**Bot can see activities for {len(visible)}/{total} non-bot members**\n"
        if lines:
            header += "⚠️ **Registered users with NO visible activities:**\n" + "\n".join(lines) + "\n"
        if registered_visible:
            header += f"\n✅ **Registered WITH activities:** {', '.join(registered_visible)}\n"
        header += "\n**All visible:**\n"
        output = header + "\n".join(visible[:20])
        if len(visible) > 20:
            output += f"\n... and {len(visible) - 20} more"
        if len(output) > 1900:
            output = output[:1900] + "..."
        await interaction.response.send_message(output, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Commands(bot))