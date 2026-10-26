import html.parser
import pathlib


class Markup(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.labels = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids
            self.ids.add(attrs["id"])
        if tag == "label":
            self.labels.add(attrs.get("for"))
        if tag == "a":
            self.links.append(attrs)


def test_chat_shell_exposes_accessible_controls_for_client_binding():
    source = pathlib.Path(__file__).resolve().parents[1] / "viewer" / "app.html"
    parser = Markup()
    parser.feed(source.read_text())
    required_ids = {
        "chat-toggle", "chat-panel", "chat-provider", "chat-model", "chat-auth-state",
        "chat-login-area", "chat-login-link", "chat-new-session", "chat-events",
        "chat-approval", "chat-approval-details", "chat-diff-status", "chat-diff",
        "chat-message", "chat-send", "chat-cancel", "chat-close-session",
        "agent-bar", "agent-bar-toggle", "agent-session-cards", "agent-session-count",
    }
    assert required_ids <= parser.ids
    assert {"chat-provider", "chat-model", "chat-message"} <= parser.labels
    login_links = [link for link in parser.links if link.get("id") == "chat-login-link"]
    assert len(login_links) == 1 and login_links[0].get("rel") == "noopener noreferrer"
    markup = source.read_text()
    assert "No active agent sessions" in markup
    assert 'aria-live="polite"' in markup and 'role="log"' in markup
