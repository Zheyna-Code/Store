import asyncio
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import bot
from exchange_rates import ExchangeRates, RateQuote, parse_cbr_daily
XML = b'<ValCurs Date="30.09.2026"><Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>90,1234</Value></Valute></ValCurs>'

class ExchangeRateTests(unittest.IsolatedAsyncioTestCase):

    def test_official_xml_and_nominal(self):
        quote = parse_cbr_daily(XML)
        self.assertEqual(quote.rub_per_usd, Decimal('90.1234'))
        self.assertEqual(quote.effective_date, '2026-09-30')
        quote = parse_cbr_daily(XML.replace(b'<Nominal>1</Nominal>', b'<Nominal>10</Nominal>'))
        self.assertEqual(quote.rub_per_usd, Decimal('9.01234'))

    def test_financial_rounding(self):
        quote = RateQuote(Decimal('90.1234'), '2026-09-30')
        self.assertEqual(quote.rubles('1.20'), Decimal('108.15'))
        self.assertEqual(quote.rubles('77'), Decimal('6939.50'))

    def test_invalid_rates_rejected(self):
        for value in [b'-1', b'0', b'NaN', b'Infinity', b'1000000']:
            with self.assertRaises(ValueError):
                parse_cbr_daily(XML.replace(b'90,1234', value))
        with self.assertRaises(ValueError):
            parse_cbr_daily(XML.replace(b'USD', b'EUR'))
        with self.assertRaises(ValueError):
            parse_cbr_daily(b'x' * 500001)

    def test_invalid_amount_rejected(self):
        for value in ['NaN', 'Infinity', '-1']:
            with self.assertRaises(ValueError):
                RateQuote(Decimal('90'), '2026-09-30').rubles(value)

    async def test_quote_is_cached(self):
        service = ExchangeRates()
        service._fetch = AsyncMock(return_value=parse_cbr_daily(XML))
        self.assertEqual(await service.quote(), await service.quote())
        service._fetch.assert_awaited_once()

    async def test_concurrent_calls_share_one_rate_fetch(self):

        async def fetch():
            await asyncio.sleep(0.01)
            return parse_cbr_daily(XML)
        service = ExchangeRates()
        service._fetch = AsyncMock(side_effect=fetch)
        results = await asyncio.gather(*(service.quote() for _ in range(10)))
        self.assertTrue(all((q.rub_per_usd == Decimal('90.1234') for q in results)))
        service._fetch.assert_awaited_once()

    async def test_outage_does_not_invent_rate(self):
        service = ExchangeRates()
        service._fetch = AsyncMock(side_effect=asyncio.TimeoutError)
        self.assertIsNone(await service.quote())
        self.assertIsNone(await service.quote())
        service._fetch.assert_awaited_once()

    async def test_recent_cache_is_marked_stale(self):
        service = ExchangeRates()
        service.cached = parse_cbr_daily(XML)
        service.fetched_at = 1
        service._fetch = AsyncMock(side_effect=asyncio.TimeoutError)
        with patch('exchange_rates.time.monotonic', return_value=4000):
            quote = await service.quote()
        self.assertTrue(quote.stale)
        self.assertEqual(quote.rub_per_usd, Decimal('90.1234'))

    async def test_cache_older_than_one_day_not_used(self):
        service = ExchangeRates()
        service.cached = parse_cbr_daily(XML)
        service.fetched_at = 1
        service._fetch = AsyncMock(side_effect=asyncio.TimeoutError)
        with patch('exchange_rates.time.monotonic', return_value=90000):
            self.assertIsNone(await service.quote())

    async def test_summary_displays_both_and_date(self):
        with patch.object(bot.exchange_rates, 'quote', AsyncMock(return_value=parse_cbr_daily(XML))):
            text = await bot.payment_summary('77')
        self.assertIn('77.00', text)
        self.assertIn('USD', text)
        self.assertIn('6 939,50 ₽', text)
        self.assertIn('30.09.2026', text)

    async def test_summary_during_outage_still_shows_usd(self):
        with patch.object(bot.exchange_rates, 'quote', AsyncMock(return_value=None)):
            text = await bot.payment_summary('77')
        self.assertIn('77.00', text)
        self.assertIn('временно недоступен', text)
        self.assertNotIn('≈', text)

    async def test_payment_invoice_amount_remains_usd(self):
        order = {'id': 1, 'name': 'Gemini', 'price': '77.00'}
        db = SimpleNamespace(upsert_customer=AsyncMock(), create_crypto_order=AsyncMock(return_value=order), set_crypto_invoice=AsyncMock())
        callback = SimpleNamespace(data='buy:2', from_user=SimpleNamespace(id=10, username='test', first_name='Test'), answer=AsyncMock(), message=SimpleNamespace(answer=AsyncMock()))
        invoice = AsyncMock(return_value={'invoice_id': 1, 'pay_url': 'https://example.invalid/pay'})
        with patch.object(bot, 'database', db), patch.object(bot, 'settings', SimpleNamespace(crypto_pay_token='test')), patch.object(bot, 'create_crypto_invoice', invoice), patch.object(bot.exchange_rates, 'quote', AsyncMock(return_value=parse_cbr_daily(XML))):
            await bot.buy_product(callback)
        invoice.assert_awaited_once_with(order)
        self.assertEqual(order['price'], '77.00')
        text = callback.message.answer.call_args.args[0]
        self.assertIn('77.00', text)
        self.assertIn('6 939,50 ₽', text)

    async def test_wallet_payment_options_show_both(self):
        message = SimpleNamespace(delete=AsyncMock(), answer=AsyncMock())
        with patch.object(bot.exchange_rates, 'quote', AsyncMock(return_value=parse_cbr_daily(XML))):
            await bot.show_payment_options(message, '1.20')
        text = message.answer.call_args.args[0]
        self.assertIn('1.20', text)
        self.assertIn('108,15 ₽', text)
if __name__ == '__main__':
    unittest.main()
