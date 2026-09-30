"""Personal links and one 5% reward for each newly invited customer's first purchase."""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

BOT_USERNAME = 'wanderersshop_bot'
REFERRAL_RATE = Decimal('0.05')
MAX_USER_ID = 2**63 - 1

REFERRAL_SCHEMA = """
ALTER TABLE customers ADD COLUMN IF NOT EXISTS referred_by BIGINT REFERENCES customers(telegram_id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS customers_referred_by_idx ON customers(referred_by) WHERE referred_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS orders_paid_customer_idx ON orders(customer_id) WHERE status='paid';
CREATE TABLE IF NOT EXISTS referral_rewards (
    invitee_id BIGINT PRIMARY KEY REFERENCES customers(telegram_id),
    referrer_id BIGINT NOT NULL REFERENCES customers(telegram_id),
    order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id),
    amount NUMERIC(12,2) NOT NULL CHECK(amount >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS referral_rewards_referrer_idx ON referral_rewards(referrer_id);
"""


def referral_link(user_id: int) -> str:
    if isinstance(user_id, bool) or not isinstance(user_id, int) or not 0 < user_id <= MAX_USER_ID:
        raise ValueError('Invalid Telegram user ID')
    return f'https://t.me/{BOT_USERNAME}?start=ref_{user_id}'


def start_referrer(text: str | None) -> int | None:
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r'/start(?:@wanderersshop_bot)?\s+ref_([1-9][0-9]{0,18})\s*', text, re.IGNORECASE)
    if not match:
        return None
    value = int(match[1])
    return value if value <= MAX_USER_ID else None


async def lock_purchase_accounts(connection, customer_id: int):
    """Lock buyer + inviter in a fixed order BEFORE taking a product/stock lock."""
    referrer = await connection.fetchval('SELECT referred_by FROM customers WHERE telegram_id=$1', customer_id)
    ids = sorted({customer_id, referrer} if referrer else {customer_id})
    rows = await connection.fetch('SELECT * FROM customers WHERE telegram_id=ANY($1::bigint[]) ORDER BY telegram_id FOR UPDATE', ids)
    return next((row for row in rows if row['telegram_id'] == customer_id), None)


async def award_referral(connection, customer_id: int, order_id: int, paid_amount: Decimal):
    referrer = await connection.fetchval('SELECT referred_by FROM customers WHERE telegram_id=$1', customer_id)
    if not referrer or referrer == customer_id:
        return None
    paid_orders = await connection.fetchval("SELECT COUNT(*) FROM orders WHERE customer_id=$1 AND status='paid'", customer_id)
    if paid_orders != 1:
        return None
    amount = (paid_amount * REFERRAL_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    reward = await connection.fetchrow("""INSERT INTO referral_rewards(invitee_id,referrer_id,order_id,amount)
        VALUES($1,$2,$3,$4) ON CONFLICT(invitee_id) DO NOTHING RETURNING *""", customer_id, referrer, order_id, amount)
    if reward and amount > 0:
        await connection.execute('UPDATE customers SET balance=balance+$1 WHERE telegram_id=$2', amount, referrer)
        await connection.execute('INSERT INTO balance_transactions(customer_id,amount,reason) VALUES($1,$2,$3)',
            referrer, amount, f'Реферальный бонус 5% за первую покупку пользователя {customer_id}, заказ #{order_id}')
    return reward
