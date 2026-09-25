# Riven roller simulator

Simulates cycling Riven mods under the Iceblade of Narin rules: you can
lock exactly one stat, and each cycle with a lock costs extra kuva.
Stdlib only, no installs. Run from this folder:

    python sim.py roll --class rifle --dispo 1.0
    python sim.py sim --class rifle --require damage multishot --lock damage --compare

## Modes

`roll` is a hands-on roller. Unveiling is free, then `cycle` spends kuva
per the live cost curve and shows a pending roll you `accept` or
`decline`. `lock <stat>` pins one positive from the current roll;
`unlock` clears it; `status` shows spend; `pool` lists rollable stats.
A new `cycle` while a roll is pending discards the pending roll.

`sim` is a montecarlo estimator. Define the keeper and a lock strategy,
and it reports keeper rate, rolls/kuva distributions, and expected kuva
per keeper including failed attempts. `--compare` runs the same chase
with the lock on and off. Progress prints to stderr as trials/s with
an ETA (`--no-progress` hides it). Hard chases run around a hundred
trials a second, so a few thousand trials is plenty for a rough answer
and 20k+ gives stable p90s.

## Keeper definition

- `--require a b` positives that must be present (aliases work: `dmg`,
  `ms`, `cc`, `cd`, `fr`, `sc`, `sd`, ...).
- `--min-positives 2|3`, `--no-negative`, `--require-negative`,
  `--ban-curse zoom recoil`.
- `--min-value damage=0.95` demands a stat at 95% of its max possible
  roll (disposition-agnostic).

## Lock strategy

`--lock damage multishot` sets the priority order: after each dud roll,
the first listed stat present on the roll is locked. `--min-lock 0.9`
only locks it if the value is at least 90% of its max roll, since a
lock freezes the value too. Locking a low roll of the right stat and
then paying +50% per cycle on it is the classic trap; use `--compare`
to see it.

## Assumptions (things DE has not locked in)

- Locked cycles cost base x 1.5 (`--lock-mult` overrides). DE confirmed
  locking costs kuva plus extra per cycle with a lock, not the amount.
- Locked stat keeps its identity and value; stat-count odds are
  unchanged while locked; one lock at a time; positives only.
- Stat-count weights (2/3 positives x neg/no-neg) are equal at 25%
  each; the real weights are not public. Edit `DEFAULT_COUNT_WEIGHTS`
  in `data.py` when they are known.
- Stat draws are uniform within the pool, no duplicates per roll, the
  curse never equals a positive on the same roll.
- Value formula follows the wiki: base x disposition x count
  multiplier x uniform(0.9, 1.1), rounded to 1 decimal. Bow fire-rate
  doubling and heavy-attack crit doubling are display quirks, skipped.
- Base values are the wiki max-rank table. Impact/puncture/slash need a
  25%+ physical share on the weapon; `--no-physical` drops them.
- Stat combining (Heat + Cold = Blast, Damage + Multishot = Weakspot
  Damage) is deterministic and post-roll, so it is reference data in
  `data.py`, not simulated. It still matters for strategy: stats you
  plan to combine later are fine lock targets even if they look weak
  today.

## Example result

Rifle, dispo 1.0, chasing Damage + Multishot, 20k trials:

- No lock: ~467k kuva expected per keeper, median 94 rolls.
- Lock Damage on sight at +50%/cycle: ~88k kuva expected, median 19.

Locking wins by a lot on two-stat chases because the second stat only
has to land once alongside a frozen first. The gap shrinks if you set
`--min-lock` high (fewer locks qualify) or chase three positives.
