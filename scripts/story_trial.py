"""The story trial: how a rules version plays as a story, over ten seeds.

    python scripts/story_trial.py --rules-version 1.0 [--flags upkeep_phase=1,prestige=0]
    python scripts/story_trial.py --matrix [--markdown FILE]

Plays `--turns` turns (default 100) on scratch copies of the Meridian world
(`meridian-v1.0.3`) for each seed in `--seeds` (default 1867-1876) under a named
rules version, with any of its feature flags overridden, builds the game's beats
(hoc/export/beats.py), replays them as dispatches with the story layer
(tests/js/story_report.mjs), and prints one table of mean and range across the
seeds. Nothing it plays touches a scenario, hoc.db or the record: every world is
built from the blank seed into a temporary directory and thrown away.

`--matrix` runs the comparison docs/STORY_DESIGN.md Phase C1 asks for: the
current published rules as a baseline, the draft version with each of its new
flags on alone (the earlier versions' flags left as the draft sets them), and
the draft with every flag on.

`--c2` runs Phase C2's before/after: the current published rules, the draft
with Phase C1's flags on and Phase C2's off ("C1 all on"), and the draft with
every flag on ("§6 all on").

What it measures (§6, as far as it can be measured without schemes):

- the share of actions aimed at another named house;
- ridings passing between houses, in all and per turn after turn 20;
- prestige (or provisional standing) lead changes and the longest single lead;
- §5's chapters as turn ranges: in how many after the first a house that began
  the chapter in the top eight ended it outside or removed;
- the share of turns whose headline reaches the pause threshold, and the longest
  run of quiet turns after turn 10;
- houses active and ridings claimed at turns 25, 50 and 100, and the share of
  the ridings open at personal 1867 claimed by turn 60;
- storylines with five or more beats, by type; closed storylines without an
  outcome; the share of headlines by storyline type;
- rivalries by outcome and the median number of turns a rivalry runs;
- median capital, influence and cohesion at turn 100;
- Crown foundings by turn 25, and the most in any ten turns after turn 40.

And Phase C2's (rules 1.0 `schemes` and `contested_claims`), from the schemes
table and the story layer:

- the share of closed rivalries reconciled, and the share ended by a contest, a
  cession under a standing claim or a house's removal;
- contests resolved, and the share the attacker won;
- the share of claims their target answered (of those it had a turn to);
- houses fallen or removed by turn 100;
- the share of ended schemes that reached their resolution, and the median
  length of a resolved scheme in turns;
- after turn 15, the share of turns with at least three public schemes
  involving a house of the cast.
"""

import argparse
import json
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import rules_data, scenario  # noqa: E402
from hoc.export import beats as beats_export  # noqa: E402

REFERENCE = "meridian-v1.0.3"
SEEDS = tuple(range(1867, 1877))
TURNS = 100
AIMED = {
    "Correspond", "Propose compact", "Reconcile", "Dispute", "Challenge (11b)",
    "Purchase riding", "Marriage alliance", "Absorb", "Cede / swap",
    # Rules 1.0 `schemes`: the schemes with a named house as their target.
    "Claim a riding", "Buy out a neighbour", "Break a rival", "Dynastic match",
    "Seek a protector", "Make peace", "Fortify", "Sue for peace", "Counter-claim",
}
NEW_FLAGS = (
    "upkeep_phase", "holder_traits", "marriage_pairing", "prestige", "founding_curve",
    "succession_watch",
)
C2_FLAGS = ("schemes", "contested_claims", "prestige_politics", "cohesion_strain")
DECISIVE = ("won in a contest", "held in a contest", "ceded under a claim", "a house removed")
REPORT = ROOT / "tests" / "js" / "story_report.mjs"


def _counts(conn):
    houses = conn.execute("SELECT COUNT(*) AS n FROM houses WHERE status = 'active'").fetchone()["n"]
    ridings = conn.execute(
        "SELECT COUNT(*) AS n FROM holdings WHERE released_event_id IS NULL"
    ).fetchone()["n"]
    return houses, ridings


