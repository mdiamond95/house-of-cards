"""Every generated script has to parse, in the one place that matters: a real
JavaScript engine.

The console shipped for a while with an unparseable script (a Python
triple-quoted string swallowed a `\\n` meant to reach the browser literally, so
`node --check` failed with "Invalid regular expression: missing /") and nothing
in the suite caught it, because nothing had ever asked a JS engine to look at
the generated JS. `hoc/export/site.py`'s templates read as valid JavaScript to
a human; only `node --check` (or a browser) proves they parse.

This covers every `.js` file the exporter writes and every inline `<script>`
block on every generated page, across three sites: the legacy build, a
played-world site (the only one with the scrubber, the season chronicle and the
console — none of which the legacy site renders), and the archive.
"""

import shutil
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402

from hoc import scenario, sim  # noqa: E402
from hoc.export import site  # noqa: E402

NODE = shutil.which("node")


class _ScriptCollector(HTMLParser):
    """Every inline <script> block's text, in document order. A <script
    src="..."> tag has no text to collect and is not this class's concern —
    the .js files it points at are gathered separately, by path."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._capturing = False
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not any(name == "src" for name, _ in attrs):
            self._capturing = True
            self._buffer = []

    def handle_endtag(self, tag):
        if tag == "script" and self._capturing:
            self.blocks.append("".join(self._buffer))
            self._capturing = False

    def handle_data(self, data):
        if self._capturing:
            self._buffer.append(data)


def inline_scripts(html_path):
    collector = _ScriptCollector()
    collector.feed(html_path.read_text(encoding="utf-8"))
    return collector.blocks


def check_node_syntax(tmp_path, label, source):
    """Write `source` to a scratch .js file and run `node --check` on it.
    Raises an AssertionError naming `label` and node's stderr on failure."""
    scratch = tmp_path / "syntax-check.js"
    scratch.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [NODE, "--check", str(scratch)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"{label} does not parse as JavaScript:\n{result.stderr}"
    )


def assert_site_scripts_parse(tmp_path, site_dir, label):
    js_files = sorted(site_dir.rglob("*.js"))
    assert js_files, f"{label}: no .js files were found under {site_dir}"
    for path in js_files:
        check_node_syntax(
            tmp_path, f"{label}: {path.relative_to(site_dir)}", path.read_text(encoding="utf-8")
        )

    html_files = sorted(site_dir.rglob("*.html"))
    assert html_files, f"{label}: no .html files were found under {site_dir}"
    checked_any_inline = False
    for path in html_files:
        for index, block in enumerate(inline_scripts(path)):
            checked_any_inline = True
            check_node_syntax(
                tmp_path,
                f"{label}: inline <script> #{index} in {path.relative_to(site_dir)}",
                block,
            )
    # Not asserted as a requirement — the site currently has no inline scripts,
    # only src= references — but recorded so a future inline script is known to
    # have been exercised rather than silently skipped by an empty loop.
    return checked_any_inline


@pytest.fixture(scope="module")
def legacy_site(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("legacy")
    conn = load_seed.build(tmp / "legacy.db", seed=scenario.seed_dir("legacy"))
    site.write_site(conn, out_dir=tmp)
    conn.close()
    return tmp / site.SITE_DIRNAME


@pytest.fixture(scope="module")
def played_site(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("played")
    conn = load_seed.build(tmp / "played.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=1867)
    world.initialise(1867)
    for _ in range(9):
        world.run_season()
    site.write_site(conn, out_dir=tmp)
    conn.close()
    return tmp / site.SITE_DIRNAME


@pytest.fixture(scope="module")
def archive_site(tmp_path_factory):
    import build_archive

    tmp = tmp_path_factory.mktemp("archive")
    build_archive.build_archive(out_dir=tmp)
    return tmp / site.SITE_DIRNAME / site.ARCHIVE_DIRNAME


def test_node_is_available_in_this_session():
    """Not a real test of the code — a loud, explicit record of whether the
    rest of this file could run at all, so a green suite with node missing
    never reads the same as a green suite that actually checked the JS."""
    if NODE is None:
        pytest.skip(
            "node was not found on PATH in this session, so generated JavaScript"
            " could not be syntax-checked here. This must not be read as the"
            " scripts having been verified — see the engine workflow, which runs"
            " on GitHub's ubuntu runners where node is preinstalled."
        )


@pytest.mark.skipif(NODE is None, reason="node is not available in this session")
def test_legacy_site_scripts_parse(tmp_path, legacy_site):
    assert_site_scripts_parse(tmp_path, legacy_site, "legacy")


@pytest.mark.skipif(NODE is None, reason="node is not available in this session")
def test_played_world_site_scripts_parse(tmp_path, played_site):
    """The one that would have caught the bug: the played-world site is the
    only fixture that renders console.js at all."""
    assert (played_site / "console.js").exists(), "a played world must render the console"
    assert_site_scripts_parse(tmp_path, played_site, "played world")


@pytest.mark.skipif(NODE is None, reason="node is not available in this session")
def test_archive_site_scripts_parse(tmp_path, archive_site):
    assert_site_scripts_parse(tmp_path, archive_site, "archive")


@pytest.mark.skipif(NODE is None, reason="node is not available in this session")
def test_console_js_regression_the_rules_regex_and_diff_join_parse(tmp_path, played_site):
    """Pinned directly to the bug: a JSON.parse(atob(...).replace(/\\n/g, ''))
    call and a diff.join('\\n') call, both of which broke when a Python
    triple-quoted (non-raw) string turned their \\n into a real newline
    character before the file was ever written."""
    console_js = (played_site / "console.js").read_text(encoding="utf-8")
    assert r"replace(/\n/g, '')" in console_js
    assert r"diff.join('\n')" in console_js
    check_node_syntax(tmp_path, "console.js", console_js)


# --------------------------------------------------- the hand-written engine --
#
# Everything above checks JavaScript this repo *generates*. web/engine/ is
# JavaScript this repo *is*: the second implementation of the game engine
# (Phase 10-1). tests/test_js_engine_parity.py exercises it far harder than a
# syntax check by actually running it, but that only reaches the modules
# selftest.js imports — this catches a file that parses nowhere because nothing
# loads it yet.

ENGINE_DIR = Path(__file__).resolve().parent.parent / "web" / "engine"


@pytest.mark.skipif(NODE is None, reason="node is not available in this session")
def test_the_javascript_engine_modules_parse():
    modules = sorted(ENGINE_DIR.glob("*.js")) if ENGINE_DIR.exists() else []
    assert modules, "web/engine/ holds no .js files"
    for module in modules:
        result = subprocess.run(
            [NODE, "--check", str(module)], capture_output=True, text=True
        )
        assert result.returncode == 0, f"{module.name} does not parse:\n{result.stderr}"


@pytest.mark.skipif(NODE is None, reason="node is not available in this session")
def test_the_javascript_engine_uses_no_dependencies():
    """web/engine/ is plain ES modules with no build step and no packages: it
    has to load from a static site by <script type="module"> alone. An import
    of anything but a relative path or a node: builtin would break that."""
    for module in sorted(ENGINE_DIR.glob("*.js")):
        source = module.read_text(encoding="utf-8")
        for match in re.finditer(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]""",
                                 source, re.MULTILINE | re.DOTALL):
            target = match.group(1)
            assert target.startswith(".") or target.startswith("node:"), (
                f"{module.name} imports {target!r}: web/engine must stay dependency-free"
            )
        assert "require(" not in source, f"{module.name} uses require(); this is ES modules only"
