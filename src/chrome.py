"""Запуск Google Chrome через NoDriver.

Словарь NoDriver ↔ Playwright (вы уже знаете Playwright):

  uc.start()                 ≈  chromium.launch()
  Browser                    ≈  Browser
  Tab                        ≈  Page
  browser.get(url)           ≈  page.goto() на первой вкладке
  browser.create_context()   ≈  browser.new_context() + новая вкладка
  tab.evaluate(...)          ≈  page.evaluate(...)
  tab.save_screenshot(...)   ≈  page.screenshot(path=...)
  tab.sleep(n)               ≈  page.wait_for_timeout(n * 1000)
  await tab                  ≈  «подождать DOM» (специфика NoDriver)
  uc.loop()                  ≈  свой event loop; не asyncio.run()

Прокси с логином Chrome сам в --proxy-server не умеет. NoDriver поднимает
локальный forwarder и отдаёт контексту http://127.0.0.1:порт.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from pathlib import Path
from urllib.parse import urlsplit

import nodriver as uc

from proxies import Protocol, Proxy
from user_agent import UaProfile, client_hints

# AXS после shop часто уходит на tix.axs.com — permission нужен и там.
_AXS_ORIGINS = (
    "https://shop.axs.com",
    "https://tix.axs.com",
    "https://www.axs.com",
)


def page_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def session_profile(base: Path, proxy: Proxy | None) -> Path:
    name = (proxy.session_id if proxy and proxy.session_id else "default")
    return base / name


async def start_chrome(
    *,
    chrome_path: Path,
    profile_dir: Path,
    headless: bool,
    lang: str,
    window_size: str,
    proxy: Proxy | None = None,
    timezone: str | None = None,
    locale: str | None = None,
    proxy_protocol: Protocol = "http",
) -> uc.Browser:
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        f"--window-size={window_size}",
        "--start-maximized",
        # WebRTC иначе может отдать домашний IP.
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        # Не качать webstore/update через прокси — там сыпятся 504.
        "--disable-component-update",
    ]
    forwarder = None
    if proxy:
        # Chrome не умеет user:pass в --proxy-server. Forwarder — локальный
        # http://127.0.0.1:порт без логина, дальше сам ходит в IPRoyal.
        upstream = "socks5" if proxy_protocol == "socks5" else "http"
        forwarder = uc.util.ProxyForwarder(proxy_server=proxy.url(upstream))
        await asyncio.sleep(0.5)
        args.append(f"--proxy-server={forwarder.proxy_server}")
    # В Docker не root — sandbox включён, без жёлтой плашки --no-sandbox.
    sandbox = True
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        sandbox = False
    # Настоящий TZ процесса, не CDP Emulation: Turnstile ловит подмену.
    if sys.platform.startswith("linux") and timezone:
        os.environ["TZ"] = timezone
    if locale:
        loc = locale.replace("-", "_")
        os.environ["LANG"] = f"{loc}.UTF-8"
        os.environ["LANGUAGE"] = loc
    config = _ChromeConfig(
        user_data_dir=str(profile_dir),
        headless=headless,
        browser_executable_path=str(chrome_path),
        browser_args=args,
        sandbox=sandbox,
        lang=lang,
    )
    browser = await uc.start(config)
    browser._proxy_forwarder = forwarder
    return browser


class _ChromeConfig(uc.Config):
    """Меньше дефолтных флагов NoDriver: они сами по себе fingerprint."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        skip = {
            "--disable-infobars",
            "--disable-breakpad",
            "--disable-dev-shm-usage",
            "--no-pings",
            "--homepage=about:blank",
        }
        self._default_browser_args = [
            item for item in self._default_browser_args if item not in skip
        ]

    def __call__(self):
        args = super().__call__()
        features: list[str] = []
        cleaned: list[str] = []
        for arg in args:
            if arg.startswith("--disable-features="):
                for feat in arg.split("=", 1)[1].split(","):
                    if feat and feat not in features and feat not in {
                        "IsolateOrigins",
                        "site-per-process",
                    }:
                        features.append(feat)
                continue
            cleaned.append(arg)
        if "Translate" not in features:
            features.append("Translate")
        cleaned.append("--disable-features=" + ",".join(features))
        return cleaned


