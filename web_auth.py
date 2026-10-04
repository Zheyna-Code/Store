"""Telegram-verified Mini App identity and explicitly approved browser sessions."""
import hashlib
import hmac
import json
import re
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
-- Аккаунты сайта по почте и паролю. Им выдаётся отрицательный customer_id,
-- чтобы никогда не пересекаться с Telegram ID (они всегда положительные).
CREATE SEQUENCE IF NOT EXISTS web_account_seq;
CREATE TABLE IF NOT EXISTS web_accounts (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    customer_id BIGINT UNIQUE NOT NULL REFERENCES customers(telegram_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

EMAIL_RE=re.compile(r'^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,63}$')
SCRYPT=dict(n=2**14,r=8,p=1,dklen=32)


def normalize_email(value):
    if not isinstance(value,str): raise ValueError('Введите почту.')
    email=value.strip().lower()
    if len(email)>254 or not EMAIL_RE.match(email): raise ValueError('Проверьте адрес почты.')
    return email


def check_password(value):
    if not isinstance(value,str) or not 8<=len(value)<=128: raise ValueError('Пароль должен быть от 8 до 128 символов.')
    return value


def hash_password(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    key=hashlib.scrypt(password.encode(),salt=salt,maxmem=64*1024*1024,**SCRYPT)
    return f'scrypt${salt.hex()}${key.hex()}'


def verify_password(password,stored):
    try:
        kind,salt,key=stored.split('$')
        if kind!='scrypt': return False
        return hmac.compare_digest(hash_password(password,bytes.fromhex(salt)),stored)
    except (ValueError,AttributeError):
        return False


DUMMY_HASH=hash_password('dummy-password-for-timing')


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

    async def register(self,email,password_hash,name):
        """Создаёт клиента сайта с почтой. None — если почта уже занята."""
        async with self.pool.acquire() as c,c.transaction():
            if await c.fetchval('SELECT 1 FROM web_accounts WHERE email=$1',email): return None
            uid=-await c.fetchval("SELECT nextval('web_account_seq')")
            await c.execute('INSERT INTO customers(telegram_id,username,first_name) VALUES($1,NULL,$2)',uid,name)
            try:
                await c.execute('INSERT INTO web_accounts(email,password_hash,customer_id) VALUES($1,$2,$3)',email,password_hash,uid)
            except Exception as exc:
                if exc.__class__.__name__=='UniqueViolationError': return None
                raise
            return uid

    async def account(self,email):
        return await self.pool.fetchrow('SELECT * FROM web_accounts WHERE email=$1',email)

    async def email_of(self,uid):
        return await self.pool.fetchval('SELECT email FROM web_accounts WHERE customer_id=$1',uid)

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
