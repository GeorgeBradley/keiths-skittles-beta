# keiths_skittles/routing.py
from django.urls import re_path
from scores.consumers import GameConsumer

websocket_urlpatterns = [
    re_path(r'ws/game/(?P<game_id>\d+)/$', GameConsumer.as_asgi()),
]
