import json
from pathlib import Path


PAYLOAD_OMIT = {
    "graph",
    "reverse_graph",
    "file_graph",
    "most_depended_on",
    "highest_fan_out",
    "imports",
}


def cache_dir(project_root, owner, repo, sha):
    return Path(project_root) / "cache" / owner / repo / sha


def load_cached_report(directory):
    analysis_path = directory / "analysis.json"
    map_path = directory / "map.json"
    rag_path = directory / "rag.json"
    if not analysis_path.exists() or not map_path.exists():
        return None
    report = json.loads(analysis_path.read_text(encoding="utf-8"))
    report["map"] = json.loads(map_path.read_text(encoding="utf-8"))
    if rag_path.exists():
        report["rag"] = json.loads(rag_path.read_text(encoding="utf-8"))
    report["cache"] = {"hit": True, "key": "/".join(Path(directory).parts[-3:])}
    return report


def save_cached_report(directory, report):
    directory.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in report.items() if key not in {"map", "rag"}}
    (directory / "analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (directory / "map.json").write_text(
        json.dumps(report.get("map") or {}, ensure_ascii=False),
        encoding="utf-8",
    )
    if report.get("rag") is not None:
        (directory / "rag.json").write_text(
            json.dumps(report.get("rag") or {}, ensure_ascii=False),
            encoding="utf-8",
        )


def load_ai_answer(directory, intent):
    path = directory / "ai.json"
    if not path.exists():
        return None
    try:
        answers = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    answer = answers.get(intent)
    if not isinstance(answer, dict) or answer.get("mode") != "gemini-rag" or not answer.get("grounded"):
        return None
    cached = dict(answer)
    cached["cached"] = True
    return cached


def save_ai_answer(directory, intent, answer):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ai.json"
    try:
        answers = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        answers = {}
    answers[intent] = answer
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")


def trim_client_payload(report):
    trimmed = {key: value for key, value in report.items() if key not in PAYLOAD_OMIT}
    issues = trimmed.get("resolution_issues") or []
    if isinstance(issues, list) and len(issues) > 40:
        trimmed["resolution_issues"] = issues[:40]
        trimmed["unresolved_call_count"] = len(issues)
    return trimmed
