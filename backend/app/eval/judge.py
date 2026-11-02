"""LLM-as-judge metrics: faithfulness, answer relevance and correctness against a reference.

Each method returns a score in [0, 1] or None if the judge's reply could not be parsed.
Use a strong model as the judge when you can (JUDGE_PROVIDER / JUDGE_MODEL in .env).
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.models import message_text
from app.rag.prompts import (
    JUDGE_CORRECTNESS_SYSTEM,
    JUDGE_CORRECTNESS_USER,
    JUDGE_FAITHFULNESS_SYSTEM,
    JUDGE_FAITHFULNESS_USER,
    JUDGE_RELEVANCE_SYSTEM,
    JUDGE_RELEVANCE_USER,
)

log = logging.getLogger(__name__)


class LLMJudge:
    def __init__(self, llm, retries: int = 1) -> None:
        self.llm = llm
        self.retries = retries

    def _ask(self, system: str, user: str) -> dict | None:
        for attempt in range(self.retries + 1):
            try:
                reply = message_text(self.llm.invoke([SystemMessage(system), HumanMessage(user)]))
                match = re.search(r"\{.*\}", reply, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
            except Exception as exc:
                log.warning("Judge call failed (attempt %d): %s", attempt + 1, exc)
        return None

    def faithfulness(self, context: str, answer: str) -> float | None:
        data = self._ask(JUDGE_FAITHFULNESS_SYSTEM, JUDGE_FAITHFULNESS_USER.format(context=context, answer=answer))
        if not data:
            return None
        try:
            total = int(data.get("total", 0))
            supported = int(data.get("supported", 0))
        except (TypeError, ValueError):
            return None
        if total <= 0:
            return None  # no claims (e.g. a refusal): faithfulness does not apply
        return max(0.0, min(1.0, supported / total))

    def _score(self, system: str, user: str) -> float | None:
        data = self._ask(system, user)
        try:
            return None if not data else max(0.0, min(1.0, float(data.get("score"))))
        except (TypeError, ValueError):
            return None

    def relevance(self, question: str, answer: str) -> float | None:
        return self._score(JUDGE_RELEVANCE_SYSTEM, JUDGE_RELEVANCE_USER.format(question=question, answer=answer))

    def correctness(self, question: str, reference: str, answer: str) -> float | None:
        return self._score(
            JUDGE_CORRECTNESS_SYSTEM, JUDGE_CORRECTNESS_USER.format(question=question, reference=reference, answer=answer)
        )
