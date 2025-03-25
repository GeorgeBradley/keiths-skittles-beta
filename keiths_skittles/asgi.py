# keiths_skittles/asgi.py
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import keiths_skittles.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "keiths_skittles.settings")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            keiths_skittles.routing.websocket_urlpatterns
        )
    ),
})
