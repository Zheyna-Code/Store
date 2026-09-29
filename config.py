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
    admin_secret: str
    database_url: str
    crypto_pay_token: str
    crypto_pay_webhook_secret: str
    public_base_url: str = ""


settings = Settings(
    token=os.getenv("BOT_TOKEN", ""),
    warranty_url=os.getenv("WARRANTY_URL", ""),
    terms_url=os.getenv("TERMS_URL", ""),
    privacy_url=os.getenv("PRIVACY_URL", ""),
    admin_secret=os.getenv("ADMIN_SECRET", ""),
    database_url=os.getenv("DATABASE_URL", ""),
    crypto_pay_token=os.getenv("CRYPTO_PAY_TOKEN", ""),
    crypto_pay_webhook_secret=os.getenv("CRYPTO_PAY_WEBHOOK_SECRET", ""),
    public_base_url=os.getenv("PUBLIC_BASE_URL", ""),
)

COVERS_DIR = BASE_DIR / "brand-covers"
