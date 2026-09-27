from dataclasses import dataclass
from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ImportError:
    # Бот остаётся запускаемым и без python-dotenv: удобно для простых Hostless-окружений.
    def load_dotenv(path: Path) -> None:
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", maxsplit=1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    token: str
    warranty_url: str
    terms_url: str
    privacy_url: str


settings = Settings(
    token=os.getenv("BOT_TOKEN", ""),
    warranty_url=os.getenv("WARRANTY_URL", ""),
    terms_url=os.getenv("TERMS_URL", ""),
    privacy_url=os.getenv("PRIVACY_URL", ""),
)

COVERS_DIR = BASE_DIR / "brand-covers"
