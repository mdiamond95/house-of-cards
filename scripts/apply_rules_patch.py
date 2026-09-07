"""Apply a numeric patch to the rules tables, bump the version, log the change.

    python scripts/apply_rules_patch.py '<json>' "the director's note"

The patch is a JSON object of file → dotted path → new value:

    {"friction.json": {"flashpoint.threshold": 55},
     "actions.csv": {"Dispute.base_weight": 2.5}}

Only numbers may change. A patch that would add a key, remove one, change a
string, or reach a file outside `rules/` is refused before anything is written —
the console is a dial, not an editor, and a rule whose *shape* changes is a
design decision that belongs in a Code session with a CHANGELOG entry written by
hand.

On success the rules version is bumped and `rules/CHANGELOG.md` gains an entry
carrying the director's note and every value that moved.
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ROOT / "rules"
CHANGELOG = RULES_DIR / "CHANGELOG.md"

# Which CSV columns hold numbers a director may turn. Everything else in those
# files is prose or a name, and changing it here would be an edit, not a tuning.
CSV_NUMERIC_COLUMNS = {
    "actions.csv": ("base_weight", "target", "enclosure_bonus"),
    "objectives.csv": (),
    "mortality.csv": ("age_min", "age_max", "annual_probability_pct"),
}

VERSION_PATTERN = re.compile(r"^## (\d+)\.(\d+)", re.MULTILINE)


class PatchError(Exception):
    """A patch that will not be applied."""


def current_version():
    """The highest version in the changelog, as (major, minor)."""
    versions = [
        (int(major), int(minor))
        for major, minor in VERSION_PATTERN.findall(CHANGELOG.read_text(encoding="utf-8"))
    ]
    if not versions:
        raise PatchError("rules/CHANGELOG.md records no version")
    return max(versions)


def next_version():
    major, minor = current_version()
    return f"{major}.{minor + 1}"


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _resolve_file(filename):
    path = (RULES_DIR / filename).resolve()
    if path.parent != RULES_DIR.resolve():
        raise PatchError(f"{filename!r} is outside rules/")
    if not path.exists():
        raise PatchError(f"rules/{filename} does not exist")
    return path


def _patch_json(path, changes):
    """Set dotted paths in a JSON file. Returns [(path, before, after)]."""
    data = json.loads(path.read_text(encoding="utf-8"))
    applied = []

    for dotted, new in sorted(changes.items()):
        if not _is_number(new):
            raise PatchError(f"{path.name}: {dotted} must be set to a number, got {new!r}")

        node = data
        parts = dotted.split(".")
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                raise PatchError(f"{path.name}: no such key {dotted!r}")
            node = node[part]
        leaf = parts[-1]
        if not isinstance(node, dict) or leaf not in node:
            raise PatchError(f"{path.name}: no such key {dotted!r}")

        before = node[leaf]
        if not _is_number(before):
            raise PatchError(
                f"{path.name}: {dotted} currently holds {before!r}, which is not a number;"
                " only numeric fields can be tuned here"
            )
        node[leaf] = new
        applied.append((f"{path.name}:{dotted}", before, new))

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return applied


def _patch_csv(path, changes):
    """Set `<row key>.<column>` in a CSV. The row key is the first column."""
    allowed = CSV_NUMERIC_COLUMNS.get(path.name)
    if allowed is None:
        raise PatchError(f"{path.name}: this file has no tunable numeric columns")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    key_column = fieldnames[0]

    applied = []
    for dotted, new in sorted(changes.items()):
        if not _is_number(new):
            raise PatchError(f"{path.name}: {dotted} must be set to a number, got {new!r}")
        row_key, _, column = dotted.rpartition(".")
        if column not in allowed:
            raise PatchError(
                f"{path.name}: column {column!r} is not tunable;"
                f" tunable columns are {', '.join(allowed) or 'none'}"
            )
        target = next((row for row in rows if row[key_column] == row_key), None)
        if target is None:
            raise PatchError(f"{path.name}: no row named {row_key!r}")

        before = target[column]
        try:
            float(before)
        except (TypeError, ValueError):
            raise PatchError(
                f"{path.name}: {dotted} currently holds {before!r}, which is not a number"
            )
        rendered = str(int(new)) if float(new).is_integer() else str(new)
        target[column] = rendered
        applied.append((f"{path.name}:{dotted}", before, rendered))

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return applied


def apply_patch(patch, note, dry_run=False):
    """Apply a whole patch. Returns (version, [(path, before, after)])."""
    if not isinstance(patch, dict) or not patch:
        raise PatchError("patch must be a non-empty object of file -> changes")
    if not (note or "").strip():
        raise PatchError("a rules change needs a note saying why")

    originals = {}
    applied = []
    try:
        for filename, changes in sorted(patch.items()):
            path = _resolve_file(filename)
            if not isinstance(changes, dict) or not changes:
                raise PatchError(f"{filename}: changes must be a non-empty object")
            originals[path] = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                applied.extend(_patch_json(path, changes))
            elif path.suffix == ".csv":
                applied.extend(_patch_csv(path, changes))
            else:
                raise PatchError(f"{filename}: only .json and .csv rules files can be patched")
    except Exception:
        for path, text in originals.items():  # all or nothing, like a turn
            path.write_text(text, encoding="utf-8")
        raise

    version = next_version()
    if dry_run:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")
        return version, applied

    _append_changelog(version, note, applied)
    return version, applied


def _append_changelog(version, note, applied):
    lines = [
        "",
        f"## {version} — tuned from the console",
        "",
        f"{note.strip()}",
        "",
        "| field | from | to |",
        "|---|---|---|",
    ]
    lines.extend(f"| `{where}` | {before} | {after} |" for where, before, after in applied)
    lines.append("")
    lines.append(
        "Applied by the engine workflow. Every value here is a number that was"
        " already in the table; the console cannot add, remove or rename a rule."
    )
    with open(CHANGELOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        patch = json.loads(sys.argv[1])
    except ValueError as exc:
        print(f"error: patch is not valid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        version, applied = apply_patch(patch, sys.argv[2])
    except PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"rules {version}")
    for where, before, after in applied:
        print(f"  {where}: {before} -> {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
