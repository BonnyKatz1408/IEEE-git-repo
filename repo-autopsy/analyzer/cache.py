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
    if not analysis_path.exists() or not map_path.exists():
        return None
    report = json.loads(analysis_path.read_text(encoding="utf-8"))
    report["map"] = json.loads(map_path.read_text(encoding="utf-8"))
    report["cache"] = {"hit": True, "key": "/".join(Path(directory).parts[-3:])}
    return report


def save_cached_report(directory, report):
    directory.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in report.items() if key != "map"}
    (directory / "analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (directory / "map.json").write_text(
        json.dumps(report.get("map") or {}, ensure_ascii=False),
        encoding="utf-8",
    )


def trim_client_payload(report):
    trimmed = {key: value for key, value in report.items() if key not in PAYLOAD_OMIT}
    issues = trimmed.get("resolution_issues") or []
    if isinstance(issues, list) and len(issues) > 40:
        trimmed["resolution_issues"] = issues[:40]
        trimmed["unresolved_call_count"] = len(issues)
    return trimmed
