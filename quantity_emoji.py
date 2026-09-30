"""Resolve actual +/- custom emoji IDs from the user's ABC Emoji pack via Telegram."""
from __future__ import annotations

import asyncio
import logging
import time

from emoji_library import validate_emoji_id

QUANTITY_EMOJI_PACK = 'ABCEmoji'


class QuantityEmoji:
    def __init__(self):
        self.ids: dict[str, str] = {}
        self.refresh_at = 0.0
        self.lock = asyncio.Lock()

    async def load(self, bot) -> dict[str, str]:
        if bot is None or time.monotonic() < self.refresh_at:
            return dict(self.ids)
        async with self.lock:
            if time.monotonic() < self.refresh_at:
                return dict(self.ids)
            try:
                pack = await bot.get_sticker_set(QUANTITY_EMOJI_PACK, request_timeout=5)
                if pack.name.lower() != QUANTITY_EMOJI_PACK.lower() or pack.sticker_type != 'custom_emoji':
                    raise ValueError('Unexpected emoji set')
                ids = {}
                for sticker in pack.stickers:
                    symbol = (sticker.emoji or '').replace('\ufe0f', '')
                    key = {'➖': 'minus', '➕': 'plus', '-': 'minus', '+': 'plus'}.get(symbol)
                    if key and sticker.custom_emoji_id:
                        ids.setdefault(key, validate_emoji_id(sticker.custom_emoji_id))
                if set(ids) != {'minus', 'plus'}:
                    raise ValueError('Plus/minus missing from set')
                self.ids = ids
                self.refresh_at = time.monotonic() + 86400
            except Exception:
                # Never substitute an ID from another set or log Telegram token-bearing URLs.
                logging.warning('ABC Emoji unavailable; quantity controls remain usable')
                self.refresh_at = time.monotonic() + 60
        return dict(self.ids)
