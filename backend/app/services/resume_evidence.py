"""Evidence-first helpers for truthful resume tailoring."""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from typing import Any


_TECH_OR_DOMAIN_RE = re.compile(
    r"\b(?:OpenAI|Azure OpenAI|Claude|Gemini|Bedrock|LLM|RAG|LangChain|LangGraph|CrewAI|LlamaIndex|"
    r"Semantic Kernel|MCP|Model Context Protocol|Pinecone|Chroma|pgvector|Weaviate|structured JSON|structured outputs?|"
    r"JSON Schema|function calling|tool calling|multi-block responses?|PDF parsing|PyMuPDF|pdfplumber|Camelot|"
    r"OCR|Tesseract|Azure Document Intelligence|AWS Textract|Google Document AI|SQL Server|T-SQL|stored procedures?|PostgreSQL|MySQL|MongoDB|Python|Django|"
    r"Flask|FastAPI|Java|C\#|C\+\+|Go|Golang|Ruby|PHP|Bash|PowerShell|Spring Boot|Spring|Hibernate|JPA|JavaScript|TypeScript|React|Node\.js|"
    r"GraphQL|REST APIs?|Shopify|AWS|Azure|GCP|Docker|Kubernetes|Terraform|CI/CD|GitHub Actions|"
    r"HIPAA|PHI|healthcare|financial|regulated data|production deployment|monitoring|logging|retries?|"
    r"guardrails?|hallucination|validation|structured JSON|PDF parsing|document processing|prompt design|SQL)\b",
    re.I,
)

_SOFT_SKILL_RE = re.compile(
    r"\b(?:communication|leadership|teamwork|collaboration|stakeholder|agile|problem solving|ownership)\b",
    re.I,
)


@dataclass(frozen=True)
class SourceFact:
    fact_id: str
    text: str
    source: str
    company: str = ""
    verified: bool = True
    experience_id: str = ""
    title: str = ""
    source_order: int = 0


@dataclass(frozen=True)
class AtomicFact:
    factId: str
    subject: str
    action: str
    value: str
    technology: str | None
    sourceBulletId: str
    experienceId: str = ""


@dataclass(frozen=True)
class MetricFact:
    metricId: str
    value: str
    appliesTo: str
    sourceBulletId: str
    experienceId: str
    sourceFactIds: list[str]


ProvenanceBullet = dict[str, Any]


CANONICAL_SKILL_CATEGORIES: tuple[str, ...] = (
    "Programming Languages",
    "AI and Machine Learning",
    "Backend and APIs",
    "Databases and Data",
    "Cloud and DevOps",
    "Testing and Quality",
    "Frontend",
    "Tools and Collaboration",
    "Domain Knowledge",
)

TRANSFERABLE_SKILL_GROUPS: dict[str, set[str]] = {
    "relational_database": {"postgresql", "mysql", "sql server", "t-sql", "sql"},
    "cloud": {"aws", "azure", "gcp"},
    "ai_assisted": {"prompt engineering", "ai-assisted development", "ai-assisted workflows", "chatgpt"},
    "healthcare_domain": {"healthcare", "healthcare products", "hipaa", "phi"},
    "backend": {"spring boot", "spring framework", "fastapi", "django", "flask", "node.js", "rest apis", "graphql"},
    "frontend": {"react", "next.js", "ionic", "javascript", "typescript"},
    "deployment": {"docker", "kubernetes", "terraform", "ci/cd", "github actions"},
}

_SKILL_TAXONOMY: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("python", "Python", ("Programming Languages",)),
    ("java", "Java", ("Programming Languages",)),
    ("javascript", "JavaScript", ("Programming Languages",)),
    ("typescript", "TypeScript", ("Programming Languages",)),
    ("c#", "C#", ("Programming Languages",)),
    ("c++", "C++", ("Programming Languages",)),
    ("golang", "Go", ("Programming Languages",)),
    ("ruby", "Ruby", ("Programming Languages",)),
    ("php", "PHP", ("Programming Languages",)),
    ("bash", "Bash", ("Programming Languages",)),
    ("powershell", "PowerShell", ("Programming Languages",)),
    ("open ai", "OpenAI API", ("AI and Machine Learning",)),
    ("openai api", "OpenAI API", ("AI and Machine Learning",)),
    ("azure openai", "Azure OpenAI", ("AI and Machine Learning", "Cloud and DevOps")),
    ("claude api", "Claude API", ("AI and Machine Learning",)),
    ("gemini", "Gemini", ("AI and Machine Learning",)),
    ("bedrock", "AWS Bedrock", ("AI and Machine Learning", "Cloud and DevOps")),
    ("rag", "RAG", ("AI and Machine Learning",)),
    ("llm", "LLM", ("AI and Machine Learning",)),
    ("llm api", "LLM API Integration", ("AI and Machine Learning", "Backend and APIs")),
    ("prompt engineering", "Prompt Engineering", ("AI and Machine Learning",)),
    ("prompt design", "Prompt Engineering", ("AI and Machine Learning",)),
    ("structured json", "Structured Outputs", ("AI and Machine Learning",)),
    ("structured output", "Structured Outputs", ("AI and Machine Learning",)),
    ("json schema", "JSON Schema", ("AI and Machine Learning", "Testing and Quality")),
    ("function calling", "Function Calling", ("AI and Machine Learning",)),
    ("tool calling", "Tool Calling", ("AI and Machine Learning",)),
    ("multi-block response", "Multi-Block Response Handling", ("AI and Machine Learning", "Backend and APIs")),
    ("multi-block responses", "Multi-Block Response Handling", ("AI and Machine Learning", "Backend and APIs")),
    ("pdf parsing", "PDF Parsing", ("Backend and APIs", "AI and Machine Learning")),
    ("pymupdf", "PyMuPDF", ("Backend and APIs", "AI and Machine Learning")),
    ("pdfplumber", "pdfplumber", ("Backend and APIs", "AI and Machine Learning")),
    ("camelot", "Camelot", ("Backend and APIs", "AI and Machine Learning")),
    ("ocr", "OCR", ("AI and Machine Learning", "Backend and APIs")),
    ("tesseract", "Tesseract", ("AI and Machine Learning", "Backend and APIs")),
    ("azure document intelligence", "Azure Document Intelligence", ("AI and Machine Learning", "Cloud and DevOps")),
    ("aws textract", "AWS Textract", ("AI and Machine Learning", "Cloud and DevOps")),
    ("google document ai", "Google Document AI", ("AI and Machine Learning", "Cloud and DevOps")),
    ("document classification", "Document Classification", ("AI and Machine Learning",)),
    ("information extraction", "Information Extraction", ("AI and Machine Learning",)),
    ("document processing", "Document Processing", ("Backend and APIs", "AI and Machine Learning")),
    ("unstructured document", "Document Processing", ("Backend and APIs", "AI and Machine Learning")),
    ("structured document", "Document Processing", ("Backend and APIs", "AI and Machine Learning")),
    ("guardrails", "LLM Guardrails", ("Testing and Quality", "AI and Machine Learning")),
    ("output validation", "LLM Output Validation", ("Testing and Quality", "AI and Machine Learning")),
    ("source grounding", "Source Grounding", ("AI and Machine Learning", "Testing and Quality")),
    ("hallucination", "Hallucination Handling", ("AI and Machine Learning", "Testing and Quality")),
    ("confidence scoring", "Confidence Scoring", ("AI and Machine Learning", "Testing and Quality")),
    ("human-in-the-loop", "Human-in-the-Loop Review", ("AI and Machine Learning", "Testing and Quality")),
    ("human review", "Human-in-the-Loop Review", ("AI and Machine Learning", "Testing and Quality")),
    ("prompt versioning", "Prompt Versioning", ("AI and Machine Learning", "Testing and Quality")),
    ("llm monitoring", "LLM Monitoring", ("Testing and Quality", "AI and Machine Learning")),
    ("llm evaluation", "LLM Evaluation", ("Testing and Quality", "AI and Machine Learning")),
    ("retry handling", "Retry Handling", ("Testing and Quality", "Backend and APIs")),
    ("fallback logic", "Fallback Logic", ("Testing and Quality", "Backend and APIs")),
    ("embeddings", "Embeddings", ("AI and Machine Learning",)),
    ("vector search", "Vector Search", ("AI and Machine Learning", "Databases and Data")),
    ("vector database", "Vector Databases", ("AI and Machine Learning", "Databases and Data")),
    ("pinecone", "Pinecone", ("AI and Machine Learning", "Databases and Data")),
    ("chroma", "Chroma", ("AI and Machine Learning", "Databases and Data")),
    ("pgvector", "pgvector", ("AI and Machine Learning", "Databases and Data")),
    ("weaviate", "Weaviate", ("AI and Machine Learning", "Databases and Data")),
    ("semantic search", "Semantic Search", ("AI and Machine Learning",)),
    ("langchain", "LangChain", ("AI and Machine Learning", "Backend and APIs")),
    ("langgraph", "LangGraph", ("AI and Machine Learning", "Backend and APIs")),
    ("crewai", "CrewAI", ("AI and Machine Learning", "Backend and APIs")),
    ("llamaindex", "LlamaIndex", ("AI and Machine Learning", "Backend and APIs")),
    ("semantic kernel", "Semantic Kernel", ("AI and Machine Learning", "Backend and APIs")),
    ("model context protocol", "Model Context Protocol (MCP)", ("AI and Machine Learning", "Backend and APIs")),
    ("mcp", "Model Context Protocol (MCP)", ("AI and Machine Learning", "Backend and APIs")),
    ("agentic workflow", "Agentic Workflows", ("AI and Machine Learning",)),
    ("orchestration", "AI Orchestration", ("AI and Machine Learning",)),
    ("state management", "Agent State Management", ("AI and Machine Learning",)),
    ("ai-assisted development", "AI-Assisted Development", ("AI and Machine Learning",)),
    ("ai-assisted workflows", "AI-Assisted Development", ("AI and Machine Learning",)),
    ("chatgpt", "AI-Assisted Development", ("AI and Machine Learning",)),
    ("fastapi", "FastAPI", ("Backend and APIs",)),
    ("django", "Django", ("Backend and APIs",)),
    ("flask", "Flask", ("Backend and APIs",)),
    ("spring boot", "Spring Boot", ("Backend and APIs",)),
    ("spring framework", "Spring Framework", ("Backend and APIs",)),
    ("spring", "Spring Framework", ("Backend and APIs",)),
    ("node.js", "Node.js", ("Backend and APIs",)),
    ("rest api", "REST APIs", ("Backend and APIs",)),
    ("rest apis", "REST APIs", ("Backend and APIs",)),
    ("restful api", "REST APIs", ("Backend and APIs",)),
    ("restful apis", "REST APIs", ("Backend and APIs",)),
    ("graphql", "GraphQL", ("Backend and APIs",)),
    ("postgre sql", "PostgreSQL", ("Databases and Data",)),
    ("postgres", "PostgreSQL", ("Databases and Data",)),
    ("postgresql", "PostgreSQL", ("Databases and Data",)),
    ("mysql", "MySQL", ("Databases and Data",)),
    ("mongodb", "MongoDB", ("Databases and Data",)),
    ("redis", "Redis", ("Databases and Data",)),
    ("sql server", "SQL Server", ("Databases and Data",)),
    ("microsoft sql server", "SQL Server", ("Databases and Data",)),
    ("t-sql", "T-SQL", ("Databases and Data",)),
    ("stored procedure", "Stored Procedures", ("Databases and Data",)),
    ("stored procedures", "Stored Procedures", ("Databases and Data",)),
    ("schema design", "Database Schema Design", ("Databases and Data",)),
    ("query tuning", "Query Tuning", ("Databases and Data", "Testing and Quality")),
    ("query optimization", "Query Optimization", ("Databases and Data", "Testing and Quality")),
    ("indexing", "Database Indexing", ("Databases and Data",)),
    ("amazon web services", "AWS", ("Cloud and DevOps",)),
    ("aws", "AWS", ("Cloud and DevOps",)),
    ("microsoft azure", "Azure", ("Cloud and DevOps",)),
    ("azure", "Azure", ("Cloud and DevOps",)),
    ("gcp", "GCP", ("Cloud and DevOps",)),
    ("docker", "Docker", ("Cloud and DevOps",)),
    ("kubernetes", "Kubernetes", ("Cloud and DevOps",)),
    ("terraform", "Terraform", ("Cloud and DevOps",)),
    ("continuous integration / continuous deployment", "CI/CD", ("Cloud and DevOps",)),
    ("continuous integration", "CI/CD", ("Cloud and DevOps",)),
    ("continuous deployment", "CI/CD", ("Cloud and DevOps",)),
    ("ci/cd", "CI/CD", ("Cloud and DevOps",)),
    ("github actions", "GitHub Actions", ("Cloud and DevOps", "Tools and Collaboration")),
    ("monitoring", "Production Monitoring", ("Cloud and DevOps", "Testing and Quality")),
    ("audit logging", "Audit Logging", ("Testing and Quality", "Domain Knowledge")),
    ("unit testing", "Unit Testing", ("Testing and Quality",)),
    ("integration testing", "Integration Testing", ("Testing and Quality",)),
    ("automated testing", "Automated Testing", ("Testing and Quality",)),
    ("code review", "Code Review", ("Testing and Quality",)),
    ("data validation", "Data Validation", ("Testing and Quality",)),
    ("react", "React", ("Frontend",)),
    ("next.js", "Next.js", ("Frontend",)),
    ("nextjs", "Next.js", ("Frontend",)),
    ("ionic", "Ionic", ("Frontend",)),
    ("vue", "Vue", ("Frontend",)),
    ("angular", "Angular", ("Frontend",)),
    ("shopify", "Shopify", ("Domain Knowledge", "Frontend")),
    ("hipaa", "HIPAA", ("Domain Knowledge",)),
    ("phi", "PHI", ("Domain Knowledge",)),
    ("healthcare", "Healthcare", ("Domain Knowledge",)),
    ("healthcare products", "Healthcare Products", ("Domain Knowledge",)),
    ("kafka", "Kafka", ("Databases and Data",)),
    ("fintech", "Fintech", ("Domain Knowledge",)),
    ("logistics", "Logistics", ("Domain Knowledge",)),
    ("ecommerce", "eCommerce", ("Domain Knowledge",)),
    ("e-commerce", "eCommerce", ("Domain Knowledge",)),
    ("git", "Git", ("Tools and Collaboration",)),
    ("github", "GitHub", ("Tools and Collaboration",)),
    ("jira", "Jira", ("Tools and Collaboration",)),
)

