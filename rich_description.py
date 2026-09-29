"""Allow only custom-emoji tokens inside otherwise literal product descriptions."""
import html
from html.parser import HTMLParser
import re

TOKEN = re.compile(r'<tg-emoji\b([^>]*)>([^<>]*)</tg-emoji\s*>|<custom-emoji-element\b([^>]*)>[^<>]*</custom-emoji-element\s*>', re.I)
ID = re.compile(r'[1-9][0-9]{0,19}\Z')


class Attributes(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.attrs = {}
        self.feed('<x ' + source + '>')
    def handle_starttag(self, tag, attrs):
        self.attrs = dict(attrs)


def description_parts(value):
    value = str(value or '')
    offset = 0
    for match in TOKEN.finditer(value):
        if match.start() > offset:
            yield {'text': value[offset:match.start()]}
        attrs = Attributes(match[1] if match[1] is not None else match[3]).attrs
        emoji_id = attrs.get('emoji-id' if match[1] is not None else 'data-doc-id', '') or ''
        fallback = html.unescape(match[2]) if match[1] is not None else attrs.get('data-sticker-emoji')
        if ID.fullmatch(emoji_id) and fallback and len(fallback) <= 32:
            yield {'id': emoji_id, 'emoji': fallback}
        else:
            yield {'text': match[0]}
        offset = match.end()
    if offset < len(value):
        yield {'text': value[offset:]}


def description_to_html(value):
    return ''.join(html.escape(p['text']) if 'text' in p else
        f'<tg-emoji emoji-id="{p["id"]}">{html.escape(p["emoji"])}</tg-emoji>'
        for p in description_parts(value))
