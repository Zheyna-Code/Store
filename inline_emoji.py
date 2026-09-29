"""Inline text composition and signed, token-free Telegram emoji thumbnails."""
import asyncio
from collections import OrderedDict
import hashlib
import hmac
import html
import re
from io import BytesIO
import time
from urllib.parse import urlencode, urlsplit
import warnings

from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, LinkPreviewOptions
from PIL import Image, ImageOps, UnidentifiedImageError

PAGE_SIZE = 24
THUMB_TTL = 900
PLACEHOLDER = "{эмодзи}"
ALIASES = {
    "звезда": "⭐🌟✨✡🔯", "star": "⭐🌟✨✡🔯",
    "доллар": "$💵💲💰🤑", "dollar": "$💵💲💰🤑",
    "шестеренка": "⚙", "шестерёнка": "⚙", "gear": "⚙",
    "сердце": "❤💙💚💛🧡💜🖤🤍🤎💖💗💓💕💞💘💝", "heart": "❤💙💚💛🧡💜🖤🤍🤎💖💗💓💕💞💘💝",
    "огонь": "🔥", "fire": "🔥", "подарок": "🎁", "gift": "🎁",
    "назад": "⬅←↩🔙", "back": "⬅←↩🔙", "самолет": "✈", "самолёт": "✈",
    "галочка": "✔✅☑", "check": "✔✅☑", "закладка": "🔖", "bookmark": "🔖",
}


def normalized(value):
    return str(value).replace("\ufe0f", "").casefold()


class InlineCatalog:
    def __init__(self, items):
        if any(not isinstance(item["id"], str) or not re.fullmatch(r"[1-9][0-9]{0,19}", item["id"]) for item in items):
            raise ValueError("Некорректный ID в каталоге")
        self.items = items
        self.ids = frozenset(item["id"] for item in items)
        self.index = [(item, normalized(" ".join((item["emoji"], item["pack"], item["category"])))) for item in items]
        counts = {}
        self.positions = {}
        for item in items:
            counts[item["pack"]] = counts.get(item["pack"], 0) + 1
            self.positions[item["id"]] = counts[item["pack"]]

    def page(self, query, offset=""):
        text, separator, search = query.partition("|")
        text = text.strip()
        search = normalized(search.strip()) if separator else ""
        terms = search.split()
        rows = [item for item, haystack in self.index if all(
            term in haystack or (term in ALIASES and any(char in normalized(item["emoji"]) for char in ALIASES[term]))
            for term in terms)]
        if offset and (not offset.isascii() or not offset.isdecimal() or len(offset) > 8):
            raise ValueError("Некорректная страница")
        index = int(offset or "0")
        if index > len(rows):
            return text, [], ""
        stop = index + PAGE_SIZE
        return text, rows[index:stop], str(stop) if stop < len(rows) else ""


def compose(text, emoji_id, fallback):
    tag = f'<tg-emoji emoji-id="{emoji_id}">{html.escape(fallback)}</tg-emoji>'
    if PLACEHOLDER in text:
        return tag.join(html.escape(part) for part in text.split(PLACEHOLDER))
    return (html.escape(text) + " " if text else "") + tag


def public_base(value):
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Задайте PUBLIC_BASE_URL как HTTPS-адрес приложения без /admin")
    if parsed.path.endswith("/admin"):
        raise ValueError("PUBLIC_BASE_URL должен быть без /admin")
    return value


def signature(secret, emoji_id, expires):
    payload = f"inline-emoji-v1:{emoji_id}:{expires}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def thumbnail_url(base, secret, emoji_id, now=None):
    expires = int(time.time() if now is None else now) + THUMB_TTL
    return f"{public_base(base)}/api/inline/emoji/{emoji_id}.jpg?" + urlencode({
        "expires": expires, "sig": signature(secret, emoji_id, expires)})


def valid_thumbnail(secret, allowed_ids, emoji_id, expires, supplied_signature, now=None):
    if not isinstance(supplied_signature, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied_signature):
        return False
    if not secret or emoji_id not in allowed_ids or not expires.isascii() or not expires.isdecimal() or len(expires) > 12:
        return False
    timestamp = int(time.time() if now is None else now)
    deadline = int(expires)
    if deadline < timestamp or deadline > timestamp + THUMB_TTL:
        return False
    return hmac.compare_digest(signature(secret, emoji_id, deadline), supplied_signature)


def result_for(query, text, item, catalog, base, secret):
    preview = text.replace(PLACEHOLDER, item["emoji"]) if PLACEHOLDER in text else f'{text} {item["emoji"]}'.strip()
    return InlineQueryResultArticle(
        id=hashlib.sha256((query + "\0" + item["id"]).encode()).hexdigest()[:40],
        title=f'{item["emoji"]} {item["pack"]} · №{catalog.positions[item["id"]]}',
        description=preview[:160],
        thumbnail_url=thumbnail_url(base, secret, item["id"]),
        thumbnail_width=128, thumbnail_height=128,
        input_message_content=InputTextMessageContent(
            message_text=compose(text, item["id"], item["emoji"]), parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True)),
    )


def jpeg_thumbnail(content, repaint=False):
    """Render the real Telegram image on a dark tile; never fabricate an icon."""
    if len(content) > 2_000_000:
        raise ValueError("Слишком большая миниатюра")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"} or source.width * source.height > 2_000_000:
                    raise ValueError("Некорректная миниатюра")
                image = source.convert("RGBA")
        if repaint and image.getchannel("A").getextrema()[0] < 255:
            alpha = image.getchannel("A")
            image = Image.new("RGBA", image.size, "white")
            image.putalpha(alpha)
        image = ImageOps.contain(image, (112, 112), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (128, 128), (24, 38, 51))
        tile.paste(image, ((128-image.width)//2, (128-image.height)//2), image)
        output = BytesIO()
        tile.save(output, "JPEG", quality=90, optimize=True)
        return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Недоступная миниатюра") from exc


class InlineThumbnails:
    def __init__(self):
        self.cache = OrderedDict()
        self.pending = {}
        self.limit = asyncio.Semaphore(4)

    async def _load(self, bot, library, emoji_id):
        async with self.limit:
            content, _ = await library.image(bot, emoji_id)
            sticker = library.metadata.get(emoji_id)
            data = await asyncio.to_thread(jpeg_thumbnail, content, bool(getattr(sticker, "needs_repainting", False)))
            self.cache[emoji_id] = data
            while len(self.cache) > 256:
                self.cache.popitem(last=False)
            return data

    async def get(self, bot, library, emoji_id):
        if emoji_id in self.cache:
            self.cache.move_to_end(emoji_id)
            return self.cache[emoji_id]
        if emoji_id not in self.pending:
            task = asyncio.create_task(self._load(bot, library, emoji_id))
            self.pending[emoji_id] = task
            def done(result):
                self.pending.pop(emoji_id, None)
                if not result.cancelled():
                    result.exception()  # Consume failures even if all HTTP callers disconnect.
            task.add_done_callback(done)
        return await asyncio.shield(self.pending[emoji_id])
