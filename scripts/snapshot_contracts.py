"""Save every skill's JSON output on the recorded replay day to tests/contracts/.

Run after upgrading the pinned skills, then review the diff:

    uv run python scripts/snapshot_contracts.py
    git diff tests/contracts
"""

import json
import sys
import tempfile
from pathlib import Path

from gatekeeper.contracts import generate
from gatekeeper.settings import ROOT, get_settings


def main() -> int:
    dest = ROOT / "tests" / "contracts"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gatekeeper-contracts-") as tmp:
        try:
            contracts = generate(Path(tmp), get_settings().skills_path)
        except RuntimeError as e:
            print(f"snapshot failed: {e}", file=sys.stderr)
            return 1
    for name, data in contracts.items():
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        (dest / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote tests/contracts/{name}.json")
    print(f"{len(contracts)} contracts saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
