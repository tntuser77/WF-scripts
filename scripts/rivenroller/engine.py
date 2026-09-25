"""Core simulation engine: rolling, stat locking, keeper matching, trials."""

import random
from dataclasses import dataclass, field

from data import (
    COUNT_MULTS,
    DEFAULT_COUNT_WEIGHTS,
    STATS,
    curse_pool,
    kuva_cost,
    positive_pool,
)


@dataclass(frozen=True)
class Stat:
    name: str
    value: float  # signed; negative values are curses
    positive: bool

    @property
    def label(self):
        return STATS[self.name]["label"]

    def display(self):
        units = STATS[self.name]["units"]
        if units == "x":
            return f"{self.value:+.2f}x {self.label}"
        if units in ("s", "m", "flat"):
            return f"{self.value:+.1f}{units} {self.label}"
        if self.name == "recoil" and self.positive:
            return f"{self.value:.1f}% {self.label} (reduced)"
        return f"{self.value:+.1f}% {self.label}"


@dataclass
class Riven:
    positives: list = field(default_factory=list)  # list[Stat]
    negative: object = None  # Stat | None
    rolls: int = 0  # cycles performed to reach this state

    def names(self):
        return {s.name for s in self.positives}

    def get(self, name):
        for s in self.positives:
            if s.name == name:
                return s
        return None

    def describe(self):
        lines = [f"  {s.display()}" for s in self.positives]
        if self.negative is not None:
            lines.append(f"  {self.negative.display()}")
        return "\n".join(lines)


@dataclass
class Target:
    """What counts as a keeper roll."""
    required: frozenset = frozenset()  # positive stat names that must appear
    min_positives: int = 2
    allow_negative: bool = True
    require_negative: bool = False
    banned_curses: frozenset = frozenset()  # curse names that disqualify
    # stat name -> minimum value as a fraction of that stat's max
    # possible roll (disposition-agnostic, e.g. 0.95 = top 5% of range).
    min_frac: dict = field(default_factory=dict)

    def matches(self, riven, dispo, cls):
        if len(riven.positives) < self.min_positives:
            return False
        if not self.required.issubset(riven.names()):
            return False
        if riven.negative is None:
            if self.require_negative:
                return False
        else:
            if not self.allow_negative:
                return False
            if riven.negative.name in self.banned_curses:
                return False
        n_pos = len(riven.positives)
        has_neg = riven.negative is not None
        bonus_mult, _ = COUNT_MULTS[(n_pos, has_neg)]
        for name, frac in self.min_frac.items():
            stat = riven.get(name)
            if stat is None:
                return False
            max_roll = STATS[name]["base"][cls] * dispo * bonus_mult * 1.1
            if stat.value < frac * max_roll:
                return False
        return True


def _roll_value(rng, name, cls, dispo, mult):
    base = STATS[name]["base"][cls]
    return round(base * dispo * mult * rng.uniform(0.9, 1.1), 1)


def roll_riven(rng, cls, dispo, count_weights=None, physical=True,
               locked=None):
    """Generate one cycled riven.

    locked is a Stat (or None) carried over untouched from the current
    roll, per the Iceblade of Narin one-stat lock. Only positives lock.
    """
    weights = count_weights or DEFAULT_COUNT_WEIGHTS
    configs = list(weights)
    config = rng.choices(configs, weights=[weights[c] for c in configs])[0]
    n_pos, has_neg = config
    bonus_mult, malus_mult = COUNT_MULTS[config]

    positives = []
    used = set()
    if locked is not None:
        positives.append(locked)
        used.add(locked.name)

    pool = [n for n in positive_pool(cls, physical) if n not in used]
    for name in rng.sample(pool, n_pos - len(positives)):
        positives.append(Stat(name, _roll_value(rng, name, cls, dispo,
                                                bonus_mult), True))

    negative = None
    if has_neg:
        curse_candidates = [n for n in curse_pool(cls, physical)
                            if n not in used and n not in {s.name for s in positives}]
        if curse_candidates:
            name = rng.choice(curse_candidates)
            negative = Stat(name, _roll_value(rng, name, cls, dispo,
                                             malus_mult), False)
    return Riven(positives, negative)


@dataclass
class TrialResult:
    success: bool
    rolls: int
    kuva: int
    final: object = None  # Riven | None
    locked_name: object = None  # str | None


def run_trial(rng, cls, dispo, target, lock_priority=(), min_lock_frac=0.0,
              max_rolls=10_000, max_kuva=None, lock_mult=1.5,
              count_weights=None, physical=True, allow_lock=True):
    """Roll until the target keeper lands or the budget runs out.

    Lock flow mirrors the announced UI: after each non-keeper roll, the
    first lock_priority stat present at >= min_lock_frac of its max roll
    is locked (only one stat at a time), and every later cycle costs
    extra kuva until a keeper lands.
    """
    locked = None
    riven = roll_riven(rng, cls, dispo, count_weights, physical)
    rolls = 0
    kuva = 0
    if target.matches(riven, dispo, cls):
        return TrialResult(True, 0, 0, riven, None)

    while rolls < max_rolls:
        if locked is None and allow_lock:
            locked = _choose_lock(riven, dispo, cls, lock_priority,
                                  min_lock_frac)
        cost = kuva_cost(rolls + 1, locked is not None, lock_mult)
        if max_kuva is not None and kuva + cost > max_kuva:
            break
        kuva += cost
        rolls += 1
        riven = roll_riven(rng, cls, dispo, count_weights, physical,
                           locked)
        riven.rolls = rolls
        if target.matches(riven, dispo, cls):
            locked_name = locked.name if locked else None
            return TrialResult(True, rolls, kuva, riven, locked_name)
    locked_name = locked.name if locked else None
    return TrialResult(False, rolls, kuva, riven, locked_name)


def _choose_lock(riven, dispo, cls, lock_priority, min_lock_frac):
    n_pos = len(riven.positives)
    has_neg = riven.negative is not None
    bonus_mult, _ = COUNT_MULTS[(n_pos, has_neg)]
    for name in lock_priority:
        stat = riven.get(name)
        if stat is None:
            continue
        max_roll = STATS[name]["base"][cls] * dispo * bonus_mult * 1.1
        if stat.value >= min_lock_frac * max_roll:
            return stat
    return None
