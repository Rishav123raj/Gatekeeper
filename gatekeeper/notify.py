"""Notifications for fired alerts: a Windows toast or a Telegram message (NOTIFY in .env).

    NOTIFY=none       nothing is sent (the default)
    NOTIFY=toast      a Windows notification (needs: uv sync --extra notify)
    NOTIFY=telegram   a message from your bot (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

A notification is information only: it never places, cancels or changes an order. A failed
notification is logged and reported as False, never raised, so it can't stop the worker.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from gatekeeper.settings import Settings, get_settings

log = logging.getLogger("gatekeeper.notify")

TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_urgent(rule_id: str, message: str = "") -> bool:
    """Stop and flat-by alerts are urgent: they mean something has to be done now."""
    rid, msg = rule_id.lower(), message.lower()
    return "stop" in rid or "flat-by" in rid or msg.startswith("flat by")


def _toast(title: str, body: str, urgent: bool) -> bool:
    # win11toast.notify shows the toast and returns at once (its toast() waits for a click or a
    # dismissal, which would hold up the worker). The default app id is used: Windows can silently
    # drop toasts from an unregistered one. The title says "Gatekeeper".
    try:
        from win11toast import notify as show
    except ImportError:
        log.warning("NOTIFY=toast but win11toast isn't installed: uv sync --extra notify")
        return False
    show(title, body, duration="long" if urgent else "short")
    return True


def _telegram(title: str, body: str, urgent: bool, s: Settings, client: httpx.Client | None) -> bool:
    if not (s.telegram_bot_token and s.telegram_chat_id):
        log.warning("NOTIFY=telegram but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID aren't set")
        return False
    text = f"{'🚨 ' if urgent else ''}{title}\n{body}"
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        r = client.post(TELEGRAM_URL.format(token=s.telegram_bot_token),
                        json={"chat_id": s.telegram_chat_id, "text": text, "disable_web_page_preview": True})
        if r.status_code != 200:
            log.warning("telegram answered HTTP %s", r.status_code)  # never log the token
            return False
        return True
    finally:
        if own:
            client.close()


def notify(
    title: str,
    body: str,
    *,
    urgent: bool = False,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> bool:
    """Sends one notification on the configured channel. True when it was handed over."""
    s = settings or get_settings()
    try:
        if s.notify == "toast":
            return _toast(title, body, urgent)
        if s.notify == "telegram":
            return _telegram(title, body, urgent, s, client)
    except Exception as e:  # a notification must never take the worker down
        log.warning("notification failed (%s): %s", s.notify, type(e).__name__)
        return False
    return False


Notifier = Callable[..., bool]
