"""Command line entry point.

    python -m hoc apply scenarios/legacy/turns/0001_slug.json
    python -m hoc export                       regenerate outputs/ from hoc.db
    python -m hoc status                       compact summary of the state
    python -m hoc check <house> <riding>       test an expansion, changing nothing
    python -m hoc scenario list                which games exist, and which is active
    python -m hoc scenario use <name>          switch the active scenario
"""

import argparse
import sys

from hoc import db, rules, scenario as scenario_mod
from hoc.export import dump, map as map_export, site, workbook
from hoc.turn import TurnError, apply_turn


def _export_all(conn, out_dir=None):
    kwargs = {} if out_dir is None else {"out_dir": out_dir}
    written = list(dump.write_dump(conn, **kwargs))
    written.append(workbook.write_workbook(conn, **kwargs))
    written.extend(map_export.write_maps(conn, **kwargs))
    site_files = site.write_site(conn, **kwargs)
    written.append(site_files[0].parent)  # the site is many files; report the directory
    return written


def cmd_apply(args):
    conn = db.connect(args.db)
    try:
        summary = apply_turn(conn, args.turnfile)
    except TurnError as exc:
        where = "" if exc.operation_index is None else f" (operation {exc.operation_index})"
        print(f"turn not applied{where}: {exc.reason}", file=sys.stderr)
        return 1

    for warning in summary["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)

    print(f"applied turn {summary['turn_id']} as event {summary['event_id']}")
    print(f"  operations: {summary['ops_applied']}")
    print(f"  holdings:   {summary['holdings']}")
    for cohort, value in sorted(summary["climate"].items()):
        print(f"  climate [{cohort}]: {value}")

    for path in _export_all(conn):
        print(f"  wrote {path}")
    conn.close()
    return 0


def cmd_export(args):
    conn = db.connect(args.db)
    for path in _export_all(conn):
        print(f"wrote {path}")
    conn.close()
    return 0


def cmd_status(args):
    conn = db.connect(args.db)
    counts = conn.execute(
        "SELECT (SELECT COUNT(*) FROM houses WHERE status = 'active') AS active,"
        "       (SELECT COUNT(*) FROM houses WHERE status = 'removed') AS removed,"
        "       (SELECT COUNT(*) FROM ridings) AS ridings,"
        "       (SELECT COUNT(*) FROM holdings WHERE released_event_id IS NULL) AS claimed,"
        "       (SELECT COUNT(*) FROM holders WHERE is_current = 1 AND name IS NULL) AS unrecovered"
    ).fetchone()

    print(f"houses:  {counts['active']} active, {counts['removed']} removed")
    print(f"ridings: {counts['claimed']} claimed of {counts['ridings']}")
    print("climate:")
    for row in conn.execute("SELECT * FROM v_current_climate ORDER BY era_cohort"):
        print(f"  {row['era_cohort']}: {row['cumulative_after']}")

    print("last events:")
    events = conn.execute(
        "SELECT id, kind, title, turn_id FROM events ORDER BY id DESC LIMIT 5"
    ).fetchall()
    if not events:
        print("  (none)")
    for row in events:
        turn = "" if row["turn_id"] is None else f" [turn {row['turn_id']}]"
        print(f"  {row['id']:>4} {row['kind']:<10} {row['title']}{turn}")

    print(f"holders with no recovered name: {counts['unrecovered']}")
    conn.close()
    return 0


def cmd_check(args):
    conn = db.connect(args.db)
    try:
        check = rules.validate_expansion(conn, args.house, args.riding)
    except rules.RuleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    verdict = "OK" if check.ok else "REJECTED"
    print(f"{verdict}: {args.house} -> {args.riding}")
    print(f"  fed_id: {check.fed_id}")
    print(f"  reason: {check.reason}")
    if check.warning:
        print(f"  warning: {check.warning}")
    conn.close()
    return 0 if check.ok else 1


def cmd_scenario(args):
    if args.scenario_command == "list":
        active = scenario_mod.current_name()
        for name in scenario_mod.scenario_names():
            manifest = scenario_mod.read_manifest(name)
            marker = "*" if name == active else " "
            kind = manifest.get("kind", "unknown")
            seed = manifest.get("seed")
            seed_text = "no seed yet" if seed is None else f"seed {seed}"
            print(f" {marker} {name:<8} {kind:<9} {seed_text}")
        print("\n* is the scenario hoc.db is built from (scenarios/current.txt)")
        return 0

    try:
        scenario_mod.set_current(args.name)
    except scenario_mod.ScenarioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"active scenario is now {args.name!r}")
    print("run `python scripts/rebuild.py` to rebuild hoc.db from it")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m hoc", description=__doc__)
    parser.add_argument("--db", default=str(db.DEFAULT_DB_PATH), help="path to hoc.db")
    sub = parser.add_subparsers(dest="command", required=True)

    apply_parser = sub.add_parser("apply", help="apply a turn file, then export")
    apply_parser.add_argument("turnfile")
    apply_parser.set_defaults(func=cmd_apply)

    export_parser = sub.add_parser("export", help="regenerate outputs/ from hoc.db")
    export_parser.set_defaults(func=cmd_export)

    status_parser = sub.add_parser("status", help="compact summary of the current state")
    status_parser.set_defaults(func=cmd_status)

    check_parser = sub.add_parser("check", help="test an expansion without changing anything")
    check_parser.add_argument("house")
    check_parser.add_argument("riding")
    check_parser.set_defaults(func=cmd_check)

    scenario_parser = sub.add_parser("scenario", help="list or switch the active scenario")
    scenario_sub = scenario_parser.add_subparsers(dest="scenario_command", required=True)
    scenario_sub.add_parser("list", help="show every scenario and which is active")
    use_parser = scenario_sub.add_parser("use", help="make a scenario active")
    use_parser.add_argument("name")
    scenario_parser.set_defaults(func=cmd_scenario)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
