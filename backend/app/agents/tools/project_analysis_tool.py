"""Read-only project inspection restricted to an allowlist under AGENT_PROJECT_ROOT.

Only exact relative paths and shallow directory listings are allowed. The tool
never reads ``.env`` files, follows no caller-supplied paths and cannot run code.
When no root is configured the tool reports itself as disabled rather than
pretending it inspected a repository.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent_schemas import ToolContext, ToolResult
from app.agents.tools.base_tool import ToolSpec
from app.agents.tools.registry import registry
from app.config import settings

Mode = Literal[
    "architecture",
    "deployment",
    "environment",
    "database",
    "frontend",
    "missing_components",
]

_FILE_ALLOWLIST = {
    "README.md",
    "backend/requirements.txt",
    "backend/.env.example",
    "backend/alembic.ini",
    "backend/app/config.py",
    "backend/app/main.py",
    "frontend/package.json",
    "frontend/next.config.mjs",
    "frontend/.env.local.example",
    "frontend/tsconfig.json",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    ".github/workflows/ci.yml",
}
_LIST_ALLOWLIST = {
    "backend/app",
    "backend/app/api",
    "backend/app/agents",
    "backend/alembic/versions",
    "frontend/app",
    "frontend/components",
    "tests",
    "docs",
}


class ProjectAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode = "architecture"
    project_name: str | None = Field(default=None, max_length=120)


def _root() -> Path:
    return Path(settings.agent_project_root).expanduser()


def _configured() -> bool:
    raw = settings.agent_project_root.strip()
    return bool(raw) and _root().is_dir()


def _safe_path(relative: str) -> Path | None:
    root = _root().resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _read(relative: str) -> tuple[str | None, str | None]:
    if relative not in _FILE_ALLOWLIST:
        return None, f"{relative}: not in the read allowlist"
    path = _safe_path(relative)
    if path is None or not path.is_file():
        return None, f"{relative}: not found"
    try:
        if path.stat().st_size > settings.agent_project_max_file_bytes:
            return None, f"{relative}: file exceeds the inspection size limit"
        return path.read_text(encoding="utf-8", errors="ignore"), None
    except OSError:
        return None, f"{relative}: could not be read"


def _list_dir(relative: str) -> list[str]:
    if relative not in _LIST_ALLOWLIST:
        return []
    path = _safe_path(relative)
    if path is None or not path.is_dir():
        return []
    try:
        return sorted(
            (item.name + ("/" if item.is_dir() else ""))
            for item in path.iterdir()
            if not item.name.startswith("__pycache__")
        )[:60]
    except OSError:
        return []


def _exists(relative: str) -> bool:
    path = _safe_path(relative)
    return bool(path and path.exists())


def _package_json() -> tuple[dict, list[str]]:
    text, error = _read("frontend/package.json")
    if error or not text:
        return {}, [error] if error else []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}, ["frontend/package.json: invalid JSON"]
    return data, []


def _requirements() -> tuple[list[str], list[str]]:
    text, error = _read("backend/requirements.txt")
    if error or not text:
        return [], [error] if error else []
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ], []


def _env_keys(relative: str) -> list[str]:
    text, error = _read(relative)
    if error or not text:
        return []
    keys = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0].strip())
    return keys[:80]


def _settings_names() -> list[str]:
    text, error = _read("backend/app/config.py")
    if error or not text:
        return []
    return sorted(set(re.findall(r"^\s{4}([a-z][a-z0-9_]+)\s*:\s*[A-Za-z]", text, re.M)))[:120]


def _migrations() -> list[str]:
    versions = _list_dir("backend/alembic/versions")
    return [name for name in versions if name.endswith(".py")]


def _verdict(findings: list[dict], recommendations: list[dict], limitations: list[str]) -> ToolResult:
    if not findings:
        return ToolResult(
            ok=False,
            summary="The configured project root contained no readable allowlisted evidence.",
            error="No allowlisted project files were readable.",
            error_kind="not_configured",
            data={"findings": [], "recommendations": recommendations, "limitations": limitations},
        )
    summary = (
        f"Inspected {len(findings)} piece(s) of repository evidence and produced "
        f"{len(recommendations)} recommendation(s). Recommendations are separated from observed facts."
    )
    return ToolResult(
        ok=True,
        summary=summary,
        data={
            "findings": findings,
            "recommendations": recommendations,
            "limitations": limitations,
            "evidence_paths": sorted({str(item["source"]) for item in findings}),
            "note": "Observed findings come from files that exist; recommendations are suggestions, not facts.",
        },
        evidence=sorted({str(item["source"]) for item in findings}),
        sources=[f"repository:{item['source']}" for item in findings],
    )


def project_analysis(context: ToolContext, payload: ProjectAnalysisInput) -> ToolResult:
    if not _configured():
        return ToolResult(
            ok=False,
            summary="Project inspection is not configured.",
            error="Set AGENT_PROJECT_ROOT to the repository path to enable read-only inspection.",
            error_kind="not_configured",
        )

    findings: list[dict] = []
    recommendations: list[dict] = []
    limitations: list[str] = [
        "Only allowlisted files and shallow directory names are read; .env files and arbitrary paths are never opened.",
        "Findings describe the current repository state only; no deployment or build is executed.",
    ]

    package, package_errors = _package_json()
    requirements, requirement_errors = _requirements()
    backend_packages = _list_dir("backend/app")
    frontend_routes = _list_dir("frontend/app")
    components = _list_dir("frontend/components")
    migrations = _migrations()

    for error in package_errors + requirement_errors:
        limitations.append(error)

    if payload.mode in {"architecture", "missing_components"}:
        if backend_packages:
            findings.append(
                {
                    "key": "backend_packages",
                    "value": ", ".join(name.rstrip("/") for name in backend_packages),
                    "source": "backend/app",
                }
            )
        if frontend_routes:
            findings.append(
                {
                    "key": "frontend_routes",
                    "value": ", ".join(name for name in frontend_routes if name.endswith("/")),
                    "source": "frontend/app",
                }
            )
        if requirements:
            findings.append(
                {
                    "key": "backend_dependencies",
                    "value": f"{len(requirements)} declared requirement(s)",
                    "source": "backend/requirements.txt",
                    "detail": requirements[:25],
                }
            )
        if package:
            deps = package.get("dependencies", {})
            findings.append(
                {
                    "key": "frontend_dependencies",
                    "value": f"{len(deps)} runtime dependenc(ies)",
                    "source": "frontend/package.json",
                    "detail": sorted(deps)[:25],
                }
            )
        if migrations:
            findings.append(
                {
                    "key": "migrations",
                    "value": f"{len(migrations)} migration file(s)",
                    "source": "backend/alembic/versions",
                    "detail": migrations,
                }
            )
        if not components:
            recommendations.append(
                {
                    "item": "Frontend component directory not found",
                    "severity": "medium",
                    "reason": "frontend/components was empty or missing in the configured root.",
                }
            )

    if payload.mode == "deployment":
        checks = {
            "backend/requirements.txt": "Backend dependency manifest",
            "backend/.env.example": "Backend environment template",
            "frontend/.env.local.example": "Frontend environment template",
            "README.md": "Operator documentation",
        }
        for relative, label in checks.items():
            if _exists(relative):
                findings.append({"key": "present", "value": label, "source": relative})
            else:
                recommendations.append(
                    {
                        "item": f"Add {relative}",
                        "severity": "high" if relative.endswith(".example") else "medium",
                        "reason": f"{label} was not found in the configured project root.",
                    }
                )
        scripts = package.get("scripts", {}) if package else {}
        if scripts:
            findings.append(
                {
                    "key": "frontend_scripts",
                    "value": ", ".join(sorted(scripts)),
                    "source": "frontend/package.json",
                }
            )
        else:
            recommendations.append(
                {
                    "item": "Define frontend build scripts",
                    "severity": "high",
                    "reason": "No scripts were found in frontend/package.json.",
                }
            )
        if not _exists("Dockerfile"):
            recommendations.append(
                {
                    "item": "No Dockerfile detected",
                    "severity": "low",
                    "reason": "Container deployment is optional; absence is not an error.",
                }
            )
        if not migrations:
            recommendations.append(
                {
                    "item": "No Alembic migrations detected",
                    "severity": "high",
                    "reason": "Database schema cannot be provisioned without migrations.",
                }
            )

    if payload.mode == "environment":
        for relative in ("backend/.env.example", "frontend/.env.local.example"):
            keys = _env_keys(relative)
            if keys:
                findings.append(
                    {
                        "key": "env_keys",
                        "value": f"{len(keys)} documented variable(s)",
                        "source": relative,
                        "detail": keys,
                    }
                )
            else:
                recommendations.append(
                    {
                        "item": f"Document variables in {relative}",
                        "severity": "medium",
                        "reason": "No KEY= entries were found; only templates are ever read.",
                    }
                )
        names = _settings_names()
        if names:
            findings.append(
                {
                    "key": "backend_settings",
                    "value": f"{len(names)} declared settings",
                    "source": "backend/app/config.py",
                    "detail": names[:40],
                }
            )

    if payload.mode == "database":
        if migrations:
            findings.append(
                {
                    "key": "migration_files",
                    "value": f"{len(migrations)} revision(s) present",
                    "source": "backend/alembic/versions",
                    "detail": migrations,
                }
            )
        else:
            recommendations.append(
                {
                    "item": "Database migrations are missing",
                    "severity": "high",
                    "reason": "backend/alembic/versions contained no Python revisions.",
                }
            )
        keys = _env_keys("backend/.env.example")
        if "DATABASE_URL" in keys:
            findings.append(
                {
                    "key": "database_url_documented",
                    "value": "DATABASE_URL is documented in backend/.env.example",
                    "source": "backend/.env.example",
                }
            )

    if payload.mode == "frontend":
        if package:
            findings.append(
                {
                    "key": "frontend_package",
                    "value": package.get("name", "unnamed"),
                    "source": "frontend/package.json",
                    "detail": {
                        "scripts": sorted(package.get("scripts", {})),
                        "dependencies": sorted(package.get("dependencies", {})),
                    },
                }
            )
        if frontend_routes:
            findings.append(
                {
                    "key": "routes",
                    "value": ", ".join(name for name in frontend_routes if name.endswith("/")),
                    "source": "frontend/app",
                }
            )
        if not _exists("frontend/next.config.mjs"):
            limitations.append("frontend/next.config.mjs was not found; framework defaults apply.")

    if payload.mode == "missing_components":
        optional = {
            "tests": "Automated test directory",
            "docs": "Architecture documentation directory",
            ".github/workflows/ci.yml": "Continuous-integration workflow",
            "Dockerfile": "Container build definition",
        }
        for relative, label in optional.items():
            present = bool(_list_dir(relative)) if relative in _LIST_ALLOWLIST else _exists(relative)
            if present:
                findings.append({"key": "present", "value": label, "source": relative})
            else:
                recommendations.append(
                    {
                        "item": f"Consider adding {label.lower()}",
                        "severity": "low",
                        "reason": f"{relative} was not found in the configured project root.",
                    }
                )
        if package:
            dev = package.get("devDependencies", {})
            if not dev.get("typescript") and not dev.get("eslint"):
                recommendations.append(
                    {
                        "item": "Add static analysis tooling",
                        "severity": "medium",
                        "reason": "No TypeScript or ESLint dev dependency was found in package.json.",
                    }
                )

    if payload.project_name:
        findings.insert(
            0,
            {
                "key": "project_name",
                "value": payload.project_name,
                "source": "user objective",
            },
        )
    return _verdict(findings, recommendations, limitations)


registry.register(
    ToolSpec(
        name="project_analysis",
        description=(
            "Inspect allowlisted repository files and directory names under AGENT_PROJECT_ROOT "
            "and separate observed findings from recommendations."
        ),
        category="project",
        permission="read_only",
        input_model=ProjectAnalysisInput,
        handler=project_analysis,
        enabled_check=_configured,
        disabled_reason="AGENT_PROJECT_ROOT is not set to a readable repository directory.",
    )
)
