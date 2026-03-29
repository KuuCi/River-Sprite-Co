"""Shared mutable state accessed across modules."""

# {discord_user_id: {"riot_name", "riot_tag", "puuid", "platform", "region", "last_match_id"}}
user_data = {}

# {discord_user_id: {"balance", "vc_minutes_today", "daily_claimed", ...}}
user_balances = {}

# {discord_user_id: {"in_game": bool, "guild_id": int}}
game_states = {}

# {(guild_id, player_user_id): {bet_data}}
active_bets = {}

# {guild_id: channel_id}
announcement_channels = {}

# {guild_id: {"message", "player_bks", "closes_at", "challenges", "close_task", "closed"}}
bet_groups = {}

# {guild_id: {"results": [...], "task": Task}}
pending_results = {}

# [{"id": "TFT13_Ahri", "name": "Ahri"}, ...]
champion_pool = []