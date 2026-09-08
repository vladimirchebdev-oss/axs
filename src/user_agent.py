"""Пул User-Agent только для Docker: Linux + Chrome 152.

Пока IP жив — тот же профиль, даже если страницу открыли заново.
Протухшие сессии и последний UA пишутся на диск (logs/) — живут после рестарта Docker.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import Settings

# Как в контейнере: google-chrome 152.0.7977.82, reduced UA = 152.0.0.0
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)
_FULL = "152.0.7977.82"
_MAJOR = "152"


@dataclass(frozen=True)
class UaProfile:
    name: str
    user_agent: str
    platform: str
    grease: str


_POOL: tuple[UaProfile, ...] = (
    UaProfile("linux-152-a", _UA, "Linux x86_64", "Not:A-Brand"),
    UaProfile("linux-152-b", _UA, "Linux x86_64", "Not A(Brand"),
    UaProfile("linux-152-c", _UA, "Linux x86_64", "Not)A;Brand"),
    UaProfile("linux-152-d", _UA, "Linux x86_64", "Not_A Brand"),
    UaProfile("linux-152-e", _UA, "Linux x86_64", "Not-A.Brand"),
)
_BY_NAME = {item.name: item for item in _POOL}


def session_store_path(settings: Settings) -> Path:
    """Файл на volume logs/ — не пропадает при recreate контейнера."""
    return settings.relpath("LOGS_DIR") / "session-store.json"


def _key(session_id: str | None, ip: str | None) -> str:
    return f"{session_id or ''}@{ip or ''}"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {"dead": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"dead": []}
    if not isinstance(data, dict):
        return {"dead": []}
    data.setdefault("dead", [])
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick(avoid: set[str]) -> UaProfile:
    choices = [item for item in _POOL if item.name not in avoid]
    if not choices:
        choices = list(_POOL)
    return random.choice(choices)


def is_dead_session(store: Path, session_id: str | None) -> bool:
    if not session_id:
        return False
    return any(item.get("session") == session_id for item in _load(store).get("dead") or [])


def dead_sessions(store: Path) -> list[dict]:
    return list(_load(store).get("dead") or [])


def ua_for_open(session_id: str | None, ip: str | None, store: Path) -> UaProfile:
    """Тот же UA, если этот IP ещё жив и сессия не в списке протухших."""
    data = _load(store)
    key = _key(session_id, ip)
    current = data.get("name")
    if (
        not is_dead_session(store, session_id)
        and data.get("key") == key
        and current in _BY_NAME
    ):
        return _BY_NAME[current]
    profile = _pick({current, data.get("prev")} - {None})
    _save(
        store,
        {
            "key": key,
            "name": profile.name,
            "prev": current,
            "ip": ip,
            "session": session_id,
            "dead": data.get("dead") or [],
        },
    )
    return profile


def forget_dead(store: Path, session_id: str | None) -> bool:
    """Сессия снова прошла сайт — убираем из протухших."""
    if not session_id:
        return False
    data = _load(store)
    dead = data.get("dead") or []
    kept = [item for item in dead if item.get("session") != session_id]
    if len(kept) == len(dead):
        return False
    data["dead"] = kept
    _save(store, data)
    return True


def remember_dead(
    store: Path,
    *,
    session_id: str | None,
    ip: str | None,
    ua_name: str | None,
    reason: str,
) -> None:
    data = _load(store)
    name = ua_name or data.get("name")
    dead = [
        item
        for item in (data.get("dead") or [])
        if item.get("session") != session_id
    ]
    if session_id:
        dead.append(
            {
                "session": session_id,
                "ip": ip,
                "ua": name,
                "reason": reason,
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    _save(
        store,
        {
            "key": None,
            "name": None,
            "prev": name or data.get("prev"),
            "ip": None,
            "session": None,
            "dead": dead[-200:],
        },
    )


def client_hints(profile: UaProfile):
    from nodriver.cdp.emulation import UserAgentBrandVersion, UserAgentMetadata

    grease = UserAgentBrandVersion(brand=profile.grease, version="99")
    chromium = UserAgentBrandVersion(brand="Chromium", version=_MAJOR)
    chrome = UserAgentBrandVersion(brand="Google Chrome", version=_MAJOR)
    grease_full = UserAgentBrandVersion(brand=profile.grease, version="10.0.1.4")
    chromium_full = UserAgentBrandVersion(brand="Chromium", version=_FULL)
    chrome_full = UserAgentBrandVersion(brand="Google Chrome", version=_FULL)
    return UserAgentMetadata(
        platform="Linux",
        platform_version="",
        architecture="x86",
        model="",
        mobile=False,
        brands=[grease, chromium, chrome],
        full_version_list=[grease_full, chromium_full, chrome_full],
        full_version=_FULL,
        bitness="64",
        wow64=False,
        form_factors=["Desktop"],
    )
