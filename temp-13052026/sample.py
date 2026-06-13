"""
from openai import OpenAI
from app.config import settings

client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,  # -> https://llm.kimchi.dev/openai/v1
)

resp = client.chat.completions.create(
    model=settings.LLM_MODEL,           # "kimi-k2.6"
    messages=[{"role": "user", "content": "ping"}],
)
print(resp.choices[0].message.content)
"""