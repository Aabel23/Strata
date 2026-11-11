"""The Claude models, effort levels and permission modes Strata offers for Claude Code (`claude --model ... --effort ...`).

One list for every picker (AI chat and task agents). An alias ("opus") follows the newest
version of its family; a full id ("claude-opus-5-5") pins one version. "" means Claude Code's
own default. Each model lists the effort levels it accepts; "" (default) is always allowed.
"""
from __future__ import annotations

ALL_EFFORTS = ("low", "medium", "high", "xhigh", "max")
NO_XHIGH = ("low", "medium", "high", "max")

# (id, label, hint)
EFFORTS = (
    ("", "Default effort", "Claude Code's default for the model"),
    ("low", "Low effort", "Fast, fewer tool calls; simple tasks"),
    ("medium", "Medium effort", "Balanced"),
    ("high", "High effort", "Thorough"),
    ("xhigh", "Extra high effort", "Best for most coding and agent work"),
    ("max", "Max effort", "Slowest, most thorough; when correctness matters most"),
)

# (id, label, family, efforts)
MODELS = (
    ("", "Default model", "Latest", ALL_EFFORTS),
    ("fable", "Fable latest", "Latest", ALL_EFFORTS),
    ("opus", "Opus latest", "Latest", ALL_EFFORTS),
    ("sonnet", "Sonnet latest", "Latest", ALL_EFFORTS),
    ("haiku", "Haiku latest", "Latest", ALL_EFFORTS),
    ("claude-fable-5-2", "Fable 5.2", "Fable", ALL_EFFORTS),
    ("claude-fable-5-1", "Fable 5.1", "Fable", ALL_EFFORTS),
    ("claude-fable-5", "Fable 5", "Fable", ALL_EFFORTS),
    ("claude-opus-5-5", "Opus 5.5", "Opus", ALL_EFFORTS),
    ("claude-opus-5", "Opus 5", "Opus", ALL_EFFORTS),
    ("claude-opus-4-8", "Opus 4.8", "Opus", ALL_EFFORTS),
    ("claude-opus-4-7", "Opus 4.7", "Opus", ALL_EFFORTS),
    ("claude-opus-4-6", "Opus 4.6", "Opus", NO_XHIGH),
    ("claude-sonnet-5-5", "Sonnet 5.5", "Sonnet", ALL_EFFORTS),
    ("claude-sonnet-5", "Sonnet 5", "Sonnet", ALL_EFFORTS),
    ("claude-sonnet-4-6", "Sonnet 4.6", "Sonnet", NO_XHIGH),
    ("claude-haiku-5-5", "Haiku 5.5", "Haiku", ALL_EFFORTS),
    ("claude-haiku-4-5", "Haiku 4.5", "Haiku", ()),
)

# Claude Code permission modes the chat offers. Every action Claude Code still asks about reaches the viewer
# for Allow/Deny. bypassPermissions (never asks) and dontAsk (denies anything not pre-allowed) are left out.
# (id, label, hint)
PERMISSIONS = (
    ("auto", "Auto", "Claude runs safe actions itself and asks you when unsure"),
    ("manual", "Ask", "Claude asks before every action"),
    ("acceptEdits", "Accept edits", "File edits go through; commands still ask"),
    ("plan", "Plan", "Claude reads and plans, makes no changes"),
)
DEFAULT_PERMISSION = "auto"

MODEL_IDS = tuple(m[0] for m in MODELS)
PERMISSION_IDS = tuple(p[0] for p in PERMISSIONS)
EFFORT_IDS = tuple(e[0] for e in EFFORTS)
_LATEST = {"fable": "Fable 5.2", "opus": "Opus 5.5", "sonnet": "Sonnet 5.5", "haiku": "Haiku 5.5"}
_BY_ID = {m[0]: m for m in MODELS}


def effort_ok(model: str, effort: str) -> bool:
    """True when `model` is offered and accepts `effort` ("" always works)."""
    return model in _BY_ID and effort in EFFORT_IDS and (effort == "" or effort in _BY_ID[model][3])


def catalog() -> dict:
    """The picker data the viewer renders: models grouped by family, effort levels, which model takes which effort."""
    def hint(i):
        if i in _LATEST:
            return f"Follows the newest version, now {_LATEST[i]}"
        return "Claude Code's default model" if not i else f"Pinned: {i}"
    return {"models": [{"id": i, "label": label, "group": group, "efforts": list(efforts), "hint": hint(i)}
                       for i, label, group, efforts in MODELS],
            "efforts": [{"id": i, "label": label, "hint": h} for i, label, h in EFFORTS]}


def chat_catalog() -> dict:
    """The chat panel also picks a permission mode."""
    return {**catalog(), "permissions": [{"id": i, "label": label, "hint": h} for i, label, h in PERMISSIONS], "permission": DEFAULT_PERMISSION}
