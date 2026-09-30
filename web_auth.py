"""Telegram-verified Mini App identity and explicitly approved browser sessions."""
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl

WEB_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(telegram_id),
    csrf TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW()+INTERVAL '1 day'
);
CREATE INDEX IF NOT EXISTS web_sessions_expiry_idx ON web_sessions(expires_at);
CREATE TABLE IF NOT EXISTS web_logins (
    id TEXT PRIMARY KEY,
    browser_hash TEXT UNIQUE NOT NULL,
    code TEXT NOT NULL,
    customer_id BIGINT REFERENCES customers(telegram_id),
    status TEXT NOT NULL DEFAULT 'pending',
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW()+INTERVAL '5 minutes'
);
CREATE INDEX IF NOT EXISTS web_logins_expiry_idx ON web_logins(expires_at);
"""


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def validate_init_data(raw, bot_token, now=None):
    if not bot_token or not isinstance(raw,str) or not 0<len(raw)<=16384:
        raise ValueError('Не удалось подтвердить вход через Telegram.')
    pairs=parse_qsl(raw,keep_blank_values=True,strict_parsing=True)
    if len({key for key,_ in pairs})!=len(pairs):
        raise ValueError('Повторяющиеся поля Telegram.')
    data=dict(pairs); received=data.pop('hash','')
    if len(received)!=64:
        raise ValueError('Неверная подпись Telegram.')
    key=hmac.new(b'WebAppData',bot_token.encode(),hashlib.sha256).digest()
    text='\n'.join(f'{key}={value}' for key,value in sorted(data.items()))
    if not hmac.compare_digest(hmac.new(key,text.encode(),hashlib.sha256).hexdigest(),received):
        raise ValueError('Неверная подпись Telegram.')
    try:
        current=time.time() if now is None else now
        age=current-int(data['auth_date'])
        user=json.loads(data['user'])
        if not -30<=age<=3600 or not isinstance(user,dict): raise ValueError
        uid=user['id']
        if isinstance(uid,bool) or not isinstance(uid,int) or not 0<uid<2**63 or user.get('is_bot'): raise ValueError
        if not isinstance(user.get('first_name',''),str) or not isinstance(user.get('username',''),str): raise ValueError
    except (KeyError,ValueError,TypeError):
        raise ValueError('Данные входа устарели. Откройте приложение заново.') from None
    return user,data


class WebAuth:
    def __init__(self,get_db): self.get_db=get_db
    @property
    def pool(self): return self.get_db()._pool()

    async def session(self,token):
        if not isinstance(token,str) or not 20<=len(token)<=100: return None
        return await self.pool.fetchrow('SELECT * FROM web_sessions WHERE token_hash=$1 AND expires_at>NOW()',digest(token))

    async def create_session(self,uid):
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
        await self.pool.execute('DELETE FROM web_sessions WHERE expires_at<NOW()')
        await self.pool.execute('INSERT INTO web_sessions(token_hash,customer_id,csrf) VALUES($1,$2,$3)',digest(token),uid,csrf)
        return token,csrf

    async def create_login(self):
        token=secrets.token_urlsafe(32);login_id=secrets.token_urlsafe(24);code=f'{secrets.randbelow(1000000):06d}'
        await self.pool.execute('DELETE FROM web_logins WHERE expires_at<NOW()')
        await self.pool.execute('DELETE FROM web_sessions WHERE expires_at<NOW()')
        await self.pool.execute('INSERT INTO web_logins(id,browser_hash,code) VALUES($1,$2,$3)',login_id,digest(token),code)
        return token,login_id,code

    async def claim(self,login_id,uid):
        return await self.pool.fetchrow("""UPDATE web_logins SET customer_id=$2 WHERE id=$1 AND expires_at>NOW()
            AND status='pending' AND (customer_id IS NULL OR customer_id=$2) RETURNING *""",login_id,uid)

    async def approve(self,login_id,uid,allow=True):
        return await self.pool.fetchrow("""UPDATE web_logins SET status=$3 WHERE id=$1 AND customer_id=$2
            AND status='pending' AND expires_at>NOW() RETURNING *""",login_id,uid,'approved' if allow else 'denied')

    async def poll(self,token):
        if not token or len(token)>100: return None,None
        async with self.pool.acquire() as c,c.transaction():
            row=await c.fetchrow('SELECT * FROM web_logins WHERE browser_hash=$1 AND expires_at>NOW() FOR UPDATE',digest(token))
            if not row: return None,None
            if row['status']!='approved': return row['status'],None
            session=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
            await c.execute('INSERT INTO web_sessions(token_hash,customer_id,csrf) VALUES($1,$2,$3)',digest(session),row['customer_id'],csrf)
            await c.execute("UPDATE web_logins SET status='consumed' WHERE id=$1",row['id'])
            return 'approved',(session,csrf)
