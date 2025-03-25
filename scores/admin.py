# scores/admin.py
from django.contrib import admin
from .models import Game, Player, GamePlayer, Score

admin.site.register(Game)
admin.site.register(Player)
admin.site.register(GamePlayer)
admin.site.register(Score)
