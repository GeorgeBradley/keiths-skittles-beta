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
    # --- ADD THIS LINE ---
    path("game/<int:game_id>/", views.game_detail, name="game_detail"),
    # --------------------
    # Add delete_game URL if you haven't already
    path("delete/<int:game_id>/", views.delete_game, name="delete_game"),
        path("player-stats/", views.player_statistics, name="player_statistics"),
    path('ajax/add-opponent/', views.ajax_add_opponent, name='ajax_add_opponent'),
    path('ajax/add-location/', views.ajax_add_location, name='ajax_add_location'),
    path('opponent-stats/', views.opponent_statistics, name='opponent_statistics'),



]