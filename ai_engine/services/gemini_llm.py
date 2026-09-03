# import json

# from google import genai

# from django.conf import settings


# client = genai.Client(
#     api_key=settings.GEMINI_API_KEY
# )


# def generate_json(
#     prompt,
#     default=None
# ):

#     try:

#         response = client.models.generate_content(

#             model=settings.GEMINI_MODEL,

#             contents=prompt

#         )

#         text = response.text

#         text = text.replace(
#             "```json",
#             ""
#         )

#         text = text.replace(
#             "```",
#             ""
#         )

#         return json.loads(text)

#     except Exception:

#         return default