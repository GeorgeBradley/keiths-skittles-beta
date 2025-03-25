# keiths_skittles/urls.py
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("scores.urls")),
    path("users/", include("users.urls")),
]
