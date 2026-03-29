import re
import discord
from typing import Optional
from bot.config import TFT_ACTIVITY_NAMES, IN_GAME_KEYWORDS, NOT_IN_GAME_KEYWORDS


def get_tft_activity(member: discord.Member) -> Optional[discord.Activity]:
    """Detect TFT activity. Discord shows it as:
    name:    'League of Legends'
    details: 'Teamfight Tactics (Ranked)'
    state:   'In Lobby (1 of 3)' / 'In Game' / etc.
    """
    for activity in member.activities:
        name = (getattr(activity, "name", None) or "").lower()
        details = (getattr(activity, "details", None) or "").lower()
        combined = f"{name} {details}"
        if any(kw in combined for kw in TFT_ACTIVITY_NAMES):
            return activity
    return None


def is_in_game(activity: Optional[discord.Activity]) -> bool:
    """Check if TFT presence indicates active game."""
    if not activity:
        return False
    details = (getattr(activity, "details", None) or "").lower()
    state = (getattr(activity, "state", None) or "").lower()
    combined = f"{details} {state}"

    if any(kw in combined for kw in IN_GAME_KEYWORDS):
        return True
    if any(kw in combined for kw in NOT_IN_GAME_KEYWORDS):
        return False
    return False


def log_activity(label: str, member: discord.Member):
    for activity in member.activities:
        name = getattr(activity, "name", None) or "?"
        details = getattr(activity, "details", None)
        state_val = getattr(activity, "state", None)
        parts = [f"[{label}] {type(activity).__name__}: {name}"]
        if details:
            parts.append(f"details={details}")
        if state_val:
            parts.append(f"state={state_val}")
        print(f"   🎮 {' | '.join(parts)}")
        if hasattr(activity, "to_dict"):
            try:
                print(f"      RAW: {activity.to_dict()}")
            except:
                pass