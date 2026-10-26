import pathlib
import re


def test_chat_layout_has_hidden_default_drawers_responsive_scrolling_and_focus():
    css = (pathlib.Path(__file__).resolve().parents[1] / "viewer" / "app.css").read_text()
    assert "body.chat-open #chat-panel:not([hidden]){display:grid}" in css
    assert "#chat-panel[hidden]" in css and "display:none!important" in css
    assert "@media (max-width:1023px)" in css and "@media (max-width:767px)" in css
    assert "body.agent-expanded{--agent-bar-height:210px}" in css
    assert "body.agent-expanded{--agent-bar-height:190px}" in css
    assert css.count("inset:0 0 var(--agent-bar-height)") == 2
    for selector in ("#chat-events", "#chat-review-details", "#chat-diff", "#chat-approval"):
        match = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
        assert match and "overflow:auto" in match.group(1)
    assert "#chat-panel button:focus-visible" in css
    assert "@media (prefers-reduced-motion:reduce)" in css
    assert "body.agent-expanded #agent-bar" in css
