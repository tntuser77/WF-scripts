"""Riven roller simulator (Iceblade of Narin rules): interactive + montecarlo.

Usage:
    python sim.py roll --class rifle --dispo 1.0
    python sim.py sim --class rifle --require damage multishot --lock damage
"""

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data import CLASSES, canonical, curse_pool, kuva_cost, positive_pool  # noqa: E402
from engine import Riven, Target, roll_riven, run_trial  # noqa: E402


# --------------------------------------------------------------------------
# shared option parsing


def add_common(p):
    p.add_argument("--class", dest="cls", default="rifle", choices=CLASSES)
    p.add_argument("--dispo", type=float, default=1.0,
                   help="weapon riven disposition, 0.5 - 1.55")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--no-physical", action="store_true",
                   help="weapon lacks 25%%+ share of a physical damage type, "
                        "so impact/puncture/slash cannot roll")
    p.add_argument("--lock-mult", type=float, default=1.5,
                   help="kuva cost multiplier per cycle while a stat is "
                        "locked (assumed 1.5x)")


def parse_min_values(items):
    out = {}
    for item in items or []:
        name, _, frac = item.partition("=")
        out[canonical(name)] = float(frac)
    return out


# --------------------------------------------------------------------------
# interactive rolling


def cmd_roll(args):
    rng = random.Random(args.seed)
    physical = not args.no_physical
    current = roll_riven(rng, args.cls, args.dispo, physical=physical)
    pending = None
    locked = None
    kuva = 0
    cycles = 0
    pool = positive_pool(args.cls, physical)
    print(f"Unveiled {args.cls} riven (dispo {args.dispo}):")
    print(current.describe())
    print("Commands: cycle | accept | decline | lock <stat> | unlock | "
          "status | pool | quit")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        cmd, _, rest = raw.partition(" ")
        cmd = cmd.lower()
        if cmd in ("quit", "q", "exit"):
            break
        elif cmd == "cycle":
            if pending is not None:
                print("(Previous pending roll discarded.)")
            cost = kuva_cost(cycles + 1, locked is not None,
                             args.lock_mult)
            kuva += cost
            cycles += 1
            pending = roll_riven(rng, args.cls, args.dispo,
                                 physical=physical, locked=locked)
            pending.rolls = cycles
            tag = " (LOCKED: %s, x%.2g kuva)" % (locked.name,
                                                 args.lock_mult) if locked else ""
            print(f"Cycle {cycles} costs {cost} kuva{tag}. New roll:")
            print(pending.describe())
            print("accept to keep it, decline to keep the old roll.")
        elif cmd == "accept":
            if pending is None:
                print("Nothing pending. cycle first.")
            else:
                current = pending
                pending = None
                print("Kept the new roll.")
        elif cmd == "decline":
            if pending is None:
                print("Nothing pending.")
            else:
                pending = None
                print("Kept the old roll (kuva is still spent).")
        elif cmd == "lock":
            if not rest:
                print("Usage: lock <stat>")
                continue
            try:
                name = canonical(rest)
            except ValueError as e:
                print(e)
                continue
            stat = current.get(name)
            if stat is None:
                print(f"{name} is not on the current roll.")
            else:
                locked = stat
                print(f"Locked {stat.display()}. Future cycles cost "
                      f"x{args.lock_mult} kuva.")
        elif cmd == "unlock":
            locked = None
            print("Lock cleared.")
        elif cmd == "status":
            print(f"Cycles: {cycles}, kuva spent: {kuva}, "
                  f"locked: {locked.name if locked else 'none'}")
            print("Current roll:")
            print(current.describe())
        elif cmd == "pool":
            curses = set(curse_pool(args.cls, physical))
            for name in pool:
                mark = " (curse ok)" if name in curses else " (pos only)"
                print(f"  {name}{mark}")
        else:
            print("Unknown command.")
    print(f"Done. {cycles} cycles, {kuva} kuva spent.")


# --------------------------------------------------------------------------
# montecarlo


def summarize(results, label):
    n = len(results)
    wins = [r for r in results if r.success]
    total_kuva = sum(r.kuva for r in results)
    print(f"--- {label} ---")
    print(f"trials: {n}, keepers: {len(wins)} ({100.0 * len(wins) / n:.2f}%)")
    if not wins:
        print("no keepers landed.")
        return
    rolls = sorted(r.rolls for r in wins)
    kuvas = sorted(r.kuva for r in wins)

    def pct(xs, p):
        return xs[min(len(xs) - 1, int(p * len(xs)))]

    print(f"rolls to keeper: mean {statistics.mean(rolls):.1f}, "
          f"median {statistics.median(rolls)}, p90 {pct(rolls, 0.9)}")
    print(f"kuva to keeper:  mean {statistics.mean(kuvas):,.0f}, "
          f"median {statistics.median(kuvas):,.0f}, "
          f"p90 {pct(kuvas, 0.9):,.0f}")
    print(f"expected kuva per keeper (incl. failed attempts): "
          f"{total_kuva / len(wins):,.0f}")