def play_one(version, overrides, seed, turns=TURNS):
    """One seed: the trial's raw numbers for it."""
    import load_seed

    from hoc import sim

    with tempfile.TemporaryDirectory(prefix="hoc-trial-") as work:
        work = Path(work)
        conn = load_seed.build(
            work / "trial.db", seed=scenario.blank_seed_dir(), reference_data=REFERENCE,
        )
        rules = rules_data.load_rules(version=version)
        rules.features.update(overrides)
        world = sim.World(conn, rules=rules, world_seed=seed)
        open_1867 = {
            fed for fed, stats in world.riding_stats.items() if stats.get("opens_year", 1867) <= 1867
        } or {row["fed_id"] for row in conn.execute("SELECT fed_id FROM ridings")}
        at = {}
        with conn:
            world.initialise(seed)
            last = None
            for season in range(2, turns + 1):
                last = world.run_season()
                if season in (25, 50, 60, 75, 100):
                    at[season] = _counts(conn)
                if season in (25, 50, 75, 100):
                    # Phase D1: the share of the ridings in play that year that
                    # are held — under world_calendar, those whose sovereign is
                    # Canada; otherwise those open by the year a house founded
                    # in 1867 would have reached.
                    year = 1866 + season
                    feds = [r["fed_id"] for r in conn.execute("SELECT fed_id FROM ridings")]
                    if world.feature("world_calendar"):
                        play = {f for f in feds if world.in_play(f, year)}
                    else:
                        play = {f for f in feds if world.opens_year(f) <= year}
                    held = {r["fed_id"] for r in conn.execute(
                        "SELECT fed_id FROM holdings WHERE released_event_id IS NULL")}
                    at[f"inplay{season}"] = len(held & play) / len(play)
                if season == 60:
                    ranked = sorted((-world.standing(r["house"]), r["house"]) for r in world.active_houses())
                    top = [world.rank_index.get(world.house_row(h)["rank"], 0) for _, h in ranked[:8]]
                    at["rank_span60"] = (max(top) - min(top) + 1) if top else 0
                    held = {r["fed_id"] for r in conn.execute(
                        "SELECT fed_id FROM holdings WHERE released_event_id IS NULL")}
                    at["open60"] = len(held & open_1867) / len(open_1867)

        actions = [row["action"] for row in conn.execute("SELECT action FROM house_actions")]
        aimed = sum(1 for a in actions if a in AIMED)
        median = {}
        for stat in ("capital", "influence", "cohesion"):
            values = [row[stat] for row in conn.execute(
                f"SELECT s.{stat} FROM house_stats s JOIN houses h ON h.house = s.house"
                " WHERE h.status = 'active'")]
            median[stat] = statistics.median(values) if values else 0
        crown = [row["founded_season"] for row in conn.execute(
            "SELECT founded_season FROM house_stats WHERE founded_by = 'crown' ORDER BY founded_season")]
        late_window = max(
            (sum(1 for s in crown if start <= s < start + 10) for start in range(41, turns - 8)),
            default=0,
        )

        claims = [s.scheme for s in rules.schemes if s.resolves_as == "contest"]
        schemes = conn.execute("SELECT * FROM schemes").fetchall()
        contests = [r for r in schemes if r["scheme"] in claims and r["status"] == "resolved"
                    and r["outcome"] in ("won", "held")]
        considered = [r for r in schemes if r["scheme"] in claims and r["considered"] > 0]
        ended = [r for r in schemes if r["status"] != "active"]
        resolved = [r for r in ended if r["status"] == "resolved"]
        lengths = sorted(r["ended_season"] - r["begun_season"] + 1 for r in resolved)
        removed = conn.execute(
            "SELECT COUNT(*) AS n FROM houses WHERE status = 'removed'").fetchone()["n"]
        # Phase D1 `crises` and `world_calendar`.
        crises = [json.loads(r["mechanical_delta"])["crisis"] for r in conn.execute(
            "SELECT mechanical_delta FROM events WHERE kind = 'societal'"
            " AND mechanical_delta LIKE '%\"crisis\"%' ORDER BY id")]
        d1 = {}
        if crises:
            d1["crisis_both_camps"] = sum(1 for c in crises if c["lead"] and c["resist"]) / len(crises)
            d1["crisis_lead_carried"] = sum(1 for c in crises if c["carried"] == "lead") / len(crises)
        if world.feature("world_calendar"):
            d1["reckoning"] = 1 if last is not None and "reckoning" in last else 0

        turn_inputs, _ = beats_export.turn_inputs(conn)
        # A riding passing between houses: a transfer, or (rules 1.0) a claim
        # won in a contest, and each riding a rout takes.
        passes = [(turn, beat) for turn, data in turn_inputs for beat in beats_export.type_turn(data)
                  if beat["kind"] in ("riding_passes", "contest_won")]
        beats_export.write_beats(conn, work / "data", title=f"trial {seed}")
        conn.close()
        report = json.loads(subprocess.run(
            ["node", str(REPORT), str(work / "data" / "beats")],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout)

    story = report["storylines"]
    trial = report["trial"]
    headlines = report["summary"]["headlines"] or 1
    outcomes = trial["rivalryOutcomes"]
    closed = sum(v for k, v in outcomes.items() if k != "open")
    c2 = {}
    if schemes:
        c2 = {
            "rivalry_reconciled": outcomes.get("reconciled", 0) / closed if closed else 0,
            "rivalry_decisive": sum(outcomes.get(k, 0) for k in DECISIVE) / closed if closed else 0,
            "contests": len(contests),
            "attacker_wins": (sum(1 for r in contests if r["outcome"] == "won") / len(contests)
                              if contests else 0),
            "claims_answered": (sum(1 for r in considered if r["considered"] == 2) / len(considered)
                                if considered else 0),
            "schemes_resolved": len(resolved) / len(ended) if ended else 0,
            "median_scheme_turns": statistics.median(lengths) if lengths else 0,
            "cast_scheme_share": trial.get("castSchemeShare") or 0,
        }
    return {
        "aimed": aimed / len(actions) if actions else 0,
        "passes": len(passes),
        "passes_after_20_per_turn": sum(1 for t, _ in passes if t > 20) / max(1, turns - 20),
        "lead_changes": trial["leadChanges"],
        "longest_lead": trial["longestLead"],
        "chapters_churned": sum(1 for c in trial["chapterChurn"] if c),
        "heavy_share": trial["heavyShare"],
        "max_quiet_run": trial["maxQuietRunAfter10"],
        "houses_25": at[25][0], "houses_50": at[50][0], "houses_100": at[100][0],
        "ridings_25": at[25][1], "ridings_50": at[50][1], "ridings_100": at[100][1],
        "open_claimed_60": at["open60"],
        "in_play_25": at["inplay25"], "in_play_50": at["inplay50"],
        "in_play_75": at["inplay75"], "in_play_100": at["inplay100"],
        "five_plus": story["fivePlus"],
        "rise_decline": story["byType"].get("rise", 0) + story["byType"].get("decline", 0),
        "pause_share": report["summary"]["paused"] / max(1, report["summary"]["turns"]),
        "rank_span_60": at["rank_span60"],
        "five_plus_by_type": trial["fivePlusByType"],
        "closed_without_outcome": story["closedWithoutOutcome"],
        "headline_types": {k: v / headlines for k, v in trial["headlineTypes"].items()},
        "rivalry_outcomes": trial["rivalryOutcomes"],
        "median_rivalry_turns": trial["medianRivalryTurns"],
        "median_capital": median["capital"],
        "median_influence": median["influence"],
        "median_cohesion": median["cohesion"],
        "crown_by_25": sum(1 for s in crown if s <= 25),
        "crown_late_window": late_window,
        "removed_100": removed,
        **c2,
        **d1,
    }


def run_config(label, version, overrides, seeds=SEEDS, turns=TURNS):
    return label, [play_one(version, overrides, seed, turns) for seed in seeds]


# --------------------------------------------------------------------- table --

def _flat(results):
    """Every scalar and dict-of-scalars metric across seeds, keyed by name."""
    keys = {}
    for r in results:
        for key, value in r.items():
            if isinstance(value, dict):
                for sub, v in value.items():
                    keys.setdefault(f"{key}.{sub}", []).append(v)
            elif value is not None:
                keys.setdefault(key, []).append(value)
    # A breakdown key missing from a seed counts as zero there.
    n = len(results)
    for key, values in keys.items():
        if "." in key and len(values) < n:
            values.extend([0] * (n - len(values)))
    return keys


ROWS = (
    ("§6 actions aimed at another house (target ≥ 30%)", "aimed", "pct"),
    ("§6 riding passes per turn after 20 (target ≥ 0.33)", "passes_after_20_per_turn", "num2"),
    ("ridings passing between houses, all turns", "passes", "num"),
    ("§6 lead changes (target ≥ 4)", "lead_changes", "num"),
    ("§6 longest single lead, turns (target ≤ 50)", "longest_lead", "num"),
    ("§6 chapters II–V with top-eight churn (target 4)", "chapters_churned", "num"),
    ("D1 turns with a headline ≥ pause (target 40–65%)", "heavy_share", "pct"),
    ("§6 longest quiet run after turn 10 (target ≤ 3)", "max_quiet_run", "num"),
    ("§6 houses active at turn 100 (target 20–40)", "houses_100", "num"),
    ("D1 ranks spanned by the top eight at turn 60 (target ≥ 3)", "rank_span_60", "num"),
    ("D1 rise and decline storylines (target ≤ 20)", "rise_decline", "num"),
    ("D1 turns that pause Auto (target 15–30%)", "pause_share", "pct"),
    ("D1 ridings in play held at turn 25 (no target)", "in_play_25", "pct"),
    ("D1 ridings in play held at turn 50 (no target)", "in_play_50", "pct"),
    ("D1 ridings in play held at turn 75 (no target)", "in_play_75", "pct"),
    ("D1 ridings in play held at turn 100 (no target)", "in_play_100", "pct"),
    ("§6 storylines of 5+ beats (target ≥ 8)", "five_plus", "num"),
    ("§6 closed storylines without an outcome (target 0)", "closed_without_outcome", "num"),
    ("houses active at turn 25", "houses_25", "num"),
    ("houses active at turn 50", "houses_50", "num"),
    ("ridings claimed at turn 25", "ridings_25", "num"),
    ("ridings claimed at turn 50", "ridings_50", "num"),
    ("ridings claimed at turn 100", "ridings_100", "num"),
    ("Crown foundings by turn 25", "crown_by_25", "num"),
    ("most Crown foundings in ten turns after 40", "crown_late_window", "num"),
    ("D1 median capital at turn 100 (target 30–70)", "median_capital", "num"),
    ("§6 median influence at turn 100 (target 40–70)", "median_influence", "num"),
    ("§6 median cohesion at turn 100 (target 55–85)", "median_cohesion", "num"),
    ("§6 median turns a rivalry runs (target 4–10)", "median_rivalry_turns", "num"),
    ("§6 houses fallen or removed by turn 100 (target 4–10)", "removed_100", "num"),
    ("§6 rivalries reconciled (target ≤ 40%)", "rivalry_reconciled", "pct"),
    ("§6 rivalries ended by contest, cession under a claim or a fall (target ≥ 25%)",
     "rivalry_decisive", "pct"),
    ("D1 contests resolved (target 20–35)", "contests", "num"),
    ("§6 contests the attacker won (target 35–60%)", "attacker_wins", "pct"),
    ("§6 claims answered by their target (target ≥ 50%)", "claims_answered", "pct"),
    ("§6 ended schemes that reached resolution (target ≥ 60%)", "schemes_resolved", "pct"),
    ("§6 median turns a resolved scheme runs (target 3–6)", "median_scheme_turns", "num"),
    ("§6 turns after 15 with 3+ cast schemes (target ≥ 80%)", "cast_scheme_share", "pct"),
    ("D1 crises with both camps non-empty (target ≥ 70%)", "crisis_both_camps", "pct"),
    ("D1 crises carried by those who lead", "crisis_lead_carried", "pct"),
    ("D1 games ending with a reckoning (target 100%)", "reckoning", "pct"),
)


def _cell(values, style):
    if not values:
        return "—"
    mean = sum(values) / len(values)
    lo, hi = min(values), max(values)
    if style == "pct":
        return f"{100 * mean:.0f}% ({100 * lo:.0f}–{100 * hi:.0f})"
    if style == "num2":
        return f"{mean:.2f} ({lo:.2f}–{hi:.2f})"
    return f"{mean:.1f} ({lo:g}–{hi:g})"


def table(configs, markdown=True):
    """One row per metric, one column per configuration: mean (min–max)."""
    labels = [label for label, _ in configs]
    flats = [_flat(results) for _, results in configs]
    rows = [(name, key, style) for name, key, style in ROWS]
    extra = sorted({k for f in flats for k in f if "." in k})
    for key in extra:
        group, sub = key.split(".", 1)
        style = "pct" if group == "headline_types" else "num"
        title = {
            "five_plus_by_type": "storylines of 5+ beats", "headline_types": "headlines in",
            "rivalry_outcomes": "rivalries",
        }[group]
        rows.append((f"{title}: {sub}", key, style))
    out = ["| metric | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    for name, key, style in rows:
        out.append(f"| {name} | " + " | ".join(_cell(f.get(key, []), style) for f in flats) + " |")
    return "\n".join(out)


def matrix(draft="1.0", baseline=None, seeds=SEEDS, turns=TURNS, workers=4):
    baseline = baseline or rules_data.current_version()
    draft_features = rules_data.load_features(draft)
    off = {flag: False for flag in NEW_FLAGS}
    plan = [(baseline, baseline, {})]
    for flag in NEW_FLAGS:
        plan.append((f"{draft}: {flag}", draft, {**off, flag: True}))
    plan.append((f"{draft}: all on", draft, {f: draft_features.get(f, False) for f in NEW_FLAGS}))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_config, label, version, overrides, seeds, turns)
                   for label, version, overrides in plan]
        return [f.result() for f in futures]


