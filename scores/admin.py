# scores/admin.py
from django.contrib import admin
from .models import Game, Player, GamePlayer, Score, Location, GameType


admin.site.register(Game)
admin.site.register(GamePlayer)
admin.site.register(Score)
admin.site.register(Player)
admin.site.register(Location)   # New: Allows adding/editing locations
admin.site.register(GameType)  