_VAGUE_GENERATED_RE = re.compile(
    r"\b(?:robust developments?|advanced solutions?|enhanced workflows?|role-relevant engineering work|"
    r"innovative solutions?|cutting-edge|synerg|leveraged)\b",
    re.I,
)

_MALFORMED_TEXT_RE = re.compile(r"(?:Ã|Â|â€|�){2,}|[^\x09\x0a\x0d\x20-\x7e]{5,}")

_METRIC_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|x|k\+|m\+|users?|requests?|documents?|transactions?)?(?=\b|[^A-Za-z0-9])",
    re.I,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_generated_skills(value: Any) -> str:
    """Convert model skill strings, arrays, or objects into clean `Category: items` lines."""
    if value is None:
        return ""
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ""
        if raw[:1] in "[{" and raw[-1:] in "]}":
            parsed: Any = None
            try:
                import json
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                try:
                    parsed = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    parsed = None
            if parsed is not None and not isinstance(parsed, str):
                return normalize_generated_skills(parsed)
        return "\n".join(
            line.strip().strip("'\"")
            for line in raw.splitlines()
            if line.strip()
        )
    if isinstance(value, dict):
        lines: list[str] = []
        for category, skills in value.items():
            if isinstance(skills, (list, tuple, set)):
                items = ", ".join(
                    _clean(str(item)).strip("'\"")
                    for item in skills
                    if _clean(str(item))
                )
            else:
                items = _clean(str(skills)).strip("'\"")
            if items:
                lines.append(f"{_clean(str(category)).strip(':')}: {items}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple, set)):
        lines: list[str] = []
        for item in value:
            lines.extend(
                line for line in normalize_generated_skills(item).splitlines() if line.strip()
            )
        return "\n".join(lines)
    return _clean(str(value))


def is_experience_section_placeholder(role: Any) -> bool:
    """Detect a résumé section heading that the DOCX parser misclassified as a job role."""
    headings = {
        "experience",
        "professional experience",
        "work experience",
        "employment experience",
        "employment history",
        "work history",
        "career experience",
    }

    def normalized(value: Any) -> str:
        return re.sub(r"[^a-z]+", " ", str(value or "").lower()).strip()

    company = normalized(getattr(role, "company", ""))
    title = normalized(getattr(role, "title", ""))
    period = _clean(str(getattr(role, "period", "")))
    location = _clean(str(getattr(role, "location", "")))
    if company in headings and title in headings:
        return True
    if not period and not location and company in headings and (not title or title in headings):
        return True
    if not period and not location and title in headings and (not company or company in headings):
        return True
    return False


def _has_malformed_text(text: str) -> bool:
    clean = _clean(text)
    if not clean:
        return True
    alpha_count = len(re.findall(r"[A-Za-z]", clean))
    if alpha_count < 4 and len(clean) > 12:
        return True
    return bool(_MALFORMED_TEXT_RE.search(clean))


def extract_named_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in _TECH_OR_DOMAIN_RE.finditer(text or ""):
        term = _clean(match.group(0))
        if term and term.lower() not in {t.lower() for t in terms}:
            terms.append(term)
    return terms


def _primary_action(text: str) -> str:
    match = re.search(r"\b(improved|reduced|increased|built|developed|designed|implemented|optimized|led|created|integrated|deployed|tested)\b", text, re.I)
    return match.group(1).lower() if match else ""


def _metric_subject(text: str, metric: str) -> str:
    before = text.split(metric, 1)[0]
    after = text.split(metric, 1)[1] if metric in text else ""
    phrase = before[-90:] + " " + after[:70]
    phrase = re.sub(r"\b(?:by|to|from|using|with|through|via|and|the|a|an)\b", " ", phrase, flags=re.I)
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9+-]*", phrase) if len(w) > 2]
    stop = {"improved", "reduced", "increased", "optimized", "built", "developed", "using", "with"}
    subject_words = [w for w in words if w.lower() not in stop][:5]
    return " ".join(subject_words).lower()


def extract_atomic_facts_from_bullet(
    text: str,
    source_bullet_id: str,
    *,
    experience_id: str = "",
) -> tuple[list[AtomicFact], list[MetricFact]]:
    clean = _clean(text)
    action = _primary_action(clean)
    technologies = extract_named_terms(clean)
    metrics = [m.group(0).strip() for m in _METRIC_RE.finditer(clean)]
    atomic: list[AtomicFact] = []
    metric_facts: list[MetricFact] = []
    if metrics:
        for i, metric in enumerate(metrics, start=1):
            fact_id = f"{source_bullet_id}_fact_{i:03d}"
            subject = _metric_subject(clean, metric)
            atomic.append(
                AtomicFact(
                    factId=fact_id,
                    subject=subject,
                    action=action,
                    value=metric,
                    technology=technologies[0] if technologies else None,
                    sourceBulletId=source_bullet_id,
                    experienceId=experience_id,
                )
            )
            metric_facts.append(
                MetricFact(
                    metricId=f"{source_bullet_id}_metric_{i:03d}",
                    value=metric,
                    appliesTo=subject,
                    sourceBulletId=source_bullet_id,
                    experienceId=experience_id,
                    sourceFactIds=[fact_id],
                )
            )
    else:
        atomic.append(
            AtomicFact(
                factId=f"{source_bullet_id}_fact_001",
                subject=clean[:80].lower(),
                action=action,
                value="",
                technology=technologies[0] if technologies else None,
                sourceBulletId=source_bullet_id,
                experienceId=experience_id,
            )
        )
    return atomic, metric_facts


def build_verified_candidate_facts(
    *,
    contact: str,
    summary: str,
    skills: str,
    roles: list[Any],
    education: str,
    other: str,
) -> list[SourceFact]:
    facts: list[SourceFact] = []
    for label, text in (
        ("contact", contact),
        ("summary", summary),
        ("skills", skills),
        ("education", education),
        ("other", other),
    ):
        clean = _clean(text)
        if clean:
            facts.append(SourceFact(f"{label}_001", clean[:1200], "candidate_resume"))
    for role_i, role in enumerate(roles, start=1):
        experience_id = f"exp_{role_i:03d}"
        company = _clean(getattr(role, "company", "") or getattr(role, "header", ""))
        title = _clean(getattr(role, "title", ""))
        header = _clean(
            " | ".join(
                part
                for part in (
                    title,
                    company,
                    getattr(role, "location", ""),
                    getattr(role, "period", ""),
                )
                if part
            )
        )
        if header:
            facts.append(
                SourceFact(
                    f"{experience_id}_header",
                    header,
                    "candidate_resume",
                    company,
                    experience_id=experience_id,
                    title=title,
                    source_order=0,
                )
            )
        for bullet_i, bullet in enumerate(getattr(role, "bullets", []) or [], start=1):
            clean = _clean(str(bullet))
            if clean:
                facts.append(
                    SourceFact(
                        f"{experience_id}_bullet_{bullet_i:03d}",
                        clean,
                        "candidate_resume",
                        company,
                        experience_id=experience_id,
                        title=title,
                        source_order=bullet_i,
                    )
                )
    return facts