def c2_compare(draft="1.0", baseline=None, seeds=SEEDS, turns=TURNS, workers=4):
    """Phase C2's before/after: the published rules, the draft with Phase C1's
    flags on and Phase C2's off, and the draft with every flag on."""
    baseline = baseline or rules_data.current_version()
    draft_features = rules_data.load_features(draft)
    plan = [
        (baseline, baseline, {}),
        (f"{draft}: C1 all on", draft, {**{f: draft_features.get(f, False) for f in NEW_FLAGS},
                                         **{f: False for f in C2_FLAGS}}),
        (f"{draft}: C2 all on", draft, {f: draft_features.get(f, False) for f in NEW_FLAGS + C2_FLAGS}),
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_config, label, version, overrides, seeds, turns)
                   for label, version, overrides in plan]
        return [f.result() for f in futures]


def _parse_flags(text):
    out = {}
    for part in (text or "").split(","):
        if not part.strip():
            continue
        name, _, value = part.partition("=")
        if name.strip() not in rules_data.FEATURE_DEFAULTS:
            raise SystemExit(f"unknown flag {name!r}")
        out[name.strip()] = value.strip() not in ("0", "false", "off")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rules-version", default=None)
    parser.add_argument("--flags", default="", help="name=1,name=0 overrides")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--c2", action="store_true", help="Phase C2's before/after table")
    parser.add_argument("--seeds", default=f"{SEEDS[0]}-{SEEDS[-1]}")
    parser.add_argument("--turns", type=int, default=TURNS)
    parser.add_argument("--markdown", default=None, help="also write the table here")
    parser.add_argument("--json", default=None, help="also write the raw results here")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    if shutil.which("node") is None:
        raise SystemExit("node is not on PATH: the story report needs it")
    first, _, last = args.seeds.partition("-")
    seeds = tuple(range(int(first), int(last or first) + 1))

    if args.matrix:
        configs = matrix(seeds=seeds, turns=args.turns, workers=args.workers)
    elif args.c2:
        configs = c2_compare(seeds=seeds, turns=args.turns, workers=args.workers)
    else:
        version = args.rules_version or rules_data.current_version()
        overrides = _parse_flags(args.flags)
        label = version + (f" {args.flags}" if args.flags else "")
        configs = [run_config(label, version, overrides, seeds, args.turns)]
    text = table(configs)
    print(text)
    if args.markdown:
        Path(args.markdown).write_text(text + "\n", encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(configs, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
