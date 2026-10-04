"""Checkout orchestration, polling fallback and retryable private delivery."""
from __future__ import annotations

import asyncio
import html
import json
import logging
from collections import OrderedDict

from crypto_pay import CryptoPay, PaymentError, invoice_url, validate_invoice
from payment_store import PaymentStore


class Payments:
    def __init__(self, pool, client: CryptoPay, bot):
        self.store = PaymentStore(pool)
        self.client = client
        self.bot = bot
        self.locks = OrderedDict()

    def lock(self, owner: int, purpose: str, product_id):
        key = (owner, purpose, product_id)
        if key not in self.locks:
            self.locks[key] = asyncio.Lock()
        self.locks.move_to_end(key)
        # Only evict unlocked locks, keeping the live checkout serialization intact.
        if len(self.locks) > 2048:
            for k, lock in list(self.locks.items()):
                if k != key and not lock.locked():
                    self.locks.pop(k)
                    break
        return self.locks[key]

    async def ensure_invoice(self, p, *, fresh=False):
        if p['invoice_id'] and p['pay_url']:
            return p
        if fresh:
            try:
                invoice = await self.client.create(p)
            except PaymentError as exc:
                if not exc.ambiguous:
                    await self.store.release(p['id'], 'failed')
                raise
        else:
            # Recover a successful createInvoice with a lost response, don't charge twice.
            invoice = next((i for i in await self.client.invoices() if i.get('payload') == p['payload']), None)
            if not invoice:
                raise PaymentError('Счёт ещё обрабатывается. Повторите через несколько секунд.', ambiguous=True)
        validate_invoice(invoice, p)
        await self.store.bind(p['id'], invoice, invoice_url(invoice))
        await self.store.apply(invoice)
        return await self.store.get(p['id'])

    async def close_invoice(self, p, *, status='expired'):
        if p['status'] == 'paid':
            return False
        if not p['invoice_id']:
            p = await self.ensure_invoice(p)
            if p['status'] == 'paid':
                await self.deliver(p['id'])
                return False
        items = await self.client.invoices([p['invoice_id']])
        invoice = next((i for i in items if i.get('invoice_id') == p['invoice_id']), None)
        if not invoice:
            # A locally persisted URL is never cancelled based merely on an empty API response.
            raise PaymentError('Не удалось проверить предыдущий счёт. Повторите позже.')
        settled = await self.store.apply(invoice)
        if settled['status'] == 'paid':
            await self.deliver(p['id'])
            return False
        if invoice['status'] == 'active':
            try:
                await self.client.delete(p['invoice_id'])
            except PaymentError:
                # Payment and invoice deletion can race. Always re-check before releasing stock.
                items = await self.client.invoices([p['invoice_id']])
                invoice = next((i for i in items if i.get('invoice_id') == p['invoice_id']), None)
                if invoice and invoice.get('status') == 'paid':
                    await self.store.apply(invoice)
                    await self.deliver(p['id'])
                    return False
                raise
        await self.store.release(p['id'], status)
        return True

    async def checkout(self, owner: int, purpose: str, *, product_id=None, count=1, amount=None):
        if not self.client.token:
            raise PaymentError('Crypto Bot пока не настроен. Выберите оплату через администратора.')
        async with self.lock(owner, purpose, product_id):
            existing = await self.store.current(owner, purpose, product_id, amount)
            if existing and existing['quantity'] != count:
                await self.close_invoice(existing)
            p, fresh = await self.store.prepare(owner, purpose, product_id=product_id, count=count, amount=amount)
            return await self.ensure_invoice(p, fresh=fresh)

    async def check(self, payment_id: int, owner: int):
        p = await self.store.get(payment_id, owner)
        if not p:
            raise ValueError('Этот счёт недоступен.')
        if p['status'] == 'paid':
            await self.deliver(p['id'])
            return p
        if not p['invoice_id']:
            p = await self.ensure_invoice(p)
        items = await self.client.invoices([p['invoice_id']])
        invoice = next((i for i in items if i.get('invoice_id') == p['invoice_id']), None)
        if not invoice:
            raise PaymentError('Счёт не найден в Crypto Bot. Попробуйте позже.')
        p = await self.store.apply(invoice)
        if p['status'] == 'paid':
            await self.deliver(p['id'])
        return p

    async def balance_purchase(self, payment_id: int, owner: int):
        p = await self.store.get(payment_id, owner)
        if not p or p['purpose'] != 'product':
            raise ValueError('Счёт недоступен.')
        async with self.lock(owner, 'product', p['product_id']):
            p = await self.store.get(payment_id, owner)
            if p['status'] == 'paid':
                await self.deliver(payment_id)
                return p
            customer = await self.store.pool.fetchrow('SELECT balance FROM customers WHERE telegram_id=$1', owner)
            if not customer or customer['balance'] < p['amount']:
                raise ValueError('Недостаточно средств. Пополните кошелёк или оплатите через Crypto Bot.')
            if p['status'] in {'creating', 'pending'}:
                if not await self.close_invoice(p, status='balance_ready'):
                    return await self.store.get(payment_id, owner)
            p = await self.store.buy_balance(payment_id, owner)
            await self.deliver(payment_id)
            return p

    async def deliver(self, payment_id: int | None = None):
        if self.bot is None:
            return False
        p = await self.store.claim_delivery(payment_id)
        if not p:
            return False
        success = False
        if p['customer_id'] is not None and p['customer_id'] < 0:
            # Аккаунт сайта (почта): Telegram-чата нет, товар показывается на сайте в «Мои покупки».
            success = True
            await self.store.delivered(p['id'], p['delivery_claim'], success)
            return True
        try:
            total = f"{p['amount']:.2f} $"
            if p['outcome'] == 'topup':
                balance = await self.store.pool.fetchval('SELECT balance FROM customers WHERE telegram_id=$1', p['customer_id'])
                title = 'Дополнительная оплата возвращена на баланс ✅' if p['compensates_id'] else 'Баланс пополнен ✅'
                text = f'<b>{title}</b>\n\nЗачислено: <b>{total}</b>\nБаланс: <b>{balance:.2f} $</b>'
            elif p['outcome'] == 'wallet_refund':
                text = f'Оплата {total} получена. Товар недоступен, вся сумма зачислена на ваш баланс магазина.\nДля возврата через платёжную систему напишите @Ditzzmback.'
            else:
                items = json.loads(p['delivery_items']) if isinstance(p['delivery_items'], str) else p['delivery_items']
                header = f"<b>Оплата получена ✅</b>\n\n<b>{html.escape(p['product_name'])}</b> × {p['quantity']}\nСумма: <b>{total}</b>\n\n"
                # Send credential-safe chunks. Retrying may repeat the same goods, never issue new ones.
                chunks = [header]
                for index, item in enumerate(items, 1):
                    prefix = f'{index}. ' if len(items) > 1 else ''
                    # Split raw text before escaping; Telegram length limits use rendered text.
                    for offset in range(0, len(item), 2500):
                        chunk = f"{prefix}<code>{html.escape(item[offset:offset + 2500])}</code>\n"
                        if len(chunks[-1]) + len(chunk) > 3800:
                            chunks.append(chunk)
                        else:
                            chunks[-1] += chunk
                for text in chunks:
                    await self.bot.send_message(p['customer_id'], text, parse_mode='HTML')
                success = True
                return True
            await self.bot.send_message(p['customer_id'], text, parse_mode='HTML')
            success = True
            return True
        except Exception:
            # Telegram errors can contain credentials/URLs: log IDs only.
            logging.warning('Payment delivery postponed: payment=%s', p['id'])
            return False
        finally:
            await self.store.delivered(p['id'], p['delivery_claim'], success)

    async def reconcile(self):
        pending = await self.store.pending()
        ids = [p['invoice_id'] for p in pending if p['invoice_id']]
        legacy_ids = {r['provider_invoice_id'] for r in await self.store.legacy_pending()}
        ids += list(legacy_ids)
        invoices = await self.client.invoices(list(dict.fromkeys(ids))) if ids else []
        unbound = {p['payload']: p for p in pending if not p['invoice_id']}
        if unbound:
            for invoice in await self.client.invoices():
                p = unbound.get(invoice.get('payload'))
                if p:
                    validate_invoice(invoice, p)
                    await self.store.bind(p['id'], invoice, invoice_url(invoice))
                    invoices.append(invoice)
        for invoice in invoices:
            try:
                await self.store.apply(invoice)
            except ValueError:
                if invoice.get('invoice_id') in legacy_ids:
                    await self.close_legacy(invoice)
                else:
                    logging.warning('Crypto Pay invoice validation failed: id=%s', invoice.get('invoice_id'))
        if pending:
            await self.store.pool.execute('UPDATE payments SET last_checked_at=NOW() WHERE id=ANY($1::bigint[])', [p['id'] for p in pending])
        # Free reservations only after an authoritative expired result. Unbound ambiguous
        # creations get ten minutes for webhook/API recovery before their hold expires.
        for p in pending:
            if not p['invoice_id'] and p['payload'] not in {i.get('payload') for i in invoices}:
                expired = await self.store.pool.fetchval('SELECT expires_at<=NOW() FROM payments WHERE id=$1', p['id'])
                if expired:
                    await self.store.release(p['id'])

    async def close_legacy(self, invoice: dict):
        """Old RUB invoices from the first bot version never match the USD checks.
        Close them so they stop being polled every 30 seconds; paid ones go to manual review."""
        status = invoice.get('status')
        if status == 'active':
            return
        new_status = 'needs_review' if status == 'paid' else 'expired'
        await self.store.pool.execute("UPDATE orders SET status=$1 WHERE provider='crypto_pay' AND status='pending' AND provider_invoice_id=$2",
                                      new_status, invoice.get('invoice_id'))
        if new_status == 'needs_review':
            logging.warning('Old Crypto Pay invoice was paid, check the order manually: id=%s', invoice.get('invoice_id'))
        else:
            logging.info('Old Crypto Pay invoice closed: id=%s', invoice.get('invoice_id'))

    async def run(self):
        while True:
            try:
                if self.client.token:
                    await self.reconcile()
            except Exception:
                logging.warning('Crypto Pay reconciliation postponed; retry in 30 seconds')
            try:
                for _ in range(20):
                    if not await self.deliver():
                        break
            except Exception:
                logging.warning('Payment notifications postponed')
            await asyncio.sleep(30)
