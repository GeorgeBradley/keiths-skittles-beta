# scores/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.game_id = self.scope['url_route']['kwargs']['game_id']
        self.group_name = f"game_{self.game_id}"
        # Join game group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        # Leave game group
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Receive message from WebSocket (if needed)
    async def receive(self, text_data):
        data = json.loads(text_data)
        # Here you could handle client messages if needed.
        pass

    # Receive update from group
    async def game_update(self, event):
        # event should be a dict with update info
        await self.send(text_data=json.dumps(event["data"]))
