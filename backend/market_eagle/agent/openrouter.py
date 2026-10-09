"""OpenRouter Chat Completions adapter for the fixed free research model."""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from .activities import (
    EXPLANATION_INSTRUCTIONS,
    SUMMARY_INSTRUCTIONS,
    interpretation_instructions,
)
from .models import Decision

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
FREE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


def _strict_decision_schema() -> dict:
    schema = Decision.model_json_schema()

    def normalize(node: dict | list) -> None:
        if isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    normalize(item)
            return
        node.pop("default", None)
        if "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for value in node.values():
            if isinstance(value, (dict, list)):
                normalize(value)

    normalize(schema)
    return schema


class OpenRouterResearchModel:
    def __init__(self, *, api_key: str, model: str, client: OpenAI | None = None):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        if model != FREE_MODEL:
            raise ValueError(f"OPENROUTER_MODEL must be {FREE_MODEL}")
        self.model = model
        self.client = client or OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            max_retries=0,
            timeout=45.0,
        )

    def _complete(
        self, instructions: str, payload: dict | list[dict], *, structured: bool
    ) -> str:
        options: dict[str, Any] = {}
        if structured:
            options["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_decision_v1",
                    "strict": True,
                    "schema": _strict_decision_schema(),
                },
            }
            options["extra_body"] = {"provider": {"require_parameters": True}}
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
            max_tokens=2048 if structured else 512,
            **options,
        )
        choice = response.choices[0]
        if choice.finish_reason != "stop" or not choice.message.content:
            raise ValueError("OpenRouter did not return a complete text response")
        return choice.message.content

    def interpret(self, context: dict, *, feedback: str | None = None) -> Decision:
        content = self._complete(
            interpretation_instructions(context),
            {
                "question": context["question"],
                "summary": context["summary"],
                "recent_turns": context["recent_turns"],
                "validation_feedback": feedback,
            },
            structured=True,
        )
        return Decision.model_validate_json(content)

    def explain(self, question: str, result: dict, assumptions: list[str]) -> str:
        return self._complete(
            EXPLANATION_INSTRUCTIONS,
            {"question": question, "result": result, "assumptions": assumptions},
            structured=False,
        )

    def summarize(self, turns: list[dict]) -> str:
        return self._complete(SUMMARY_INSTRUCTIONS, turns, structured=False)[:4000]
