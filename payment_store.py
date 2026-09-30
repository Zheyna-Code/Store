"""Durable, idempotent payment ledger. Top-ups never inflate shop sales analytics."""
from __future__ import annotations

import json
import secrets
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from crypto_pay import money, quantity, validate_invoice

PAYMENT_SCHEMA = """
ALTER TABLE stock_items ADD COLUMN IF NOT EXISTS reservation_key TEXT;
ALTER TABLE stock_items ADD COLUMN IF NOT EXISTS reserved_until TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity INTEGER NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(telegram_id),
    purpose TEXT NOT NULL CHECK(purpose IN ('topup','product')),
    provider TEXT NOT NULL DEFAULT 'crypto_pay',
    product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
    product_name TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity BETWEEN 1 AND 100),
    amount NUMERIC(12,2) NOT NULL CHECK(amount > 0),
    payload TEXT NOT NULL UNIQUE,
    invoice_id BIGINT UNIQUE,
    pay_url TEXT,
    order_id BIGINT UNIQUE REFERENCES orders(id),
    status TEXT NOT NULL DEFAULT 'creating',
    outcome TEXT,
    delivery_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '10 minutes',
    last_checked_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    delivery_claim TEXT,
    delivery_claimed_at TIMESTAMPTZ,
    delivery_attempt_at TIMESTAMPTZ
);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS compensates_id BIGINT UNIQUE REFERENCES payments(id);
CREATE INDEX IF NOT EXISTS payments_pending_idx ON payments(last_checked_at, id)
    WHERE status IN ('creating','pending');
CREATE INDEX IF NOT EXISTS payments_delivery_idx ON payments(id)
    WHERE status='paid' AND delivered_at IS NULL;
CREATE INDEX IF NOT EXISTS stock_available_idx ON stock_items(product_id,id) WHERE NOT is_issued;
"""

FREE_STOCK = "NOT is_issued AND (reserved_until IS NULL OR reserved_until <= NOW())"


