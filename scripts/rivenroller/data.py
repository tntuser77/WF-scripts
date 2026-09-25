"""Static data for the riven roller simulator.

Sources and assumptions are documented in README.md. Base stat values are
taken from the WARFRAME wiki Riven Mods page (max-rank values per weapon
class). Kuva cycle costs are the live in-game curve.
"""

CLASSES = ("rifle", "shotgun", "pistol", "melee", "archgun")

# (positive count, has negative) -> (bonus multiplier, malus multiplier).
# From the wiki attribute value formula table.
COUNT_MULTS = {
    (2, False): (0.99, 0.0),
    (2, True): (1.2375, -0.495),
    (3, False): (0.75, 0.0),
    (3, True): (0.9375, -0.75),
}

# Default draw weights for the four stat-count configs above.
# The real weights are not public, so equal weights are assumed (configurable).
DEFAULT_COUNT_WEIGHTS = {
    (2, False): 0.25,
    (2, True): 0.25,
    (3, False): 0.25,
    (3, True): 0.25,
}

# Live kuva cost curve. cycle_cost(n) is the price of the nth cycle.
KUVA_COSTS = [900, 1000, 1200, 1400, 1700, 2000, 2350, 2750, 3150, 3500]


def kuva_cost(cycle_number, locked=False, lock_mult=1.5):
    """Kuva price of the nth cycle (1-based). Locked rolls cost extra."""
    base = KUVA_COSTS[min(cycle_number, len(KUVA_COSTS)) - 1]
    if locked:
        return int(base * lock_mult + 0.5)
    return base


# Per-stat metadata. "base" maps weapon class to the wiki base value
# (None = cannot roll on that class). "units" is only used for display.
# "pos_only" stats can never appear as the negative curse; per the wiki
# that is cold/heat/electricity/toxin/punch_through/damage, plus multishot
# which is also never a curse in game. "physical" stats only roll on
# weapons with a big share of that physical damage type (toggleable).
STATS = {
    "combo_chance": {
        "label": "Additional Combo Count Chance",
        "base": {"melee": 58.77},
        "units": "%",
    },
    "ammo_max": {
        "label": "Ammo Maximum",
        "base": {"rifle": 49.95, "shotgun": 90.0, "pistol": 90.0,
                 "archgun": 99.9},
        "units": "%",
    },
    "dmg_corpus": {
        "label": "Damage vs Corpus",
        "base": {"rifle": 0.45, "shotgun": 0.45, "pistol": 0.45,
                 "archgun": 0.45, "melee": 0.45},
        "units": "x",
    },
    "dmg_grineer": {
        "label": "Damage vs Grineer",
        "base": {"rifle": 0.45, "shotgun": 0.45, "pistol": 0.45,
                 "archgun": 0.45, "melee": 0.45},
        "units": "x",
    },
    "dmg_infested": {
        "label": "Damage vs Infested",
        "base": {"rifle": 0.45, "shotgun": 0.45, "pistol": 0.45,
                 "archgun": 0.45, "melee": 0.45},
        "units": "x",
    },
    "cold": {
        "label": "Cold Damage",
        "base": {"rifle": 90.0, "shotgun": 90.0, "pistol": 90.0,
                 "archgun": 119.7, "melee": 90.0},
        "units": "%",
        "pos_only": True,
    },
    "combo_duration": {
        "label": "Combo Duration",
        "base": {"melee": 8.1},
        "units": "s",
    },
    "crit_chance": {
        "label": "Critical Chance",
        "base": {"rifle": 149.99, "shotgun": 90.0, "pistol": 149.99,
                 "archgun": 99.9, "melee": 180.0},
        "units": "%",
    },
    "crit_slide": {
        "label": "Critical Chance for Slide Attack",
        "base": {"melee": 120.0},
        "units": "%",
    },
    "crit_damage": {
        "label": "Critical Damage",
        "base": {"rifle": 120.0, "shotgun": 90.0, "pistol": 90.0,
                 "archgun": 80.1, "melee": 90.0},
        "units": "%",
    },
    "damage": {
        "label": "Damage",
        "base": {"rifle": 165.0, "shotgun": 164.7, "pistol": 219.6,
                 "archgun": 99.9, "melee": 164.7},
        "units": "%",
        "pos_only": True,
    },
    "electricity": {
        "label": "Electricity Damage",
        "base": {"rifle": 90.0, "shotgun": 90.0, "pistol": 90.0,
                 "archgun": 119.7, "melee": 90.0},
        "units": "%",
        "pos_only": True,
    },
    "heat": {
        "label": "Heat Damage",
        "base": {"rifle": 90.0, "shotgun": 90.0, "pistol": 90.0,
                 "archgun": 119.7, "melee": 90.0},
        "units": "%",
        "pos_only": True,
    },
    "finisher": {
        "label": "Finisher Damage",
        "base": {"melee": 119.7},
        "units": "%",
    },
    "fire_rate": {
        "label": "Fire Rate / Attack Speed",
        "base": {"rifle": 60.03, "shotgun": 90.0, "pistol": 74.7,
                 "archgun": 60.03, "melee": 54.9},
        "units": "%",
    },
    "projectile_speed": {
        "label": "Projectile Speed",
        "base": {"rifle": 90.0, "shotgun": 90.0, "pistol": 90.0},
        "units": "%",
    },
    "initial_combo": {
        "label": "Initial Combo",
        "base": {"melee": 24.5},
        "units": "flat",
    },
    "impact": {
        "label": "Impact Damage",
        "base": {"rifle": 119.97, "shotgun": 119.97, "pistol": 119.97,
                 "archgun": 90.0, "melee": 119.7},
        "units": "%",
        "physical": True,
    },
    "magazine": {
        "label": "Magazine Capacity",
        "base": {"rifle": 50.0, "shotgun": 50.0, "pistol": 50.0,
                 "archgun": 60.3},
        "units": "%",
    },
    "heavy_efficiency": {
        "label": "Heavy Attack Efficiency",
        "base": {"melee": 73.44},
        "units": "%",
    },
    "multishot": {
        "label": "Multishot",
        "base": {"rifle": 90.0, "shotgun": 119.7, "pistol": 119.7,
                 "archgun": 60.3},
        "units": "%",
        "pos_only": True,
    },
    "toxin": {
        "label": "Toxin Damage",
        "base": {"rifle": 90.0, "shotgun": 90.0, "pistol": 90.0,
                 "archgun": 119.7, "melee": 90.0},
        "units": "%",
        "pos_only": True,
    },
    "punch_through": {
        "label": "Punch Through",
        "base": {"rifle": 2.7, "shotgun": 2.7, "pistol": 2.7,
                 "archgun": 2.7},
        "units": "m",
        "pos_only": True,
    },
    "puncture": {
        "label": "Puncture Damage",
        "base": {"rifle": 119.97, "shotgun": 119.97, "pistol": 119.97,
                 "archgun": 90.0, "melee": 119.7},
        "units": "%",
        "physical": True,
    },
    "reload": {
        "label": "Reload Speed",
        "base": {"rifle": 50.0, "shotgun": 50.0, "pistol": 50.0,
                 "archgun": 99.9},
        "units": "%",
    },
    "range": {
        "label": "Range",
        "base": {"melee": 1.94},
        "units": "m",
    },
    "slash": {
        "label": "Slash Damage",
        "base": {"rifle": 119.97, "shotgun": 119.97, "pistol": 119.97,
                 "archgun": 90.0, "melee": 119.7},
        "units": "%",
        "physical": True,
    },
    "status_chance": {
        "label": "Status Chance",
        "base": {"rifle": 90.0, "shotgun": 90.0, "pistol": 90.0,
                 "archgun": 60.3, "melee": 90.0},
        "units": "%",
    },
    "status_duration": {
        "label": "Status Duration",
        "base": {"rifle": 99.99, "shotgun": 99.99, "pistol": 99.99,
                 "archgun": 99.99, "melee": 99.99},
        "units": "%",
    },
    "recoil": {
        "label": "Weapon Recoil",
        "base": {"rifle": 90.0, "shotgun": 90.0, "pistol": 90.0,
                 "archgun": 90.0},
        "units": "%",
    },
    "zoom": {
        "label": "Zoom",
        "base": {"rifle": 59.99, "pistol": 80.1, "archgun": 59.99},
        "units": "%",
    },
}

