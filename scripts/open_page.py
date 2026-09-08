"""Открыть страницу в Chrome через NoDriver.

  python scripts/open_page.py --ip-check
  python scripts/open_page.py --rotate 7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nodriver as uc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import get_settings  # noqa: E402
from proxies import ProxyPool  # noqa: E402
from runner import open_page  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ip-check",
        action="store_true",
        help="open CHECK_URL instead of AXS (verify proxy inside Chrome)",
    )
    parser.add_argument("--url", default="")
    parser.add_argument(
        "--rotate",
        type=int,
        default=0,
        help="skip N proxies first (use after an IP was already blocked)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.url:
        url = args.url
    elif args.ip_check:
        url = settings.need("CHECK_URL")
    else:
        url = settings.need("PAGE_URL")

    pool = ProxyPool.from_settings(settings, ROOT)
    for _ in range(args.rotate):
        pool.rotate()
    await open_page(pool, settings, url=url, ip_check=args.ip_check)
    return 0


if __name__ == "__main__":
    try:
        uc.loop().run_until_complete(main())
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
