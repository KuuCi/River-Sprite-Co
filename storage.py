import json
import os
from bot.config import DATA_FILE, SETTINGS_FILE, BALANCES_FILE, STARTING_BALANCE
from bot import state


def load_user_data():
    state.user_data = json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else {}


def save_user_data():
    with open(DATA_FILE, "w") as f:
        json.dump(state.user_data, f, indent=2)


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        data = json.load(open(SETTINGS_FILE))
        state.announcement_channels = {int(k): v for k, v in data.get("announcement_channels", {}).items()}
    else:
        state.announcement_channels = {}


def save_settings():
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"announcement_channels": state.announcement_channels}, f, indent=2)


def load_balances():
    state.user_balances = json.load(open(BALANCES_FILE)) if os.path.exists(BALANCES_FILE) else {}


def save_balances():
    with open(BALANCES_FILE, "w") as f:
        json.dump(state.user_balances, f, indent=2)


def get_balance(user_id: str) -> int:
    if user_id not in state.user_balances:
        state.user_balances[user_id] = {
            "balance": STARTING_BALANCE,
            "vc_minutes_today": 0,
            "vc_join_time": None,
            "daily_claimed": False,
            "last_daily_date": None,
        }
        save_balances()
    return state.user_balances[user_id]["balance"]


def update_balance(user_id: str, amount: int) -> int:
    get_balance(user_id)
    state.user_balances[user_id]["balance"] = max(0, state.user_balances[user_id]["balance"] + amount)
    save_balances()
    return state.user_balances[user_id]["balance"]


def set_balance(user_id: str, amount: int) -> int:
    get_balance(user_id)
    state.user_balances[user_id]["balance"] = max(0, amount)
    save_balances()
    return state.user_balances[user_id]["balance"]