# Shorthand aliases accepted on the command line.
ALIASES = {
    "dmg": "damage",
    "ms": "multishot",
    "cc": "crit_chance",
    "cd": "crit_damage",
    "fr": "fire_rate",
    "as": "fire_rate",
    "sc": "status_chance",
    "sd": "status_duration",
    "mag": "magazine",
    "reload": "reload",
    "elec": "electricity",
    "tox": "toxin",
    "pt": "punch_through",
    "corpus": "dmg_corpus",
    "grineer": "dmg_grineer",
    "infested": "dmg_infested",
    "ammo": "ammo_max",
    "proj": "projectile_speed",
    "fs": "projectile_speed",
    "combo": "combo_duration",
}


def canonical(name):
    """Resolve a user-typed stat name or alias to a canonical stat key."""
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    key = ALIASES.get(key, key)
    if key not in STATS:
        raise ValueError(f"unknown stat '{name}'")
    return key


def positive_pool(cls, physical=True):
    """Stat keys that can roll as positives for a weapon class."""
    pool = []
    for name, meta in STATS.items():
        if cls not in meta["base"]:
            continue
        if meta.get("physical") and not physical:
            continue
        pool.append(name)
    return pool


def curse_pool(cls, physical=True):
    """Stat keys that can roll as the negative curse."""
    return [n for n in positive_pool(cls, physical)
            if not STATS[n].get("pos_only")]


# Stat-combining recipes announced for Iceblade of Narin (reference only;
# combining is a deterministic post-roll action, not part of rolling).
KNOWN_COMBINES = {
    ("cold", "heat"): "blast",
    ("damage", "multishot"): "weakspot_damage",
}