def parse_verified_answer_facts(raw_answers: str | list[dict[str, Any]] | None) -> list[SourceFact]:
    if not raw_answers:
        return []
    import json

    if isinstance(raw_answers, str):
        try:
            parsed = json.loads(raw_answers)
        except json.JSONDecodeError:
            parsed = [{"answer": raw_answers}]
    else:
        parsed = raw_answers
    if not isinstance(parsed, list):
        parsed = [parsed]
    facts: list[SourceFact] = []
    for i, item in enumerate(parsed, start=1):
        if isinstance(item, dict):
            question = _clean(str(item.get("question", "")))
            answer = _clean(str(item.get("answer", "") or item.get("text", "")))
        else:
            question = ""
            answer = _clean(str(item))
        if not answer or answer.lower() in {"no", "n/a", "none", "not sure"}:
            continue
        is_bare_confirmation = answer.lower().startswith("candidate confirmed this qualification")
        is_skill_inventory = question.lower().startswith("which missing skills can you personally confirm")
        # Detailed answers are candidate evidence in their own right. Prefixing the
        # Yes/No question polluted semantic and metric validation with unrelated text.
        text = f"{question} {answer}".strip() if is_bare_confirmation or is_skill_inventory else answer
        facts.append(SourceFact(f"user_verified_{i:03d}", text, "candidate_verified_answer", verified=True))
    return facts


def build_candidate_knowledge_base(
    *,
    contact: str,
    summary: str,
    skills: str,
    roles: list[Any],
    education: str,
    other: str,
) -> dict[str, Any]:
    """Structured extraction only: no rewriting, inference, or years calculation."""
    candidate = {"contact": _clean(contact), "summary": _clean(summary)}
    experience: list[dict[str, Any]] = []
    for role_i, role in enumerate(roles, start=1):
        experience_id = f"exp_{role_i:03d}"
        bullets = [_clean(str(b)) for b in getattr(role, "bullets", []) or [] if _clean(str(b))]
        combined = " ".join([getattr(role, "header", ""), *bullets])
        metrics = [m.group(0) for m in re.finditer(r"\b\d+(?:\.\d+)?\s*(?:%|percent|x|k\+|m\+)?\b", combined, re.I)]
        bullet_objects: list[dict[str, Any]] = []
        role_atomic: list[dict[str, Any]] = []
        role_metrics: list[dict[str, Any]] = []
        for bullet_i, bullet in enumerate(bullets, start=1):
            bullet_id = f"{experience_id}_bullet_{bullet_i:03d}"
            atomic_facts, metric_facts = extract_atomic_facts_from_bullet(
                bullet,
                bullet_id,
                experience_id=experience_id,
            )
            role_atomic.extend(fact.__dict__ for fact in atomic_facts)
            role_metrics.extend(metric.__dict__ for metric in metric_facts)
            bullet_objects.append(
                {
                    "bulletId": bullet_id,
                    "id": bullet_id,
                    "experienceId": experience_id,
                    "company": _clean(getattr(role, "company", "")),
                    "title": _clean(getattr(role, "title", "")),
                    "sourceText": bullet,
                    "sourceOrder": bullet_i,
                    "text": bullet,
                    "technologies": extract_named_terms(bullet),
                    "metrics": [metric.__dict__ for metric in metric_facts],
                    "atomicFacts": [fact.__dict__ for fact in atomic_facts],
                    "responsibilities": [bullet],
                    "achievements": [bullet],
                }
            )
        experience.append(
            {
                "id": experience_id,
                "experienceId": experience_id,
                "company": _clean(getattr(role, "company", "")),
                "title": _clean(getattr(role, "title", "")),
                "location": _clean(getattr(role, "location", "")),
                "start": "",
                "end": _clean(getattr(role, "period", "")),
                "sourceText": _clean(getattr(role, "header", "")),
                "technologies": extract_named_terms(combined),
                "bullets": bullet_objects,
                "atomicFacts": role_atomic,
                "metricFacts": role_metrics,
                "responsibilities": bullets,
                "achievements": bullets,
                "metrics": list(dict.fromkeys(metrics)),
                "industry": "",
                "warnings": ["malformed_or_ambiguous_text"] if any(_has_malformed_text(b) for b in bullets) else [],
            }
        )
    return {
        "candidate": candidate,
        "experience": experience,
        "projects": [],
        "skills": [
            {
                "name": skill,
                "sourceIds": ["skills_001"],
                "evidenceType": "self_reported",
            }
            for skill in extract_named_terms(skills)
        ],
        "education": [_clean(line) for line in (education or "").splitlines() if _clean(line)],
        "certifications": [],
        "languages": [],
        "achievements": [_clean(line) for line in (other or "").splitlines() if _clean(line)],
    }


def build_canonical_skills_section(
    *,
    source_skills: str,
    job_description: str,
    facts: list[SourceFact],
    final_experience: str,
    max_skills: int = 30,
) -> tuple[str, list[dict[str, Any]]]:
    inventory = build_candidate_skill_inventory(
        source_skills=source_skills,
        facts=facts,
        final_experience=final_experience,
        job_description=job_description,
    )
    selected = select_candidate_skills(inventory, max_skills=max_skills)
    buckets: dict[str, list[str]] = {category: [] for category in CANONICAL_SKILL_CATEGORIES}
    for skill in selected:
        category = str(skill["category"])
        if category in buckets and len(buckets[category]) < int(os.getenv("RESUME_MAX_SKILLS_PER_CATEGORY", "16")):
            buckets[category].append(str(skill["canonicalName"]))
    ordered_categories = _ordered_skill_categories(job_description, selected)
    lines = [
        f"{category}: {', '.join(buckets[category])}"
        for category in ordered_categories
        if buckets.get(category)
    ][: int(os.getenv("RESUME_MAX_SKILL_CATEGORIES", "10"))]
    audit: list[dict[str, Any]] = []
    for idx, skill in enumerate(selected, start=1):
        audit.append(
            {
                "claimId": f"skill_{idx:03d}",
                "skillId": skill["skillId"],
                "finalText": skill["canonicalName"],
                "canonicalSkill": skill["canonicalName"],
                "skill": skill["canonicalName"],
                "category": skill["category"],
                "sourceIds": skill["sourceIds"],
                "sourceTypes": skill["sourceTypes"],
                "sourceType": "candidate_verified_answer"
                if "candidate_verified_answer" in skill["sourceTypes"]
                else skill["sourceTypes"][0],
                "evidenceType": skill["evidenceType"],
                "evidenceStrength": skill["evidenceStrength"],
                "jobRelevance": skill["jobRelevanceScore"],
                "jobRelevanceScore": skill["jobRelevanceScore"],
                "transferabilityScore": skill["transferabilityScore"],
                "recencyScore": skill["recencyScore"],
                "frequencyScore": skill["frequencyScore"],
                "inclusionScore": skill["inclusionScore"],
                "selectionLayer": skill["selectionLayer"],
                "matchType": skill["matchType"],
                "matchedRequirements": skill["matchedRequirements"],
                "requirementsSupported": skill["matchedRequirements"],
                "transformationType": "unchanged",
                "confidence": skill["evidenceStrength"],
                "include": True,
            }
        )
    return "\n".join(lines), audit


def build_candidate_skill_inventory(
    *,
    source_skills: str,
    facts: list[SourceFact],
    final_experience: str,
    job_description: str,
) -> list[dict[str, Any]]:
    """Build candidate-owned skill inventory first; JD terms only score relevance."""
    jd_blob = (job_description or "").lower()
    candidate_sources = [fact for fact in facts if fact.source in _candidate_skill_sources()]
    max_exp = max(
        [int(match.group(1)) for fact in candidate_sources for match in [re.match(r"exp_(\d{3})_", fact.fact_id)] if match]
        or [1]
    )
    by_canonical: dict[str, dict[str, Any]] = {}
    for alias, canonical, categories in _SKILL_TAXONOMY:
        if _is_vague_skill(canonical):
            continue
        matched_sources = [
            fact
            for fact in candidate_sources
            if _alias_in_text(alias, fact.text) or _alias_in_text(canonical, fact.text)
        ]
        if not matched_sources:
            continue
        if not _high_risk_skill_allowed(canonical, alias, matched_sources):
            continue
        existing = by_canonical.setdefault(
            canonical,
            {
                "rawNames": set(),
                "canonicalName": canonical,
                "category": categories[0],
                "sourceIds": [],
                "sourceTypes": [],
                "evidenceTypes": set(),
                "sourceOrders": [],
                "aliases": set(),
            },
        )
        existing["rawNames"].add(alias)
        existing["aliases"].add(alias)
        for fact in matched_sources:
            if fact.fact_id not in existing["sourceIds"]:
                existing["sourceIds"].append(fact.fact_id)
                existing["sourceTypes"].append(fact.source)
                existing["evidenceTypes"].add(_skill_evidence_type(fact))
                if fact.fact_id.startswith("exp_"):
                    match = re.match(r"exp_(\d{3})_", fact.fact_id)
                    if match:
                        existing["sourceOrders"].append(int(match.group(1)))
    inventory: list[dict[str, Any]] = []
    for idx, item in enumerate(by_canonical.values(), start=1):
        evidence_strength = _skill_evidence_strength(item["evidenceTypes"], item["sourceIds"])
        recency = _skill_recency_score(item["sourceOrders"], max_exp)
        frequency = min(1.0, len(item["sourceIds"]) / 4)
        relevance, match_type, matched_requirements = _skill_job_match(
            str(item["canonicalName"]),
            set(item["aliases"]),
            jd_blob,
        )
        transferability = 0.9 if match_type == "transferable" else 1.0 if match_type == "exact" else 0.55
        inclusion = round(
            evidence_strength * 0.35
            + relevance * 0.30
            + transferability * 0.15
            + recency * 0.10
            + frequency * 0.10,
            4,
        )
        evidence_type = _dominant_evidence_type(item["evidenceTypes"])
        inventory.append(
            {
                "skillId": f"skill_{idx:03d}",
                "rawName": sorted(item["rawNames"])[0],
                "canonicalName": item["canonicalName"],
                "category": item["category"],
                "sourceIds": item["sourceIds"][:8],
                "sourceTypes": list(dict.fromkeys(item["sourceTypes"])),
                "evidenceType": evidence_type,
                "evidenceStrength": evidence_strength,
                "yearsEvidence": None,
                "recencyScore": recency,
                "frequencyScore": frequency,
                "jobRelevanceScore": relevance,
                "transferabilityScore": transferability,
                "inclusionScore": inclusion,
                "selectionLayer": _selection_layer(relevance, match_type, evidence_strength),
                "matchType": match_type,
                "matchedRequirements": matched_requirements,
                "include": True,
            }
        )
    return inventory


