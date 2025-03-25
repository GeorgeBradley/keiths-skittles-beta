# scores/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("start/", views.start_game, name="start_game"),
        path("live/<int:game_id>/", views.live_game, name="live_game"),
        path("round-complete/<int:game_id>/", views.round_complete, name="round_complete"),
        path("statistics/<int:game_id>/", views.game_statistics, name="game_statistics"),
        path("players/", views.add_player, name="add_player"),
        path("past-games/", views.past_games, name="past_games"),
    ]