def _origins_for(url: str) -> list[str]:
    origin = page_origin(url) if url.startswith("http") else ""
    if not origin:
        return []
    if "axs.com" in origin:
        seen = []
        for item in (origin, *_AXS_ORIGINS):
            if item not in seen:
                seen.append(item)
        return seen
    return [origin]


async def match_proxy_geo(
    browser: uc.Browser,
    tab: uc.Tab,
    *,
    timezone: str | None,
    locale: str | None,
    loc: tuple[float, float] | None,
    origins: list[str],
) -> None:
    """GPS как у IP. Timezone/locale на Linux уже в env Chrome — CDP не трогаем."""
    emulate = not sys.platform.startswith("linux")
    if emulate and timezone:
        await tab.send(uc.cdp.emulation.set_timezone_override(timezone))
    if emulate and locale:
        await tab.send(uc.cdp.emulation.set_locale_override(locale.replace("-", "_")))
    if loc:
        latitude, longitude = loc
        await tab.send(
            uc.cdp.emulation.set_geolocation_override(
                latitude=latitude,
                longitude=longitude,
                accuracy=100,
            )
        )
    perms = [
        uc.cdp.browser.PermissionType.GEOLOCATION,
        uc.cdp.browser.PermissionType.NOTIFICATIONS,
        uc.cdp.browser.PermissionType.SENSORS,
    ]
    for origin in origins:
        await browser.send(
            uc.cdp.browser.grant_permissions(permissions=perms, origin=origin)
        )


async def apply_user_agent(tab: uc.Tab, profile: UaProfile, locale: str | None) -> None:
    lang = f"{locale},en;q=0.9" if locale else "en-US,en;q=0.9"
    await tab.send(
        uc.cdp.emulation.set_user_agent_override(
            user_agent=profile.user_agent,
            accept_language=lang,
            platform=profile.platform,
            user_agent_metadata=client_hints(profile),
        )
    )


async def open_url(
    browser: uc.Browser,
    url: str,
    *,
    timezone: str | None = None,
    locale: str | None = None,
    loc: tuple[float, float] | None = None,
    ua: UaProfile | None = None,
) -> uc.Tab:
    origins = _origins_for(url)
    tab = await browser.get("about:blank")
    await match_proxy_geo(
        browser,
        tab,
        timezone=timezone,
        locale=locale,
        loc=loc,
        origins=origins,
    )
    if ua:
        await apply_user_agent(tab, ua, locale)
    await navigate_tab(tab, url)
    return tab


async def navigate_tab(tab: uc.Tab, url: str) -> None:
    await tab.send(uc.cdp.page.navigate(url=url))
    await tab.sleep(2)
    await tab


async def focus_page(tab: uc.Tab) -> None:
    """Клик по странице, не по виджету CF: адресная строка теряет выделение."""
    await tab.send(uc.cdp.page.bring_to_front())
    await tab.evaluate("window.focus()", return_by_value=True)
    await tab.mouse_click(48, 72)


async def humanize(tab: uc.Tab) -> None:
    await tab.sleep(random.uniform(0.4, 1.1))
    await tab.mouse_move(
        random.randint(240, 860),
        random.randint(180, 520),
        steps=random.randint(10, 18),
    )
    await tab.sleep(random.uniform(0.3, 0.8))
    await tab.scroll_down(random.randint(8, 16))
    await tab.sleep(random.uniform(0.4, 1.0))


_PROXY_DEAD_MARKS = (
    "err_proxy_connection_failed",
    "err_tunnel_connection_failed",
    "err_proxy_auth_requested",
    "unable to connect to the proxy",
    "proxy server is refusing",
    "the proxy server",
    "прокси-сервер",
    "не удается подключиться к прокси",
    "не удаётся подключиться к прокси",
)


