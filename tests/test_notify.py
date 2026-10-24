"""Notifications, with fake transports: nothing is really sent."""

import json
import sys
import types

import httpx
import pytest

from gatekeeper import notify
from gatekeeper.settings import get_settings


def settings(**kw):
    return get_settings().model_copy(update=kw)


@pytest.mark.parametrize(
    ("rule_id", "message", "urgent"),
    [
        ("tsla-plan-stop", "TSLA 358.10 at or below 358.32", True),
        ("tsla-flat-by", "Flat by close: it is 15:56 New York", True),
        ("my-time", "Flat by close: it is 12:56", True),
        ("tsla-plan-target", "TSLA 370.10 at or above 370.04", False),
        ("ko-move", "KO moved 3.1 %", False),
    ],
)
def test_urgency(rule_id, message, urgent):
    assert notify.is_urgent(rule_id, message) is urgent


def test_none_sends_nothing():
    assert notify.notify("t", "b", settings=settings(notify="none")) is False


def telegram_client(calls, status=200):
    def handler(req):
        calls.append((str(req.url), json.loads(req.content)))
        return httpx.Response(status, json={"ok": status == 200})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_telegram_message():
    calls = []
    s = settings(notify="telegram", telegram_bot_token="123:abc", telegram_chat_id="42")
    ok = notify.notify(
        "Gatekeeper: TSLA", "Flat by close", urgent=True, settings=s, client=telegram_client(calls)
    )
    assert ok is True
    (url, payload) = calls[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert payload["chat_id"] == "42" and payload["text"] == "🚨 Gatekeeper: TSLA\nFlat by close"


def test_telegram_needs_token_and_chat():
    calls = []
    s = settings(notify="telegram", telegram_bot_token="", telegram_chat_id="42")
    assert notify.notify("t", "b", settings=s, client=telegram_client(calls)) is False
    assert calls == []


def test_telegram_http_error_is_false_not_raised():
    s = settings(notify="telegram", telegram_bot_token="1:x", telegram_chat_id="42")
    assert notify.notify("t", "b", settings=s, client=telegram_client([], status=401)) is False


def test_telegram_network_error_is_false_not_raised():
    def handler(req):
        raise httpx.ConnectError("offline")

    s = settings(notify="telegram", telegram_bot_token="1:x", telegram_chat_id="42")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert notify.notify("t", "b", settings=s, client=client) is False


def test_toast(monkeypatch):
    shown = []
    fake = types.ModuleType("win11toast")
    fake.notify = lambda title, body, **kw: shown.append((title, body, kw))
    monkeypatch.setitem(sys.modules, "win11toast", fake)
    assert notify.notify("Gatekeeper: TSLA", "stop", urgent=True, settings=settings(notify="toast")) is True
    assert shown == [("Gatekeeper: TSLA", "stop", {"duration": "long"})]  # non-blocking notify()


def test_toast_without_the_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "win11toast", None)  # makes the import fail
    assert notify.notify("t", "b", settings=settings(notify="toast")) is False
