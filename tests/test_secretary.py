import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramServerError
from aiogram.methods import SendMessage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BusinessConnection, BusinessBotRights, Update, User, Message, Chat

import bot
from direct_emoji import DraftStore
from inline_emoji import InlineCatalog
from secretary import Secretary, ComposeState
from secretary_store import SecretaryStore, SECRETARY_SCHEMA, can_reply
from test_direct_emoji import FakeMessage, ITEMS


def conn(owner=1, enabled=True, reply=True, connection_id='conn1'):
    return SimpleNamespace(id=connection_id, user=SimpleNamespace(id=owner), user_chat_id=owner,
                           is_enabled=enabled, rights=SimpleNamespace(can_reply=reply))


class State:
    def __init__(self):
        self.state = None
        self.data = {}
    async def clear(self):
        self.state, self.data = None, {}
    async def set_state(self, state):
        self.state = state
    async def get_data(self):
        return dict(self.data)
    async def update_data(self, **data):
        self.data.update(data)


class MemoryStore:
    def __init__(self):
        self.rows = [{'connection_id':'conn1', 'chat_id':22, 'title':'Друг <test>', 'last_incoming':datetime.now(timezone.utc)}]
        self.connections = {'conn1': dict(owner_id=1,is_enabled=True,can_reply=True)}
        self.save_connection = AsyncMock(side_effect=self._save)
        self.record_incoming = AsyncMock()
    async def _save(self, c):
        self.connections[c.id] = dict(owner_id=c.user.id,is_enabled=c.is_enabled,can_reply=can_reply(c))
    async def connection(self, id):
        return self.connections.get(id)
    async def targets(self, owner):
        return [r for r in self.rows if self.connections[r['connection_id']]['owner_id'] == owner
                and self.connections[r['connection_id']]['is_enabled'] and self.connections[r['connection_id']]['can_reply']]
    async def target(self, owner, id, chat):
        return next((r for r in await self.targets(owner) if r['connection_id']==id and r['chat_id']==chat), None)
    async def find_target(self, owner, chat):
        return next((r for r in await self.targets(owner) if r['chat_id']==chat), None)


class SecretaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.drafts = DraftStore()
        self.library = SimpleNamespace(previews=AsyncMock(side_effect=lambda client,ids: {
            id:dict(available=True,emoji='⭐️') for id in ids}))
        self.client = SimpleNamespace(get_business_connection=AsyncMock(return_value=conn()),
                                      send_message=AsyncMock())
        self.service = Secretary(lambda:self.store, self.drafts, bot.show_direct_choices)
        self.state = State()
        self.message = FakeMessage('/say Привет {эмодзи}! | звезда')
        self.message.bot = self.client
        patches = [patch.object(bot,'direct_drafts',self.drafts), patch.object(bot,'secretary',self.service),
                   patch.object(bot,'inline_catalog',InlineCatalog(ITEMS)), patch.object(bot,'emoji_library',self.library)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.result = SimpleNamespace(entities=[SimpleNamespace(custom_emoji_id='1000')])
        self.client.send_message.return_value = self.result

    async def pick_target(self):
        await self.service.command(self.message, self.state)
        self.draft = list(self.drafts.items.values())[-1]
        self.picker = self.message.messages[-1]
        self.picker.bot = self.client
        self.callback = SimpleNamespace(data=f'sec:{self.draft.token}:22', from_user=SimpleNamespace(id=1), message=self.picker, answer=AsyncMock())
        await self.service.select_target(self.callback)

    async def pick_emoji(self):
        await self.pick_target()
        self.callback.data = f'emod:{self.draft.token}:pick:1000'
        await bot.direct_emoji_callback(self.callback)

    async def test_full_manual_flow_sends_exact_id_as_account_only_to_selected_chat(self):
        await self.pick_emoji()
        self.client.send_message.assert_awaited_once()
        args = self.client.send_message.call_args.kwargs
        self.assertEqual(args['business_connection_id'], 'conn1')
        self.assertEqual(args['chat_id'], 22)
        self.assertIn('Привет <tg-emoji emoji-id="1000">⭐️</tg-emoji>!',args['text'])
        self.assertNotIn('reply_markup',args)
        self.assertIn('Отправлено от твоего имени',self.picker.text)
        self.assertNotIn('<test>',self.picker.text)
        self.assertTrue(self.draft.sent)
        self.assertEqual(self.draft.query,'')
        self.assertFalse(self.draft.allowed)
        self.assertFalse(self.draft.destinations)

    async def test_choice_menu_stays_in_bot_private_chat(self):
        await self.pick_target()
        self.client.send_message.assert_not_awaited()
        self.assertEqual(self.picker.chat.id,10)
        self.assertEqual(self.draft.target_chat_id,22)
        self.assertIn('Друг &lt;test&gt;',self.picker.text)
        self.assertTrue(self.draft.secretary)

    async def test_repeat_click_does_not_send_again(self):
        await self.pick_target()
        self.callback.data=f'emod:{self.draft.token}:pick:1000'
        await asyncio.gather(bot.direct_emoji_callback(self.callback),bot.direct_emoji_callback(self.callback))
        self.client.send_message.assert_awaited_once()

    async def test_target_owner_and_picker_binding(self):
        await self.service.command(self.message,self.state)
        draft=next(iter(self.drafts.items.values()))
        picker=self.message.messages[-1]
        for owner,message,value in [(2,picker,'22'),(1,FakeMessage(message_id=999),'22'),(1,picker,'333')]:
            callback=SimpleNamespace(data=f'sec:{draft.token}:{value}',from_user=SimpleNamespace(id=owner),message=message,answer=AsyncMock())
            await self.service.select_target(callback)
            self.assertTrue(callback.answer.call_args.kwargs['show_alert'])
        self.assertIsNone(draft.business_connection_id)
        self.client.send_message.assert_not_awaited()

    async def test_revoked_connection_blocks_send(self):
        await self.pick_target()
        self.client.get_business_connection.return_value=conn(enabled=False)
        self.callback.data=f'emod:{self.draft.token}:pick:1000'
        await bot.direct_emoji_callback(self.callback)
        self.client.send_message.assert_not_awaited()
        self.assertTrue(self.draft.sent)

    async def test_changed_owner_or_reply_right_blocks_send(self):
        for c in [conn(owner=2),conn(reply=False),conn(connection_id='other')]:
            await self.pick_target()
            self.client.get_business_connection.return_value=c
            self.callback.data=f'emod:{self.draft.token}:pick:1000'
            await bot.direct_emoji_callback(self.callback)
            self.client.send_message.assert_not_awaited()

    async def test_expired_window_blocks_send(self):
        await self.pick_target()
        self.store.rows.clear()
        self.callback.data=f'emod:{self.draft.token}:pick:1000'
        await bot.direct_emoji_callback(self.callback)
        self.client.send_message.assert_not_awaited()
        self.assertIn('24 часа',self.picker.text)

    async def test_revocation_during_api_preflight_blocks_send(self):
        await self.pick_target()
        async def revoke(id):
            self.store.connections[id]['is_enabled']=False
            return conn()
        self.client.get_business_connection.side_effect=revoke
        self.callback.data=f'emod:{self.draft.token}:pick:1000'
        await bot.direct_emoji_callback(self.callback)
        self.client.send_message.assert_not_awaited()

    async def test_evicted_draft_during_preflight_cannot_send(self):
        await self.pick_target()
        async def evict(id):
            self.drafts.items.pop(self.draft.token)
            return conn()
        self.client.get_business_connection.side_effect=evict
        self.callback.data=f'emod:{self.draft.token}:pick:1000'
        await bot.direct_emoji_callback(self.callback)
        self.client.send_message.assert_not_awaited()
        self.assertIn('устарел',self.picker.text)

    async def test_server_failure_delivery_is_marked_unknown(self):
        self.client.send_message.side_effect=TelegramServerError(method=SendMessage(chat_id=22,text='test'),message='server failed')
        await self.pick_emoji()
        self.assertIn('неизвестен',self.picker.text)
        self.assertTrue(self.draft.sent)

    async def test_permission_check_failure_does_not_send(self):
        await self.pick_target()
        self.client.get_business_connection.side_effect=TelegramBadRequest(method=SendMessage(chat_id=1,text='check'),message='check failed')
        self.callback.data=f'emod:{self.draft.token}:pick:1000'
        await bot.direct_emoji_callback(self.callback)
        self.client.send_message.assert_not_awaited()
        self.assertFalse(self.draft.sent)

    async def test_ambiguous_network_failure_is_not_retried(self):
        self.client.send_message.side_effect=TelegramNetworkError(method=SendMessage(chat_id=22,text='test'),message='timeout')
        await self.pick_emoji()
        self.assertIn('неизвестен',self.picker.text)
        await bot.direct_emoji_callback(self.callback)
        self.client.send_message.assert_awaited_once()
        self.assertTrue(self.draft.sent)

    async def test_send_rejection_and_stripped_entities_are_reported(self):
        self.client.send_message.side_effect=TelegramBadRequest(method=SendMessage(chat_id=22,text='test'),message='BUSINESS_CONNECTION_INVALID')
        await self.pick_emoji()
        self.assertIn('отклонил',self.picker.text)
        self.assertTrue(self.draft.sent)
        self.client.send_message.side_effect=None
        self.client.send_message.return_value=SimpleNamespace(entities=[])
        await self.pick_emoji()
        self.assertIn('не сохранил',self.picker.text)
        self.assertNotIn('Отправлено от твоего имени',self.picker.text)

    async def test_cancel_target_selector_never_sends(self):
        await self.service.command(self.message,self.state)
        draft=next(iter(self.drafts.items.values()))
        picker=self.message.messages[-1]
        callback=SimpleNamespace(data=f'emod:{draft.token}:cancel:0',from_user=SimpleNamespace(id=1),message=picker,answer=AsyncMock())
        await bot.direct_emoji_callback(callback)
        self.assertTrue(draft.sent)
        self.assertFalse(draft.destinations)
        self.client.send_message.assert_not_awaited()

    async def test_manage_bot_deeplink_preselects_only_owners_eligible_chat(self):
        message=FakeMessage('/start bizChat22')
        await self.service.open_chat(message,self.state,22)
        self.assertEqual(self.state.state,ComposeState.text)
        self.assertEqual(self.state.data['target']['chat_id'],22)
        message.text='Привет! | звезда'
        await self.service.receive_text(message,self.state)
        draft=next(iter(self.drafts.items.values()))
        self.assertEqual(draft.target_chat_id,22)
        self.assertFalse(draft.destinations)
        self.assertIsNone(self.state.state)
        other=FakeMessage(owner=2)
        await self.service.open_chat(other,self.state,22)
        self.assertIsNone(self.state.state)
        self.assertNotIn('Друг',other.messages[-1].text)

    async def test_start_business_link_is_not_store_menu(self):
        message=FakeMessage('/start bizChat22')
        with patch.object(bot,'get_database',side_effect=AssertionError('No store menu')):
            await bot.command_menu(message,self.state)
        self.assertEqual(self.state.state,ComposeState.text)

    async def test_no_available_chats_never_guesses_destination(self):
        self.store.rows.clear()
        await self.service.command(self.message,self.state)
        self.assertFalse(self.drafts.items)
        self.assertIn('Нет доступных',self.message.messages[-1].text)
        self.client.send_message.assert_not_awaited()

    async def test_text_state_and_cancel(self):
        self.message.text='/say'
        await self.service.command(self.message,self.state)
        self.assertEqual(self.state.state,ComposeState.text)
        await self.service.cancel(self.message,self.state)
        self.assertIsNone(self.state.state)
        self.assertFalse(self.drafts.items)

    async def test_regular_messages_only_track_metadata_no_reply_no_contents(self):
        incoming=FakeMessage(text='secret text',owner=22,chat_id=22)
        incoming.business_connection_id='conn1'
        incoming.date=datetime.now(timezone.utc)
        await self.service.observe_message(incoming)
        self.store.record_incoming.assert_awaited_once()
        self.assertNotIn('secret text',str(self.store.record_incoming.call_args))
        incoming.answer.assert_not_awaited()
        self.client.send_message.assert_not_awaited()
        for owner,sender,type in [(1,None,'private'),(22,object(),'private'),(22,None,'supergroup')]:
            incoming.from_user.id=owner
            incoming.sender_business_bot=sender
            incoming.chat.type=type
            await self.service.observe_message(incoming)
        self.store.record_incoming.assert_awaited_once()

    async def test_existing_connection_recovers_after_restart_from_incoming_update(self):
        self.store.connections.clear()
        incoming=FakeMessage(owner=22,chat_id=22)
        incoming.business_connection_id='conn1'
        incoming.date=datetime.now(timezone.utc)
        incoming.bot=self.client
        await self.service.observe_message(incoming)
        self.client.get_business_connection.assert_awaited_once_with('conn1')
        self.store.save_connection.assert_awaited_once()
        self.store.record_incoming.assert_awaited_once()

    async def test_connection_notifications_only_go_to_account_owner(self):
        await self.service.connection_changed(conn(),self.client)
        self.store.save_connection.assert_awaited_once()
        self.assertEqual(self.client.send_message.call_args.args[0],1)
        self.assertIn('не отвечаю автоматически',self.client.send_message.call_args.args[1])

    async def test_router_registers_business_updates(self):
        dispatcher=Dispatcher(storage=MemoryStorage())
        dispatcher.include_router(self.service.router)
        kinds=dispatcher.resolve_used_update_types()
        self.assertIn('business_connection',kinds)
        self.assertIn('business_message',kinds)
        # Real Dispatcher delivery: ordinary incoming message must not trigger a shop command or reply.
        client=Bot('123456:ABCDEF')
        update=Update(update_id=1,business_message=Message(message_id=1,date=datetime.now(timezone.utc),
            chat=Chat(id=22,type='private',first_name='Friend'),from_user=User(id=22,is_bot=False,first_name='Friend'),
            business_connection_id='conn1',text='/start'))
        try:
            await dispatcher.feed_update(client,update)
            self.store.record_incoming.assert_awaited_once()
            self.client.send_message.assert_not_awaited()
        finally:
            await client.session.close()


class SqlTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_sql_owner_permission_and_window_binding(self):
        pool=SimpleNamespace(fetch=AsyncMock(return_value=[]),fetchrow=AsyncMock(return_value=None))
        store=SecretaryStore(pool)
        await store.target(1,'conn1',22)
        query,*args=pool.fetchrow.call_args.args
        self.assertEqual(args,[1,'conn1',22])
        for constraint in ['owner_id=$1','is_enabled','can_reply','24 hours','connection_id=$2','chat_id=$3']:
            self.assertIn(constraint,query)
        await store.targets(1)
        self.assertIn('LIMIT 20',pool.fetch.call_args.args[0])
        self.assertIn('CREATE TABLE IF NOT EXISTS secretary_connections',SECRETARY_SCHEMA)
        self.assertNotIn('message_text',SECRETARY_SCHEMA)

    async def test_incoming_sql_never_overwrites_recent_timestamp_with_older(self):
        pool=SimpleNamespace(execute=AsyncMock())
        store=SecretaryStore(pool)
        await store.record_incoming('conn1',22,'Title',datetime.now(timezone.utc))
        self.assertIn('GREATEST',pool.execute.call_args_list[0].args[0])
        self.assertIn('LEAST',pool.execute.call_args_list[0].args[0])
        self.assertIn('2 days',pool.execute.call_args_list[1].args[0])

    async def test_connection_save_is_atomic_and_revocation_clears_dialogs(self):
        class Context:
            def __init__(self,value): self.value=value
            async def __aenter__(self): return self.value
            async def __aexit__(self,*args): pass
        db=SimpleNamespace(execute=AsyncMock())
        db.transaction=lambda:Context(db)
        store=SecretaryStore(SimpleNamespace(acquire=lambda:Context(db)))
        await store.save_connection(conn())
        self.assertIn('connection_id<>$2',db.execute.call_args_list[0].args[0])
        self.assertEqual(db.execute.call_args_list[0].args[1:],(1,'conn1'))
        self.assertEqual(db.execute.call_args_list[1].args[1:],('conn1',1,1,True,True))
        db.execute.reset_mock()
        await store.save_connection(conn(enabled=False))
        self.assertIn('DELETE FROM secretary_chats',db.execute.call_args_list[-1].args[0])
        self.assertEqual(db.execute.call_args_list[-1].args[1:],('conn1',))

    def test_real_business_connection_model_rights(self):
        connection=BusinessConnection(id='conn1',user=User(id=1,is_bot=False,first_name='Owner'),
            user_chat_id=1,date=datetime.now(timezone.utc),is_enabled=True,rights=BusinessBotRights(can_reply=True))
        self.assertTrue(can_reply(connection))

    def test_rights_compatibility_and_explicit_denial(self):
        self.assertFalse(can_reply(conn(reply=False)))
        self.assertTrue(can_reply(conn()))
        self.assertFalse(can_reply(SimpleNamespace(rights=SimpleNamespace(can_reply=False),can_reply=True)))
        self.assertTrue(can_reply(SimpleNamespace(rights=None,can_reply=True)))


if __name__=='__main__':
    unittest.main()
