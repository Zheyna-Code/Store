"""Custom emoji IDs stay strings: Telegram IDs exceed JavaScript integer precision."""

DEFAULT_EMOJI = {'catalog': '5983399041197675256', 'wallet': '5769403330761593044', 'bonus': '5985472565508838112', 'support': '5891169510483823323', 'other': '5843843420468024653', 'wave': '5906995262378741881', 'chatgpt': '6134246530380472478', 'claude': '6131771460986872161', 'notion': '5364199932620194408', 'duolingo': '5796371348808799072', 'netflix': '5796522630441867305', 'spotify': '5796304385973686816', 'grok': '6179337489350663129', 'capcut': '5267309292943331240', 'perplexity': '5321199630585732877', 'gemini': '5321197740800120767', 'dollar': '5974217466270716579', 'write': '5879841310902324730', 'link': '5891169510483823323', 'crypto': '5927169041595634481', 'admin_payment': '5920052658743283381', 'profile': '5886412370347036129', 'friends': '5944970130554359187', 'card': '5927169041595634481', 'document': '5839323457015256759', 'food': '5875271289605722323', 'candy': '5987565374223159187', 'new': '5886306834410640699', 'back': '5875082500023258804', 'plane': '5875465628285931233', 'description': '5843843420468024653', 'stock': '5877260593903177342'}

EMOJI_LABELS = {'description': 'Описание товара', 'dollar': 'Цена и баланс (USD)', 'stock': 'Количество в наличии', 'catalog': 'Каталог', 'wallet': 'Кошелёк', 'bonus': 'Бонус', 'support': 'Техподдержка', 'other': 'Прочее', 'wave': 'Приветствие', 'write': 'Своя сумма', 'link': 'Ссылка', 'crypto': 'Crypto Pay', 'admin_payment': 'Оплата администратору', 'profile': 'Профиль', 'friends': 'Рефералы', 'card': 'Покупки', 'candy': 'Текст поддержки', 'new': 'Новое', 'back': 'Назад', 'plane': 'Заголовок меню'}

from pathlib import Path
import json

EMOJI_FALLBACKS = {item["id"]: item["emoji"] for item in json.loads(
    (Path(__file__).resolve().parent / "catalog/emojis.json").read_text(encoding="utf-8"))}
