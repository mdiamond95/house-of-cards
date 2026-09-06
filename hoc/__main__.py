"""Command line entry point.

    python -m hoc apply scenarios/legacy/turns/0001_slug.json
    python -m hoc export                       regenerate outputs/ from hoc.db
    python -m hoc status                       compact summary of the state
    python -m hoc check <house> <riding>       test an expansion, changing nothing
    python -m hoc scenario list                which games exist, and which is active
    python -m hoc scenario use <name>          switch the active scenario
    python -m hoc sim new --seed N             start the autoplay game at season 1
    python -m hoc sim run N                    play N seasons
    python -m hoc sim status                   where the autoplay game stands
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

    # The archive is rebuilt on every export, from its own scenario, so the
    # frozen playthrough and the live game can never drift apart.
    written.append(_build_archive(**kwargs))
    return written


def _build_archive(out_dir=None):
    sys.path.insert(0, str(db.PACKAGE_ROOT.parent / "scripts"))
    import build_archive

    files = build_archive.build_archive(**({} if out_dir is None else {"out_dir": out_dir}))
    return files[0].parent


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


def _open_world(conn, seed=None):
    from hoc import scenario as scen, sim

    return sim.World(conn, world_seed=seed, seasons_dir=scen.seasons_dir())


def cmd_sim(args):
    from hoc import scenario as scen, sim

    active = scen.current_name()
    conn = db.connect(args.db)

    if args.sim_command == "new":
        if active != "new":
            print(
                f"error: the active scenario is {active!r}; run"
                " `python -m hoc scenario use new` first",
                file=sys.stderr,
            )
            return 1
        if conn.execute("SELECT COUNT(*) AS n FROM seasons").fetchone()["n"]:
            print(
                "error: this world has already started; rebuild it from an empty"
                " seed before founding season 1 again",
                file=sys.stderr,
            )
            return 1
        world = _open_world(conn, seed=args.seed)
        with conn:
            record = world.initialise(args.seed, seat=args.seat)
        manifest = scen.read_manifest()
        manifest.update({"seed": args.seed, "started_season": 1})
        scen.write_manifest(manifest)
        for line in record["chronicle"]:
            print(line)
        print(f"world seeded {args.seed}; season 1 played")
        _export_all(conn)
        conn.close()
        return 0

    if args.sim_command == "run":
        try:
            world = _open_world(conn)
        except sim.SimError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        stop_on = tuple(s.strip() for s in (args.stop_on or "").split(",") if s.strip())
        with conn:
            records = world.run(args.count, stop_on=stop_on)
        for record in records:
            for line in record["chronicle"]:
                print(line)
        last = records[-1] if records else None
        if last:
            print(
                f"\nplayed {len(records)} season(s) to season {last['season']}:"
                f" {last['houses_after']} houses, {last['ridings_after']} ridings held"
            )
            if last.get("stopped_on"):
                print(f"stopped on: {', '.join(last['stopped_on'])}")
        _export_all(conn)
        conn.close()
        return 0

    # status
    row = conn.execute(
        "SELECT season_no, seed, houses_after, ridings_after, rules_version"
        " FROM seasons ORDER BY season_no DESC LIMIT 1"
    ).fetchone()
    print(f"scenario: {active}")
    if row is None:
        print("no seasons played")
        conn.close()
        return 0
    print(f"season:   {row['season_no']} (seed {row['seed']}, rules {row['rules_version']})")
    print(f"houses:   {row['houses_after']} active")
    print(f"ridings:  {row['ridings_after']} of 343 held")
    print("climate:")
    for climate in conn.execute("SELECT * FROM v_current_climate ORDER BY era_cohort"):
        print(f"  {climate['era_cohort']}: {climate['cumulative_after']}")
    conn.close()
    return 0


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

    sim_parser = sub.add_parser("sim", help="the autoplay engine")
    sim_sub = sim_parser.add_subparsers(dest="sim_command", required=True)
    new_parser = sim_sub.add_parser("new", help="found season 1 of the autoplay game")
    new_parser.add_argument("--seed", type=int, required=True)
    new_parser.add_argument("--seat", help="riding for the first house (default: drawn)")
    run_parser = sim_sub.add_parser("run", help="play N seasons")
    run_parser.add_argument("count", type=int)
    run_parser.add_argument(
        "--stop-on",
        help="comma-separated pause conditions: removal, challenge, major, marquis",
    )
    sim_sub.add_parser("status", help="where the autoplay game stands")
    sim_parser.set_defaults(func=cmd_sim)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
