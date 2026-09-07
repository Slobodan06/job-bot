"""AI-drafted answers for genuine free-text application questions.

Grounded strictly in the candidate's saved resume + profile. If the evidence does
not support an answer the model returns an empty string and the field is left for
the user to complete.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import AsyncOpenAI

from app.extension.autofill import custom_answer_for
from app.services.openai_compat import chat_completion_controls
from app.services.resume_analysis_ai import _json_object
from app.services.resume_model import ResumeModel

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You draft answers to job-application questions for one candidate. Use ONLY "
    "the facts in RESUME and PROFILE. Never invent an employer, project, metric, "
    "skill, or qualification. Keep each answer concise (2-5 sentences), first "
    "person, specific, and honest. If the provided facts do not support a real "
    "answer, return an empty string for that question. Return strict JSON."
)


async def draft_free_text_answers(
    *,
    fields: list[dict[str, Any]],
    model: ResumeModel | None,
    profile: dict[str, Any],
    job_text: str,
    job_title: str,
    company: str,
) -> dict[str, str]:
    answers: dict[str, str] = {}
    pending: list[dict[str, str]] = []
    for field in fields:
        label = str(field.get("label") or field.get("name") or "")
        key = str(field.get("key"))
        preset = custom_answer_for(label, profile)
        if preset:
            answers[key] = preset
            continue
        pending.append({"key": key, "question": label[:400]})

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not pending or not api_key or model is None:
        return answers

    model_name = (
        os.getenv("OPENAI_MODEL_WRITE", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip()
        or "gpt-4o-mini"
    )
    resume_json = json.dumps(model.model_dump(exclude={"meta"}), ensure_ascii=False)[:12000]
    profile_json = json.dumps(
        {k: v for k, v in profile.items() if k != "custom_answers"}, ensure_ascii=False
    )[:2000]
    user = (
        f"TARGET ROLE: {job_title} at {company}\n\n"
        f"JOB DESCRIPTION:\n{job_text[:6000]}\n\n"
        f"RESUME:\n{resume_json}\n\n"
        f"PROFILE:\n{profile_json}\n\n"
        f"QUESTIONS (answer each; empty string when unsupported):\n"
        f"{json.dumps(pending, ensure_ascii=False)}\n\n"
        'Return {"answers": [{"key": "...", "answer": "..."}]}'
    )
    try:
        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120") or "120")
        client = AsyncOpenAI(api_key=api_key, timeout=max(30.0, min(timeout, 300.0)))
        completion = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            **chat_completion_controls(model_name, max_output_tokens=2500, temperature=0.3),
        )
        payload = _json_object(completion.choices[0].message.content or "")
    except Exception:
        logger.exception("Free-text answer drafting failed")
        return answers

    for item in payload.get("answers") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        text = str(item.get("answer") or "").strip()
        if key and text:
            answers[key] = text[:4000]
    return answers