async def page_proxy_dead(tab: uc.Tab) -> str | None:
    """Страница ошибки Chrome или диалог, когда прокси сам отвалился."""
    url = str(getattr(tab.target, "url", "") or "").lower()
    if "chrome-error" in url:
        return "chrome-error"
    try:
        info = await tab.evaluate(
            """
            (() => {
              const text = document.body ? document.body.innerText.slice(0, 2500) : '';
              const dialog = document.querySelector('[role="dialog"], dialog, .modal');
              return {
                title: document.title || '',
                text,
                dialog: dialog ? (dialog.innerText || '').slice(0, 400) : '',
              };
            })()
            """,
            return_by_value=True,
        )
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    blob = " ".join(
        str(info.get(key) or "") for key in ("title", "text", "dialog")
    ).lower()
    for mark in _PROXY_DEAD_MARKS:
        if mark in blob:
            return mark
    if info.get("dialog"):
        return f"dialog: {str(info.get('dialog')).strip()[:80]}"
    return None


def attach_dialog_watch(tab: uc.Tab, store: dict) -> None:
    """Окно alert/confirm в Chrome — IP часто так и сообщает, что сдох."""

    def _on_dialog(event) -> None:
        store["dialog"] = getattr(event, "message", None) or "javascript dialog"
        try:
            asyncio.get_running_loop().create_task(
                tab.send(uc.cdp.page.handle_javascript_dialog(accept=True))
            )
        except Exception:
            pass

    tab.add_handler(uc.cdp.page.JavascriptDialogOpening, _on_dialog)


_SILENT_CF_JS = """
(() => {
  const text = ((document.body && document.body.innerText) || '').toLowerCase();
  return (
    text.includes('verifying')
    || text.includes('checking your browser')
    || text.includes('just a moment')
    || text.includes('verify you are a real fan')
  );
})()
"""

_CHECKBOX_JS = """
(() => {
  const text = ((document.body && document.body.innerText) || '').toLowerCase();
  const silent = (
    text.includes('verifying')
    || text.includes('checking your browser')
    || text.includes('just a moment')
    || text.includes('verify you are a real fan')
  );
  if (silent) return false;
  if (text.includes('verify you are human')) return true;
  const nodes = document.querySelectorAll('input[type="checkbox"], [role="checkbox"]');
  for (const el of nodes) {
    if (el.offsetWidth < 8 || el.offsetHeight < 8) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) === 0) {
      continue;
    }
    const around = `${el.getAttribute('aria-label') || ''} ${el.title || ''}`.toLowerCase();
    if (around.includes('human') || around.includes('verify')) return true;
  }
  return false;
})()
"""


def _silent_cf(text: str, title: str = "") -> bool:
    blob = f"{text} {title}".lower()
    return (
        "just a moment" in blob
        or "verifying" in blob
        or "checking your browser" in blob
        or "verify you are a real fan" in blob
    )


async def _human_checkbox_visible(tab: uc.Tab) -> bool:
    """Настоящая галочка, не спиннер Turnstile и не «Just a moment»."""
    try:
        if await tab.evaluate(_SILENT_CF_JS, return_by_value=True):
            return False
    except Exception:
        pass
    try:
        found = await tab.evaluate(_CHECKBOX_JS, return_by_value=True)
    except Exception:
        found = False
    if found:
        return True
    try:
        frames = await tab.get_frames()
    except Exception:
        frames = []
    for frame in frames:
        try:
            if await frame.evaluate(_SILENT_CF_JS, return_by_value=True):
                continue
            if await frame.evaluate(_CHECKBOX_JS, return_by_value=True):
                return True
        except Exception:
            continue
    return False


