import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import bot
from rich_description import description_parts, description_to_html

class DescriptionTests(unittest.IsolatedAsyncioTestCase):
    def test_selected_id_is_not_changed(self):
        for emoji_id in ['5875465628285931233','5843843420468024653','5877260593903177342']:
            text=f'До <tg-emoji emoji-id="{emoji_id}">⭐️</tg-emoji> после'
            self.assertEqual(description_to_html(text),text)
    def test_plain_text_and_line_breaks(self):
        self.assertEqual(description_to_html('A & B\n<Pro>'),'A &amp; B\n&lt;Pro&gt;')
    def test_arbitrary_html_never_runs(self):
        text='<script>alert(1)</script><img src="x" onerror="alert(1)">'
        result=description_to_html(text)
        self.assertNotIn('<script>',result);self.assertNotIn('<img',result)
    def test_pasted_telegram_markup(self):
        text='<custom-emoji-element class="custom-emoji" data-doc-id="5843843420468024653" data-sticker-emoji="⭐️"></custom-emoji-element>'
        self.assertEqual(description_to_html(text),'<tg-emoji emoji-id="5843843420468024653">⭐️</tg-emoji>')
    def test_invalid_id_is_literal(self):
        self.assertTrue(description_to_html('<tg-emoji emoji-id="123<script>">⭐️</tg-emoji>').startswith('&lt;'))
    def test_fallback_is_escaped(self):
        text='<tg-emoji emoji-id="123">&lt;img&gt;</tg-emoji>'
        self.assertEqual(description_to_html(text),text)
    async def test_stored_description_reaches_final_message(self):
        description='План <tg-emoji emoji-id="5843843420468024653">⭐️</tg-emoji>\nДоступ на месяц'
        product=dict(id=2,name='Gemini 18m',category_name='Gemini',description=description,price='77',category_id=3,is_active=True)
        db=SimpleNamespace(product=AsyncMock(return_value=product),upsert_customer=AsyncMock())
        service=SimpleNamespace(store=SimpleNamespace(available=AsyncMock(return_value=0)),lock=lambda *args: asyncio.Lock())
        message=SimpleNamespace(answer=AsyncMock(),chat=SimpleNamespace(type="private",id=10))
        callback=SimpleNamespace(data='product:2',message=message,answer=AsyncMock(),from_user=SimpleNamespace(id=10,username='test',first_name='Test'))
        with patch.object(bot,'database',db),patch.object(bot,'payments',service):await bot.open_product(callback)
        final=message.answer.call_args.args[0]
        self.assertIn('<tg-emoji emoji-id="5843843420468024653">⭐️</tg-emoji>',final)
        self.assertNotIn('&lt;tg-emoji',final)
        self.assertIn('Доступ на месяц',final)

if __name__=='__main__':unittest.main()
