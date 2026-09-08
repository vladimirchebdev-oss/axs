"""Rotate / reload proxies without restarting the Python process."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import get_settings  # noqa: E402
from proxies import ProxyPool  # noqa: E402
from proxy_check import acquire_valid  # noqa: E402


def _show(pool: ProxyPool, check) -> None:
    proxy = pool.current()
    print(
        f"[{pool.index + 1}/{len(pool)}] session={proxy.session_id} "
        f"ok={check.ok} ip={check.ip} country={check.country}"
    )


def main() -> int:
    settings = get_settings()
    pool = ProxyPool.from_settings(settings, ROOT)

    print(f"loaded {len(pool)} proxies. commands: enter=rotate, r=reload file, q=quit")
    check = acquire_valid(pool)
    _show(pool, check)

    while True:
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if cmd in {"q", "quit", "exit"}:
            return 0
        if cmd in {"r", "reload"}:
            count = pool.reload()
            print(f"reloaded {count} from file/env, process still running")
            continue
        pool.rotate()
        check = acquire_valid(pool)
        _show(pool, check)


if __name__ == "__main__":
    raise SystemExit(main())
