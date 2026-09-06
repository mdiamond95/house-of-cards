"""The engine workflow's one entry point: run, intervene, rules, rebuild.

    python scripts/engine_command.py run --seasons 10 --stop-on removal,challenge
    python scripts/engine_command.py intervene --payload '<turn json>' --note "why"
    python scripts/engine_command.py rules --payload '<patch json>' --note "why"
    python scripts/engine_command.py rebuild

The logic lives here rather than in shell inside `.github/workflows/engine.yml`
so that it can be tested, and so a director can run exactly what the workflow
runs from a Code session. Every command writes a markdown run summary to
`$GITHUB_STEP_SUMMARY` (or stdout when that is unset) whether it succeeds or
fails, and prints a one-line commit message for the workflow to use.

Nothing here calls out to anything. Claude is not involved in this path: the
console's Narrate control produces text for a human to paste into a Code
session, and that is the whole of Claude's part in the running game.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import db, scenario, sim  # noqa: E402
from hoc.turn import TurnError, apply_turn  # noqa: E402
from hoc.turnfile import TurnFileError, load as load_turnfile, validate as validate_turnfile  # noqa: E402

COMMIT_PREFIX = "COMMIT_MESSAGE "

# What the console may do through `intervene`. Expansion, succession, elevation
# and the climate ledger are the engine's business — a director who wants those
# runs seasons, or writes a turn by hand in a Code session where the reasoning
# can be recorded properly.
INTERVENTION_OPS = frozenset({
    "set_objective",
    "veto_objective",
    "force_action",
    "adjust_stat",
    "found_house",
    "grant_house",
    "set_clock",
    "relation",
})


class CommandError(Exception):
    """The command will not proceed. Nothing is committed."""


# ------------------------------------------------------------------ summary --


class Summary:
    """The run summary, written whatever happens."""

    def __init__(self, command, note):
        self.command = command
        self.note = note
        self.lines = []
        self.ok = None

    def add(self, text):
        self.lines.append(text)
        return self

    def table(self, before, after):
        self.add("")
        self.add("| | before | after |")
        self.add("|---|---|---|")
        self.add(f"| houses | {before[0]} | {after[0]} |")
        self.add(f"| ridings held | {before[1]} | {after[1]} |")

    def chronicle(self, lines, limit=sim.SUMMARY_CHRONICLE_LINES):
        if not lines:
            return self
        self.add("")
        self.add(f"**Chronicle** (last {min(len(lines), limit)} of {len(lines)})")
        self.add("")
        for line in lines[-limit:]:
            self.add(f"- {line}")
        return self

    def render(self):
        head = f"## Engine — {self.command}"
        if self.ok is False:
            head += " — failed, nothing committed"
        body = [head, ""]
        if self.note:
            body.append(f"> {self.note}")
            body.append("")
        body.extend(self.lines)
        return "\n".join(body) + "\n"

    def write(self):
        text = self.render()
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with open(target, "a", encoding="utf-8") as f:
                f.write(text)
        else:
            print(text)


# -------------------------------------------------------------------- run --


def cmd_run(args, summary):
    seasons = int(args.seasons or 0)
    if seasons < 1:
        raise CommandError(f"seasons must be a positive number, got {args.seasons!r}")

    stop_on = tuple(s.strip() for s in (args.stop_on or "").split(",") if s.strip())
    unknown = set(stop_on) - sim.STOP_CONDITIONS
    if unknown:
        raise CommandError(
            f"unknown stop condition(s): {', '.join(sorted(unknown))}."
            f" Valid: {', '.join(sorted(sim.STOP_CONDITIONS))}"
        )

    conn = db.connect()
    try:
        world = sim.World(conn, seasons_dir=scenario.seasons_dir())
    except sim.SimError as exc:
        conn.close()
        raise CommandError(str(exc)) from exc

    before = world.counts()
    with conn:
        records = world.run(seasons, stop_on=stop_on)
    result = world.run_summary(records, before)
    after = (result["houses_after"], result["ridings_after"])
    conn.close()

    summary.add(
        f"Played **{result['seasons_run']}** season(s), "
        f"{result['season_from']} → {result['season_to']}."
    )
    if result["stopped_on"]:
        summary.add(
            f"Stopped on **{', '.join(result['stopped_on'])}** at season"
            f" **{result['stopped_at_season']}**."
        )
    elif stop_on:
        summary.add(f"Ran to the end; none of {', '.join(stop_on)} occurred.")
    summary.table(before, after)
    summary.chronicle([line for record in records for line in record["chronicle"]])

    stopped = f", stopped on {', '.join(result['stopped_on'])}" if result["stopped_on"] else ""
    return (
        f"run: seasons {result['season_from']}–{result['season_to']}"
        f" ({result['houses_after']} houses, {result['ridings_after']} ridings{stopped})"
    )


# --------------------------------------------------------------- intervene --


def _next_turn_id(turns_dir):
    existing = [
        int(path.name[:4])
        for path in turns_dir.glob("[0-9][0-9][0-9][0-9]_*.json")
    ]
    return max(existing, default=0) + 1


def cmd_intervene(args, summary):
    if not (args.payload or "").strip():
        raise CommandError("intervene needs a payload: the turn file, as JSON")
    try:
        data = json.loads(args.payload)
    except ValueError as exc:
        raise CommandError(f"payload is not valid JSON: {exc}") from exc

    operations = data.get("operations") or []
    used = {op.get("op") for op in operations if isinstance(op, dict)}
    forbidden = used - INTERVENTION_OPS
    if forbidden:
        raise CommandError(
            f"the console may not apply {', '.join(sorted(forbidden))}."
            f" Interventions are limited to {', '.join(sorted(INTERVENTION_OPS))},"
            " or a housekeeping turn with no operations at all."
        )

    turns_dir = scenario.turns_dir()
    turns_dir.mkdir(parents=True, exist_ok=True)

    conn = db.connect()
    season = conn.execute("SELECT MAX(season_no) AS n FROM seasons").fetchone()["n"] or 0
    turn_id = _next_turn_id(turns_dir)
    # The season is in the filename so scripts/rebuild.py can put the
    # intervention back exactly where it happened when it replays the game.
    path = turns_dir / f"{turn_id:04d}_s{season:04d}-intervention.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        _, loaded = load_turnfile(path)  # load returns (turn_id, data)
        warnings = validate_turnfile(conn, loaded)
        result = apply_turn(conn, path)
    except Exception as exc:
        # Any failure at all, not only a validation one: a turn file left behind
        # by a crash would be replayed by the next rebuild as though it had been
        # applied, and would renumber every turn after it.
        path.unlink(missing_ok=True)
        conn.close()
        if isinstance(exc, (TurnFileError, TurnError)):
            raise CommandError(str(exc)) from exc
        raise

    before = (0, 0)
    after = (
        conn.execute("SELECT COUNT(*) AS n FROM houses WHERE status = 'active'").fetchone()["n"],
        conn.execute(
            "SELECT COUNT(*) AS n FROM holdings WHERE released_event_id IS NULL"
        ).fetchone()["n"],
    )
    conn.close()

    summary.add(f"Applied `{path.relative_to(ROOT)}` as turn {result['turn_id']}.")
    summary.add("")
    summary.add(f"_{data.get('directive', '').strip()}_")
    summary.add("")
    for op in operations:
        detail = ", ".join(f"{k} {v}" for k, v in op.items() if k != "op")
        summary.add(f"- `{op.get('op')}` — {detail}")
    for warning in warnings:
        summary.add(f"- warning: {warning}")
    summary.add("")
    summary.add(f"The game stands at season {season}: {after[0]} houses, {after[1]} ridings held.")

    kinds = ", ".join(sorted(used)) or "housekeeping"
    return f"intervene: {kinds} after season {season}"


# ------------------------------------------------------------------- rules --


def cmd_rules(args, summary):
    from apply_rules_patch import PatchError, apply_patch

    if not (args.payload or "").strip():
        raise CommandError("rules needs a payload: the patch, as JSON")
    try:
        patch = json.loads(args.payload)
    except ValueError as exc:
        raise CommandError(f"payload is not valid JSON: {exc}") from exc

    try:
        version, applied = apply_patch(patch, args.note or "")
    except PatchError as exc:
        raise CommandError(str(exc)) from exc

    summary.add(f"Rules are now **{version}**.")
    summary.add("")
    summary.add("| field | from | to |")
    summary.add("|---|---|---|")
    for where, before, after in applied:
        summary.add(f"| `{where}` | {before} | {after} |")
    summary.add("")
    summary.add(
        "Seasons already played keep the version they were played under;"
        " this takes effect from the next season run."
    )
    return f"rules {version}: {len(applied)} value(s) tuned"


# ----------------------------------------------------------------- rebuild --


COMPARED_TABLES = (
    ("houses", "SELECT house, peerage, rank, status, primary_hex, secondary_hex FROM houses ORDER BY house"),
    ("house_stats", "SELECT house, capital, influence, cohesion, ambition, community, region,"
                    " tag, seat_place, founded_season, removed_season FROM house_stats ORDER BY house"),
    ("holdings", "SELECT house, fed_id, seat_order, hex FROM holdings"
                 " WHERE released_event_id IS NULL ORDER BY house, seat_order"),
    ("persons", "SELECT house, name, gender, age, role, alive, married FROM persons ORDER BY house, id"),
    ("objectives", "SELECT house, objective, acquired_season, satisfied_season FROM objectives"
                   " ORDER BY house, id"),
    ("seasons", "SELECT season_no, seed, houses_after, ridings_after FROM seasons ORDER BY season_no"),
    ("clocks", "SELECT house, personal_year FROM clocks ORDER BY house"),
)


def cmd_rebuild(args, summary):
    import rebuild as rebuild_script

    with tempfile.TemporaryDirectory(prefix="hoc-verify-") as workspace:
        verify_path = Path(workspace) / "verify.db"
        fresh = rebuild_script.rebuild(verify_path, export=False, verbose=False)
        committed = db.connect()

        differences = []
        for name, sql in COMPARED_TABLES:
            left = [tuple(row) for row in fresh.execute(sql)]
            right = [tuple(row) for row in committed.execute(sql)]
            if left != right:
                differences.append((name, len(left), len(right)))

        counts = (
            fresh.execute("SELECT COUNT(*) AS n FROM houses WHERE status = 'active'").fetchone()["n"],
            fresh.execute(
                "SELECT COUNT(*) AS n FROM holdings WHERE released_event_id IS NULL"
            ).fetchone()["n"],
        )
        fresh.close()
        committed.close()

    if differences:
        summary.add("The committed database does **not** match a rebuild from the record:")
        summary.add("")
        for name, left, right in differences:
            summary.add(f"- `{name}`: {left} row(s) rebuilt against {right} committed")
        raise CommandError(
            "hoc.db does not match a rebuild from the seed and the season logs."
            " Either it was edited by hand or a rules change altered how an old"
            " season replays — neither can be fixed by committing this run."
        )

    summary.add("The committed database reproduces exactly from the seed and the record.")
    summary.table(counts, counts)
    return f"rebuild: verified {counts[0]} houses, {counts[1]} ridings"


COMMANDS = {
    "run": cmd_run,
    "intervene": cmd_intervene,
    "rules": cmd_rules,
    "rebuild": cmd_rebuild,
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="engine_command", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--seasons", default="10")
    parser.add_argument("--stop-on", default="")
    parser.add_argument("--payload", default="")
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)

    summary = Summary(args.command, args.note)
    try:
        message = COMMANDS[args.command](args, summary)
    except CommandError as exc:
        summary.ok = False
        summary.add("")
        summary.add(f"**{exc}**")
        summary.add("")
        summary.add("Nothing was committed.")
        summary.write()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # a bug, not a refusal: say so and commit nothing
        summary.ok = False
        summary.add("")
        summary.add(f"**Unexpected failure:** `{type(exc).__name__}: {exc}`")
        summary.add("")
        summary.add("Nothing was committed.")
        summary.write()
        raise

    summary.ok = True
    summary.write()
    note = f" — {args.note.strip()}" if (args.note or "").strip() else ""
    print(COMMIT_PREFIX + message + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
