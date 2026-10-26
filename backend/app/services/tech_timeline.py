"""Technology release years, so tailored bullets never predate the tools they name.

A bullet under a 2018-2020 role that mentions Claude Code (released 2025) is an
obvious fabrication to any recruiter. This module knows when well-known
technologies first became publicly available and checks every role-dated claim
against that timeline.

Years are the FIRST public availability (preview/beta counts), which keeps the
check lenient: we only flag claims that are impossible, not merely early.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TechMention:
    name: str
    year: int


@dataclass(frozen=True)
class _Tech:
    name: str
    year: int
    pattern: re.Pattern[str]


def _alias_regex(alias: str) -> str:
    # Spaces/hyphens inside a name are optional ("GPT-4" = "GPT 4" = "GPT4").
    parts = [re.escape(part) for part in re.split(r"[\s\-]+", alias) if part]
    return r"[\s\-]?".join(parts)


def _tech(name: str, year: int, *aliases: str, case: bool = False) -> _Tech:
    body = "|".join(_alias_regex(alias) for alias in (aliases or (name,)))
    pattern = rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])"
    return _Tech(name, year, re.compile(pattern, 0 if case else re.I))


# Ambiguous everyday words (react, helm, swift, bedrock, ...) are case-sensitive
# or require a qualifier so ordinary prose does not trigger the check.
_TECHNOLOGIES: tuple[_Tech, ...] = (
    # AI assistants, models, and coding agents
    _tech("Claude Code", 2025),
    _tech("Claude Agent SDK", 2025),
    _tech("Claude", 2023, "Claude", "Anthropic API", "Anthropic Claude"),
    _tech("Model Context Protocol (MCP)", 2024, "Model Context Protocol", "MCP server", "MCP servers"),
    _tech("OpenAI Codex CLI", 2025, "Codex CLI"),
    _tech("OpenAI Codex", 2021, "OpenAI Codex"),
    _tech("OpenAI Agents SDK", 2025, "OpenAI Agents SDK", "Agents SDK"),
    _tech("OpenAI Responses API", 2025, "Responses API"),
    _tech("OpenAI Assistants API", 2023, "Assistants API"),
    _tech("GPT-5", 2025),
    _tech("GPT-4.1", 2025),
    _tech("GPT-4o", 2024),
    _tech("GPT-4", 2023),
    _tech("GPT-3.5", 2022),
    _tech("ChatGPT", 2022),
    _tech("GPT-3", 2020),
    _tech("GPT-2", 2019),
    _tech("OpenAI API", 2020, "OpenAI"),
    _tech("GitHub Copilot", 2021, "GitHub Copilot", "Copilot"),
    _tech("Cursor", 2023, "Cursor IDE", "Cursor AI", "Cursor editor"),
    _tech("Windsurf", 2024),
    _tech("Codeium", 2022),
    _tech("Gemini", 2023, "Gemini"),
    _tech("Google Bard", 2023, "Google Bard", "Bard", case=True),
    _tech("PaLM", 2022, "PaLM", "PaLM 2", case=True),
    _tech("Llama", 2023, "Llama", "LLaMA", "Llama 2", "Llama 3"),
    _tech("Mistral", 2023, "Mistral", "Mixtral"),
    _tech("DeepSeek", 2023),
    _tech("Stable Diffusion", 2022),
    _tech("Midjourney", 2022),
    _tech("DALL-E", 2021, "DALL-E", "DALLE", "DALL·E"),
    _tech("Whisper", 2022, "Whisper", case=True),
    _tech("Amazon Bedrock", 2023, "Bedrock", case=True),
    _tech("Amazon Q", 2023, "Amazon Q"),
    _tech("Azure OpenAI", 2021),
    _tech("Azure AI Foundry", 2024),
    _tech("Vertex AI", 2021),
    _tech("Microsoft Fabric", 2023),
    # LLM frameworks, agents, and retrieval
    _tech("LangGraph", 2024),
    _tech("LangSmith", 2023),
    _tech("LangChain", 2022),
    _tech("LlamaIndex", 2022, "LlamaIndex", "GPT Index"),
    _tech("CrewAI", 2023),
    _tech("AutoGen", 2023),
    _tech("AutoGPT", 2023),
    _tech("Semantic Kernel", 2023),
    _tech("DSPy", 2023),
    _tech("Ollama", 2023),
    _tech("vLLM", 2023),
    _tech("Vercel AI SDK", 2023),
    _tech("agentic AI", 2023, "agentic"),
    _tech("generative AI", 2022, "generative AI", "GenAI", "Gen AI"),
    _tech("LLMs", 2019, "LLM", "LLMs", case=True),
    _tech("large language models", 2019, "large language model", "large language models"),
    _tech("retrieval-augmented generation (RAG)", 2020, "retrieval augmented generation", "RAG pipeline", "RAG pipelines", "RAG system", "RAG systems", "RAG based"),
    _tech("prompt engineering", 2020),
    _tech("Pinecone", 2021),
    _tech("ChromaDB", 2022),
    _tech("pgvector", 2021),
    _tech("Qdrant", 2021),
    _tech("Weaviate", 2019),
    _tech("Milvus", 2019),
    _tech("vector databases", 2019, "vector database", "vector databases", "vector DB"),
    _tech("Hugging Face", 2018, "Hugging Face", "HuggingFace"),
    _tech("BERT", 2018, case=True),
    # ML platforms
    _tech("PyTorch", 2016),
    _tech("TensorFlow", 2015),
    _tech("Keras", 2015),
    _tech("JAX", 2018, case=True),
    _tech("FAISS", 2017),
    _tech("MLflow", 2018),
    _tech("Kubeflow", 2017),
    _tech("SageMaker", 2017),
    _tech("Weights & Biases", 2018, "Weights & Biases", "Weights and Biases"),
    _tech("Streamlit", 2019),
    _tech("Gradio", 2019),
    # Languages and frameworks
    _tech("TypeScript", 2012),
    _tech("Kotlin", 2011),
    _tech("Swift", 2014, case=True),
    _tech("Rust", 2012, case=True),
    _tech("Flutter", 2017),
    _tech("SwiftUI", 2019),
    _tech("Jetpack Compose", 2019),
    _tech("React Native", 2015),
    _tech("React", 2013, case=True),
    _tech("Redux Toolkit", 2019),
    _tech("TanStack", 2022),
    _tech("Vue", 2014, "Vue", "Vue.js", "VueJS", case=True),
    _tech("Svelte", 2016),
    _tech("SvelteKit", 2021),
    _tech("Next.js", 2016, "Next.js", "NextJS"),
    _tech("Nuxt", 2016, "Nuxt", "Nuxt.js"),
    _tech("Vite", 2020),
    _tech("Vitest", 2021),
    _tech("esbuild", 2020),
    _tech("Bun", 2022, "Bun runtime", "Bun.js"),
    _tech("Deno", 2018),
    _tech("Tailwind CSS", 2017, "Tailwind"),
    _tech("shadcn/ui", 2023, "shadcn"),
    _tech("tRPC", 2020),
    _tech("Zod", 2020, case=True),
    _tech("Prisma", 2018),
    _tech("Drizzle ORM", 2022, "Drizzle ORM"),
    _tech("FastAPI", 2018),
    _tech("Pydantic", 2017),
    _tech("Polars", 2020, case=True),
    _tech("Playwright", 2020),
    _tech("Cypress", 2015),
    _tech(".NET Core", 2016),
    _tech("Blazor", 2018),
    _tech("WebAssembly", 2017, "WebAssembly", "Wasm"),
    # Cloud, infrastructure, and DevOps
    _tech("Docker", 2013),
    _tech("Kubernetes", 2014, "Kubernetes", "K8s"),
    _tech("Helm", 2015, case=True),
    _tech("Terraform", 2014),
    _tech("Pulumi", 2018),
    _tech("Argo CD", 2018, "Argo CD", "ArgoCD"),
    _tech("Istio", 2017),
    _tech("OpenTelemetry", 2019),
    _tech("Grafana", 2014),
    _tech("GitHub Actions", 2018),
    _tech("Podman", 2018),
    _tech("Crossplane", 2018),
    _tech("Bicep", 2020, case=True),
    _tech("AWS Lambda", 2014),
    _tech("Amazon ECS", 2014, "ECS", case=True),
    _tech("Amazon EKS", 2017, "EKS", case=True),
    _tech("AWS Fargate", 2017, "Fargate"),
    _tech("AWS CDK", 2018, "AWS CDK", "CDK", case=True),
    _tech("AWS Step Functions", 2016, "Step Functions"),
    _tech("Amazon EventBridge", 2019, "EventBridge"),
    _tech("AWS AppSync", 2017, "AppSync"),
    _tech("AWS Amplify", 2017),
    _tech("AWS Glue", 2017),
    _tech("AWS App Runner", 2021),
    _tech("Azure Functions", 2016),
    _tech("Azure Kubernetes Service (AKS)", 2017, "AKS", "Azure Kubernetes Service"),
    _tech("Azure DevOps", 2018),
    _tech("Azure Synapse", 2019),
    _tech("Azure Container Apps", 2021),
    _tech("Google Cloud Run", 2019, "Cloud Run"),
    _tech("GKE", 2015, "GKE", "Google Kubernetes Engine"),
    _tech("Anthos", 2019),
    _tech("Vercel", 2020),
    _tech("Supabase", 2020),
    _tech("PlanetScale", 2021),
    _tech("Cloudflare Workers", 2017),
    # Data
    _tech("Snowflake", 2014, case=True),
    _tech("Databricks", 2013),
    _tech("Delta Lake", 2019),
    _tech("Apache Iceberg", 2018, "Apache Iceberg", "Iceberg", case=True),
    _tech("dbt", 2016, "dbt", case=True),
    _tech("Airbyte", 2020),
    _tech("Dagster", 2019),
    _tech("DuckDB", 2019),
    _tech("ClickHouse", 2016),
    _tech("Apache Airflow", 2015, "Airflow"),
    _tech("Apache Kafka", 2011, "Kafka"),
    _tech("OpenSearch", 2021),
    _tech("TimescaleDB", 2017),
    _tech("CockroachDB", 2015),
    _tech("MongoDB Atlas", 2016),
)


@dataclass(frozen=True)
class _VersionedTech:
    label: str
    pattern: re.Pattern[str]
    years: dict[str, int]


def _versions(start_year_by_version: dict[object, int]) -> dict[str, int]:
    return {str(version): year for version, year in start_year_by_version.items()}


_VERSIONED: tuple[_VersionedTech, ...] = (
    _VersionedTech(
        "Java {v}",
        re.compile(r"(?<![A-Za-z0-9])Java\s?(?:SE\s?)?(?P<v>\d{1,2})(?!\.?\d)"),
        _versions({8: 2014, 9: 2017, 10: 2018, 11: 2018, 12: 2019, 13: 2019, 14: 2020, 15: 2020,
                   16: 2021, 17: 2021, 18: 2022, 19: 2022, 20: 2023, 21: 2023, 22: 2024, 23: 2024,
                   24: 2025, 25: 2025}),
    ),
    _VersionedTech(
        "Python {v}",
        re.compile(r"(?<![A-Za-z0-9])Python\s?(?P<v>3\.\d{1,2})(?![\d])", re.I),
        _versions({"3.6": 2016, "3.7": 2018, "3.8": 2019, "3.9": 2020, "3.10": 2021, "3.11": 2022,
                   "3.12": 2023, "3.13": 2024, "3.14": 2025}),
    ),
    _VersionedTech(
        ".NET {v}",
        # .NET 5+ (the unified platform); ".NET 4.8" is .NET Framework and is skipped.
        re.compile(r"\.NET\s?(?P<v>\d{1,2})(?:\.0)?(?!\.?\d)", re.I),
        _versions({5: 2020, 6: 2021, 7: 2022, 8: 2023, 9: 2024, 10: 2025}),
    ),
    _VersionedTech(
        "C# {v}",
        re.compile(r"(?<![A-Za-z0-9])C#\s?(?P<v>\d{1,2})(?!\.?\d)"),
        _versions({8: 2019, 9: 2020, 10: 2021, 11: 2022, 12: 2023, 13: 2024, 14: 2025}),
    ),
    _VersionedTech(
        "C++{v}",
        re.compile(r"(?<![A-Za-z0-9])C\+\+\s?(?P<v>\d{2})(?!\d)"),
        _versions({11: 2011, 14: 2014, 17: 2017, 20: 2020, 23: 2023}),
    ),
    _VersionedTech(
        "React {v}",
        re.compile(r"(?<![A-Za-z0-9])React(?:\.js|JS)?\s?(?P<v>\d{2})(?!\.?\d)"),
        _versions({16: 2017, 17: 2020, 18: 2022, 19: 2024}),
    ),
    _VersionedTech(
        "Angular {v}",
        re.compile(r"(?<![A-Za-z0-9])Angular\s?(?P<v>\d{1,2})(?!\.?\d)"),
        _versions({2: 2016, 4: 2017, 5: 2017, 6: 2018, 7: 2018, 8: 2019, 9: 2020, 10: 2020,
                   11: 2020, 12: 2021, 13: 2021, 14: 2022, 15: 2022, 16: 2023, 17: 2023,
                   18: 2024, 19: 2024, 20: 2025}),
    ),
    _VersionedTech(
        "Next.js {v}",
        re.compile(r"(?<![A-Za-z0-9])Next(?:\.js|JS)\s?(?P<v>\d{1,2})(?!\.?\d)", re.I),
        _versions({9: 2019, 10: 2020, 11: 2021, 12: 2021, 13: 2022, 14: 2023, 15: 2024, 16: 2025}),
    ),
    _VersionedTech(
        "Node.js {v}",
        re.compile(r"(?<![A-Za-z0-9])Node(?:\.js|JS)?\s?(?P<v>\d{1,2})(?!\.?\d)", re.I),
        _versions({8: 2017, 10: 2018, 12: 2019, 14: 2020, 16: 2021, 18: 2022, 20: 2023, 22: 2024, 24: 2025}),
    ),
    _VersionedTech(
        "Vue {v}",
        re.compile(r"(?<![A-Za-z0-9])Vue(?:\.js|JS)?\s?(?P<v>\d)(?!\.?\d)"),
        _versions({2: 2016, 3: 2020}),
    ),
    _VersionedTech(
        "Spring Boot {v}",
        re.compile(r"(?<![A-Za-z0-9])Spring\s?Boot\s?(?P<v>\d)(?![\d])", re.I),
        _versions({1: 2014, 2: 2018, 3: 2022}),
    ),
    _VersionedTech(
        "Django {v}",
        re.compile(r"(?<![A-Za-z0-9])Django\s?(?P<v>\d)(?![\d])", re.I),
        _versions({2: 2017, 3: 2019, 4: 2021, 5: 2023}),
    ),
    _VersionedTech(
        "PostgreSQL {v}",
        re.compile(r"(?<![A-Za-z0-9])Postgres(?:QL)?\s?(?P<v>\d{2})(?![\d])", re.I),
        _versions({10: 2017, 11: 2018, 12: 2019, 13: 2020, 14: 2021, 15: 2022, 16: 2023, 17: 2024, 18: 2025}),
    ),
    _VersionedTech(
        "PHP {v}",
        re.compile(r"(?<![A-Za-z0-9])PHP\s?(?P<v>\d)(?![\d])", re.I),
        _versions({7: 2015, 8: 2020}),
    ),
    _VersionedTech(
        "TypeScript {v}",
        re.compile(r"(?<![A-Za-z0-9])TypeScript\s?(?P<v>\d)(?![\d])", re.I),
        _versions({2: 2016, 3: 2018, 4: 2020, 5: 2023}),
    ),
)

_PRESENT = re.compile(r"\b(present|current|currently|now|today|ongoing|to date)\b", re.I)
_YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20\d{2})(?!\d)")
_OPEN_ENDED = re.compile(r"(19[5-9]\d|20\d{2})\s*(?:-|–|—|to)\s*$", re.I)


def find_tech_mentions(text: str) -> list[TechMention]:
    """All dated technologies named in `text`, deduplicated by name."""
    if not text:
        return []
    found: dict[str, int] = {}
    claimed: list[tuple[int, int]] = []
    # Specific names come first in the table, so "Claude Code" claims its span
    # and the plain "Claude" inside it is not reported as a separate tool.
    for tech in _TECHNOLOGIES:
        for match in tech.pattern.finditer(text):
            start, end = match.span()
            if any(s <= start and end <= e for s, e in claimed):
                continue
            claimed.append((start, end))
            found.setdefault(tech.name, tech.year)
    for versioned in _VERSIONED:
        for match in versioned.pattern.finditer(text):
            version = match.group("v")
            year = versioned.years.get(version)
            if year is not None:
                found.setdefault(versioned.label.format(v=version), year)
    return [TechMention(name, year) for name, year in found.items()]


def role_year_span(period: str, *, today: date | None = None) -> tuple[int | None, int | None]:
    """(start_year, end_year) of a role's date range; open-ended ranges end this year."""
    text = (period or "").strip()
    years = [int(y) for y in _YEAR.findall(text)]
    if not years:
        return None, None
    current = (today or date.today()).year
    start = min(years)
    if _PRESENT.search(text) or (len(years) == 1 and _OPEN_ENDED.search(text)):
        return start, current
    return start, max(years)


