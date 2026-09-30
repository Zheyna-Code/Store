"""Small Crypto Pay client: Decimal USD amounts, signed webhooks, no secret logging."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from aiohttp import ClientError, ClientSession, ClientTimeout


class PaymentError(RuntimeError):
    """Safe, user-facing provider failure; ambiguous means creation may have succeeded."""
    def __init__(self, message="Crypto Bot временно недоступен. Попробуйте позже.", *, ambiguous=False):
        super().__init__(message)
        self.ambiguous = ambiguous


def money(value, *, maximum=Decimal('1000000')) -> Decimal:
    try:
        amount = Decimal(str(value).strip().replace(',', '.'))
        if not amount.is_finite() or amount < Decimal('0.01') or amount > maximum:
            raise ValueError
        if amount != amount.quantize(Decimal('0.01')):
            raise ValueError
        return amount.quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Введите положительную сумму с точностью до двух знаков после запятой.') from None


def quantity(value) -> int:
    text = str(value)
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= 100:
        raise ValueError('Количество должно быть от 1 до 100.')
    return int(text)


def invoice_url(invoice: dict) -> str:
    url = invoice.get('bot_invoice_url') or invoice.get('pay_url') or ''
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme != 'https' or parsed.hostname not in {'t.me', 'pay.crypt.bot', 'testnet-pay.crypt.bot'} or parsed.username:
        raise PaymentError('Crypto Bot не вернул корректную ссылку на счёт.', ambiguous=True)
    return url


def valid_signature(token: str, body: bytes, signature: str) -> bool:
    if not token or not signature:
        return False
    key = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def validate_invoice(invoice: dict, payment) -> None:
    """Never trust a paid flag alone: bind ID, USD amount and unguessable payload."""
    try:
        invoice_id = invoice['invoice_id']
        if isinstance(invoice_id, bool) or not isinstance(invoice_id, int) or invoice_id <= 0:
            raise ValueError
        if payment['invoice_id'] is not None and payment['invoice_id'] != invoice_id:
            raise ValueError
        if invoice.get('currency_type') != 'fiat' or invoice.get('fiat') != 'USD':
            raise ValueError
        if money(invoice['amount']) != payment['amount']:
            raise ValueError
        if invoice.get('payload') != payment['payload'] or invoice.get('status') not in {'active', 'paid', 'expired'}:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError('Счёт не соответствует сохранённому платежу.') from None


class CryptoPay:
    def __init__(self, token: str, *, testnet=False):
        self.token = token
        self.base = 'https://testnet-pay.crypt.bot/api/' if testnet else 'https://pay.crypt.bot/api/'
        self.session: ClientSession | None = None

    async def close(self):
        if self.session:
            await self.session.close()

    async def request(self, method: str, data: dict):
        if not self.token:
            raise PaymentError('Оплата через Crypto Bot пока не настроена. Доступна оплата через администратора.')
        if self.session is None or self.session.closed:
            self.session = ClientSession(timeout=ClientTimeout(total=15))
        try:
            async with self.session.post(self.base + method, json=data,
                                         headers={'Crypto-Pay-API-Token': self.token}) as response:
                result = await response.json(content_type=None)
                if not isinstance(result, dict) or result.get('ok') is not True:
                    error = result.get('error') if isinstance(result, dict) else None
                    name = error.get('name') if isinstance(error, dict) else None
                    auth_error = name in {'UNAUTHORIZED', 'AUTH_TOKEN_INVALID', 'AUTH_TOKEN_REQUIRED'} or response.status in {401, 403}
                    raise PaymentError('Crypto Pay не настроен: проверьте токен приложения.' if auth_error else 'Crypto Bot отклонил запрос. Попробуйте позже.',
                                       ambiguous=response.status >= 500)
                if response.status != 200 or 'result' not in result:
                    raise PaymentError(ambiguous=True)
                return result['result']
        except PaymentError:
            raise
        except (ClientError, asyncio.TimeoutError, ValueError, TypeError):
            # No automatic createInvoice retry: timeout may follow a successful creation.
            raise PaymentError(ambiguous=True) from None

    async def create(self, payment):
        return await self.request('createInvoice', {
            'currency_type': 'fiat', 'fiat': 'USD', 'accepted_assets': 'USDT,TON',
            'amount': f"{payment['amount']:.2f}",
            'description': (f"{payment['product_name']} × {payment['quantity']}" if payment['purpose'] == 'product' else 'Пополнение баланса магазина')[:1024],
            'payload': payment['payload'], 'expires_in': 600,
            'allow_comments': False,
        })

    async def invoices(self, ids: list[int] | None = None) -> list[dict]:
        result = await self.request('getInvoices', {'invoice_ids': ','.join(map(str, ids)), 'count': len(ids)} if ids else {'count': 100})
        items = result.get('items') if isinstance(result, dict) else result
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise PaymentError()
        return items

    async def delete(self, invoice_id: int):
        result = await self.request('deleteInvoice', {'invoice_id': invoice_id})
        if result is not True:
            raise PaymentError()
