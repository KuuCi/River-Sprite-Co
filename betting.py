import discord
import asyncio
from datetime import datetime, timezone

from bot.config import (
    BETTING_WINDOW, PLACEMENT_MULTIPLIERS, PLAYER_BONUSES, PLACEMENT_EMOJIS,
    RESULTS_WAIT_TIME, BLESSED_BONUS, CURSED_PENALTY, THREE_STAR_BOUNTY,
)
from bot import state
from bot.storage import get_balance, update_balance
from bot.challenges import generate_challenges, format_challenges, evaluate_challenges
from bot.helpers import format_traits, format_units, format_augments, format_duration, queue_name


async def open_betting(bot, member: discord.Member, user_info: dict):
    ch_id = state.announcement_channels.get(member.guild.id)
    if not ch_id:
        return
    channel = member.guild.get_channel(ch_id)
    if not channel:
        return

    guild_id = member.guild.id
    bk = (guild_id, str(member.id))
    if bk in state.active_bets:
        return

    now = datetime.now(timezone.utc).timestamp()
    group = state.bet_groups.get(guild_id)

    if group and not group.get("closed") and (group["closes_at"] - now) > 30:
        challenges = group["challenges"]
    else:
        challenges = generate_challenges()
        closes_at = now + BETTING_WINDOW

        if group and group.get("close_task"):
            group["close_task"].cancel()

        state.bet_groups[guild_id] = {
            "message": None,
            "player_bks": [],
            "closes_at": closes_at,
            "challenges": challenges,
            "close_task": None,
            "closed": False,
        }
        group = state.bet_groups[guild_id]

    state.active_bets[bk] = {
        "player_name": member.display_name,
        "player_riot_id": f"{user_info['riot_name']}#{user_info['riot_tag']}",
        "player_user_id": str(member.id),
        "bets": {"top4": {}, "bot4": {}},
        "guild_id": guild_id,
        "closed": False,
        "challenges": challenges,
    }
    group["player_bks"].append(bk)

    await rebuild_group_embed(bot, guild_id, channel)

    if group.get("close_task"):
        group["close_task"].cancel()
    remaining = max(10, int(group["closes_at"] - now))
    group["close_task"] = asyncio.create_task(close_group_after_delay(bot, guild_id, remaining))

    print(f"🎰 Betting opened: {member.display_name} (group has {len(group['player_bks'])} player(s))")