def anachronistic_mentions(text: str, end_year: int | None) -> list[TechMention]:
    """Technologies in `text` first released after the role ended."""
    if end_year is None:
        return []
    return [mention for mention in find_tech_mentions(text) if mention.year > end_year]


def unavailable_technologies(candidates: list[TechMention], end_year: int | None) -> list[str]:
    """Prompt hints: candidate technologies that did not exist yet during a role."""
    if end_year is None:
        return []
    return [
        f"{mention.name} (first released {mention.year})"
        for mention in sorted(candidates, key=lambda m: (m.year, m.name))
        if mention.year > end_year
    ]


_TENURE = re.compile(
    r"(?P<years>\d{1,2})\s*\+?\s*(?:years?|yrs?)\b|\bsince\s+(?P<since>19[5-9]\d|20\d{2})\b",
    re.I,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _impossible_tenure(sentence: str, current_year: int) -> bool:
    for match in _TENURE.finditer(sentence):
        claimed_start = (
            current_year - int(match.group("years"))
            if match.group("years")
            else int(match.group("since"))
        )
        # Only technologies tied to this claim: "LangChain developer with 8 years",
        # "8+ years building LLM apps" — not a tool named later in the sentence.
        window = sentence[max(0, match.start() - 40): match.end() + 50]
        if any(mention.year > claimed_start for mention in find_tech_mentions(window)):
            return True
    return False


def strip_impossible_tenure_claims(summary: str, *, today: date | None = None) -> str:
    """Drop summary sentences claiming more years with a tool than it has existed."""
    if not summary:
        return summary
    current_year = (today or date.today()).year
    sentences = _SENTENCE_SPLIT.split(summary.strip())
    kept = [sentence for sentence in sentences if not _impossible_tenure(sentence, current_year)]
    return " ".join(kept).strip()


TECHNOLOGY_TIMELINE_RULES = """TECHNOLOGY TIMELINE RULES (non-negotiable):
- Every technology, tool, model, framework, or product named in a role's bullets must have been publicly released on or before that role's end year. A bullet in a 2018-2020 role must never mention Claude Code (2025), ChatGPT (2022), LangChain (2022), GPT-4 (2023), or any other tool released after 2020.
- Each role lists employment_years and technologies_unavailable_during_role. Never name those technologies in that role's bullets; describe the work with the tools that actually existed then.
- Place modern tools only in roles whose dates overlap their release. If no role is recent enough, list the tool in Skills only.
- Never claim more years of experience with a technology than it has existed (no "8 years of LangChain" when LangChain was released in 2022).
- The application removes any bullet that names a technology released after the role ended."""
