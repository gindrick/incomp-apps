from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a marketing analyst. Given a list of social media post texts from a single company, "
    "extract the 3-5 main recurring themes or messages. Respond with a JSON array of short strings "
    '(2-4 words each), e.g. ["fast delivery", "product innovation", "sustainability"]. '
    "No other text, just the JSON array."
)


def analyze_main_message(posts_text: list[str]) -> list[str]:
    base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000")
    api_key = os.environ.get("LITELLM_API_KEY", "sk-mysecretkey")
    model = os.environ.get("LITELLM_MODEL", "gpt-4o-mini")

    if not posts_text:
        return []

    combined = "\n---\n".join(posts_text[:10])  # cap at 10 posts to avoid token bloat

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": combined},
                ],
                "max_tokens": 200,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        import json
        themes = json.loads(content)
        if isinstance(themes, list):
            return [str(t) for t in themes[:5]]
    except Exception as exc:
        logger.warning("LiteLLM analysis failed — %s", exc)

    return []
