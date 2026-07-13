import asyncio
import base64
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

from app.schemas import TailorResponse
from app.services.resume_prompts import CANONICAL_TAILORING_POLICY
from app.services.openai_compat import chat_completion_controls
from app.services.docx_convert import convert_docx_bytes_to_pdf, pdf_download_filename
from app.services.docx_resume import (
    apply_tailored_sections_to_docx,
    output_docx_filename,
    parse_resume_from_docx,
)
from app.services.pdf_resume import (
    default_ats_bullets_per_role,
    effective_bullets_per_role,
    ats_bullets_for_generation,
    _min_bullets_per_role_env,
    extract_jd_target_role_title,
    merge_experience_headers_with_bullets,
    merge_profile_links_into_contact,
    merge_skills_for_ats,
    merge_skills_preserving_labels,
    partition_experience_bullets_by_role,
    sanitize_target_job_role,
    split_experience_line_blocks,
)
from app.services.sectionize import ParsedResume

_BULLET_CHARS = r"\-•*–—\u2022\u25cf\u25cb\u25aa\u25e6\u00b7\u2219"
_BULLET_LINE_RE = re.compile(rf"^[{_BULLET_CHARS}]\s+")
_YEARS_OF_EXPERIENCE_RE = re.compile(
    r"\b(\d+\+\s*(?:years?|yrs?)(?:\s+of\s+(?:professional\s+)?experience)?|"
    r"\d+\s+years?(?:\s+of\s+(?:professional\s+)?experience)?)\b",
    re.I,
)
_METRIC_SNIPPET_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|percent|x\b|X\b|k\+|K\+|m\+|M\+)|"
    r"(?:reduced|increased|improved|cut|decreased|accelerated|grew|lowered|boosted|saved|"
    r"delivered|processed|scaled)[^.!?\n]{0,70}\d+",
    re.I,
)

_AI_ROLE_RE = re.compile(
    r"\b(ai|ml|llm|machine\s+learning|generative|agentic|data\s+scien|deep\s+learning|"
    r"neural|nlp|computer\s+vision|mlops|prompt)\b",
    re.I,
)

_DEVOPS_ROLE_RE = re.compile(
    r"\b(devops|devsecops|sre|site\s+reliability|platform\s+engineer|cloud\s+engineer|"
    r"infrastructure\s+engineer|kubernetes\s+operations|ci/?cd)\b",
    re.I,
)

_NAMED_TECH_RE = re.compile(
    r"\b(?:Python|FastAPI|Django|Flask|LangChain|Pinecone|OpenAI|Redis|Celery|PostgreSQL|"
    r"MongoDB|AWS|Azure|GCP|Cloud Run|Firestore|BigQuery|GKE|Docker|Kubernetes|AKS|Terraform|Helm|GitOps|ArgoCD|Flux|"
    r"CI/CD|GitHub\s+Actions|Azure\s+DevOps|TeamCity|Jenkins|OpenTelemetry|Grafana|"
    r"Pydantic|GraphQL|REST|Java|Spring Boot|Spring|Hibernate|JPA|Maven|Gradle|JUnit|MySQL|"
    r"JavaScript|TypeScript|React|Angular|Vue|Node\.js|"
    r"Spark|MLflow|Pandas|NumPy|Git|GitHub|Linux|Bash|PowerShell|YAML|Splunk|Datadog|"
    r"Application\s+Insights|Azure\s+Monitor|Key\s+Vault|ACR|AKS|ARM|RBAC|"
    r"RAG|MCP|LLM|vector\s+stores?|microservices?|Shopify)\b",
    re.I,
)

_ENGINEERING_PRACTICE_RE = re.compile(
    r"\b(?:retries?|timeouts?|degraded\s+dependencies?|recovery\s+procedures?|"
    r"incident(?:s)?|debugging|latency|throughput|observability|evals?|"
    r"structured\s+outputs?|retrieval\s+pipelines?|agentic\s+workflows?|"
    r"tool[\s-]?use|tool-using|mcp\b|client communication|technical leadership|"
    r"feedback loops?|business-critical|human review|"
    r"cloud\s+migrations?|database\s+optimization|"
    r"security\s+protocols?|secrets?\s+management|vulnerability|patching|"
    r"access\s+control|branching\s+strateg|code\s+review|version\s+control|"
    r"infrastructure\s+as\s+code|gitops|monitoring|logging|alerting|"
    r"linux\s+administration|shell\s+scripting|availability|sla|sre)\b",
    re.I,
)

_MANDATORY_AI_KEYWORD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bmcp\b", "MCP"),
    (r"tool[\s-]?use|tool-using", "tool use"),
    (r"retrieval pipelines?", "retrieval pipelines"),
    (r"structured outputs?", "structured outputs"),
    (r"agentic workflows?", "agentic workflows"),
    (r"multi-agent", "multi-agent"),
    (r"\bevals?\b", "evals"),
    (r"observability|opentelemetry", "observability"),
    (r"production debugging|debugged production", "production debugging"),
    (r"maintainability", "maintainability"),
    (r"client communication|strategists?|client discovery|client-facing|nontechnical", "client-facing"),
    (r"technical leadership", "technical leadership"),
    (r"feedback loops?", "feedback loops"),
    (r"latency|cost.*maintainability|accuracy.*latency", "engineering judgment"),
)

_AI_MANDATORY_SKILLS_TERMS: tuple[str, ...] = (
    "MCP",
    "tool use",
    "structured outputs",
    "evals",
    "retrieval pipelines",
    "agentic workflows",
    "RAG",
    "multi-agent orchestration",
)

_APPLIED_AI_CONSULTING_JD_RE = re.compile(
    r"\b(consulting|client[s]?|enterprise\s+client[s]?|strategists?|designers?|"
    r"business[\s-]critical|production[\s-]grade|applied\s+ai|nontechnical|"
    r"engagement[s]?|client\s+conversation[s]?|client\s+room|kickoff)\b",
    re.I,
)

_JD_RESPONSIBILITY_PHRASE_RE = re.compile(
    r"\b(?:agentic workflows?|tool[\s-]?using llm[s]?|retrieval pipelines?|orchestration layers?|"
    r"multi[\s-]?step agents?|structured outputs?|evals?|observability|feedback loops?|"
    r"production[\s-]grade|business[\s-]critical|MCP|skills?|version control hygiene|"
    r"accuracy,?\s*latency,?\s*cost|maintainability|client discovery|client conversation[s]?)\b",
    re.I,
)

_AI_OWNERSHIP_PHRASES = frozenset(
    {
        "technical leadership",
        "client discovery",
        "client communication",
        "production debugging",
        "debugged production",
        "maintainability",
        "feedback loops",
        "latency",
        "accuracy",
        "business-critical",
        "translating",
        "strategists",
        "nontechnical",
        "owned",
        "owning",
    }
)

_MANDATORY_DEVOPS_KEYWORD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"github\s+actions", "GitHub Actions"),
    (r"azure\s+devops|azure\b", "Azure"),
    (r"kubernetes|\baks\b", "Kubernetes"),
    (r"terraform", "Terraform"),
    (r"ci/?cd|continuous\s+integration", "CI/CD"),
    (r"\bgit\b|github", "Git"),
    (r"docker", "Docker"),
    (r"linux|bash|shell\s+script", "Linux"),
    (r"monitoring|application\s+insights|datadog|splunk|azure\s+monitor", "monitoring"),
    (r"secrets?\s+management|key\s+vault|rbac|vulnerability|patching", "security"),
    (r"gitops|helm", "GitOps/Helm"),
    (r"infrastructure\s+as\s+code|\biac\b", "IaC"),
)

_DEVOPS_ATS_TERMS = (
    "CI/CD",
    "GitHub Actions",
    "Azure DevOps",
    "Git",
    "GitHub",
    "GitOps",
    "Kubernetes",
    "AKS",
    "Azure Kubernetes Service",
    "Docker",
    "Helm",
    "Terraform",
    "Infrastructure as Code",
    "IaC",
    "Azure",
    "Azure Monitor",
    "Application Insights",
    "Log Analytics",
    "Datadog",
    "Azure Key Vault",
    "secrets management",
    "RBAC",
    "Linux",
    "Bash",
    "shell scripting",
    "YAML",
    "monitoring",
    "logging",
    "alerting",
    "incident response",
    "patching",
    "vulnerability assessment",
    "access control",
    "Azure Container Registry",
    "ACR",
    "managed identity",
    "Azure Policy",
    "ARM",
    "Azure Resource Manager",
    "microservices",
    "containerization",
    "availability",
    "SLA",
    "SRE",
    "reliability engineering",
    "deployment frequency",
    "branching strategies",
    "code review",
    "TeamCity",
    "Splunk",
    "PowerShell",
    "Azure Networking",
    "Azure Storage",
    "Azure Virtual Machines",
)

_JD_TOOL_PHRASE_RE = re.compile(
    r"\b(?:GitHub Actions|Azure DevOps|Azure Kubernetes Service|AKS|Application Insights|"
    r"Azure Monitor|Azure Key Vault|Azure Container Registry|ACR|Log Analytics|"
    r"Terraform|Kubernetes|Docker|Helm|GitOps|ArgoCD|Flux|Datadog|Splunk|TeamCity|"
    r"Jenkins|GitHub|Azure Resource Manager|ARM|Azure RBAC|Managed Identity|"
    r"Azure Policy|Azure Networking|Azure Storage|PowerShell|Bash|Linux|YAML|"
    r"GitLab CI|CircleCI|Ansible|Puppet|Chef|Prometheus|Grafana|OpenTelemetry|"
    r"VPC|IAM|RDS|Aurora|ECS|Fargate|Lambda|DynamoDB|CloudWatch|S3|EC2|Route\s+53|"
    r"CloudFormation|Secrets Manager|AWS Organizations|FinOps|"
    r"Spring Boot|Spring Framework|\bSpring\b|Hibernate|JPA|Maven|Gradle|JUnit|"
    r"\bJava\b|MySQL|REST APIs?|microservices?|CI/CD|\bGit\b|\bSQL\b|Agile|SDLC|"
    r"FastAPI|LangChain|Pinecone|OpenAI|Redis|PostgreSQL|AWS|GCP|MCP|structured outputs|"
    r"agentic|evals?|RAG|retrieval)\b",
    re.I,
)

_AWS_INFRA_JD_RE = re.compile(
    r"\b(?:aws|ec2|vpc|iam|rds|aurora|ecs|fargate|lambda|dynamodb|cloudwatch|"
    r"s3|terraform|disaster recovery|high availability|networking|finops|cost reporting|"
    r"database operations|security hardening|infrastructure ownership)\b",
    re.I,
)

_AWS_MANDATORY_KEYWORD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\baws\b", "AWS"),
    (r"terraform", "Terraform"),
    (r"\bvpc\b|networking", "VPC/networking"),
    (r"\biam\b", "IAM"),
    (r"\brds\b|\baurora\b", "RDS/Aurora"),
    (r"disaster recovery|high availability|\bha\b|\bdr\b", "HA/DR"),
    (r"security hardening|security baselines?|patching", "security hardening"),
    (r"docker|\becs\b|fargate", "Docker/ECS"),
    (r"\blambda\b", "Lambda"),
    (r"ci/?cd|github\s+actions", "CI/CD"),
    (r"python|bash|shell\s+script", "scripting"),
    (r"monitoring|cloudwatch|splunk|observability", "monitoring"),
    (r"backup|database operations?|data migration", "database ops"),
)

_AWS_INFRA_BULLET_INTENTS = (
    "Infrastructure ownership",
    "IaC / Terraform",
    "Networking / VPC",
    "Security / IAM",
    "Database / DR",
    "Reliability / HA",
    "Cost / FinOps",
    "Automation / CI/CD",
)

_SKILLS_SOFT_ONLY_TERMS = frozenset(
    {
        "documentation",
        "collaboration",
        "leadership",
        "communication",
        "problem-solving",
        "problem solving",
        "mentoring",
        "teamwork",
        "agile",
        "scrum",
        "kanban",
        "methodologies",
    }
)

_GENERIC_BULLET_PHRASES = frozenset(
    {
        "cross-functional",
        "fostering a culture",
        "culture of innovation",
        "collaborated closely",
        "competitive advantage",
        "project satisfaction",
        "client workshops",
        "stakeholder engagement",
        "enhance functionality and user experience",
        "maintain competitive",
        "ongoing research of emerging",
        "operational efficiency",
        "business impact",
        "actionable insights",
        "fast-paced, innovative",
        "customer satisfaction",
        "significantly boosting",
        "enterprise software solutions",
        "high-availability enterprise",
        "secure enterprise",
        "improved customer satisfaction",
        "system uptime",
    }
)

_DUTY_BULLET_PHRASES = frozenset(
    {
        "design and maintain",
        "develop infrastructure as code",
        "build and optimize",
        "support kubernetes",
        "manage cloud infrastructure",
        "maintain enterprise-grade",
        "maintain ci/cd",
        "manage azure",
        "support containerized",
        "ensure reliable",
        "work closely with",
        "responsible for",
    }
)

_DUTY_BULLET_START_RE = re.compile(
    r"^(?:design(?:ed)?|maintain(?:ed)?|support(?:ed)?|manage(?:d)?|develop(?:ed)?|"
    r"build(?:t)?|operate(?:d)?|implement(?:ed)?)\s+(?:and\s+)?(?:maintain|support|design|"
    r"develop|build|optimize|manage|operate)?",
    re.I,
)

_EVIDENCED_GENERIC_SKILL_TERMS = frozenset(
    {
        "ci/cd",
        "iac",
        "gitops",
        "microservices",
        "automation",
        "monitoring",
        "linux",
        "containerization",
        "devops",
        "agile",
        "scrum",
    }
)

_SKILLS_DEVOPS_NOISE_TERMS = frozenset(
    {
        "wi-fi",
        "wifi",
        "tcp",
        "vmware",
        "sql server",
        "san storage",
        "san",
        "netapp",
        "harness",
        "jfrog",
        "servicenow",
        "active directory",
        "ip networking",
        "windows server",
        "oracle enterprise linux",
        "nosql",
        "bitbucket pipelines",
        "rest apis",
    }
)

_OWNERSHIP_BULLET_RE = re.compile(
    r"\b(?:chose|selected|defined|architected|led|owned|resolved|migrated|"
    r"standardized|designed|decided|introduced|built|implemented|debugged|deployed)\b",
    re.I,
)

_BANNED_BULLET_OPENERS_RE = re.compile(
    r"^(?:spearheaded|leveraged|utilized|facilitated|enhanced|achieved|improved|"
    r"optimized|accelerated|streamlined|spearhead|engineered|developed|created|established)\b",
    re.I,
)

_AI_RHYTHM_OPENERS_RE = re.compile(
    r"^(?:spearheaded|engineered|developed|created|established|automated|implemented)\b",
    re.I,
)

_BULLET_INTENTS = (
    "Architecture",
    "Business impact",
    "Reliability",
    "Ownership",
    "Scale",
    "Leadership",
    "Collaboration",
    "Implementation",
)

_CONSULTING_AI_LIFECYCLE_INTENTS = (
    "Architecture",
    "Production ownership",
    "Evaluation",
    "Observability",
    "Client collaboration",
    "Reliability",
    "Business impact",
    "Implementation",
)

_CONSULTING_AI_NARRATIVE_THREADS = (
    "Production AI",
    "Agentic workflows",
    "Retrieval",
    "Evals",
    "Observability",
    "Client delivery",
    "Iteration",
)

_ROLE_ARCHETYPE_TAXONOMIES: dict[str, list[str]] = {
    "consulting_ai_engineer": [
        "AI Engineering",
        "Backend & Data",
        "Cloud & Production",
        "Engineering Practices",
        "Evaluation & Observability",
        "Data Pipelines",
    ],
    "ai_engineer": [
        "AI Engineering",
        "Backend Systems",
        "Production AI",
        "Evaluation & Observability",
        "Cloud & Infrastructure",
        "Data Pipelines",
        "Engineering Practices",
    ],
    "devops": [
        "Cloud Platforms",
        "Infrastructure",
        "Containers",
        "CI/CD",
        "Monitoring",
        "Security",
    ],
    "aws_infrastructure_engineer": [
        "Cloud & Infrastructure",
        "Infrastructure as Code",
        "CI/CD & Automation",
        "Security & Operations",
        "Monitoring & Reliability",
        "Databases & Storage",
    ],
    "backend": [
        "Backend",
        "Distributed Systems",
        "Cloud",
        "Databases",
        "Messaging",
        "Testing",
    ],
    "java_backend": [
        "Backend Development",
        "Frameworks",
        "Databases",
        "Cloud & DevOps",
        "Engineering Practices",
    ],
    "fullstack": [
        "Frontend",
        "Backend",
        "Cloud",
        "Databases",
        "DevOps",
        "Engineering Practices",
    ],
}

_BANNED_SUMMARY_OPENINGS_RE = re.compile(
    r"^(?:results[\s-]?driven|dynamic|innovative|motivated|passionate|"
    r"highly[\s-]?motivated|detail[\s-]?oriented|proven track record)",
    re.I,
)

_BANNED_CORPORATE_PHRASES_RE = re.compile(
    r"\b(?:comprehensive|significantly enhancing|streamlining|facilitating|"
    r"synerg(?:y|ies)|leverag(?:e|ed|ing)|utiliz(?:e|ed|ing)|results[\s-]?driven)\b",
    re.I,
)

_FIRST_PERSON_SUMMARY_RE = re.compile(
    r"\b(?:I am|I'm|I have|I['']ve|my role|my experience|we built|our team)\b",
    re.I,
)

_SUMMARY_DOMAIN_COMPETENCIES = (
    "observability",
    "ownership",
    "architecture",
    "retrieval",
    "evaluation",
    "evals",
    "debugging",
    "deployment",
    "agentic",
    "microservices",
    "ci/cd",
    "leadership",
    "client communication",
    "end-to-end",
    "production",
    "scalability",
    "reliability",
    "performance",
    "security",
    "automation",
)

_BULLET_METRIC_ENDING_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|percent|x\b|\+)\.?\s*$",
    re.I,
)

_PREFERRED_BULLET_VERBS = (
    "Built, Designed, Introduced, Standardized, Migrated, Implemented, "
    "Debugged, Owned, Led, Created, Automated, Deployed"
)

_AI_ATS_TERMS = (
    "agentic workflows",
    "RAG",
    "retrieval pipelines",
    "MCP",
    "tool use",
    "tool-using LLMs",
    "structured outputs",
    "evals",
    "observability",
    "OpenTelemetry",
    "vector stores",
    "Pinecone",
    "LangChain",
    "OpenAI API",
    "FastAPI",
    "Redis",
    "Celery",
    "prompt engineering",
    "multi-agent orchestration",
    "model monitoring",
    "statistical analysis",
    "API integrations",
    "security protocols",
    "incident response",
    "cloud migrations",
    "database optimization",
    "Grafana",
    "Pydantic",
    "microservices",
    "production AI systems",
    "production debugging",
    "technical leadership",
    "client communication",
    "feedback loops",
    "business-critical workflows",
    "version control",
    "testing",
    "human review",
    "tool-using agents",
    "enterprise",
    "consulting",
    "MCP-based",
    "MCP orchestration",
    "function calling",
    "prompt engineering",
    "nontechnical clients",
    "strategists",
    "mentoring",
)

_GENERAL_SENIOR_AI_ATS_TERMS = (
    "Senior AI/ML Engineer",
    "production AI systems",
    "tool-using LLMs",
    "technical leadership",
    "client communication",
    "incident response",
    "production debugging",
    "feedback loops",
    "business-critical workflows",
    "security protocols",
    "version control",
    "testing",
    "enterprise",
    "client discovery",
    "code review",
    "problem-solving",
    "MCP",
    "tool use",
    "retrieval pipelines",
    "structured outputs",
    "consulting",
    "client-facing",
)


def _has_llm_agentic_stack(*texts: str) -> bool:
    combined = " ".join(t for t in texts if t).lower()
    return bool(
        re.search(
            r"\b(langchain|openai|llm|agentic|rag|retrieval|generative|multi-agent|pinecone|mcp|fastapi)\b",
            combined,
            re.I,
        )
    )


def _expand_inferred_ai_stack(*texts: str) -> list[str]:
    """Adjacent ATS terms for LLM/agentic profiles — used to maximize keyword coverage."""
    if not _has_llm_agentic_stack(*texts):
        return []
    return [
        "MCP",
        "MCP-based tool use",
        "tool use",
        "tool-using LLMs",
        "structured outputs",
        "retrieval pipelines",
        "agentic workflows",
        "multi-agent orchestration",
        "evals",
        "observability",
        "OpenTelemetry",
        "feedback loops",
        "business-critical workflows",
        "client communication",
        "technical leadership",
        "production debugging",
        "incident response",
        "security protocols",
        "human review",
        "Pinecone",
        "vector stores",
    ]


def build_mandatory_ai_keyword_line() -> str:
    return ", ".join(label for _, label in _MANDATORY_AI_KEYWORD_PATTERNS)


def build_mandatory_devops_keyword_line() -> str:
    return ", ".join(label for _, label in _MANDATORY_DEVOPS_KEYWORD_PATTERNS)


def _resolve_role_context(target_job_role: str, job_description: str) -> str:
    """Role label for summary/skills alignment — JD first, optional user override."""
    cleaned = sanitize_target_job_role(target_job_role)
    if cleaned:
        return cleaned
    return extract_jd_target_role_title(job_description) or ""


def _is_devops_role(target_job_role: str, job_description: str) -> bool:
    """DevOps detection — yield to AI/ML when the JD is primarily an AI engineering role."""
    if _is_ai_ml_role(target_job_role, job_description):
        blob = f"{_resolve_role_context(target_job_role, job_description)} {job_description[:4000]}"
        if _DEVOPS_ROLE_RE.search(blob) and not re.search(
            r"\b(agentic|mcp|tool[\s-]?use|retrieval|rag|evals?|llm|generative)\b",
            job_description[:3500],
            re.I,
        ):
            return True
        return False
    blob = f"{_resolve_role_context(target_job_role, job_description)} {job_description[:4000]}"
    return bool(_DEVOPS_ROLE_RE.search(blob))


def _has_devops_cloud_stack(*texts: str) -> bool:
    combined = " ".join(t for t in texts if t).lower()
    return bool(
        re.search(
            r"\b(azure|kubernetes|terraform|devops|github\s+actions|ci/?cd|docker|"
            r"helm|gitops|aks|gcp|aws)\b",
            combined,
            re.I,
        )
    )


def extract_jd_tool_phrases(job_description: str) -> list[str]:
    """Named tools/platforms from the JD for ATS weaving (multi-word phrases)."""
    jd = (job_description or "").strip()
    if not jd:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _JD_TOOL_PHRASE_RE.finditer(jd):
        term = re.sub(r"\s+", " ", match.group(0)).strip()
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


def _expand_inferred_devops_stack(skills: str, summary: str, job_description: str) -> list[str]:
    """JD-aligned DevOps ATS terms plus tools evidenced in the candidate profile."""
    if not _has_devops_cloud_stack(skills, summary, job_description):
        return list(extract_jd_tool_phrases(job_description))
    profile_text = f"{skills} {summary}"
    seen: set[str] = set()
    out: list[str] = []
    for term in list(extract_jd_tool_phrases(job_description)) + list(_DEVOPS_ATS_TERMS):
        key = term.lower()
        if key in seen:
            continue
        if key in (job_description or "").lower() or _term_appears_in_skills(term, profile_text):
            seen.add(key)
            out.append(term)
    return out


def _should_replace_skills_entirely(target_job_role: str, job_description: str) -> bool:
    """Skills tool lists are always replaced from the JD; category labels come from source layout."""
    return True


def _career_depth_tier(role_index: int, role_count: int) -> str:
    """Map employer index (0=oldest) to narrative depth tier."""
    if role_count <= 1:
        return "peak"
    if role_count == 2:
        return "peak" if role_index == 1 else "simple"
    if role_index == 0:
        return "simple"
    if role_index == role_count - 1:
        return "peak"
    return "intermediate"


