"""CI helper: print pytest's first failure block (or a timeout's stack dump) as one GitHub annotation.

    uv run python scripts/ci_failure_annotation.py pytest.log
"""

import re
import sys
from pathlib import Path

LIMIT = 12_000  # characters kept from the failure block


def first_failure(log: str) -> str:
    lines = log.splitlines()
    heads = [i for i, ln in enumerate(lines) if re.match(r"^_{3,} .+ _{3,}$", ln)]
    if heads:
        end = heads[1] if len(heads) > 1 else len(lines)
        return "\n".join(lines[heads[0]:end])
    timeout = [i for i, ln in enumerate(lines) if "Timeout" in ln and "+++" in ln]
    if timeout:
        return "\n".join(lines[timeout[0]:timeout[0] + 120])
    return "\n".join(lines[-80:])


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main() -> int:
    log = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    block = first_failure(log)
    if len(block) > LIMIT:
        block = block[:LIMIT // 2] + "\n...\n" + block[-LIMIT // 2:]
    print(f"::error title=first failure::{escape(block)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
