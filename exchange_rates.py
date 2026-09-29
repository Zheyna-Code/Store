"""Reference USD/RUB rate from CBR. Prices and invoices remain USD."""
import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import time
from xml.etree import ElementTree

from aiohttp import ClientError, ClientSession, ClientTimeout

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"


@dataclass(frozen=True)
class RateQuote:
    rub_per_usd: Decimal
    effective_date: str
    stale: bool = False

    def rubles(self, usd: str | Decimal) -> Decimal:
        amount = Decimal(str(usd))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Некорректная сумма USD")
        return (amount * self.rub_per_usd).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_cbr_daily(data: bytes) -> RateQuote:
    if len(data) > 500_000:
        raise ValueError("Слишком большой ответ ЦБ")
    root = ElementTree.fromstring(data)
    effective_date = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date().isoformat()
    for currency in root.findall("Valute"):
        if currency.findtext("CharCode") != "USD":
            continue
        nominal = Decimal(currency.findtext("Nominal", "0").strip().replace(",", "."))
        value = Decimal(currency.findtext("Value", "0").strip().replace(",", "."))
        if not nominal.is_finite() or not value.is_finite() or nominal <= 0 or value <= 0:
            raise ValueError("Некорректный курс ЦБ")
        rate = value / nominal
        if not Decimal("0.0001") <= rate <= Decimal("100000"):
            raise ValueError("Некорректный курс ЦБ")
        return RateQuote(rate, effective_date)
    raise ValueError("USD отсутствует в ответе ЦБ")


class ExchangeRates:
    def __init__(self, ttl_seconds: int = 3600, max_stale_seconds: int = 86400):
        self.ttl = ttl_seconds
        self.max_stale = max_stale_seconds
        self.cached: RateQuote | None = None
        self.fetched_at = 0.0
        self.retry_at = 0.0
        self.lock = asyncio.Lock()

    async def _fetch(self) -> RateQuote:
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with session.get(CBR_DAILY_URL) as response:
                response.raise_for_status()
                chunks = []
                size = 0
                async for chunk in response.content.iter_chunked(8192):
                    size += len(chunk)
                    if size > 500_000:
                        raise ValueError("Слишком большой ответ ЦБ")
                    chunks.append(chunk)
                data = b"".join(chunks)
        return parse_cbr_daily(data)

    def _fallback(self, now: float) -> RateQuote | None:
        if self.cached and now - self.fetched_at <= self.max_stale:
            return RateQuote(self.cached.rub_per_usd, self.cached.effective_date, stale=True)
        return None

    async def quote(self) -> RateQuote | None:
        now = time.monotonic()
        if self.cached and now - self.fetched_at < self.ttl:
            return self.cached
        if now < self.retry_at:
            return self._fallback(now)
        async with self.lock:
            now = time.monotonic()
            if self.cached and now - self.fetched_at < self.ttl:
                return self.cached
            if now < self.retry_at:
                return self._fallback(now)
            try:
                self.cached = await self._fetch()
                self.fetched_at = time.monotonic()
                self.retry_at = 0.0
                return self.cached
            except (ClientError, asyncio.TimeoutError, ElementTree.ParseError, InvalidOperation, ValueError, KeyError):
                now = time.monotonic()
                self.retry_at = now + 60
                # Never invent a rate or prevent USD payment because CBR is unavailable.
                return self._fallback(now)