def build_career_progression_experience_prompt(
    role_count: int,
    bullets_per_role: list[int],
    *,
    is_ai_role: bool = False,
    is_devops_role: bool = False,
    is_java_backend: bool = False,
    target_role: str = "",
) -> str:
    """
    Instruct the LLM to write experience as a believable career arc:
    oldest employer = simpler scope, newest = strongest JD match.
    """
    if role_count <= 0:
        return ""

    job_label = (target_role or "the target job").strip()
    lines = [
        "CAREER PROGRESSION — write experience oldest→newest so a recruiter believes the full timeline:",
        "- Bullets are grouped by employer in chronological order (do not mix companies).",
        "- Scope, tool depth, leadership, and JD alignment MUST increase over time.",
        "- Start from SOURCE bullets for each employer — rewrite them; do not ignore or replace with generic JD filler.",
        "- Never reuse the same bullet pattern or metric template across every employer.",
        "- Early roles simplify source accomplishments; the most recent role expands them with full JD depth.",
    ]

    tier_specs: dict[str, tuple[str, str, str, str]] = {
        "simple": (
            "SIMPLE (early career)",
            "Built, Implemented, Supported, Developed, Debugged",
            "single feature/module, bug fixes, code reviews, one component or service",
            "1–2 relevant tools; metrics as supporting evidence only (~15–20% of bullets); 12–18 words per bullet",
        ),
        "intermediate": (
            "INTERMEDIATE (growing ownership)",
            "Built, Designed, Migrated, Automated, Deployed, Owned",
            "modules or services end-to-end, integrations, performance wins, small team initiatives",
            "2–3 JD-relevant tools where truthful; ~25–35% bullets with quantified outcomes; 14–20 words per bullet",
        ),
        "peak": (
            f"PEAK (most recent — strongest fit for {job_label})",
            "Built, Designed, Led, Owned, Introduced, Standardized, Architected",
            "platform/system ownership, cross-team or client impact, production at scale, technical leadership",
            "JD-critical stack in bullets naturally; metrics support the method (~30–40% with numbers); 14–22 words per bullet",
        ),
    }

    if is_java_backend:
        tier_specs["simple"] = (
            tier_specs["simple"][0],
            tier_specs["simple"][1],
            "API endpoints, backend modules, database queries, debugging, unit tests, documentation",
            "Java or Python backend basics; REST; one database; ~15–20% metrics",
        )
        tier_specs["intermediate"] = (
            tier_specs["intermediate"][0],
            tier_specs["intermediate"][1],
            "REST services, database integration, microservice components, CI/CD participation, code reviews",
            "Java, REST APIs, SQL/PostgreSQL, Git, Docker where evidenced; ~25–35% metrics",
        )
        tier_specs["peak"] = (
            tier_specs["peak"][0],
            tier_specs["peak"][1],
            "scalable backend services, REST APIs, database design, SDLC, Agile collaboration, production debugging",
            "JD-critical Java/Spring/REST/SQL stack in bullets naturally; de-emphasize AI/LLM unless core to role; ~30–35% metrics",
        )
    elif is_ai_role:
        tier_specs["simple"] = (
            tier_specs["simple"][0],
            tier_specs["simple"][1],
            "API endpoints, data pipelines, model integration support, testing, documentation",
            "Python and one adjacent tool; avoid agentic/MCP/RAG leadership claims; ~15–20% metrics",
        )
        tier_specs["intermediate"] = (
            tier_specs["intermediate"][0],
            tier_specs["intermediate"][1],
            "ML features, retrieval pipelines, model deployment, monitoring hooks, API hardening",
            "Python, FastAPI, one LLM/RAG tool; growing production ownership; ~30–35% metrics",
        )
        tier_specs["peak"] = (
            tier_specs["peak"][0],
            tier_specs["peak"][1],
            "production AI end-to-end: agentic workflows, RAG, MCP tool use, evals, observability, client discovery",
            "MCP, structured outputs, multi-agent orchestration, production debugging; ~30–35% metric-ending bullets; vary bullet intents",
        )
    elif is_devops_role:
        tier_specs["simple"] = (
            tier_specs["simple"][0],
            tier_specs["simple"][1],
            "scripting, Linux admin, CI job maintenance, deployment support, monitoring dashboards",
            "Bash/Python, one cloud or CI tool; no platform-architect claims; ~15–20% metrics",
        )
        tier_specs["intermediate"] = (
            tier_specs["intermediate"][0],
            tier_specs["intermediate"][1],
            "IaC modules, containerized services, pipeline improvements, incident fixes, environment automation",
            "Terraform or cloud CLI, Docker/K8s basics, CI/CD; ~30–40% metrics",
        )
        tier_specs["peak"] = (
            tier_specs["peak"][0],
            tier_specs["peak"][1],
            "platform reliability, GitOps, multi-env IaC, SRE/incident response, security and cost at scale",
            "full JD DevOps/cloud stack; GitHub Actions, Azure/AWS, Terraform, Kubernetes; ~30–35% metric-ending bullets",
        )

    for idx in range(role_count):
        tier = _career_depth_tier(idx, role_count)
        label, verbs, scope, tools = tier_specs[tier]
        ordinal = idx + 1
        position = "oldest" if idx == 0 else ("newest" if idx == role_count - 1 else "middle")
        bullet_floor = bullets_per_role[idx] if idx < len(bullets_per_role) else 6
        lines.append(
            f"- Employer {ordinal}/{role_count} ({position}): {label} — min {bullet_floor} bullets. "
            f"Verbs: {verbs}. Scope: {scope}. Tools/metrics: {tools}."
        )

    return "\n".join(lines) + "\n"


def build_role_prompt_addon(
    *,
    is_ai_role: bool,
    is_devops_role: bool,
    has_llm_stack: bool,
    has_devops_stack: bool,
    jd_tools: list[str],
    source_metrics: list[str],
    mandatory_kw: str,
    is_consulting_ai: bool = False,
    is_aws_infrastructure: bool = False,
    jd_phrases: list[str] | None = None,
) -> str:
    lines: list[str] = []
    if source_metrics:
        lines.append(
            "- SOURCE_METRICS (reuse these truthful quantified outcomes in bullets when they fit the JD): "
            + "; ".join(source_metrics[:10])
        )
    if jd_tools:
        lines.append(
            "- JD_CRITICAL_TOOLS (place strategically — NOT repeated in summary, skills, AND every bullet): "
            + ", ".join(jd_tools[:18])
        )
        lines.append(
            "- KEYWORD PLACEMENT: summary = identity + domain narrative; experience = tools in context "
            "(e.g. 'Built MCP agents…'); skills = plain tool list. Each critical tool max 2 mentions total."
        )
    lines.append(
        "- EDIT ONLY 3 SECTIONS: (1) professional_summary — full rewrite from JD; "
        "(2) professional_experience — rewrite bullets per employer from SOURCE accomplishments; "
        "(3) skills — new JD tool lists under each source category label. "
        "Frozen: contact, education, other."
    )
    lines.append(
        "- Experience must read as a believable career arc grounded in SOURCE bullets: oldest role = simpler; "
        "middle roles = growing ownership; most recent role = deepest detail and strongest JD match."
    )
    if is_devops_role:
        lines.append(
            "- DEVOPS/CLOUD: classify the dominant role archetype from the JD (e.g. AWS Infrastructure "
            "Platform Engineer) — not generic DevOps keyword matching."
        )
        lines.append(
            "- Map JD responsibilities oldest→newest; most recent role = strongest infrastructure ownership match."
        )
        lines.append(
            "- Skills: use role-specific category labels; every category must list tools — no empty lines."
        )
        if is_aws_infrastructure:
            lines.append(
                "- AWS role: emphasize VPC, IAM, RDS/Aurora, Terraform modules, DR, cost reporting — "
                "deprioritize GCP/Kubernetes unless in source."
            )
        if has_devops_stack:
            lines.append(f"- ATS KEYWORDS (JD-aligned): {mandatory_kw}.")
    if is_ai_role:
        if is_consulting_ai:
            lines.append(
                "- CONSULTING APPLIED AI (Board-of-Innovation caliber): each bullet rewrites a SOURCE accomplishment "
                "into long-form, recruiter-believable prose with JD phrases woven in — not short metric-only lines."
            )
            if jd_phrases:
                lines.append(
                    "- JD PHRASES to distribute across experience (heaviest in most recent role): "
                    + ", ".join(jd_phrases[:16])
                )
        lines.append(
            "- APPLIED AI / CONSULTING ROLE: read like you OWNED production AI systems end-to-end — not just 'built AI'. "
            "Emphasize client discovery, architecture, deployment, production debugging, evals, observability, "
            "and translating business problems for nontechnical clients."
        )
        lines.append(
            "- Summary (2–3 sentences): (1) role + years + Python/FastAPI + agentic workflows, RAG, tool-using LLMs, "
            "structured outputs, evals, observability; (2) own full path from client discovery through deployment "
            "and incident debugging; (3) judgment on accuracy, latency, cost, security, maintainability + client communication."
        )
        lines.append(
            "- Bullets COMBINE ownership language WITH quantified outcomes (~30–40% with %) — "
            "MCP, structured outputs, production debugging, client collaboration where source supports."
        )
        lines.append(
            "- Skills list MCP, tool use, structured outputs, evals once — do not repeat every AI term in summary too."
        )
        lines.append(
            "- FORBIDDEN for AI roles: emphasizing Azure, Kubernetes, GitHub Actions unless they appear in the JD."
        )
        if has_llm_stack:
            lines.append(f"- MANDATORY AI KEYWORDS across summary + bullets + skills: {mandatory_kw}.")
    return "\n".join(lines) + ("\n" if lines else "")


def _tailor_max_tokens() -> int:
    raw = os.getenv("OPENAI_TAILOR_MAX_TOKENS", "16384").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 8192
    return max(2048, min(n, 32000))


def _tailor_temperature() -> float:
    raw = os.getenv("OPENAI_TAILOR_TEMPERATURE", "0.62").strip()
    try:
        t = float(raw)
    except ValueError:
        t = 0.62
    return max(0.0, min(t, 1.5))


STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "as", "by",
    "with", "from", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "shall",
    "can", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
    "what", "which", "who", "whom", "whose", "where", "when", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "just", "also", "into", "through",
    "during", "before", "after", "above", "below", "between", "under", "again", "further",
    "then", "once", "here", "there", "any", "if", "about", "our", "your", "their", "my",
    "me", "us", "them", "his", "her", "its", "myself", "yourself", "himself", "herself",
    "itself", "ourselves", "themselves", "within", "across", "including", "etc", "eg",
    "e.g", "i.e", "years", "year", "experience", "work", "team", "role", "job", "position",
    "company", "opportunity", "looking", "seeking", "candidate", "responsibilities",
    "requirements", "skills", "ability", "able", "strong", "excellent", "good", "great",
    "build", "building", "using", "use", "used", "including", "based", "related",
}


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s+#./-]", " ", text, flags=re.UNICODE)
    return [w for w in text.split() if len(w) > 2]


def extract_keywords(job_description: str, top_k: int = 28) -> list[str]:
    tokens = _tokenize(job_description)
    scored: Counter[str] = Counter()
    for raw in tokens:
        w = raw.strip(".-/")
        if not w or w in STOPWORDS:
            continue
        if w.isdigit():
            continue
        scored[w] += 2 if any(c.isdigit() for c in raw) else 1
    phrases = re.findall(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
        job_description,
    )
    for p in phrases:
        key = p.strip().lower()
        if len(key) < 4:
            continue
        parts = key.split()
        if all(len(x) > 2 for x in parts):
            scored[key] += 3
    out: list[str] = []
    seen: set[str] = set()
    for term, _ in scored.most_common(top_k * 2):
        if term in seen:
            continue
        seen.add(term)
        out.append(term)
        if len(out) >= top_k:
            break
    return out


def _is_ai_ml_role(target_job_role: str, job_description: str) -> bool:
    return bool(
        _AI_ROLE_RE.search(
            f"{_resolve_role_context(target_job_role, job_description)} {job_description[:3000]}"
        )
    )


def _is_applied_ai_consulting_jd(target_job_role: str, job_description: str) -> bool:
    """Applied AI in a consulting / client-delivery context (e.g. Board of Innovation)."""
    if not _is_ai_ml_role(target_job_role, job_description):
        return False
    jd = (job_description or "")[:8000]
    consulting_signals = len(_APPLIED_AI_CONSULTING_JD_RE.findall(jd))
    production_signals = len(
        re.findall(
            r"\bproduction[\s-]?(?:grade|ready|systems?)|real[\s-]world|enterprise\s+client",
            jd,
            re.I,
        )
    )
    return consulting_signals >= 2 and production_signals >= 1


def extract_jd_responsibility_phrases(job_description: str, *, limit: int = 24) -> list[str]:
    """Multi-word JD responsibility phrases to weave into experience (ATS + recruiter scan)."""
    jd = (job_description or "").strip()
    if not jd:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _JD_RESPONSIBILITY_PHRASE_RE.finditer(jd):
        phrase = re.sub(r"\s+", " ", match.group(0)).strip(" ,.;")
        key = phrase.lower()
        if len(phrase) < 4 or key in seen:
            continue
        seen.add(key)
        out.append(phrase)
        if len(out) >= limit:
            break
    return out


def build_applied_ai_consulting_style_prompt(
    *,
    jd_phrases: list[str],
    source_metrics: list[str],
    target_role: str = "",
) -> str:
    """
    High-quality applied-AI consulting resume style (production AI + client delivery + ATS).
    """
    job = (target_role or "AI Engineer").strip()
    phrase_line = ", ".join(jd_phrases[:20]) if jd_phrases else (
        "agentic workflows, tool-using LLMs, retrieval pipelines, MCP, structured outputs, evals, "
        "observability, feedback loops, client communication"
    )
    metrics_line = "; ".join(source_metrics[:8]) if source_metrics else ""

    lines = [
        "APPLIED AI CONSULTING STYLE (match this quality — rewrite SOURCE bullets, do not copy verbatim):",
        f"- Target: {job} at a consulting firm shipping production AI for enterprise clients.",
        f"- Weave these JD responsibility phrases across bullets (especially the most recent role): {phrase_line}.",
        "- BULLET FORMULA (most recent role): match the assigned bullet intent — NOT the same Verb→Tech→Metric template every line.",
        "- Bullets should be concise (14–22 words) — method and ownership first, metrics as supporting evidence.",
        "- Mix bullet intents (Architecture, Production ownership, Evaluation, Observability, Client collaboration); "
        "only ~30–40% bullets end with quantified outcomes.",
        "- Peak role MUST tell the whole AI lifecycle story: architecture, evals, observability, debugging, iteration, "
        "and client translation — not only 'Built X, improved Y by Z%'.",
        "- Include 2–3 OWNERSHIP bullets in the most recent role (start with Owned/Led/Introduced), e.g.: "
        "'Owned production RAG architecture, evaluation, and observability using LangChain, Pinecone, FastAPI, and OpenTelemetry.'",
        "- Cover lifecycle themes where source supports: MCP/tool use, structured outputs, evals, testing, feedback loops, "
        "client discovery, production debugging.",
        "- When SOURCE shows RAG, multi-agent, OpenAI, LangChain, or FastAPI services, you MAY truthfully reframe as: "
        "MCP-based tool use, tool-using LLMs, structured outputs, evals, retrieval pipelines, agentic workflows.",
        "- Most recent role MUST include: MCP, evals, observability, feedback loops, client/strategist collaboration, "
        "production debugging, technical leadership, CI/CD or version control hygiene.",
        "- Middle role: growing ML/platform ownership, evals, CI/CD, microservices — fewer consulting phrases than peak.",
        "- Oldest role: foundational software engineering (APIs, databases, Docker, migrations) — NO agentic/MCP claims.",
    ]
    if metrics_line:
        lines.append(f"- SOURCE metrics to preserve when rewriting: {metrics_line}.")
    lines.extend(
        [
            "- EXAMPLE peak-role patterns (adapt from SOURCE facts — do not paste verbatim):",
            '  "Provided technical leadership for Python agentic workflows, turning ambiguous client needs into '
            'deployable services with clearer ownership and faster handoffs."',
            '  "Built retrieval pipelines with LangChain, Pinecone, and structured outputs for production Q&A."',
            '  "Introduced MCP-based tool use and structured outputs, pairing API integrations with security protocols '
            'during early production rollouts."',
            '  "Debugged production incidents using OpenTelemetry and Redis, then strengthened observability, testing, '
            'and recovery procedures during outages."',
            '  "Worked directly with strategists and designers, translating ambiguous client problems into retrieval '
            'pipelines and maintainable delivery plans."',
        ]
    )
    return "\n".join(lines) + "\n"


def _extract_profile_tech_stack(*texts: str) -> list[str]:
    """Technologies evidenced in profile/skills (not experience bullets)."""
    seen: set[str] = set()
    out: list[str] = []
    combined = " ".join(t for t in texts if t)
    for term in _AI_ATS_TERMS:
        if re.search(r"(?<![\w\-./+#])" + re.escape(term) + r"(?![\w\-./+#])", combined, re.I):
            key = term.lower()
            if key not in seen:
                seen.add(key)
                out.append(term)
    for match in _NAMED_TECH_RE.finditer(combined):
        term = match.group(0)
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


def _count_token_evidence(token: str, *texts: str) -> int:
    """How often a skill/term appears across source resume sections."""
    token = (token or "").strip()
    if len(token) < 2:
        return 0
    total = 0
    for text in texts:
        if not text:
            continue
        if re.match(r"^[\w\-./+#]+$", token):
            total += len(
                re.findall(
                    r"(?<![\w\-./+#])" + re.escape(token) + r"(?![\w\-./+#])",
                    text,
                    re.I,
                )
            )
        else:
            total += len(re.findall(re.escape(token), text, re.I))
    return total