async def rebuild_group_embed(bot, guild_id: int, channel=None):
    group = state.bet_groups.get(guild_id)
    if not group:
        return

    if not channel:
        ch_id = state.announcement_channels.get(guild_id)
        if not ch_id:
            return
        guild = bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(ch_id)
        if not channel:
            return

    player_names = []
    for bk in group["player_bks"]:
        bd = state.active_bets.get(bk)
        if bd:
            player_names.append(bd["player_name"])

    closes_at = group["closes_at"]
    is_multi = len(group["player_bks"]) > 1

    if is_multi:
        title = f"🎰 Betting Open: {len(group['player_bks'])} Players!"
    else:
        title = f"🎰 Betting Open: {player_names[0] if player_names else '?'}"

    desc = "**Players in this game:**\n" if is_multi else ""

    for bk in group["player_bks"]:
        bd = state.active_bets.get(bk)
        if not bd:
            continue
        t4 = sum(bd["bets"]["top4"].values())
        b4 = sum(bd["bets"]["bot4"].values())
        total = t4 + b4
        t4c = len(bd["bets"]["top4"])
        b4c = len(bd["bets"]["bot4"])
        hm = 0.95 if total >= 100 else 1.0
        t4o = f"{((total * hm) / t4):.1f}x" if t4 > 0 and total > 0 else "--"
        b4o = f"{((total * hm) / b4):.1f}x" if b4 > 0 and total > 0 else "--"
        desc += f"\n**{bd['player_name']}** ({bd['player_riot_id']})\n"
        desc += f"🏆 Top 4: {t4} coins ({t4c}) | 💀 Bot 4: {b4} coins ({b4c}) | Odds: {t4o}/{b4o}\n"

    desc += f"\nUse `/bet <player> <top4|bot4> <amount>`\nBetting closes <t:{int(closes_at)}:R>"

    embed = discord.Embed(title=title, description=desc, color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🎲 Challenges", value=format_challenges(group["challenges"]), inline=False)
    embed.set_footer(text="1st/8th=1.5x • 2nd/7th=1.3x • 3rd/6th=1.15x • 4th/5th=1.0x profit")

    if group.get("message"):
        try:
            await group["message"].edit(embed=embed)
        except:
            msg = await channel.send(embed=embed)
            group["message"] = msg
    else:
        msg = await channel.send(embed=embed)
        group["message"] = msg


async def close_group_after_delay(bot, guild_id: int, delay: int):
    await asyncio.sleep(delay)
    await close_group_betting(bot, guild_id)


async def close_group_betting(bot, guild_id: int):
    group = state.bet_groups.get(guild_id)
    if not group or group.get("closed"):
        return

    group["closed"] = True
    for bk in group["player_bks"]:
        if bk in state.active_bets:
            state.active_bets[bk]["closed"] = True

    if group.get("message"):
        try:
            player_names = []
            bounty_lines = []
            for bk in group["player_bks"]:
                bd = state.active_bets.get(bk)
                if not bd:
                    continue
                player_names.append(bd["player_name"])
                t4 = sum(bd["bets"]["top4"].values())
                b4 = sum(bd["bets"]["bot4"].values())
                total = t4 + b4
                t4c = len(bd["bets"]["top4"])
                b4c = len(bd["bets"]["bot4"])
                bounty_lines.append(
                    f"**{bd['player_name']}** — 💰 **{total}** coins at stake\n"
                    f"🏆 Top 4: {t4} ({t4c} bets) | 💀 Bot 4: {b4} ({b4c} bets)"
                )

            desc = "**Bounties:**\n\n" + "\n\n".join(bounty_lines) if bounty_lines else ""
            desc += "\n\nResults when the game ends..."

            e = group["message"].embeds[0]
            e.title = f"🔒 Betting Closed: {', '.join(player_names)}"
            e.description = desc
            e.color = discord.Color.dark_gray()
            await group["message"].edit(embed=e)
        except:
            pass

    print(f"🔒 Group betting closed for guild {guild_id}")


async def update_betting_embed(bot, bk):
    if bk not in state.active_bets:
        return
    bd = state.active_bets[bk]
    await rebuild_group_embed(bot, bd["guild_id"])


async def cancel_bets(bot, bk, reason):
    if bk not in state.active_bets:
        return
    bd = state.active_bets.pop(bk)
    for side in ["top4", "bot4"]:
        for uid, amt in bd["bets"][side].items():
            update_balance(uid, amt)
    g = bot.get_guild(bd["guild_id"])
    ch_id = state.announcement_channels.get(bd["guild_id"])
    if g and ch_id:
        ch = g.get_channel(ch_id)
        if ch:
            await ch.send(f"⚠️ Bets cancelled for **{bd['player_name']}**: {reason}")

    group = state.bet_groups.get(bd["guild_id"])
    if group and bk in group["player_bks"]:
        group["player_bks"].remove(bk)
        if not group["player_bks"]:
            state.bet_groups.pop(bd["guild_id"], None)


def calculate_payouts(bd: dict, placement: int) -> dict:
    is_top4 = placement <= 4
    ws = "top4" if is_top4 else "bot4"
    ls = "bot4" if is_top4 else "top4"
    wb = bd["bets"][ws]
    lb = bd["bets"][ls]
    wt = sum(wb.values())
    lt = sum(lb.values())
    total = wt + lt
    pm = PLACEMENT_MULTIPLIERS.get(placement, 1.0)

    results = {uid: {"payout": 0, "profit": -amt, "bet": amt, "side": ls, "multiplier": None} for uid, amt in lb.items()}

    if total == 0 or wt == 0:
        return results
    hc = 0.05 if total >= 100 else 0.0

    if lt == 0:
        for uid, amt in wb.items():
            bonus = max(1, int(amt * 0.20 * pm))
            results[uid] = {"payout": amt + bonus, "profit": bonus, "bet": amt, "side": ws, "multiplier": pm}
        return results

    if len(wb) + len(lb) == 1:
        for uid, amt in wb.items():
            bonus = max(1, int(amt * 0.25 * pm))
            results[uid] = {"payout": amt + bonus, "profit": bonus, "bet": amt, "side": ws, "multiplier": pm}
        return results

    pool = total - int(total * hc)
    for uid, amt in wb.items():
        base = int(pool * (amt / wt))
        profit = int((base - amt) * pm)
        results[uid] = {"payout": max(0, amt + profit), "profit": profit, "bet": amt, "side": ws, "multiplier": pm}
    return results


async def queue_result(bot, guild_id: int, user_id: str, member, info, match_data, player_data, placement):
    """Queue a player's result for combined announcement."""
    result = {
        "user_id": user_id, "member": member, "info": info,
        "match_data": match_data, "player_data": player_data, "placement": placement,
    }

    if guild_id not in state.pending_results:
        state.pending_results[guild_id] = {"results": [], "task": None}

    state.pending_results[guild_id]["results"].append(result)
    print(f"📋 Queued result: {info['riot_name']} #{placement} ({len(state.pending_results[guild_id]['results'])} pending)")

    if state.pending_results[guild_id]["task"]:
        state.pending_results[guild_id]["task"].cancel()
    state.pending_results[guild_id]["task"] = asyncio.create_task(flush_results(bot, guild_id))


async def flush_results(bot, guild_id: int):
    """Wait for more results, then announce all at once."""
    await asyncio.sleep(RESULTS_WAIT_TIME)

    if guild_id not in state.pending_results:
        return
    results = state.pending_results.pop(guild_id)["results"]
    if not results:
        return

    guild = bot.get_guild(guild_id)
    ch_id = state.announcement_channels.get(guild_id)
    if not guild or not ch_id:
        return
    channel = guild.get_channel(ch_id)
    if not channel:
        return

    results.sort(key=lambda r: r["placement"])

    group = state.bet_groups.get(guild_id, {})
    challenges = group.get("challenges", {})

    is_multi = len(results) > 1
    if is_multi:
        title = f"🎮 TFT Results: {len(results)} Players!"
    else:
        r = results[0]
        emoji = PLACEMENT_EMOJIS.get(r["placement"], "❓")
        title = f"🎮 TFT Result: {r['info']['riot_name']} {emoji} #{r['placement']}"

    best = results[0]["placement"]
    if best == 1:
        color = discord.Color.gold()
    elif best <= 4:
        color = discord.Color.green()
    else:
        color = discord.Color.red()

    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))

    for r in results:
        pd = r["player_data"]
        placement = r["placement"]
        emoji = PLACEMENT_EMOJIS.get(placement, "❓")
        mi = r["match_data"].get("info", {})

        header = f"{emoji} #{placement} — {r['info']['riot_name']}"
        value_parts = [
            f"**{queue_name(mi.get('queue_id', 0))}** • {format_duration(mi.get('game_length', 0))} • Lvl {pd.get('level', '?')}",
            f"Board: {format_units(pd.get('units', []))}",
            f"Traits: {format_traits(pd.get('traits', []))}",
        ]
        augments = pd.get("augments", [])
        if augments:
            value_parts.append(f"Augments: {format_augments(augments)}")
        if challenges:
            cr = evaluate_challenges(challenges, pd)
            if cr["details"]:
                value_parts.append("**Challenges:** " + " • ".join(cr["details"]))

        embed.add_field(name=header, value="\n".join(value_parts), inline=False)

    await channel.send(embed=embed)
    print(f"✅ Combined announcement sent ({len(results)} players)")

    for r in results:
        bk = (guild_id, r["user_id"])
        await resolve_bets(bot, bk, r["placement"], r["player_data"])

    state.bet_groups.pop(guild_id, None)


