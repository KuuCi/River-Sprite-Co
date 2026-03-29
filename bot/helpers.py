import re
from bot.config import TRAIT_STYLE_EMOJIS


def clean_name(raw: str) -> str:
    n = re.sub(r"^(TFT\d+_|Set\d+_|TFT_Item_|TFT_Augment_)", "", raw)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n).replace("_", " ").strip()


def format_traits(traits: list) -> str:
    active = sorted(
        [t for t in traits if t.get("style", 0) > 0],
        key=lambda t: t.get("style", 0), reverse=True,
    )
    return (
        " | ".join(
            f"{TRAIT_STYLE_EMOJIS.get(t.get('style', 0), '')} {clean_name(t['name'])} {t.get('num_units', 0)}"
            for t in active[:6]
        )
        or "No active traits"
    )


def format_units(units: list) -> str:
    s = sorted(units, key=lambda u: (u.get("tier", 1), u.get("rarity", 0)), reverse=True)
    return (
        ", ".join(f"{'⭐' * u.get('tier', 1)}{clean_name(u.get('character_id', '?'))}" for u in s[:8])
        or "No units"
    )


def format_augments(augments: list) -> str:
    return " | ".join(clean_name(a) for a in augments) if augments else "None"


def format_duration(s: float) -> str:
    return f"{int(s // 60)}m {int(s % 60)}s"


def queue_name(qid: int) -> str:
    return {1090: "Normal", 1100: "Ranked", 1130: "Hyper Roll", 1160: "Double Up", 1210: "Turbo"}.get(qid, "TFT")