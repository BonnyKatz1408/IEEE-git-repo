import json
import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types


DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_TIMEOUT_MS = 150000
DEFAULT_MAX_RETRIES = 3
DEFAULT_THINKING_LEVEL = "low"
MAX_SOURCE_FILES = 12
MAX_SOURCE_LINES_PER_FILE = 70
MAX_README_CHARS = 12000
MAX_SOURCE_CONTEXT_CHARS = 10000

SYSTEM_PROMPT = """You are Repo Autopsy's evidence-grounded codebase onboarding assistant.
Explain the supplied deterministic static-analysis evidence and selected source snippets.
Do not recalculate graph metrics. Do not invent functionality, business purpose, intent,
framework behavior, or relationships. Separate claims as OBSERVED, INFERRED, or UNKNOWN.
Use UNKNOWN when the evidence is insufficient. Keep the explanation concise and useful to
a developer onboarding to the repository. Return only valid JSON matching the requested schema."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "architecture": {"type": "array", "items": {"type": "object", "properties": {"module": {"type": "string"}, "description": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["module", "description", "evidence"]}},
        "execution_flows": {"type": "array", "items": {"type": "object", "properties": {"entry_point": {"type": "string"}, "description": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}}}, "required": ["entry_point", "description", "steps"]}},
        "important_functions": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "reason": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["name", "reason", "evidence"]}},
        "hotspots": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "reason": {"type": "string"}, "metrics": {"type": "object"}}, "required": ["name", "reason", "metrics"]}},
        "reading_order": {"type": "array", "items": {"type": "object", "properties": {"path": {"type": "string"}, "reason": {"type": "string"}}, "required": ["path", "reason"]}},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "summary",
        "architecture",
        "execution_flows",
        "important_functions",
        "hotspots",
        "reading_order",
        "caveats",
    ],
}


def _relative(path, root):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path


def _metric_context(report, root):
    overview = report.get("overview", {})
    modules = []
    for module in report.get("major_modules", report.get("modules", [])):
        modules.append({
            "module": module["module"],
            "loc": module.get("total_loc", 0),
            "definitions": module.get("number_of_definitions", 0),
            "imports_in": module.get("incoming_import_dependencies", 0),
            "imports_out": module.get("outgoing_import_dependencies", 0),
            "calls_in": module.get("incoming_call_dependencies", 0),
            "calls_out": module.get("outgoing_call_dependencies", 0),
            "hotspot_score": module.get("hotspot_score", 0),
            "key_functions": module.get("key_functions", []),
            "dependencies": module.get("dependencies", []),
        })

    entry_points = []
    for entry in report.get("entry_points", []):
        entry_points.append({
            "name": entry.get("qualified_name"),
            "file": _relative(entry.get("file", ""), root),
            "line": entry.get("line"),
            "fan_in": entry.get("fan_in"),
            "fan_out": entry.get("fan_out"),
            "hints": entry.get("structural_hints", []),
            "explanation": entry.get("explanation"),
        })

    hotspots = {
        "functions": [
            {
                "name": item["qualified_name"],
                "file": _relative(item["file"], root),
                "line": item.get("line"),
                "loc": item.get("loc"),
                "fan_in": item.get("fan_in"),
                "fan_out": item.get("fan_out"),
                "score": item.get("hotspot_score"),
            }
            for item in report.get("hotspots", {}).get("functions", [])
        ],
        "files": [
            {
                **item,
                "file": _relative(item["file"], root),
            }
            for item in report.get("hotspots", {}).get("files", [])
        ],
    }

    architecture_edges = []
    module_edges = report.get("module_edges")
    source_edges = module_edges or report.get("architecture_edges", [])
    for edge in source_edges:
        if edge.get("import_count", 0) or edge.get("call_count", 0):
            architecture_edges.append({
                "from": edge["from"] if module_edges else _relative(edge["from"], root),
                "to": edge["to"] if module_edges else _relative(edge["to"], root),
                "imports": edge.get("import_count", 0),
                "calls": edge.get("call_count", 0),
                "types": edge.get("types", []),
            })

    flows = []
    for flow in report.get("execution_flows", report.get("flows", [])):
        flows.append({
            "entry_point": flow.get("entry_point"),
            "tree": flow.get("tree"),
            "evidence": flow.get("evidence", {}),
        })

    reading_order = []
    for item in report.get("reading_order", []):
        reading_order.append({
            "rank": item.get("rank"),
            "path": item.get("display_name", _relative(item.get("file", ""), root)),
            "module": item.get("module"),
            "score": item.get("score"),
            "evidence": item.get("evidence", []),
        })

    return {
        "overview": {
            "languages": overview.get("languages", []),
            "file_count": overview.get("file_count", 0),
            "function_count": overview.get("function_count", 0),
            "module_count": overview.get("module_count", 0),
        },
        "major_modules": modules,
        "entry_points": entry_points,
        "hotspots": hotspots,
        "architecture_edges": architecture_edges,
        "execution_flows": flows,
        "reading_order": reading_order,
        "cycles": report.get("cycles", []),
    }


def _important_function_context(report):
    categories = report.get("important_functions", {})
    return {
        category: [
            {
                "name": item.get("qualified_name"),
                "file": item.get("file"),
                "line": item.get("line"),
                "loc": item.get("loc"),
                "fan_in": item.get("fan_in"),
                "fan_out": item.get("fan_out"),
                "hotspot_score": item.get("hotspot_score"),
                "evidence": item.get("evidence", []),
            }
            for item in items
        ]
        for category, items in categories.items()
    }


def _module_metrics_context(report):
    return [
        {
            "module": module.get("module"),
            "loc": module.get("total_loc"),
            "definitions": module.get("number_of_definitions"),
            "imports_in": module.get("incoming_import_dependencies"),
            "imports_out": module.get("outgoing_import_dependencies"),
            "calls_in": module.get("incoming_call_dependencies"),
            "calls_out": module.get("outgoing_call_dependencies"),
            "internal_edges": module.get("internal_edges"),
            "hotspot_score": module.get("hotspot_score"),
        }
        for module in report.get("major_modules", report.get("modules", []))
    ]


def _file_metrics_context(report, root):
    selected = {}
    for item in report.get("hotspots", {}).get("files", []):
        selected[item.get("file")] = item
    for item in report.get("reading_order", []):
        selected[item.get("file")] = next(
            (metric for metric in report.get("file_metrics", []) if metric.get("file") == item.get("file")),
            selected.get(item.get("file")),
        )
    return [
        {
            "file": _relative(file_name, root),
            "loc": item.get("loc"),
            "definitions": item.get("number_of_defined_functions"),
            "imports_in": item.get("incoming_import_dependencies", 0),
            "imports_out": item.get("outgoing_import_dependencies", 0),
            "calls_in": item.get("incoming_call_dependencies", 0),
            "calls_out": item.get("outgoing_call_dependencies", 0),
            "internal_edges": item.get("internal_edges", 0),
            "hotspot_score": item.get("hotspot_score"),
        }
        for file_name, item in selected.items()
        if item
    ]


def _static_sections(report, root):
    context = _metric_context(report, root)
    compact_chains = []
    for flow in context["execution_flows"]:
        tree = flow.get("tree") or {}
        compact_chains.append({
            "entry_point": flow.get("entry_point"),
            "evidence": flow.get("evidence", {}),
            "branches": _compact_chain(tree),
        })
    return {
        "REPOSITORY OVERVIEW": context["overview"],
        "MAJOR MODULES": context["major_modules"],
        "LIKELY ENTRY POINTS": context["entry_points"],
        "TOP HOTSPOTS": context["hotspots"],
        "IMPORTANT FUNCTIONS": _important_function_context(report),
        "ARCHITECTURE EDGES": context["architecture_edges"],
        "DEPENDENCY CHAINS": compact_chains,
        "RECOMMENDED READING ORDER": context["reading_order"],
        "FILE/MODULE METRICS": {
            "modules": _module_metrics_context(report),
            "important_files": _file_metrics_context(report, root),
        },
        "CYCLES": context["cycles"],
        "CAVEATS": report.get("architectural_notes", {}).get("observations", []),
    }


def _compact_chain(node, depth=0):
    """Keep entry branches and one useful child level, omitting utility fan-out."""
    if depth >= 2:
        return []
    children = node.get("children", [])[:5]
    return [
        {
            "function": child.get("node"),
            "children": _compact_chain(child, depth + 1),
        }
        for child in children
    ]


def _function_source_candidates(report, root):
    candidates = {}
    for metric in report.get("function_metrics", []):
        if metric.get("is_test"):
            continue
        candidates[metric["qualified_name"]] = {
            "file": metric["file"],
            "line": metric.get("line", 1),
            "end_line": metric.get("end_line", metric.get("line", 1) + 80),
            "priority": metric.get("hotspot_score", 0),
        }
    for entry in report.get("entry_points", []):
        item = candidates.get(entry.get("qualified_name"))
        if item:
            item["priority"] += 2.0
    for chain in report.get("execution_flows", report.get("flows", [])):
        root_name = chain.get("entry_point")
        item = candidates.get(root_name)
        if item:
            item["priority"] += 1.0

        def prioritize_children(node):
            child_item = candidates.get(node.get("qualified_name") or node.get("node"))
            if child_item:
                child_item["priority"] += 0.75
            for child in node.get("children", []):
                prioritize_children(child)

        prioritize_children(chain.get("tree", {}))
    return candidates


def select_source_context(report, root):
    """Select bounded, evidence-linked source snippets for the model."""
    candidates = _function_source_candidates(report, root)
    selected = []
    selected_files = set()
    for qualified_name, item in sorted(candidates.items(), key=lambda pair: (-pair[1]["priority"], pair[0])):
        if len(selected_files) >= MAX_SOURCE_FILES and item["file"] not in selected_files:
            continue
        try:
            lines = Path(item["file"]).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        start = max(1, item["line"])
        end = min(len(lines), max(start, item["end_line"]))
        if end - start + 1 > MAX_SOURCE_LINES_PER_FILE:
            end = start + MAX_SOURCE_LINES_PER_FILE - 1
        selected.append({
            "file": _relative(item["file"], root),
            "function": qualified_name,
            "line_start": start,
            "line_end": end,
            "source": "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1)),
            "selection_basis": "entry point, hotspot, or dependency-flow relevance",
        })
        selected_files.add(item["file"])
        if len(selected) >= MAX_SOURCE_FILES:
            break
    return selected


def select_readme_context(root):
    """Read only the repository root README as bounded documentation context."""
    readme = Path(root) / "README.md"
    if not readme.is_file():
        readme = next(
            (candidate for candidate in Path(root).iterdir() if candidate.name.lower() == "readme.md"),
            None,
        )
    if readme is None or not readme.is_file():
        return None
    try:
        source = readme.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    return {
        "file": readme.name,
        "source": source[:MAX_README_CHARS],
        "truncated": len(source) > MAX_README_CHARS,
        "selection_basis": "repository-provided general context",
    }


def build_context(report, root):
    static_sections = _static_sections(report, root)
    readme = select_readme_context(root)
    source = select_source_context(report, root)
    if not static_sections["REPOSITORY OVERVIEW"]["file_count"] and not source:
        return ""
    sections = ["=== STATIC ANALYSIS ==="]
    for name, value in static_sections.items():
        sections.append(f"\n{name}:\n{json.dumps(value, indent=2)}")
    sections.append(f"\n=== REPOSITORY DOCUMENTATION ===\n{json.dumps(readme, indent=2)}")
    metadata = "\n".join(sections)
    source_context = json.dumps(source, indent=2)
    if len(source_context) > MAX_SOURCE_CONTEXT_CHARS:
        source_context = source_context[:MAX_SOURCE_CONTEXT_CHARS]
    return f"{metadata}\n\n=== SELECTED SOURCE CODE ===\n{source_context}"


def _request_prompt(context):
    user_prompt = f"""{context}

