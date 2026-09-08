"""Validate a proxy before the browser uses it. Does not touch AXS."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from config import Settings
from proxies import PROTOCOLS, Protocol, Proxy


@dataclass
class ProtocolResult:
    protocol: Protocol
    ok: bool
    status: int | None = None
    ip: str | None = None
    error: str | None = None


@dataclass
class ProxyCheck:
    ok: bool
    proxy: Proxy
    ip: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    timezone: str | None = None
    loc: tuple[float, float] | None = None
    org: str | None = None
    protocols: dict[str, ProtocolResult] = field(default_factory=dict)
    error: str | None = None


def _request(proxy_url: str, url: str, timeout: float) -> tuple[int, str]:
    with httpx.Client(proxy=proxy_url, timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        return response.status_code, response.text.strip()


def used_browser_protocol(proxy: Proxy) -> Protocol:
    """Чем ходит Chrome: HTTP-forwarder, не SOCKS и не отдельный HTTPS-порт."""
    return "http" if proxy.scheme != "https" else "https"


def ping_used(
    proxy: Proxy,
    settings: Settings,
    *,
    protocol: Protocol | None = None,
    timeout: float = 12.0,
) -> ProtocolResult:
    """Проверка одного канала — того, что выбран в UI / чем ходит Chrome."""
    used = protocol or used_browser_protocol(proxy)
    return _check_protocol(proxy, used, settings, timeout)


def _check_protocol(
    proxy: Proxy,
    protocol: Protocol,
    settings: Settings,
    timeout: float,
) -> ProtocolResult:
    target = (
        settings.need("CHECK_URL")
        if protocol in {"https", "socks5"}
        else settings.need("HTTP_CHECK_URL")
    )
    proxy_url = proxy.url(protocol)
    try:
        status, body = _request(proxy_url, target, timeout)
        ip = body.split()[0] if body else None
        ok = 200 <= status < 400 and bool(ip)
        return ProtocolResult(protocol=protocol, ok=ok, status=status, ip=ip)
    except Exception as exc:
        return ProtocolResult(
            protocol=protocol,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def _geo(
    proxy: Proxy,
    settings: Settings,
    timeout: float,
    protocol: Protocol = "https",
) -> dict:
    proxy_url = proxy.url(protocol)
    status, body = _request(proxy_url, settings.need("GEO_URL"), timeout)
    if not body.startswith("{"):
        return {"status": status, "raw": body}
    data = json.loads(body)
    data["status"] = status
    return data


def _parse_loc(raw: object) -> tuple[float, float] | None:
    # ipinfo отдаёт "47.6062,-122.3321"
    if not isinstance(raw, str) or "," not in raw:
        return None
    lat_s, lon_s = raw.split(",", 1)
    try:
        return float(lat_s.strip()), float(lon_s.strip())
    except ValueError:
        return None


def validate_proxy(
    proxy: Proxy,
    settings: Settings,
    *,
    timeout: float = 25.0,
    protocols: tuple[Protocol, ...] = PROTOCOLS,
) -> ProxyCheck:
    """HTTP = HTTP proxy + HTTP target; HTTPS = same proxy + HTTPS target (CONNECT); SOCKS5 = socks port."""
    results = {
        protocol: _check_protocol(proxy, protocol, settings, timeout)
        for protocol in protocols
    }
    ok_results = [item for item in results.values() if item.ok]
    if not ok_results:
        first_error = next(
            (item.error for item in results.values() if item.error),
            "all protocols failed",
        )
        return ProxyCheck(ok=False, proxy=proxy, protocols=results, error=first_error)

    ip = ok_results[0].ip
    country = region = city = timezone = org = None
    loc = None
    try:
        geo_protocol = protocols[0] if protocols else "https"
        geo = _geo(proxy, settings, timeout, geo_protocol)
        ip = geo.get("ip") or ip
        country = geo.get("country")
        region = geo.get("region")
        city = geo.get("city")
        timezone = geo.get("timezone")
        org = geo.get("org")
        loc = _parse_loc(geo.get("loc"))
    except Exception as exc:
        if settings.opt("EXPECT_COUNTRY"):
            return ProxyCheck(
                ok=False,
                proxy=proxy,
                ip=ip,
                protocols=results,
                error=f"geo lookup failed: {type(exc).__name__}: {exc}",
            )

    expected = (settings.opt("EXPECT_COUNTRY") or proxy.country or "").lower()
    if expected and not country:
        return ProxyCheck(
            ok=False,
            proxy=proxy,
            ip=ip,
            protocols=results,
            error="geo has no country",
        )
    if expected and not timezone:
        return ProxyCheck(
            ok=False,
            proxy=proxy,
            ip=ip,
            country=country,
            protocols=results,
            error="geo has no timezone",
        )
    if expected and country and country.lower() != expected.lower():
        return ProxyCheck(
            ok=False,
            proxy=proxy,
            ip=ip,
            country=country,
            region=region,
            city=city,
            timezone=timezone,
            loc=loc,
            org=org,
            protocols=results,
            error=f"country {country!r} != expected {expected!r}",
        )

    return ProxyCheck(
        ok=True,
        proxy=proxy,
        ip=ip,
        country=country,
        region=region,
        city=city,
        timezone=timezone,
        loc=loc,
        org=org,
        protocols=results,
    )


def acquire_valid(
    pool,
    *,
    timeout: float = 25.0,
    protocols: tuple[Protocol, ...] = PROTOCOLS,
) -> ProxyCheck:
    """Validate current proxy; on failure rotate in-process until one works."""
    started = pool.index
    last: ProxyCheck | None = None
    while True:
        last = validate_proxy(
            pool.current(),
            pool.settings,
            timeout=timeout,
            protocols=protocols,
        )
        if last.ok:
            return last
        pool.rotate()
        if pool.index == started:
            raise RuntimeError(
                last.error or "no working proxy left in the pool"
            )