def _collect_evidence_candidate_tokens(text: str) -> list[str]:
    """Extract short skill/tech tokens from resume text — not full bullet sentences."""
    tokens: list[str] = []
    for raw_line in (text or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(rf"^[{_BULLET_CHARS}]\s*", "", line)
        if re.match(r"^[^:]+:\s*\S", line[:70]):
            tokens.extend(_parse_skill_tokens(line))
        tokens.extend(_NAMED_TECH_RE.findall(line))
    return tokens


def build_candidate_evidence_map(*source_texts: str, limit: int = 28) -> dict[str, int]:
    """
    Evidence scores for skills/terms found in the source resume.
    Used to avoid promoting technologies that only appear once.
    """
    candidates: list[str] = []
    for text in source_texts:
        if not text:
            continue
        candidates.extend(_collect_evidence_candidate_tokens(text))
        lower = text.lower()
        for term in _SUMMARY_DOMAIN_COMPETENCIES:
            if term in lower:
                candidates.append(term)
    scored: dict[str, int] = {}
    canonical: dict[str, str] = {}
    for raw in candidates:
        token = raw.strip()
        if len(token) < 2 or len(token) > 40 or len(token.split()) > 5:
            continue
        key = token.lower()
        if key not in canonical:
            canonical[key] = token
        scored[key] = max(scored.get(key, 0), _count_token_evidence(token, *source_texts))
    ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
    return {canonical[k]: v for k, v in ranked[:limit] if v > 0}


def format_candidate_evidence_for_prompt(
    evidence: dict[str, int],
    jd_tools: list[str] | None = None,
) -> str:
    """Prompt block: evidence map + which JD tools are safe to promote."""
    if not evidence:
        return ""
    lines = [
        "CANDIDATE EVIDENCE MAP (promote only what is defensible from source — not the JD alone):",
    ]
    for term, score in list(evidence.items())[:18]:
        tier = "strong" if score >= 3 else ("ok" if score >= 2 else "weak")
        lines.append(f"  - {term}: {score} mention(s) [{tier}]")
    if jd_tools:
        evidence_lower = {k.lower(): v for k, v in evidence.items()}
        promotable: list[str] = []
        weak: list[str] = []
        for tool in jd_tools[:14]:
            score = evidence.get(tool, evidence_lower.get(tool.lower(), 0))
            if score >= 2:
                promotable.append(tool)
            elif score == 1:
                weak.append(tool)
        cautious = [
            t for t in jd_tools[:14]
            if evidence_lower.get(t.lower(), 0) == 0
        ]
        if promotable:
            lines.append(f"PROMOTE (2+ source mentions): {', '.join(promotable[:10])}")
        if weak:
            lines.append(
                f"WEAK evidence (1 mention — must appear in an experience bullet): {', '.join(weak[:8])}"
            )
        if cautious:
            lines.append(
                f"DO NOT add to skills/summary unless demonstrated in a bullet: {', '.join(cautious[:8])}"
            )
    lines.append(
        "Rule: never introduce a technology in summary or skills unless at least one experience bullet supports it."
    )
    return "\n".join(lines) + "\n"


def build_jd_stage1_analysis_prompt(job_description: str, *, target_job_role: str = "") -> str:
    """Stage 1 — extract JD requirements before writing (embedded in single LLM call)."""
    jd = (job_description or "").strip()
    if not jd:
        return ""
    priority = _extract_jd_priority_text(jd) or jd
    required = extract_jd_tool_phrases(jd)[:10]
    preferred = extract_keywords(priority, top_k=12)
    responsibilities = extract_jd_responsibility_phrases(jd)[:8]
    role = (target_job_role or extract_jd_target_role_title(jd) or "target role").strip()
    culture_hits = [
        term
        for term in ("ownership", "collaboration", "innovation", "learning", "impact", "agile", "quality")
        if re.search(rf"\b{re.escape(term)}\b", jd, re.I)
    ]
    return (
        "STAGE 1 — JOB ANALYSIS (reason about this BEFORE writing the resume in Stage 2):\n"
        f"- Target role: {role}\n"
        f"- Required / must-have tools: {', '.join(required) if required else 'see JD'}\n"
        f"- Preferred skills: {', '.join(preferred[:10]) if preferred else 'see JD'}\n"
        f"- Core responsibilities: {', '.join(responsibilities[:6]) if responsibilities else 'see JD'}\n"
        f"- Culture / values signals: {', '.join(culture_hits) if culture_hits else 'none explicit'}\n"
        "STAGE 2 — Rewrite summary, experience, skills using Stage 1 + candidate evidence only.\n"
    )


_JAVA_BACKEND_JD_RE = re.compile(
    r"\b(?:java\b|spring boot|spring framework|\bspring\b|hibernate|jpa\b|maven|gradle|"
    r"junit|rest apis?|microservices?|sql\b|postgresql|mysql)\b",
    re.I,
)

_JAVA_BACKEND_NARRATIVE = (
    "Java",
    "Spring",
    "REST APIs",
    "Microservices",
    "Databases",
    "Cloud",
    "CI/CD",
)

_AI_PROFILE_TERMS = frozenset(
    {
        "langchain", "langgraph", "rag", "llm", "openai", "mcp", "agentic",
        "generative ai", "pinecone", "prompt engineering", "mlops", "multi-agent",
        "retrieval", "evals", "fastapi",
    }
)

_JAVA_BACKEND_TERMS = frozenset(
    {
        "java", "spring", "spring boot", "hibernate", "jpa", "rest", "rest api",
        "maven", "gradle", "junit", "postgresql", "mysql", "sql", "microservices",
        "docker", "kubernetes", "git", "ci/cd", "agile", "sdlc",
    }
)

_AI_DEEMPHASIS_DEFAULT = (
    "LLMs", "RAG", "OpenAI", "LangChain", "LangGraph", "MCP", "agentic workflows",
    "Generative AI", "multi-agent orchestration", "prompt engineering",
)


@dataclass
class TailoringStrategy:
    """Internal plan: target role vs candidate profile — drives pivot aggressiveness."""
    jd_archetype: str
    candidate_archetype: str
    compatibility: float
    mode: str  # full | moderate | conservative
    primary_story: str
    secondary_story: str
    de_emphasize: list[str]
    promote: list[str]
    jd_role_title: str = ""
    summary_angle: str = ""
    experience_guidance: str = ""
    skills_categories: list[str] = field(default_factory=list)
    bullet_priorities: list[str] = field(default_factory=list)


def is_java_backend_jd(target_job_role: str, job_description: str) -> bool:
    """JD is primarily Java/Spring backend — not AI/ML."""
    blob = f"{target_job_role} {job_description}"
    java_hits = len(_JAVA_BACKEND_JD_RE.findall(blob))
    ai_hits = len(_AI_ROLE_RE.findall(job_description[:5000]))
    return java_hits >= 3 and java_hits >= ai_hits + 1


def is_jd_ai_focused(target_job_role: str, job_description: str) -> bool:
    """True only when the JOB (not the candidate) is AI/ML-focused."""
    if is_java_backend_jd(target_job_role, job_description):
        return False
    return _is_ai_ml_role(target_job_role, job_description)


def detect_jd_role_archetype(
    target_job_role: str,
    job_description: str,
    *,
    is_consulting_ai: bool = False,
    is_aws_infrastructure: bool = False,
) -> str:
    """Classify the target job — drives skills taxonomy and narrative (JD-first)."""
    if is_consulting_ai:
        return "consulting_ai_engineer"
    if is_aws_infrastructure:
        return "aws_infrastructure_engineer"
    if is_java_backend_jd(target_job_role, job_description):
        return "java_backend"
    if _is_devops_role(target_job_role, job_description):
        return "devops"
    if _is_ai_ml_role(target_job_role, job_description):
        return "ai_engineer"
    combined = f"{target_job_role} {job_description}".lower()
    if re.search(r"full[\s-]?stack", combined):
        return "fullstack"
    if re.search(r"\bbackend\b|\bapi engineer\b|\bmicroservice", combined):
        return "backend"
    return "generic"


def detect_candidate_archetype(
    parsed: ParsedResume,
    evidence_map: dict[str, int],
) -> str:
    """Classify the candidate's primary profile from source evidence."""
    combined = " ".join(
        t
        for t in (
            parsed.skills,
            parsed.professional_summary,
            parsed.professional_experience,
        )
        if t
    ).lower()
    ai_score = sum(
        1 for term in _AI_PROFILE_TERMS
        if term in combined or any(term in k.lower() for k in evidence_map)
    )
    java_score = sum(
        1 for term in _JAVA_BACKEND_TERMS
        if re.search(rf"(?<![\w\-./+#]){re.escape(term)}(?![\w\-./+#])", combined)
    )
    devops_score = len(_DEVOPS_ROLE_RE.findall(combined))
    if ai_score >= 4 and ai_score > java_score + 2:
        return "ai_engineer"
    if java_score >= 3 and java_score >= ai_score:
        return "java_backend"
    if devops_score >= 2:
        return "devops"
    if java_score >= 2:
        return "backend_engineer"
    if ai_score >= 2:
        return "ai_engineer"
    return "software_engineer"


def _archetype_overlap_score(jd_archetype: str, candidate_archetype: str) -> float:
    if jd_archetype == candidate_archetype:
        return 1.0
    pairs: dict[tuple[str, str], float] = {
        ("java_backend", "ai_engineer"): 0.55,
        ("java_backend", "backend_engineer"): 0.82,
        ("java_backend", "software_engineer"): 0.65,
        ("backend", "ai_engineer"): 0.58,
        ("backend", "backend_engineer"): 0.88,
        ("ai_engineer", "backend_engineer"): 0.62,
        ("devops", "ai_engineer"): 0.52,
        ("aws_infrastructure_engineer", "devops"): 0.85,
        ("fullstack", "ai_engineer"): 0.68,
    }
    return pairs.get((jd_archetype, candidate_archetype), pairs.get((candidate_archetype, jd_archetype), 0.45))


def compute_role_compatibility(
    jd_archetype: str,
    candidate_archetype: str,
    evidence_map: dict[str, int],
    job_description: str,
    *,
    jd_tools: list[str] | None = None,
) -> float:
    """0–1 score: how well candidate evidence aligns with target role."""
    base = _archetype_overlap_score(jd_archetype, candidate_archetype)
    tools = jd_tools or extract_jd_tool_phrases(job_description)
    evidence_lower = {k.lower(): v for k, v in evidence_map.items()}
    if not tools:
        return round(min(0.95, max(0.25, base)), 2)
    supported = 0
    for tool in tools[:15]:
        score = evidence_lower.get(tool.lower(), 0)
        if score == 0:
            for key, val in evidence_lower.items():
                if tool.lower() in key or key in tool.lower():
                    score = max(score, val)
        if score >= 1:
            supported += 1
    support_ratio = supported / max(1, min(len(tools), 15))
    adjusted = base * 0.55 + support_ratio * 0.45
    if jd_archetype == "java_backend" and candidate_archetype == "ai_engineer":
        java_ev = max(
            evidence_lower.get("java", 0),
            evidence_map.get("Java", 0),
        )
        if java_ev >= 2:
            adjusted = max(adjusted, 0.72)
        elif java_ev >= 1:
            adjusted = max(adjusted, 0.58)
        else:
            adjusted = min(adjusted, 0.48)
    return round(min(0.95, max(0.2, adjusted)), 2)


def build_tailoring_strategy(
    parsed: ParsedResume,
    job_description: str,
    evidence_map: dict[str, int],
    *,
    target_job_role: str = "",
    is_consulting_ai: bool = False,
    is_aws_infrastructure: bool = False,
) -> TailoringStrategy:
    """Role-aware tailoring plan before writing."""
    jd_arch = detect_jd_role_archetype(
        target_job_role,
        job_description,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infrastructure,
    )
    cand_arch = detect_candidate_archetype(parsed, evidence_map)
    jd_tools = extract_jd_tool_phrases(job_description)
    compatibility = compute_role_compatibility(
        jd_arch, cand_arch, evidence_map, job_description, jd_tools=jd_tools
    )
    evidence_lower = {k.lower(): v for k, v in evidence_map.items()}

    def _evidenced(tool: str) -> bool:
        return evidence_lower.get(tool.lower(), 0) >= 1

    promote = [t for t in jd_tools if _evidenced(t)][:10]
    for tool in jd_tools[:15]:
        if tool not in promote and evidence_lower.get(tool.lower(), 0) >= 2:
            promote.append(tool)
    if jd_arch == "java_backend":
        for term in ("Java", "REST", "REST APIs", "Python", "SQL", "PostgreSQL", "Git", "Docker", "CI/CD"):
            if _evidenced(term) and term not in promote:
                promote.append(term)
    promote = list(dict.fromkeys(promote))[:12]

    de_emphasize: list[str] = []
    if jd_arch == "java_backend" and cand_arch in ("ai_engineer", "fullstack"):
        de_emphasize = list(_AI_DEEMPHASIS_DEFAULT)
    elif jd_arch == "devops" and cand_arch == "ai_engineer":
        de_emphasize = ["RAG", "LangChain", "OpenAI", "MCP", "Generative AI"]
    elif compatibility < 0.55:
        de_emphasize = [t for t in jd_tools if not _evidenced(t)][:8]

    if compatibility >= 0.82:
        mode = "full"
    elif compatibility >= 0.55:
        mode = "moderate"
    else:
        mode = "conservative"

    primary_story = "Backend engineering"
    secondary_story = "Cloud and DevOps"
    if jd_arch == "java_backend":
        primary_story = "Java backend engineering"
        secondary_story = "REST APIs, databases, and CI/CD"
    elif jd_arch == "ai_engineer":
        primary_story = "Production AI engineering"
        secondary_story = "Backend and cloud delivery"
    elif jd_arch == "devops":
        primary_story = "Platform and infrastructure"
        secondary_story = "Reliability and automation"
    elif jd_arch == "aws_infrastructure_engineer":
        primary_story = "AWS infrastructure ownership"
        secondary_story = "IaC, networking, and DR"

    role_title = (target_job_role or extract_jd_target_role_title(job_description) or "").strip()
    return TailoringStrategy(
        jd_archetype=jd_arch,
        candidate_archetype=cand_arch,
        compatibility=compatibility,
        mode=mode,
        primary_story=primary_story,
        secondary_story=secondary_story,
        de_emphasize=de_emphasize,
        promote=promote,
        jd_role_title=role_title,
    )


def build_tailoring_strategy_prompt(strategy: TailoringStrategy) -> str:
    """Feed internal tailoring strategy into the LLM before writing."""
    lines = [
        "TAILORING STRATEGY (complete before writing — optimize for TARGET ROLE, not candidate's strongest profile):",
        f"- JD role archetype: {strategy.jd_archetype.replace('_', ' ')}",
        f"- Candidate archetype: {strategy.candidate_archetype.replace('_', ' ')}",
        f"- Compatibility: {int(strategy.compatibility * 100)}%",
        f"- Tailoring mode: {strategy.mode}",
        f"- Primary story: {strategy.primary_story}",
        f"- Secondary story: {strategy.secondary_story}",
    ]
    if strategy.promote:
        lines.append(f"- PROMOTE (evidence-backed + JD-critical): {', '.join(strategy.promote[:12])}")
    if strategy.de_emphasize:
        lines.append(
            f"- DE-EMPHASIZE (do not lead summary/skills/experience with these): "
            f"{', '.join(strategy.de_emphasize[:10])}"
        )
    if strategy.mode == "moderate":
        lines.append(
            "- MODERATE PIVOT: reorder and emphasize transferable backend/cloud skills; "
            "do NOT pretend the candidate is primarily a different specialty. "
            "Do NOT invent tools with zero source evidence (e.g. Spring Boot if absent)."
        )
    elif strategy.mode == "conservative":
        lines.append(
            "- CONSERVATIVE: emphasize overlapping skills only; keep candidate identity truthful; "
            "minimal keyword injection."
        )
    else:
        lines.append("- FULL TAILOR: strong alignment — tailor aggressively to the JD.")
    if strategy.jd_archetype == "java_backend":
        lines.append(
            "- Summary must NOT open with 'AI/ML Engineer' or lead with LLMs/RAG. "
            "Lead with Senior Software/Backend Engineer + Java, REST, microservices, CI/CD where evidenced."
        )
        lines.append(
            "- Experience: lead with Java/REST/database bullets; move AI/ML bullets later or reframe as "
            "supporting backend work only where truthful."
        )
        lines.append(
            "- Skills taxonomy: Backend Development, Frameworks, Databases, Cloud & DevOps, Engineering Practices — "
            "NOT Generative AI & LLM as the first category."
        )
    if strategy.summary_angle:
        lines.append(f"- Summary angle: {strategy.summary_angle}")
    if strategy.experience_guidance:
        lines.append(f"- Experience guidance: {strategy.experience_guidance}")
    if strategy.skills_categories:
        lines.append(f"- Skills category order: {', '.join(strategy.skills_categories[:8])}")
    if strategy.bullet_priorities:
        lines.append(f"- Bullet priorities (most recent role first): {', '.join(strategy.bullet_priorities[:8])}")
    return "\n".join(lines) + "\n"


def build_jd_weighted_tools_prompt(job_description: str, evidence_map: dict[str, int]) -> str:
    """Weight JD tools by importance vs candidate evidence — don't treat all keywords equally."""
    priority = _extract_jd_priority_text(job_description) or job_description
    tools = extract_jd_tool_phrases(job_description)[:15]
    if not tools:
        return ""
    evidence_lower = {k.lower(): v for k, v in evidence_map.items()}
    lines = ["JD TOOL WEIGHTS (promote high-weight + evidenced; never invent zero-evidence tools):"]
    for idx, tool in enumerate(tools[:12]):
        weight = max(60, 100 - idx * 5)
        if _score_skill_token_against_jd(tool, priority, job_description) >= 4:
            weight = min(100, weight + 10)
        ev = evidence_lower.get(tool.lower(), 0)
        if ev >= 2:
            action = "PROMOTE in summary/skills/peak-role bullets"
        elif ev == 1:
            action = "one experience bullet only"
        else:
            action = "DO NOT add — no source evidence"
        lines.append(f"  - {tool} (weight {weight}, evidence {ev}): {action}")
    return "\n".join(lines) + "\n"


def detect_primary_cloud_provider(job_description: str) -> str:
    """Dominant cloud in the JD — used to avoid Azure/GCP over-emphasis on AWS roles."""
    jd = (job_description or "").lower()
    aws = len(_AWS_INFRA_JD_RE.findall(jd))
    azure = len(re.findall(r"\bazure\b|\baks\b|application insights|arm templates?", jd))
    gcp = len(re.findall(r"\bgcp\b|google cloud|\bgke\b|cloud run|firestore", jd))
    if aws >= max(azure, gcp) and aws >= 2:
        return "aws"
    if azure >= max(aws, gcp) and azure >= 2:
        return "azure"
    if gcp >= max(aws, azure) and gcp >= 2:
        return "gcp"
    return "mixed"


def is_aws_infrastructure_jd(target_job_role: str, job_description: str) -> bool:
    """AWS infrastructure/platform ownership role (e.g. Snapsheet-style Senior DevOps)."""
    if not _is_devops_role(target_job_role, job_description):
        return False
    return detect_primary_cloud_provider(job_description) == "aws"


def build_mandatory_devops_keyword_line_for_jd(job_description: str) -> str:
    """Cloud-aware mandatory DevOps keywords for prompts."""
    cloud = detect_primary_cloud_provider(job_description)
    if cloud == "aws":
        return ", ".join(label for _, label in _AWS_MANDATORY_KEYWORD_PATTERNS)
    return build_mandatory_devops_keyword_line()


def build_devops_cloud_priority_prompt(job_description: str) -> str:
    """Priority tiers so the model emphasizes the right stack for this JD."""
    cloud = detect_primary_cloud_provider(job_description)
    lines = [
        "DEVOPS CLOUD PRIORITY (match the JD — not generic DevOps keyword stuffing):",
    ]
    if cloud == "aws":
        lines.extend(
            [
                "- Classify role as: AWS Infrastructure Platform Engineer / Senior DevOps Engineer.",
                "- Core (emphasize): AWS, Terraform, VPC/networking, IAM, RDS/Aurora, HA/DR, security hardening.",
                "- Secondary: Docker, ECS/Fargate, Lambda, CI/CD, Python/Bash scripting, GitHub admin.",
                "- Supportive: SRE collaboration, observability, cost/FinOps, documentation, runbooks.",
                "- Lower priority (only if in source): GCP, Kubernetes, generic Agile buzzwords.",
                "- Summary MUST address: AWS infrastructure ownership, VPC, IAM, RDS/Aurora, Terraform modules, "
                "disaster recovery, cost reporting, database operations — when supported by source.",
            ]
        )
    elif cloud == "azure":
        lines.extend(
            [
                "- Classify role as: Azure Platform / DevOps Engineer.",
                "- Core: Azure, Terraform/ARM, AKS, CI/CD, GitHub Actions/Azure DevOps, IAM/RBAC, monitoring.",
                "- Lower priority: GCP, unrelated cloud terms unless in JD.",
            ]
        )
    else:
        lines.append("- Match the dominant cloud and platform tools named in the JD requirements section.")
    lines.append("- Prefer role-specific infrastructure language over generic DevOps language.")
    lines.append("- Do not invent experience. Deprioritize tools not in the JD or source resume.")
    return "\n".join(lines) + "\n"


def build_devops_validation_checklist_prompt() -> str:
    """Pre-output validation the model should mentally run before returning JSON."""
    return (
        "PRE-OUTPUT VALIDATION (check before returning JSON):\n"
        "1. No empty skill categories — every category must list tools.\n"
        "2. Top 10 JD keywords appear in summary/skills/experience and are supported by source bullets.\n"
        "3. No duplicate or near-duplicate accomplishment bullets.\n"
        "4. Resume is not over-optimized for the wrong cloud (e.g. GCP/K8s-heavy when JD is AWS).\n"
        "5. Experience output is bullets only — never repeat title as 'DevOps Engineer | DevOps Engineer'.\n"
    )


def build_aws_infrastructure_style_prompt(
    *,
    jd_tools: list[str],
    source_metrics: list[str],
    target_role: str = "",
) -> str:
    """Snapsheet-style AWS infrastructure owner — not generic DevOps."""
    job = (target_role or "Senior DevOps Engineer").strip()
    tools = ", ".join(jd_tools[:16]) if jd_tools else "AWS, Terraform, VPC, IAM, RDS, Aurora, ECS, Lambda, CI/CD"
    lines = [
        "AWS INFRASTRUCTURE OWNER STYLE (not generic DevOps):",
        f"- Target: {job} owning AWS infrastructure/platform — VPC, IAM, RDS/Aurora, Terraform modules, DR, FinOps.",
        f"- JD tools to weave into peak role: {tools}.",
        "- Peak role bullets: infrastructure ownership, IaC modules, networking, IAM policies, database ops, "
        "backup/DR, cost reporting, incident response — vary intents; not all 'Built X improved Y%'.",
        "- Do NOT lead with GCP or Kubernetes unless they dominate the JD or source experience.",
        "- Older roles: simpler ops scope; avoid repeating the same DR/backup migration wording across employers.",
        "- Skills use categories: Cloud & Infrastructure, Infrastructure as Code, CI/CD & Automation, "
        "Security & Operations, Monitoring & Reliability, Databases & Storage.",
    ]
    if source_metrics:
        lines.append(f"- SOURCE metrics to reuse when truthful: {'; '.join(source_metrics[:6])}.")
    return "\n".join(lines) + "\n"


def infer_role_archetype(
    target_role: str,
    job_description: str,
    *,
    is_consulting_ai: bool = False,
    is_aws_infrastructure: bool = False,
) -> str:
    """Role archetype for dynamic skills taxonomy generation (JD-first)."""
    return detect_jd_role_archetype(
        target_role,
        job_description,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infrastructure,
    )


def _score_token_for_skill_category(token: str, category_label: str) -> int:
    """How well a tool fits a dynamic category label."""
    score = 0
    if _skill_fits_category(token, category_label):
        score += 6
    label_l = category_label.lower()
    token_l = token.lower()
    extended: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("production ai", ("rag", "llm", "agentic", "mcp", "langchain", "openai", "prompt", "embedding")),
        ("ai engineering", ("rag", "llm", "agentic", "mcp", "langchain", "retrieval", "tool", "multi-agent")),
        ("backend & data", ("fastapi", "python", "django", "postgresql", "redis", "celery", "pandas", "spark", "graphql")),
        ("cloud & infrastructure", ("aws", "ec2", "vpc", "iam", "ecs", "lambda", "s3", "networking")),
        ("infrastructure as code", ("terraform", "iac", "cloudformation", "module", "provisioning")),
        ("ci/cd & automation", ("github actions", "ci", "cd", "pipeline", "python", "bash", "automation")),
        ("security & operations", ("iam", "security", "patching", "incident", "rbac", "secrets", "hardening")),
        ("monitoring & reliability", ("cloudwatch", "splunk", "datadog", "grafana", "runbook", "sre", "uptime")),
        ("databases & storage", ("rds", "aurora", "backup", "disaster recovery", "migration", "ebs", "s3")),
        ("engineering practice", ("observability", "feedback", "monitoring", "client", "integration", "debugging", "api")),
        ("evaluation", ("eval", "observability", "opentelemetry", "grafana", "monitor", "tracing", "metric")),
        ("backend system", ("fastapi", "python", "api", "redis", "celery", "postgresql", "pydantic", "django")),
        ("data pipeline", ("etl", "spark", "kafka", "airflow", "pipeline", "warehouse", "bigquery")),
        ("engineering practice", ("leadership", "communication", "maintainability", "debugging", "testing", "agile")),
        ("distributed", ("kafka", "microservice", "grpc", "queue", "event", "scale", "latency")),
        ("messaging", ("kafka", "rabbit", "sqs", "pubsub", "event", "queue")),
        ("monitoring", ("datadog", "grafana", "prometheus", "splunk", "alert", "sre", "incident")),
        ("security", ("oauth", "tls", "iam", "vault", "secret", "compliance", "auth")),
        ("frontend", ("react", "vue", "angular", "typescript", "css", "html", "next")),
        ("backend development", ("java", "python", "rest", "fastapi", "django", "api", "microservice")),
        ("frameworks", ("spring", "hibernate", "jpa", "django", "fastapi", "flask")),
        ("cloud & devops", ("aws", "docker", "kubernetes", "ci/cd", "terraform", "jenkins", "github actions")),
        ("engineering practices", ("git", "agile", "sdlc", "junit", "testing", "debugging", "code review")),
    )
    for label_key, hints in extended:
        if label_key in label_l:
            if any(h in token_l for h in hints):
                score += 5
    if token_l in label_l or any(part in token_l for part in label_l.split() if len(part) > 3):
        score += 2
    return score


def build_dynamic_skills_for_role(
    source_skills: str,
    skills_text: str,
    job_description: str,
    *,
    target_role: str = "",
    is_devops_role: bool = False,
    is_consulting_ai: bool = False,
    is_aws_infrastructure: bool = False,
) -> str:
    """
    Generate role-specific skill category labels (colon layout) while preserving line count.
    Paired Word templates keep source header labels — only reorder tools.
    """
    source = (source_skills or "").strip()
    tailored = (skills_text or "").strip()
    if not source or not tailored:
        return tailored or source
    layout = _skills_layout_mode(source)
    source_cats = _parse_skill_categories(source)
    tailored_cats = _parse_skill_categories(tailored)
    if not source_cats:
        return tailored

    if layout == "paired":
        return reorder_skill_categories_by_jd(tailored, job_description, is_devops_role=is_devops_role)

    archetype = infer_role_archetype(
        target_role,
        job_description,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infrastructure,
    )
    taxonomy = list(_ROLE_ARCHETYPE_TAXONOMIES.get(archetype, []))
    if not taxonomy:
        return reorder_skill_categories_by_jd(tailored, job_description, is_devops_role=is_devops_role)

    all_tokens: list[str] = []
    seen_tokens: set[str] = set()
    for cat in tailored_cats:
        for token in [str(t).strip() for t in (cat.get("tokens") or []) if str(t).strip()]:
            key = token.lower()
            if key in seen_tokens:
                continue
            seen_tokens.add(key)
            all_tokens.append(token)

    slot_count = len(source_cats)
    labels = taxonomy[:slot_count]
    if len(labels) < slot_count:
        for src_cat in source_cats[len(labels):]:
            labels.append(str(src_cat.get("label", "")).strip())

    assigned: list[list[str]] = [[] for _ in range(slot_count)]
    for token in all_tokens:
        scores = [(idx, _score_token_for_skill_category(token, labels[idx])) for idx in range(slot_count)]
        best_idx = max(scores, key=lambda item: item[1])[0]
        if scores[best_idx][1] <= 0:
            best_idx = min(range(slot_count), key=lambda idx: len(assigned[idx]))
        assigned[best_idx].append(token)

    merged: list[dict[str, object]] = []
    for idx, label in enumerate(labels[:slot_count]):
        tokens = assigned[idx]
        if not tokens:
            src_tokens = [str(t).strip() for t in (source_cats[idx].get("tokens") or []) if str(t).strip()]
            tokens = src_tokens[:8]
        merged.append({"label": label.rstrip(":"), "tokens": _dedupe_skill_tokens(tokens)[:14]})

    return _format_skill_categories(merged, layout)


def build_jd_tool_reasoning_prompt(
    jd_tools: list[str],
    evidence_map: dict[str, int],
    job_description: str,
) -> str:
    """Per-tool reasoning: central to role? evidenced? improves narrative?"""
    if not jd_tools:
        return ""
    priority = (_extract_jd_priority_text(job_description) or job_description).lower()
    evidence_lower = {k.lower(): v for k, v in evidence_map.items()}
    lines = [
        "JD TOOL REASONING (reason before writing — do NOT treat the JD as a keyword checklist):",
        "For each tool ask: (1) central to the role? (2) supported by source evidence? (3) improves the engineering narrative?",
    ]
    for tool in jd_tools[:12]:
        score = evidence_map.get(tool, evidence_lower.get(tool.lower(), 0))
        in_priority = tool.lower() in priority
        if in_priority and score >= 2:
            decision = "EMPHASIZE in peak-role bullets and skills"
        elif score >= 2:
            decision = "include in experience context where truthful"
        elif score == 1:
            decision = "one experience bullet only — do not put in summary/skills alone"
        else:
            decision = "DO NOT add — no source evidence"
        lines.append(
            f"  - {tool}: central={str(in_priority).lower()}, evidence={score} → {decision}"
        )
    return "\n".join(lines) + "\n"


def build_resume_narrative_prompt(
    evidence_map: dict[str, int],
    job_description: str,
    *,
    target_role: str = "",
    is_consulting_ai: bool = False,
) -> str:
    """What story should this resume tell? — narrative before writing."""
    role = (target_role or extract_jd_target_role_title(job_description) or "engineer").strip()
    archetype = infer_role_archetype(target_role, job_description, is_consulting_ai=is_consulting_ai)
    strengths = [term for term, score in evidence_map.items() if score >= 2][:8]
    if is_consulting_ai:
        threads = list(_CONSULTING_AI_NARRATIVE_THREADS)
    elif archetype == "devops":
        threads = ["Platform reliability", "Infrastructure automation", "CI/CD at scale", "Incident response", "Security", "Cost efficiency"]
    elif archetype in ("ai_engineer", "consulting_ai_engineer"):
        threads = ["Production AI engineer", "Enterprise systems", "Reliability", "Leadership", "Client collaboration", "Maintainability"]
    elif archetype == "java_backend":
        threads = list(_JAVA_BACKEND_NARRATIVE)
    elif archetype == "backend":
        threads = ["Backend systems", "Distributed services", "API design", "Data integrity", "Performance", "Operational excellence"]
    else:
        threads = [f"{role} identity", "Technical depth", "Delivery", "Collaboration", "Production quality"]
    if strengths:
        threads = strengths[:3] + threads[:4]
    narrative = " → ".join(list(dict.fromkeys(threads))[:7])
    return (
        "RESUME NARRATIVE (everything else follows this story):\n"
        f"- Target: {role}\n"
        f"- Narrative arc: {narrative}\n"
        "- Summary introduces this identity; experience proves it; skills list the tools that support it.\n"
    )


def build_resume_strategy_prompt(
    evidence_map: dict[str, int],
    jd_tools: list[str],
    job_description: str,
    *,
    target_role: str = "",
    is_consulting_ai: bool = False,
    is_aws_infrastructure: bool = False,
) -> str:
    """Internal resume strategy before generation — strengths, gaps, emphasis plan."""
    role = (target_role or extract_jd_target_role_title(job_description) or "target role").strip()
    strengths = [term for term, score in evidence_map.items() if score >= 3][:6]
    if not strengths:
        strengths = [term for term, score in evidence_map.items() if score >= 2][:6]
    evidence_lower = {k.lower(): v for k, v in evidence_map.items()}
    emphasize = [t for t in jd_tools if evidence_lower.get(t.lower(), 0) >= 2][:8]
    deemphasize = [t for t in jd_tools if evidence_lower.get(t.lower(), 0) == 0][:8]
    weak = [t for t in jd_tools if evidence_lower.get(t.lower(), 0) == 1][:6]
    archetype = infer_role_archetype(
        target_role,
        job_description,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infrastructure,
    )
    taxonomy = _ROLE_ARCHETYPE_TAXONOMIES.get(archetype, [])
    lines = [
        "RESUME STRATEGY (complete this reasoning BEFORE writing Stage 2 content):",
        f"- Candidate strengths (evidence-backed): {', '.join(strengths) if strengths else 'see evidence map'}",
        f"- Target role: {role}",
    ]
    if is_aws_infrastructure:
        lines.append(
            "- Archetype: AWS Infrastructure Platform Engineer — VPC, IAM, RDS/Aurora, Terraform modules, "
            "DR, cost reporting, database operations (not generic DevOps)."
        )
    elif is_consulting_ai:
        lines.append(
            "- Archetype: Consulting AI Engineer / Production LLM Engineer — show whole-system ownership "
            "(architecture, evals, observability, debugging, iteration, client translation)."
        )
    elif archetype == "java_backend":
        lines.append(
            "- Archetype: Java Backend Engineer — REST APIs, databases, microservices, SDLC, CI/CD. "
            "Do NOT lead with AI/LLM/RAG unless the JD explicitly requires it."
        )
    lines.append(f"- Emphasize: {', '.join(emphasize) if emphasize else 'evidence-backed stack from source'}")
    if deemphasize:
        lines.append(f"- Do NOT overemphasize (JD-only, no source evidence): {', '.join(deemphasize)}")
    if weak:
        lines.append(f"- Use cautiously (weak evidence — one bullet max each): {', '.join(weak)}")
    if taxonomy:
        lines.append(
            f"- Skills categories for this role (use these labels): {', '.join(taxonomy[:10])}"
        )
    lines.append("- Every summary competency must be demonstrated in at least one experience bullet.")
    lines.append("- Do not repeat the same bullet structure more than twice across the resume.")
    return "\n".join(lines) + "\n"


