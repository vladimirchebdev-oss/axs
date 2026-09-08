"""Долгоживущий сервис: ротация прокси без рестарта контейнера.

  GET  /
  GET  /style.css
  GET  /health
  GET  /status
  GET  /shot/<file>
  POST /rotate
  POST /rotate?dir=prev
  POST /reload
  POST /check?protocols=http,https,socks5
  POST /open
  POST /open?url=https://shop.axs.com/...
  POST /open?ip_check=1
  POST /open?protocol=http|https|socks5
  POST /stop
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import nodriver as uc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import get_settings  # noqa: E402
from proxies import PROTOCOLS, Protocol, ProxyPool  # noqa: E402
from proxy_check import validate_proxy  # noqa: E402
from runner import (  # noqa: E402
    browser_alive,
    goto_page,
    last_dead_reason,
    open_page,
    proxy_info,
    stop_current,
    watch_live_session,
)

LOOP: asyncio.AbstractEventLoop | None = None
BUSY = threading.Lock()
JOB: asyncio.Future | None = None


def _settings_pool():
    settings = get_settings()
    return settings, ProxyPool.from_settings(settings, ROOT)


SETTINGS, POOL = _settings_pool()


def _call(coro, timeout: float = 180):
    if LOOP is None:
        raise RuntimeError("event loop is not running")
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)


def _protocols(raw: str) -> tuple[Protocol, ...]:
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    unknown = [item for item in items if item not in PROTOCOLS]
    if unknown:
        raise ValueError(f"unknown protocol(s): {unknown}")
    return items or PROTOCOLS


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"http {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._bytes(code, body, "application/json; charset=utf-8")

    def _bytes(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _web_asset(self, name: str, content_type: str) -> None:
        safe = Path(name).name
        if safe != name or safe in {".", ".."}:
            self._send(400, {"ok": False, "error": "bad filename"})
            return
        path = ROOT / "web" / safe
        if not path.is_file():
            self._send(404, {"ok": False, "error": "not found"})
            return
        self._bytes(200, path.read_bytes(), content_type)

    def _ui(self) -> None:
        self._web_asset("index.html", "text/html; charset=utf-8")

    def _shot(self, name: str) -> None:
        safe = Path(name).name
        if safe != name or safe in {".", ".."}:
            self._send(400, {"ok": False, "error": "bad filename"})
            return
        path = SETTINGS.relpath("SCREENSHOTS_DIR") / safe
        if not path.is_file():
            self._send(404, {"ok": False, "error": "screenshot not found"})
            return
        self._bytes(200, path.read_bytes(), "image/png")

    def _query(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        return {key: values[-1] for key, values in parse_qs(parsed.query).items()}

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._ui()
            return
        if path == "/style.css":
            self._web_asset("style.css", "text/css; charset=utf-8")
            return
        if path == "/health":
            self._send(200, {"ok": True})
            return
        if path == "/status":
            self._send(
                200,
                {
                    "ok": True,
                    "browser_alive": browser_alive(),
                    "dead_reason": last_dead_reason(),
                    "vnc": (SETTINGS.opt("VNC") or "1").lower()
                    in {"1", "true", "yes", "on"},
                    **proxy_info(POOL),
                },
            )
            return
        if path.startswith("/shot/"):
            self._shot(unquote(path[len("/shot/") :]))
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        global JOB
        path = urlparse(self.path).path
        query = self._query()
        try:
            if path == "/rotate":
                closed = False
                if browser_alive():
                    stop_current()
                    closed = True
                direction = (query.get("dir") or "next").lower()
                steps = -1 if direction in {"prev", "back", "previous"} else 1
                POOL.rotate(steps)
                self._send(
                    200,
                    {
                        "ok": True,
                        "action": "rotate",
                        "dir": "prev" if steps < 0 else "next",
                        "chrome_closed": closed,
                        **proxy_info(POOL),
                    },
                )
                return
            if path == "/reload":
                count = POOL.reload()
                self._send(
                    200,
                    {"ok": True, "action": "reload", "loaded": count, **proxy_info(POOL)},
                )
                return
            if path == "/check":
                protocols = _protocols(query.get("protocols", "http,https,socks5"))
                check = validate_proxy(
                    POOL.current(), SETTINGS, protocols=protocols
                )
                self._send(
                    200 if check.ok else 502,
                    {
                        "ok": check.ok,
                        "ip": check.ip,
                        "country": check.country,
                        "city": check.city,
                        "timezone": check.timezone,
                        "error": check.error,
                        "protocols": {
                            name: {"ok": item.ok, "ip": item.ip, "error": item.error}
                            for name, item in check.protocols.items()
                        },
                        **proxy_info(POOL),
                    },
                )
                return
            if path == "/stop":
                stopped = stop_current()
                if JOB is not None and not JOB.done():
                    JOB.cancel()
                self._send(200, {"ok": True, "action": "stop", "stopped": stopped})
                return
            if path == "/open":
                if not BUSY.acquire(blocking=False):
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                try:
                    url = query.get("url") or (
                        SETTINGS.need("CHECK_URL")
                        if query.get("ip_check") in {"1", "true", "yes"}
                        else SETTINGS.need("PAGE_URL")
                    )
                    if LOOP is None:
                        raise RuntimeError("event loop is not running")
                    ip_check = query.get("ip_check") in {"1", "true", "yes"}
                    if browser_alive():
                        JOB = asyncio.run_coroutine_threadsafe(
                            goto_page(POOL, SETTINGS, url=url, ip_check=ip_check),
                            LOOP,
                        )
                    else:
                        JOB = asyncio.run_coroutine_threadsafe(
                            open_page(
                                POOL,
                                SETTINGS,
                                url=url,
                                ip_check=ip_check,
                                protocol=query.get("protocol") or "http",
                            ),
                            LOOP,
                        )
                    try:
                        result = JOB.result(timeout=180)
                    except (asyncio.CancelledError, concurrent.futures.CancelledError):
                        self._send(200, {"ok": True, "state": "stopped"})
                        return
                    self._send(200, result)
                finally:
                    JOB = None
                    BUSY.release()
                return
        except Exception as exc:
            self._send(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._send(404, {"ok": False, "error": "not found"})


def main() -> None:
    global LOOP
    host = SETTINGS.opt("SERVICE_HOST") or "0.0.0.0"
    port = int(SETTINGS.opt("SERVICE_PORT") or "8080")
    server = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"service on http://{host}:{port}  proxies={len(POOL)}", flush=True)
    print(
        "POST /rotate  POST /reload  POST /check  POST /open  POST /stop  GET /status",
        flush=True,
    )
    LOOP = uc.loop()
    LOOP.create_task(watch_live_session(SETTINGS))
    try:
        LOOP.run_forever()
    except KeyboardInterrupt:
        print("stop", flush=True)
    finally:
        server.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
