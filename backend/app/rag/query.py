"""Pre-retrieval: query routing, query transformation (rewrite) and query decomposition (expansion)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.models import message_text
from app.rag.prompts import EXPAND_SYSTEM, EXPAND_USER, REWRITE_SYSTEM, REWRITE_USER

log = logging.getLogger(__name__)

_SMALLTALK = re.compile(
    r"^\s*(hi|hello|hey|salam|assalam[ou]?\s*alaikum|good (morning|afternoon|evening)|thanks?( you)?|thank you|"
    r"ok(ay)?|cool|great|who are you|what can you do|help)\b[\s!.?]*$",
    re.IGNORECASE,
)


@dataclass
class QueryPlan:
    original: str
    route: str = "documents"  # documents | smalltalk
    standalone: str = ""
    sub_queries: list[str] = field(default_factory=list)

    @property
    def search_queries(self) -> list[str]:
        queries = [self.standalone or self.original, *self.sub_queries]
        seen, unique = set(), []
        for q in queries:
            key = q.strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(q.strip())
        return unique


def route_query(question: str) -> str:
    """Cheap, deterministic routing: greetings and thanks do not need a document search."""
    return "smalltalk" if _SMALLTALK.match(question) and len(question.split()) <= 6 else "documents"


def rewrite_query(llm: BaseChatModel, question: str, history: list[tuple[str, str]]) -> str:
    """Turn a follow-up ("and for contractors?") into a standalone question using recent turns."""
    if not history:
        return question
    lines = [f"{'User' if role == 'user' else 'Assistant'}: {re.sub(r'\[\d+\]', '', text)[:500]}" for role, text in history]
    try:
        result = llm.invoke(
            [SystemMessage(REWRITE_SYSTEM), HumanMessage(REWRITE_USER.format(history="\n".join(lines), question=question))]
        )
        rewritten = message_text(result).strip().strip('"').splitlines()[0].strip() if message_text(result).strip() else ""
        return rewritten or question
    except Exception as exc:  # never fail the answer because the rewrite failed
        log.warning("Query rewrite failed, using the original question: %s", exc)
        return question


def expand_query(llm: BaseChatModel, question: str, max_queries: int) -> list[str]:
    """Split a complex or multi-part question into focused sub-queries."""
    try:
        result = llm.invoke(
            [SystemMessage(EXPAND_SYSTEM.format(max_queries=max_queries)), HumanMessage(EXPAND_USER.format(question=question))]
        )
        lines = [re.sub(r"^[\-\*\d.)\s]+", "", ln).strip() for ln in message_text(result).splitlines()]
        return [ln for ln in lines if len(ln) > 3][:max_queries]
    except Exception as exc:
        log.warning("Query expansion failed: %s", exc)
        return []


def plan_query(
    llm: BaseChatModel,
    question: str,
    history: list[tuple[str, str]],
    *,
    rewrite: bool,
    expand: bool,
    max_sub_queries: int,
) -> QueryPlan:
    plan = QueryPlan(original=question, route=route_query(question))
    if plan.route != "documents":
        return plan
    plan.standalone = rewrite_query(llm, question, history) if rewrite else question
    if expand:
        plan.sub_queries = [q for q in expand_query(llm, plan.standalone, max_sub_queries) if q != plan.standalone]
    return plan
