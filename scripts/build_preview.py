"""Play the draft rules and publish the game at outputs/site/preview/.

    python scripts/build_preview.py [out_dir]

    outputs/site/preview/replay.html       the preview told one turn at a time
    outputs/site/preview/storylines.html   its storylines
    outputs/site/preview/reckoning.html    its reckoning, for a game that ends in one
    outputs/site/preview-hex/              the same, played on the hex board

docs/STORY_DESIGN.md Phase C2, and D1. While a draft rules version exists
(rules/README.md, "A draft version": the one directory newer than
rules/current.txt), every export plays it from seed `SEED` on a scratch world
built from the blank seed and the `REFERENCE` reference set — the whole game when
the draft has a world calendar (rules 1.0 `world_calendar`: 1867 to 1966, with
its chapters and its reckoning), else `SEASONS` seasons — and renders the game
with the archive's Replay and Storylines pages, and its Reckoning. It is not a scenario: it is written to a
temporary database and thrown away, it writes no season file, nothing under
scenarios/ and nothing in hoc.db, and every page says it is a draft-rules preview
and not a game of record. Because it is played afresh on every export, it changes
exactly when the draft (or the engine) does. With no draft, preview/ is removed.
"""

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc import rules_data, scenario, sim  # noqa: E402  (after sys.path setup)
from hoc.export import beats as beats_export, site  # noqa: E402

SEED = 1867
SEASONS = 100
REFERENCE = "meridian-v1.0.3"
# The hex board (docs/hex-trial/v2/README.md): the same draft and seed played
# on the hex board, published beside the riding preview at preview-hex/.
HEX_REFERENCE = "meridian-hex-v1.0.5"


def play_preview(db_path, version, seed=SEED, seasons=SEASONS, records=None, reference=REFERENCE):
    """A scratch world, played `seasons` seasons under `version`. Returns the
    open connection. Each season's record is appended to `records`, if given:
    the preview writes no season file, and the exporter reads the records'
    `order` (rules 1.0 `round_record`) from them."""
    import load_seed

    conn = load_seed.build(db_path, seed=scenario.blank_seed_dir(), reference_data=reference)
    world = sim.World(conn, rules=rules_data.load_rules(version=version), world_seed=seed)
    kept = records if records is not None else []
    with conn:
        kept.append(world.initialise(seed))
        for _ in range(seasons - 1):
            kept.append(world.run_season())
    return conn


def preview_length(version):
    """The draft's whole game under a world calendar, else SEASONS."""
    rules = rules_data.load_rules(version=version)
    if rules.feature("world_calendar") and rules.game:
        return rules.game["turns"]
    return SEASONS


def build_preview(out_dir=site.DEFAULT_OUT_DIR, verbose=False):
    """Render the preview, or remove it when there is no draft. Returns the
    paths written."""
    version = rules_data.draft_version()
    boards = ((site.PREVIEW_DIRNAME, REFERENCE), (site.HEX_PREVIEW_DIRNAME, HEX_REFERENCE))
    if version is None:
        for dirname, _ in boards:
            shutil.rmtree(Path(out_dir) / site.SITE_DIRNAME / dirname, ignore_errors=True)
        if verbose:
            print("preview: no draft rules version; preview/ and preview-hex/ removed")
        return []
    written = []
    seasons = preview_length(version)
    for dirname, reference in boards:
        with tempfile.TemporaryDirectory(prefix="hoc-preview-") as workspace:
            records = []
            conn = play_preview(Path(workspace) / "preview.db", version, seasons=seasons,
                                records=records, reference=reference)
            files = site.write_preview(conn, version, out_dir=out_dir, seed=SEED, seasons=seasons,
                                       orders=beats_export.orders_from_records(records),
                                       dirname=dirname)
            conn.close()
        written.extend(files)
        if verbose:
            print(f"{dirname}: {seasons} turns under rules {version} (draft) on {reference},"
                  f" {len(files)} files")
    return written


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else site.DEFAULT_OUT_DIR
    build_preview(out_dir, verbose=True)
    print(f"wrote {Path(out_dir) / site.SITE_DIRNAME / site.PREVIEW_DIRNAME} and"
          f" {site.HEX_PREVIEW_DIRNAME}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
