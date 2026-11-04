"""多聊天隔离：真实 API、原生检查点，模型使用可重复的工具批次。"""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

from constants import VISITOR_COOKIE
from fake_chat import TestChatModel, goal_and_tools
from service.app import create_app
from service.storage.store import Store


class ChatIsolationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / 'support.db')
        self.prompts = []
        self.client = self.open()
        self.a = self.create_chat()
        self.b = self.create_chat()
        self.orders = self.client.get('/api/orders').json()

    def model(self, messages):
        self.prompts.append(messages)
        _, tools = goal_and_tools(messages)
        return '' if tools else [('track_shipment', {}), ('preview', {})]

    def open(self):
        client = TestClient(create_app(self.store, lambda: TestChatModel(responder=self.model)))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def create_chat(self):
        response = self.client.post('/api/chats')
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def send(self, chat_id, message, action=None):
        response = self.client.post('/api/chat', json={'chat_id': chat_id, 'message': message, 'action': action})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def select(self, chat_id, order):
        return self.send(chat_id, '选择' + order['product'], {'kind': 'select_order', 'order_id': order['id']})

    def state(self, chat_id):
        return self.client.app.state.conversation.graph.get_state({'configurable': {'thread_id': chat_id}})

    def test_concurrent_interrupts_restart_and_separate_selection(self):
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(lambda chat: self.send(chat, '查物流，再看看能不能退'), [self.a, self.b]))
        self.assertTrue(all('orders' in reply for reply in replies))
        self.assertNotEqual(self.a, self.client.cookies[VISITOR_COOKIE])
        a_interrupt = self.state(self.a).interrupts[0].id
        b_interrupt = self.state(self.b).interrupts[0].id
        self.assertNotEqual(a_interrupt, b_interrupt)

        old = self.client
        self.client = self.open()
        self.client.cookies.update(old.cookies)
        a_result = self.select(self.a, self.orders[0])
        self.assertEqual(a_result['card']['order_id'], self.orders[0]['id'])
        self.assertFalse(self.state(self.a).interrupts)
        self.assertEqual(self.state(self.b).interrupts[0].id, b_interrupt)
        b_result = self.select(self.b, self.orders[1])
        self.assertNotIn('card', b_result)
        self.assertIn('超过', b_result['text'])
        visitor = self.client.cookies[VISITOR_COOKIE]
        self.assertEqual(self.store.chat(visitor, self.a)['selected'], self.orders[0]['id'])
        self.assertEqual(self.store.chat(visitor, self.b)['selected'], self.orders[1]['id'])

    def test_history_and_model_context_are_chat_scoped(self):
        self.select(self.a, self.orders[0])
        self.send(self.a, '聊天 A 的专属问题')
        self.send(self.b, '聊天 B 的专属问题')
        request = self.prompts[-1]
        human_texts = [message.content for message in request if isinstance(message, HumanMessage)]
        self.assertEqual(human_texts, ['聊天 B 的专属问题'])
        self.assertFalse(any('当前会话选中订单' in str(message.content) for message in request))
        history_a = self.client.get('/api/chats/' + self.a).json()
        history_b = self.client.get('/api/chats/' + self.b).json()
        self.assertIn('聊天 A 的专属问题', str(history_a))
        self.assertNotIn('聊天 A 的专属问题', str(history_b))
        self.assertNotIn('聊天 B 的专属问题', str(history_a))
        self.assertIn('card', history_a['turns'][-1]['reply'])

    def test_cancelling_other_chat_does_not_invalidate_card(self):
        self.select(self.a, self.orders[0])
        card = self.send(self.a, '查物流，再看看能不能退')['card']
        self.select(self.b, self.orders[0])
        other_card = self.send(self.b, '查物流，再看看能不能退')['card']
        wrong_chat = self.client.post('/api/refunds/confirm', json={'chat_id': self.b, 'ticket': card['ticket']})
        self.assertEqual(wrong_chat.status_code, 409)
        self.send(self.b, '取消', {'kind': 'cancel_pending'})
        self.assertEqual(self.client.post('/api/refunds/confirm', json={
            'chat_id': self.b, 'ticket': other_card['ticket']}).status_code, 409)
        body = {'chat_id': self.a, 'ticket': card['ticket']}
        first = self.client.post('/api/refunds/confirm', json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.post('/api/refunds/confirm', json=body).json()['id'], first.json()['id'])
        self.assertEqual(len(self.store.sql('SELECT id FROM refunds')), 1)

    def test_foreign_chat_is_rejected_before_read_resume_or_confirm(self):
        self.send(self.a, '查物流，再看看能不能退')
        interrupt_id = self.state(self.a).interrupts[0].id
        stranger = self.open()
        self.assertEqual(stranger.get('/api/chats').json(), [])
        self.assertEqual(stranger.get('/api/chats/' + self.a).status_code, 404)
        response = stranger.post('/api/chat', json={'chat_id': self.a, 'message': '选这笔',
            'action': {'kind': 'select_order', 'order_id': self.orders[0]['id']}})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(stranger.post('/api/refunds/confirm', json={
            'chat_id': self.a, 'ticket': 'P-0000000000000000'}).status_code, 404)
        self.assertEqual(self.state(self.a).interrupts[0].id, interrupt_id)
        self.assertEqual(self.client.post('/api/chat', json={'message': '查物流'}).status_code, 422)
        self.assertEqual(self.client.post('/api/chat', json={
            'chat_id': 'C-0000000000000000', 'message': '查物流'}).status_code, 404)
