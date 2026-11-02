"""AI-drafted answers for genuine free-text application questions.

Grounded strictly in the resume tailored for this job + the job description. If the
evidence does not support an answer the model returns an empty string and the member
answers it themselves. Drafts are shown for the member to copy, never typed into forms.
"""
from __future__ import annotations

import json
import logging
from typing import Any


from app.extension.autofill import custom_answer_for
from app.services.llm_config import llm_api_key, llm_model, make_llm_client
from app.services.openai_compat import chat_completion_controls
from app.services.resume_analysis_ai import _json_object
from app.services.resume_model import ResumeModel

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You draft answers to job-application questions for one candidate. Use ONLY "
    "the facts in RESUME and PROFILE, and tie each answer to what JOB DESCRIPTION "
    "asks for. Never invent an employer, project, metric, skill, or qualification. "
    "Keep each answer concise (2-5 sentences), first person, specific, and honest. "
    "Answer the question actually asked. Return an empty string when the facts do "
    "not support a real answer, and for anything only the candidate can know: "
    "accommodation or medical needs, personal circumstances, preferences, or "
    "availability. Return strict JSON."
)

# Never sent to the AI: secrets, and demographics no written answer should draw on.
_PRIVATE_PROFILE_KEYS = frozenset({
    "custom_answers", "application_password", "application_password_enc",
    "gender", "hispanic_latino", "race_ethnicity", "veteran_status", "disability_status",
})


async def draft_free_text_answers(
    *,
    fields: list[dict[str, Any]],
    model: ResumeModel | None,
    profile: dict[str, Any],
    job_text: str,
    job_title: str,
    company: str,
    tailored_text: str = "",
) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (the member's own saved answers, AI drafts), both by field key.

    `tailored_text` is the resume tailored for this job; without one, the saved base resume."""
    answers: dict[str, str] = {}
    drafts: dict[str, str] = {}
    pending: list[dict[str, str]] = []
    for field in fields:
        label = str(field.get("label") or field.get("name") or "")
        key = str(field.get("key"))
        preset = custom_answer_for(label, profile)
        if preset:
            answers[key] = preset
            continue
        pending.append({"key": key, "question": label[:400]})

    api_key = llm_api_key()
    if not pending or not api_key or (model is None and not tailored_text):
        return answers, drafts

    model_name = llm_model("OPENAI_MODEL_WRITE", "OPENAI_MODEL", openai_default="gpt-4o-mini", role="write")
    resume = tailored_text or json.dumps(model.model_dump(exclude={"meta"}), ensure_ascii=False)
    profile_json = json.dumps(
        {k: v for k, v in profile.items() if k not in _PRIVATE_PROFILE_KEYS}, ensure_ascii=False
    )[:2000]
    user = (
        f"TARGET ROLE: {job_title} at {company}\n\n"
        f"JOB DESCRIPTION:\n{job_text[:6000]}\n\n"
        f"RESUME:\n{resume[:12000]}\n\n"
        f"PROFILE:\n{profile_json}\n\n"
        f"QUESTIONS (answer each; empty string when unsupported):\n"
        f"{json.dumps(pending, ensure_ascii=False)}\n\n"
        'Return {"answers": [{"key": "...", "answer": "..."}]}'
    )
    try:
        client = make_llm_client(api_key=api_key)
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
        return answers, drafts

    for item in payload.get("answers") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        text = str(item.get("answer") or "").strip()
        if key and text:
            drafts[key] = text[:4000]
    return answers, drafts
