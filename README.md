# TFT Discord Bot 🎮

A Discord bot that detects TFT games via Discord presence, fetches results from Riot's official API, and runs a placement-scaled betting system.

## How It Works

1. **Discord Presence** detects when a registered user starts/stops a TFT game
2. **Betting opens** for 3 minutes when a game starts
3. When the game ends, the bot fetches match results from **Riot's TFT Match API**
4. **Placement-scaled payouts** reward correct bets — better placements = bigger multiplier

No constant API polling needed. Discord does the heavy lifting for game detection.

## Placement Multipliers

| Placement | Multiplier | Category |
|-----------|-----------|----------|
| 🥇 1st   | 1.5x profit | Top 4 (WIN) |
| 🥈 2nd   | 1.3x profit | Top 4 (WIN) |
| 🥉 3rd   | 1.15x profit | Top 4 (WIN) |
| 4th       | 1.0x profit | Top 4 (WIN) |
| 5th       | 1.0x profit | Bot 4 (LOSS) |
| 6th       | 1.15x profit | Bot 4 (LOSS) |
| 7th       | 1.3x profit | Bot 4 (LOSS) |
| 💀 8th   | 1.5x profit | Bot 4 (LOSS) |

## Player Bonuses (for the TFT player)

| Placement | Pot % | Flat Bonus |
|-----------|-------|------------|
| 1st | 20% | +30 coins |
| 2nd | 15% | +20 coins |
| 3rd | 10% | +15 coins |
| 4th | 5%  | +10 coins |

## Commands

| Command | Description |
|---------|-------------|
| `/register <name> <tag> <region>` | Link your Riot ID |
| `/unregister` | Stop tracking |
| `/stats` | Your recent TFT stats |
| `/status` | Who's being tracked |
| `/bet <player> <top4\|bot4> <amount>` | Place a bet |
| `/balance` | Check your coins |
| `/leaderboard` | Top coin holders |
| `/setchannel <channel>` | Set announcement channel (Admin) |
| `/set <user> <amount>` | Set balance (Admin) |
| `/rules` | Show rules |
| `/debugpresence [user]` | Debug presence data |

## Setup

### 1. Discord Bot

1. [Discord Developer Portal](https://discord.com/developers/applications) → New Application
2. Bot section → Enable **Presence Intent**, **Server Members Intent**, **Message Content Intent**
3. OAuth2 → URL Generator → Scopes: `bot`, `applications.commands`
4. Permissions: Send Messages, Embed Links, Use Slash Commands
5. Copy bot token

### 2. Riot API Key

1. Go to [developer.riotgames.com](https://developer.riotgames.com)
2. Sign in and copy your Development API Key
3. **Note:** Dev keys expire every 24 hours. Register a Personal project for a persistent key.

### 3. Environment Variables

```bash
DISCORD_BOT_TOKEN=your_discord_bot_token
RIOT_API_KEY=RGAPI-your-key-here
```

### 4. Run

```bash
pip install -r requirements.txt
python discord_bot.py
```

## Architecture

```
Discord Presence (game detection)
         │
         ├── TFT activity appears with "in game" state
         │   └── Open betting (3 min window)
         │
         └── TFT activity disappears
             └── Wait 60s → Fetch match from Riot API
                 └── Announce placement + resolve bets
```

## Important Notes

- **Dev API keys expire every 24 hours.** Regenerate at developer.riotgames.com or register for a Personal key.
- **Discord presence requires** users to have "Display current activity" enabled in Discord settings.
- The bot uses the `/debugpresence` command to help troubleshoot what Discord is sending.
- House takes 5% only on betting pools ≥ 100 coins.