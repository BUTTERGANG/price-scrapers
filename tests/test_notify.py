"""Tests for utils/notify.py — Telegram notification plumbing.

No real Telegram calls: requests.post is monkeypatched throughout.
"""
import json

import pytest

from utils import notify as notify_mod
from utils.db import acknowledge_alert, add_watchlist_item, check_price_alerts


@pytest.fixture
def notify_file(tmp_path, monkeypatch):
    """Point config/notify.json at a temp file and clear env chat IDs."""
    path = tmp_path / "notify.json"
    monkeypatch.setattr(notify_mod, "NOTIFY_PATH", path)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    return path


class _FakeResponse:
    def __init__(self, ok=True, status_code=200, text="ok"):
        self.ok = ok
        self.status_code = status_code
        self.text = text


def test_chat_ids_from_env(notify_file, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111, 222,")
    assert notify_mod.chat_ids() == ["111", "222"]


def test_chat_ids_env_and_file_deduplicated(notify_file, monkeypatch):
    notify_file.write_text(json.dumps({"chat_ids": ["222", "333"]}))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111,222")
    assert notify_mod.chat_ids() == ["111", "222", "333"]


def test_chat_ids_missing_or_corrupt_file(notify_file):
    assert notify_mod.chat_ids() == []
    notify_file.write_text("{not json")
    assert notify_mod.chat_ids() == []


def test_register_chat(notify_file):
    assert notify_mod.register_chat(12345) is True
    assert notify_mod.register_chat("12345") is False  # already registered
    assert json.loads(notify_file.read_text()) == {"chat_ids": ["12345"]}
    assert notify_mod.chat_ids() == ["12345"]


def test_notify_noop_without_token(notify_file, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")

    def _boom(*a, **kw):
        raise AssertionError("must not hit the network without a token")

    monkeypatch.setattr(notify_mod.requests, "post", _boom)
    assert notify_mod.notify("hi") == 0


def test_notify_noop_without_chats(notify_file, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t0k3n")
    monkeypatch.setattr(
        notify_mod.requests, "post",
        lambda *a, **kw: pytest.fail("must not send with no chat IDs"),
    )
    assert notify_mod.notify("hi") == 0


def test_notify_sends_to_each_chat(notify_file, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t0k3n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111,222")
    calls = []

    def _post(url, json=None, timeout=None):
        calls.append((url, json))
        return _FakeResponse()

    monkeypatch.setattr(notify_mod.requests, "post", _post)
    assert notify_mod.notify("price drop!") == 2
    assert all("t0k3n/sendMessage" in url for url, _ in calls)
    assert [c[1]["chat_id"] for c in calls] == ["111", "222"]
    assert all(c[1]["text"] == "price drop!" for c in calls)


def test_notify_swallows_network_errors(notify_file, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t0k3n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111,222")

    def _post(url, json=None, timeout=None):
        if json["chat_id"] == "111":
            raise notify_mod.requests.ConnectionError("boom")
        return _FakeResponse()

    monkeypatch.setattr(notify_mod.requests, "post", _post)
    assert notify_mod.notify("hi") == 1  # second chat still delivered


def test_notify_counts_only_ok_responses(notify_file, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t0k3n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    monkeypatch.setattr(
        notify_mod.requests, "post",
        lambda *a, **kw: _FakeResponse(ok=False, status_code=403, text="forbidden"),
    )
    assert notify_mod.notify("hi") == 0


# ---------------------------------------------------------------------------
# check_price_alerts dedup — a sale persisting across 6h scrapes must not
# re-alert until the previous alert is acknowledged.
# ---------------------------------------------------------------------------

def test_price_alert_dedup(db_conn):
    add_watchlist_item(db_conn, "kroger", "p1", name="Milk", target_price=3.00)

    first = check_price_alerts(db_conn, "kroger", "p1", 2.50, name="Milk")
    assert first is not None
    assert float(first["triggered_price"]) == 2.50

    # Same sale seen on the next scrape → suppressed
    assert check_price_alerts(db_conn, "kroger", "p1", 2.50, name="Milk") is None
    assert check_price_alerts(db_conn, "kroger", "p1", 2.40, name="Milk") is None

    # Once acknowledged, a later qualifying price alerts again
    assert acknowledge_alert(db_conn, first["alert_id"]) is True
    again = check_price_alerts(db_conn, "kroger", "p1", 2.75, name="Milk")
    assert again is not None
    assert float(again["triggered_price"]) == 2.75


def test_price_alert_not_triggered_above_target(db_conn):
    add_watchlist_item(db_conn, "kroger", "p2", name="Eggs", target_price=2.00)
    assert check_price_alerts(db_conn, "kroger", "p2", 2.50, name="Eggs") is None