async def page_state(tab: uc.Tab) -> str:
    text = await tab.evaluate(
        "document.body ? document.body.innerText.slice(0, 4000) : ''",
        return_by_value=True,
    )
    title = await tab.evaluate("document.title", return_by_value=True)
    low = str(text or "").lower()
    title_low = str(title or "").lower()
    if "access has been restricted" in low:
        return "restricted"
    if "why has this happened?" in low:
        return "bot_wall"
    if "are you a real fan?" in low and "just a moment" not in low:
        return "bot_wall"
    if _silent_cf(low, title_low):
        return "cloudflare"
    if await _human_checkbox_visible(tab):
        return "cf_checkbox"
    if "ensuring a fair fan" in low:
        return "queue"
    if "select tickets" in title_low or (
        "ticket" in low
        and any(word in low for word in ("select", "find", "buy", "cart", "seat"))
    ):
        return "shop"
    return "loading"


async def wait_ready(tab: uc.Tab, seconds: float = 90, on_state=None) -> str:
    """Тихий Turnstile ждём. Галочка — только если держится несколько опросов."""
    elapsed = 0.0
    state = "loading"
    checkbox_hits = 0
    while elapsed < seconds:
        state = await page_state(tab)
        if on_state:
            on_state(state)
        if state == "cf_checkbox":
            checkbox_hits += 1
            if checkbox_hits >= 3:
                return state
        else:
            checkbox_hits = 0
            if state in {"restricted", "bot_wall", "shop"}:
                return state
        step = 1.5
        await tab.sleep(step)
        elapsed += step
    return state


_COOKIE_SELECTORS = (
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    "button[id*='accept-all' i]",
    "button[aria-label='Accept All']",
)

_COOKIE_LABELS = (
    "Accept All",
    "Accept all",
    "Accept All Cookies",
)


async def accept_cookies(tab: uc.Tab, seconds: float = 15) -> bool:
    """Баннер AXS: кнопка Accept All (OneTrust и текстовый поиск)."""
    deadline = seconds
    elapsed = 0.0
    while elapsed < deadline:
        for selector in _COOKIE_SELECTORS:
            try:
                button = await tab.select(selector, timeout=0.4)
            except Exception:
                button = None
            if button:
                await button.click()
                await tab.sleep(0.8)
                return True
        for label in _COOKIE_LABELS:
            try:
                button = await tab.find(label, best_match=True, timeout=0.6)
            except Exception:
                button = None
            if button:
                await button.click()
                await tab.sleep(0.8)
                return True
        clicked = await tab.evaluate(
            """
            (() => {
              const labels = ['accept all', 'accept all cookies', 'allow all'];
              const nodes = [
                document.querySelector('#onetrust-accept-btn-handler'),
                ...document.querySelectorAll('button, [role="button"]'),
              ].filter(Boolean);
              const btn = nodes.find((el) => {
                const text = `${el.innerText || ''} ${el.getAttribute('aria-label') || ''}`
                  .trim().toLowerCase();
                return labels.some((item) => text === item || text.startsWith(item));
              });
              if (!btn) return false;
              btn.click();
              return true;
            })()
            """,
            return_by_value=True,
        )
        if clicked:
            await tab.sleep(0.8)
            return True
        await tab.sleep(0.7)
        elapsed += 1.7
    return False


async def wait_dom_ready(tab: uc.Tab, seconds: float = 30) -> str:
    """readyState complete и, если получится, уход «Loading map...»."""
    elapsed = 0.0
    last = "loading"
    while elapsed < seconds:
        info = await tab.evaluate(
            """
            (() => {
              const text = document.body ? document.body.innerText : '';
              return {
                ready: document.readyState,
                loadingMap: /loading map/i.test(text),
                cookies: /accept all/i.test(text),
              };
            })()
            """,
            return_by_value=True,
        )
        ready = (info or {}).get("ready") if isinstance(info, dict) else None
        loading_map = bool(info.get("loadingMap")) if isinstance(info, dict) else True
        if ready == "complete" and not loading_map:
            return "complete"
        last = "loading-map" if loading_map else str(ready or "loading")
        await tab.sleep(1)
        elapsed += 1
    return last
