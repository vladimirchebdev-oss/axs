"""Простой HTTP GET к страницам AXS — без браузера, чтобы увидеть сырой ответ."""

import ssl
import urllib.request

URLS = [
    "https://shop.axs.com/?c=axs&e=6414022407626854",
    "https://shop.axs.com/?c=axs&e=4436620017755968",
]

PREVIEW = 1500


def probe(url: str) -> None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    ctx = ssl.create_default_context()

    print("=" * 72)
    print(f"URL: {url}\n")

    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            body = resp.read()
            print(f"status: {resp.status}")
            print(f"final url: {resp.geturl()}")
            print("headers:")
            for key, value in resp.headers.items():
                print(f"  {key}: {value}")
            print(f"\nbody bytes: {len(body)}")
            print(f"body empty: {len(body) == 0}")
            print(f"\n--- preview ({min(PREVIEW, len(body))} bytes) ---")
            print(body[:PREVIEW].decode("utf-8", errors="replace"))
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}")
        if hasattr(exc, "code"):
            print(f"http code: {exc.code}")
        if hasattr(exc, "headers") and exc.headers:
            print("headers:")
            for key, value in exc.headers.items():
                print(f"  {key}: {value}")
        body = getattr(exc, "read", lambda: b"")()
        if body:
            print(f"\nbody bytes: {len(body)}")
            print(f"body empty: {len(body) == 0}")
            print(f"\n--- preview ---")
            print(body[:PREVIEW].decode("utf-8", errors="replace"))
        else:
            print("body empty: True (нет тела ответа)")
    print()


if __name__ == "__main__":
    for url in URLS:
        probe(url)
