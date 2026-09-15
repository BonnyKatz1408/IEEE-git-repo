from pathlib import Path

IGNORED_DIRS = {".git", "venv", ".venv","dist","build","__pycache","node_modules"}
SUPPORTED_EXTENSIONS = {".py",".js",".jsx",".ts",".tsx",".cpp",".h",".java",".hpp"}

def scan_repo(repo_path):
    repo = Path(repo_path)
    files = []

    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        
        if any(part in IGNORED_DIRS for part in path.parts):
            continue

        if path.suffix in SUPPORTED_EXTENSIONS:
            files.append(path)
    return files
