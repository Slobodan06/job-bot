#!/usr/bin/env python3
"""Print resume section analytics (same payload as POST /api/parse-sections)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/parse_resume_analytics.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.resume_sections import analyze_resume_file


def _to_api_payload(analysis) -> dict:
    total_bullets = sum(len(role.bullets) for role in analysis.work_experience_roles)
    return {
        "contact": analysis.contact,
        "professional_summary": analysis.professional_summary,
        "professional_experience": analysis.professional_experience,
        "skills": analysis.skills,
        "education": analysis.education,
        "other": analysis.other,
        "work_experience_roles": [
            {
                "header": role.header,
                "company": role.company,
                "title": role.title,
                "location": role.location,
                "period": role.period,
                "bullets": list(role.bullets),
                "bullet_count": len(role.bullets),
            }
            for role in analysis.work_experience_roles
        ],
        "role_count": analysis.role_count,
        "experience_layout": analysis.experience_layout,
        "sections_detected": list(analysis.sections_detected),
        "source_format": analysis.source_format,
        "total_experience_bullets": total_bullets,
    }


def _call_api(api_base: str, token: str, resume_path: Path) -> dict:
    import urllib.request

    boundary = "----JobBotAnalytics"
    body_parts: list[bytes] = []
    filename = resume_path.name
    file_bytes = resume_path.read_bytes()
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(
        f'Content-Disposition: form-data; name="resume"; filename="{filename}"\r\n'.encode()
    )
    body_parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
    body_parts.append(file_bytes)
    body_parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    url = api_base.rstrip("/") + "/api/parse-sections"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume analytics (parse-sections API shape)")
    parser.add_argument("resume", type=Path, help="Path to .docx or .pdf resume")
    parser.add_argument("-o", "--output", type=Path, help="Write JSON to file")
    parser.add_argument(
        "--api",
        metavar="BASE_URL",
        help="Call live API (e.g. http://127.0.0.1:8080) instead of local parse",
    )
    parser.add_argument("--token", help="Bearer token (required with --api)")
    args = parser.parse_args()

    if not args.resume.is_file():
        print(f"File not found: {args.resume}", file=sys.stderr)
        sys.exit(1)

    if args.api:
        if not args.token:
            print("--token is required when using --api", file=sys.stderr)
            sys.exit(1)
        payload = _call_api(args.api, args.token, args.resume)
    else:
        raw = args.resume.read_bytes()
        analysis = analyze_resume_file(raw, filename=args.resume.name)
        payload = _to_api_payload(analysis)

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
