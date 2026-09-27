"""Answer job-application questions ("Why do you want to work here?", "Describe a
time you…") from the candidate's resume + the job description, ChatGPT-style.

The answer is streamed token by token. It is grounded in the resume: the model may
connect the candidate's real experience to the job, but must never invent
employers, projects, numbers or credentials — where a question needs a fact the
resume doesn't contain (salary, notice period, visa…), it leaves a clearly marked
[placeholder] for the candidate to fill in instead of guessing.
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from typing import Literal

from openai import AsyncOpenAI

from app.services.openai_compat import chat_completion_controls
from app.services.resume_model import ResumeModel

logger = logging.getLogger(__name__)

AnswerLength = Literal["concise", "standard", "detailed"]

_LENGTH_GUIDE: dict[str, str] = {
    "concise": "Keep it to about 60-120 words (a short paragraph) unless the question clearly needs less.",
    "standard": "Aim for about 150-250 words.",
    "detailed": "Give a thorough answer of about 300-450 words, with a concrete example from the resume.",
}

_MAX_RESUME_CHARS = 14000
_MAX_JD_CHARS = 9000
_MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = """You are an expert career coach helping ONE candidate answer questions on a job application form (and in screening interviews). You write the answer the candidate will paste into the form, in the candidate's own voice.

Grounding rules (strict):
- Use ONLY facts found in the RESUME. Never invent employers, job titles, projects, dates, metrics, tools, degrees, certifications or achievements.
- You MAY connect the candidate's real experience to the JOB DESCRIPTION and explain why it is relevant — that reasoning is the value you add.
- If the question needs a fact the resume doesn't contain (salary expectations, notice period, visa status, availability, a specific story not in the resume…), write the best honest answer you can and insert a clear placeholder in square brackets, e.g. [your expected salary range], for the candidate to fill in. Never guess such facts.
- If a skill the job asks for is missing from the resume, don't claim it; highlight the closest real, transferable experience instead.

Writing rules:
- First person, confident, specific, professional and warm — not generic or over-the-top. No clichés like "I am a results-driven professional".
- Answer the question that was asked, directly, in the first sentence.
- For behavioral questions ("Tell me about a time…"), use a compact STAR structure (situation, task, action, result) drawn from a real resume entry.
- For "why this company / role" questions, tie specific points from the job description to specific resume experience.
- Plain text only: no markdown headings, no bold/italics. Short paragraphs; simple "- " bullets only if the question asks for a list.
- Output only the answer text — no preamble like "Here is your answer", no notes after it (placeholders are the only way to flag missing info).
- For follow-up requests (e.g. "make it shorter", "more technical", "rewrite for a startup"), revise your previous answer accordingly and output the full revised answer."""


def resume_text_from_model(model: ResumeModel) -> str:
    parts = [
        model.contact_block(),
        f"SUMMARY:\n{model.professional_summary}" if model.professional_summary.strip() else "",
        f"EXPERIENCE:\n{model.experience_text()}",
        f"SKILLS:\n{model.skills_text()}",
        f"EDUCATION:\n{model.education_text()}",
        model.extras_text(),
    ]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def openai_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _model_name() -> str:
    return (
        os.getenv("OPENAI_MODEL_ANSWERS", "").strip()
        or os.getenv("OPENAI_MODEL_WRITE", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip()
        or "gpt-4o-mini"
    )


def build_messages(
    *,
    resume_text: str,
    job_description: str,
    question: str,
    history: list[dict[str, str]],
    company_name: str = "",
    target_role: str = "",
    length: str = "standard",
) -> list[dict[str, str]]:
    """Chat messages: grounding context first, then prior turns, then the new question."""
    context = [
        f"COMPANY: {company_name.strip() or '(not specified)'}",
        f"TARGET ROLE: {target_role.strip() or '(infer from the job description)'}",
        f"JOB DESCRIPTION:\n{job_description.strip()[:_MAX_JD_CHARS] or '(not provided — answer from the resume alone)'}",
        f"RESUME:\n{resume_text.strip()[:_MAX_RESUME_CHARS]}",
    ]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "\n\n".join(context)},
    ]
    for turn in history[-_MAX_HISTORY_MESSAGES:]:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:6000]})
    guide = _LENGTH_GUIDE.get(length, _LENGTH_GUIDE["standard"])
    messages.append({"role": "user", "content": f"{question.strip()}\n\n(Length: {guide})"})
    return messages


async def open_answer_stream(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """Start the OpenAI request, then return an iterator of answer text chunks.

    The request is opened *before* returning so auth/model errors surface as a
    normal exception (→ HTTP error) instead of in the middle of a streamed body.
    """
    model = _model_name()
    timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120") or "120")
    client = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY", "").strip(), timeout=max(30.0, min(timeout, 300.0))
    )
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        **chat_completion_controls(model, max_output_tokens=1600, temperature=0.5),
    )

    async def chunks() -> AsyncIterator[str]:
        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception:
            logger.exception("Application answer stream broke off")
            yield "\n\n[The answer was interrupted — please try again.]"

    return chunks()
