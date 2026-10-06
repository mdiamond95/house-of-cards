"""Play the draft rules and publish the game at outputs/site/preview/.

    python scripts/build_preview.py [out_dir]

    outputs/site/preview/replay.html       the preview told one turn at a time
    outputs/site/preview/storylines.html   its storylines

docs/STORY_DESIGN.md Phase C2. While a draft rules version exists (rules/README.md,
"A draft version": the one directory newer than rules/current.txt), every export
plays `SEASONS` seasons of it from seed `SEED` on a scratch world built from the
blank seed and the `REFERENCE` reference set, and renders the game with the
archive's Replay and Storylines pages. It is not a scenario: it is written to a
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
from hoc.export import site  # noqa: E402

SEED = 1867
SEASONS = 100
REFERENCE = "meridian-v1.0.3"


def play_preview(db_path, version, seed=SEED, seasons=SEASONS):
    """A scratch world, played `seasons` seasons under `version`. Returns the
    open connection."""
    import load_seed

    conn = load_seed.build(db_path, seed=scenario.blank_seed_dir(), reference_data=REFERENCE)
    world = sim.World(conn, rules=rules_data.load_rules(version=version), world_seed=seed)
    with conn:
        world.initialise(seed)
        for _ in range(seasons - 1):
            world.run_season()
    return conn


def build_preview(out_dir=site.DEFAULT_OUT_DIR, verbose=False):
    """Render the preview, or remove it when there is no draft. Returns the
    paths written."""
    version = rules_data.draft_version()
    preview_dir = Path(out_dir) / site.SITE_DIRNAME / site.PREVIEW_DIRNAME
    if version is None:
        shutil.rmtree(preview_dir, ignore_errors=True)
        if verbose:
            print("preview: no draft rules version; preview/ removed")
        return []
    with tempfile.TemporaryDirectory(prefix="hoc-preview-") as workspace:
        conn = play_preview(Path(workspace) / "preview.db", version)
        written = site.write_preview(conn, version, out_dir=out_dir, seed=SEED, seasons=SEASONS)
        conn.close()
    if verbose:
        print(f"preview: {SEASONS} seasons under rules {version} (draft), {len(written)} files")
    return written


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else site.DEFAULT_OUT_DIR
    build_preview(out_dir, verbose=True)
    print(f"wrote {Path(out_dir) / site.SITE_DIRNAME / site.PREVIEW_DIRNAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
