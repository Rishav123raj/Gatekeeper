"""`uv run python -m worker`. Placeholder until Phase 2: prints the clock once a minute."""

import time

from gatekeeper.clock import PHASE_LABELS, fmt_dual, load_session_times, market_day, now_ny, session_phase
from gatekeeper.settings import get_settings


def main() -> None:
    settings = get_settings()
    print("Gatekeeper worker (placeholder until Phase 2). Ctrl+C to stop.", flush=True)
    try:
        while True:
            now = now_ny()
            phase = session_phase(now, load_session_times(settings.trader_path), market_day(now.date()))
            print(f"{fmt_dual(now)}  {PHASE_LABELS[phase]}", flush=True)
            time.sleep(60)
    except KeyboardInterrupt:
        print("Worker stopped.")


if __name__ == "__main__":
    main()
