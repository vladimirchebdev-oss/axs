"""Validate proxies from env and/or config file. No browser, no AXS."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import get_settings  # noqa: E402
from proxies import ProxyPool, parse_protocols  # noqa: E402
from proxy_check import acquire_valid, validate_proxy  # noqa: E402


def _print_check(check) -> None:
    proxy = check.proxy
    print(f"\nsession={proxy.session_id} host={proxy.host} scheme={proxy.scheme}")
    print(f"ok={check.ok} ip={check.ip} country={check.country} city={check.city} tz={check.timezone}")
    if check.error:
        print(f"error={check.error}")
    for name, result in check.protocols.items():
        extra = result.ip or result.error or result.status
        print(f"  {name}: ok={result.ok} {extra}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate HTTP / HTTPS / SOCKS5 proxies before use"
    )
    parser.add_argument("--all", action="store_true", help="check every proxy")
    parser.add_argument(
        "--acquire",
        action="store_true",
        help="validate current, rotate in-process until one works",
    )
    parser.add_argument("--protocols", default="http,https,socks5")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()

    settings = get_settings()
    pool = ProxyPool.from_settings(settings, ROOT)
    protocols = parse_protocols(args.protocols)

    print(f"loaded proxies: {len(pool)} (env and/or PROXY_FILE)")
    print(f"protocols: {', '.join(protocols)}")

    if args.acquire:
        check = acquire_valid(
            pool,
            timeout=args.timeout,
            protocols=protocols,
        )
        _print_check(check)
        return 0 if check.ok else 1

    items = list(pool) if args.all else [pool.current()]
    failed = 0
    for proxy in items:
        check = validate_proxy(
            proxy,
            settings,
            timeout=args.timeout,
            protocols=protocols,
        )
        _print_check(check)
        if not check.ok:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
