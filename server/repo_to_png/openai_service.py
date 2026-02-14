from __future__ import annotations

import os

import tiktoken
from dotenv import load_dotenv
from openai import OpenAI

from .format_message import format_user_message

load_dotenv()


class OpenAIService:
    def __init__(self) -> None:
        self.default_api_key = os.getenv("OPENAI_API_KEY")
        self.encoding = tiktoken.get_encoding("o200k_base")

    def _resolve_api_key(self, override_api_key: str | None = None) -> str:
        api_key = override_api_key or self.default_api_key
        if not api_key:
            raise ValueError(
                "Missing OpenAI API key. Set OPENAI_API_KEY or pass api_key."
            )
        return api_key

    def completion(
        self,
        *,
        model: str,
        system_prompt: str,
        data: dict[str, str],
        api_key: str | None = None,
        reasoning_effort: str | None = "low",
    ) -> str:
        user_message = format_user_message(data)
        client = OpenAI(api_key=self._resolve_api_key(api_key))
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_completion_tokens": 12000,
            "temperature": 0.2,
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        completion = client.chat.completions.create(**payload)
        content = completion.choices[0].message.content
        if content is None:
            raise ValueError(f"No content from OpenAI model {model}")
        return content

    def count_tokens(self, prompt: str) -> int:
        return len(self.encoding.encode(prompt))
