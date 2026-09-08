"""Один прогон: проверить прокси → Chrome → страница → скрин."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from chrome import (
    accept_cookies,
    attach_dialog_watch,
    focus_page,
    humanize,
    match_proxy_geo,
    navigate_tab,
    open_url,
    origins_for,
    page_origin,
    page_proxy_dead,
    session_profile,
    start_chrome,
    wait_dom_ready,
    wait_ready,
)
from config import Settings
from proxies import PROTOCOLS, Protocol, Proxy, ProxyPool
from proxy_check import acquire_valid, ping_used
from user_agent import (
    dead_sessions,
    forget_dead,
    remember_dead,
    session_store_path,
    ua_for_open,
)


@dataclass
class _Session:
    browser: object | None = None
    tab: object | None = None
    proxy: Proxy | None = None
    ip: str | None = None
    session_id: str | None = None
    protocol: Protocol = "http"
    meta: dict = field(default_factory=dict)
    dialog: dict = field(default_factory=dict)
    fail_streak: int = 0
    dead_reason: str | None = None
    phase: str = ""
    stop_requested: bool = False


_live = _Session()


def browser_alive() -> bool:
    return _live.browser is not None


def set_phase(name: str) -> None:
    _live.phase = name


def _clear_bind() -> None:
    _live.proxy = None
    _live.ip = None
    _live.session_id = None
    _live.protocol = "http"
    _live.fail_streak = 0
    _live.phase = ""
    _live.tab = None
    _live.meta = {}
    _live.dialog.clear()


def _bind_session(proxy: Proxy, ip: str | None, protocol: Protocol = "http") -> None:
    _live.proxy = proxy
    _live.ip = ip
    _live.session_id = proxy.session_id
    _live.protocol = protocol
    _live.fail_streak = 0
    _live.dead_reason = None
    _live.dialog.clear()


def last_dead_reason() -> str | None:
    return _live.dead_reason


def stop_current() -> bool:
    """Остановить живой Chrome. Вызывается из кнопки «Остановить»."""
    _live.stop_requested = True
    browser = _live.browser
    _clear_bind()
    if browser is None:
        return False
    try:
        browser.stop()
    except Exception:
        pass
    _live.browser = None
    return True


def _log(path: Path, message: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(message, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def proxy_info(pool: ProxyPool) -> dict:
    proxy = pool.current()
    return {
        "index": pool.index,
        "total": len(pool),
        "session": proxy.session_id,
        "host": proxy.host,
        "scheme": proxy.scheme,
        "protocol": _live.protocol if browser_alive() else None,
        "browser_session": _live.session_id,
        "bound_ip": _live.ip if browser_alive() else None,
        "proxy_live": browser_alive(),
        "dead_reason": _live.dead_reason,
        "dead_count": len(dead_sessions(session_store_path(pool.settings))),
        "phase": _live.phase,
    }


async def _finish_tab(
    tab,
    *,
    browser,
    settings: Settings,
    store: Path,
    log_file: Path,
    ip_check: bool,
    session_id: str | None,
    ip: str | None,
    ua_name: str | None,
    geo_tz: str | None,
    locale: str | None,
    loc: tuple[float, float] | None,
    accept_banner: bool = True,
) -> tuple[str, str, str, object, Path]:
    state = "ip-check"
    if not ip_check:
        state = await wait_ready(tab, on_state=set_phase)
        current = str(tab.target.url or "")
        if current.startswith("http"):
            await match_proxy_geo(
                browser,
                tab,
                timezone=geo_tz,
                locale=locale,
                loc=loc,
                origins=[page_origin(current)],
            )
        if state in {"cf_checkbox", "cloudflare", "bot_wall", "restricted"}:
            _live.dead_reason = f"cloudflare: {state}"
            remember_dead(
                store,
                session_id=session_id,
                ip=ip,
                ua_name=ua_name,
                reason=_live.dead_reason or state,
            )
            _log(
                log_file,
                "cloudflare checkbox — не прошёл, сессия записана как протухшая"
                if state == "cf_checkbox"
                else f"cloudflare blocked — сессия записана как протухшая ({state})",
            )
        if state == "shop":
            if forget_dead(store, session_id):
                _live.dead_reason = None
                _log(log_file, f"session={session_id} снова живая — убрал из протухших")
            if accept_banner:
                set_phase("cookies")
                await focus_page(tab)
                cookies = await accept_cookies(tab)
                _log(log_file, f"cookies accept all: {'yes' if cookies else 'not found'}")
            else:
                _log(log_file, "cookies: skip — тот же Chrome, баннер уже принят")
            set_phase("settle")
            settled = await wait_dom_ready(tab)
            _log(log_file, f"dom: {settled}")
            await humanize(tab)

    ua = await tab.evaluate("navigator.userAgent", return_by_value=True)
    platform = await tab.evaluate("navigator.platform", return_by_value=True)
    webdriver = await tab.evaluate("navigator.webdriver", return_by_value=True)
    chrome_version = settings.need("CHROME_VERSION")
    _log(log_file, f"ua: {ua} platform={platform} webdriver={webdriver}")
    if chrome_version not in str(ua):
        _log(log_file, f"warning: expected Chrome {chrome_version} in userAgent")

    title = await tab.evaluate("document.title", return_by_value=True)
    tab_url = str(tab.target.url or "")
    _log(log_file, f"document.title: {title}")
    _log(log_file, f"page state: {state}")
    _log(log_file, f"tab url: {tab_url}")
    if "AfterEvent" in tab_url:
        _log(log_file, "note: event is AfterEvent — витрина пустая, это не бан")

    set_phase("screenshot")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shot = settings.relpath("SCREENSHOTS_DIR") / f"{stamp}.png"
    saved = await tab.save_screenshot(str(shot), format="png")
    _log(log_file, f"screenshot: {saved}")
    set_phase("ready")
    return state, str(title), tab_url, saved, shot


async def goto_page(
    pool: ProxyPool,
    settings: Settings,
    *,
    url: str,
    ip_check: bool = False,
) -> dict:
    """Тот же Chrome, другой URL — без нового профиля и прокси."""
    browser = _live.browser
    if browser is None:
        raise RuntimeError("Chrome не запущен")
    log_file = settings.relpath("LOGS_DIR") / "run.log"
    settings.relpath("SCREENSHOTS_DIR").mkdir(parents=True, exist_ok=True)
    store = session_store_path(settings)
    _live.stop_requested = False
    tab = _live.tab
    if tab is None:
        tabs = getattr(browser, "tabs", None) or []
        if not tabs:
            raise RuntimeError("нет вкладки Chrome")
        tab = tabs[0]
        _live.tab = tab
    set_phase("navigate")
    _log(log_file, f"goto (same chrome): {url}")
    meta = _live.meta
    await match_proxy_geo(
        browser,
        tab,
        timezone=meta.get("timezone"),
        locale=meta.get("locale"),
        loc=meta.get("loc"),
        origins=origins_for(url),
    )
    try:
        await navigate_tab(tab, url)
        state, title, tab_url, saved, shot = await _finish_tab(
            tab,
            browser=browser,
            settings=settings,
            store=store,
            log_file=log_file,
            ip_check=ip_check,
            session_id=_live.session_id,
            ip=_live.ip,
            ua_name=meta.get("ua_name"),
            geo_tz=meta.get("timezone"),
            locale=meta.get("locale"),
            loc=meta.get("loc"),
            accept_banner=False,
        )
    except (asyncio.CancelledError, Exception) as exc:
        if _live.stop_requested or isinstance(exc, asyncio.CancelledError):
            _log(log_file, "stopped by user")
            return {"ok": True, "state": "stopped", **proxy_info(pool)}
        raise
    return {
        "ok": True,
        "state": state,
        "title": title,
        "url": tab_url,
        "screenshot": str(Path(saved) if saved else shot),
        "ip": meta.get("ip") or _live.ip,
        "country": meta.get("country"),
        "timezone": meta.get("timezone"),
        "browser_alive": True,
        "reused": True,
        "dead_reason": _live.dead_reason,
        **proxy_info(pool),
    }


async def open_page(
    pool: ProxyPool,
    settings: Settings,
    *,
    url: str,
    ip_check: bool = False,
    protocol: str = "http",
) -> dict:
    if protocol not in PROTOCOLS:
        raise ValueError(f"unknown protocol: {protocol!r}")
    proto = cast(Protocol, protocol)
    set_phase("proxy")
    log_file = settings.relpath("LOGS_DIR") / "run.log"
    settings.relpath("SCREENSHOTS_DIR").mkdir(parents=True, exist_ok=True)

    store = session_store_path(settings)
    check = acquire_valid(pool, protocols=(proto,))
    proxy = check.proxy
    _log(
        log_file,
        f"proxy ok session={proxy.session_id} ip={check.ip} "
        f"country={check.country} city={check.city} tz={check.timezone} loc={check.loc} "
        f"protocol={proto}",
    )

    if not ip_check and (not check.timezone or not check.country):
        raise RuntimeError("proxy geo incomplete — AXS не открываю")

    # Новый каталог: старый профиль с CF-cookie ядовит.
    profile_dir = (
        session_profile(settings.relpath("PROFILE_DIR"), proxy)
        / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )
    set_phase("chrome")
    chrome_path = settings.filepath("CHROME_PATH")
    _log(log_file, f"chrome: {chrome_path} profile: {profile_dir}")
    _live.stop_requested = False
    browser = await start_chrome(
        chrome_path=chrome_path,
        profile_dir=profile_dir,
        headless=settings.flag("HEADLESS"),
        lang=settings.need("BROWSER_LANG"),
        window_size=settings.need("WINDOW_SIZE"),
        proxy=proxy,
        timezone=check.timezone,
        locale=settings.need("BROWSER_LANG"),
        proxy_protocol=proto,
    )
    _live.browser = browser
    _bind_session(proxy, check.ip, proto)
    _live.meta = {
        "timezone": check.timezone,
        "locale": settings.need("BROWSER_LANG"),
        "loc": check.loc,
        "country": check.country,
        "ip": check.ip,
        "ua_name": None,
    }
    ua_profile = ua_for_open(proxy.session_id, check.ip, store)
    _live.meta["ua_name"] = ua_profile.name
    _log(log_file, f"ua profile={ua_profile.name} grease={ua_profile.grease}")
    keep = False
    try:
        set_phase("navigate")
        _log(log_file, f"open: {url}")
        tab = await open_url(
            browser,
            url,
            timezone=check.timezone,
            locale=settings.need("BROWSER_LANG"),
            loc=check.loc,
            ua=ua_profile,
            spoof_fp=settings.flag("SPOOF_FP"),
        )
        _live.tab = tab
        attach_dialog_watch(tab, _live.dialog)
        js_tz = await tab.evaluate(
            "Intl.DateTimeFormat().resolvedOptions().timeZone",
            return_by_value=True,
        )
        _log(log_file, f"js timezone: {js_tz}")

        state, title, tab_url, saved, shot = await _finish_tab(
            tab,
            browser=browser,
            settings=settings,
            store=store,
            log_file=log_file,
            ip_check=ip_check,
            session_id=proxy.session_id,
            ip=check.ip,
            ua_name=ua_profile.name,
            geo_tz=check.timezone,
            locale=settings.need("BROWSER_LANG"),
            loc=check.loc,
        )
        keep = not _live.stop_requested
    except (asyncio.CancelledError, Exception) as exc:
        if _live.stop_requested or isinstance(exc, asyncio.CancelledError):
            keep = False
            _log(log_file, "stopped by user")
            return {"ok": True, "state": "stopped", **proxy_info(pool)}
        keep = True
        raise
    finally:
        if keep and not _live.stop_requested:
            _live.browser = browser
            _log(log_file, "session kept — Chrome остаётся открытым")
        else:
            _live.browser = None
            _clear_bind()
            try:
                browser.stop()
            except Exception:
                pass

    return {
        "ok": True,
        "state": state,
        "title": str(title),
        "url": tab_url,
        "screenshot": str(Path(saved) if saved else shot),
        "ip": check.ip,
        "country": check.country,
        "timezone": check.timezone,
        "browser_alive": keep,
        "dead_reason": _live.dead_reason,
        **proxy_info(pool),
    }


async def _chrome_death_signal(browser) -> str | None:
    if _live.dialog.get("dialog"):
        return f"window: {_live.dialog['dialog']}"
    tabs = getattr(browser, "tabs", None) or []
    for tab in tabs:
        try:
            mark = await page_proxy_dead(tab)
        except Exception:
            continue
        if mark:
            return mark
    return None


def _proxy_health(settings: Settings) -> str | None:
    if _live.proxy is None:
        return None
    ping = ping_used(_live.proxy, settings, protocol=_live.protocol, timeout=12.0)
    if not ping.ok:
        _live.fail_streak += 1
        if _live.fail_streak >= 2:
            return ping.error or f"{_live.protocol} proxy failed"
        return None
    _live.fail_streak = 0
    if _live.ip and ping.ip and ping.ip != _live.ip:
        return f"ip changed {_live.ip} -> {ping.ip}"
    return None


async def watch_live_session(settings: Settings) -> None:
    """Пока Chrome открыт: проверяем живой IP и окно ошибки."""
    while True:
        await asyncio.sleep(20)
        browser = _live.browser
        if browser is None:
            continue
        reason = await _chrome_death_signal(browser)
        if not reason:
            reason = await asyncio.to_thread(_proxy_health, settings)
        if not reason:
            continue
        _live.dead_reason = reason
        remember_dead(
            session_store_path(settings),
            session_id=_live.session_id,
            ip=_live.ip,
            ua_name=None,
            reason=reason,
        )
        print(f"proxy died ({reason}) — Chrome closed, next Open = new session", flush=True)
        stop_current()
