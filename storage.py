"""PostgreSQL storage for the shop and its admin panel."""

from __future__ import annotations

import json
from emoji_library import validate_emoji_id
from payment_store import PAYMENT_SCHEMA
from referrals import REFERRAL_SCHEMA, MAX_USER_ID
from web_auth import WEB_SCHEMA

from decimal import Decimal
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import asyncpg


DEFAULT_CATEGORIES = (
    "ChatGPT", "Claude", "Gemini", "Notion", "Grok",
    "Perplexity", "Netflix", "Duolingo", "CapCut", "Spotify",
)


def public_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, (date, datetime)) else str(value) if isinstance(value, Decimal) else value
        for key, value in dict(row).items()
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS categories (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE categories ADD COLUMN IF NOT EXISTS custom_emoji_id TEXT;
ALTER TABLE categories ADD COLUMN IF NOT EXISTS emoji_fallback TEXT NOT NULL DEFAULT '🛍';
CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    category_id BIGINT REFERENCES categories(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price NUMERIC(12, 2) NOT NULL CHECK(price >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS stock_items (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    payload TEXT NOT NULL,
    is_issued BOOLEAN NOT NULL DEFAULT FALSE,
    issued_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS customers (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT NOT NULL DEFAULT '',
    balance NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK(balance >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS customers_username_idx ON customers (LOWER(username));
CREATE TABLE IF NOT EXISTS balance_transactions (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(telegram_id) ON DELETE CASCADE,
    amount NUMERIC(12, 2) NOT NULL,
    reason TEXT NOT NULL DEFAULT 'Выдано администратором',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(telegram_id) ON DELETE SET NULL,
    product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK(amount >= 0),
    status TEXT NOT NULL DEFAULT 'paid',
    provider TEXT,
    provider_invoice_id BIGINT UNIQUE,
    stock_item_id BIGINT REFERENCES stock_items(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS orders_created_at_idx ON orders(created_at);
CREATE TABLE IF NOT EXISTS page_visits (
    id BIGSERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    visitor_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS page_visits_created_at_idx ON page_visits(created_at);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS provider TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS provider_invoice_id BIGINT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS stock_item_id BIGINT REFERENCES stock_items(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX IF NOT EXISTS orders_provider_invoice_id_idx ON orders(provider_invoice_id) WHERE provider_invoice_id IS NOT NULL;
"""

SCHEMA += PAYMENT_SCHEMA + REFERRAL_SCHEMA + WEB_SCHEMA


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        async with self.pool.acquire() as connection:
            await connection.execute(SCHEMA)
            # Only bootstrap a fresh shop. Admin edits must survive subsequent restarts.
            if not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM categories)"):
                await connection.executemany(
                    """INSERT INTO categories(name, sort_order) VALUES($1, $2)
                       ON CONFLICT (name) DO NOTHING""",
                    [(name, position) for position, name in enumerate(DEFAULT_CATEGORIES, 1)],
                )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def _pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("База данных ещё не подключена")
        return self.pool

    async def upsert_customer(self, telegram_id: int, username: str | None, first_name: str, referrer_id: int | None = None) -> None:
        if not isinstance(referrer_id, int) or isinstance(referrer_id, bool) or not 0 < referrer_id <= MAX_USER_ID:
            referrer_id = None
        # Attach an inviter only on initial registration. Existing users can't rebind;
        # self-referrals and unknown inviter IDs are ignored in the same SQL statement.
        await self._pool().execute(
            """INSERT INTO customers(telegram_id, username, first_name, referred_by)
               VALUES($1,$2,$3,CASE WHEN $4::bigint IS NOT NULL AND $4<>$1
                   AND EXISTS(SELECT 1 FROM customers WHERE telegram_id=$4) THEN $4 ELSE NULL END)
               ON CONFLICT (telegram_id) DO UPDATE SET username=EXCLUDED.username,
                   first_name=EXCLUDED.first_name, last_seen_at=NOW()""",
            telegram_id, username, first_name, referrer_id,
        )

    async def referral_stats(self, telegram_id: int) -> dict[str, Any]:
        row = await self._pool().fetchrow("""SELECT
            (SELECT COUNT(*) FROM customers WHERE referred_by=$1) AS invited,
            (SELECT COALESCE(SUM(amount),0) FROM referral_rewards WHERE referrer_id=$1) AS earned,
            (SELECT COUNT(*) FROM orders WHERE customer_id=$1 AND status='paid') AS purchases""", telegram_id)
        return public_row(row)

    async def customer(self, telegram_id: int) -> asyncpg.Record | None:
        return await self._pool().fetchrow("SELECT * FROM customers WHERE telegram_id=$1", telegram_id)

    async def dashboard(self) -> dict[str, Any]:
        p = self._pool()
        totals = await p.fetchrow("""SELECT COALESCE(SUM(amount), 0) AS revenue,
            COALESCE(SUM(amount) FILTER (WHERE created_at >= date_trunc('day', NOW())), 0) AS today_revenue,
            COUNT(*) AS orders FROM orders WHERE status='paid'""")
        visits = await p.fetchval("SELECT COUNT(DISTINCT COALESCE(visitor_key, id::text)) FROM page_visits WHERE created_at >= date_trunc('day', NOW())")
        top_categories = await p.fetch("""SELECT COALESCE(c.name, 'Без категории') AS name, SUM(o.quantity) AS sales,
            COALESCE(SUM(o.amount), 0) AS revenue FROM categories c
            RIGHT JOIN products p ON p.category_id=c.id RIGHT JOIN orders o ON o.product_id=p.id
            WHERE o.status='paid' GROUP BY c.name ORDER BY revenue DESC, sales DESC LIMIT 50""")
        return {"revenue": str(totals["revenue"]), "today_revenue": str(totals["today_revenue"]),
                "orders": totals["orders"], "today_visits": visits,
                "top_categories": [dict(row) | {"revenue": str(row["revenue"])} for row in top_categories]}

    async def analytics(self, days: int = 30, tz_offset: int = 0) -> dict[str, Any]:
        """Данные для графиков: по дням, сравнение с прошлым периодом, статусы и топ товаров."""
        days = max(1, min(int(days), 365))
        tz_offset = max(-14 * 60, min(int(tz_offset), 14 * 60))
        shift = timedelta(minutes=tz_offset)
        today = (datetime.now(timezone.utc) + shift).date()
        first = today - timedelta(days=days - 1)
        current_start = datetime.combine(first, time.min, tzinfo=timezone.utc) - shift
        previous_start = current_start - timedelta(days=days)
        p = self._pool()
        day_sql = "((created_at AT TIME ZONE 'UTC') + make_interval(mins => $2::int))::date"
        paid = await p.fetch(f"""SELECT {day_sql} AS day, COUNT(*) AS orders, COALESCE(SUM(amount), 0) AS revenue
            FROM orders WHERE status='paid' AND created_at >= $1 GROUP BY 1""", previous_start, tz_offset)
        customers = await p.fetch(f"""SELECT {day_sql} AS day, COUNT(*) AS n
            FROM customers WHERE created_at >= $1 GROUP BY 1""", previous_start, tz_offset)
        visits = await p.fetch(f"""SELECT {day_sql} AS day, COUNT(DISTINCT COALESCE(visitor_key, id::text)) AS n
            FROM page_visits WHERE created_at >= $1 GROUP BY 1""", previous_start, tz_offset)
        statuses = await p.fetch("SELECT status, COUNT(*) AS n FROM orders WHERE created_at >= $1 GROUP BY status", current_start)
        top = await p.fetch("""SELECT COALESCE(p.name, 'Удалённый товар') AS name, SUM(o.quantity) AS sales, COALESCE(SUM(o.amount), 0) AS revenue
            FROM orders o LEFT JOIN products p ON p.id=o.product_id
            WHERE o.status='paid' AND o.created_at >= $1 GROUP BY p.id, p.name ORDER BY revenue DESC, sales DESC LIMIT 8""", current_start)
        series = {first + timedelta(days=i): {"revenue": 0.0, "orders": 0, "customers": 0, "visits": 0} for i in range(days)}
        current = {"revenue": 0.0, "orders": 0, "customers": 0, "visits": 0}
        previous = dict(current)

        def add(rows: list[asyncpg.Record], fields: dict[str, str]) -> None:
            for row in rows:
                bucket = current if row["day"] >= first else previous
                for target, source in fields.items():
                    value = float(row[source]) if target == "revenue" else int(row[source])
                    bucket[target] += value
                    if row["day"] >= first and row["day"] in series:
                        series[row["day"]][target] += value

        add(paid, {"revenue": "revenue", "orders": "orders"})
        add(customers, {"customers": "n"})
        add(visits, {"visits": "n"})
        return {
            "days": days,
            "series": [{"date": day.isoformat(), **values} for day, values in sorted(series.items())],
            "statuses": {row["status"]: row["n"] for row in statuses},
            "top_products": [{"name": row["name"], "sales": row["sales"], "revenue": float(row["revenue"])} for row in top],
            "current": current,
            "previous": previous,
        }

    async def list_categories(self) -> list[dict[str, Any]]:
        rows = await self._pool().fetch("SELECT * FROM categories ORDER BY sort_order, name")
        return [public_row(row) for row in rows]

    async def active_categories(self) -> list[dict[str, Any]]:
        rows = await self._pool().fetch("SELECT id, name, custom_emoji_id, emoji_fallback FROM categories WHERE is_active ORDER BY sort_order, name")
        return [dict(row) for row in rows]

    async def save_category(self, data: dict[str, Any], category_id: int | None = None) -> dict[str, Any]:
        # Older clients changing visibility/order must not erase the selected emoji.
        has_emoji = "custom_emoji_id" in data
        emoji_id = data.get("custom_emoji_id")
        if emoji_id:
            emoji_id = validate_emoji_id(emoji_id)
        else:
            emoji_id = None
        fallback = str(data.get("emoji_fallback") or "🛍")[:16]
        if category_id:
            row = await self._pool().fetchrow("""UPDATE categories SET name=$1, sort_order=$2, is_active=$3,
                custom_emoji_id=CASE WHEN $4 THEN $5 ELSE custom_emoji_id END,
                emoji_fallback=CASE WHEN $4 THEN $6 ELSE emoji_fallback END
                WHERE id=$7 RETURNING *""", data["name"], data.get("sort_order", 0), data.get("is_active", True),
                has_emoji, emoji_id, fallback, category_id)
        else:
            row = await self._pool().fetchrow("""INSERT INTO categories(name,sort_order,is_active,custom_emoji_id,emoji_fallback)
                VALUES($1,$2,$3,$4,$5) RETURNING *""", data["name"], data.get("sort_order", 0),
                data.get("is_active", True), emoji_id, fallback)
        if not row:
            raise ValueError("Категория не найдена")
        return public_row(row)

    async def emoji_settings(self) -> dict[str, str]:
        value = await self._pool().fetchval("SELECT value FROM shop_settings WHERE key='emojis'")
        return json.loads(value) if isinstance(value, str) else (value or {})

    async def save_emoji_settings(self, values: dict[str, str]) -> dict[str, str]:
        value = await self._pool().fetchval("""INSERT INTO shop_settings(key,value) VALUES('emojis',$1::jsonb)
            ON CONFLICT(key) DO UPDATE SET value=shop_settings.value || EXCLUDED.value RETURNING value""",
            json.dumps(values))
        return json.loads(value) if isinstance(value, str) else value

    async def list_products(self) -> list[dict[str, Any]]:
        rows = await self._pool().fetch("""SELECT p.*, c.name AS category_name,
             COUNT(s.id) FILTER (WHERE NOT s.is_issued AND (s.reserved_until IS NULL OR s.reserved_until <= NOW())) AS stock_count
             FROM products p LEFT JOIN categories c ON c.id=p.category_id
             LEFT JOIN stock_items s ON s.product_id=p.id GROUP BY p.id, c.name ORDER BY p.created_at DESC""")
        return [public_row(row) for row in rows]

    async def product(self, product_id: int) -> dict[str, Any] | None:
        row = await self._pool().fetchrow("""SELECT p.*, c.name AS category_name, c.custom_emoji_id AS category_emoji_id,
            c.emoji_fallback AS category_emoji_fallback FROM products p LEFT JOIN categories c ON c.id=p.category_id
            WHERE p.id=$1""", product_id)
        return public_row(row) if row else None

    async def active_products(self) -> list[dict[str, Any]]:
        rows = await self._pool().fetch("""SELECT p.*, COUNT(s.id) FILTER (WHERE NOT s.is_issued AND (s.reserved_until IS NULL OR s.reserved_until <= NOW())) AS stock_count
            FROM products p LEFT JOIN stock_items s ON s.product_id=p.id
            WHERE p.is_active GROUP BY p.id HAVING COUNT(s.id) FILTER (WHERE NOT s.is_issued AND (s.reserved_until IS NULL OR s.reserved_until <= NOW())) > 0 ORDER BY p.created_at DESC""")
        return [public_row(row) for row in rows]

    async def category_products(self, category_id: int) -> list[dict[str, Any]]:
        rows = await self._pool().fetch("""SELECT p.id, p.name, p.description, p.price,
            COUNT(s.id) FILTER (WHERE NOT s.is_issued AND (s.reserved_until IS NULL OR s.reserved_until <= NOW())) AS stock_count
            FROM products p LEFT JOIN stock_items s ON s.product_id=p.id
            WHERE p.category_id=$1 AND p.is_active GROUP BY p.id ORDER BY p.created_at DESC""", category_id)
        return [public_row(row) for row in rows]

    async def save_product(self, data: dict[str, Any], product_id: int | None = None) -> dict[str, Any]:
        values = (data["name"], data.get("description", ""), Decimal(str(data["price"])), data.get("category_id"), data.get("is_active", True))
        if product_id:
            row = await self._pool().fetchrow("UPDATE products SET name=$1, description=$2, price=$3, category_id=$4, is_active=$5, updated_at=NOW() WHERE id=$6 RETURNING *", *values, product_id)
        else:
            row = await self._pool().fetchrow("INSERT INTO products(name,description,price,category_id,is_active) VALUES($1,$2,$3,$4,$5) RETURNING *", *values)
        if not row:
            raise ValueError("Товар не найден")
        return public_row(row)

    async def delete_product(self, product_id: int) -> None:
        async with self._pool().acquire() as c, c.transaction():
            if not await c.fetchval("SELECT id FROM products WHERE id=$1 FOR UPDATE", product_id):
                raise ValueError("Товар не найден")
            if await c.fetchval("SELECT EXISTS(SELECT 1 FROM stock_items WHERE product_id=$1 AND NOT is_issued AND reserved_until>NOW())", product_id):
                raise ValueError("Товар зарезервирован под счёт. Удаление доступно после оплаты или истечения счёта.")
            await c.execute("DELETE FROM products WHERE id=$1", product_id)

    async def stock(self, product_id: int) -> list[dict[str, Any]]:
        rows = await self._pool().fetch("SELECT * FROM stock_items WHERE product_id=$1 ORDER BY id", product_id)
        return [public_row(row) for row in rows]

    async def replace_stock(self, product_id: int, items: list[str]) -> None:
        async with self._pool().acquire() as connection, connection.transaction():
            exists = await connection.fetchval("SELECT id FROM products WHERE id=$1 FOR UPDATE", product_id)
            if not exists:
                raise ValueError("Товар не найден")
            reserved = await connection.fetchval("SELECT EXISTS(SELECT 1 FROM stock_items WHERE product_id=$1 AND NOT is_issued AND reserved_until>NOW())", product_id)
            if reserved:
                raise ValueError("Есть товар, зарезервированный под счёт. Измените остаток после оплаты или истечения счёта.")
            await connection.execute("DELETE FROM stock_items WHERE product_id=$1 AND NOT is_issued", product_id)
            if items:
                await connection.executemany("INSERT INTO stock_items(product_id, payload) VALUES($1,$2)", [(product_id, item) for item in items if item.strip()])

    async def customers(self, query: str = "") -> list[dict[str, Any]]:
        rows = await self._pool().fetch("""SELECT c.*, COUNT(o.id) AS purchases FROM customers c LEFT JOIN orders o ON o.customer_id=c.telegram_id
            WHERE $1='' OR LOWER(COALESCE(c.username,'')) LIKE '%' || LOWER($1) || '%'
            GROUP BY c.telegram_id ORDER BY c.last_seen_at DESC LIMIT 200""", query.lstrip("@"))
        return [public_row(row) for row in rows]

    async def grant_balance(self, username: str, amount: Decimal, reason: str) -> dict[str, Any]:
        async with self._pool().acquire() as connection, connection.transaction():
            row = await connection.fetchrow("UPDATE customers SET balance=balance+$1 WHERE LOWER(username)=LOWER($2) RETURNING *", amount, username.lstrip("@"))
            if not row:
                raise ValueError("Покупатель с таким username не найден")
            await connection.execute("INSERT INTO balance_transactions(customer_id, amount, reason) VALUES($1,$2,$3)", row["telegram_id"], amount, reason or "Выдано администратором")
            return public_row(row)

    async def grant_balance_by_id(self, telegram_id: int, amount: Decimal, reason: str) -> dict[str, Any]:
        async with self._pool().acquire() as connection, connection.transaction():
            row = await connection.fetchrow("UPDATE customers SET balance=balance+$1 WHERE telegram_id=$2 RETURNING *", amount, telegram_id)
            if not row:
                raise ValueError("Покупатель не найден")
            await connection.execute("INSERT INTO balance_transactions(customer_id, amount, reason) VALUES($1,$2,$3)", row["telegram_id"], amount, reason or "Выдано администратором")
            return public_row(row)

    async def orders(self) -> list[dict[str, Any]]:
        rows = await self._pool().fetch("""SELECT o.*, p.name AS product_name, c.username, c.first_name FROM orders o
            LEFT JOIN products p ON p.id=o.product_id LEFT JOIN customers c ON c.telegram_id=o.customer_id
            ORDER BY o.created_at DESC LIMIT 500""")
        return [public_row(row) for row in rows]

    async def visit(self, path: str, visitor_key: str | None) -> None:
        await self._pool().execute("INSERT INTO page_visits(path, visitor_key) VALUES($1,$2)", path, visitor_key)
