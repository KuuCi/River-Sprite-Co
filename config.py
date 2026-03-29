import os

# Betting
STARTING_BALANCE = 100
DAILY_BONUS = 50
VC_MINUTES_FOR_DAILY = 30
BETTING_WINDOW = 180  # seconds

# Match fetching
MATCH_FETCH_DELAY = 60
MATCH_FETCH_RETRIES = 8
MATCH_FETCH_RETRY_INTERVAL = 20

# Grouped results
RESULTS_WAIT_TIME = 30  # seconds to wait for squad members

# Placement
PLACEMENT_MULTIPLIERS = {1: 1.5, 2: 1.3, 3: 1.15, 4: 1.0, 5: 1.0, 6: 1.15, 7: 1.3, 8: 1.5}
PLAYER_BONUSES = {
    1: (0.20, 30), 2: (0.15, 20), 3: (0.10, 15), 4: (0.05, 10),
    5: (0, 0), 6: (0, 0), 7: (0, 0), 8: (0, 0),
}
PLACEMENT_EMOJIS = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "💀"}
TRAIT_STYLE_EMOJIS = {0: "⬛", 1: "🟤", 2: "⚪", 3: "🟡", 4: "💎"}

# Presence detection
TFT_ACTIVITY_NAMES = ["teamfighttactics", "teamfight tactics"]
IN_GAME_KEYWORDS = ["in game"]
NOT_IN_GAME_KEYWORDS = ["in queue", "queue", "matchmaking", "searching", "lobby", "menu", "idle", "in lobby"]

# Challenges
BLESSED_COUNT = 2
CURSED_COUNT = 2
BLESSED_BONUS = 20
CURSED_PENALTY = 15
THREE_STAR_BOUNTY = 75

# Data paths
DATA_DIR = os.getenv("DATA_DIR", ".")
DATA_FILE = os.path.join(DATA_DIR, "user_data.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
BALANCES_FILE = os.path.join(DATA_DIR, "balances.json")

# Region mappings
PLATFORM_MAP = {
    "na": "na1", "euw": "euw1", "eune": "eun1", "kr": "kr",
    "br": "br1", "oce": "oc1", "jp": "jp1", "tr": "tr1",
    "lan": "la1", "las": "la2", "ru": "ru",
}
REGIONAL_MAP = {
    "na": "americas", "br": "americas", "lan": "americas", "las": "americas", "oce": "americas",
    "euw": "europe", "eune": "europe", "tr": "europe", "ru": "europe",
    "kr": "asia", "jp": "asia",
}