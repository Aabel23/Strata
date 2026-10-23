"""Classic scripts share one global scope: a duplicate top-level name blanks the viewer."""
import re
from collections import defaultdict
from pathlib import Path

V = Path(__file__).resolve().parent.parent / "viewer"
DECL = re.compile(r"^(?:async +)?(?:const|let|var|function\*?|class) +([A-Za-z_$][\w$]*)", re.M)


def test_no_duplicate_toplevel_names_across_scripts():
    for page in ("app.html", "page.html"):
        seen = defaultdict(list)
        for src in re.findall(r'<script src="/([^"]+)"', (V / page).read_text()):
            f = V / src
            if "vendor" in src or not f.exists():
                continue
            for n in DECL.findall(f.read_text()):
                seen[n].append(src)
        dups = {n: s for n, s in seen.items() if len(s) > 1}
        assert not dups, f"{page}: {dups}"
