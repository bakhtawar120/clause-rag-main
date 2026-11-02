"""Model factories (LangChain `init_chat_model` / `init_embeddings`) plus offline test models.

Real providers: anything LangChain supports ("ollama", "openai", "anthropic", "google_genai", ...).
Install the provider package first, e.g. `uv add langchain-openai`.

The "fake" provider needs no network and no API key. It is used by the test suite and is handy
for trying the UI offline. Its answers are extractive (copied sentences), so quality is limited.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator
from typing import Any

import numpy as np
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.core.config import Settings
from app.rag.prompts import NOT_FOUND
from app.rag.text import content_tokens, split_sentences, tokenize


# ============================================================================ factories
def build_chat_model(settings: Settings, *, purpose: str = "chat") -> BaseChatModel:
    if purpose == "judge":
        provider = settings.judge_provider or settings.chat_provider
        model = settings.judge_model or settings.chat_model
        api_key = settings.judge_api_key or settings.chat_api_key
        base_url = settings.judge_base_url or settings.chat_base_url
        temperature = 0.0
    else:
        provider, model = settings.chat_provider, settings.chat_model
        api_key, base_url, temperature = settings.chat_api_key, settings.chat_base_url, settings.chat_temperature

    if provider == "fake":
        return ExtractiveChatModel()

    from langchain.chat_models import init_chat_model

    kwargs: dict[str, Any] = {"temperature": temperature}
    if api_key is not None:
        kwargs["api_key"] = api_key.get_secret_value()
    if base_url:
        kwargs["base_url"] = base_url
    return init_chat_model(model, model_provider=provider, **kwargs)


def build_embeddings(settings: Settings) -> Embeddings:
    if settings.embedding_provider == "fake":
        return HashingEmbeddings()

    from langchain.embeddings import init_embeddings

    kwargs: dict[str, Any] = {}
    if settings.embedding_api_key is not None:
        kwargs["api_key"] = settings.embedding_api_key.get_secret_value()
    if settings.embedding_base_url:
        kwargs["base_url"] = settings.embedding_base_url
    return init_embeddings(settings.embedding_model, provider=settings.embedding_provider, **kwargs)


def embedding_signature(settings: Settings) -> str:
    """Identifies the embedding space. If it changes, every stored vector must be re-embedded."""
    if settings.embedding_provider == "fake":
        return f"fake:hashing-{HashingEmbeddings.DIM}"
    return f"{settings.embedding_provider}:{settings.embedding_model}"


def message_text(message: BaseMessage) -> str:
    text = message.text
    return text if isinstance(text, str) else str(text)


# ============================================================================ offline embeddings
class HashingEmbeddings(Embeddings):
    """Deterministic bag-of-words embeddings (unigrams + bigrams, signed feature hashing).

    No model download, no network. Captures word overlap, not deep meaning, which is enough
    for tests and offline demos.
    """

    DIM = 768

    def _vector(self, text: str) -> list[float]:
        tokens = tokenize(text)
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        vec = np.zeros(self.DIM, dtype=np.float32)
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.DIM
            sign = 1.0 if (value >> 63) & 1 else -1.0
            weight = 0.5 if "_" in feature else 1.0
            vec[index] += sign * weight
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


# ============================================================================ offline chat model
_SOURCE_BLOCK = re.compile(r"\[(\d+)\] \((.*?)\)\n(.*?)(?=\n\n\[\d+\] \(|\n\nQUESTION:|\Z)", re.DOTALL)
_HEADING_LINE = re.compile(r"^(#+\s+.*|\d+(\.\d+)*\.?\s+[A-Z][^.]{0,80}|[A-Z][\w &/,'()-]{0,60}\??)$")
REFUSAL_THRESHOLD = 0.34
_REFERENTIAL = {"it", "its", "that", "this", "these", "those", "they", "them", "their", "one", "ones", "same", "also"}


class ExtractiveChatModel(BaseChatModel):
    """A deterministic stand-in for an LLM, driven by the TASK line of the system prompt."""

    @property
    def _llm_type(self) -> str:
        return "clause-extractive-fake"

    # ---- LangChain hooks
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._respond(messages)))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        text = self._respond(messages)
        for piece in re.findall(r"\S+\s*", text):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk

    # ---- task routing
    def _respond(self, messages: list[BaseMessage]) -> str:
        system = next((message_text(m) for m in messages if isinstance(m, SystemMessage)), "")
        user = next((message_text(m) for m in reversed(messages) if isinstance(m, HumanMessage)), "")
        task = system.splitlines()[0].replace("TASK:", "").strip() if system.startswith("TASK:") else "answer"
        handlers = {
            "answer": self._answer,
            "rewrite": self._rewrite,
            "expand": self._expand,
            "rerank": self._rerank,
            "judge-faithfulness": self._judge_faithfulness,
            "judge-relevance": self._judge_relevance,
            "judge-correctness": self._judge_correctness,
        }
        return handlers.get(task, self._answer)(user)

    @staticmethod
    def _field(text: str, label: str) -> str:
        match = re.search(rf"(?:^|\n){re.escape(label)}:[ \t]*\n?(.*?)(?=\n\n[A-Z][A-Z -]+:|\Z)", text, re.DOTALL)
        return match.group(1).strip() if match else ""

    def _answer(self, user: str) -> str:
        question = self._field(user, "QUESTION") or user
        sources = _SOURCE_BLOCK.findall(user)
        q = content_tokens(question)
        if not q or not sources:
            return NOT_FOUND
        candidates: list[tuple[float, int, str, set[str]]] = []
        for rank, (num, header, body) in enumerate(sources):
            context_tokens = set(content_tokens(header))
            paragraph: list[str] = []
            paragraphs: list[str] = []
            for line in [ln.strip() for ln in body.splitlines()] + [""]:
                if not line or (_HEADING_LINE.match(line) and not line.endswith(".")):
                    if paragraph:
                        paragraphs.append(" ".join(paragraph))
                        paragraph = []
                    if line:
                        context_tokens |= content_tokens(line)
                    continue
                paragraph.append(line)
            for para in paragraphs:
                for sentence in split_sentences(para):
                    own = content_tokens(sentence)
                    if len(own) < 2 or not (q & own):
                        continue  # "Yes." or a sentence that shares nothing with the question
                    tokens = own | context_tokens
                    coverage = (len(q & own) + 0.5 * len((q & tokens) - own)) / len(q)
                    candidates.append((coverage - rank * 0.001, int(num), sentence, tokens))
        if not candidates:
            return NOT_FOUND
        candidates.sort(key=lambda c: c[0], reverse=True)
        best = candidates[0]
        if best[0] < REFUSAL_THRESHOLD:
            return NOT_FOUND
        parts = [f"{best[2]} [{best[1]}]"]
        missing = q - best[3]
        for score, num, sentence, tokens in candidates[1:]:
            if missing & tokens and score >= 0.3 and sentence != best[2]:
                parts.append(f"{sentence} [{num}]")
                break
        return " ".join(parts)

    def _rewrite(self, user: str) -> str:
        question = self._field(user, "FOLLOW-UP QUESTION")
        history = self._field(user, "CHAT HISTORY")
        last_user = ""
        for line in history.splitlines():
            if line.lower().startswith("user:"):
                last_user = line.split(":", 1)[1].strip()
        words = set(re.findall(r"[a-z']+", question.lower()))
        refers_back = bool(words & _REFERENTIAL) or question.lower().startswith(("and ", "what about", "how about"))
        if last_user and refers_back:
            return f"{question} ({last_user})"
        return question

    def _expand(self, user: str) -> str:
        return self._field(user, "QUESTION") or user

    def _rerank(self, user: str) -> str:
        question = self._field(user, "QUESTION")
        q = content_tokens(question)
        passages = re.findall(r"\[(\d+)\]\s(.*?)(?=\n\n\[\d+\]\s|\Z)", self._field(user, "PASSAGES"), re.DOTALL)
        scores = [round(10 * len(q & content_tokens(p)) / max(1, len(q)), 1) for _, p in passages]
        return json.dumps({"scores": scores})

    def _judge_faithfulness(self, user: str) -> str:
        context = content_tokens(self._field(user, "CONTEXT"))
        answer = re.sub(r"\[\d+\]", "", self._field(user, "ANSWER"))
        if NOT_FOUND.lower()[:20] in answer.lower():
            return json.dumps({"supported": 0, "total": 0, "reason": "Refusal, no claims."})
        sentences = [s for s in split_sentences(answer) if content_tokens(s)]
        supported = sum(1 for s in sentences if len(content_tokens(s) & context) / len(content_tokens(s)) >= 0.7)
        return json.dumps({"supported": supported, "total": len(sentences), "reason": "Token overlap check."})

    def _judge_relevance(self, user: str) -> str:
        q = content_tokens(self._field(user, "QUESTION"))
        a = content_tokens(self._field(user, "ANSWER"))
        score = len(q & a) / len(q) if q else 0.0
        return json.dumps({"score": round(min(1.0, score * 1.25), 2), "reason": "Token overlap check."})

    def _judge_correctness(self, user: str) -> str:
        ref = tokenize(self._field(user, "REFERENCE ANSWER"))
        ans = tokenize(re.sub(r"\[\d+\]", "", self._field(user, "ANSWER")))
        common = sum(min(ref.count(t), ans.count(t)) for t in set(ref))
        if not ref or not ans or common == 0:
            return json.dumps({"score": 0.0, "reason": "No overlap."})
        precision, recall = common / len(ans), common / len(ref)
        f1 = 2 * precision * recall / (precision + recall)
        return json.dumps({"score": round(min(1.0, math.sqrt(f1)), 2), "reason": "Token F1 check."})
