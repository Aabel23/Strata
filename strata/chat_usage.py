"""Small, bounded account-usage snapshot for the chat composer."""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import threading
import time
from typing import Any

from strata.chat_claude import _child_env as claude_env, _claude_executable
from strata.chat_codex import CodexSession
from strata.chat_antigravity import child_env as antigravity_env

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _percent(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100:
        return round(value)
    return None


def _claude() -> dict[str, Any]:
    cmd = [_claude_executable(os.environ), "-p", "/usage", "--output-format", "json"]
    done = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=15, env=claude_env())
    if done.returncode:
        raise ValueError("usage command failed")
    report = json.loads(done.stdout).get("result", "")
    short = re.search(r"^Current session:\s*(\d{1,3})% used", report, re.M)
    week = re.search(r"^Current week \(all models\):\s*(\d{1,3})% used", report, re.M)
    return {"short": _percent(int(short.group(1))) if short else None,
            "week": _percent(int(week.group(1))) if week else None,
            "short_label": "5h"}


def _codex() -> dict[str, Any]:
    session = CodexSession(pathlib.Path.cwd())
    try:
        session._launch()
        result = session._rpc("account/rateLimits/read", {})
        limits = result.get("rateLimits", {}) if isinstance(result, dict) else {}
        primary, secondary = limits.get("primary") or {}, limits.get("secondary") or {}
        return {"short": _percent(primary.get("usedPercent")),
                "week": _percent(secondary.get("usedPercent")),
                "short_label": f"{primary.get('windowDurationMins', 300)//60}h"}
    finally:
        session.close()


def _antigravity() -> dict[str, Any]:
    done = subprocess.run(["agy", "-p", "/usage"], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=15, env=antigravity_env())
    if done.returncode:
        raise ValueError("usage command failed")
    # The CLI reports one or more model-group weekly *remaining* percentages.
    remaining = [int(x) for x in re.findall(r"Weekly Limit Remaining\s+(\d{1,3})%", done.stdout)]
    return {"short": None, "week": _percent(100 - min(remaining)) if remaining else None,
            "short_label": "5h"}


def usage_status(provider: str) -> dict[str, Any]:
    if provider not in ("claude", "codex", "antigravity", "openrouter", "omniroute"):
        raise ValueError("invalid provider")
    with _lock:
        previous = _cache.get(provider)
        if previous and time.monotonic() - previous[0] < 90:
            return dict(previous[1])
    try:
        values = {"claude": _claude, "codex": _codex, "antigravity": _antigravity}.get(provider)
        data = values() if values else {"short": None, "week": None, "short_label": "5h"}
    except Exception:
        data = {"short": None, "week": None, "short_label": "5h"}
    result = {"provider": provider, **data}
    with _lock:
        _cache[provider] = (time.monotonic(), result)
    return result
