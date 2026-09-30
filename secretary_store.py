"""Only connection permissions and recent dialog metadata, never chat contents."""
SECRETARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS secretary_connections (
    connection_id TEXT PRIMARY KEY,
    owner_id BIGINT NOT NULL,
    user_chat_id BIGINT NOT NULL,
    is_enabled BOOLEAN NOT NULL,
    can_reply BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS secretary_active_owner_idx
    ON secretary_connections(owner_id) WHERE is_enabled;
CREATE TABLE IF NOT EXISTS secretary_chats (
    connection_id TEXT NOT NULL REFERENCES secretary_connections(connection_id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    last_incoming TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(connection_id, chat_id)
);
CREATE INDEX IF NOT EXISTS secretary_recent_idx ON secretary_chats(last_incoming);
"""


def can_reply(connection):
    rights = getattr(connection, 'rights', None)
    return bool(getattr(rights, 'can_reply', False)) if rights is not None else bool(getattr(connection, 'can_reply', False))


class SecretaryStore:
    def __init__(self, pool):
        self.pool = pool

    async def save_connection(self, connection):
        async with self.pool.acquire() as db:
            async with db.transaction():
                if connection.is_enabled:
                    await db.execute('''UPDATE secretary_connections SET is_enabled=FALSE, updated_at=NOW()
                        WHERE owner_id=$1 AND connection_id<>$2''', connection.user.id, connection.id)
                await db.execute('''INSERT INTO secretary_connections
                    (connection_id, owner_id, user_chat_id, is_enabled, can_reply)
                    VALUES($1,$2,$3,$4,$5) ON CONFLICT(connection_id) DO UPDATE SET
                    owner_id=EXCLUDED.owner_id, user_chat_id=EXCLUDED.user_chat_id,
                    is_enabled=EXCLUDED.is_enabled, can_reply=EXCLUDED.can_reply, updated_at=NOW()''',
                    connection.id, connection.user.id, connection.user_chat_id, connection.is_enabled, can_reply(connection))
                if not connection.is_enabled:
                    await db.execute('DELETE FROM secretary_chats WHERE connection_id=$1', connection.id)

    async def connection(self, connection_id):
        return await self.pool.fetchrow('SELECT * FROM secretary_connections WHERE connection_id=$1', connection_id)

    async def record_incoming(self, connection_id, chat_id, title, when):
        await self.pool.execute('''INSERT INTO secretary_chats(connection_id,chat_id,title,last_incoming)
            VALUES($1,$2,$3,LEAST($4::timestamptz,NOW())) ON CONFLICT(connection_id,chat_id) DO UPDATE SET
            title=EXCLUDED.title, last_incoming=GREATEST(secretary_chats.last_incoming,EXCLUDED.last_incoming)''',
            connection_id, chat_id, title[:128], when)
        await self.pool.execute("DELETE FROM secretary_chats WHERE last_incoming < NOW()-INTERVAL '2 days'")

    async def targets(self, owner_id):
        return await self.pool.fetch('''SELECT c.connection_id,c.chat_id,c.title,c.last_incoming
            FROM secretary_chats c JOIN secretary_connections b USING(connection_id)
            WHERE b.owner_id=$1 AND b.is_enabled AND b.can_reply
              AND c.last_incoming>NOW()-INTERVAL '24 hours'
            ORDER BY c.last_incoming DESC LIMIT 20''', owner_id)

    async def target(self, owner_id, connection_id, chat_id):
        return await self.pool.fetchrow('''SELECT c.connection_id,c.chat_id,c.title,c.last_incoming
            FROM secretary_chats c JOIN secretary_connections b USING(connection_id)
            WHERE b.owner_id=$1 AND b.is_enabled AND b.can_reply AND c.connection_id=$2 AND c.chat_id=$3
              AND c.last_incoming>NOW()-INTERVAL '24 hours' ''', owner_id, connection_id, chat_id)

    async def find_target(self, owner_id, chat_id):
        return await self.pool.fetchrow('''SELECT c.connection_id,c.chat_id,c.title,c.last_incoming
            FROM secretary_chats c JOIN secretary_connections b USING(connection_id)
            WHERE b.owner_id=$1 AND b.is_enabled AND b.can_reply AND c.chat_id=$2
              AND c.last_incoming>NOW()-INTERVAL '24 hours' ''', owner_id, chat_id)
