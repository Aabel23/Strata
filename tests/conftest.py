import os, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "tests/fixtures/c4_layered"   # layered C4 folder: 5 objects, 5 links, 3 contracts, 1 behavior, 1 flow


def run(dbp, *args):
    r = subprocess.run([sys.executable, str(ROOT / "strata.py"), *args], capture_output=True, text=True,
                       env={**os.environ, "STRATA_DB": str(dbp)})
    return r.returncode, r.stdout


@pytest.fixture
def dbp(tmp_path): return tmp_path / "t.db"