=== TASK ===
Use STATIC ANALYSIS as the primary source of truth. Transform the supplied evidence; do not
rediscover or recalculate it.
MAJOR MODULES -> ARCHITECTURE.
LIKELY ENTRY POINTS -> HOW IT WORKS.
DEPENDENCY CHAINS -> EXECUTION FLOWS.
RECOMMENDED READING ORDER -> WHERE TO START.
TOP HOTSPOTS and IMPORTANT FUNCTIONS -> IMPORTANT FUNCTIONS and HOTSPOTS.
ARCHITECTURE EDGES -> MODULE RELATIONSHIPS, preserving imports versus calls versus both.
FILE/MODULE METRICS -> evidence attached to claims.
Never output UNKNOWN for a field when STATIC ANALYSIS contains that value. For example, use
the exact entry_point from LIKELY ENTRY POINTS and the exact path from RECOMMENDED READING ORDER.
Only output UNKNOWN when the requested fact genuinely does not exist in the supplied evidence.
Every claim should identify OBSERVED, INFERRED, or UNKNOWN and cite concise evidence.
Repository documentation is general context, not proof when it conflicts with static analysis.

Return exactly this JSON shape:
{json.dumps(OUTPUT_SCHEMA, indent=2)}"""
    return user_prompt


def _extract_text(payload):
    candidates = payload.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini response did not contain candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts)
    if not text.strip():
        raise ValueError("Gemini response was empty")
    return text


def _validate_explanation(explanation):
    required = set(OUTPUT_SCHEMA["required"])
    missing = sorted(required - set(explanation))
    if missing:
        raise ValueError(f"Gemini explanation missing fields: {', '.join(missing)}")
    if not isinstance(explanation["summary"], str):
        raise ValueError("Gemini explanation summary must be a string")
    for field in required - {"summary"}:
        if not isinstance(explanation[field], list):
            raise ValueError(f"Gemini explanation field {field} must be an array")


def _is_unknown(value):
    return not value or str(value).strip().lower() in {"unknown", "unknown module", "unknown entry point", "unknown path"}


def _normalize_deterministic_identifiers(explanation, report, root):
    """Keep model prose, but anchor identifiers to deterministic report values."""
    modules = report.get("major_modules", report.get("modules", []))
    generated_architecture = explanation.get("architecture", [])
    architecture = []
    for index, module in enumerate(modules):
        match = next((item for item in generated_architecture if item.get("module") == module.get("module")), None)
        if match is None and index < len(generated_architecture):
            match = generated_architecture[index]
        match = match or {}
        architecture.append({
            "module": module.get("module"),
            "description": match.get("description") if not _is_unknown(match.get("description")) else module.get("description", "Observed module group."),
            "evidence": match.get("evidence") or module.get("evidence", []),
        })
    explanation["architecture"] = architecture

    chains = report.get("execution_flows", report.get("flows", []))
    generated_flows = explanation.get("execution_flows", [])
    flows = []
    for index, chain in enumerate(chains):
        match = next((item for item in generated_flows if item.get("entry_point") == chain.get("entry_point")), None)
        if match is None and index < len(generated_flows):
            match = generated_flows[index]
        match = match or {}
        flows.append({
            "entry_point": chain.get("entry_point"),
            "description": match.get("description") if not _is_unknown(match.get("description")) else "Observed bounded dependency chain from this entry point.",
            "steps": match.get("steps") or _flow_step_names(chain.get("tree", {})),
        })
    explanation["execution_flows"] = flows

    reading = report.get("reading_order", [])
    generated_reading = explanation.get("reading_order", [])
    explanation["reading_order"] = [
        {
            "path": item.get("display_name", _relative(item.get("file", ""), root)),
            "reason": (
                generated_reading[index].get("reason")
                if index < len(generated_reading) and not _is_unknown(generated_reading[index].get("reason"))
                else "; ".join(item.get("evidence", [])) or "Deterministic onboarding ranking"
            ),
        }
        for index, item in enumerate(reading)
    ]


def _flow_step_names(node):
    names = []
    for child in node.get("children", []):
        name = child.get("node", "")
        names.append(name)
    return names


def _fallback(
    status,
    message,
    context_size=0,
    model=None,
    timeout_ms=None,
    attempts=0,
    input_character_count=None,
):
    return {
        "status": status,
        "model": model or DEFAULT_MODEL,
        "summary": None,
        "explanation": None,
        "error": message,
        "context_size": context_size,
        "input_character_count": input_character_count or context_size,
        "estimated_context_tokens": (input_character_count or context_size) // 4,
        "timeout_ms": timeout_ms,
        "attempts": attempts,
    }


def _env_file_value(env_file, variable):
    if not env_file:
        return None
    try:
        lines = Path(env_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != variable:
            continue
        value = value.strip().strip("'\"")
        return value or None
    return None


def _env_file_key(env_file):
    return _env_file_value(env_file, "GEMINI_API_KEY")


def generate_explanation(
    report,
    root,
    api_key=None,
    timeout_ms=None,
    env_file=None,
    max_retries=None,
):
    """Generate a structured Gemini explanation without making static analysis dependent on it."""
    context = build_context(report, root)
    context_size = len(context)
    if not context:
        return _fallback("skipped", "analysis context is empty", context_size)
    api_key = api_key or os.getenv("GEMINI_API_KEY") or _env_file_key(env_file)
    if not api_key:
        return _fallback("skipped", "GEMINI_API_KEY is not set", context_size)

    model = os.getenv("GEMINI_MODEL") or _env_file_value(env_file, "GEMINI_MODEL") or DEFAULT_MODEL
    timeout_ms = timeout_ms or int(os.getenv("GEMINI_TIMEOUT_MS") or _env_file_value(env_file, "GEMINI_TIMEOUT_MS") or DEFAULT_TIMEOUT_MS)
    max_retries = max_retries or int(os.getenv("GEMINI_MAX_RETRIES") or _env_file_value(env_file, "GEMINI_MAX_RETRIES") or DEFAULT_MAX_RETRIES)
    thinking_level = os.getenv("GEMINI_THINKING_LEVEL") or _env_file_value(env_file, "GEMINI_THINKING_LEVEL") or DEFAULT_THINKING_LEVEL
    prompt = _request_prompt(context)
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=OUTPUT_SCHEMA,
                    thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
                ),
            )
            explanation = json.loads(response.text)
            if not isinstance(explanation, dict):
                raise ValueError("Gemini explanation was not a JSON object")
            _normalize_deterministic_identifiers(explanation, report, root)
            _validate_explanation(explanation)
            return {
                "status": "ok",
                "model": model,
                "summary": explanation.get("summary"),
                "explanation": explanation,
                "error": None,
                "context_size": context_size,
                "input_character_count": len(prompt),
                "estimated_context_tokens": len(prompt) // 4,
                "timeout_ms": timeout_ms,
                "thinking_level": thinking_level,
                "attempts": attempt,
            }
        except Exception as error:  # SDK exception types vary across releases.
            last_error = error
            error_code = getattr(error, "code", None)
            error_text = str(error).lower()
            transient = (
                isinstance(error, (TimeoutError, OSError))
                or error_code == 429
                or (isinstance(error_code, int) and error_code >= 500)
                or any(token in error_text for token in ("timeout", "temporarily unavailable", "service unavailable"))
            )
            print(
                f"Gemini request failed: model={model} input_chars={len(prompt)} "
                f"estimated_context_tokens={len(prompt) // 4} timeout_ms={timeout_ms} "
                f"attempt={attempt}/{max_retries} error_type={type(error).__name__}",
                file=sys.stderr,
            )
            if not transient or attempt >= max_retries:
                status = "rate_limited" if error_code == 429 else "malformed_response" if isinstance(error, (json.JSONDecodeError, ValueError, TypeError)) else "api_error"
                return _fallback(
                    status,
                    f"Gemini request failed: {error}",
                    context_size,
                    model,
                    timeout_ms,
                    attempt,
                    len(prompt),
                )
            time.sleep(2 ** (attempt - 1))

    return _fallback(
        "api_error",
        f"Gemini request failed: {last_error}",
        context_size,
        model,
        timeout_ms,
        max_retries,
        len(prompt),
    )
