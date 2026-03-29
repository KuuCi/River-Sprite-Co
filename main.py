import discord
from discord.ext import commands
import os
import asyncio


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.presences = True
    intents.members = True
    intents.message_content = True
    intents.voice_states = True

    return commands.Bot(command_prefix="!", intents=intents)


bot = create_bot()


async def load_cogs():
    await bot.load_extension("bot.cogs.events")
    await bot.load_extension("bot.cogs.commands")


@bot.event
async def on_ready():
    pass  # Handled by Events cog


async def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ Set DISCORD_BOT_TOKEN in .env")
        return

    rk = os.getenv("RIOT_API_KEY")
    if not rk:
        print("⚠️ No RIOT_API_KEY — match results won't work")
    else:
        print(f"🔑 Riot key: {rk[:6]}...")

    async with bot:
        await load_cogs()
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())