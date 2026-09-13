from django.urls import path

from .views import ask_rag, rag_chat


urlpatterns = [
    path(
        "ai-assistant/",
        rag_chat,
        name="rag_chat"
    ),

    path(
        "api/rag/ask/",
        ask_rag,
        name="ask_rag"
    ),
]