def _progress(label, done, total, start):
    el = time.time() - start
    rate = done / el if el > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else 0.0
    sys.stderr.write(f"\r{label}: {done}/{total} "
                     f"({100.0 * done / total:.0f}%) "
                     f"{rate:.0f} trials/s, eta {eta:.0f}s   ")
    sys.stderr.flush()


def run_plan(label, rng, args, target, lock_priority, min_lock_frac,
             physical, allow_lock):
    results = []
    start = time.time()
    next_update = start + 0.25
    for i in range(args.trials):
        results.append(run_trial(rng, args.cls, args.dispo, target,
                                 lock_priority=lock_priority,
                                 min_lock_frac=min_lock_frac,
                                 max_rolls=args.max_rolls,
                                 max_kuva=args.max_kuva,
                                 lock_mult=args.lock_mult,
                                 physical=physical,
                                 allow_lock=allow_lock))
        now = time.time()
        if not args.no_progress and (now >= next_update
                                     or i + 1 == args.trials):
            _progress(label, i + 1, args.trials, start)
            next_update = now + 0.5
    if not args.no_progress:
        sys.stderr.write("\n")
    return results


def cmd_sim(args):
    rng = random.Random(args.seed)
    physical = not args.no_physical
    target = Target(
        required=frozenset(canonical(s) for s in args.require or []),
        min_positives=args.min_positives,
        allow_negative=not args.no_negative,
        require_negative=args.require_negative,
        banned_curses=frozenset(canonical(s) for s in args.ban_curse or []),
        min_frac=parse_min_values(args.min_value),
    )
    lock_priority = [canonical(s) for s in args.lock or []]
    min_lock_frac = args.min_lock
    plans = []
    if args.compare or not args.no_lock:
        plans.append(("stat lock ON", True))
    if args.compare or args.no_lock:
        plans.append(("stat lock OFF", False))
    for label, allow_lock in plans:
        results = run_plan(label, rng, args, target, lock_priority,
                           min_lock_frac, physical, allow_lock)
        summarize(results, label)


# --------------------------------------------------------------------------


def main(argv=None):
    p = argparse.ArgumentParser(description="Riven roller simulator "
                                "(Iceblade of Narin lock rules).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("roll", help="interactively roll one riven")
    add_common(pr)
    pr.set_defaults(func=cmd_roll)

    ps = sub.add_parser("sim", help="montecarlo keeper odds and kuva cost")
    add_common(ps)
    ps.add_argument("--require", nargs="*", default=[],
                    help="positive stats the keeper must have")
    ps.add_argument("--min-positives", type=int, default=2)
    ps.add_argument("--no-negative", action="store_true",
                    help="keeper must have no curse")
    ps.add_argument("--require-negative", action="store_true",
                    help="keeper must have a curse")
    ps.add_argument("--ban-curse", nargs="*", default=[],
                    help="curse names that disqualify a keeper")
    ps.add_argument("--min-value", nargs="*", default=[],
                    help="e.g. damage=0.95 (fraction of max roll)")
    ps.add_argument("--lock", nargs="*", default=[],
                    help="lock priority order, e.g. --lock damage")
    ps.add_argument("--min-lock", type=float, default=0.0,
                    help="only lock a stat at this fraction of its max roll")
    ps.add_argument("--no-lock", action="store_true",
                    help="run the no-lock baseline (implied with --compare)")
    ps.add_argument("--compare", action="store_true",
                    help="run lock ON and lock OFF and show both")
    ps.add_argument("--trials", type=int, default=20000)
    ps.add_argument("--max-rolls", type=int, default=10000)
    ps.add_argument("--max-kuva", type=int, default=None)
    ps.add_argument("--no-progress", action="store_true",
                    help="hide the progress readout on stderr")
    ps.set_defaults(func=cmd_sim)

    args = p.parse_args(argv)
    if not 0.5 <= args.dispo <= 1.55:
        p.error("dispo must be between 0.5 and 1.55")
    args.func(args)


if __name__ == "__main__":
    main()
