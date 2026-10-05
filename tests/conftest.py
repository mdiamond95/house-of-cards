"""Shared fixtures.

`live_game` makes the repository's second scenario read as live for the length
of a module. The game in `scenarios/new` is frozen (it finished at season 150),
but a large part of this suite exercises the machinery that plays and saves a
game — the play page, the console, the referee — against it, and that machinery
refuses a frozen scenario by design. Rather than rewrite every such test around a
scratch scenarios directory, the manifest is patched in memory: nothing on disk
changes, and the tests that prove the refusal (tests/test_frozen.py) do not use it.

Module-scoped on purpose, so that a module's own module-scoped fixtures (a site
exported once and read by many tests) are built with the patch in place.
"""

import pytest

from hoc import scenario


@pytest.fixture(scope="module")
def live_game():
    real = scenario.read_manifest

    def read_manifest(name=None, root=None):
        manifest = dict(real(name, root))
        if (name or scenario.current_name(root)) == "new":
            manifest["status"] = scenario.STATUS_LIVE
        return manifest

    patch = pytest.MonkeyPatch()
    patch.setattr(scenario, "read_manifest", read_manifest)
    yield "new"
    patch.undo()
