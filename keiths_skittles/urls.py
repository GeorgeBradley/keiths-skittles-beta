# keiths_skittles/urls.py
from django.contrib import admin
from django.urls import path, include
from scores.views import past_games, delete_game

urlpatterns = [
    path("", past_games, name="past_games"),
    path("admin/", admin.site.urls),
    path("accounts/", include("users.urls")),
    path("live/", include("scores.urls")),
    path("delete/<int:game_id>/", delete_game, name="delete_game"),
]
