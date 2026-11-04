"""单聊天回归用客户端；显式创建聊天并在请求中携带 chat_id。"""
from fastapi.testclient import TestClient


class ChatTestClient(TestClient):
    @property
    def chat_id(self):
        chats = self.get('/api/chats').json()
        if chats:
            return chats[0]['id']
        return super().post('/api/chats').json()['id']

    def post(self, url, **kwargs):
        if url in ('/api/chat', '/api/refunds/confirm'):
            body = dict(kwargs.get('json', {}))
            if 'chat_id' not in body:
                body['chat_id'] = self.chat_id
            kwargs['json'] = body
        return super().post(url, **kwargs)
