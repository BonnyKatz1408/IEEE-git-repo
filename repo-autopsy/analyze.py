import subprocess
from collections import defaultdict
from pathlib import Path
from analyzer.scanner import scan_repo
from analyzer.parser import parse_file
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


def _short_name(symbol):
    return symbol["name"].split(".")[-1]


def resolve_calls(functions, calls):
    """Match call names against definitions found in this repository.

    Builtins/externals are simply the calls with no matching definition.
    Same-file matches are preferred; ambiguous cross-file name matches are skipped.
    """
    by_name = defaultdict(list)
    for symbol in functions:
        by_name[_short_name(symbol)].append(symbol)

    edges = []
    for call in calls:
        matches = by_name.get(call["name"], [])
        if not matches:
            continue

        same_file = [s for s in matches if s["file"] == call["file"]]
        if same_file:
            chosen = same_file
        elif len(matches) == 1:
            chosen = matches
        else:
            continue

        for symbol in chosen:
            target = symbol.get("qualified_name") or f"{symbol['file']}::{symbol['name']}"
            edges.append({
                "from": call.get("caller"),
                "to": target,
                "name": call["name"],
                "file": call["file"],
                "line": call["line"],
            })
    return edges


def summarize_graph(functions, edges):
    incoming = defaultdict(int)
    outgoing = defaultdict(int)
    for edge in edges:
        if edge.get("from"):
            outgoing[edge["from"]] += 1
        incoming[edge["to"]] += 1

    qualified = {
        s.get("qualified_name") or f"{s['file']}::{s['name']}": s
        for s in functions
    }

    hotspots = []
    for qname, symbol in qualified.items():
        score = incoming[qname] + outgoing[qname]
        if score == 0:
            continue
        hotspots.append({
            "name": symbol["name"],
            "qualified_name": qname,
            "incoming": incoming[qname],
            "outgoing": outgoing[qname],
            "score": score,
        })
    hotspots.sort(key=lambda h: h["score"], reverse=True)

    entry_points = []
    for qname, symbol in qualified.items():
        if incoming[qname] == 0 and outgoing[qname] > 0:
            entry_points.append({
                "name": symbol["name"],
                "qualified_name": qname,
                "outgoing": outgoing[qname],
            })
    entry_points.sort(key=lambda e: e["outgoing"], reverse=True)

    file_edges = defaultdict(int)
    for edge in edges:
        if not edge.get("from"):
            continue
        src = edge["from"].rsplit("::", 1)[0]
        dst = edge["to"].rsplit("::", 1)[0]
        if src != dst:
            file_edges[(src, dst)] += 1

    return hotspots, entry_points, file_edges


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
        allfunctions.extend(symbols)
        allcalls.extend(calls)

    alledges.extend(resolve_calls(allfunctions, allcalls))

    print("\nDEFINED METHODS:\n")
    for symbol in allfunctions:
        print(symbol)

    print("\nCALLS:\n")
    for call in allcalls:
        print(call)

    print("\nINTERNAL EDGES:\n")
    for edge in alledges:
        print(f"{edge['from']} -> {edge['to']}  ({edge['file']}:{edge['line']})")

    hotspots, entry_points, file_edges = summarize_graph(allfunctions, alledges)

    print("\nHOTSPOTS (most connected):\n")
    for item in hotspots[:20]:
        print(
            f"{item['qualified_name']}  "
            f"in={item['incoming']} out={item['outgoing']} score={item['score']}"
        )

    print("\nENTRY POINTS (defined, called nothing inbound, calls outbound):\n")
    for item in entry_points[:20]:
        print(f"{item['qualified_name']}  out={item['outgoing']}")

    print("\nFILE DEPENDENCIES:\n")
    for (src, dst), count in sorted(file_edges.items(), key=lambda kv: kv[1], reverse=True)[:30]:
        print(f"{src} -> {dst}  ({count})")

    print(
        f"\nsummary: {len(allfunctions)} definitions, "
        f"{len(allcalls)} calls, {len(alledges)} internal edges"
    )


if __name__ == "__main__":
    analyze("https://github.com/chanjoongx/atlas")
