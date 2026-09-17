import subprocess
from pathlib import Path
from analyzer.scanner import scan_repo
from analyzer.parser import parse_file
from analyzer.resolver import resolve_calls
from analyzer.graph_analysis import analyze_graph
from analyzer.imports import analyze_imports
from analyzer.architecture import enrich_architecture
from analyzer.report import build_report, print_report
from analyzer.explainer import generate_explanation
from analyzer.extractors.java import extract as extract_java
from analyzer.extractors.cpp import extract as extract_cpp
from analyzer.extractors.js import extract as extract_javascript
from analyzer.extractors.pyt import extract as extract_python
from analyzer.extractors.typescript import extract as extract_typescript
from analyzer.extractors.c import extract as extract_c


#map suffixes to extractors
EXTRACTORS = {
    "java": extract_java,
    "cpp" : extract_cpp,
    "javascript" : extract_javascript,
    "python" : extract_python,
    "typescript" : extract_typescript,
    "c" : extract_c
}

#map suffixes to languages
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

# Stores all functions/methods found across the repo
allfunctions = []
allcalls = []
alledges = []


# ------------------------------------------------------------------ #
# url cleaner and standardizer
def clean(url):
    url = url.strip().replace(" ", "")
    index = url.lower().find("github.com")

    if index != -1:
        url = url[index:]

        if not url.startswith(("http://", "https://")):
            url = "https://" + url
    else:
        url = "https://github.com/" + url.lstrip("/")

    return url


def _label(qualified_name):
    if not qualified_name:
        return None
    return qualified_name.split("::")[-1]


def _print_chain(node, prefix=""):
    for index, child in enumerate(node.get("children", [])):
        branch = "└── " if index == len(node["children"]) - 1 else "├── "
        print(f"{prefix}{branch}{_label(child['node'])}")
        next_prefix = prefix + ("    " if index == len(node["children"]) - 1 else "│   ")
        _print_chain(child, next_prefix)


#clone repo
# ------------------------------------------------------------------ #
def analyze(url):
    allfunctions.clear()
    allcalls.clear()
    alledges.clear()

    url = clean(url)

    repo_name = url.rstrip("/").split("/")[-1]

    project_root = Path(__file__).resolve().parents[1]

    repo_path = project_root / "repos" / repo_name

    if not repo_path.exists():
        subprocess.run(
            ["git", "clone", url, str(repo_path)],
            check=True
        )

    files = scan_repo(repo_path)

    print(f"found {len(files)} source files")

    for file in files:
        language = LANGUAGES.get(file.suffix)
        if language is None:
            continue
        extractor = EXTRACTORS.get(language)
        if extractor is None:
            continue
        tree = parse_file(file, language)
        symbols, calls = extractor(tree, file)
        file_loc = len(file.read_text(encoding="utf-8", errors="ignore").splitlines())
        for symbol in symbols:
            symbol["loc"] = max(1, symbol["end_line"] - symbol["line"] + 1)
            symbol["file_loc"] = file_loc
        allfunctions.extend(symbols)
        allcalls.extend(calls)

    resolution = resolve_calls(allfunctions, allcalls)
    alledges.extend(resolution["edges"])
    source_files = {
        str(file): len(file.read_text(encoding="utf-8", errors="ignore").splitlines())
        for file in files
        if file.suffix in LANGUAGES
    }
    analysis = analyze_graph(allfunctions, alledges, source_files)
    import_analysis = analyze_imports(source_files, repo_path)
    analysis.update(enrich_architecture(analysis, import_analysis, source_files, repo_path))
    analysis["resolution_issues"] = resolution["unresolved"]
    report = build_report(analysis, source_files, LANGUAGES, repo_path)
    print("\nDETERMINISTIC ANALYSIS")
    print_report(report, repo_path)
    explanation = generate_explanation(report, repo_path, env_file=project_root / ".env")
    report["llm_explanation"] = explanation
    print("\nGEMINI EXPLANATION")
    print(f"status: {explanation['status']} | model: {explanation['model']}")
    print(
        f"input_chars: {explanation.get('input_character_count', explanation.get('context_size', 0))} "
        f"estimated_context_tokens: {explanation.get('estimated_context_tokens', 0)} "
        f"timeout_ms: {explanation.get('timeout_ms', 'n/a')} "
        f"thinking_level: {explanation.get('thinking_level', 'low')} "
        f"attempts: {explanation.get('attempts', 0)}"
    )
    if explanation["status"] == "ok":
        generated = explanation.get("explanation") or {}
        print("\nSUMMARY")
        print(generated.get("summary") or "Gemini returned a structured explanation without a summary.")
        print("\nARCHITECTURE")
        for item in generated.get("architecture", []):
            print(f"- {item.get('module', item.get('name', 'unknown module'))}: {item.get('description', item.get('reason', 'UNKNOWN'))}")
        print("\nHOW IT WORKS")
        for flow in generated.get("execution_flows", []):
            print(f"- {flow.get('entry_point', 'unknown entry point')}: {flow.get('description', 'UNKNOWN')}")
            for step in flow.get("steps", []):
                print(f"  - {step}")
        print("\nWHERE TO START")
        for item in generated.get("reading_order", []):
            print(f"- {item.get('path', 'unknown path')}: {item.get('reason', 'UNKNOWN')}")
        if generated.get("caveats"):
            print("\nCAVEATS")
            for caveat in generated["caveats"]:
                print(f"- {caveat}")
    else:
        print(f"unavailable: {explanation['error']}")
    return report


if __name__ == "__main__":
    analyze("https://github.com/chanjoongx/atlas")
