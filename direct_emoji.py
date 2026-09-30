"""Short-lived, owner/chat-bound emoji drafts; no database or message history."""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import secrets
import time

from inline_emoji import PLACEHOLDER

DIRECT_PAGE_SIZE = 8
DRAFT_TTL = 900


@dataclass
class EmojiDraft:
    token: str
    owner_id: int
    query: str
    expires: float
    chat_id: int | None = None
    picker_id: int | None = None
    offset: int = 0
    allowed: dict = field(default_factory=dict)
    sent: bool = False
    secretary: bool = False
    business_connection_id: str | None = None
    target_chat_id: int | None = None
    target_title: str = ""
    destinations: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class DraftStore:
    def __init__(self, max_items=256, per_user=4):
        self.items = OrderedDict()
        self.max_items = max_items
        self.per_user = per_user

    def purge(self):
        now = time.monotonic()
        for token, draft in list(self.items.items()):
            if draft.expires <= now:
                del self.items[token]

    def create(self, owner_id, query, chat_id=None):
        self.purge()
        if len(query.encode('utf-16-le')) // 2 > 4000:
            raise ValueError('Текст слишком длинный. Сократите его до 4000 символов.')
        if query.count(PLACEHOLDER) > 80:
            raise ValueError('Слишком много вставок эмодзи.')
        mine = [token for token, draft in self.items.items() if draft.owner_id == owner_id]
        while len(mine) >= self.per_user:
            del self.items[mine.pop(0)]
        token = secrets.token_urlsafe(9)
        draft = EmojiDraft(token, owner_id, query, time.monotonic()+DRAFT_TTL, chat_id)
        self.items[token] = draft
        while len(self.items) > self.max_items:
            self.items.popitem(last=False)
        return draft

    def get(self, token, owner_id):
        self.purge()
        draft = self.items.get(token)
        return draft if draft and draft.owner_id == owner_id else None


def plain_composed(text, fallback):
    return text.replace(PLACEHOLDER, fallback) if PLACEHOLDER in text else (text+' ' if text else '')+fallback


def has_exact_emoji(message, emoji_id, expected=1):
    entities = getattr(message, 'entities', None) or []
    return sum(getattr(entity, 'custom_emoji_id', None) == emoji_id for entity in entities) == expected
