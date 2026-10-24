"""No wording in the dashboard or the Go / No-Go engine says "buy" or "sell" as advice.

"buy" / "sell" may only appear inside a phrase that says what something is NOT (or in the
skills' own order tickets, which describe an order, not advice). Any new use fails here.
"""

import re

from gatekeeper.settings import ROOT

FILES = [
    *sorted((ROOT / "app").rglob("*.py")),
    ROOT / "gatekeeper" / "readiness.py",
    ROOT / "gatekeeper" / "regime.py",
    ROOT / "gatekeeper" / "lab.py",
]
ALLOWED = ["not a buy list", 'GO never means "buy"']
WORD = re.compile(r"\b(buy|buys|buying|sell|sells|selling)\b", re.IGNORECASE)


def test_no_buy_or_sell_advice():
    offenders = []
    for path in FILES:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            cleaned = line
            for ok in ALLOWED:
                cleaned = cleaned.replace(ok, "")
            if WORD.search(cleaned):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert offenders == []


def test_the_check_would_catch_advice():
    assert WORD.search("GO: buy now")
    assert not WORD.search("not a buy list".replace("not a buy list", ""))
