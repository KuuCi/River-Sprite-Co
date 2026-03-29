# TFT Discord Bot 🎮

A Discord bot that detects TFT games via Discord presence, fetches results from Riot's official API, and runs a placement-scaled betting system with per-game challenges.

## How It Works

1. **Discord Presence** detects when registered users start/stop TFT games
2. **Betting opens** with a combined embed showing all active players and randomized challenges
3. Friends can bet on individual players (top 4 / bot 4) with separate pools per player
4. When games end, the bot fetches match results from **Riot's TFT Match API**
5. **Placement-scaled payouts** and **challenge bonuses/penalties** are calculated and announced

No constant API polling. Discord handles game detection; Riot API is only hit when a game ends.

## Per-Game Challenges 🎲

Every time a game starts, the bot randomizes challenges that are shown in the betting embed:

**😇 Blessed Units** — 2 random champions are blessed each game. If they're on your final board, you earn +20 coins each. Risk/reward: they might not fit your comp, but the bonus is tempting.

**😈 Cursed Units** — 2 random champions are cursed. If they're on your final board, you lose -15 coins each. Risk/reward: a cursed unit might be meta, forcing you to choose between LP and coins.

**⭐⭐⭐ 3-Star Bounty** — One random champion is the bounty target. 3-star it and earn +75 coins. High risk — forcing a 3-star can tank your placement.

Challenges are checked automatically against your final board when the Riot API returns match data.

### Example Betting Embed

```
🎰 Betting Open: 2 Players!

Bob (Bob#NA1)
🏆 Top 4: 50 coins (2) | 💀 Bot 4: 30 coins (1) | Odds: 1.6x/2.7x

Alice (Alice#NA1)
🏆 Top 4: 0 coins (0) | 💀 Bot 4: 20 coins (1) | Odds: --/1.0x

🎲 Challenges
😇 Blessed: Ahri, Jinx (+20 coins each)
😈 Cursed: Zed, Warwick (-15 coins each)
⭐⭐⭐ 3-Star Bounty: Lux (+75 coins)
```

## Multi-Player Support

When multiple registered users start TFT around the same time, the bot combines them into a single betting embed with individual pools per player. When games end, results are grouped into one combined announcement (the bot waits 30s for squad members to finish before posting).

## Placement Multipliers

Profit from winning bets is scaled by placement — extreme placements pay more:

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

## Player Bonuses

The TFT player earns coins for placing well (from the betting pot + flat bonus):

| Placement | Pot % | Flat Bonus |
|-----------|-------|------------|
| 1st | 20% | +30 coins |
| 2nd | 15% | +20 coins |
| 3rd | 10% | +15 coins |
| 4th | 5%  | +10 coins |

## Earning Coins

- **Starting balance:** 100 coins
- **Top 4 placement:** % of pot + flat bonus (see above)
- **Challenges:** Blessed/cursed units and 3-star bounties
- **Voice chat daily:** Spend 30 minutes in VC → auto-claim 50 coins
- **Winning bets:** Pari-mutuel payouts with placement multipliers
- **Going broke:** You're out until the next daily bonus

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
| `/rules` | Show all rules |
| `/setchannel <channel>` | Set announcement channel (Admin) |
| `/set <user> <amount>` | Set a user's balance (Admin) |
| `/resetcoins` | Reset all balances to 100 (Admin) |
| `/debugpresence [user]` | Debug: show Discord activity data |
| `/debugscan` | Debug: show which members have visible activities |

## Setup

### 1. Discord Bot

1. [Discord Developer Portal](https://discord.com/developers/applications) → New Application
2. Bot section → Enable **Presence Intent**, **Server Members Intent**, **Message Content Intent**
3. OAuth2 → URL Generator → Scopes: `bot`, `applications.commands`
4. Permissions: Send Messages, Embed Links, Use Slash Commands
5. Copy bot token

### 2. Riot API Key

1. Go to [developer.riotgames.com](https://developer.riotgames.com)
2. Sign in and request for a personal key

### 3. Environment Variables

```bash
DISCORD_BOT_TOKEN=your_discord_bot_token
RIOT_API_KEY=RGAPI-your-key-here
```

### 4. Run

```bash
pip install -r requirements.txt
python -m bot.main
```

## Project Structure

```
bot/
├── main.py            # Entry point — creates bot, loads cogs
├── config.py          # All constants, tuning knobs, region maps
├── state.py           # Shared mutable state (user_data, active_bets, etc)
├── storage.py         # JSON persistence, balance management
├── riot_api.py        # Riot API client
├── presence.py        # TFT activity detection from Discord presence
├── helpers.py         # Display formatters (traits, units, augments)
├── challenges.py      # Blessed/cursed system, Data Dragon champion loading
├── betting.py         # Grouped betting, payouts, embeds, results queue
└── cogs/
    ├── events.py      # on_ready, presence updates, VC tracking, match fetching
    └── commands.py    # All slash commands
```

## Architecture

```
Discord Presence (game detection)
         │
         ├── TFT activity appears with "In Game" state
         │   ├── Generate random challenges (blessed/cursed/3-star bounty)
         │   ├── Open grouped betting embed (3 min window)
         │   └── Additional players join the same embed
         │
         └── TFT activity changes away from "In Game"
             └── Wait 60s → Fetch match from Riot API
                 ├── Queue result (wait 30s for squad members)
                 ├── Combined announcement embed
                 ├── Evaluate challenges vs final board
                 └── Resolve bets with placement multipliers
```

## House Rules

- 5% house cut only on betting pools ≥ 100 coins
- No cut on small pools or unanimous bets (everyone on same side)
- Solo bets get a 25% bonus for being brave

## Configuration

All tuning knobs are in `bot/config.py`:

```python
BETTING_WINDOW = 180        # Seconds before betting closes
MATCH_FETCH_DELAY = 60      # Wait before hitting Riot API
RESULTS_WAIT_TIME = 30      # Wait for squad members before announcing
BLESSED_BONUS = 20          # Coins per blessed unit on board
CURSED_PENALTY = 15         # Coins lost per cursed unit on board
THREE_STAR_BOUNTY = 75      # Coins for 3-starring the bounty target
STARTING_BALANCE = 100      # Coins everyone starts with
DAILY_BONUS = 50            # Coins from 30 min VC daily
```

## Important Notes

- **Discord presence requires** users to have "Display current activity" enabled in Discord settings (Activity Privacy → Share my activity).
- **TFT shows as "League of Legends"** in Discord with TFT details in the `details` field — the bot handles this.
- The champion pool for challenges is loaded from Riot's Data Dragon CDN on startup (no API key needed).
- Use `/debugpresence` and `/debugscan` to troubleshoot activity detection issues.