def select_candidate_skills(inventory: list[dict[str, Any]], *, max_skills: int = 24) -> list[dict[str, Any]]:
    min_skills = int(os.getenv("RESUME_MIN_SKILLS", "10"))
    max_skills = int(os.getenv("RESUME_MAX_SKILLS", str(max_skills)))
    max_skills = max(1, min(max_skills, 30))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    layers = ("core", "transferable", "supporting")
    for layer in layers:
        candidates = [
            skill
            for skill in inventory
            if skill["selectionLayer"] == layer
            and str(skill["canonicalName"]).lower() not in seen
            and _candidate_owned_skill(skill)
        ]
        candidates.sort(key=lambda skill: (-float(skill["inclusionScore"]), -float(skill["evidenceStrength"]), str(skill["canonicalName"])))
        layer_limit = max(0, max_skills - len(selected))
        for skill in candidates[:layer_limit]:
            if len(selected) >= max_skills:
                break
            selected.append(skill)
            seen.add(str(skill["canonicalName"]).lower())
    if len(selected) < min_skills:
        remaining = [
            skill
            for skill in inventory
            if str(skill["canonicalName"]).lower() not in seen
            and _candidate_owned_skill(skill)
            and not _is_vague_skill(str(skill["canonicalName"]))
        ]
        remaining.sort(key=lambda skill: (-float(skill["inclusionScore"]), -float(skill["evidenceStrength"]), str(skill["canonicalName"])))
        for skill in remaining:
            if len(selected) >= min(min_skills, max_skills):
                break
            selected.append(skill)
            seen.add(str(skill["canonicalName"]).lower())
    selected.sort(
        key=lambda skill: (
            _category_sort_index(str(skill["category"])),
            {"core": 0, "transferable": 1, "supporting": 2}.get(str(skill["selectionLayer"]), 3),
            -float(skill["inclusionScore"]),
            str(skill["canonicalName"]),
        )
    )
    return selected[:max_skills]


def _candidate_skill_sources() -> set[str]:
    return {"candidate_resume", "candidate_verified_answer", "project", "education", "certification", "self_reported"}


def _candidate_owned_skill(skill: dict[str, Any]) -> bool:
    return bool(set(skill.get("sourceTypes", [])) & _candidate_skill_sources()) and bool(skill.get("sourceIds"))


def _alias_in_text(alias: str, text: str) -> bool:
    alias = (alias or "").strip().lower()
    if not alias:
        return False
    return bool(re.search(rf"(?<![a-z0-9+#]){re.escape(alias)}(?![a-z0-9+#])", (text or "").lower()))


def _is_vague_skill(skill: str) -> bool:
    return skill.strip().lower() in {
        "ai",
        "cloud",
        "devops",
        "testing",
        "backend development",
        "programming",
        "data",
        "collaboration",
        "llm",
    }


def _high_risk_skill_allowed(canonical: str, alias: str, sources: list[SourceFact]) -> bool:
    corpus = "\n".join(fact.text for fact in sources).lower()
    canonical_l = canonical.lower()
    if canonical in {"SQL Server", "T-SQL"}:
        return _alias_in_text("sql server", corpus) or _alias_in_text("t-sql", corpus) or _alias_in_text("microsoft sql server", corpus)
    if canonical == "Azure":
        return _alias_in_text("azure", corpus) or _alias_in_text("microsoft azure", corpus)
    if canonical in {"OpenAI API", "Claude API", "AWS Bedrock", "RAG"}:
        if canonical == "OpenAI API":
            return bool(re.search(r"\bopenai\s+api\b", corpus))
        if canonical == "Claude API":
            return bool(re.search(r"\bclaude\s+api\b", corpus))
        if canonical == "AWS Bedrock":
            return bool(re.search(r"\b(?:aws\s+)?bedrock\b", corpus))
        return bool(re.search(r"\brag\b|retrieval-augmented generation", corpus))
    if canonical in {"HIPAA", "PHI"}:
        return _alias_in_text(canonical, corpus)
    return True


def _skill_evidence_type(fact: SourceFact) -> str:
    if fact.fact_id.startswith("exp_"):
        return "professional"
    if fact.source == "candidate_verified_answer":
        return "verified_answer"
    if fact.source in {"project", "education", "certification"}:
        return fact.source
    return "self_reported"


def _dominant_evidence_type(types: set[str]) -> str:
    for item in ("professional", "project", "verified_answer", "certification", "education", "self_reported"):
        if item in types:
            return item
    return "self_reported"


def _skill_evidence_strength(types: set[str], source_ids: list[str]) -> float:
    if "professional" in types:
        return 0.95 if len(source_ids) >= 2 else 0.88
    if "project" in types or "verified_answer" in types:
        return 0.82
    if "certification" in types or "education" in types:
        return 0.72
    return 0.55 if len(source_ids) <= 1 else 0.65


def _skill_recency_score(source_orders: list[int], max_exp: int) -> float:
    if not source_orders:
        return 0.45
    newest = max(source_orders)
    if max_exp <= 1:
        return 0.8
    return round(0.45 + 0.5 * ((newest - 1) / max(1, max_exp - 1)), 3)


def _skill_job_match(canonical: str, aliases: set[str], jd_blob: str) -> tuple[float, str, list[str]]:
    canonical_l = canonical.lower()
    exact_terms = {canonical_l, *{alias.lower() for alias in aliases}}
    if any(_alias_in_text(term, jd_blob) for term in exact_terms):
        return 1.0, "exact", [canonical]
    if canonical == "OpenAI API" and re.search(r"\bopenai\b", jd_blob):
        return 1.0, "exact", ["OpenAI API"]
    if canonical == "Claude API" and re.search(r"\bclaude\b", jd_blob):
        return 1.0, "exact", ["Claude API"]
    if canonical == "AWS Bedrock" and re.search(r"\bbedrock\b", jd_blob):
        return 1.0, "exact", ["AWS Bedrock"]
    if canonical == "AI-Assisted Development" and re.search(r"\b(openai|claude|gemini|bedrock|llm|rag|ai)\b", jd_blob):
        return 0.74, "transferable", ["AI/LLM workflow"]
    for group in TRANSFERABLE_SKILL_GROUPS.values():
        if canonical_l in group or any(alias in group for alias in aliases):
            requested = [term for term in group if _alias_in_text(term, jd_blob)]
            if requested:
                if canonical in {"SQL Server", "T-SQL", "Azure", "OpenAI API", "Claude API", "AWS Bedrock", "RAG", "HIPAA", "PHI"}:
                    return 0.0, "none", []
                return 0.74, "transferable", sorted(requested)
    if _category_relevant_to_job(canonical, jd_blob):
        return 0.58, "supporting", []
    if canonical in {"Java", "JavaScript", "TypeScript", "Spring Boot", "Spring Framework", "React", "Next.js", "Ionic", "Docker", "Kubernetes", "Terraform", "Kafka", "Code Review", "Automated Testing", "Integration Testing"}:
        return 0.42, "supporting", []
    return 0.25, "supporting", []


def _category_relevant_to_job(canonical: str, jd_blob: str) -> bool:
    backend_terms = r"backend|api|service|microservice|server|software engineer|production"
    frontend_terms = r"frontend|react|ui|web"
    testing_terms = r"test|quality|validation|reliability"
    cloud_terms = r"cloud|deploy|infrastructure|devops|ci/cd"
    data_terms = r"database|sql|data|pipeline"
    category = next((cats[0] for alias, name, cats in _SKILL_TAXONOMY if name == canonical), "")
    if category == "Backend and APIs":
        return bool(re.search(backend_terms, jd_blob))
    if category == "Frontend":
        return bool(re.search(frontend_terms, jd_blob))
    if category == "Testing and Quality":
        return bool(re.search(testing_terms, jd_blob))
    if category == "Cloud and DevOps":
        return bool(re.search(cloud_terms, jd_blob))
    if category == "Databases and Data":
        return bool(re.search(data_terms, jd_blob))
    return False


def _selection_layer(relevance: float, match_type: str, evidence_strength: float) -> str:
    if match_type == "exact" and relevance >= 0.9:
        return "core"
    if match_type == "transferable":
        return "transferable"
    if evidence_strength >= 0.8 and relevance >= 0.55:
        return "core"
    return "supporting"


def _category_sort_index(category: str) -> int:
    try:
        return CANONICAL_SKILL_CATEGORIES.index(category)
    except ValueError:
        return 99


def _ordered_skill_categories(job_description: str, selected: list[dict[str, Any]]) -> list[str]:
    jd = (job_description or "").lower()
    order = list(CANONICAL_SKILL_CATEGORIES)
    if re.search(r"\b(frontend|react|ui|ux)\b", jd):
        order = [
            "Programming Languages",
            "Frontend",
            "Backend and APIs",
            "Testing and Quality",
            "Cloud and DevOps",
            "Databases and Data",
            "Tools and Collaboration",
            "AI and Machine Learning",
            "Domain Knowledge",
        ]
    elif re.search(r"\b(ai|llm|machine learning|rag|prompt)\b", jd):
        order = [
            "Programming Languages",
            "AI and Machine Learning",
            "Backend and APIs",
            "Databases and Data",
            "Cloud and DevOps",
            "Testing and Quality",
            "Tools and Collaboration",
            "Frontend",
            "Domain Knowledge",
        ]
    present = {str(skill["category"]) for skill in selected}
    return [category for category in order if category in present]


def _skill_job_relevance(alias: str, canonical: str, jd_blob: str) -> int:
    alias_l = alias.lower()
    canonical_l = canonical.lower()
    if alias_l in jd_blob or canonical_l in jd_blob:
        return 100
    for group_name, group in TRANSFERABLE_SKILL_GROUPS.items():
        if alias_l in group and any(term in jd_blob for term in group):
            if canonical in {"SQL Server", "T-SQL", "Azure", "OpenAI API", "Claude API", "AWS Bedrock", "RAG", "HIPAA", "PHI"}:
                return 0
            return 62
    if canonical in {"Python", "Java", "Spring Boot", "REST APIs", "PostgreSQL", "AWS", "CI/CD", "Testing", "Automated Testing", "React", "Kafka"}:
        return 45
    return 0


