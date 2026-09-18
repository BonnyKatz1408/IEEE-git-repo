import json
import subprocess
from pathlib import Path

from analyzer.scanner import scan_repo
from analyzer.parser import parse_file
from analyzer.resolver import resolve_calls
from analyzer.graph_analysis import analyze_graph
from analyzer.imports import analyze_imports
from analyzer.architecture import enrich_architecture
from analyzer.report import build_report, print_report
from analyzer.map_layout import build_map_layout
from analyzer.rag import RAG_INDEX_VERSION, build_rag_index
from analyzer.cache import cache_dir, load_cached_report, save_cached_report, trim_client_payload
from analyzer.extractors.java import extract as extract_java
from analyzer.extractors.cpp import extract as extract_cpp
from analyzer.extractors.js import extract as extract_javascript
from analyzer.extractors.pyt import extract as extract_python
from analyzer.extractors.typescript import extract as extract_typescript
from analyzer.extractors.c import extract as extract_c


EXTRACTORS = {
    "java": extract_java,
    "cpp": extract_cpp,
    "javascript": extract_javascript,
    "python": extract_python,
    "typescript": extract_typescript,
    "c": extract_c,
}

LANGUAGES = {
    ".java": "java",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".c": "c",
}

allfunctions = []
allcalls = []
alledges = []


def clean(url):
    url = url.strip().replace(" ", "")
    index = url.lower().find("github.com")

    if index != -1:
        url = url[index:]
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
    else:
        url = "https://github.com/" + url.lstrip("/")

    return url.rstrip("/").removesuffix(".git")


def github_identity(url):
    parts = clean(url).rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError("Could not parse GitHub owner/repository from URL.")
    return parts[-2], parts[-1]


def resolve_commit_sha(url):
    result = subprocess.run(
        ["git", "ls-remote", f"{clean(url)}.git", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    sha = (result.stdout.split() or [""])[0].strip()
    if not sha:
        raise RuntimeError("Could not resolve the repository HEAD commit.")
    return sha


def checkout_commit(repo_path, url, sha):
    repo_path = Path(repo_path)
    if not (repo_path / ".git").exists():
        subprocess.run(["git", "clone", "--filter=blob:none", url, str(repo_path)], check=True)
    current = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if current.returncode == 0 and current.stdout.strip() == sha:
        return
    subprocess.run(["git", "-C", str(repo_path), "fetch", "--depth", "1", "origin", sha], check=False)
    checkout = subprocess.run(["git", "-C", str(repo_path), "checkout", "--force", sha], capture_output=True, text=True)
    if checkout.returncode != 0:
        subprocess.run(["git", "-C", str(repo_path), "fetch", "origin"], check=True)
        subprocess.run(["git", "-C", str(repo_path), "checkout", "--force", sha], check=True)


def _label(qualified_name):
    if not qualified_name:
        return None
    return qualified_name.split("::")[-1]


def analyze(url):
    allfunctions.clear()
    allcalls.clear()
    alledges.clear()

    url = clean(url)
    owner, repo_name = github_identity(url)
    project_root = Path(__file__).resolve().parents[1]
    sha = resolve_commit_sha(url)
    cached = load_cached_report(cache_dir(project_root, owner, repo_name, sha))
    if cached:
        cached.setdefault("overview", {})["repository"] = f"{owner}/{repo_name}"
        cached["version"] = {"owner": owner, "repo": repo_name, "sha": sha}
        rag_cache = cached.get("rag") or {}
        if rag_cache.get("version") != RAG_INDEX_VERSION or not rag_cache.get("chunks"):
            repo_path = project_root / "repos" / repo_name
            checkout_commit(repo_path, url, sha)
            cached["rag"] = build_rag_index(cached, repo_path)
            save_cached_report(cache_dir(project_root, owner, repo_name, sha), cached)
        print(f"cache hit for {owner}/{repo_name}@{sha[:12]}")
        cached["cache"] = {"hit": True, "key": f"{owner}/{repo_name}/{sha}"}
        return trim_client_payload(cached)

    repo_path = project_root / "repos" / repo_name
    checkout_commit(repo_path, url, sha)

    files = scan_repo(repo_path)
    print(f"found {len(files)} source files")
    source_files = {}

    for file in files:
        language = LANGUAGES.get(file.suffix)
        if language is None:
            continue
        extractor = EXTRACTORS.get(language)
        if extractor is None:
            continue
        tree, source = parse_file(file, language)
        file_loc = source.decode("utf-8", errors="ignore").count("\n") + (0 if source.endswith(b"\n") else 1 if source else 0)
        if not source:
            file_loc = 0
        source_files[str(file)] = max(file_loc, len(source.decode("utf-8", errors="ignore").splitlines()))
        symbols, calls = extractor(tree, file)
        for symbol in symbols:
            symbol["loc"] = max(1, symbol["end_line"] - symbol["line"] + 1)
            symbol["file_loc"] = source_files[str(file)]
        allfunctions.extend(symbols)
        allcalls.extend(calls)

    resolution = resolve_calls(allfunctions, allcalls)
    alledges.extend(resolution["edges"])
    analysis = analyze_graph(allfunctions, alledges, source_files)
    import_analysis = analyze_imports(source_files, repo_path)
    analysis.update(enrich_architecture(analysis, import_analysis, source_files, repo_path))
    analysis["resolution_issues"] = resolution["unresolved"]
    report = build_report(analysis, source_files, LANGUAGES, repo_path)
    report["overview"]["repository"] = f"{owner}/{repo_name}"
    report["version"] = {"owner": owner, "repo": repo_name, "sha": sha}
    report["map"] = build_map_layout(report)
    report["rag"] = build_rag_index(report, repo_path)
    print("\nDETERMINISTIC ANALYSIS")
    print_report(report, repo_path)
    report["llm_explanation"] = {
        "status": "disabled",
        "model": None,
        "error": "Gemini is disabled while the deterministic map is being developed.",
    }
    payload = trim_client_payload(report)
    payload["rag"] = report["rag"]
    save_cached_report(cache_dir(project_root, owner, repo_name, sha), payload)
    payload["cache"] = {"hit": False, "key": f"{owner}/{repo_name}/{sha}"}
    return payload


if __name__ == "__main__":
    print(json.dumps(analyze("https://github.com/vishal-baliyan-ji/Liberary_management_system").get("overview"), indent=2))