def build_hidden_planning_step_prompt(
    target_role: str,
    job_description: str,
    evidence_map: dict[str, int],
    *,
    is_consulting_ai: bool = False,
    is_aws_infrastructure: bool = False,
) -> str:
    """Five-step hidden planning block — reason before writing (embedded in one LLM call)."""
    role = (target_role or extract_jd_target_role_title(job_description) or "target role").strip()
    if is_aws_infrastructure:
        archetype_label = "AWS Infrastructure Platform Engineer / Senior DevOps Engineer"
        narrative = " → ".join(
            ("AWS infrastructure ownership", "VPC/networking", "IAM", "RDS/Aurora", "Terraform/IaC", "HA/DR", "FinOps")
        )
    elif is_consulting_ai:
        archetype_label = "Consulting AI Engineer / Production LLM Engineer"
        narrative = " → ".join(_CONSULTING_AI_NARRATIVE_THREADS)
    else:
        archetype_label = role
        narrative = build_resume_narrative_prompt(
            evidence_map, job_description, target_role=target_role, is_consulting_ai=False
        ).split("Narrative arc: ", 1)[-1].split("\n", 1)[0]
    evidence_line = ", ".join(list(evidence_map.keys())[:12]) or "see evidence map"
    if is_aws_infrastructure:
        lifecycle_intents = ", ".join(_AWS_INFRA_BULLET_INTENTS)
    elif is_consulting_ai:
        lifecycle_intents = ", ".join(_CONSULTING_AI_LIFECYCLE_INTENTS)
    else:
        lifecycle_intents = ", ".join(_BULLET_INTENTS)
    return (
        "HIDDEN PLANNING STEP (reason through this BEFORE writing — do not echo in output JSON):\n"
        f"Step 1 — Identify target role archetype: {archetype_label}\n"
        f"Step 2 — Build narrative: {narrative}\n"
        f"Step 3 — Select evidence from source resume only: {evidence_line}\n"
        f"Step 4 — Rewrite bullets by intent ({lifecycle_intents})\n"
        "Step 5 — Generate final resume (summary, experience bullets, skills)\n"
    )


def build_bullet_intent_plan(
    bullets_per_role: list[int],
    *,
    is_consulting_ai: bool = False,
    is_aws_infrastructure: bool = False,
) -> str:
    """Assign each bullet a distinct intent so writing rhythm varies naturally."""
    if not bullets_per_role:
        return ""
    if is_aws_infrastructure:
        intent_label = (
            "Infrastructure ownership | IaC/Terraform | Networking/VPC | Security/IAM | "
            "Database/DR | Reliability/HA | Cost/FinOps | Automation/CI/CD"
        )
        peak_pool = _AWS_INFRA_BULLET_INTENTS
    elif is_consulting_ai:
        intent_label = (
            "Architecture | Production ownership | Evaluation | Observability | Client collaboration | "
            "Reliability | Business impact | Implementation"
        )
        peak_pool = _CONSULTING_AI_LIFECYCLE_INTENTS
    else:
        intent_label = (
            "Architecture | Business impact | Reliability | Ownership | Scale | Leadership | "
            "Collaboration | Implementation"
        )
        peak_pool = _BULLET_INTENTS
    lines = [
        "BULLET INTENT PLAN — each bullet has a different purpose (NOT Verb → Technology → Metric every time):",
        f"Intents: {intent_label}",
    ]
    cursor = 0
    role_count = len(bullets_per_role)
    for role_idx, count in enumerate(bullets_per_role):
        if count <= 0:
            continue
        is_peak = role_idx == role_count - 1
        use_special = (is_consulting_ai or is_aws_infrastructure) and is_peak
        intent_pool = peak_pool if use_special else _BULLET_INTENTS
        intents = [intent_pool[cursor % len(intent_pool)]]
        cursor += 1
        while len(intents) < count:
            nxt = intent_pool[cursor % len(intent_pool)]
            if nxt != intents[-1]:
                intents.append(nxt)
            cursor += 1
        role_note = " (PEAK — full AI lifecycle)" if (is_consulting_ai and is_peak) else (
            " (PEAK — AWS infrastructure ownership)" if (is_aws_infrastructure and is_peak) else ""
        )
        lines.append(
            f"  Employer {role_idx + 1}{role_note}: "
            + ", ".join(f"bullet {i + 1}={intents[i]}" for i in range(count))
        )
    lines.append(
        "Write each bullet to match its intent. Do not repeat the same structure more than twice. "
        "Only ~40% should end with a metric; others focus on architecture, ownership, evals, or collaboration."
    )
    if is_consulting_ai:
        lines.append(
            "Consulting peak role: include 2–3 bullets starting with Owned/Led/Introduced covering "
            "architecture + evals + observability together."
        )
    if is_aws_infrastructure:
        lines.append(
            "AWS peak role: emphasize VPC, IAM, RDS/Aurora, Terraform modules, DR, cost reporting — "
            "not GCP/Kubernetes unless source supports."
        )
    return "\n".join(lines) + "\n"


def reorder_skill_categories_by_jd(
    skills_text: str,
    job_description: str,
    *,
    is_devops_role: bool = False,
) -> str:
    """Order skill categories by relevance to the target role (dynamic taxonomy via ordering)."""
    layout = _skills_layout_mode(skills_text)
    categories = _parse_skill_categories(skills_text)
    if len(categories) <= 1:
        return skills_text
    priority_text = _extract_jd_priority_text(job_description) or job_description

    def _cat_score(cat: dict[str, object]) -> int:
        label = str(cat.get("label", ""))
        tokens = [str(t) for t in (cat.get("tokens") or [])]
        score = _score_skill_token_against_jd(label, priority_text, job_description) * 2
        for token in tokens[:8]:
            score += _score_skill_token_against_jd(token, priority_text, job_description)
        if is_devops_role and re.search(r"cloud|devops|ci|infra|platform", label, re.I):
            score += 4
        if re.search(r"ai|ml|generative|llm", label, re.I):
            score += 3
        return score

    categories.sort(key=_cat_score, reverse=True)
    return _format_skill_categories(categories, layout)


def build_weighted_jd_keyword_plan(
    job_description: str,
    *,
    target_job_role: str = "",
    jd_tools: list[str] | None = None,
    jd_phrases: list[str] | None = None,
) -> str:
    """Weighted keyword graph — prioritize critical tech over soft skills and values."""
    priority_text = _extract_jd_priority_text(job_description) or job_description
    critical = list(jd_tools or extract_jd_tool_phrases(job_description))[:6]
    if not critical:
        critical = extract_keywords(priority_text, top_k=6)
    responsibilities = list(jd_phrases or extract_jd_responsibility_phrases(job_description))[:5]
    domain: list[str] = []
    if _is_ai_ml_role(target_job_role, job_description):
        domain = [t for t in ("RAG", "MCP", "tool use", "evals", "observability", "agentic workflows") if t]
    soft: list[str] = []
    for term in ("ownership", "architecture", "debugging", "communication", "collaboration"):
        if re.search(re.escape(term), priority_text, re.I):
            soft.append(term)
    values: list[str] = []
    for term in ("innovation", "learning", "impact"):
        if re.search(rf"\b{re.escape(term)}\b", job_description, re.I):
            values.append(term)

    lines = [
        "WEIGHTED JD KEYWORD PLAN (optimize naturally — not a keyword cloud):",
        f"- Critical technologies (weight 10): {', '.join(critical) if critical else 'from JD must-haves'}",
        f"- Responsibilities (weight 9): {', '.join(responsibilities[:4]) if responsibilities else 'ownership, delivery'}",
        f"- Domain concepts (weight 8): {', '.join(domain[:4]) if domain else 'role-specific domain from JD'}",
        f"- Soft skills (weight 5): {', '.join(soft[:3]) if soft else 'only if in JD'}",
        f"- Company values (weight 2): {', '.join(values[:2]) if values else 'only if in JD'}",
        "- PLACEMENT: summary = narrative identity + domain; experience = critical tech in bullet context; "
        "skills = tool names. Never paste the same keyword in all three sections.",
        "- Each specific tool/phrase: maximum 2 mentions total across summary + skills + experience.",
    ]
    return "\n".join(lines) + "\n"


def build_human_resume_writing_prompt() -> str:
    """Rules so output reads like a senior recruiter wrote it — not an AI keyword stuffer."""
    return (
        "HUMAN RECRUITER VOICE (mandatory):\n"
        "- Write like a principal engineering recruiter with 20 years of experience — believable after a 30-second scan.\n"
        "- Optimize for ATS naturally; never sacrifice narrative for keyword density.\n"
        "- Every bullet starts with a strong verb. PREFER: "
        + _PREFERRED_BULLET_VERBS
        + ".\n"
        "- NEVER start bullets with: Spearheaded, Leveraged, Utilized, Facilitated, Enhanced, Achieved, "
        "Improved, Optimized, Accelerated, Streamlined.\n"
        "- NEVER use corporate filler: comprehensive, significantly enhancing, streamlining, facilitating.\n"
        "- NEVER open summary with: Results-driven, Dynamic, Innovative, Passionate, Highly motivated.\n"
        "- Summary: 3–4 sentences; engineering identity (role, years, specialization, scope) — NO first person (I am/my).\n"
        "- Summary must establish a distinctive identity — not 'AI Engineer with N years of experience' alone.\n"
        "- Summary avoids motivational adjectives; focus on specialization, technical strengths, and engineering scope.\n"
        "- Bullets: assign each bullet an intent (Architecture, Ownership, Reliability, etc.) — vary structure.\n"
        "- No more than 40% of bullets may END with a quantified metric; others emphasize decisions and scope.\n"
        "- Build an engineering narrative (career story), not a keyword cloud. Each employer block should read distinct.\n"
        "- Every core competency in the summary must appear in at least one experience bullet.\n"
        "- Do not repeat the same JD phrase in summary, skills, AND experience. Distribute keywords by weight.\n"
        "- Do not repeat the same bullet structure more than twice across the resume.\n"
        "- Skills categories must be role-specific — not the same generic template every time.\n"
    )


def build_ats_priority_terms(
    job_description: str,
    *,
    target_job_role: str = "",
    skills: str = "",
    summary: str = "",
    experience: str = "",
) -> list[str]:
    """High-value ATS terms to weave into summary, experience, and skills."""
    seen: set[str] = set()
    out: list[str] = []

    def _add(term: str) -> None:
        cleaned = re.sub(r"\s+", " ", (term or "").strip(" ,;."))
        if len(cleaned) < 2:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(cleaned)

    profile_text = f"{skills} {summary}"
    for kw in extract_keywords(job_description, top_k=36):
        _add(kw)
    for kw in extract_keywords(_extract_jd_priority_text(job_description) or job_description, top_k=24):
        _add(kw)
    for tech in _extract_profile_tech_stack(skills, summary):
        _add(tech)
    for tech in _expand_inferred_ai_stack(skills, summary, experience):
        _add(tech)
    for tech in extract_jd_tool_phrases(job_description):
        _add(tech)
    for tech in _expand_inferred_devops_stack(skills, summary, job_description):
        _add(tech)

    if _is_ai_ml_role(target_job_role, job_description):
        for term in _AI_ATS_TERMS:
            _add(term)
        for term in _GENERAL_SENIOR_AI_ATS_TERMS:
            _add(term)
        for phrase in extract_jd_responsibility_phrases(job_description):
            _add(phrase)
    if _is_devops_role(target_job_role, job_description):
        for term in _DEVOPS_ATS_TERMS:
            _add(term)

    return out[:56]


def _ats_term_hits(text: str, terms: list[str]) -> int:
    lower = (text or "").lower()
    return sum(1 for term in terms if term.lower() in lower)


@dataclass
class TailoredSections:
    contact: str
    professional_summary: str
    professional_experience: str
    skills: str
    education: str
    other: str
    experience_role_titles: str = ""
    experience_bullets_per_role: list[int] | None = None


def _source_section_stats(parsed: ParsedResume) -> dict[str, int | list[int]]:
    exp = (parsed.professional_experience or "").strip()
    skills = (parsed.skills or "").strip()
    bullets = len(re.findall(rf"^[{_BULLET_CHARS}]\s", exp, re.M))
    roles = len(re.findall(r"\n\s*\n", exp)) + (1 if exp else 0)
    skill_lines = len([line for line in skills.splitlines() if line.strip()])
    per_role = _experience_bullets_per_role(exp)
    return {
        "experience_chars": len(exp),
        "experience_bullets": bullets,
        "experience_roles_est": roles,
        "experience_bullets_per_role": per_role,
        "skills_chars": len(skills),
        "skills_lines": skill_lines,
    }


def _resolve_bullets_per_role_for_tailor(
    parsed: ParsedResume,
    resolved_role_count: int,
    *,
    docx_bullet_slots: list[int] | None = None,
) -> tuple[list[int], list[int]]:
    """
    Returns (generation_targets, docx_export_caps).
    Generation is NOT capped by source bullet count (default min 2 per role).
    Docx export caps to physical Word bullet paragraph slots when known.
    """
    ats = _progressive_ats_bullets_per_role(resolved_role_count)
    generation = ats_bullets_for_generation(ats)
    text_slots = _experience_bullets_per_role(parsed.professional_experience)
    if docx_bullet_slots and len(docx_bullet_slots) == resolved_role_count:
        slots = [
            max(text_slots[i] if i < len(text_slots) else 0, docx_bullet_slots[i])
            for i in range(resolved_role_count)
        ]
    elif docx_bullet_slots and len(docx_bullet_slots) > 0:
        slots = docx_bullet_slots
    else:
        slots = text_slots
    export_caps = effective_bullets_per_role(ats, slots) if slots else generation
    return generation, export_caps


def _experience_bullets_per_role(experience: str) -> list[int]:
    blocks = split_experience_line_blocks(experience or "")
    if not blocks:
        return []
    return [
        sum(1 for line in block if _BULLET_LINE_RE.match(line.strip()))
        for block in blocks
    ]


def _count_experience_roles(experience: str) -> int:
    return len(split_experience_line_blocks(experience or ""))


def _experience_headers_only(experience: str) -> str:
    """Keep role headers (company/title/dates) but strip source bullets so the LLM cannot reuse them."""
    blocks = split_experience_line_blocks(experience or "")
    if not blocks:
        return ""
    out: list[str] = []
    for block_i, block in enumerate(blocks):
        headers = [line for line in block if not _BULLET_LINE_RE.match(line.strip())]
        if headers:
            out.extend(headers)
        if block_i < len(blocks) - 1:
            out.append("")
    return "\n".join(out).strip()


def _experience_has_bullets(text: str) -> bool:
    return bool(re.search(rf"^[{_BULLET_CHARS}]\s", text or "", re.M))


def _progressive_ats_bullets_per_role(role_count: int) -> list[int]:
    """Alias for shared ATS bullet minimums (never derived from source resume)."""
    return default_ats_bullets_per_role(role_count)


def _resolve_role_count(parsed: ParsedResume, role_count: int | None = None) -> int:
    from_blocks = _count_experience_roles(parsed.professional_experience)
    if role_count and role_count > 0:
        if from_blocks > 0:
            return max(role_count, from_blocks)
        return role_count
    if from_blocks > 0:
        return from_blocks
    stats = _source_section_stats(parsed)
    return max(1, int(stats.get("experience_roles_est") or 1))


def _partition_flat_bullets(bullets: list[str], counts: list[int]) -> list[list[str]]:
    return partition_experience_bullets_by_role(bullets, counts)


def _tailored_bullets_per_role(tailored_experience: str, role_counts: list[int]) -> list[int]:
    bullets = [
        line.strip()
        for line in (tailored_experience or "").splitlines()
        if line.strip() and _BULLET_LINE_RE.match(line.strip())
    ]
    return [len(part) for part in _partition_flat_bullets(bullets, role_counts)]


def extract_years_of_experience(*texts: str) -> str | None:
    """Find a years-of-experience phrase from profile, summary, or contact."""
    for text in texts:
        if not text:
            continue
        match = _YEARS_OF_EXPERIENCE_RE.search(text)
        if match:
            return match.group(1).strip()
    return None


def extract_source_metrics(*texts: str, limit: int = 12) -> list[str]:
    """Collect quantified results from the source resume to reuse in tailored bullets."""
    seen: set[str] = set()
    metrics: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in _METRIC_SNIPPET_RE.finditer(text):
            snippet = re.sub(r"\s+", " ", match.group(0)).strip(" ,;.")
            key = snippet.lower()
            if len(snippet) < 4 or key in seen:
                continue
            seen.add(key)
            metrics.append(snippet)
            if len(metrics) >= limit:
                return metrics
    return metrics


def ensure_years_in_summary(summary: str, source_summary: str, contact: str = "") -> str:
    """Keep the profile's years-of-experience phrase in the tailored summary."""
    summary = (summary or "").strip()
    if not summary:
        return summary
    years = extract_years_of_experience(source_summary, contact)
    if not years:
        return summary
    if extract_years_of_experience(summary):
        return summary
    years_phrase = years if re.search(r"experience|exp", years, re.I) else f"{years} of experience"
    parts = re.split(r"(?<=[.!?])\s+", summary, maxsplit=1)
    first = parts[0].rstrip(".")
    rest = parts[1].strip() if len(parts) > 1 else ""
    if re.search(r"\b(with|bringing)\b", first, re.I):
        first = f"{first}, {years_phrase}"
    else:
        first = f"{first} with {years_phrase}"
    return f"{first}. {rest}".strip() if rest else f"{first}."


def _tailor_volume_ok(
    parsed: ParsedResume,
    tailored: TailoredSections,
    *,
    bullets_per_role: list[int] | None = None,
) -> bool:
    stats = _source_section_stats(parsed)
    out_sk = len(tailored.skills.strip())
    out_sum = len(tailored.professional_summary.strip())
    role_count = _resolve_role_count(parsed)
    targets = bullets_per_role or _progressive_ats_bullets_per_role(role_count)
    generation = ats_bullets_for_generation(targets)
    min_total_bullets = sum(generation) if generation else 8
    out_bullets = len(re.findall(rf"^[{_BULLET_CHARS}]\s", tailored.professional_experience, re.M))
    if out_bullets < max(10, int(min_total_bullets * 0.9)):
        return False
    if generation:
        actual_per_role = _tailored_bullets_per_role(tailored.professional_experience, generation)
        for actual, minimum in zip(actual_per_role, generation):
            floor = max(_min_bullets_per_role_env(), minimum if minimum <= 2 else int(minimum * 0.85))
            if actual < floor:
                return False
    if stats["skills_chars"] > 80 and out_sk < stats["skills_chars"] * 0.55:
        return False
    if (parsed.professional_summary or "").strip() and out_sum < max(200, len(parsed.professional_summary.strip()) * 0.55):
        return False
    return True


def _meaningful_lines(text: str, *, min_len: int = 24) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if len(stripped) >= min_len:
            lines.append(stripped)
    if lines:
        return lines
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        s = sentence.strip()
        if len(s) >= min_len:
            lines.append(s)
    return lines


def _verbatim_line_overlap(source: str, tailored: str) -> float:
    src_lines = [line.lower() for line in _meaningful_lines(source)]
    if not src_lines:
        return 0.0
    tailored_lower = (tailored or "").lower()
    hits = sum(1 for line in src_lines if line in tailored_lower)
    return hits / len(src_lines)


def _bullet_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _bullet_outcome_fingerprint(body: str) -> tuple[str, ...]:
    lower = body.lower()
    markers = (
        "enterprise software",
        "system uptime",
        "customer satisfaction",
        "operational efficiency",
        "business impact",
        "99.9%",
        "high-availability",
        "secure enterprise",
    )
    return tuple(m for m in markers if m in lower)


def _bullets_are_redundant(a: str, b: str) -> bool:
    a_words = {w for w in re.findall(r"[a-z0-9]+", a.lower()) if len(w) > 2}
    b_words = {w for w in re.findall(r"[a-z0-9]+", b.lower()) if len(w) > 2}
    if len(a_words) < 8 or len(b_words) < 8:
        return False
    if _bullet_similarity(a_words, b_words) >= 0.88:
        return True
    fp_a = _bullet_outcome_fingerprint(a)
    fp_b = _bullet_outcome_fingerprint(b)
    if fp_a and fp_b and len(set(fp_a) & set(fp_b)) >= 2:
        return True
    a_open = " ".join(a.lower().split()[:4])
    b_open = " ".join(b.lower().split()[:4])
    if a_open == b_open and _METRIC_SNIPPET_RE.search(a) and _METRIC_SNIPPET_RE.search(b):
        return True
    return False


def _tailor_duplicate_bullets_ok(tailored: TailoredSections) -> bool:
    """Reject experience with near-duplicate accomplishment bullets."""
    bodies = _bullet_bodies(tailored.professional_experience or "")
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            if _bullets_are_redundant(bodies[i], bodies[j]):
                return False
    return True


def _tailor_bullet_richness_ok(tailored: TailoredSections) -> bool:
    """Bullets should be substantive but concise — not corporate paragraph dumps."""
    bodies = _bullet_bodies(tailored.professional_experience or "")
    if len(bodies) < 4:
        return True
    rich = 0
    for body in bodies:
        words = len(body.split())
        tech_hits = len(_NAMED_TECH_RE.findall(body))
        practice = bool(_ENGINEERING_PRACTICE_RE.search(body))
        if 12 <= words <= 24 and tech_hits >= 1:
            rich += 1
        elif words >= 14 and tech_hits >= 2 and practice:
            rich += 1
    return rich >= max(3, int(len(bodies) * 0.45))


def _dedupe_similar_bullets(experience: str) -> str:
    """Drop near-duplicate bullets while preserving order."""
    lines = (experience or "").replace("\r\n", "\n").split("\n")
    kept_bodies: list[set[str]] = []
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not re.match(rf"^[{_BULLET_CHARS}]\s+", stripped):
            out.append(stripped)
            continue
        body = re.sub(rf"^[{_BULLET_CHARS}]\s+", "", stripped).strip().lower()
        if any(_bullets_are_redundant(body, prev) for prev in kept_bodies):
            continue
        kept_bodies.append(body)
        out.append(stripped)
    return "\n".join(out).strip()


def _bullet_bodies(text: str) -> list[str]:
    bodies: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped:
            continue
        if re.match(rf"^[{_BULLET_CHARS}]\s+", stripped):
            body = re.sub(rf"^[{_BULLET_CHARS}]\s+", "", stripped).strip().lower()
            if len(body) >= 20:
                bodies.append(body)
    return bodies


def _bullet_verbatim_overlap(source: str, tailored: str) -> float:
    src = _bullet_bodies(source)
    if not src:
        return 0.0
    tail = set(_bullet_bodies(tailored))
    if not tail:
        return 1.0
    hits = sum(1 for body in src if body in tail)
    return hits / len(src)


def _bullets_with_metrics(text: str) -> int:
    count = 0
    for body in _bullet_bodies(text):
        if _METRIC_SNIPPET_RE.search(body):
            count += 1
    return count


def _bullets_with_impact_metrics(text: str) -> int:
    """Quantified bullets that also name stack or production practice (ATS + recruiter friendly)."""
    count = 0
    for body in _bullet_bodies(text):
        if not _METRIC_SNIPPET_RE.search(body):
            continue
        if _NAMED_TECH_RE.search(body) or _ENGINEERING_PRACTICE_RE.search(body):
            count += 1
    return count


