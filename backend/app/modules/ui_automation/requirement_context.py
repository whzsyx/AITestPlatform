"""Requirement-document context helpers for UI automation execution."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

MAX_REQUIREMENT_CONTEXT_CHARS = 2600
_MAX_PARAGRAPH_CHARS = 900
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-zA-Z0-9_#-]{2,}")


def _clamp(text: str, max_chars: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 1)].rstrip() + "…"


def _query_terms(text: str) -> set[str]:
    lower = (text or "").lower()
    terms = {m.group(0) for m in _WORD_RE.finditer(lower)}
    for cjk in _CJK_RE.findall(text or ""):
        if len(cjk) <= 2:
            terms.add(cjk)
            continue
        terms.update(cjk[i : i + 2] for i in range(len(cjk) - 1))
    return {t for t in terms if len(t) >= 2}


def _split_paragraphs(text: str) -> list[str]:
    raw_parts = re.split(r"\n\s*\n|\r\n\s*\r\n", text or "")
    parts: list[str] = []
    for raw in raw_parts:
        normalized = re.sub(r"\s+", " ", raw).strip()
        if normalized:
            parts.append(_clamp(normalized, _MAX_PARAGRAPH_CHARS))
    return parts


def _score_paragraph(paragraph: str, terms: set[str]) -> int:
    lower = paragraph.lower()
    return sum(1 for term in terms if term and term in lower)


def extract_relevant_excerpt(
    content_text: str,
    *,
    query: str,
    max_chars: int = MAX_REQUIREMENT_CONTEXT_CHARS,
) -> str:
    """Return the most relevant requirement paragraphs for a testcase query."""
    paragraphs = _split_paragraphs(content_text)
    if not paragraphs:
        return ""
    terms = _query_terms(query)
    if not terms:
        return _clamp("\n\n".join(paragraphs[:3]), max_chars)

    scored = [
        (idx, _score_paragraph(paragraph, terms), paragraph)
        for idx, paragraph in enumerate(paragraphs)
    ]
    positives = [item for item in scored if item[1] > 0]
    selected = positives if positives else scored[:3]
    selected = sorted(selected, key=lambda item: (-item[1], item[0]))[:5]
    selected = sorted(selected, key=lambda item: item[0])

    out: list[str] = []
    used = 0
    for _, _, paragraph in selected:
        extra = len(paragraph) + (2 if out else 0)
        if out and used + extra > max_chars:
            break
        if not out and len(paragraph) > max_chars:
            out.append(_clamp(paragraph, max_chars))
            break
        out.append(paragraph)
        used += extra
    return "\n\n".join(out).strip()


def build_requirement_context_text(
    *,
    document_name: str,
    content_text: str,
    query: str,
    max_chars: int = MAX_REQUIREMENT_CONTEXT_CHARS,
) -> str:
    excerpt_budget = max(300, max_chars - len(document_name) - 80)
    excerpt = extract_relevant_excerpt(
        content_text,
        query=query,
        max_chars=excerpt_budget,
    )
    if not excerpt:
        return ""
    return _clamp(
        f"来源文档：{document_name}\n相关需求片段：\n{excerpt}",
        max_chars,
    )


def build_case_requirement_query(testcase: Any) -> str:
    parts: list[str] = [
        str(getattr(testcase, "title", "") or ""),
        str(getattr(testcase, "precondition", "") or ""),
    ]
    for step in list(getattr(testcase, "steps", []) or []):
        parts.append(str(getattr(step, "action", "") or ""))
        parts.append(str(getattr(step, "expected_result", "") or ""))
    return "\n".join(p for p in parts if p.strip())


async def load_requirement_contexts(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    testcases: Sequence[Any],
    max_chars: int = MAX_REQUIREMENT_CONTEXT_CHARS,
) -> dict[uuid.UUID, str]:
    """Load source requirement snippets for AI-generated testcases.

    The stable link is ``testcase.generation_batch_id`` →
    ``ai_generation_batches.document_id``. Manual/imported cases simply do not
    get a source document context.
    """
    batch_ids = {
        getattr(tc, "generation_batch_id", None)
        for tc in testcases
        if getattr(tc, "generation_batch_id", None) is not None
    }
    if not batch_ids:
        return {}

    from app.modules.testcases.models import AIGenerationBatch

    result = await db.execute(
        select(AIGenerationBatch)
        .options(selectinload(AIGenerationBatch.document))
        .where(
            AIGenerationBatch.project_id == project_id,
            AIGenerationBatch.id.in_(batch_ids),
        )
    )
    batches = {batch.id: batch for batch in result.scalars().all()}

    contexts: dict[uuid.UUID, str] = {}
    for tc in testcases:
        tc_id = getattr(tc, "id", None)
        batch = batches.get(getattr(tc, "generation_batch_id", None))
        doc = getattr(batch, "document", None) if batch is not None else None
        if tc_id is None or doc is None:
            continue
        if getattr(doc, "project_id", None) != project_id:
            continue
        content = getattr(doc, "content_text", None) or ""
        context = build_requirement_context_text(
            document_name=getattr(doc, "filename", "") or "未命名需求文档",
            content_text=content,
            query=build_case_requirement_query(tc),
            max_chars=max_chars,
        )
        if context:
            contexts[tc_id] = context
    return contexts


__all__ = [
    "MAX_REQUIREMENT_CONTEXT_CHARS",
    "build_case_requirement_query",
    "build_requirement_context_text",
    "extract_relevant_excerpt",
    "load_requirement_contexts",
]
