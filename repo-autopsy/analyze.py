import subprocess
from pathlib import Path
from analyzer.scanner import scan_repo
from analyzer.parser import parse_file
from analyzer.resolver import resolve_calls
from analyzer.graph_analysis import analyze_graph
from analyzer.imports import analyze_imports
from analyzer.architecture import enrich_architecture
from analyzer.report import build_report, print_report
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
    report["llm_explanation"] = {
        "status": "disabled",
        "model": None,
        "error": "Gemini is disabled while the deterministic map is being developed.",
    }
    return report


if __name__ == "__main__":
    analyze("https://github.com/vishal-baliyan-ji/Liberary_management_system")
