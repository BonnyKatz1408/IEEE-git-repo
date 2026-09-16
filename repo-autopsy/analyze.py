import subprocess
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


#clone repo
# ------------------------------------------------------------------ #
def analyze(url):

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
        symbols = extractor(tree, file)
        allfunctions.extend(symbols)
    
    print("\nDEFINED METHODS:\n")
    for symbol in allfunctions:
        print(symbol)


analyze("https://github.com/chanjoongx/atlas")