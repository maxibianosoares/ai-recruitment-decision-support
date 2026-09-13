import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from rag.rag_pipeline import rag_pipeline
from django.shortcuts import render

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 1000


@login_required
@require_POST
def ask_rag(request):
    try:
        payload = json.loads(
            request.body or "{}"
        )
    except json.JSONDecodeError:
        return JsonResponse(
            {"error": "Invalid JSON."},
            status=400
        )

    question = str(
        payload.get("question", "")
    ).strip()

    if not question:
        return JsonResponse(
            {"error": "Question is required."},
            status=400
        )

    if len(question) > MAX_QUESTION_LENGTH:
        return JsonResponse(
            {"error": "Question is too long."},
            status=400
        )

    try:
        result = rag_pipeline.ask(question)

        return JsonResponse(
            result,
            status=200
        )

    except Exception:
        logger.exception(
            "RAG request failed."
        )

        return JsonResponse(
            {
                "error":
                    "AI service temporarily unavailable."
            },
            status=500
        )

@login_required
def rag_chat(request):
    return render(
        request,
        "ai_engine/rag_chat.html"
    )