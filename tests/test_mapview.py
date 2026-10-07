"""The map view (docs/STORY_DESIGN.md §3.6, Phases V and V2) in a real browser.

Builds the draft-rules preview into a scratch directory, serves it, and runs
tests/js/mapview.e2e.mjs against it at 390 x 844, 820 x 1180 and 1440 x 900:
Next walks a year's world, each house and the close in order, and the strip
follows; Next year stops at the close; a chip and a row of the standings open
a house's sheet; Auto stops on a pause-weight turn; follow mode frames a turn
between the top bar and the docked card; the houses' names never overlap; a
crisis tints its camps; a chapter's close is opaque; a drag, a pinch and a
double tap (the wheel on a desktop) move the map; a mark's card opens and
closes; and no page logs an error. Skipped where node or Playwright is not
installed (the CI runner has neither browser nor Playwright; a Code session
has both).
"""

import functools
import http.server
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def _playwright_available():
    if NODE is None:
        return False
    probe = subprocess.run(
        [NODE, "-e", (
            "const {createRequire}=require('node:module');"
            "const {execSync}=require('node:child_process');"
            "let ok=false;"
            "for (const b of [process.cwd()+'/', (()=>{try{return execSync('npm root -g',{encoding:'utf8'}).trim()+'/'}catch(e){return null}})()]) {"
            " if(!b) continue; try{createRequire(b)('playwright');ok=true;break}catch(e){} }"
            "process.exit(ok?0:1)"
        )],
        cwd=ROOT, capture_output=True,
    )
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(not _playwright_available(), reason="node or Playwright is not installed")


@pytest.fixture(scope="module")
def served_preview(tmp_path_factory):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_preview
    from hoc.export import site

    out = tmp_path_factory.mktemp("mapview")
    assert build_preview.build_preview(out_dir=out)
    root = out / site.SITE_DIRNAME
    handler = functools.partial(_Quiet, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/{site.PREVIEW_DIRNAME}"
    finally:
        server.shutdown()


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def test_the_map_view_works_on_a_phone_an_ipad_and_a_desktop(served_preview):
    result = subprocess.run(
        [NODE, str(ROOT / "tests" / "js" / "mapview.e2e.mjs"), served_preview],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    assert lines, f"no report: {result.stdout[-2000:]} {result.stderr[-2000:]}"
    report = json.loads(lines[-1])
    if report.get("ok") is None:
        pytest.skip(report.get("skipped", "playwright unavailable"))
    assert report["ok"], report["failures"]
    assert report["checks"] >= 100
    assert report["errors"] == []
