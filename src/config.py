import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = (
    "SOCKS_PORT",
    "EXPECT_COUNTRY",
    "CHECK_URL",
    "HTTP_CHECK_URL",
    "GEO_URL",
    "CHROME_PATH",
    "CHROME_VERSION",
    "HEADLESS",
    "VNC",
    "SPOOF_FP",
    "PROFILE_DIR",
    "SCREENSHOTS_DIR",
    "LOGS_DIR",
    "BROWSER_LANG",
    "WINDOW_SIZE",
    "PAGE_URL",
    "SERVICE_HOST",
    "SERVICE_PORT",
)


def load_env(path: Path | None = None) -> dict[str, str]:
    env_path = path or (ROOT / ".env")
    values: dict[str, str] = {}
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    # Docker / система перекрывают файл — так и задумано в ТЗ.
    for key, value in os.environ.items():
        if value:
            values[key] = value
    return values


class Settings:
    def __init__(self, data: dict[str, str]):
        self._data = data

    def need(self, key: str) -> str:
        value = self._data.get(key, "").strip()
        if not value:
            raise ValueError(f"missing {key} in .env")
        return value

    def opt(self, key: str) -> str:
        return self._data.get(key, "").strip()

    def integer(self, key: str) -> int:
        return int(self.need(key))

    def flag(self, key: str) -> bool:
        return self.need(key).lower() in {"1", "true", "yes", "on"}

    def relpath(self, key: str) -> Path:
        return ROOT / self.need(key)

    def filepath(self, key: str) -> Path:
        path = Path(self.need(key))
        if not path.exists():
            raise FileNotFoundError(f"{key} not found: {path}")
        return path


def get_settings() -> Settings:
    data = load_env()
    missing = [key for key in REQUIRED if not data.get(key, "").strip()]
    if missing:
        raise ValueError(f"missing in env: {', '.join(missing)}")
    settings = Settings(data)
    settings.integer("SOCKS_PORT")
    settings.integer("SERVICE_PORT")
    settings.filepath("CHROME_PATH")
    if not settings.opt("PROXY") and not settings.opt("PROXY_FILE"):
        raise ValueError("set PROXY or PROXY_FILE")
    return settings
