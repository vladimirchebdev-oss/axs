from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast, get_args
from urllib.parse import quote, unquote, urlparse

from config import Settings

Protocol = Literal["http", "https", "socks5"]
PROTOCOLS: tuple[Protocol, ...] = get_args(Protocol)
_SCHEME_RE = re.compile(rf"^({'|'.join(PROTOCOLS)})://", re.IGNORECASE)
_FLAG_RE = re.compile(
    r"_(country|session|lifetime)-([^_]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Proxy:
    username: str
    password: str
    host: str
    port: int
    socks_port: int
    scheme: Protocol
    country: str | None
    session_id: str | None
    lifetime: str | None
    raw: str

    def url(self, protocol: Protocol) -> str:
        user = quote(self.username, safe="")
        password = quote(self.password, safe="")
        if protocol == "socks5":
            scheme: Protocol = "socks5"
            port = self.port if self.scheme == "socks5" else self.socks_port
        else:
            # HTTP-прокси закрывает и HTTP, и HTTPS (CONNECT).
            # https:// в URL — только если в строке явно указан HTTPS-прокси.
            scheme = "https" if protocol == "https" and self.scheme == "https" else "http"
            port = self.port
        return f"{scheme}://{user}:{password}@{self.host}:{port}"


class ProxyParseError(ValueError):
    pass


def parse_protocols(raw: str) -> tuple[Protocol, ...]:
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    unknown = [item for item in items if item not in PROTOCOLS]
    if unknown:
        raise ValueError(f"unknown protocol(s): {unknown}")
    return items or PROTOCOLS


def _flags_from_password(password: str) -> dict[str, str]:
    return {key.lower(): value for key, value in _FLAG_RE.findall(password)}


def parse_proxy_line(raw: str, socks_port: int) -> Proxy:
    line = raw.strip()
    if not line or line.startswith("#"):
        raise ProxyParseError("empty proxy line")

    to_parse = line if _SCHEME_RE.match(line) else f"http://{line}"
    parsed = urlparse(to_parse)
    scheme = parsed.scheme.lower()
    if scheme not in PROTOCOLS:
        raise ProxyParseError(f"unsupported scheme in: {line!r}")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    host = parsed.hostname or ""
    port = parsed.port
    if port is None or not username or not password or not host:
        raise ProxyParseError(f"expected [scheme://]user:pass@host:port, got: {line!r}")

    flags = _flags_from_password(password)
    return Proxy(
        username=username,
        password=password,
        host=host,
        port=port,
        scheme=cast(Protocol, scheme),
        country=flags.get("country"),
        session_id=flags.get("session"),
        lifetime=flags.get("lifetime"),
        raw=line,
        socks_port=socks_port,
    )


def _collect_lines(settings: Settings, root: Path) -> list[str]:
    lines: list[str] = []
    single = settings.opt("PROXY")
    if single:
        lines.append(single)

    file_value = settings.opt("PROXY_FILE")
    if file_value:
        path = Path(file_value)
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            raise FileNotFoundError(f"PROXY_FILE not found: {path}")
        lines.extend(path.read_text(encoding="utf-8").splitlines())
    return lines


def load_proxies(settings: Settings, root: Path) -> list[Proxy]:
    proxies: list[Proxy] = []
    seen: set[str] = set()
    for line in _collect_lines(settings, root):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in seen:
            continue
        seen.add(stripped)
        proxies.append(
            parse_proxy_line(stripped, socks_port=settings.integer("SOCKS_PORT"))
        )
    return proxies


@dataclass
class ProxyPool:
    """In-memory pool: rotate/reload without restarting the process."""

    _proxies: list[Proxy] = field(default_factory=list)
    _index: int = 0
    _settings: Settings | None = None
    _root: Path | None = None

    @classmethod
    def from_settings(cls, settings: Settings, root: Path) -> "ProxyPool":
        proxies = load_proxies(settings, root)
        if not proxies:
            raise ValueError("proxy list is empty — set PROXY or PROXY_FILE")
        return cls(_proxies=proxies, _settings=settings, _root=root)

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            raise RuntimeError("pool has no settings")
        return self._settings

    @property
    def index(self) -> int:
        return self._index

    def current(self) -> Proxy:
        return self._proxies[self._index]

    def rotate(self, steps: int = 1) -> Proxy:
        self._index = (self._index + steps) % len(self._proxies)
        return self.current()

    def reload(self) -> int:
        if self._root is None:
            raise RuntimeError("pool was not loaded from settings, cannot reload")
        current_raw = self.current().raw
        self._proxies = load_proxies(self.settings, self._root)
        if not self._proxies:
            raise ValueError("proxy list is empty after reload")
        for i, proxy in enumerate(self._proxies):
            if proxy.raw == current_raw:
                self._index = i
                break
        else:
            self._index = 0
        return len(self._proxies)

    def __len__(self) -> int:
        return len(self._proxies)

    def __iter__(self):
        return iter(self._proxies)
