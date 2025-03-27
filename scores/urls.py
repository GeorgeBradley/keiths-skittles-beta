# scores/urls.py
from django.urls import path
from . import views

# app_name = 'scores' # Optional: Define an app namespace

urlpatterns = [
    # Define the root path for this app first if you want one
    path('', views.past_games, name='home'),

    # Other paths
    path("start/", views.start_game, name="start_game"),

    # Decide on a consistent pattern for viewing a game's live state/details
    # Option 1: Use /game/<id>/ for live game
    path("game/<int:game_id>/", views.live_game, name="live_game"),
    # Option 2: Or maybe just /<id>/ (use if no other integer patterns at this level)
    # path("<int:game_id>/", views.live_game, name="live_game"),

    path("game/<int:game_id>/round-complete/", views.round_complete, name="round_complete"), # Example: Nesting round complete
    path("game/<int:game_id>/statistics/", views.game_statistics, name="game_statistics"), # Example: Nesting statistics
    path("game/<int:game_id>/detail/", views.game_detail, name="game_detail"), # Example: Nesting detail
    path("game/<int:game_id>/delete/", views.delete_game, name="delete_game"), # Example: Nesting delete

    path("players/", views.add_player, name="add_player"),
    path("past-games/", views.past_games, name="past_games"), # You might remove this if '' points here
    path("player-stats/", views.player_statistics, name="player_statistics"),
    path('opponent-stats/', views.opponent_statistics, name='opponent_statistics'),

    # AJAX URLs (prefixing with ajax/ is good practice)
    path('ajax/add-opponent/', views.ajax_add_opponent, name='ajax_add_opponent'),
    path('ajax/add-location/', views.ajax_add_location, name='ajax_add_location'),
]