def analyze_job_description(job_description: str) -> dict[str, list[dict[str, str | int]]]:
    jd = job_description or ""
    terms = extract_named_terms(jd)
    required: list[dict[str, str | int]] = []
    preferred: list[dict[str, str | int]] = []
    for idx, term in enumerate(terms[:24]):
        window_re = re.compile(rf".{{0,80}}\b{re.escape(term)}\b.{{0,80}}", re.I)
        window = " ".join(m.group(0) for m in window_re.finditer(jd))
        is_required = bool(re.search(r"\b(required|must|required qualifications?|minimum|need|responsibilit)", window, re.I))
        priority = "required" if is_required or idx < 8 else "preferred"
        weight = max(35, 100 - idx * 4) if priority == "required" else max(20, 70 - idx * 3)
        item = {
            "id": f"req_{idx + 1:03d}",
            "name": term,
            "skill": term,
            "category": _requirement_category(term),
            "priority": priority,
            "weight": weight,
            "importance": max(4, 10 - idx // 3),
            "evidenceExpected": _evidence_expected_for_term(term),
            "evidence_expected": _evidence_expected_for_term(term),
            "minimumDuration": None,
        }
        if priority == "required":
            required.append(item)
        else:
            preferred.append(item)
    responsibilities = [
        _clean(line)
        for line in re.split(r"[\n•*-]+", jd)
        if 40 <= len(_clean(line)) <= 220 and re.search(r"\b(build|design|develop|manage|own|implement|support|deploy|optimi[sz]e|validate)\b", line, re.I)
    ][:10]
    experience_requirements: list[dict[str, Any]] = []
    for i, match in enumerate(
        re.finditer(
            r"\b(?P<years>\d{1,2})\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?P<area>[^.;\n]{0,90}?)(?=\s+(?:experience|working|building|developing|designing)\b|[.;\n]|$)",
            jd,
            re.I,
        )
    ):
        area = _clean(match.group("area")).strip(" ,-:") or "relevant professional"
        experience_requirements.append(
            {
                "id": f"experience_{i + 1:03d}",
                "years": int(match.group("years")),
                "area": area,
                "text": _clean(match.group(0)),
                "priority": "required" if re.search(r"\b(required|must|minimum|at least)\b", match.group(0), re.I) else "preferred",
                "weight": 95,
            }
        )
    education_requirements = [
        {
            "id": f"education_{i + 1:03d}",
            "text": _clean(match.group(0)),
            "priority": "required" if re.search(r"\b(required|must|minimum)\b", match.group(0), re.I) else "preferred",
            "weight": 80,
        }
        for i, match in enumerate(
            re.finditer(
                r"(?:bachelor(?:'s)?|master(?:'s)?|ph\.?d\.?|degree)\s+(?:degree\s+)?(?:in\s+)?[^.;\n]{0,100}",
                jd,
                re.I,
            )
        )
    ][:5]
    soft_patterns = (
        ("Communication", r"\bcommunicat(?:e|es|ed|ing|ion|ions)\b"),
        ("Leadership", r"\b(?:leadership|lead|leads|leading)\b"),
        ("Collaboration", r"\b(?:collaborat\w*|teamwork|cross-functional)\b"),
        ("Stakeholder Management", r"\bstakeholders?\b"),
        ("Problem Solving", r"\bproblem[ -]solv\w*\b"),
        ("Ownership", r"\b(?:ownership|own|owns|owned|accountability)\b"),
        ("Agile", r"\bagile\b"),
    )
    soft_names = [name for name, pattern in soft_patterns if re.search(pattern, jd, re.I)]
    location_requirements = [
        {"id": f"elig_location_{i + 1:03d}", "text": _clean(m.group(0)), "priority": "eligibility", "weight": 100}
        for i, m in enumerate(re.finditer(r"(?:must be|based in|located in|hybrid in|onsite in|remote in)[^.\n]{0,80}", jd, re.I))
    ]
    authorization_requirements = [
        {"id": f"elig_auth_{i + 1:03d}", "text": _clean(m.group(0)), "priority": "eligibility", "weight": 100}
        for i, m in enumerate(re.finditer(r"(?:work authorization|authorized to work|visa sponsorship|citizenship|clearance)[^.\n]{0,100}", jd, re.I))
    ]
    title_match = re.search(r"\b(?:title|role)\s*:\s*([^\n]+)", jd, re.I)
    return {
        "jobTitle": _clean(title_match.group(1)) if title_match else "",
        "required": required[:14],
        "requiredQualifications": required[:14],
        "preferred": preferred[:10],
        "preferredQualifications": preferred[:10],
        "responsibilities": [{"text": r, "importance": 7} for r in responsibilities],
        "experienceRequirements": experience_requirements[:8],
        "educationRequirements": education_requirements,
        "domain_terms": [{"skill": t, "importance": 6, "evidence_expected": "explicit domain evidence"} for t in terms if re.search(r"healthcare|HIPAA|PHI|financial|regulated", t, re.I)],
        "technicalSkills": [{"name": t} for t in terms],
        "domainKnowledge": [{"name": t} for t in terms if re.search(r"healthcare|HIPAA|PHI|financial|regulated", t, re.I)],
        "softSkills": [{"name": name, "importance": 5} for name in soft_names[:10]],
        "locationRequirements": location_requirements,
        "workAuthorizationRequirements": authorization_requirements,
        "applicationQuestions": [],
        "atsKeywords": terms,
    }


def _requirement_category(term: str) -> str:
    lower = term.lower()
    if lower in {"hipaa", "phi", "healthcare", "financial", "regulated data"}:
        return "domain"
    if lower in {"openai", "claude", "gemini", "bedrock", "llm", "rag", "langchain"}:
        return "ai"
    if lower in {"aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ci/cd"}:
        return "cloud_devops"
    if lower in {"postgresql", "mysql", "mongodb", "sql server", "t-sql", "sql"}:
        return "data"
    return "technical"


def _evidence_expected_for_term(term: str) -> str:
    lower = term.lower()
    if lower in {"sql", "sql server", "t-sql", "postgresql", "mysql"}:
        return "database work in skills, projects, or experience"
    if lower in {"openai", "claude", "gemini", "bedrock", "llm", "rag", "langchain"}:
        return "verified AI/LLM project or production usage"
    if "pdf" in lower or "ocr" in lower:
        return "document parsing, PDF, OCR, or extraction work"
    if lower in {"aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ci/cd"}:
        return "deployment, infrastructure, or delivery workflow evidence"
    return "resume fact showing practical use"


def create_evidence_map(job_analysis: dict[str, list[dict[str, str | int]]], facts: list[SourceFact]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    fact_texts = [(fact, fact.text.lower()) for fact in facts]
    for item in [*job_analysis.get("required", []), *job_analysis.get("preferred", []), *job_analysis.get("domain_terms", [])]:
        requirement = str(item.get("skill", "")).strip()
        if not requirement:
            continue
        req_l = requirement.lower()
        exact_supporting = [
            {
                "fact_id": fact.fact_id,
                "company": fact.company,
                "claim": fact.text[:240],
                "confidence": 0.91 if fact.source == "candidate_resume" and fact.fact_id.startswith("exp_") else 0.72,
            }
            for fact, text in fact_texts
            if req_l in text
        ][:6]
        practical_required = bool(
            re.search(
                r"\b(openai|claude|gemini|bedrock|llm|rag|prompt|pdf|ocr|document processing|"
                r"structured (?:json|output|data)|guardrail|monitoring|production python|agentic|orchestration)\b",
                req_l,
            )
        )
        practical_exact = [
            evidence
            for evidence in exact_supporting
            if any(
                fact.fact_id == evidence["fact_id"]
                and (
                    fact.fact_id.startswith("exp_")
                    or fact.source == "project"
                    or (
                        fact.source == "candidate_verified_answer"
                        and not fact.text.lower().startswith("which missing skills can you personally confirm")
                    )
                )
                for fact in facts
            )
        ]
        transferable_supporting = [
            {
                "fact_id": fact.fact_id,
                "company": fact.company,
                "claim": fact.text[:240],
                "confidence": 0.58,
            }
            for fact, text in fact_texts
            if not exact_supporting and _is_transferable_requirement(req_l, text)
        ][:6]
        supporting = exact_supporting or transferable_supporting
        if practical_required and not practical_exact and exact_supporting:
            status = "partial"
        elif len(exact_supporting) >= 2:
            status = "strong"
        elif len(exact_supporting) == 1:
            status = "exact_match"
        elif transferable_supporting:
            status = "transferable_match"
        else:
            status = "missing"
        mapped.append(
            {
                "requirementId": str(item.get("id") or f"req_{len(mapped) + 1:03d}"),
                "requirement": requirement,
                "name": requirement,
                "category": str(item.get("category", "technical")),
                "priority": str(item.get("priority", "required")),
                "importance": int(item.get("importance", 5) or 5),
                "weight": int(item.get("weight", item.get("importance", 5)) or 5),
                "status": status,
                "sourceIds": [e["fact_id"] for e in supporting],
                "supporting_evidence": supporting,
                "reason": (
                    "Skill-level evidence found; practical project or professional evidence is still needed."
                    if status == "partial"
                    else "Direct evidence found."
                    if exact_supporting
                    else "Transferable evidence found."
                    if transferable_supporting
                    else "No verified candidate evidence found."
                ),
                "confidence": 0.9 if len(exact_supporting) >= 2 else 0.72 if exact_supporting else 0.58 if transferable_supporting else 0.0,
                "missing_details": (
                    ["specific project or professional usage, ownership, production status, and validation approach"]
                    if status == "partial"
                    else [] if supporting else [str(item.get("evidence_expected", "verified evidence"))]
                ),
                "missingDetails": (
                    ["specific project or professional usage, ownership, production status, and validation approach"]
                    if status == "partial"
                    else [] if supporting else [str(item.get("evidence_expected", "verified evidence"))]
                ),
            }
        )
    return mapped


def _is_transferable_requirement(requirement: str, evidence_text: str) -> bool:
    for group in TRANSFERABLE_SKILL_GROUPS.values():
        if requirement in group and any(term in evidence_text for term in group if term != requirement):
            if requirement in {"sql server", "t-sql"} and "sql server" not in evidence_text and "t-sql" not in evidence_text:
                return True
            if requirement == "azure" and "aws" in evidence_text:
                return True
            if requirement in {"hipaa", "phi"} and "healthcare" in evidence_text:
                return True
            if requirement in {"rag", "openai", "claude", "gemini", "bedrock"} and ("chatgpt" in evidence_text or "ai-assisted" in evidence_text):
                return True
            return True
    return False


def rank_source_bullets_for_job(
    source_bullets: list[str],
    job_analysis: dict[str, list[dict[str, str | int]]],
    *,
    limit: int = 12,
    experience_id: str = "",
) -> list[dict[str, Any]]:
    """Rank existing bullets before rewriting; never creates new experience."""
    terms = [
        str(item.get("skill", "")).lower()
        for item in [*job_analysis.get("required", []), *job_analysis.get("preferred", [])]
        if str(item.get("skill", "")).strip()
    ]
    responsibilities = [str(item.get("text", "")).lower() for item in job_analysis.get("responsibilities", [])]
    ranked: list[tuple[int, int, str, list[str]]] = []
    for idx, bullet in enumerate(source_bullets):
        clean = _clean(bullet)
        lower = clean.lower()
        matched_terms = [term for term in terms if term and _term_supported_by_text(term, lower)]
        resp_hits = sum(1 for resp in responsibilities if resp and len(set(resp.split()) & set(lower.split())) >= 3)
        metric_bonus = 2 if re.search(r"\d", clean) else 0
        raw_score = len(matched_terms) * 22 + resp_hits * 8 + metric_bonus * 6
        score = max(0, min(100, raw_score))
        if score >= 70:
            action = "rewrite"
        elif score >= 35:
            action = "keep"
        elif score >= 15:
            action = "ask_for_detail"
        else:
            action = "omit"
        ranked.append((score, -idx, clean, matched_terms))
    ranked.sort(reverse=True)
    return [
        {
            "source_index": abs(original_index),
            "sourceOrder": abs(original_index) + 1,
            "sourceBulletId": f"{experience_id}_bullet_{abs(original_index) + 1:03d}" if experience_id else "",
            "experienceId": experience_id,
            "text": bullet,
            "matched_requirements": matched,
            "rank_score": score,
            "score": score,
            "action": "rewrite" if score >= 70 else "keep" if score >= 35 else "ask_for_detail" if score >= 15 else "omit",
        }
        for score, original_index, bullet, matched in ranked[:limit]
        if bullet
    ]


def _term_supported_by_text(term: str, text: str) -> bool:
    if term in text:
        return True
    aliases = {
        "rest api": ("api", "rest"),
        "rest apis": ("api", "rest"),
        "ci/cd": ("pipeline", "deployment", "github actions"),
        "structured json": ("json", "structured output"),
        "structured output": ("json", "schema", "validation"),
        "structured outputs": ("json", "schema", "validation"),
        "sql": ("database", "postgres", "mysql", "jdbc"),
    }
    return any(alias in text for alias in aliases.get(term, ()))


def unsupported_terms_for_claim(claim: str, facts: list[SourceFact]) -> list[str]:
    claim_terms = extract_named_terms(claim)
    corpus = "\n".join(f.text for f in facts).lower()
    unsupported: list[str] = []
    claim_l = (claim or "").lower()
    if re.search(r"\b(openai api|claude api|gemini api|bedrock|production\s+llm|llm api)\b", claim_l) and not re.search(
        r"\b(openai api|claude api|gemini api|bedrock|production\s+llm|llm api)\b",
        corpus,
    ):
        unsupported.append("production LLM API experience")
    if re.search(r"\b(ai engineer|ai engineering|machine learning engineer)\b", claim_l) and not re.search(
        r"\b(production\s+ai|production\s+llm|machine learning model|ml pipeline|openai api|claude api|rag)\b",
        corpus,
    ):
        unsupported.append("AI engineering title/identity")
    if re.search(r"\bsql server\b|\bt-sql\b", claim_l) and not re.search(r"\bsql server\b|\bt-sql\b", corpus):
        unsupported.append("SQL Server/T-SQL")
    if re.search(r"\bhipaa\b|\bphi\b", claim_l) and not re.search(r"\bhipaa\b|\bphi\b", corpus):
        unsupported.append("HIPAA/PHI")
    if re.search(r"\bpdf parsing\b|\bocr\b|\bdocument processing\b", claim_l) and not re.search(
        r"\bpdf parsing\b|\bocr\b|\bdocument processing\b|\bparsed pdf\b",
        corpus,
    ):
        unsupported.append("document-processing experience")
    for metric in _METRIC_RE.findall(claim or ""):
        metric_clean = metric.strip().lower()
        if metric_clean and metric_clean not in corpus:
            unsupported.append(metric.strip())
    for term in claim_terms:
        lower = term.lower()
        if _term_supported_by_text(lower, corpus):
            continue
        if _SOFT_SKILL_RE.search(term):
            continue
        unsupported.append(term)
    return unsupported


def infer_source_fact_ids(claim: str, facts: list[SourceFact], *, role_index: int | None = None) -> list[str]:
    claim_l = (claim or "").lower()
    candidates = facts
    if role_index is not None:
        prefix = f"exp_{role_index + 1:03d}_"
        scoped = [fact for fact in facts if fact.fact_id.startswith(prefix)]
        if scoped:
            candidates = scoped
    scored: list[tuple[int, SourceFact]] = []
    claim_words = {w for w in re.findall(r"[a-z0-9+#.]{3,}", claim_l) if len(w) > 2}
    for fact in candidates:
        fact_words = {w for w in re.findall(r"[a-z0-9+#.]{3,}", fact.text.lower()) if len(w) > 2}
        overlap = len(claim_words & fact_words)
        if overlap:
            scored.append((overlap, fact))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [fact.fact_id for _, fact in scored[:3]]


def experience_id_for_role_index(role_index: int) -> str:
    return f"exp_{role_index + 1:03d}"


def source_id_experience_id(source_id: str) -> str:
    match = re.match(r"^(exp_\d{3})_", source_id or "")
    return match.group(1) if match else ""


def _fact_index(facts: list[SourceFact]) -> dict[str, SourceFact]:
    return {fact.fact_id: fact for fact in facts}


def bullet_text(bullet: str | ProvenanceBullet) -> str:
    if isinstance(bullet, dict):
        return _clean(str(bullet.get("text") or bullet.get("finalText") or ""))
    return _clean(str(bullet))


def bullet_experience_id(bullet: str | ProvenanceBullet, *, fallback_role_index: int | None = None) -> str:
    if isinstance(bullet, dict):
        explicit = _clean(str(bullet.get("experienceId") or ""))
        if explicit:
            return explicit
    if fallback_role_index is not None:
        return experience_id_for_role_index(fallback_role_index)
    return ""


def bullet_source_ids(bullet: str | ProvenanceBullet) -> list[str]:
    if isinstance(bullet, dict):
        raw = bullet.get("sourceIds") or bullet.get("sourceFactIds") or bullet.get("source_fact_ids") or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(v) for v in raw if str(v).strip()]
    return []


def bullet_source_bullet_ids(bullet: str | ProvenanceBullet) -> list[str]:
    if isinstance(bullet, dict):
        raw = bullet.get("sourceBulletIds") or []
        if isinstance(raw, str):
            raw = [raw]
        source_bullets = [str(v) for v in raw if str(v).strip()]
        if source_bullets:
            return source_bullets
        return [source_id for source_id in bullet_source_ids(bullet) if re.match(r"^exp_\d{3}_bullet_\d{3}$", source_id)]
    return []


def _metric_ids_for_sources(source_ids: list[str]) -> list[str]:
    return [f"{source_id}_metric_001" for source_id in source_ids if re.match(r"^exp_\d{3}_bullet_\d{3}$", source_id)]


def make_provenance_bullet(
    *,
    text: str,
    role_index: int,
    source_ids: list[str],
    facts: list[SourceFact],
    transformation_type: str = "rewritten",
) -> ProvenanceBullet | None:
    clean = _clean(text).lstrip("-*â€¢ ").strip()
    if not clean:
        return None
    experience_id = experience_id_for_role_index(role_index)
    fact_lookup = _fact_index(facts)
    source_ids = list(dict.fromkeys(source_ids))
    role_source_ids = [source_id for source_id in source_ids if source_id_experience_id(source_id)]
    if any(source_id_experience_id(source_id) != experience_id for source_id in role_source_ids):
        return None
    if not source_ids:
        return None
    source_bullet_ids = [source_id for source_id in source_ids if re.match(rf"^{experience_id}_bullet_\d{{3}}$", source_id)]
    role_header_ids = [source_id for source_id in source_ids if source_id == f"{experience_id}_header"]
    user_verified_ids = [source_id for source_id in source_ids if source_id.startswith("user_verified_")]
    if not (source_bullet_ids or user_verified_ids):
        return None
    company = next((fact_lookup[s].company for s in source_ids if s in fact_lookup and fact_lookup[s].company), "")
    title = next((fact_lookup[s].title for s in source_ids if s in fact_lookup and fact_lookup[s].title), "")
    metric_ids = [
        f"{source_id}_metric_{i + 1:03d}"
        for source_id in source_bullet_ids
        for i, metric in enumerate(_METRIC_RE.findall(fact_lookup[source_id].text if source_id in fact_lookup else ""))
        if metric.strip().lower() in clean.lower()
    ]
    return {
        "text": clean,
        "finalText": clean,
        "experienceId": experience_id,
        "company": company,
        "title": title,
        "sourceIds": [*source_bullet_ids, *role_header_ids, *user_verified_ids],
        "sourceFactIds": [*source_bullet_ids, *role_header_ids, *user_verified_ids],
        "sourceBulletIds": source_bullet_ids,
        "metricIds": metric_ids,
        "transformationType": transformation_type,
        "validationStatus": "unvalidated",
    }


def assert_render_provenance(roles: list[Any], bullets_by_role: list[list[str | ProvenanceBullet]]) -> None:
    for role_index, role_bullets in enumerate(bullets_by_role):
        expected = experience_id_for_role_index(role_index)
        for bullet in role_bullets:
            actual = bullet_experience_id(bullet, fallback_role_index=role_index)
            if actual != expected:
                company = _clean(getattr(roles[role_index], "company", "")) if role_index < len(roles) else expected
                raise ValueError(
                    f"Role provenance validation failed: bullet from {actual or 'unknown'} cannot render under {expected} ({company})."
                )


def filter_supported_bullets(
    generated: list[dict[str, Any] | str],
    source_bullets: list[str],
    facts: list[SourceFact],
    *,
    role_index: int,
    wanted: int,
) -> list[ProvenanceBullet]:
    accepted: list[ProvenanceBullet] = []
    accepted_texts: set[str] = set()
    experience_id = experience_id_for_role_index(role_index)
    for item in generated:
        if isinstance(item, dict):
            text = _clean(str(item.get("generated_text") or item.get("text") or ""))
            source_ids = [str(v) for v in item.get("source_fact_ids", []) if str(v).strip()]
            if not source_ids:
                source_ids = [str(v) for v in item.get("sourceIds", []) if str(v).strip()]
            if not source_ids:
                source_ids = [str(v) for v in item.get("sourceBulletIds", []) if str(v).strip()]
            unsupported = [str(v) for v in item.get("unsupported_terms", []) if str(v).strip()]
        else:
            text = _clean(str(item))
            source_ids = infer_source_fact_ids(text, facts, role_index=role_index)
            unsupported = unsupported_terms_for_claim(text, facts)
        if not text or _has_malformed_text(text) or unsupported or _VAGUE_GENERATED_RE.search(text):
            continue
        if not source_ids:
            source_ids = infer_source_fact_ids(text, facts, role_index=role_index)
        if not source_ids:
            continue
        if any(source_id_experience_id(source_id) and source_id_experience_id(source_id) != experience_id for source_id in source_ids):
            continue
        fact_lookup = _fact_index(facts)
        user_facts = [
            fact_lookup[source_id]
            for source_id in source_ids
            if source_id.startswith("user_verified_") and source_id in fact_lookup
        ]
        if any(not fact.experience_id or fact.experience_id != experience_id for fact in user_facts):
            continue
        bullet = make_provenance_bullet(
            text=text,
            role_index=role_index,
            source_ids=source_ids,
            facts=facts,
            transformation_type="rewritten",
        )
        if bullet and bullet_text(bullet).lower() not in accepted_texts:
            accepted.append(bullet)
            accepted_texts.add(bullet_text(bullet).lower())
        if len(accepted) >= wanted:
            break
    for source_order, src in enumerate(source_bullets, start=1):
        clean = _clean(src).lstrip("-* ").strip()
        source_id = f"{experience_id}_bullet_{source_order:03d}"
        if (
            clean
            and not _has_malformed_text(clean)
            and not unsupported_terms_for_claim(clean, facts)
            and clean.lower() not in accepted_texts
        ):
            bullet = make_provenance_bullet(
                text=clean,
                role_index=role_index,
                source_ids=[source_id],
                facts=facts,
                transformation_type="unchanged",
            )
            if bullet:
                accepted.append(bullet)
                accepted_texts.add(clean.lower())
        if len(accepted) >= wanted:
            break
    return accepted[:wanted]
    for src in source_bullets:
        clean = _clean(src).lstrip("-*• ").strip()
        if (
            clean
            and not _has_malformed_text(clean)
            and not unsupported_terms_for_claim(clean, facts)
            and clean.lower() not in {b.lower() for b in accepted}
        ):
            accepted.append(clean)
        if len(accepted) >= wanted:
            break
    return accepted[:wanted]


def select_nonduplicative_bullets(
    roles: list[Any],
    bullets_by_role: list[list[str | ProvenanceBullet]],
    facts: list[SourceFact],
    *,
    max_total: int = 24,
) -> list[list[str | ProvenanceBullet]]:
    assert_render_provenance(roles, bullets_by_role)
    selected: list[list[str | ProvenanceBullet]] = []
    global_seen: list[tuple[str, set[str], set[str], str]] = []
    total = 0
    role_count = max(1, len(roles), len(bullets_by_role))
    for role_i in range(role_count):
        # The upstream JD/recency planner already requests the appropriate depth.
        # Do not reintroduce an arbitrary 3-5 bullet cap during deduplication.
        role_cap = max_total
        role_out: list[str | ProvenanceBullet] = []
        local_seen: list[tuple[str, set[str], set[str], str]] = []
        for bullet in bullets_by_role[role_i] if role_i < len(bullets_by_role) else []:
            if total >= max_total or len(role_out) >= role_cap:
                break
            signature = _bullet_signature(bullet, facts, role_i)
            if _is_duplicate_signature(signature, local_seen) or _is_duplicate_signature(signature, global_seen):
                continue
            role_out.append(bullet)
            local_seen.append(signature)
            global_seen.append(signature)
            total += 1
        selected.append(role_out)
    return selected


def _bullet_signature(bullet: str | ProvenanceBullet, facts: list[SourceFact], role_index: int) -> tuple[str, set[str], set[str], str]:
    text = bullet_text(bullet)
    norm = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    source_ids = set(bullet_source_ids(bullet) or infer_source_fact_ids(text, facts, role_index=role_index))
    metrics = {m.strip().lower() for m in _METRIC_RE.findall(text)}
    action = _primary_action(text)
    subject = re.sub(r"\b(?:built|developed|designed|implemented|optimized|improved|reduced|increased|led|created|integrated)\b", "", norm).strip()
    subject = " ".join(subject.split()[:8])
    return norm, source_ids, metrics, f"{action}:{subject}"


def _is_duplicate_signature(signature: tuple[str, set[str], set[str], str], seen: list[tuple[str, set[str], set[str], str]]) -> bool:
    norm, source_ids, metrics, action_object = signature
    norm_words = set(norm.split())
    for prev_norm, prev_source_ids, prev_metrics, prev_action_object in seen:
        if norm == prev_norm:
            return True
        overlapping_sources = source_ids & prev_source_ids
        if overlapping_sources and any(not source_id.startswith("user_verified_") for source_id in overlapping_sources):
            return True
        if metrics and prev_metrics and metrics & prev_metrics and action_object == prev_action_object:
            return True
        prev_words = set(prev_norm.split())
        if norm_words and prev_words and len(norm_words & prev_words) / max(1, min(len(norm_words), len(prev_words))) >= 0.92:
            return True
        if action_object and action_object == prev_action_object:
            return True
    return False


def audit_bullets(
    *,
    roles: list[Any],
    bullets_by_role: list[list[str]],
    facts: list[SourceFact],
    job_analysis: dict[str, list[dict[str, str | int]]],
) -> list[dict[str, Any]]:
    terms = [
        str(item.get("skill", ""))
        for item in [*job_analysis.get("required", []), *job_analysis.get("preferred", [])]
        if str(item.get("skill", "")).strip()
    ]
    audit: list[dict[str, Any]] = []
    role_index_by_id = {id(role): idx for idx, role in enumerate(roles)}
    for display_i, role in enumerate(roles):
        source_role_index = role_index_by_id.get(id(role), display_i)
        company = _clean(getattr(role, "company", ""))
        for bullet_i, bullet in enumerate(bullets_by_role[display_i] if display_i < len(bullets_by_role) else [], start=1):
            text = bullet_text(bullet)
            source_ids = bullet_source_ids(bullet) or infer_source_fact_ids(text, facts, role_index=source_role_index)
            supported_requirements = [term for term in terms if term.lower() in text.lower()]
            unsupported = unsupported_terms_for_claim(text, facts)
            audit.append(
                {
                    "claimId": f"claim_exp_{display_i + 1:03d}_{bullet_i:03d}",
                    "finalText": text,
                    "bullet": text,
                    "experienceId": bullet_experience_id(bullet, fallback_role_index=source_role_index),
                    "company": company,
                    "source": source_ids,
                    "sourceIds": source_ids,
                    "sourceBulletIds": bullet_source_bullet_ids(bullet),
                    "metricIds": bullet.get("metricIds", []) if isinstance(bullet, dict) else [],
                    "validationStatus": bullet.get("validationStatus", "") if isinstance(bullet, dict) else "",
                    "transformationType": (
                        bullet.get("transformationType", "")
                        if isinstance(bullet, dict)
                        else "rewritten" if source_ids and text.lower() not in {f.text.lower() for f in facts if f.fact_id in source_ids} else "unchanged"
                    ),
                    "evidence_strength": "strong" if len(source_ids) >= 2 else "supported" if source_ids else "missing",
                    "evidenceStrength": "strong" if len(source_ids) >= 2 else "supported" if source_ids else "missing",
                    "job_requirements_supported": supported_requirements,
                    "requirementsSupported": supported_requirements,
                    "unsupported_terms": unsupported,
                    "confidence": 0.92 if len(source_ids) >= 2 else 0.74 if source_ids else 0.0,
                }
            )
    return audit


def build_gap_report(evidence_map: list[dict[str, Any]]) -> list[str]:
    gaps = []
    for item in evidence_map:
        if item.get("status") in {"missing", "unknown", "contradicted", "partial"}:
            gaps.append(f"{item.get('requirement')}: unsupported; ask for {', '.join(item.get('missing_details') or ['verified evidence'])}.")
        elif item.get("status") == "transferable_match":
            gaps.append(f"{item.get('requirement')}: transferable only; exact evidence not found.")
    return gaps[:10]


def generate_clarifying_questions(gap_report: list[str]) -> list[str]:
    joined = "\n".join(gap_report).lower()
    questions: list[str] = []
    if re.search(r"openai|claude|gemini|bedrock|llm|rag|langchain", joined):
        questions.extend(
            [
                "Have you built a production application using OpenAI, Claude, Gemini, or Bedrock?",
                "What API did you use, and did the model return structured JSON?",
                "How did you validate model output, handle parsing failures, and add guardrails?",
                "Was the system deployed to production, and how many users, documents, or requests did it support?",
            ]
        )
    if re.search(r"pdf|ocr|document", joined):
        questions.append("Did you process PDFs, OCR output, invoices, forms, contracts, or other document inputs?")
    if re.search(r"sql|database|stored|t-sql", joined):
        questions.extend(
            [
                "Did you store the output in SQL, and which SQL database did you use?",
                "Did you build stored procedures or optimize complex queries?",
            ]
        )
    if re.search(r"healthcare|hipaa|phi|financial|regulated", joined):
        questions.append("Did you work with healthcare, financial, personal, or regulated data?")
    questions.append("Can you describe one confidently wrong or failed output and the guardrail you added?")
    return list(dict.fromkeys(questions))[:12]


def evaluate_eligibility(job_analysis: dict[str, Any], facts: list[SourceFact]) -> dict[str, Any]:
    requirements = [
        *job_analysis.get("locationRequirements", []),
        *job_analysis.get("workAuthorizationRequirements", []),
    ]
    if not requirements:
        return {"eligibilityStatus": "unknown", "requirements": [], "reason": "No explicit eligibility constraints detected."}
    corpus = "\n".join(f.text for f in facts).lower()
    missing: list[dict[str, Any]] = []
    supported: list[dict[str, Any]] = []
    for req in requirements:
        text = str(req.get("text", ""))
        tokens = [
            t.lower()
            for t in re.findall(r"[A-Za-z]{4,}", text)
            if t.lower()
            not in {
                "must",
                "based",
                "located",
                "hybrid",
                "onsite",
                "remote",
                "work",
                "authorization",
                "authorized",
                "required",
                "visa",
                "sponsorship",
            }
        ]
        if tokens and any(token in corpus for token in tokens):
            supported.append(req)
        else:
            missing.append(req)
    if missing and supported:
        status = "unknown"
    elif missing:
        status = "possibly_ineligible"
    else:
        status = "eligible"
    return {
        "eligibilityStatus": status,
        "requirements": requirements,
        "missing": missing,
        "supported": supported,
        "reason": "Eligibility constraints are separated from skill scoring.",
    }


def score_resume_match(
    *,
    job_analysis: dict[str, list[dict[str, str | int]]],
    evidence_map: list[dict[str, Any]],
    final_resume_text: str,
    eligibility: dict[str, Any] | None = None,
) -> dict[str, int]:
    reqs = [*job_analysis.get("required", []), *job_analysis.get("preferred", [])]
    terms = [str(item.get("skill", "")) for item in reqs if str(item.get("skill", "")).strip()]
    final_l = (final_resume_text or "").lower()
    keyword_hits = sum(1 for term in terms if term.lower() in final_l)
    supported = sum(1 for item in evidence_map if item.get("status") in {"strong", "exact_match", "supported", "strongly_supported"})
    required = [item for item in evidence_map if item.get("priority") == "required"] or evidence_map[: max(1, len(job_analysis.get("required", [])))]
    preferred = [item for item in evidence_map if item.get("priority") == "preferred"]
    required_supported = sum(1 for item in required if item.get("status") in {"strong", "exact_match", "supported", "strongly_supported"})
    preferred_supported = sum(1 for item in preferred if item.get("status") in {"strong", "exact_match", "supported", "strongly_supported"})
    unsupported_in_output = sum(1 for term in terms if term.lower() in final_l and not any(item.get("requirement") == term and item.get("status") != "unsupported" for item in evidence_map))
    keyword_match = round(100 * keyword_hits / max(1, len(terms)))
    evidence_match = round(100 * supported / max(1, len(evidence_map)))
    minimum_match = round(100 * required_supported / max(1, len(required)))
    preferred_match = round(100 * preferred_supported / max(1, len(preferred))) if preferred else 0
    credibility_score = max(0, 100 - unsupported_in_output * 12)
    ats_score = min(100, round((keyword_match * 0.45) + (credibility_score * 0.35) + 20))
    eligibility_status = (eligibility or {}).get("eligibilityStatus", "unknown")
    eligibility_penalty = 20 if eligibility_status == "possibly_ineligible" else 0
    overall_match = max(
        0,
        round((keyword_match * 0.15) + (evidence_match * 0.25) + (minimum_match * 0.35) + (credibility_score * 0.25) - eligibility_penalty),
    )
    critical_gaps = [str(item.get("requirement")) for item in required if item.get("status") not in {"strong", "exact_match", "supported", "strongly_supported"}]
    strengths = [str(item.get("requirement")) for item in evidence_map if item.get("status") in {"strong", "exact_match"}][:8]
    return {
        "keyword_match": round(100 * keyword_hits / max(1, len(terms))),
        "experience_match": evidence_match,
        "evidence_match": evidence_match,
        "minimum_qualification_match": minimum_match,
        "mandatoryQualificationMatch": minimum_match,
        "preferredQualificationMatch": preferred_match,
        "ats_score": ats_score,
        "atsFormattingScore": ats_score,
        "credibility_score": credibility_score,
        "credibilityScore": credibility_score,
        "overall_match": overall_match,
        "overallMatch": overall_match,
        "eligibilityStatus": eligibility_status,
        "criticalGaps": critical_gaps,
        "strengths": strengths,
    }


def validate_tailored_resume(
    *,
    summary: str,
    skills: str,
    bullets_by_role: list[list[str | ProvenanceBullet]],
    facts: list[SourceFact],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    all_bullets = [(role_index, bullet) for role_index, role_bullets in enumerate(bullets_by_role) for bullet in role_bullets]
    metric_sources = _metric_source_index(facts)
    fact_lookup = _fact_index(facts)
    for role_index, bullet in all_bullets:
        text = bullet_text(bullet)
        norm = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        expected_experience_id = experience_id_for_role_index(role_index)
        actual_experience_id = bullet_experience_id(bullet, fallback_role_index=role_index)
        source_ids = bullet_source_ids(bullet) or infer_source_fact_ids(text, facts, role_index=role_index)
        source_bullet_ids = bullet_source_bullet_ids(bullet)
        metric_ids = bullet.get("metricIds", []) if isinstance(bullet, dict) else []
        if actual_experience_id != expected_experience_id:
            issues.append({"severity": "critical", "claim": text, "reason": "Final bullet is assigned to a different experienceId than its rendered role."})
        source_experience_ids = {
            source_id_experience_id(source_id)
            for source_id in source_ids
            if source_id_experience_id(source_id)
        }
        if len(source_experience_ids) > 1:
            issues.append({"severity": "critical", "claim": text, "reason": "Final bullet combines source bullets from different roles."})
        if source_experience_ids and source_experience_ids != {expected_experience_id}:
            issues.append({"severity": "critical", "claim": text, "reason": "Source bullet role differs from rendered role."})
        for metric_id in metric_ids:
            metric_source = metric_id.rsplit("_metric_", 1)[0]
            if metric_source and metric_source not in source_bullet_ids:
                issues.append({"severity": "critical", "claim": text, "reason": "Metric belongs to a different source bullet."})
            if source_id_experience_id(metric_source) and source_id_experience_id(metric_source) != expected_experience_id:
                issues.append({"severity": "critical", "claim": text, "reason": "Metric belongs to a different role."})
        for source_id in source_ids:
            fact = fact_lookup.get(source_id)
            if fact and fact.company and isinstance(bullet, dict) and bullet.get("company") and _clean(str(bullet.get("company"))) != fact.company:
                issues.append({"severity": "critical", "claim": text, "reason": "Company changed from source evidence."})
            if fact and fact.title and isinstance(bullet, dict) and bullet.get("title") and _clean(str(bullet.get("title"))) != fact.title:
                issues.append({"severity": "critical", "claim": text, "reason": "Title changed from source evidence."})
        if not source_ids:
            issues.append({"severity": "critical", "claim": text, "reason": "Final claim has no candidate source ID."})
        if _has_malformed_text(text):
            issues.append({"severity": "critical", "claim": text, "reason": "Malformed or ambiguous extracted text."})
            continue
        if len(text.split()) > 32:
            issues.append({"severity": "medium", "claim": text, "reason": "Bullet is over the 30-word target."})
        if _VAGUE_GENERATED_RE.search(text):
            issues.append({"severity": "medium", "claim": text, "reason": "Vague generated language without specific evidence."})
        if norm in seen:
            issues.append({"severity": "medium", "claim": text, "reason": "Duplicate or near-duplicate bullet."})
        seen.add(norm)
        unsupported = unsupported_terms_for_claim(text, facts)
        if unsupported:
            issues.append({"severity": "critical", "claim": text, "reason": f"Unsupported terms: {', '.join(unsupported)}"})
        cited_facts = [fact_lookup[source_id] for source_id in source_ids if source_id in fact_lookup]
        scoped_metric_sources = _metric_source_index(cited_facts) if cited_facts else metric_sources
        metric_issue = "" if _metric_claim_supported_by_source_text(text, cited_facts) else _metric_alignment_issue(text, scoped_metric_sources)
        if metric_issue:
            issues.append({"severity": "critical", "claim": text, "reason": metric_issue})
    for section_name, text in (("summary", summary), ("skills", skills)):
        unsupported = unsupported_terms_for_claim(text, facts)
        if unsupported:
            issues.append(
                {
                    "severity": "high",
                    "claim": section_name,
                    "reason": f"{section_name.title()} contains unsupported terms: {', '.join(unsupported[:8])}",
                }
            )
    for line in (skills or "").splitlines():
        if not line.strip():
            continue
        label = line.split(":", 1)[0].strip() if ":" in line else line.strip()
        if label not in CANONICAL_SKILL_CATEGORIES:
            issues.append({"severity": "high", "claim": label, "reason": "Malformed or non-canonical skill category."})
    return {"status": "PASS" if not any(i["severity"] in {"critical", "high"} for i in issues) else "FAIL", "issues": issues[:20]}


def _metric_source_index(facts: list[SourceFact]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for fact in facts:
        for metric in _METRIC_RE.findall(fact.text):
            subject = _metric_subject(fact.text, metric)
            if subject:
                index.setdefault(metric.strip().lower(), []).append(subject)
    return index


def _metric_alignment_issue(claim: str, metric_sources: dict[str, list[str]]) -> str:
    for metric in _METRIC_RE.findall(claim):
        key = metric.strip().lower()
        source_subjects = metric_sources.get(key, [])
        if not source_subjects:
            continue
        claim_subject = _metric_subject(claim, metric)
        if not claim_subject:
            continue
        claim_words = set(claim_subject.split())
        if any(db in claim_subject for db in ("postgresql", "sql server", "database")) and not any(
            any(db in source for db in ("postgresql", "sql server", "database")) for source in source_subjects
        ):
            return f"Metric {metric} cannot be reassigned to database performance."
        if not any(len(claim_words & set(source.split())) >= 1 for source in source_subjects):
            return f"Metric {metric} is detached from its original meaning ({'; '.join(source_subjects[:2])})."
    return ""


def _metric_claim_supported_by_source_text(claim: str, source_facts: list[SourceFact]) -> bool:
    """Accept a metric rewrite when its cited fact contains the same metric and strong semantic overlap."""
    metrics = {metric.strip().lower() for metric in _METRIC_RE.findall(claim)}
    if not metrics or not source_facts:
        return False
    stop = {
        "with", "from", "that", "this", "using", "used", "built", "developed", "designed",
        "implemented", "improved", "reduced", "increased", "through", "into", "over", "under",
    }
    claim_words = {
        word for word in re.findall(r"[a-z][a-z0-9+#.-]{2,}", claim.lower())
        if word not in stop
    }
    for metric in metrics:
        matching_facts = [fact for fact in source_facts if metric in {m.strip().lower() for m in _METRIC_RE.findall(fact.text)}]
        if not matching_facts:
            return False
        if not any(
            len(
                claim_words
                & {
                    word for word in re.findall(r"[a-z][a-z0-9+#.-]{2,}", fact.text.lower())
                    if word not in stop
                }
            ) >= 4
            for fact in matching_facts
        ):
            return False
    return True
