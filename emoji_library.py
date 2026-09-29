"""Authenticated static Telegram previews. No token or Telegram file URL is sent to browsers."""
import asyncio
from collections import OrderedDict
from io import BytesIO
import json
from pathlib import Path
import re


def validate_emoji_id(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ValueError("ID эмодзи должен быть строкой из 1–20 цифр")
    return value


class EmojiLibrary:
    def __init__(self, catalog_path: Path):
        self.items = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.metadata = OrderedDict()
        self.images = OrderedDict()
        self.image_bytes = 0
        self.metadata_lock = asyncio.Lock()
        self.download_limit = asyncio.Semaphore(4)

    async def previews(self, bot, ids):
        async with self.metadata_lock:
            missing = [value for value in ids if value not in self.metadata]
            if missing:
                stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=missing)
                for sticker in stickers:
                    if sticker.custom_emoji_id:
                        self.metadata[sticker.custom_emoji_id] = sticker
                while len(self.metadata) > 3000:
                    self.metadata.popitem(last=False)
        return {value: {"available": value in self.metadata,
                        "emoji": self.metadata[value].emoji or "" if value in self.metadata else "",
                        "pack": self.metadata[value].set_name or "" if value in self.metadata else ""}
                for value in ids}

    async def image(self, bot, emoji_id):
        if emoji_id in self.images:
            self.images.move_to_end(emoji_id)
            return self.images[emoji_id]
        async with self.download_limit:
            if emoji_id not in self.metadata:
                await self.previews(bot, [emoji_id])
            sticker = self.metadata.get(emoji_id)
            if not sticker:
                raise ValueError("Unknown emoji")
            # Use original static WEBP; use an actual thumbnail for TGS/WEBM.
            file_id = sticker.thumbnail.file_id if (sticker.is_animated or sticker.is_video) and sticker.thumbnail else sticker.file_id
            if (sticker.is_animated or sticker.is_video) and not sticker.thumbnail:
                raise ValueError("No static thumbnail")
            telegram_file = await bot.get_file(file_id)
            if telegram_file.file_size and telegram_file.file_size > 2_000_000:
                raise ValueError("Preview too large")
            dest = BytesIO()
            await bot.download_file(telegram_file.file_path, destination=dest, timeout=15)
            content = dest.getvalue()
            if len(content) > 2_000_000:
                raise ValueError("Preview too large")
            if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                mime = "image/webp"
            elif content.startswith(b"\xff\xd8\xff"):
                mime = "image/jpeg"
            elif content.startswith(b"\x89PNG\r\n\x1a\n"):
                mime = "image/png"
            else:
                raise ValueError("Unsupported preview")
            if emoji_id in self.images:
                self.image_bytes -= len(self.images[emoji_id][0])
            self.images[emoji_id] = (content, mime)
            self.image_bytes += len(content)
            while len(self.images) > 256 or self.image_bytes > 16 * 1024 * 1024:
                _, old = self.images.popitem(last=False)
                self.image_bytes -= len(old[0])
            return content, mime