def _tailor_metrics_ok(
    tailored: TailoredSections,
    *,
    bullets_per_role: list[int] | None = None,
    is_devops_role: bool = False,
    is_ai_role: bool = False,
    is_consulting_ai: bool = False,
) -> bool:
    total_bullets = len(_bullet_bodies(tailored.professional_experience))
    if total_bullets == 0:
        return False
    impact_metrics = _bullets_with_impact_metrics(tailored.professional_experience)
    if is_consulting_ai:
        ratio = 0.28
    elif is_devops_role:
        ratio = 0.32
    elif is_ai_role:
        ratio = 0.30
    else:
        ratio = 0.28
    min_required = max(4, int(total_bullets * ratio))
    if bullets_per_role:
        per_role_floor = sum(max(2, count // 3) for count in bullets_per_role) if is_devops_role else sum(
            max(1, count // 5) for count in bullets_per_role
        )
        min_required = max(min_required, per_role_floor)
    return impact_metrics >= min_required


def _bullets_with_technical_depth(text: str) -> int:
    count = 0
    for body in _bullet_bodies(text):
        if _NAMED_TECH_RE.search(body) or _ENGINEERING_PRACTICE_RE.search(body):
            count += 1
    return count


def _generic_bullet_ratio(text: str) -> float:
    bodies = _bullet_bodies(text)
    if not bodies:
        return 1.0
    hits = sum(1 for body in bodies if any(phrase in body.lower() for phrase in _GENERIC_BULLET_PHRASES))
    return hits / len(bodies)


def _tailor_technical_depth_ok(
    tailored: TailoredSections,
    ats_terms: list[str],
    *,
    is_ai_role: bool,
    is_devops_role: bool = False,
) -> bool:
    exp = tailored.professional_experience or ""
    summ = tailored.professional_summary or ""
    bullets = _bullet_bodies(exp)
    if len(bullets) < 4:
        return False

    depth_bullets = _bullets_with_technical_depth(exp)
    if depth_bullets < max(4, int(len(bullets) * 0.72)):
        return False
    if _generic_bullet_ratio(exp) > 0.2:
        return False

    priority = ats_terms[:28]
    combined = f"{summ}\n{exp}"
    combined_lower = combined.lower()
    if priority:
        min_hits = max(8, int(len(priority) * 0.32))
        if _ats_term_hits(combined, priority) < min_hits:
            return False

    if is_ai_role:
        ai_signals = (
            "rag",
            "agentic",
            "eval",
            "observability",
            "fastapi",
            "langchain",
            "retrieval",
            "llm",
            "mcp",
            "structured output",
            "pinecone",
            "opentelemetry",
            "tool use",
            "tool-using",
        )
        combined_lower = combined.lower()
        ai_hits = sum(1 for sig in ai_signals if sig in combined_lower)
        if ai_hits < 8:
            return False
        if "mcp" not in combined_lower:
            return False
        if not re.search(r"tool[\s-]?use|tool-using", combined_lower):
            return False
        if "structured output" not in combined_lower:
            return False
        summary_lower = summ.lower()
        if not any(
            p in summary_lower
            for p in ("client discovery", "client communication", "production", "maintainability", "latency")
        ):
            return False
        summary_opening = " ".join(re.split(r"(?<=[.!?])\s+", summ.strip())[:2])
        stack_terms = len(_NAMED_TECH_RE.findall(summary_opening)) + len(
            [term for term in _AI_ATS_TERMS if term.lower() in summary_opening.lower()]
        )
        if stack_terms < 4 and not re.search(r"\bstrong in\b", summary_opening, re.I):
            return False

    if is_devops_role and not is_ai_role:
        devops_signals = (
            "azure",
            "kubernetes",
            "terraform",
            "github actions",
            "azure devops",
            "ci/cd",
            "docker",
            "git",
            "linux",
            "monitoring",
            "helm",
            "gitops",
        )
        combined_lower = combined.lower()
        devops_hits = sum(1 for sig in devops_signals if sig in combined_lower)
        if devops_hits < 9:
            return False
        exp_lower = exp.lower()
        if "github actions" not in exp_lower and "azure devops" not in exp_lower:
            return False

    return True


def _skill_token_jd_relevant(token: str, job_description: str, *, is_devops_role: bool) -> bool:
    token_lower = (token or "").strip().lower()
    if not token_lower or len(token_lower) < 2:
        return False
    if is_devops_role and token_lower in _SKILLS_DEVOPS_NOISE_TERMS:
        return False
    priority_text = _extract_jd_priority_text(job_description) or job_description
    score = _score_skill_token_against_jd(token, priority_text, job_description)
    if score >= 3:
        return True
    if is_devops_role and score >= 1 and token_lower in _EVIDENCED_GENERIC_SKILL_TERMS:
        return True
    if not is_devops_role:
        return score >= 2
    return score >= 2 and token_lower not in _SKILLS_DEVOPS_NOISE_TERMS


def _recent_role_bullets(experience: str) -> list[str]:
    blocks = split_experience_line_blocks(experience or "")
    if not blocks:
        return []
    last_block = blocks[-1]
    return [
        re.sub(rf"^[{_BULLET_CHARS}]\s+", "", line.strip())
        for line in last_block
        if _BULLET_LINE_RE.match(line.strip())
    ]


def _tailor_recent_role_authenticity_ok(tailored: TailoredSections) -> bool:
    """Recent role should not read like every bullet was copy-pasted from the JD with round metrics."""
    recent = _recent_role_bullets(tailored.professional_experience)
    if len(recent) < 4:
        return True
    pct_bullets = sum(1 for body in recent if re.search(r"\d+(?:\.\d+)?\s*%", body))
    if pct_bullets > max(2, int(len(recent) * 0.5)):
        return False
    ownership = sum(1 for body in recent if _OWNERSHIP_BULLET_RE.search(body))
    return ownership >= 1


def _tailor_ownership_bullets_ok(tailored: TailoredSections) -> bool:
    bodies = _bullet_bodies(tailored.professional_experience)
    if len(bodies) < 6:
        return True
    return sum(1 for body in bodies if _OWNERSHIP_BULLET_RE.search(body)) >= 2


def _tailor_duty_bullets_ok(tailored: TailoredSections) -> bool:
    """Reject generic duty-style bullets without quantified outcomes."""
    bodies = _bullet_bodies(tailored.professional_experience)
    if len(bodies) < 4:
        return True
    weak = 0
    for body in bodies:
        if _METRIC_SNIPPET_RE.search(body):
            continue
        lower = body.lower()
        if any(phrase in lower for phrase in _DUTY_BULLET_PHRASES):
            weak += 1
        elif _DUTY_BULLET_START_RE.match(body) and len(body.split()) <= 22:
            weak += 1
    return weak <= max(1, int(len(bodies) * 0.08))


def _tailor_skills_experience_consistency_ok(tailored: TailoredSections) -> bool:
    """Top skills must be evidenced in experience bullets."""
    skill_tokens = _parse_skill_tokens(tailored.skills)
    tech_tokens = [
        t
        for t in skill_tokens
        if t.lower() not in _SKILLS_SOFT_ONLY_TERMS and len(t) >= 4
    ]
    if not tech_tokens:
        return True
    exp = tailored.professional_experience or ""
    priority = tech_tokens[:10]
    missing = sum(1 for token in priority if not _term_appears_in_skills(token, exp))
    return missing <= max(4, int(len(priority) * 0.65))


def _tailor_mandatory_devops_keywords_ok(
    tailored: TailoredSections,
    *,
    is_devops_role: bool,
    has_devops_stack: bool,
    job_description: str = "",
) -> bool:
    if not is_devops_role:
        return True
    combined = f"{tailored.professional_summary}\n{tailored.professional_experience}\n{tailored.skills}"
    cloud = detect_primary_cloud_provider(job_description)
    patterns = _AWS_MANDATORY_KEYWORD_PATTERNS if cloud == "aws" else _MANDATORY_DEVOPS_KEYWORD_PATTERNS
    hits = sum(1 for pattern, _label in patterns if re.search(pattern, combined, re.I))
    exp = tailored.professional_experience or ""
    min_hits = 7 if cloud == "aws" else 8
    if cloud == "aws":
        aws_in_exp = len(re.findall(r"\baws\b|\bvpc\b|\biam\b|\brds\b|terraform", exp, re.I))
        return hits >= min_hits and aws_in_exp >= 2
    github_actions_mentions = len(re.findall(r"github\s+actions", exp, re.I))
    return hits >= min_hits and github_actions_mentions >= 1


def _tailor_skills_nonempty_categories_ok(skills: str) -> bool:
    """Every skill category must contain at least one tool."""
    categories = _parse_skill_categories(skills)
    if not categories:
        return True
    empty = sum(
        1 for cat in categories
        if not [str(t).strip() for t in (cat.get("tokens") or []) if str(t).strip()]
    )
    return empty == 0


def _tailor_cloud_provider_alignment_ok(
    tailored: TailoredSections,
    job_description: str,
) -> bool:
    """Reject resumes over-optimized for the wrong cloud provider."""
    cloud = detect_primary_cloud_provider(job_description)
    if cloud not in ("aws", "azure", "gcp"):
        return True
    combined = f"{tailored.professional_summary}\n{tailored.professional_experience}\n{tailored.skills}".lower()
    if cloud == "aws":
        aws_hits = len(re.findall(r"\baws\b|\bvpc\b|\biam\b|\brds\b|\baurora\b|\bec2\b", combined))
        wrong_hits = len(re.findall(r"\bgcp\b|google cloud|\bgke\b", combined))
        k8s_hits = len(re.findall(r"\bkubernetes\b|\baks\b", combined))
        if wrong_hits >= 3 and wrong_hits > aws_hits // 2:
            return False
        if k8s_hits >= 5 and aws_hits < k8s_hits:
            return False
    elif cloud == "azure":
        azure_hits = len(re.findall(r"\bazure\b|\baks\b", combined))
        wrong_hits = len(re.findall(r"\bgcp\b|google cloud|\baws\b(?!\s*lambda)", combined))
        if wrong_hits >= 4 and wrong_hits > azure_hits // 2:
            return False
    return True


def _tailor_top_jd_keywords_evidenced_ok(
    tailored: TailoredSections,
    job_description: str,
    *,
    jd_tools: list[str] | None = None,
) -> bool:
    """Top JD tools should appear in output when evidenced in experience."""
    tools = list(jd_tools or extract_jd_tool_phrases(job_description))[:10]
    if len(tools) < 4:
        return True
    combined = f"{tailored.professional_summary}\n{tailored.professional_experience}\n{tailored.skills}"
    hits = sum(1 for tool in tools if _term_count_in_text(tool, combined) > 0)
    return hits >= max(4, int(len(tools) * 0.5))


def _fill_empty_skill_categories(skills_text: str, source_skills: str) -> str:
    """Backfill empty tailored categories from source so Word export has no blank skill lines."""
    layout = _skills_layout_mode(source_skills or skills_text)
    categories = _parse_skill_categories(skills_text)
    source_cats = _parse_skill_categories(source_skills)
    if not categories:
        return skills_text
    merged: list[dict[str, object]] = []
    for idx, cat in enumerate(categories):
        label = str(cat.get("label", "")).strip()
        tokens = [str(t).strip() for t in (cat.get("tokens") or []) if str(t).strip()]
        if not tokens and idx < len(source_cats):
            tokens = [
                str(t).strip() for t in (source_cats[idx].get("tokens") or []) if str(t).strip()
            ][:10]
        merged.append({"label": label, "tokens": tokens})
    return _format_skill_categories(merged, layout)


def _tailor_skills_concrete_tools_ok(skills: str, *, is_devops_role: bool) -> bool:
    if not is_devops_role:
        return True
    tokens = _parse_skill_tokens(skills)
    concrete = [t for t in tokens if t.lower() not in _SKILLS_SOFT_ONLY_TERMS]
    return len(concrete) >= 10


def _tailor_mandatory_ai_keywords_ok(
    tailored: TailoredSections,
    *,
    is_ai_role: bool,
    has_llm_stack: bool,
) -> bool:
    if not is_ai_role:
        return True
    combined = f"{tailored.professional_summary}\n{tailored.professional_experience}\n{tailored.skills}"
    hits = 0
    for pattern, _label in _MANDATORY_AI_KEYWORD_PATTERNS:
        if re.search(pattern, combined, re.I):
            hits += 1
    skills = (tailored.skills or "").lower()
    skills_hits = sum(1 for term in _AI_MANDATORY_SKILLS_TERMS if term.lower() in skills)
    exp = tailored.professional_experience or ""
    mcp_in_exp = bool(re.search(r"\bmcp\b", exp, re.I))
    return hits >= 10 and skills_hits >= 5 and mcp_in_exp


def _tailor_ai_ownership_bullets_ok(tailored: TailoredSections, *, is_ai_role: bool) -> bool:
    if not is_ai_role:
        return True
    bodies = _bullet_bodies(tailored.professional_experience)
    if len(bodies) < 6:
        return True
    ownership = sum(
        1 for body in bodies if any(phrase in body.lower() for phrase in _AI_OWNERSHIP_PHRASES)
    )
    metrics = _bullets_with_impact_metrics(tailored.professional_experience)
    return ownership >= 3 and metrics >= max(3, int(len(bodies) * 0.22))


def _tailor_peak_role_consulting_ok(tailored: TailoredSections, *, is_consulting_ai: bool) -> bool:
    """Most recent role matches applied-AI consulting quality (MCP, evals, client-facing, long bullets)."""
    if not is_consulting_ai:
        return True
    recent = _recent_role_bullets(tailored.professional_experience)
    if len(recent) < 6:
        return True
    combined = " ".join(recent)
    checks: tuple[tuple[str, int], ...] = (
        (r"\bmcp\b", 1),
        (r"\bevals?\b", 1),
        (r"observability|opentelemetry", 1),
        (r"client|strategist|designer", 1),
        (r"agentic|retrieval|tool[\s-]?use|structured outputs?", 2),
        (r"feedback loops?", 1),
        (r"production debugging|debugged production|incident", 1),
    )
    for pattern, minimum in checks:
        if len(re.findall(pattern, combined, re.I)) < minimum:
            return False
    long_bullets = sum(1 for body in recent if len(body.split()) >= 20)
    return long_bullets >= max(4, int(len(recent) * 0.5))


def _tailor_rewrite_aggressive_enough(parsed: ParsedResume, tailored: TailoredSections) -> bool:
    """Reject light edits — editable sections must be substantially rewritten for the JD."""
    if _verbatim_line_overlap(parsed.professional_summary, tailored.professional_summary) > 0.15:
        return False
    if _bullet_verbatim_overlap(parsed.professional_experience, tailored.professional_experience) > 0.12:
        return False
    if _verbatim_line_overlap(parsed.skills, tailored.skills) > 0.55:
        return False
    return True


def _extract_summary_competencies(summary: str) -> list[str]:
    """Domain terms and named tech claimed in the professional summary."""
    text = (summary or "").strip()
    if not text:
        return []
    lower = text.lower()
    found: list[str] = []
    for term in _SUMMARY_DOMAIN_COMPETENCIES:
        if term in lower:
            found.append(term)
    for tech in _NAMED_TECH_RE.findall(text):
        found.append(tech.strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:14]


def _bullet_ends_with_metric(body: str) -> bool:
    trimmed = (body or "").strip().rstrip(".")
    if _BULLET_METRIC_ENDING_RE.search(trimmed):
        return True
    return bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:%|percent|x\b)\s*$", trimmed, re.I))


def _tailor_summary_engineering_voice_ok(tailored: TailoredSections) -> bool:
    """Summary should read like an engineer wrote it — not generic resume language."""
    summary = (tailored.professional_summary or "").strip()
    if not summary:
        return True
    if _FIRST_PERSON_SUMMARY_RE.search(summary):
        return False
    if _BANNED_SUMMARY_OPENINGS_RE.search(summary):
        return False
    if _BANNED_CORPORATE_PHRASES_RE.search(summary):
        return False
    words = len(summary.split())
    if words < 18 or words > 95:
        return False
    return True


def _tailor_summary_competencies_in_experience_ok(tailored: TailoredSections) -> bool:
    """Every major summary claim should be backed by at least one experience bullet."""
    summary = (tailored.professional_summary or "").strip()
    exp = tailored.professional_experience or ""
    if not summary or not exp:
        return True
    competencies = _extract_summary_competencies(summary)
    if len(competencies) < 2:
        return True
    missing = sum(
        1 for comp in competencies
        if _term_count_in_text(comp, exp) == 0 and comp.lower() not in exp.lower()
    )
    return missing <= max(1, int(len(competencies) * 0.25))


def _tailor_metric_ending_ratio_ok(tailored: TailoredSections) -> bool:
    """At most 40% of bullets should end with a quantified metric."""
    bodies = _bullet_bodies(tailored.professional_experience or "")
    if len(bodies) < 5:
        return True
    ending = sum(1 for body in bodies if _bullet_ends_with_metric(body))
    return ending <= int(len(bodies) * 0.40)


def _bullet_first_word(body: str) -> str:
    words = (body or "").strip().split()
    return words[0].lower().rstrip(".,;:") if words else ""


def _tailor_bullet_rhythm_ok(tailored: TailoredSections) -> bool:
    """Reject uniform AI rhythm: same opener verb and Verb→Tech→Metric on every line."""
    bodies = _bullet_bodies(tailored.professional_experience or "")
    if len(bodies) < 6:
        return True
    rhythm_hits = sum(1 for body in bodies if _AI_RHYTHM_OPENERS_RE.match(body.strip()))
    if rhythm_hits > int(len(bodies) * 0.22):
        return False
    opener_counts: dict[str, int] = {}
    for body in bodies:
        word = _bullet_first_word(body)
        if word:
            opener_counts[word] = opener_counts.get(word, 0) + 1
    if opener_counts:
        max_same = max(opener_counts.values())
        if max_same > max(3, int(len(bodies) * 0.28)):
            return False
    return True


def _tailor_summary_distinctive_ok(tailored: TailoredSections) -> bool:
    """Reject generic 'Role with N years of experience' summaries with no engineering identity."""
    summary = (tailored.professional_summary or "").strip()
    if not summary:
        return True
    generic_open = re.match(
        r"^(?:senior\s+)?(?:ai|ml|software|full[\s-]?stack|backend|devops)\s+engineer\s+with\s+\d+",
        summary,
        re.I,
    )
    if not generic_open:
        return True
    lower = summary.lower()
    has_identity = any(
        phrase in lower
        for phrase in (
            "specializ",
            "background in",
            "building production",
            "experienced leading",
            "focus on",
            "retrieval",
            "observability",
            "enterprise",
            "platform",
        )
    )
    tech_terms = len(_NAMED_TECH_RE.findall(summary))
    return has_identity or tech_terms >= 3


_BUILT_METRIC_PATTERN_RE = re.compile(
    r"^(?:built|designed|implemented|engineered|developed)\b[^.]{0,120}(?:\d+%|\d+x\b|reduc|improv)",
    re.I,
)


def _tailor_bullet_structure_repetition_ok(tailored: TailoredSections) -> bool:
    """No more than two bullets may share the same Built+X+metric template."""
    bodies = _bullet_bodies(tailored.professional_experience or "")
    if len(bodies) < 5:
        return True
    template_hits = sum(1 for body in bodies if _BUILT_METRIC_PATTERN_RE.search(body.strip()))
    return template_hits <= max(2, int(len(bodies) * 0.28))


def _tailor_ownership_bullets_ok(tailored: TailoredSections, *, is_consulting_ai: bool) -> bool:
    """Consulting AI peak role should include ownership-style bullets."""
    if not is_consulting_ai:
        return True
    recent = _recent_role_bullets(tailored.professional_experience)
    if len(recent) < 4:
        return True
    owned = sum(
        1 for body in recent
        if re.match(r"^(?:owned|led|introduced|standardized)\b", body.strip(), re.I)
    )
    return owned >= 2


def _tailor_human_voice_ok(tailored: TailoredSections) -> bool:
    """Reject corporate/AI phrasing, buzzword summaries, and bloated bullets."""
    bodies = _bullet_bodies(tailored.professional_experience or "")
    if not bodies:
        return False

    banned_starts = sum(1 for body in bodies if _BANNED_BULLET_OPENERS_RE.match(body.strip()))
    if banned_starts > max(1, int(len(bodies) * 0.06)):
        return False

    lengths = [len(body.split()) for body in bodies]
    avg_len = sum(lengths) / len(lengths)
    if avg_len < 10 or avg_len > 24:
        return False
    if sum(1 for w in lengths if w > 28) > max(2, int(len(bodies) * 0.10)):
        return False

    summary = (tailored.professional_summary or "").strip()
    if summary and _BANNED_SUMMARY_OPENINGS_RE.search(summary):
        return False

    corporate_hits = sum(1 for body in bodies if _BANNED_CORPORATE_PHRASES_RE.search(body))
    if corporate_hits > max(1, int(len(bodies) * 0.08)):
        return False

    return True


def _term_count_in_text(term: str, text: str) -> int:
    if len(term) < 3 or not text:
        return 0
    if re.match(r"^[\w\-./+#]+$", term):
        return len(re.findall(r"(?<![\w\-./+#])" + re.escape(term) + r"(?![\w\-./+#])", text, re.I))
    return len(re.findall(re.escape(term), text, re.I))


def _tailor_keyword_spam_ok(tailored: TailoredSections, jd_tools: list[str] | None) -> bool:
    """Each critical JD tool should not appear in all three sections or more than twice total."""
    tools = [t for t in (jd_tools or []) if len(t.strip()) >= 3][:14]
    if not tools:
        return True
    summary = tailored.professional_summary or ""
    skills = tailored.skills or ""
    experience = tailored.professional_experience or ""
    for term in tools:
        counts = (
            _term_count_in_text(term, summary),
            _term_count_in_text(term, skills),
            _term_count_in_text(term, experience),
        )
        total = sum(counts)
        if total > 4:
            return False
        if total >= 3 and sum(1 for c in counts if c > 0) >= 3:
            return False
    return True


def _deprioritize_skills_terms(skills_text: str, de_emphasize: list[str]) -> str:
    """Move de-emphasized terms to the end of each skills category."""
    if not skills_text or not de_emphasize:
        return skills_text
    de_set = {t.lower() for t in de_emphasize}
    layout = _skills_layout_mode(skills_text)
    cats = _parse_skill_categories(skills_text)
    if not cats:
        return skills_text
    merged: list[dict[str, object]] = []
    for cat in cats:
        tokens = [str(t).strip() for t in (cat.get("tokens") or []) if str(t).strip()]
        front = [t for t in tokens if t.lower() not in de_set]
        back = [t for t in tokens if t.lower() in de_set]
        merged.append({"label": cat.get("label", ""), "tokens": front + back})
    return _format_skill_categories(merged, layout)


def _summary_leads_with_ai(summary: str) -> bool:
    opening = (summary or "")[:160].lower()
    return bool(
        re.search(
            r"\b(?:senior\s+)?(?:ai|ml|machine learning|generative ai|llm)\s*(?:/|\s)?(?:ml\s+)?engineer\b",
            opening,
        )
        or re.search(r"\b(?:generative ai|llms?|rag\b|langchain)\b", opening)
    )


def _tailor_role_pivot_ok(tailored: TailoredSections, strategy: TailoringStrategy | None) -> bool:
    """Reject output that still leads with candidate AI identity when JD is a different archetype."""
    if not strategy or strategy.jd_archetype != "java_backend":
        return True
    summary = tailored.professional_summary or ""
    if _summary_leads_with_ai(summary):
        return False
    cats = _parse_skill_categories(tailored.skills or "")
    if cats:
        first_label = str(cats[0].get("label", "")).lower()
        if any(x in first_label for x in ("generative", "llm", "ai engineering", "production ai")):
            return False
        first_tokens = " ".join(str(t) for t in (cats[0].get("tokens") or [])[:4]).lower()
        ai_hits = sum(
            1 for term in _AI_DEEMPHASIS_DEFAULT
            if term.lower() in first_tokens
        )
        if ai_hits >= 2:
            return False
    bodies = _bullet_bodies(tailored.professional_experience)[:10]
    if bodies and strategy.mode in ("moderate", "conservative"):
        ai_bullets = sum(
            1 for b in bodies
            if any(x in b for x in ("rag", "llm", "langchain", "openai", "mcp", "agentic", "generative"))
        )
        backend_bullets = sum(
            1 for b in bodies
            if any(x in b for x in ("java", "rest", "spring", "sql", "hibernate", "jpa", "microservice", "api"))
        )
        if ai_bullets > backend_bullets and backend_bullets < 2:
            return False
    return True


def _tailor_quality_ok(
    parsed: ParsedResume,
    tailored: TailoredSections,
    *,
    bullets_per_role: list[int] | None = None,
    ats_terms: list[str] | None = None,
    jd_tools: list[str] | None = None,
    is_ai_role: bool = False,
    is_devops_role: bool = False,
    has_llm_stack: bool = False,
    has_devops_stack: bool = False,
    is_consulting_ai: bool = False,
    job_description: str = "",
    tailoring_strategy: TailoringStrategy | None = None,
) -> bool:
    terms = ats_terms or []
    return (
        _tailor_volume_ok(parsed, tailored, bullets_per_role=bullets_per_role)
        and _tailor_rewrite_aggressive_enough(parsed, tailored)
        and _tailor_human_voice_ok(tailored)
        and _tailor_keyword_spam_ok(tailored, jd_tools)
        and _tailor_recent_role_authenticity_ok(tailored)
        and _tailor_metrics_ok(
            tailored,
            bullets_per_role=bullets_per_role,
            is_devops_role=is_devops_role,
            is_ai_role=is_ai_role,
            is_consulting_ai=is_consulting_ai,
        )
        and _tailor_technical_depth_ok(
            tailored, terms, is_ai_role=is_ai_role, is_devops_role=is_devops_role
        )
        and _tailor_mandatory_ai_keywords_ok(tailored, is_ai_role=is_ai_role, has_llm_stack=has_llm_stack)
        and _tailor_ai_ownership_bullets_ok(tailored, is_ai_role=is_ai_role)
        and _tailor_peak_role_consulting_ok(tailored, is_consulting_ai=is_consulting_ai)
        and _tailor_mandatory_devops_keywords_ok(
            tailored,
            is_devops_role=is_devops_role,
            has_devops_stack=has_devops_stack,
            job_description=job_description,
        )
        and _tailor_skills_nonempty_categories_ok(tailored.skills)
        and _tailor_cloud_provider_alignment_ok(tailored, job_description)
        and _tailor_top_jd_keywords_evidenced_ok(tailored, job_description, jd_tools=jd_tools)
        and _tailor_duplicate_bullets_ok(tailored)
        and _tailor_bullet_richness_ok(tailored)
        and _tailor_duty_bullets_ok(tailored)
        and _tailor_skills_format_ok(tailored.skills, source_skills=parsed.skills)
        and _tailor_skills_concrete_tools_ok(tailored.skills, is_devops_role=is_devops_role)
        and _tailor_skills_experience_consistency_ok(tailored)
        and _tailor_bullet_balance_ok(tailored)
        and _tailor_summary_engineering_voice_ok(tailored)
        and _tailor_summary_competencies_in_experience_ok(tailored)
        and _tailor_metric_ending_ratio_ok(tailored)
        and _tailor_bullet_rhythm_ok(tailored)
        and _tailor_bullet_structure_repetition_ok(tailored)
        and _tailor_ownership_bullets_ok(tailored, is_consulting_ai=is_consulting_ai)
        and _tailor_summary_distinctive_ok(tailored)
        and _tailor_role_pivot_ok(tailored, tailoring_strategy)
    )


def build_docx_highlight_keywords(
    job_description: str,
    parsed: ParsedResume,
    tailored: TailoredSections,
) -> list[str]:
    """Terms to bold in experience: top-weight JD tools, metrics — not every extracted keyword."""
    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        cleaned = re.sub(r"\s+", " ", (term or "").strip(" ,;."))
        if len(cleaned) < 3:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        terms.append(cleaned)

    for tech in extract_jd_tool_phrases(job_description)[:10]:
        _add(tech)
    for kw in extract_keywords(_extract_jd_priority_text(job_description) or job_description, top_k=12):
        _add(kw)

    for metric in extract_source_metrics(
        tailored.professional_experience or parsed.professional_experience,
        tailored.professional_summary or parsed.professional_summary,
        limit=16,
    ):
        _add(metric)

    for body in _bullet_bodies(tailored.professional_experience or ""):
        for match in _METRIC_SNIPPET_RE.finditer(body):
            _add(match.group(0))

    _tech_highlight_re = (
        r"\b(?:React(?:\.js)?|Angular|Vue(?:\.js)?|Node(?:\.js)?|TypeScript|JavaScript|Python|"
        r"Java|AWS|Azure|GCP|Docker|Kubernetes|Terraform|CI/CD|PostgreSQL|MongoDB|Redis|"
        r"GraphQL|REST(?:ful)?|FastAPI|Django|Flask|\.NET|Next(?:\.js)?|OpenAI|LangChain|"
        r"Pinecone|Celery|Pydantic|OpenTelemetry|Grafana|MCP|RAG|LLM|evals?|observability|"
        r"agentic|microservices?|vector\s+stores?|Shopify)\b"
    )
    for body in _bullet_bodies(tailored.professional_experience or parsed.professional_experience):
        for match in re.finditer(_tech_highlight_re, body, re.I):
            _add(match.group(0))

    summary_text = tailored.professional_summary or parsed.professional_summary or ""
    for match in re.finditer(_tech_highlight_re, summary_text, re.I):
        _add(match.group(0))

    return sorted(terms, key=len, reverse=True)


def _skills_highlight_max() -> int:
    raw = os.getenv("OPENAI_SKILLS_HIGHLIGHT_MAX", "10").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 10
    return max(3, min(n, 16))


def _extract_jd_priority_text(job_description: str) -> str:
    """Requirements / qualifications / responsibilities — weighted higher for skill highlights."""
    jd = (job_description or "").strip()
    if not jd:
        return ""
    chunks: list[str] = []
    section_starts = re.compile(
        r"(?:^|\n)\s*(?:requirements|qualifications|what you(?:'ll| will) do|"
        r"core focus|must have|required skills|key skills|you have|who you are|"
        r"key responsibilities|job description|responsibilities|preferred qualifications|skills)\b",
        re.I | re.M,
    )
    matches = list(section_starts.finditer(jd))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(jd)
        chunk = jd[start:end].strip()
        if len(chunk) > 40:
            chunks.append(chunk[:3000])
    return "\n\n".join(chunks)


def _parse_skill_tokens(skills_text: str) -> list[str]:
    tokens: list[str] = []
    for raw_line in (skills_text or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line[:60]:
            line = line.split(":", 1)[1]
        for part in re.split(r"[,;|/•·]", line):
            token = part.strip()
            if token and len(token) >= 2 and token.lower() not in STOPWORDS:
                tokens.append(token)
    return tokens


def _term_appears_in_skills(term: str, skills_text: str) -> bool:
    term = (term or "").strip()
    if len(term) < 2 or not skills_text:
        return False
    if re.match(r"^[\w\-./+#]+$", term):
        return bool(
            re.search(
                r"(?<![\w\-./+#])" + re.escape(term) + r"(?![\w\-./+#])",
                skills_text,
                re.I,
            )
        )
    return term.lower() in skills_text.lower()


_SKILL_HIGHLIGHT_STOPWORDS = frozenset(
    {
        "management", "customer", "order", "flow", "operations", "experience",
        "relationship", "tools", "frontend", "backend", "database", "practices",
        "communication", "leadership", "development", "platform", "integration",
        "process", "performance", "reporting", "compliance", "automation",
        "technical", "professional", "excellent", "strong", "skills",
    }
)


def _score_skill_token_against_jd(token: str, priority_text: str, full_jd: str) -> int:
    token_lower = token.lower()
    score = 0
    for kw in extract_keywords(priority_text, top_k=40):
        kw_lower = kw.lower()
        if kw_lower == token_lower:
            score += 6
        elif len(kw_lower) >= 4 and (kw_lower in token_lower or token_lower in kw_lower):
            score += 4
    for kw in extract_keywords(full_jd, top_k=24):
        kw_lower = kw.lower()
        if kw_lower == token_lower:
            score += 2
        elif len(kw_lower) >= 5 and kw_lower in token_lower:
            score += 1
    if _term_appears_in_skills(token, priority_text):
        score += 3
    return score


def _prune_substring_highlights(terms: list[str]) -> list[str]:
    kept: list[str] = []
    for term in terms:
        lower = term.lower()
        if any(lower != other.lower() and lower in other.lower() for other in terms):
            continue
        kept.append(term)
    return kept


def build_skills_highlight_keywords(job_description: str, skills_text: str) -> list[str]:
    """
    Return only the most job-critical skills to bold in the Skills section (not every keyword).
    Terms must be actual skill entries from the resume and score high against JD requirements.
    """
    skills = (skills_text or "").strip()
    if not skills:
        return []

    max_highlights = _skills_highlight_max()
    priority_text = _extract_jd_priority_text(job_description) or job_description
    tokens = _parse_skill_tokens(skills)

    scored: list[tuple[int, int, str]] = []
    for token in tokens:
        if len(token) < 2:
            continue
        token_lower = token.lower()
        if token_lower in STOPWORDS or token_lower in _SKILL_HIGHLIGHT_STOPWORDS:
            continue
        score = _score_skill_token_against_jd(token, priority_text, job_description)
        if score < 4:
            continue
        scored.append((score, len(token), token))

    scored.sort(key=lambda item: (-item[0], -item[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _score, _length, token in scored:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= max_highlights:
            break
    return _prune_substring_highlights(out)


def _extract_evidenced_career_stack(*texts: str) -> list[str]:
    """Tools/platforms evidenced anywhere in the resume (skills, summary, experience)."""
    seen: set[str] = set()
    out: list[str] = []
    combined = " ".join(t for t in texts if t)
    for term in list(_AI_ATS_TERMS) + list(_DEVOPS_ATS_TERMS):
        if _term_appears_in_skills(term, combined):
            key = term.lower()
            if key not in seen:
                seen.add(key)
                out.append(term)
    for match in _NAMED_TECH_RE.finditer(combined):
        term = match.group(0)
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    for token in _parse_skill_tokens(combined):
        key = token.lower()
        if key not in seen and len(token) >= 2:
            seen.add(key)
            out.append(token)
    return out


def _evidenced_stack_blob(*texts: str) -> str:
    return " ".join(_extract_evidenced_career_stack(*texts)).lower()


def _token_is_evidenced(token: str, *source_texts: str) -> bool:
    token = (token or "").strip()
    if not token or len(token) < 2:
        return False
    token_lower = token.lower()
    if token_lower in _SKILLS_SOFT_ONLY_TERMS or token_lower in _EVIDENCED_GENERIC_SKILL_TERMS:
        return True
    combined = " ".join(t for t in source_texts if t).lower()
    if token_lower in combined:
        return True
    if _term_appears_in_skills(token, combined):
        return True
    for evidenced in _extract_evidenced_career_stack(*source_texts):
        ev_lower = evidenced.lower()
        if token_lower == ev_lower or token_lower in ev_lower or ev_lower in token_lower:
            return True
    return False


def _skills_layout_mode(source: str) -> str:
    lines = [line.strip() for line in (source or "").splitlines() if line.strip()]
    if not lines:
        return "colon"
    colon_lines = sum(1 for line in lines if re.match(r"^[^:]+:\s*\S", line))
    if colon_lines >= max(2, int(len(lines) * 0.45)):
        return "colon"
    return "paired"


def _split_skill_tokens(raw: str) -> list[str]:
    tokens: list[str] = []
    for part in re.split(r"[,;|/•·]", raw or ""):
        token = part.strip()
        if token and len(token) >= 2:
            tokens.append(token)
    return tokens


def _parse_skill_categories(text: str) -> list[dict[str, object]]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return []
    layout = _skills_layout_mode(text)
    categories: list[dict[str, object]] = []
    if layout == "colon":
        for line in lines:
            match = re.match(r"^([^:]+):\s*(.*)$", line)
            if not match:
                continue
            categories.append(
                {"label": match.group(1).strip(), "tokens": _split_skill_tokens(match.group(2))}
            )
        return categories
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        colon_match = re.match(r"^([^:]+):\s*(.*)$", line)
        if colon_match and colon_match.group(2).strip():
            categories.append(
                {
                    "label": colon_match.group(1).strip(),
                    "tokens": _split_skill_tokens(colon_match.group(2)),
                }
            )
            idx += 1
            continue
        label = line.rstrip(":")
        tokens: list[str] = []
        if idx + 1 < len(lines):
            nxt = lines[idx + 1]
            if not re.match(r"^[^:]+:\s*\S", nxt) or _split_skill_tokens(nxt.split(":", 1)[-1]):
                if "," in nxt or ";" in nxt or len(nxt.split()) <= 8:
                    tokens = _split_skill_tokens(nxt)
                    idx += 2
                    categories.append({"label": label, "tokens": tokens})
                    continue
        categories.append({"label": label, "tokens": tokens})
        idx += 1
    return categories


def _format_skill_categories(categories: list[dict[str, object]], layout: str) -> str:
    lines: list[str] = []
    for cat in categories:
        label = str(cat.get("label", "")).strip()
        tokens = [str(t).strip() for t in (cat.get("tokens") or []) if str(t).strip()]
        if not label:
            continue
        if layout == "paired":
            lines.append(label if label.endswith(":") else label)
            lines.append(", ".join(tokens))
        else:
            lines.append(f"{label.rstrip(':')}: {', '.join(tokens)}".strip())
    return "\n".join(lines)


def _experience_headers_for_prompt(experience: str) -> str:
    """Role/company/date headers only — used when bullets must not be sent to the LLM."""
    return _experience_headers_only(experience)


def _experience_evidence_for_prompt(experience: str) -> str:
    """Full headers + source accomplishment bullets — ground truth for LLM rewrites."""
    return (experience or "").strip()


def _skill_fits_category(tool: str, category_label: str) -> bool:
    cat = category_label.lower()
    tool_l = tool.lower()
    rules: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("cloud", ("azure", "gcp", "aws", "cloud", "kubernetes", "docker", "opentelemetry")),
        ("generative", ("langchain", "openai", "rag", "llm", "mcp", "agentic", "eval", "retrieval", "embedding")),
        ("ai", ("langchain", "openai", "rag", "llm", "mcp", "agentic", "eval", "retrieval", "tool", "structured")),
        ("production", ("rag", "llm", "agentic", "mcp", "langchain", "openai", "eval", "deployment", "production")),
        ("observability", ("opentelemetry", "grafana", "datadog", "monitor", "tracing", "eval", "logging")),
        ("backend system", ("fastapi", "python", "api", "redis", "celery", "postgresql", "django", "pydantic")),
        ("infrastructure", ("terraform", "iac", "arm", "gitops", "infrastructure")),
        ("container", ("kubernetes", "docker", "helm", "k8s", "microservice", "container")),
        ("ci/cd", ("github", "devops", "ci", "cd", "git", "pipeline", "teamcity", "gitops")),
        ("programming", ("python", "bash", "powershell", "javascript", "yaml", "script")),
        ("operating", ("linux", "windows", "bash", "shell")),
        ("monitoring", ("datadog", "splunk", "monitor", "insights", "logging", "alert")),
        ("network", ("dns", "firewall", "tls", "routing", "subnet")),
        ("database", ("sql", "postgres", "mongo", "bigquery", "firestore", "database")),
        ("enterprise", ("vmware", "active directory", "servicenow")),
        ("methodolog", ("agile", "scrum", "kanban")),
    )
    for cat_key, hints in rules:
        if cat_key in cat:
            return any(h in tool_l for h in hints)
    return False


def _ai_mandatory_terms_for_category(label: str) -> list[str]:
    key = label.lower()
    if any(x in key for x in ("ai", "generative", "llm", "ml")):
        return list(_AI_MANDATORY_SKILLS_TERMS)
    if "backend" in key or "data" in key:
        return ["Python", "FastAPI", "Pydantic", "PostgreSQL", "Redis", "LangChain", "Celery"]
    if "cloud" in key or "production" in key or "infrastructure" in key:
        return ["AWS", "Docker", "CI/CD pipelines", "OpenTelemetry", "Grafana", "testing", "incident response"]
    if "engineering" in key or "practices" in key or "frontend" in key:
        return [
            "technical leadership",
            "client communication",
            "maintainability",
            "production debugging",
            "feedback loops",
            "API integrations",
        ]
    return []


def build_ai_skills_for_template(
    source_skills: str,
    tailored_skills: str,
    job_description: str,
) -> str:
    """JD + BOI-style AI skills: mandatory MCP/tool use/structured outputs in AI categories."""
    base = build_jd_skills_for_template(
        source_skills,
        tailored_skills,
        job_description,
        is_devops_role=False,
    )
    layout = _skills_layout_mode(source_skills)
    categories = _parse_skill_categories(base)
    if not categories:
        return base

    merged: list[dict[str, object]] = []
    for cat in categories:
        label = str(cat.get("label", "")).strip()
        tokens = [str(t).strip() for t in (cat.get("tokens") or []) if str(t).strip()]
        mandatory = _ai_mandatory_terms_for_category(label)
        combined: list[str] = []
        seen: set[str] = set()
        for token in mandatory + tokens:
            key = token.lower()
            if key in seen:
                continue
            if token in mandatory and not _token_is_evidenced(token, source_skills):
                continue
            seen.add(key)
            combined.append(token)
        merged.append({"label": label, "tokens": _dedupe_skill_tokens(combined)[:16]})
    return _format_skill_categories(merged, layout)


def build_jd_skills_for_template(
    source_skills: str,
    tailored_skills: str,
    job_description: str,
    *,
    is_devops_role: bool = False,
) -> str:
    """
    Build JD-optimized skill tool lists under the source resume's category labels.
    Category header lines are never changed — only tool content is replaced for ATS.
    """
    source = (source_skills or "").strip()
    tailored = coerce_skills_text(tailored_skills) or (tailored_skills or "").strip()
    if not source:
        return tailored
    layout = _skills_layout_mode(source)
    source_cats = _parse_skill_categories(source)
    if not source_cats:
        return _normalize_skills_preserving_layout(tailored, source)

    tailored_map = {
        str(cat.get("label", "")).strip().lower(): [
            str(t).strip() for t in (cat.get("tokens") or []) if str(t).strip()
        ]
        for cat in _parse_skill_categories(tailored)
    }
    priority_text = _extract_jd_priority_text(job_description) or job_description
    jd_tools = extract_jd_tool_phrases(job_description)
    merged: list[dict[str, object]] = []

    for src_cat in source_cats:
        label = str(src_cat.get("label", "")).strip()
        key = label.lower()
        tokens: list[str] = list(tailored_map.get(key, []))
        if not tokens:
            tokens = [str(t).strip() for t in (src_cat.get("tokens") or []) if str(t).strip()]

        for tool in jd_tools:
            if tool.lower() in {t.lower() for t in tokens}:
                continue
            if _skill_fits_category(tool, label):
                tokens.append(tool)

        if is_devops_role:
            tokens = [t for t in tokens if t.lower() not in _SKILLS_DEVOPS_NOISE_TERMS]

        tokens.sort(
            key=lambda t: (
                -_score_skill_token_against_jd(t, priority_text, job_description),
                t.lower(),
            )
        )
        max_per = 10 if is_devops_role else 14
        merged.append({"label": label, "tokens": _dedupe_skill_tokens(tokens)[:max_per]})

    return _format_skill_categories(merged, layout)


def build_evidence_based_skills(
    source_skills: str,
    tailored_skills: str,
    job_description: str,
    *,
    profile_stack: list[str],
    summary: str = "",
    experience: str = "",
    is_devops_role: bool = False,
) -> str:
    """Merge tailored skills into the source layout using only interview-defensible, JD-relevant tools."""
    source = (source_skills or "").strip()
    tailored = (tailored_skills or "").strip()
    if not source:
        return tailored or source
    layout = _skills_layout_mode(source)
    source_cats = _parse_skill_categories(source)
    if not source_cats:
        return tailored or source

    priority_text = _extract_jd_priority_text(job_description) or job_description
    tailored_cats = _parse_skill_categories(coerce_skills_text(tailored) or tailored)
    evidence_texts = (source, summary, experience)
    merged: list[dict[str, object]] = []

    for src_cat in source_cats:
        label = str(src_cat.get("label", "")).strip()
        src_tokens = [str(t).strip() for t in (src_cat.get("tokens") or []) if str(t).strip()]
        tail_tokens: list[str] = []
        label_lower = label.lower()
        for tail_cat in tailored_cats:
            tail_label = str(tail_cat.get("label", "")).strip().lower()
            if tail_label == label_lower or label_lower in tail_label or tail_label in label_lower:
                tail_tokens.extend(str(t).strip() for t in (tail_cat.get("tokens") or []) if str(t).strip())

        candidates: list[str] = []
        seen: set[str] = set()
        for token in src_tokens + tail_tokens:
            key = token.lower()
            if key in seen:
                continue
            if not _token_is_evidenced(token, *evidence_texts):
                continue
            if is_devops_role and not _skill_token_jd_relevant(token, job_description, is_devops_role=True):
                continue
            seen.add(key)
            candidates.append(token)

        if not candidates and src_tokens:
            candidates = [
                t
                for t in src_tokens
                if _token_is_evidenced(t, *evidence_texts)
                and t.lower() not in _SKILLS_DEVOPS_NOISE_TERMS
            ][:4]

        candidates.sort(
            key=lambda t: (
                -_score_skill_token_against_jd(t, priority_text, job_description),
                t.lower(),
            )
        )
        max_per_cat = 8 if is_devops_role else 14
        merged.append({"label": label, "tokens": _dedupe_skill_tokens(candidates)[:max_per_cat]})

    return _format_skill_categories(merged, layout)


def _dedupe_skill_tokens(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _normalize_skills_preserving_layout(text: str, source_skills: str) -> str:
    """Keep paired/colon layout from the source resume when normalizing skills output."""
    source = (source_skills or "").strip()
    normalized = coerce_skills_text(text)
    if not normalized:
        return source
    if not source:
        return _skills_as_categorized_lines(normalized)
    layout = _skills_layout_mode(source)
    if layout == "colon":
        return _skills_as_categorized_lines(normalized)
    parsed = _parse_skill_categories(normalized)
    if parsed:
        return _format_skill_categories(parsed, layout)
    return normalized


def _skills_as_categorized_lines(text: str) -> str:
    """Normalize skills to one category per line: AI Engineering: a, b, c"""
    raw = coerce_skills_text(text)
    if not raw:
        return ""
    out: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        s = re.sub(r"^[•\-\*\u2022]+\s*", "", s)
        s = re.sub(r"\s+", " ", s)
        if not re.match(r"^[^:]+:\s*\S", s):
            continue
        out.append(s)
    return "\n".join(out)


def coerce_skills_text(raw: object) -> str:
    """Convert LLM skills (string, dict, or dict-literal string) to plain categorized lines."""
    if raw is None:
        return ""
    if isinstance(raw, dict):
        lines: list[str] = []
        for key, value in raw.items():
            label = str(key).strip().rstrip(":")
            body = re.sub(r"\s+", " ", str(value).strip(" ,"))
            if label and body:
                lines.append(f"{label}: {body}")
        return "\n".join(lines)
    text = str(raw).strip()
    if not text:
        return ""
    if text.startswith("{") and ":" in text:
        import ast

        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return coerce_skills_text(parsed)
        except (SyntaxError, ValueError):
            pass
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return coerce_skills_text(parsed)
        except json.JSONDecodeError:
            pass
    return text


def _tailor_skills_format_ok(skills: str, *, source_skills: str = "") -> bool:
    if not (skills or "").strip():
        return False
    if "{" in skills and ":" in skills and skills.strip().startswith("{"):
        return False
    layout = _skills_layout_mode(source_skills or skills)
    if layout == "paired":
        categories = _parse_skill_categories(skills)
        return len(categories) >= 3 and all(str(cat.get("label", "")).strip() for cat in categories)
    normalized = _skills_as_categorized_lines(skills)
    if not normalized:
        return False
    lines = [ln for ln in normalized.splitlines() if ln.strip()]
    return len(lines) >= 3 and all(":" in ln for ln in lines)


def _tailor_bullet_balance_ok(tailored: TailoredSections) -> bool:
    """Reject resumes where most bullets lead with metrics instead of technical method."""
    bodies = _bullet_bodies(tailored.professional_experience or "")
    if len(bodies) < 4:
        return True
    metric_first = 0
    for body in bodies:
        lower = body.lower()
        if _METRIC_SNIPPET_RE.search(body) and not (
            _NAMED_TECH_RE.search(body) or _ENGINEERING_PRACTICE_RE.search(body)
        ):
            metric_first += 1
        elif re.search(
            r"^(?:spearheaded|engineered|developed|created|established|enhanced|automated|implemented|built)\b"
            r"[^.]{0,90}\d+%",
            lower,
        ):
            metric_first += 1
    return metric_first <= max(3, int(len(bodies) * 0.22))


def _offline_tailor_structured(parsed: ParsedResume, jd: str) -> TailoredSections:
    keywords = extract_keywords(jd, top_k=26)
    kline = ", ".join(keywords[:20])

    summ = (parsed.professional_summary or "").strip()
    if summ:
        professional_summary = (
            summ + "\n\n[Role alignment — weave these keywords where truthful: " + kline + "]"
        )
    else:
        professional_summary = (
            "Professional summary oriented to role themes: "
            + kline
            + ". Lead with outcomes and tools already evidenced in your experience."
        )

    exp = (parsed.professional_experience or "").strip()
    role_count = _count_experience_roles(exp) or 1
    bullets_per_role = _progressive_ats_bullets_per_role(role_count)
    per_role_hint = ", ".join(str(n) for n in bullets_per_role)
    if not exp:
        exp = "[Paste your roles and bullets under Professional Experience in the source resume.]"

    sk = (parsed.skills or "").strip()
    if sk:
        skills_raw = (
            sk
            + "\n\nPosting-aligned terms to weave in when accurate: "
            + kline
            + "."
        )
    else:
        skills_raw = (
            "Frontend: add comma-separated UI frameworks and libraries from your experience.\n"
            "Backend: add languages, runtimes, and API styles you have used.\n"
            "Database: add databases and data tools you have used.\n"
            "DevOps & cloud: add CI/CD, containers, and hosting where applicable.\n"
            "Other: "
            + kline
        )

    return TailoredSections(
        contact=(parsed.contact or "").strip(),
        professional_summary=professional_summary.strip(),
        professional_experience=(parsed.professional_experience or "").strip(),
        skills=_skills_as_categorized_lines(skills_raw),
        education=(parsed.education or "").strip(),
        other=(parsed.other or "").strip(),
    )


STRUCTURED_SYSTEM = """You are a principal engineering recruiter with 20 years of experience at top tech companies.
Your job is NOT to maximize keyword density — it is to produce a resume that reads human, truthful, and ATS-strong.

Return ONLY a JSON object with exactly these keys (all strings, use \\n for line breaks inside values):
"contact", "professional_summary", "professional_experience", "skills", "education", "other"

ONLY EDIT THESE 3 SECTIONS (JD-driven rewrite grounded in source truth):
1. professional_summary — engineering identity (role, years, specialization, scope).
2. professional_experience — REWRITE accomplishment bullets per employer from SOURCE bullets.
3. skills — JD-optimized tool lists under each source category label, ordered by importance to THIS job.

FROZEN — return verbatim from SOURCE_SECTIONS_JSON:
- contact, education, other

HUMAN WRITING RULES (mandatory):
- PREFER bullet verbs: Built, Designed, Introduced, Standardized, Migrated, Debugged, Owned, Led.
- NEVER start bullets with: Spearheaded, Engineered, Developed, Created, Established, Leveraged, Utilized, Facilitated.
- NEVER use corporate filler: comprehensive, significantly enhancing, streamlining, facilitating.
- NEVER open summary with: Results-driven, Dynamic, Innovative, Passionate, Highly motivated.
- NEVER use first person in summary (I am, my role, we built).
- NEVER write generic summaries like "AI Engineer with N years of experience" without a distinctive engineering identity.
- Each bullet has an assigned INTENT (Architecture, Ownership, Reliability, etc.) — vary structure; not Verb→Tech→Metric every line.
- No more than 40% of bullets may END with a quantified metric.
- Build an engineering narrative (career story), not a keyword cloud.
- Do NOT repeat the same JD keyword in summary, skills, AND experience. Max 2 mentions per tool/phrase total.
- Every core competency in summary must appear in at least one experience bullet.
- Prioritize evidence over keyword density — reason about each JD tool before using it.

Experience rules:
- Output professional_experience as ONLY new "- " bullet lines (no company names, titles, or dates).
- Rewrite SOURCE bullets — preserve real projects, tools, scale, and metrics; do not invent work.
- Follow the BULLET INTENT PLAN — each bullet serves a different purpose (architecture vs ownership vs reliability).
- Cover EVERY employer in chronological order (oldest first). Multiple roles at one company = separate blocks.
- BULLETS_PER_ROLE = minimum per employer; fill template slots; 3+ bullets when source supports it.
- CAREER ARC: oldest = simpler; middle = growing ownership; most recent = deepest JD match.
- Each employer block must read distinct — never reuse the same bullet template across companies.

professional_summary rules:
- 3–4 sentences: role + years + specialization + technical strengths + engineering scope.
- Engineering identity — like someone introducing themselves, not a keyword summary.
- Example tone: "Senior AI Engineer with a background in building production AI platforms, retrieval systems, and FastAPI services..."
- Do NOT mirror the JD sentence-by-sentence.

skills rules:
- Use the role-specific category labels from RESUME STRATEGY (do not reuse the same generic categories every time).
- Order categories by JD importance. List tools plainly.
- Never add a tool to skills unless an experience bullet supports it.

Truth boundaries:
- NEVER invent employers, schools, degrees, dates, or certifications.

No markdown fences, no commentary outside JSON.""" + "\n\n" + CANONICAL_TAILORING_POLICY


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _sanitize_llm_error(exc: Exception) -> str:
    """Short user-safe message — never include API keys."""
    msg = str(exc).strip().replace("\n", " ")
    if len(msg) > 180:
        msg = msg[:177] + "..."
    msg = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", msg)
    name = type(exc).__name__
    if not msg:
        return name
    return f"{name}: {msg}"


JD_ANALYSIS_SYSTEM = """You analyze job descriptions for resume tailoring.
Return ONLY a JSON object with these keys:
- target_role_title (string)
- role_archetype (one of: java_backend, ai_engineer, devops, aws_infrastructure_engineer, consulting_ai_engineer, backend, fullstack, generic)
- required_tools (array of strings, ordered by importance)
- preferred_tools (array of strings)
- core_responsibilities (array of short phrases)
- seniority_level (string: junior, mid, senior, staff, principal, or unknown)
- culture_signals (array of strings)
No markdown, no commentary."""

STRATEGY_SYSTEM = """You are a senior technical recruiter planning how to tailor a candidate resume to ONE target job.
The resume must optimize for the TARGET ROLE — not the candidate's strongest unrelated profile.
Return ONLY a JSON object with these keys:
- primary_story (string)
- secondary_story (string)
- summary_angle (1-2 sentences: how the summary should open and what identity to project)
- mode (full, moderate, or conservative)
- compatibility (number 0-1)
- promote (array: evidence-backed tools/skills to emphasize — never invent)
- de_emphasize (array: themes/tools to move later or minimize)
- experience_guidance (string: how to reorder/reframe bullets across employers)
- skills_categories (array: category labels in display order for this JD)
- bullet_priorities (array: themes for the most recent role bullets, in order)
Ground every promote item in candidate evidence. Do not add tools with zero evidence."""

REVIEW_SYSTEM = """You are a Senior Engineering Hiring Manager screening ONE resume for ONE job opening.
You have 30 seconds. Be harsh but fair — flag real rejection reasons, not nitpicks.
Return ONLY a JSON object with these keys:
- rejection_reasons (array of specific strings — empty if none)
- needs_fix (boolean)
- professional_summary (full replacement text when needs_fix, else empty string)
- professional_experience (full replacement bullet lines starting with "- " when needs_fix, else empty string)
- skills (full replacement skills text when needs_fix, else empty string)
Rules when fixing:
- Do NOT invent employers, degrees, dates, or tools unsupported by the draft or source.
- Fix narrative misalignment (wrong specialty lead, keyword stuffing, generic AI voice).
- Keep human engineering tone — not corporate filler.
- Preserve frozen sections — only fix summary, experience bullets, and skills."""


def _openai_pipeline_mode() -> str:
    return os.getenv("OPENAI_PIPELINE", "v2").strip().lower()


def _openai_model_fast() -> str:
    return os.getenv("OPENAI_MODEL_FAST", "").strip() or "gpt-4o-mini"


def _openai_model_write() -> str:
    return (
        os.getenv("OPENAI_MODEL_WRITE", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip()
        or "chat-latest"
    )


def _openai_model_strategy() -> str:
    return os.getenv("OPENAI_MODEL_STRATEGY", "").strip() or _openai_model_write()


def _openai_model_review() -> str:
    return os.getenv("OPENAI_MODEL_REVIEW", "").strip() or _openai_model_write()


def _strategy_to_dict(strategy: TailoringStrategy) -> dict[str, object]:
    return {
        "jd_archetype": strategy.jd_archetype,
        "candidate_archetype": strategy.candidate_archetype,
        "compatibility": strategy.compatibility,
        "mode": strategy.mode,
        "primary_story": strategy.primary_story,
        "secondary_story": strategy.secondary_story,
        "promote": strategy.promote,
        "de_emphasize": strategy.de_emphasize,
        "jd_role_title": strategy.jd_role_title,
        "summary_angle": strategy.summary_angle,
        "experience_guidance": strategy.experience_guidance,
        "skills_categories": strategy.skills_categories,
        "bullet_priorities": strategy.bullet_priorities,
    }


def _merge_llm_strategy(base: TailoringStrategy, llm: dict[str, object]) -> TailoringStrategy:
    def _str_list(key: str, fallback: list[str]) -> list[str]:
        raw = llm.get(key)
        if not isinstance(raw, list):
            return fallback
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out or fallback

    promote = list(dict.fromkeys(_str_list("promote", base.promote) + base.promote))[:14]
    de_em = list(dict.fromkeys(_str_list("de_emphasize", base.de_emphasize) + base.de_emphasize))[:14]
    mode = str(llm.get("mode") or base.mode).strip().lower()
    if mode not in ("full", "moderate", "conservative"):
        mode = base.mode
    try:
        compat = float(llm.get("compatibility", base.compatibility))
    except (TypeError, ValueError):
        compat = base.compatibility
    skills_cats = _str_list("skills_categories", base.skills_categories)
    if not skills_cats:
        arch = base.jd_archetype
        skills_cats = list(_ROLE_ARCHETYPE_TAXONOMIES.get(arch, []))
    return TailoringStrategy(
        jd_archetype=base.jd_archetype,
        candidate_archetype=base.candidate_archetype,
        compatibility=round(min(0.95, max(0.2, compat)), 2),
        mode=mode,
        primary_story=str(llm.get("primary_story") or base.primary_story).strip() or base.primary_story,
        secondary_story=str(llm.get("secondary_story") or base.secondary_story).strip() or base.secondary_story,
        promote=promote,
        de_emphasize=de_em,
        jd_role_title=base.jd_role_title,
        summary_angle=str(llm.get("summary_angle") or base.summary_angle).strip(),
        experience_guidance=str(llm.get("experience_guidance") or base.experience_guidance).strip(),
        skills_categories=skills_cats,
        bullet_priorities=_str_list("bullet_priorities", base.bullet_priorities),
    )


def _merge_jd_analysis_llm(
    llm: dict[str, object],
    *,
    target_role: str,
    job_description: str,
    is_consulting_ai: bool,
    is_aws_infrastructure: bool,
) -> dict[str, object]:
    python_arch = detect_jd_role_archetype(
        target_role,
        job_description,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infrastructure,
    )
    llm_arch = str(llm.get("role_archetype") or "").strip().lower()
    if python_arch in ("java_backend", "aws_infrastructure_engineer", "consulting_ai_engineer", "devops"):
        role_archetype = python_arch
    elif llm_arch in _ROLE_ARCHETYPE_TAXONOMIES or llm_arch == "generic":
        role_archetype = llm_arch
    else:
        role_archetype = python_arch
    required = llm.get("required_tools")
    if not isinstance(required, list) or not required:
        required = extract_jd_tool_phrases(job_description)[:12]
    else:
        required = [str(x).strip() for x in required if str(x).strip()]
    preferred = llm.get("preferred_tools")
    if not isinstance(preferred, list):
        preferred = extract_keywords(job_description, top_k=12)
    else:
        preferred = [str(x).strip() for x in preferred if str(x).strip()]
    responsibilities = llm.get("core_responsibilities")
    if not isinstance(responsibilities, list):
        responsibilities = extract_jd_responsibility_phrases(job_description)[:10]
    else:
        responsibilities = [str(x).strip() for x in responsibilities if str(x).strip()]
    return {
        "target_role_title": str(llm.get("target_role_title") or target_role).strip() or target_role,
        "role_archetype": role_archetype,
        "required_tools": required,
        "preferred_tools": preferred,
        "core_responsibilities": responsibilities,
        "seniority_level": str(llm.get("seniority_level") or "unknown").strip(),
        "culture_signals": [
            str(x).strip() for x in (llm.get("culture_signals") or []) if str(x).strip()
        ],
    }


def _sections_from_json(data: dict[str, object], parsed: ParsedResume) -> TailoredSections:
    return TailoredSections(
        contact=str(data.get("contact", parsed.contact or "")).strip(),
        professional_summary=str(data.get("professional_summary", "")).strip(),
        professional_experience=str(data.get("professional_experience", "")).strip(),
        skills=_normalize_skills_preserving_layout(
            coerce_skills_text(str(data.get("skills", ""))),
            parsed.skills,
        ),
        education=str(data.get("education", parsed.education or "")).strip(),
        other=str(data.get("other", parsed.other or "")).strip(),
        experience_role_titles="",
    )


def _apply_review_fixes(draft: TailoredSections, review: dict[str, object], parsed: ParsedResume) -> TailoredSections:
    if not review.get("needs_fix"):
        return draft
    summary = str(review.get("professional_summary") or "").strip()
    experience = str(review.get("professional_experience") or "").strip()
    skills = str(review.get("skills") or "").strip()
    return TailoredSections(
        contact=draft.contact,
        professional_summary=summary or draft.professional_summary,
        professional_experience=experience or draft.professional_experience,
        skills=_normalize_skills_preserving_layout(
            coerce_skills_text(skills) if skills else draft.skills,
            parsed.skills,
        ),
        education=draft.education,
        other=draft.other,
        experience_role_titles=draft.experience_role_titles,
    )


async def _llm_json_call(
    client: AsyncOpenAI,
    *,
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int | None = None,
) -> dict[str, object]:
    completion = await client.chat.completions.create(
        model=model,
        **chat_completion_controls(
            model,
            max_output_tokens=max_tokens or _tailor_max_tokens(),
            temperature=temperature,
        ),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    raw = completion.choices[0].message.content or "{}"
    data = _parse_json_object(raw)
    return data if isinstance(data, dict) else {}


async def _llm_analyze_jd(
    client: AsyncOpenAI,
    jd: str,
    *,
    target_role: str,
    is_consulting_ai: bool,
    is_aws_infrastructure: bool,
) -> dict[str, object]:
    heuristic = build_jd_stage1_analysis_prompt(jd, target_job_role=target_role)
    user = (
        f"{heuristic}\n"
        "Analyze the job description below and return structured JSON.\n\n"
        f"JOB DESCRIPTION:\n{jd.strip()}"
    )
    llm = await _llm_json_call(
        client,
        model=_openai_model_fast(),
        system=JD_ANALYSIS_SYSTEM,
        user=user,
        temperature=0.2,
        max_tokens=2048,
    )
    return _merge_jd_analysis_llm(
        llm,
        target_role=target_role,
        job_description=jd,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infrastructure,
    )


async def _llm_refine_strategy(
    client: AsyncOpenAI,
    parsed: ParsedResume,
    jd: str,
    *,
    target_role: str,
    evidence_map: dict[str, int],
    base_strategy: TailoringStrategy,
    jd_analysis: dict[str, object],
) -> TailoringStrategy:
    evidence_block = format_candidate_evidence_for_prompt(evidence_map, jd_analysis.get("required_tools", []))
    user = (
        "Refine the tailoring strategy for this candidate and job.\n"
        f"JD ANALYSIS:\n{json.dumps(jd_analysis, ensure_ascii=False)}\n\n"
        f"PYTHON BASELINE STRATEGY:\n{json.dumps(_strategy_to_dict(base_strategy), ensure_ascii=False)}\n\n"
        f"{evidence_block}\n"
        f"CANDIDATE SUMMARY (source):\n{(parsed.professional_summary or '')[:1200]}\n\n"
        f"CANDIDATE SKILLS (source):\n{(parsed.skills or '')[:1200]}\n\n"
        f"TARGET ROLE: {target_role}\n\n"
        f"JOB DESCRIPTION:\n{jd.strip()[:6000]}"
    )
    llm = await _llm_json_call(
        client,
        model=_openai_model_strategy(),
        system=STRATEGY_SYSTEM,
        user=user,
        temperature=0.45,
        max_tokens=3072,
    )
    merged = _merge_llm_strategy(base_strategy, llm)
    if not merged.skills_categories:
        merged.skills_categories = list(
            _ROLE_ARCHETYPE_TAXONOMIES.get(merged.jd_archetype, [])
        )
    return merged


def _build_v2_write_prompt(
    *,
    parsed: ParsedResume,
    jd: str,
    target_role: str,
    strategy: TailoringStrategy,
    jd_analysis: dict[str, object],
    evidence_map: dict[str, int],
    jd_tools: list[str],
    source_experience: str,
    payload: dict[str, object],
    bullet_intent_plan: str,
    career_progression: str,
    human_voice: str,
    bullets_per_role: list[int],
    template_slots: list[int],
    stats: dict[str, int],
    years: str,
    stack_line: str,
) -> str:
    strategy_prompt = build_tailoring_strategy_prompt(strategy)
    evidence_block = format_candidate_evidence_for_prompt(evidence_map, jd_tools)
    jd_weighted = build_jd_weighted_tools_prompt(jd, evidence_map)
    per_role_text = ", ".join(str(n) for n in bullets_per_role)
    preserve_lines: list[str] = []
    if years:
        preserve_lines.append(f'- Years of experience (keep in summary): "{years}"')
    if stack_line:
        preserve_lines.append(f"- SOURCE_TECH_STACK (evidence only): {stack_line}")
    preserve_block = "\n".join(preserve_lines) + "\n\n" if preserve_lines else ""
    return (
        "STAGE 4 — RESUME WRITING. Rewrite ONLY summary, experience bullets, and skills.\n"
        f"JD ANALYSIS:\n{json.dumps(jd_analysis, ensure_ascii=False)}\n\n"
        + strategy_prompt
        + jd_weighted
        + evidence_block
        + bullet_intent_plan
        + career_progression
        + human_voice
        + "- professional_summary: 3–4 sentences following summary_angle and primary_story.\n"
        + "- professional_experience: output ONLY new \"- \" lines (no headers); follow bullet_priorities.\n"
        + "- skills: use skills_categories from strategy; order tools by JD importance.\n"
        + "- FROZEN — return contact, education, other verbatim from source.\n"
        + "- Ground every bullet in source accomplishments — do not fabricate.\n"
        + f"- BULLETS_PER_ROLE (minimum per employer): {per_role_text}\n"
        + f"- TEMPLATE_BULLET_SLOTS: {', '.join(str(n) for n in template_slots)}\n"
        + f"- Source skills layout: {stats.get('skills_lines', 0)} lines.\n\n"
        + preserve_block
        + f"TARGET ROLE: {target_role}\n\n"
        + "JOB DESCRIPTION:\n"
        + jd.strip()
        + "\n\nSOURCE EXPERIENCE:\n"
        + source_experience
        + "\n\nSOURCE_SECTIONS_JSON:\n"
        + json.dumps(payload, ensure_ascii=False)
    )


async def _llm_write_resume(
    client: AsyncOpenAI,
    parsed: ParsedResume,
    write_prompt: str,
) -> TailoredSections:
    data = await _llm_json_call(
        client,
        model=_openai_model_write(),
        system=STRUCTURED_SYSTEM,
        user=write_prompt,
        temperature=_tailor_temperature(),
    )
    return _sections_from_json(data, parsed)


async def _llm_review_and_fix(
    client: AsyncOpenAI,
    parsed: ParsedResume,
    jd: str,
    *,
    target_role: str,
    strategy: TailoringStrategy,
    jd_analysis: dict[str, object],
    draft: TailoredSections,
    source_experience: str,
) -> TailoredSections:
    user = (
        "Review this tailored resume draft for ONE job. Fix rejection-worthy issues only.\n"
        f"TARGET ROLE: {target_role}\n"
        f"JD ANALYSIS:\n{json.dumps(jd_analysis, ensure_ascii=False)}\n\n"
        f"TAILORING STRATEGY:\n{json.dumps(_strategy_to_dict(strategy), ensure_ascii=False)}\n\n"
        f"SOURCE EXPERIENCE (ground truth — do not invent beyond this):\n{source_experience[:8000]}\n\n"
        "DRAFT RESUME:\n"
        f"SUMMARY:\n{draft.professional_summary}\n\n"
        f"EXPERIENCE BULLETS:\n{draft.professional_experience}\n\n"
        f"SKILLS:\n{draft.skills}\n\n"
        f"JOB DESCRIPTION:\n{jd.strip()[:5000]}"
    )
    review = await _llm_json_call(
        client,
        model=_openai_model_review(),
        system=REVIEW_SYSTEM,
        user=user,
        temperature=0.35,
        max_tokens=_tailor_max_tokens(),
    )
    reasons = review.get("rejection_reasons")
    if isinstance(reasons, list) and reasons:
        logger.info("Resume review flagged %d issue(s): %s", len(reasons), "; ".join(str(r) for r in reasons[:5]))
    return _apply_review_fixes(draft, review, parsed)


async def _run_multi_stage_pipeline(
    client: AsyncOpenAI,
    parsed: ParsedResume,
    jd: str,
    *,
    target_role: str,
    tailoring_strategy: TailoringStrategy,
    evidence_map: dict[str, int],
    jd_tools: list[str],
    source_experience: str,
    payload: dict[str, object],
    bullet_intent_plan: str,
    career_progression: str,
    human_voice: str,
    bullets_per_role: list[int],
    template_slots: list[int],
    stats: dict[str, int],
    years: str,
    stack_line: str,
    is_consulting_ai: bool,
    is_aws_infra: bool,
    is_ai_role: bool,
    is_devops_role: bool,
    has_llm_stack: bool,
    has_devops_stack: bool,
    ats_terms: list[str],
) -> TailoredSections:
    logger.info(
        "Tailor v2 pipeline: fast=%s strategy=%s write=%s review=%s",
        _openai_model_fast(),
        _openai_model_strategy(),
        _openai_model_write(),
        _openai_model_review(),
    )
    jd_analysis = await _llm_analyze_jd(
        client,
        jd,
        target_role=target_role,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infra,
    )
    strategy = await _llm_refine_strategy(
        client,
        parsed,
        jd,
        target_role=target_role,
        evidence_map=evidence_map,
        base_strategy=tailoring_strategy,
        jd_analysis=jd_analysis,
    )
    write_prompt = _build_v2_write_prompt(
        parsed=parsed,
        jd=jd,
        target_role=target_role,
        strategy=strategy,
        jd_analysis=jd_analysis,
        evidence_map=evidence_map,
        jd_tools=jd_tools,
        source_experience=source_experience,
        payload=payload,
        bullet_intent_plan=bullet_intent_plan,
        career_progression=career_progression,
        human_voice=human_voice,
        bullets_per_role=bullets_per_role,
        template_slots=template_slots,
        stats=stats,
        years=years,
        stack_line=stack_line,
    )
    draft = await _llm_write_resume(client, parsed, write_prompt)
    reviewed = await _llm_review_and_fix(
        client,
        parsed,
        jd,
        target_role=target_role,
        strategy=strategy,
        jd_analysis=jd_analysis,
        draft=draft,
        source_experience=source_experience,
    )

    def _quality_v2(t: TailoredSections) -> bool:
        return _tailor_quality_ok(
            parsed,
            t,
            bullets_per_role=bullets_per_role,
            ats_terms=ats_terms,
            jd_tools=jd_tools,
            is_ai_role=is_ai_role,
            is_devops_role=is_devops_role,
            has_llm_stack=has_llm_stack,
            has_devops_stack=has_devops_stack,
            is_consulting_ai=is_consulting_ai,
            job_description=jd,
            tailoring_strategy=strategy,
        )

    if _quality_v2(reviewed):
        return reviewed

    retry_prompt = (
        write_prompt
        + "\n\nQUALITY RETRY after automated review:\n"
        "- Sound human; vary bullet structure; max 40% metric-ending bullets.\n"
        "- Align with tailoring strategy — optimize for TARGET ROLE.\n"
        "- Rewrite every source bullet; do not leave generic filler.\n"
    )
    draft2 = await _llm_write_resume(client, parsed, retry_prompt)
    reviewed2 = await _llm_review_and_fix(
        client,
        parsed,
        jd,
        target_role=target_role,
        strategy=strategy,
        jd_analysis=jd_analysis,
        draft=draft2,
        source_experience=source_experience,
    )
    return reviewed2


def _openai_client(api_key: str) -> AsyncOpenAI:
    timeout_raw = os.getenv("OPENAI_TIMEOUT_SECONDS", "120").strip()
    try:
        timeout = float(timeout_raw)
    except ValueError:
        timeout = 120.0
    return AsyncOpenAI(api_key=api_key, timeout=max(30.0, min(timeout, 900.0)))


async def _llm_tailor_structured(
    parsed: ParsedResume,
    jd: str,
    api_key: str,
    *,
    target_job_role: str = "",
    role_count: int | None = None,
    docx_bullet_slots: list[int] | None = None,
) -> TailoredSections:
    client = _openai_client(api_key)
    stats = _source_section_stats(parsed)
    target_role = _resolve_role_context(target_job_role, jd)
    is_ai_role = is_jd_ai_focused(target_role, jd)
    is_devops_role = _is_devops_role(target_role, jd)
    is_consulting_ai = _is_applied_ai_consulting_jd(target_role, jd)
    is_aws_infra = is_aws_infrastructure_jd(target_role, jd)
    evidence_map = build_candidate_evidence_map(
        parsed.skills,
        parsed.professional_summary,
        parsed.professional_experience,
    )
    tailoring_strategy = build_tailoring_strategy(
        parsed,
        jd,
        evidence_map,
        target_job_role=target_role,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infra,
    )
    is_java_backend = tailoring_strategy.jd_archetype == "java_backend"
    profile_stack = _extract_evidenced_career_stack(
        parsed.skills,
        parsed.professional_summary,
        parsed.professional_experience,
    )
    ats_terms = build_ats_priority_terms(
        jd,
        target_job_role=target_role,
        skills=parsed.skills,
        summary=parsed.professional_summary,
        experience=parsed.professional_experience,
    )
    jd_tools = extract_jd_tool_phrases(jd)
    jd_phrases = extract_jd_responsibility_phrases(jd)
    source_metrics = extract_source_metrics(
        parsed.professional_experience,
        parsed.professional_summary,
        limit=14,
    )
    keyword_line = ", ".join(ats_terms[:36])
    stack_line = ", ".join(profile_stack[:20])
    years = extract_years_of_experience(parsed.professional_summary, parsed.contact)
    resolved_role_count = _resolve_role_count(parsed, role_count)
    ats_bullets_per_role = _progressive_ats_bullets_per_role(resolved_role_count)
    bullets_per_role, _docx_export_caps = _resolve_bullets_per_role_for_tailor(
        parsed,
        resolved_role_count,
        docx_bullet_slots=docx_bullet_slots,
    )
    template_slots = _experience_bullets_per_role(parsed.professional_experience)
    per_role_text = ", ".join(str(n) for n in bullets_per_role)
    has_llm_stack = _has_llm_agentic_stack(
        parsed.skills, parsed.professional_summary, parsed.professional_experience, jd
    )
    has_devops_stack = _has_devops_cloud_stack(parsed.skills, parsed.professional_summary, jd)
    mandatory_kw = (
        build_mandatory_devops_keyword_line_for_jd(jd)
        if is_devops_role
        else build_mandatory_ai_keyword_line()
    )
    role_addon = build_role_prompt_addon(
        is_ai_role=is_ai_role,
        is_devops_role=is_devops_role,
        has_llm_stack=has_llm_stack,
        has_devops_stack=has_devops_stack,
        jd_tools=jd_tools,
        source_metrics=source_metrics,
        mandatory_kw=mandatory_kw,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infra,
        jd_phrases=jd_phrases,
    )
    career_progression = build_career_progression_experience_prompt(
        resolved_role_count,
        bullets_per_role,
        is_ai_role=is_ai_role,
        is_devops_role=is_devops_role,
        is_java_backend=is_java_backend,
        target_role=target_role,
    )
    consulting_style = ""
    if is_consulting_ai:
        consulting_style = build_applied_ai_consulting_style_prompt(
            jd_phrases=jd_phrases,
            source_metrics=source_metrics,
            target_role=target_role,
        )
    aws_infra_style = ""
    devops_priority = ""
    devops_validation = ""
    if is_devops_role:
        devops_priority = build_devops_cloud_priority_prompt(jd)
        devops_validation = build_devops_validation_checklist_prompt()
        if is_aws_infra:
            aws_infra_style = build_aws_infrastructure_style_prompt(
                jd_tools=jd_tools,
                source_metrics=source_metrics,
                target_role=target_role,
            )
    weighted_plan = build_weighted_jd_keyword_plan(
        jd,
        target_job_role=target_role,
        jd_tools=jd_tools,
        jd_phrases=jd_phrases,
    )
    tailoring_strategy_prompt = build_tailoring_strategy_prompt(tailoring_strategy)
    jd_weighted_tools = build_jd_weighted_tools_prompt(jd, evidence_map)
    evidence_lower = {k.lower(): v for k, v in evidence_map.items()}
    evidenced_jd_tools = [t for t in jd_tools if evidence_lower.get(t.lower(), 0) >= 1]
    stage1 = build_jd_stage1_analysis_prompt(jd, target_job_role=target_role)
    evidence_block = format_candidate_evidence_for_prompt(evidence_map, jd_tools)
    jd_tool_reasoning = build_jd_tool_reasoning_prompt(jd_tools, evidence_map, jd)
    resume_narrative = build_resume_narrative_prompt(
        evidence_map, jd, target_role=target_role, is_consulting_ai=is_consulting_ai
    )
    resume_strategy = build_resume_strategy_prompt(
        evidence_map,
        jd_tools,
        jd,
        target_role=target_role,
        is_consulting_ai=is_consulting_ai,
        is_aws_infrastructure=is_aws_infra,
    )
    hidden_planning = build_hidden_planning_step_prompt(
        target_role, jd, evidence_map, is_consulting_ai=is_consulting_ai, is_aws_infrastructure=is_aws_infra
    )
    bullet_intent_plan = build_bullet_intent_plan(
        bullets_per_role, is_consulting_ai=is_consulting_ai, is_aws_infrastructure=is_aws_infra
    )
    human_voice = build_human_resume_writing_prompt()
    if profile_stack and tailoring_strategy.de_emphasize and tailoring_strategy.mode in ("moderate", "conservative"):
        de_set = {d.lower() for d in tailoring_strategy.de_emphasize}
        pivot_stack = [t for t in profile_stack if t.lower() not in de_set]
        stack_line = ", ".join(list(dict.fromkeys(tailoring_strategy.promote + pivot_stack))[:15])
    preserve_lines: list[str] = []
    if years:
        preserve_lines.append(f'- Years of experience (keep in summary): "{years}"')
    if profile_stack:
        preserve_lines.append(f"- SOURCE_TECH_STACK (evidence only — do not dump all in every section): {stack_line}")
    preserve_block = "\n".join(preserve_lines) + "\n\n" if preserve_lines else ""
    source_experience = _experience_evidence_for_prompt(parsed.professional_experience)
    source_bullet_total = sum(
        1 for line in source_experience.splitlines() if _BULLET_LINE_RE.match(line.strip())
    )
    payload = {
        "contact": parsed.contact,
        "professional_summary": parsed.professional_summary,
        "professional_experience": source_experience,
        "skills": parsed.skills,
        "education": parsed.education,
        "other": parsed.other,
    }
    user_intro = (
        "TARGET JOB — rewrite ONLY summary, experience bullets, and skills.\n"
        + stage1
        + tailoring_strategy_prompt
        + jd_weighted_tools
        + hidden_planning
        + evidence_block
        + jd_tool_reasoning
        + resume_narrative
        + resume_strategy
        + bullet_intent_plan
        + human_voice
        + weighted_plan
        + "- professional_summary: 3–4 sentences, distinctive engineering identity, no first person.\n"
        + "- professional_experience: follow BULLET INTENT PLAN — output ONLY new \"- \" lines (no headers).\n"
        + "- skills: use role-specific category labels from RESUME STRATEGY; order by JD importance.\n"
        + "- FROZEN — return contact, education, other verbatim from source.\n"
        + "- Ground every bullet in source accomplishments — do not fabricate work the candidate did not do.\n"
        + (f"- EVIDENCED JD TOOLS (safe to weave in): {', '.join(evidenced_jd_tools[:12])}\n" if evidenced_jd_tools else "")
        + consulting_style
        + aws_infra_style
        + devops_priority
        + devops_validation
        + career_progression
        + role_addon
        + f"- BULLETS_PER_ROLE (MINIMUM per employer, oldest→newest; fill ALL slots): {per_role_text}\n"
        + f"- TEMPLATE_BULLET_SLOTS (max per employer in Word layout): {', '.join(str(n) for n in template_slots)}\n"
        + f"- MINIMUM_TOTAL_BULLETS: {sum(bullets_per_role)}\n"
        + f"- ROLE_COUNT: {resolved_role_count}\n"
        + f"- SOURCE_BULLET_COUNT: {source_bullet_total} (rewrite/enrich these; do not ignore them)\n"
        + (f"- JD_ROLE_FOR_SUMMARY: {target_role}\n" if target_role else "")
        + f"- Source skills layout: {stats['skills_lines']} lines / preserve category labels.\n\n"
        + preserve_block
        + "JOB DESCRIPTION:\n"
        + jd.strip()
        + "\n\nSOURCE EXPERIENCE (ground truth — headers + bullets per employer; rewrite for ATS + JD):\n"
        + source_experience
        + "\n\nSOURCE_SECTIONS_JSON (same data; contact/education/other frozen in output):\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    def _quality(t: TailoredSections) -> bool:
        return _tailor_quality_ok(
            parsed,
            t,
            bullets_per_role=bullets_per_role,
            ats_terms=ats_terms,
            jd_tools=jd_tools,
            is_ai_role=is_ai_role,
            is_devops_role=is_devops_role,
            has_llm_stack=has_llm_stack,
            has_devops_stack=has_devops_stack,
            is_consulting_ai=is_consulting_ai,
            job_description=jd,
            tailoring_strategy=tailoring_strategy,
        )

    if _openai_pipeline_mode() != "legacy":
        tailored = await _run_multi_stage_pipeline(
            client,
            parsed,
            jd,
            target_role=target_role,
            tailoring_strategy=tailoring_strategy,
            evidence_map=evidence_map,
            jd_tools=jd_tools,
            source_experience=source_experience,
            payload=payload,
            bullet_intent_plan=bullet_intent_plan,
            career_progression=career_progression,
            human_voice=human_voice,
            bullets_per_role=bullets_per_role,
            template_slots=template_slots,
            stats=stats,
            years=years or "",
            stack_line=stack_line,
            is_consulting_ai=is_consulting_ai,
            is_aws_infra=is_aws_infra,
            is_ai_role=is_ai_role,
            is_devops_role=is_devops_role,
            has_llm_stack=has_llm_stack,
            has_devops_stack=has_devops_stack,
            ats_terms=ats_terms,
        )
        return _ensure_source_sections(parsed, tailored)

    async def _call(user_content: str, temp_boost: float = 0.0) -> TailoredSections:
        model = _openai_model_write()
        completion = await client.chat.completions.create(
            model=model,
            **chat_completion_controls(
                model,
                max_output_tokens=_tailor_max_tokens(),
                temperature=min(_tailor_temperature() + temp_boost, 0.72),
            ),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": STRUCTURED_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        )
        raw = completion.choices[0].message.content or "{}"
        data = _parse_json_object(raw)
        return TailoredSections(
            contact=str(data.get("contact", "")).strip(),
            professional_summary=str(data.get("professional_summary", "")).strip(),
            professional_experience=str(data.get("professional_experience", "")).strip(),
            skills=_normalize_skills_preserving_layout(
                coerce_skills_text(data.get("skills", "")),
                parsed.skills,
            ),
            education=str(data.get("education", "")).strip(),
            other=str(data.get("other", "")).strip(),
            experience_role_titles="",
        )

    tailored = await _call(user_intro)
    if _quality(tailored):
        return _ensure_source_sections(parsed, tailored)

    min_total_bullets = sum(bullets_per_role)
    retry_msg = (
        user_intro
        + "\n\nQUALITY RETRY: rewrite must sound human — not AI keyword stuffing.\n"
        "Follow BULLET INTENT PLAN — vary structure; max 40% bullets ending with metrics.\n"
        "No Engineered/Developed/Created/Established/Spearheaded openers. Use Built/Designed/Owned/Led/Debugged.\n"
        "Summary: distinctive engineering identity in 3–4 sentences — not 'AI Engineer with N years' alone.\n"
        "No comprehensive/streamlining/facilitating. Every summary competency in an experience bullet.\n"
        "Distribute JD keywords by section — never repeat the same tool in summary, skills, AND experience.\n"
        f"Include at least {min_total_bullets} \"- \" bullets ({per_role_text}). "
        "Rewrite EVERY source bullet from real accomplishments.\n"
        "Return contact, education, other verbatim."
    )
    if is_devops_role:
        retry_msg += (
            "\n\nDEVOPS RETRY: match dominant cloud from JD. For AWS roles emphasize VPC, IAM, RDS/Aurora, "
            "Terraform, DR, FinOps — not GCP/Kubernetes unless in source. Fill every skill category."
        )
    elif is_java_backend:
        retry_msg += (
            "\n\nJAVA BACKEND RETRY: optimize for the TARGET ROLE — not the candidate's AI profile. "
            "Summary opens as Senior Software/Backend Engineer (NOT AI/ML Engineer). "
            "Skills lead with Backend Development (Java, REST, SQL) — NOT Generative AI & LLM. "
            "Experience: lead with Java/REST/database bullets; move AI/RAG/LLM bullets later. "
            "Do NOT invent Spring Boot if absent from source."
        )
    elif is_ai_role:
        retry_msg += (
            "\n\nAI RETRY: summary = production AI identity; experience = Built/Designed + stack in context; "
            "skills = tool list. MCP/evals/observability in bullets where source supports — not every line."
        )
    elif has_llm_stack:
        retry_msg += f"\n\nUse these terms in context only (max 2 mentions each): {mandatory_kw}."
    tailored = await _call(retry_msg, temp_boost=0.08)
    if _quality(tailored):
        return _ensure_source_sections(parsed, tailored)

    retry_msg2 = (
        retry_msg
        + "\n\nStill too generic. Shorten bullets (14–20 words). Vary structure — not every bullet Action+tech+metric. "
        "Each employer must read differently. Summary = engineering identity in 3–4 sentences, no first person."
    )
    if is_devops_role:
        retry_msg2 += " Place DevOps tools in experience context only."
    elif is_java_backend:
        retry_msg2 += (
            " Pivot narrative to Java → Spring → REST → Microservices → Databases → Cloud → CI/CD. "
            "De-emphasize LLM/RAG/LangChain unless directly relevant."
        )
    elif is_ai_role:
        retry_msg2 += " Peak role: ownership + production AI; avoid repeating MCP in every bullet."
    else:
        retry_msg2 += (
            " Most recent role gets deepest detail; oldest stays simple. "
            "Do not copy peak-role bullets into early career."
        )
    tailored = await _call(retry_msg2, temp_boost=0.12)
    return _ensure_source_sections(parsed, tailored)


def _ensure_source_sections(parsed: ParsedResume, tailored: TailoredSections) -> TailoredSections:
    """Keep frozen sections from source; summary/skills/experience come from the LLM."""
    return TailoredSections(
        contact=(parsed.contact or "").strip(),
        professional_summary=tailored.professional_summary.strip(),
        professional_experience=tailored.professional_experience.strip(),
        skills=tailored.skills.strip() or (parsed.skills or "").strip(),
        education=(parsed.education or "").strip(),
        other=(parsed.other or "").strip(),
    )


def _assemble_plain(t: TailoredSections) -> str:
    parts: list[str] = []
    if t.contact.strip():
        parts.append(t.contact.strip())
    if t.professional_summary.strip():
        parts.append("PROFESSIONAL SUMMARY\n" + t.professional_summary.strip())
    if t.professional_experience.strip():
        parts.append("PROFESSIONAL EXPERIENCE\n" + t.professional_experience.strip())
    if t.skills.strip():
        parts.append("SKILLS\n" + t.skills.strip())
    if t.education.strip():
        parts.append("EDUCATION\n" + t.education.strip())
    if t.other.strip():
        parts.append("ADDITIONAL\n" + t.other.strip())
    return "\n\n".join(parts)


def _finalize_tailored(
    parsed: ParsedResume,
    tailored: TailoredSections,
    job_description: str = "",
    *,
    target_job_role: str = "",
    role_count: int | None = None,
    docx_bullet_slots: list[int] | None = None,
) -> TailoredSections:
    """Merge AI rewrites into experience/skills layout; freeze contact, education, other."""
    resolved_role_count = _resolve_role_count(parsed, role_count)
    ats_bullets_per_role = _progressive_ats_bullets_per_role(resolved_role_count)
    bullets_per_role, docx_export_caps = _resolve_bullets_per_role_for_tailor(
        parsed,
        resolved_role_count,
        docx_bullet_slots=docx_bullet_slots,
    )
    deduped_experience = _dedupe_similar_bullets(tailored.professional_experience)
    exp_merged = merge_experience_headers_with_bullets(
        parsed.professional_experience,
        deduped_experience,
        bullets_per_role=bullets_per_role,
    )
    if not _experience_has_bullets(exp_merged):
        if _experience_has_bullets(deduped_experience):
            exp_merged = merge_experience_headers_with_bullets(
                parsed.professional_experience,
                deduped_experience,
                bullets_per_role=bullets_per_role,
            )
        elif _experience_has_bullets(parsed.professional_experience):
            exp_merged = parsed.professional_experience
    is_devops = _is_devops_role(target_job_role, job_description)
    is_ai = is_jd_ai_focused(target_job_role, job_description)
    is_consulting = _is_applied_ai_consulting_jd(target_job_role, job_description)
    is_aws_infra = is_aws_infrastructure_jd(target_job_role, job_description)
    evidence_map = build_candidate_evidence_map(
        parsed.skills,
        parsed.professional_summary,
        parsed.professional_experience,
    )
    tailoring_strategy = build_tailoring_strategy(
        parsed,
        job_description,
        evidence_map,
        target_job_role=target_job_role,
        is_consulting_ai=is_consulting,
        is_aws_infrastructure=is_aws_infra,
    )
    skills_merged = merge_skills_for_ats(
        parsed.skills,
        tailored.skills,
        replace_entirely=True,
    )
    if is_ai:
        skills_base = build_ai_skills_for_template(
            parsed.skills,
            skills_merged,
            job_description,
        )
    else:
        skills_base = build_jd_skills_for_template(
            parsed.skills,
            skills_merged,
            job_description,
            is_devops_role=is_devops,
        )
    summary = ensure_years_in_summary(
        tailored.professional_summary.strip(),
        parsed.professional_summary,
        parsed.contact,
    )
    profile_stack = _extract_evidenced_career_stack(
        parsed.skills,
        parsed.professional_summary,
        parsed.professional_experience,
    )
    skills_final = build_evidence_based_skills(
        parsed.skills,
        skills_base,
        job_description,
        profile_stack=profile_stack,
        summary=summary,
        experience=exp_merged,
        is_devops_role=is_devops,
    )
    skills_final = build_dynamic_skills_for_role(
        parsed.skills,
        skills_final,
        job_description,
        target_role=target_job_role,
        is_devops_role=is_devops,
        is_consulting_ai=is_consulting,
        is_aws_infrastructure=is_aws_infra,
    )
    if tailoring_strategy.de_emphasize:
        skills_final = _deprioritize_skills_terms(skills_final, tailoring_strategy.de_emphasize)
    skills_final = _fill_empty_skill_categories(skills_final, parsed.skills)
    return TailoredSections(
        contact=(parsed.contact or "").strip(),
        professional_summary=summary,
        professional_experience=exp_merged.strip(),
        skills=_normalize_skills_preserving_layout(skills_final, parsed.skills),
        education=(parsed.education or "").strip(),
        other=(parsed.other or "").strip(),
        experience_bullets_per_role=docx_export_caps,
    )


def _default_tips_llm() -> list[str]:
    pipeline = _openai_pipeline_mode()
    tips = [
        "Resume is built through a multi-stage pipeline: JD analysis → strategy → writing → hiring-manager review.",
        "Strategy chooses the career narrative for the TARGET role — not the candidate's unrelated strengths.",
        "Bullets follow varied intents (Architecture, Ownership, Reliability) — not the same Verb→Tech→Metric rhythm.",
        "Skills categories are generated for your target role (AI Engineer, DevOps, Backend) — not a fixed template.",
        "Summary establishes a distinctive engineering identity — not generic 'N years of experience' language.",
        "JD tools are only promoted when supported by your source experience.",
        "Employer names, titles, and dates stay from your original resume; education and contact are unchanged.",
        "Verify employers, schools, dates, and contact details before submitting.",
    ]
    if pipeline != "legacy":
        tips.insert(
            1,
            f"Models: analysis={_openai_model_fast()}, strategy/write/review={_openai_model_write()}.",
        )
    return tips


def _default_tips_offline() -> list[str]:
    return [
        "Set OPENAI_API_KEY in backend/.env for AI-generated ATS experience bullets from the job description.",
        "Offline mode kept your original experience bullets; summary and skills include JD keyword alignment notes.",
        "Use clear section headers in your .docx (Summary, Experience, Skills, Education) for best results.",
        "Review headline, education, and contact lines before sending applications.",
    ]


def _build_docx_sync(
    *,
    source_docx_bytes: bytes,
    section_header_indices: dict[str, int],
    section_body_indices: dict[str, list[int]],
    contact_paragraph_indices: list[int],
    experience_table_rows: list,
    source_sections: ParsedResume,
    original_filename: str,
    tailored: TailoredSections,
    highlight_keywords: list[str] | None = None,
    skills_highlight_keywords: list[str] | None = None,
    enable_bold: bool = True,
) -> tuple[str, str, bool]:
    """Returns (base64_docx, download_filename, used_inplace_on_upload)."""
    download_name = output_docx_filename(original_filename)
    inplace = apply_tailored_sections_to_docx(
        source_docx_bytes,
        contact=tailored.contact,
        professional_summary=tailored.professional_summary,
        professional_experience=tailored.professional_experience,
        skills=tailored.skills,
        education=tailored.education,
        other=tailored.other,
        section_header_indices=section_header_indices,
        section_body_indices=section_body_indices,
        contact_paragraph_indices=contact_paragraph_indices,
        experience_table_rows=experience_table_rows,
        highlight_keywords=highlight_keywords,
        skills_highlight_keywords=skills_highlight_keywords,
        experience_bullets_per_role=tailored.experience_bullets_per_role,
        enable_bold=enable_bold,
        source_sections=source_sections,
        original_filename=original_filename,
    )
    if inplace is not None:
        data, name = inplace
        return base64.b64encode(data).decode("ascii"), name, True
    return "", download_name, False


async def tailor_resume(
    resume_text: str,
    job_description: str,
    *,
    source_docx_bytes: bytes,
    original_filename: str = "resume.docx",
    target_job_role: str = "",
    enable_bold: bool = True,
) -> TailorResponse:
    docx_doc = parse_resume_from_docx(source_docx_bytes)
    parsed = docx_doc.parsed
    resume_text = docx_doc.plain_text
    docx_section_header_indices = docx_doc.section_header_indices
    docx_section_body_indices = docx_doc.section_body_indices
    contact_paragraph_indices = docx_doc.contact_paragraph_indices
    experience_table_rows = docx_doc.experience_table_rows
    role_count = docx_doc.detected_role_count or (
        len(experience_table_rows) if experience_table_rows else None
    )
    docx_bullet_slots = list(docx_doc.experience_bullet_slots or [])

    enriched_contact = merge_profile_links_into_contact(
        parsed.contact,
        resume_text,
        docx_bytes=source_docx_bytes,
    )
    parsed = ParsedResume(
        contact=enriched_contact,
        professional_summary=parsed.professional_summary,
        professional_experience=parsed.professional_experience,
        skills=parsed.skills,
        education=parsed.education,
        other=parsed.other,
    )
    keywords = extract_keywords(job_description, top_k=22)
    key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_configured = bool(key)
    used_llm = False
    llm_error = ""
    tailored: TailoredSections

    if key:
        try:
            tailored = await _llm_tailor_structured(
                parsed,
                job_description,
                key,
                target_job_role=target_job_role,
                role_count=role_count,
                docx_bullet_slots=docx_bullet_slots or None,
            )
            if not (
                tailored.professional_summary.strip()
                or tailored.professional_experience.strip()
                or tailored.skills.strip()
                or tailored.contact.strip()
            ):
                raise ValueError("empty structured sections")
            used_llm = True
            tips = _default_tips_llm()
        except Exception as exc:
            logger.exception("OpenAI tailor pass failed")
            llm_error = _sanitize_llm_error(exc)
            tailored = _offline_tailor_structured(parsed, job_description)
            used_llm = False
            tips = _default_tips_offline() + [
                f"AI pass failed ({llm_error}); used offline section edits.",
            ]
    else:
        tailored = _offline_tailor_structured(parsed, job_description)
        tips = _default_tips_offline()

    tailored = _finalize_tailored(
        parsed,
        tailored,
        job_description,
        target_job_role=target_job_role,
        role_count=role_count,
        docx_bullet_slots=docx_bullet_slots or None,
    )
    highlight_keywords = build_docx_highlight_keywords(job_description, parsed, tailored) if enable_bold else []
    skills_highlight_keywords = (
        build_skills_highlight_keywords(job_description, tailored.skills) if enable_bold else []
    )
    full_text = _assemble_plain(tailored)

    docx_b64 = ""
    docx_download_name = output_docx_filename(original_filename)
    pdf_b64 = ""
    pdf_download_name = pdf_download_filename(docx_download_name)
    used_docx_inplace = False

    if docx_section_header_indices or contact_paragraph_indices or experience_table_rows:
        try:
            docx_b64, docx_download_name, used_docx_inplace = await asyncio.to_thread(
                _build_docx_sync,
                source_docx_bytes=source_docx_bytes,
                section_header_indices=docx_section_header_indices,
                section_body_indices=docx_section_body_indices,
                contact_paragraph_indices=contact_paragraph_indices,
                experience_table_rows=experience_table_rows,
                source_sections=parsed,
                original_filename=original_filename,
                tailored=tailored,
                highlight_keywords=highlight_keywords,
                skills_highlight_keywords=skills_highlight_keywords,
                enable_bold=enable_bold,
            )
            if used_docx_inplace and docx_b64:
                pdf_result = await asyncio.to_thread(
                    convert_docx_bytes_to_pdf,
                    base64.b64decode(docx_b64),
                    original_filename=docx_download_name,
                )
                if pdf_result is not None:
                    pdf_bytes, pdf_download_name = pdf_result
                    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
                    tips = [
                        *tips,
                        "A PDF version of your tailored resume is ready to download.",
                    ]
            if used_docx_inplace:
                tips = [
                    *tips,
                    "Your Word file keeps original formatting. Experience bolds top JD tools; Skills bolds only critical matches.",
                    "Resume voice targets human recruiter readability — not keyword-stuffed AI output.",
                ]
            else:
                tips = [
                    *tips,
                    "Could not map every section in your .docx. Use clear headers (Summary, Experience, Skills, Education) or copy sections below.",
                ]
        except Exception:
            tips = [*tips, "Word export failed; tailored text sections are still available below."]
        if docx_b64 and not pdf_b64:
            tips = [
                *tips,
                "PDF export needs Microsoft Word (docx2pdf) or LibreOffice installed on the server.",
            ]

    return TailorResponse(
        tailored_resume=full_text,
        tailored_contact=tailored.contact,
        tailored_summary=tailored.professional_summary,
        tailored_experience=tailored.professional_experience,
        tailored_skills=tailored.skills,
        tailored_education=tailored.education,
        tailored_other=tailored.other,
        docx_base64=docx_b64,
        download_filename=docx_download_name,
        pdf_base64=pdf_b64,
        pdf_download_filename=pdf_download_name,
        keywords_highlighted=list(
            dict.fromkeys([*highlight_keywords, *skills_highlight_keywords])
        )[:40],
        experience_keywords_highlighted=highlight_keywords,
        skills_keywords_highlighted=skills_highlight_keywords,
        ats_tips=tips,
        used_llm=used_llm,
        openai_configured=openai_configured,
        llm_error=llm_error,
        enable_bold_applied=enable_bold,
    )
