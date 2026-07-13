"""Pre-generation resume gap analysis and candidate confirmation questions."""
from __future__ import annotations

import re
from typing import Any

from app.services.resume_evidence import (
    SourceFact,
    analyze_job_description,
    build_verified_candidate_facts,
    create_evidence_map,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _target_title(job_description: str, job_analysis: dict[str, Any]) -> str:
    explicit = _clean(str(job_analysis.get("jobTitle", "")))
    if explicit:
        return explicit
    for raw_line in (job_description or "").splitlines()[:12]:
        line = _clean(re.sub(r"^[#>*\-\s]+|[*_`]+", "", raw_line))
        if 2 <= len(line.split()) <= 8 and re.search(
            r"\b(engineer|developer|architect|scientist|analyst|manager|director|specialist)\b",
            line,
            re.I,
        ):
            return line
    return "Target role"


def _practical_facts(facts: list[SourceFact]) -> list[SourceFact]:
    return [
        fact
        for fact in facts
        if fact.fact_id.startswith("exp_") and "_bullet_" in fact.fact_id
        or fact.source == "project"
    ]


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def default_professional_role_index(fact_text: str, roles: list[Any]) -> int | None:
    """Place detailed unscoped confirmations in the newest existing role, never a new employer."""
    if not roles or (fact_text or "").strip().lower().startswith("candidate confirms"):
        return None
    return len(roles) - 1


def build_qualification_questions(
    *,
    job_description: str,
    facts: list[SourceFact],
    evidence_map: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create high-value yes/no questions only where practical evidence is missing."""
    jd = job_description or ""
    all_evidence = "\n".join(fact.text for fact in facts)
    practical_evidence = "\n".join(fact.text for fact in _practical_facts(facts))
    gap_names = {
        str(item.get("requirement", "")).lower()
        for item in evidence_map
        if item.get("status") in {"missing", "unknown", "contradicted", "partial", "transferable_match"}
    }
    questions: list[dict[str, Any]] = []
    confirmation_claims = {
        "llm_production": "Candidate confirms hands-on experience building or maintaining an application that used an LLM API or LLM orchestration framework.",
        "document_processing": "Candidate confirms experience building a document processing workflow that converted unstructured document inputs into structured data.",
        "production_python": "Candidate confirms writing production Python application code used by other people or operational workflows.",
        "sql_server_depth": "Candidate confirms SQL Server or T-SQL work beyond basic CRUD.",
        "agentic_workflows": "Candidate confirms experience building a multi-step or agentic AI workflow with orchestration, tools, or persisted state.",
        "llm_failure_guardrail": "Candidate confirms experience responding to an incorrect AI or LLM output with a concrete validation, guardrail, monitoring, fallback, or human-review control.",
        "llm_document_generation": "Candidate confirms experience using an LLM to generate controlled document content from structured inputs.",
        "regulated_data": "Candidate confirms experience engineering systems that handled healthcare, financial, personal, or other regulated data.",
        "cloud_release": "Candidate confirms experience deploying and maintaining production services through cloud infrastructure and a Git-based release process.",
        "relevant_ai_projects": "Candidate confirms having completed a relevant personal, freelance, open-source, or internal AI project.",
    }
    fictional_examples = {
        "llm_production": (
            "FICTIONAL EXAMPLE - replace every detail with your real experience: At Example Health, I built and maintained "
            "a production Python service using the OpenAI API for prompt-driven extraction and schema-constrained JSON. "
            "The workflow processed 8,000 healthcare documents per month, validated required fields against source text, "
            "retried malformed responses, and routed low-confidence output to human review, reducing manual review by 35%."
        ),
        "document_processing": (
            "FICTIONAL EXAMPLE - replace every detail: At Example Insurance, I developed a PDF intake pipeline using "
            "PyMuPDF and Azure Document Intelligence to extract claim fields into structured JSON and persist verified "
            "records to SQL Server. Schema checks, page-level source citations, confidence thresholds, and a review queue "
            "handled incorrect parses and cut average processing time from 20 minutes to 6 minutes per claim."
        ),
        "production_python": (
            "FICTIONAL EXAMPLE - replace every detail: I have 4 years of production Python experience, representing about "
            "60% of my backend work at Example Company. I built FastAPI services, ETL jobs, scheduled batch processors, "
            "and AI integrations; added Pytest coverage, structured logging, retries, and monitoring; deployed through "
            "Docker and CI/CD; and supported the services through production incidents and releases."
        ),
        "sql_server_depth": (
            "FICTIONAL EXAMPLE - replace every detail: At Example Health, I used Microsoft SQL Server and T-SQL for 3 years. "
            "I designed normalized schemas, wrote multi-table queries, views, and stored procedures, reviewed execution plans, "
            "added indexes, and scheduled reconciliation jobs with SQL Server Agent, improving a nightly audit query from "
            "18 minutes to 5 minutes."
        ),
        "agentic_workflows": (
            "FICTIONAL EXAMPLE - replace every detail: I built a LangGraph workflow that classified incoming documents, "
            "called extraction and validation tools, persisted state between steps, compared agent output with source text, "
            "retried transient failures, and escalated unresolved records to a reviewer. The internal workflow handled "
            "1,500 documents per week in production."
        ),
        "llm_failure_guardrail": (
            "FICTIONAL EXAMPLE - replace every detail: An LLM confidently assigned the wrong denial reason when a PDF contained "
            "conflicting codes across pages. I blocked automatic release, required every extracted code to match cited source text, "
            "added deterministic code validation and confidence thresholds, and routed conflicts to human review. The guardrail "
            "prevented unsupported records from reaching downstream billing workflows."
        ),
        "llm_document_generation": (
            "FICTIONAL EXAMPLE - replace every detail: I built an LLM document-generation service that converted validated SQL "
            "records into audit letters. Versioned prompts and templates controlled tone and required sections; JSON Schema, "
            "business-rule validation, source-field comparison, and reviewer approval prevented unsupported content before release."
        ),
        "relevant_ai_projects": (
            "FICTIONAL EXAMPLE - replace every detail: Claims Document Validator | Personal project | 2025. Built a Python and "
            "OpenAI API application that extracted structured JSON from sample claim PDFs, displayed source citations, validated "
            "required fields, and routed failed parses for manual review. Deployed a demonstration on Azure with source code and "
            "technical documentation in GitHub."
        ),
        "regulated_data": (
            "FICTIONAL EXAMPLE - replace every detail: At Example Health, I maintained Python services that processed "
            "protected health information in a HIPAA-regulated workflow. I applied least-privilege access, encrypted data "
            "in transit and at rest, excluded sensitive fields from logs, maintained audit trails, and documented data-handling "
            "controls for engineering and operations teams, reducing privacy and operational risk."
        ),
        "cloud_release": (
            "FICTIONAL EXAMPLE - replace every detail: At Example Company, I deployed Python and AI services to Azure App "
            "Service using Docker, Git, and an automated CI/CD pipeline. I added unit and integration tests, environment-specific "
            "configuration, health checks, structured logging, alerts, rollback procedures, and release documentation, then "
            "owned production monitoring and incident fixes after deployment."
        ),
    }
    fictional_skill_examples = {
        "llm_production": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: Python, OpenAI API, Claude API, prompt engineering, structured JSON outputs, JSON Schema, function calling, multi-block response handling, LangChain, LangGraph, RAG, embeddings, vector databases, retry and fallback logic",
        "document_processing": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: PDF parsing, PyMuPDF, pdfplumber, Camelot, OCR, Tesseract, Azure Document Intelligence, AWS Textract, document classification, information extraction, schema validation, source grounding, confidence thresholds, human review",
        "production_python": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: Python, FastAPI, Flask, Django, REST APIs, ETL, data pipelines, batch processing, microservices, Pytest, Docker, structured logging, monitoring, CI/CD",
        "sql_server_depth": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: Microsoft SQL Server, T-SQL, complex joins, stored procedures, views, triggers, schema design, indexing, execution plans, query tuning, SQL Server Agent, data reconciliation",
        "agentic_workflows": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: agentic workflows, LangGraph, LangChain, CrewAI, Semantic Kernel, LlamaIndex, Model Context Protocol (MCP), orchestration, state management, tool calling, output validation, human-in-the-loop review",
        "llm_failure_guardrail": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: LLM guardrails, source-data validation, hallucination handling, JSON Schema validation, confidence thresholds, evaluation, prompt versioning, audit logging, monitoring, retry logic, fallback logic, human review",
        "llm_document_generation": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: LLM document generation, prompt templates, structured inputs, JSON Schema, business-rule validation, source-field comparison, prompt versioning, approval workflows",
        "regulated_data": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: healthcare data, HIPAA, protected health information (PHI), privacy controls, role-based access control, encryption, secrets management, audit logging, data retention, regulated workflows",
        "cloud_release": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: Azure, Azure App Service, Azure Functions, Docker, Git, CI/CD, GitHub Actions, Azure DevOps, unit testing, integration testing, monitoring, alerting, rollback procedures, production support",
        "relevant_ai_projects": "FICTIONAL SKILLS EXAMPLE - keep only skills you really used: Python, LLM APIs, document processing, structured outputs, validation, deployment, technical documentation",
    }

    def add(
        question_id: str,
        category: str,
        title: str,
        prompt: str,
        why: str,
        detail_prompt: str,
        details: list[str],
        requirements: list[str],
    ) -> None:
        if any(item["id"] == question_id for item in questions):
            return
        questions.append(
            {
                "id": question_id,
                "category": category,
                "title": title,
                "prompt": prompt,
                "why_it_matters": why,
                "detail_prompt": detail_prompt,
                "suggested_details": details,
                "missing_requirements": requirements,
                "confirmation_claim": confirmation_claims[question_id],
                "example_answer": fictional_examples[question_id],
                "example_skills": fictional_skill_examples[question_id],
                "skills_prompt": "List every relevant technology, platform, framework, method, and domain skill you genuinely used. Keep only items you can defend in an interview.",
                "details_required_when_yes": False,
            }
        )

    llm_jd = _has(r"\b(llm|large language model|openai|claude|gemini|bedrock|prompt design|function calling|tool calling)\b", jd)
    llm_practical = _has(r"\b(openai|claude|gemini|bedrock|llm|large language model)\b", practical_evidence)
    if llm_jd and not llm_practical:
        add(
            "llm_production",
            "AI / LLM Engineering",
            "Production LLM experience",
            "Have you personally built or maintained an application using an LLM API or LLM orchestration framework?",
            "The posting requires hands-on LLM engineering, but the résumé currently shows skills or general AI exposure without a defensible production example.",
            "Name every technology you actually used and describe one system: employer/project, production or prototype status, your contribution, inputs/outputs, users or scale, validation, deployment, and result.",
            [
                "OpenAI, Claude, Gemini, Azure OpenAI, or Bedrock",
                "Prompt design and structured JSON/schema outputs",
                "Function/tool calling, multi-block responses, RAG, or vector databases",
                "LangChain, LangGraph, LlamaIndex, Semantic Kernel, CrewAI, or MCP",
                "One wrong output or failure mode and the guardrail, monitoring, retry, fallback, or human review added",
            ],
            sorted(name for name in gap_names if _has(r"openai|claude|gemini|bedrock|llm|rag|langchain", name)),
        )

    document_jd = _has(r"\b(pdfs?|ocr|document processing|document parsing|unstructured documents?|information extraction)\b", jd)
    document_practical = _has(r"\b(pdfs?|ocr|document parsing|document processing|textract|tesseract|document intelligence|pdfplumber|pymupdf|camelot)\b", practical_evidence)
    if document_jd and not document_practical:
        add(
            "document_processing",
            "Document Processing",
            "PDF and document automation",
            "Have you built a workflow that parsed PDFs, OCR output, forms, claims, invoices, contracts, medical documents, or similar files into structured data?",
            "Document-to-structured-data automation is central to this role and is not demonstrated in the current work history.",
            "Describe the employer/project, document types, libraries or services used, target schema/output, how incorrect parses were detected, failure handling, destination system, and supported result.",
            [
                "PyMuPDF, pdfplumber, Camelot, Tesseract, OCR",
                "Azure Document Intelligence, AWS Textract, or Google Document AI",
                "Structured JSON, schema validation, source comparison, confidence thresholds, or human review",
                "LLM document generation from structured inputs, if applicable",
            ],
            sorted(name for name in gap_names if _has(r"pdf|ocr|document", name)),
        )

    python_jd = _has(r"\bpython\b", jd)
    python_practical = _has(r"\bpython\b", practical_evidence)
    if python_jd and not python_practical:
        add(
            "production_python",
            "Python",
            "Production Python depth",
            "Have you written Python application code that other people or production workflows depended on?",
            "Python is listed in Skills, but the current experience bullets do not establish production usage, ownership, or duration.",
            "Provide approximate years and the employer/project. Describe the Python work (APIs, FastAPI/Flask/Django, ETL, data pipelines, automation, AI services, batch processing, or microservices), production ownership, testing, deployment, and a supported outcome. If useful, estimate the percentage of your backend work that was Python.",
            ["Approximate years", "Employer or project", "Production system type", "Testing, monitoring, deployment, and maintenance"],
            ["Python"],
        )

    sql_jd = _has(r"\b(sql server|microsoft sql|t-sql|stored procedures?|query tuning|schema design|relational database)\b", jd)
    sql_specifics_jd = _has(r"\b(t-sql|stored procedures?|views?|triggers?|index(?:es|ing)|schema design|sql server agent)\b", jd)
    sql_specifics_practical = _has(r"\b(t-sql|stored procedures?|views?|triggers?|index(?:es|ing)|schema design|sql server agent)\b", practical_evidence)
    relational_sql_practical = _has(r"\b(sql server|t-sql|stored procedures?|query (?:tuning|optimization)|multi-table|joins?)\b", practical_evidence)
    if sql_jd and ((sql_specifics_jd and not sql_specifics_practical) or not relational_sql_practical):
        add(
            "sql_server_depth",
            "SQL and Data",
            "SQL Server and T-SQL depth",
            "Have you performed SQL Server or T-SQL work beyond basic CRUD?",
            "The posting expects relational reasoning and prefers SQL Server-specific depth that is not fully established by the résumé.",
            "Name the employer/project and confirm what you used: multi-table queries, stored procedures, views, triggers, schema design, indexes, query plans/tuning, SQL Server Agent, reporting, or data pipelines. Include approximate years and only supported outcomes.",
            ["Stored procedures and views", "Schema design and indexing", "Complex joins and query optimization", "SQL Server Agent, reporting, or pipeline persistence"],
            sorted(name for name in gap_names if _has(r"sql|database|stored|t-sql", name)),
        )

    agentic_jd = _has(r"\b(agentic|agents?|orchestration|state management|tool calling|multi-step)\b", jd)
    agentic_practical = _has(r"\b(agentic|ai agents?|langgraph|crew(?:ai)?|orchestration|state management|tool calling|mcp)\b", practical_evidence)
    if agentic_jd and not agentic_practical and not any(q["id"] == "llm_production" for q in questions):
        add(
            "agentic_workflows",
            "AI / LLM Engineering",
            "Agentic workflows",
            "Have you built a multi-step or agentic AI workflow with orchestration, tools, or persisted state?",
            "Agentic workflow experience is preferred, but the current résumé does not show a concrete implementation.",
            "Describe the employer/project, orchestration framework, workflow steps, state management, tool/function calls, output validation, retry/fallback behavior, and production status.",
            ["Orchestration framework", "State and tool management", "Validation and source grounding", "Retries, fallbacks, and monitoring"],
            sorted(name for name in gap_names if _has(r"agent|orchestration|state", name)),
        )

    reliability_jd = _has(r"\b(guardrails?|hallucination|confidently wrong|validation against source|human review|not ready for production|monitoring)\b", jd)
    reliability_practical = _has(r"\b(guardrails?|hallucination|source validation|validated .* source|human[- ]in[- ]the[- ]loop|confidence threshold|llm monitoring|prompt versioning)\b", practical_evidence)
    if reliability_jd and not reliability_practical:
        add(
            "llm_failure_guardrail",
            "AI Reliability",
            "Wrong output and production guardrails",
            "Have you encountered an LLM or AI output that was confidently wrong and then added a concrete guardrail or withheld the system from production?",
            "The employer explicitly values production judgment, source verification, monitoring, and willingness to stop unsafe automation.",
            "Describe the specific system, wrong output, root failure mode, risk, guardrail or validation added, how failures were routed, and the observable result. Do not invent a story if you have not experienced this.",
            ["Failure mode", "Source-data verification", "Schema/rule validation", "Human review, monitoring, retry, or fallback"],
            ["Validation", "Guardrails", "Monitoring"],
        )

    document_generation_jd = _has(r"\b(document generation|generate documents?|document creation)\b", jd) and llm_jd
    document_generation_practical = _has(r"\b(generated?|generation)\b.{0,50}\b(document|report|letter|form)\b", practical_evidence)
    if document_generation_jd and not document_generation_practical and not any(q["id"] == "document_processing" for q in questions):
        add(
            "llm_document_generation",
            "AI / LLM Engineering",
            "LLM document generation",
            "Have you used an LLM to generate documents, reports, letters, forms, or other controlled content from structured inputs?",
            "The role includes LLM-powered document generation, which is distinct from chatbots and extraction.",
            "Describe the input schema, generated document type, prompt/template approach, validation or approval workflow, production status, and result.",
            ["Structured input", "Prompt or template versioning", "Output validation", "Approval and production workflow"],
            ["LLM-powered document generation"],
        )

    regulated_jd = _has(r"\b(healthcare|hipaa|phi|protected health information|regulated|financial data|privacy)\b", jd)
    regulated_practical = _has(r"\b(hipaa|phi|protected health information|regulated|privacy controls?|audit logging|healthcare data)\b", practical_evidence)
    if regulated_jd and not regulated_practical:
        add(
            "regulated_data",
            "Security and Compliance",
            "Regulated-data engineering",
            "Have you built or maintained systems that handled healthcare, financial, personal, or other regulated data?",
            "The employer operates in healthcare and values candidates who understand privacy, auditability, and careful production data handling.",
            "Describe the employer, data type, regulations or internal controls, your engineering responsibility, access/logging/encryption safeguards, production status, documentation, and supported result.",
            ["Healthcare, HIPAA, or PHI", "Access control and secrets management", "Encryption and safe logging", "Audit trails, retention, reviews, or documentation"],
            sorted(name for name in gap_names if _has(r"healthcare|hipaa|phi|regulated|privacy", name)),
        )

    cloud_release_jd = _has(r"\b(azure|git|ci/cd|continuous integration|continuous delivery|release process|production deployment)\b", jd)
    cloud_release_practical = _has(r"\b(azure|github actions|azure devops|ci/cd|continuous integration|docker|release pipeline|production deployment)\b", practical_evidence)
    if cloud_release_jd and not cloud_release_practical:
        add(
            "cloud_release",
            "Cloud and Production Delivery",
            "Cloud deployment and release ownership",
            "Have you deployed and maintained production services using Azure or another cloud platform with Git and a real development-to-production release process?",
            "This build role expects the engineer to ship, monitor, document, and maintain production software rather than stop at prototypes.",
            "Describe the employer, cloud services, application deployed, Git and CI/CD workflow, tests, environments, monitoring, rollback or incident support, documentation, and supported outcome.",
            ["Azure services or comparable cloud platform", "Git branching and code review", "CI/CD, tests, and environment promotion", "Monitoring, rollback, incident response, and documentation"],
            sorted(name for name in gap_names if _has(r"azure|git|ci/cd|deployment|release", name)),
        )

    return questions[:10]


def analyze_resume_qualification_gaps(
    *, source_docx_bytes: bytes, job_description: str
) -> dict[str, Any]:
    # Keep document-parser imports lazy so the deterministic question builder can
    # be tested without loading native PDF/OCR dependencies.
    from app.services.docx_resume import parse_resume_from_docx
    from app.services.resume_sections import resolve_docx_sections

    doc = parse_resume_from_docx(source_docx_bytes)
    resolved = resolve_docx_sections(source_docx_bytes, doc=doc)
    if not resolved.work_experience_roles:
        raise ValueError("No work experience roles detected in the uploaded resume.")
    facts = build_verified_candidate_facts(
        contact=resolved.contact,
        summary=resolved.professional_summary,
        skills=resolved.skills,
        roles=list(resolved.work_experience_roles),
        education=resolved.education,
        other=resolved.other,
    )
    job_analysis = analyze_job_description(job_description)
    evidence_map = create_evidence_map(job_analysis, facts)
    questions = build_qualification_questions(
        job_description=job_description,
        facts=facts,
        evidence_map=evidence_map,
    )
    supported = [
        str(item.get("requirement"))
        for item in evidence_map
        if item.get("status") in {"strong", "exact_match"} and item.get("requirement")
    ][:12]
    return {
        "target_role": _target_title(job_description, job_analysis),
        "intro": (
            f"Before generating the resume, confirm {len(questions)} important qualification area"
            f"{'s' if len(questions) != 1 else ''}. Select Yes only for experience you can defend in an interview. "
            "For every Yes, add both the relevant skills and a detailed experience example when possible. Copyable AI-written samples are provided as editing guides. Without supporting details, the resume can use only a high-level confirmation and will not invent employers, tools, metrics, or outcomes."
        ),
        "questions": questions,
        "already_supported": list(dict.fromkeys(supported)),
        "question_count": len(questions),
    }