class PaymentStore:
    def __init__(self, pool):
        self.pool = pool

    async def get(self, payment_id: int, customer_id: int | None = None):
        return await self.pool.fetchrow('SELECT * FROM payments WHERE id=$1 AND ($2::bigint IS NULL OR customer_id=$2)', payment_id, customer_id)

    async def current(self, customer_id: int, purpose: str, product_id: int | None = None, amount=None):
        return await self.pool.fetchrow("""SELECT * FROM payments WHERE customer_id=$1 AND purpose=$2
            AND product_id IS NOT DISTINCT FROM $3 AND status IN ('creating','pending') AND expires_at>NOW()
            AND ($4::numeric IS NULL OR amount=$4) ORDER BY id DESC LIMIT 1""", customer_id, purpose, product_id, amount)

    async def available(self, product_id: int, customer_id: int | None = None) -> int:
        return await self.pool.fetchval(f"""SELECT COUNT(*) FROM stock_items s WHERE product_id=$1 AND NOT is_issued
            AND (reserved_until IS NULL OR reserved_until<=NOW() OR reservation_key IN
                (SELECT payload FROM payments WHERE customer_id=$2 AND product_id=$1 AND status IN ('creating','pending')))""", product_id, customer_id)

    async def prepare(self, customer_id: int, purpose: str, *, product_id=None, count=1, amount=None):
        count = quantity(count)
        if purpose not in {'topup', 'product'}:
            raise ValueError('Неизвестный тип платежа')
        async with self.pool.acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock($1)', customer_id)
            customer = await c.fetchrow('SELECT * FROM customers WHERE telegram_id=$1', customer_id)
            if not customer:
                raise ValueError('Сначала откройте /start в личном чате с ботом.')
            existing = await c.fetchrow("""SELECT * FROM payments WHERE customer_id=$1 AND purpose=$2
                AND product_id IS NOT DISTINCT FROM $3 AND status IN ('creating','pending') AND expires_at>NOW()
                AND ($4::numeric IS NULL OR amount=$4) ORDER BY id DESC LIMIT 1 FOR UPDATE""",
                customer_id, purpose, product_id, money(amount) if purpose == 'topup' else None)
            if existing:
                if existing['quantity'] != count:
                    raise ValueError('Сначала закройте предыдущий счёт для изменения количества.')
                return existing, False
            await c.fetchval('SELECT telegram_id FROM customers WHERE telegram_id=$1 FOR UPDATE', customer_id)
            name = ''
            stock = []
            if purpose == 'product':
                product = await c.fetchrow('SELECT * FROM products WHERE id=$1 AND is_active FOR UPDATE', product_id)
                if not product:
                    raise ValueError('Товар недоступен.')
                amount = money(product['price'] * count)
                name = product['name']
                stock = await c.fetch(f'SELECT id FROM stock_items WHERE product_id=$1 AND {FREE_STOCK} ORDER BY id LIMIT $2 FOR UPDATE', product_id, count)
                if len(stock) != count:
                    raise ValueError('Не хватает товара в наличии. Уменьшите количество.')
            else:
                amount = money(amount, maximum=Decimal('10000'))
            payment = await c.fetchrow("""INSERT INTO payments(customer_id,purpose,product_id,product_name,quantity,amount,payload)
                VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *""", customer_id, purpose, product_id, name, count, amount, 'shop:' + secrets.token_urlsafe(24))
            if stock:
                await c.execute('UPDATE stock_items SET reservation_key=$1,reserved_until=$2 WHERE id=ANY($3::bigint[])',
                                payment['payload'], payment['expires_at'], [s['id'] for s in stock])
                order_id = await c.fetchval("""INSERT INTO orders(customer_id,product_id,amount,quantity,status,provider)
                    VALUES($1,$2,$3,$4,'pending','crypto_pay') RETURNING id""", customer_id, product_id, amount, count)
                payment = await c.fetchrow('UPDATE payments SET order_id=$1 WHERE id=$2 RETURNING *', order_id, payment['id'])
            return payment, True

    async def release(self, payment_id: int, status='expired'):
        async with self.pool.acquire() as c, c.transaction():
            p = await c.fetchrow("UPDATE payments SET status=$2,last_checked_at=NOW() WHERE id=$1 AND status IN ('creating','pending') RETURNING *", payment_id, status)
            if p:
                await c.execute('UPDATE stock_items SET reservation_key=NULL,reserved_until=NULL WHERE reservation_key=$1', p['payload'])
                await c.execute("UPDATE orders SET status=$1 WHERE id=$2 AND status='pending'", status, p['order_id'])

    async def bind(self, payment_id: int, invoice: dict, url: str):
        async with self.pool.acquire() as c, c.transaction():
            p = await c.fetchrow('SELECT * FROM payments WHERE id=$1 FOR UPDATE', payment_id)
            validate_invoice(invoice, p)
            # Provider expiration starts on creation, which can be later than local prepare.
            # Keep a one-minute hold grace so a slow API response cannot expose reserved goods.
            expires = p['expires_at'] + timedelta(seconds=60)
            if invoice.get('expiration_date'):
                try:
                    provider_expiry = datetime.fromisoformat(invoice['expiration_date'].replace('Z', '+00:00'))
                    if provider_expiry.tzinfo is not None:
                        expires = provider_expiry + timedelta(seconds=60)
                except (ValueError, TypeError, AttributeError):
                    pass
            await c.execute('UPDATE payments SET expires_at=$1 WHERE id=$2', expires, p['id'])
            await c.execute('UPDATE stock_items SET reserved_until=$1 WHERE reservation_key=$2 AND NOT is_issued', expires, p['payload'])
            await c.execute("""UPDATE payments SET invoice_id=$1,pay_url=$2,
                status=CASE WHEN status='creating' THEN 'pending' ELSE status END WHERE id=$3""", invoice['invoice_id'], url, payment_id)
            await c.execute('UPDATE orders SET provider_invoice_id=$1 WHERE id=$2', invoice['invoice_id'], p['order_id'])

    async def locate(self, invoice: dict):
        """A signed event may arrive before createInvoice's response is persisted."""
        payload = invoice.get('payload')
        if not isinstance(payload, str):
            raise ValueError('Нет payload')
        p = await self.pool.fetchrow('SELECT * FROM payments WHERE payload=$1', payload)
        if p:
            return p
        # Adopt pending USD invoices issued by the previous version, never already paid history.
        if payload.isascii() and payload.isdigit():
            async with self.pool.acquire() as c, c.transaction():
                order = await c.fetchrow("""SELECT o.*,p.name FROM orders o LEFT JOIN products p ON p.id=o.product_id
                    WHERE o.id=$1 AND o.provider='crypto_pay' AND o.provider_invoice_id=$2
                    AND o.status='pending'""", int(payload), invoice.get('invoice_id'))
                if order and order['customer_id']:
                    candidate = dict(amount=order['amount'], invoice_id=order['provider_invoice_id'], payload=payload)
                    validate_invoice(invoice, candidate)
                    await c.execute("""INSERT INTO payments(customer_id,purpose,product_id,product_name,amount,payload,invoice_id,order_id,status)
                        VALUES($1,'product',$2,$3,$4,$5,$6,$7,'pending') ON CONFLICT(payload) DO NOTHING""",
                        order['customer_id'], order['product_id'], order['name'] or 'Товар', order['amount'], payload, order['provider_invoice_id'], order['id'])
                    return await c.fetchrow('SELECT * FROM payments WHERE payload=$1', payload)
        return None

    async def apply(self, invoice: dict):
        p = await self.locate(invoice)
        if not p:
            return None
        async with self.pool.acquire() as c, c.transaction():
            p = await c.fetchrow('SELECT * FROM payments WHERE id=$1 FOR UPDATE', p['id'])
            validate_invoice(invoice, p)
            await c.execute('UPDATE payments SET invoice_id=$1,last_checked_at=NOW() WHERE id=$2', invoice['invoice_id'], p['id'])
            if p['status'] == 'paid':
                # A crypto payment can race with switching to wallet payment. Never discard
                # that second receipt: compensate on the shop balance exactly once.
                if p['provider'] == 'balance' and invoice['status'] == 'paid':
                    compensation = await c.fetchrow("""INSERT INTO payments(customer_id,purpose,amount,payload,status,outcome,compensates_id)
                        VALUES($1,'topup',$2,$3,'paid','topup',$4) ON CONFLICT(compensates_id) DO NOTHING RETURNING *""",
                        p['customer_id'], p['amount'], 'compensation:' + p['payload'], p['id'])
                    if compensation:
                        await c.execute('UPDATE customers SET balance=balance+$1 WHERE telegram_id=$2', p['amount'], p['customer_id'])
                        await c.execute('INSERT INTO balance_transactions(customer_id,amount,reason) VALUES($1,$2,$3)',
                                        p['customer_id'], p['amount'], f"Дополнительная Crypto Pay оплата покупки с баланса #{p['id']}")
                    return compensation or await c.fetchrow('SELECT * FROM payments WHERE compensates_id=$1', p['id'])
                return p
            if invoice['status'] != 'paid':
                if invoice['status'] == 'expired':
                    await c.execute("UPDATE payments SET status='expired' WHERE id=$1", p['id'])
                    await c.execute('UPDATE stock_items SET reservation_key=NULL,reserved_until=NULL WHERE reservation_key=$1', p['payload'])
                    await c.execute("UPDATE orders SET status='expired' WHERE id=$1 AND status='pending'", p['order_id'])
                return await c.fetchrow('SELECT * FROM payments WHERE id=$1', p['id'])
            await c.fetchval('SELECT telegram_id FROM customers WHERE telegram_id=$1 FOR UPDATE', p['customer_id'])
            outcome = 'topup'
            stock = []
            if p['purpose'] == 'product':
                # Lock the product consistently with checkout and admin stock replacement.
                if p['product_id']:
                    await c.fetchval('SELECT id FROM products WHERE id=$1 FOR UPDATE', p['product_id'])
                stock = await c.fetch(f"""SELECT id,payload FROM stock_items WHERE product_id=$1 AND NOT is_issued
                    AND (reservation_key=$2 OR reserved_until IS NULL OR reserved_until<=NOW())
                    ORDER BY (reservation_key=$2) DESC NULLS LAST,id LIMIT $3 FOR UPDATE""", p['product_id'], p['payload'], p['quantity'])
                if len(stock) == p['quantity']:
                    outcome = 'product'
                    await c.execute('UPDATE stock_items SET is_issued=TRUE,issued_at=NOW(),reservation_key=NULL,reserved_until=NULL WHERE id=ANY($1::bigint[])', [s['id'] for s in stock])
                else:
                    outcome = 'wallet_refund'
                    stock = []
                await c.execute("""UPDATE orders SET status=$1,provider_invoice_id=$2,stock_item_id=$3 WHERE id=$4""",
                                'paid' if outcome == 'product' else 'paid_no_stock', invoice['invoice_id'], stock[0]['id'] if stock else None, p['order_id'])
            if outcome != 'product':
                await c.execute('UPDATE customers SET balance=balance+$1 WHERE telegram_id=$2', p['amount'], p['customer_id'])
                await c.execute('INSERT INTO balance_transactions(customer_id,amount,reason) VALUES($1,$2,$3)', p['customer_id'], p['amount'],
                                ('Crypto Pay пополнение #' if outcome == 'topup' else 'Товар недоступен: возврат на баланс #') + str(p['id']))
            await c.execute('UPDATE stock_items SET reservation_key=NULL,reserved_until=NULL WHERE reservation_key=$1', p['payload'])
            return await c.fetchrow("""UPDATE payments SET status='paid',outcome=$1,delivery_items=$2::jsonb WHERE id=$3 RETURNING *""",
                                   outcome, json.dumps([s['payload'] for s in stock]), p['id'])

    async def buy_balance(self, payment_id: int, customer_id: int):
        """Spend an invoice's immutable total exactly once; crypto invoice must be deleted first."""
        async with self.pool.acquire() as c, c.transaction():
            p = await c.fetchrow('SELECT * FROM payments WHERE id=$1 AND customer_id=$2 FOR UPDATE', payment_id, customer_id)
            if not p or p['purpose'] != 'product':
                raise ValueError('Счёт не найден.')
            if p['status'] == 'paid':
                return p
            if p['status'] != 'balance_ready' or p['expires_at'] <= datetime.now(timezone.utc):
                raise ValueError('Счёт уже закрыт. Откройте карточку товара снова.')
            customer = await c.fetchrow('SELECT * FROM customers WHERE telegram_id=$1 FOR UPDATE', customer_id)
            if customer['balance'] < p['amount']:
                raise ValueError('Недостаточно средств на балансе.')
            await c.fetchval('SELECT id FROM products WHERE id=$1 FOR UPDATE', p['product_id'])
            stock = await c.fetch(f'SELECT id,payload FROM stock_items WHERE product_id=$1 AND {FREE_STOCK} ORDER BY id LIMIT $2 FOR UPDATE', p['product_id'], p['quantity'])
            if len(stock) != p['quantity']:
                raise ValueError('Товар закончился, деньги не списаны.')
            await c.execute('UPDATE customers SET balance=balance-$1 WHERE telegram_id=$2', p['amount'], customer_id)
            await c.execute('INSERT INTO balance_transactions(customer_id,amount,reason) VALUES($1,$2,$3)', customer_id, -p['amount'], f"Покупка #{p['order_id']}")
            await c.execute('UPDATE stock_items SET is_issued=TRUE,issued_at=NOW(),reservation_key=NULL,reserved_until=NULL WHERE id=ANY($1::bigint[])', [s['id'] for s in stock])
            await c.execute("UPDATE orders SET status='paid',provider='balance',stock_item_id=$1 WHERE id=$2", stock[0]['id'], p['order_id'])
            return await c.fetchrow("UPDATE payments SET status='paid',provider='balance',outcome='product',delivery_items=$1::jsonb WHERE id=$2 RETURNING *", json.dumps([s['payload'] for s in stock]), p['id'])

    async def pending(self):
        return await self.pool.fetch("""SELECT * FROM payments WHERE (provider='crypto_pay' AND status IN ('creating','pending'))
            OR (provider='balance' AND status='paid' AND invoice_id IS NOT NULL AND expires_at>NOW()-INTERVAL '20 minutes')
            ORDER BY last_checked_at NULLS FIRST,id LIMIT 50""")

    async def legacy_pending(self):
        return await self.pool.fetch("""SELECT provider_invoice_id FROM orders WHERE provider='crypto_pay' AND status='pending'
            AND provider_invoice_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM payments WHERE payments.order_id=orders.id)
            ORDER BY id DESC LIMIT 50""")

    async def claim_delivery(self, payment_id: int | None = None):
        token = secrets.token_urlsafe(18)
        async with self.pool.acquire() as c, c.transaction():
            p = await c.fetchrow("""SELECT * FROM payments WHERE status='paid' AND delivered_at IS NULL
                AND ($1::bigint IS NULL OR id=$1) AND (delivery_claimed_at IS NULL OR delivery_claimed_at<NOW()-INTERVAL '5 minutes')
                AND (delivery_attempt_at IS NULL OR delivery_attempt_at<NOW()-INTERVAL '30 seconds')
                ORDER BY delivery_attempt_at NULLS FIRST,id LIMIT 1 FOR UPDATE SKIP LOCKED""", payment_id)
            if not p:
                return None
            return await c.fetchrow('UPDATE payments SET delivery_claim=$1,delivery_claimed_at=NOW(),delivery_attempt_at=NOW() WHERE id=$2 RETURNING *', token, p['id'])

    async def delivered(self, payment_id: int, token: str, success: bool):
        await self.pool.execute("""UPDATE payments SET delivered_at=CASE WHEN $3 THEN NOW() ELSE delivered_at END,
            delivery_claim=NULL,delivery_claimed_at=NULL WHERE id=$1 AND delivery_claim=$2""", payment_id, token, success)