async def resolve_bets(bot, bk, placement, player_data=None):
    if bk not in state.active_bets:
        return
    bd = state.active_bets.pop(bk)
    is_top4 = placement <= 4
    total = sum(bd["bets"]["top4"].values()) + sum(bd["bets"]["bot4"].values())

    puid = bd["player_user_id"]
    pp, fb = PLAYER_BONUSES.get(placement, (0, 0))
    pbonus = int(total * pp) + fb if (pp or fb) else 0
    if pbonus > 0:
        update_balance(puid, pbonus)

    challenges = bd.get("challenges", {})
    challenge_result = {"total": 0, "details": []}
    if challenges and player_data:
        challenge_result = evaluate_challenges(challenges, player_data)
        if challenge_result["total"] != 0:
            update_balance(puid, challenge_result["total"])
            print(f"🎲 Challenge: {bd['player_name']}: {challenge_result['total']:+d} coins")

    g = bot.get_guild(bd["guild_id"])
    ch_id = state.announcement_channels.get(bd["guild_id"])
    if not g or not ch_id:
        return
    ch = g.get_channel(ch_id)
    if not ch:
        return

    if total == 0:
        parts = []
        if pbonus > 0:
            parts.append(f"🏆 Placement: +**{pbonus}**")
        if challenge_result["total"] != 0:
            parts.append(f"🎲 Challenges: **{challenge_result['total']:+d}**")
        if parts:
            await ch.send(f"**{bd['player_name']}** placed **#{placement}**!\n" + " • ".join(parts))
        return

    payouts = calculate_payouts(bd, placement)
    for uid, r in payouts.items():
        if r["payout"] > 0:
            update_balance(uid, r["payout"])

    emoji = PLACEMENT_EMOJIS.get(placement, "❓")
    embed = discord.Embed(
        title=f"🎰 {bd['player_name']} {emoji} #{placement}",
        description=f"**{bd['player_riot_id']}** — {'TOP 4' if is_top4 else 'BOTTOM 4'}",
        color=discord.Color.green() if is_top4 else discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )

    mult = PLACEMENT_MULTIPLIERS.get(placement, 1.0)
    summary_parts = [f"📊 {mult}x profit multiplier"]
    if pbonus > 0:
        summary_parts.append(f"🏆 +{pbonus} player bonus")
    if challenge_result["total"] != 0:
        summary_parts.append(f"🎲 {challenge_result['total']:+d} challenges")
    embed.add_field(name="Bonuses", value=" • ".join(summary_parts), inline=False)

    if challenge_result["details"]:
        embed.add_field(name="🎲 Challenge Details", value="\n".join(challenge_result["details"]), inline=False)

    sr = sorted(payouts.items(), key=lambda x: x[1]["profit"], reverse=True)
    wt, lt, mentions = [], [], []
    for uid, r in sr:
        try:
            m = g.get_member(int(uid))
            name = m.display_name if m else f"User {uid[:8]}"
            if m:
                mentions.append(m.mention)
        except:
            name = f"User {uid[:8]}"
        mt = f" ({r['multiplier']}x)" if r.get("multiplier") else ""
        if r["profit"] > 0:
            wt.append(f"🤑 **{name}**: +{r['profit']}{mt} (bet {r['bet']} on {r['side']})")
        elif r["profit"] == 0:
            wt.append(f"😐 **{name}**: ±0 (bet {r['bet']} on {r['side']})")
        else:
            lt.append(f"😭 **{name}**: {r['profit']} (bet {r['bet']} on {r['side']})")
    if wt:
        embed.add_field(name="Winners", value="\n".join(wt[:10]), inline=False)
    if lt:
        embed.add_field(name="Losers", value="\n".join(lt[:10]), inline=False)

    embed.set_footer(text=f"Pool: {total}" + (f" • House: {int(total * 0.05)}" if total >= 100 else ""))
    await ch.send(content=" ".join(mentions) if mentions else "", embed=embed)
    print(f"🎰 Resolved: {bd['player_name']} #{placement}")