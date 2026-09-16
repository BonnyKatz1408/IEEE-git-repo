from pathlib import Path
MAX_FILE_SIZE = 20971520
IGNORED_DIRS = {
    ".git",
    ".github",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    "dist",
    "build",
    "target",
    "out",
    "__pycache__",
    ".idea",
    ".vscode",
    "bin",
    "obj",
}
SUPPORTED_EXTENSIONS = {
    ".py",
    ".js", ".jsx",
    ".ts", ".tsx",
    ".cpp", ".cc", ".cxx",
    ".c",
    ".h", ".hpp",
    ".java",
    ".cs",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".json",
    ".yaml", ".yml",
    ".toml",
    ".xml",
    ".md",
    ".txt",
}

def scan_repo(repo_path):
    repo = Path(repo_path)
    files = []

    dirs_to_check = [repo]

    while dirs_to_check:
        current_dir = dirs_to_check.pop()
        try:
            for path in current_dir.iterdir():
                if path.is_dir():
                    if(path.name not in IGNORED_DIRS):
                        dirs_to_check.append(path)
                elif path.is_file():
                    if (path.suffix in SUPPORTED_EXTENSIONS and path.stat().st_size<=MAX_FILE_SIZE):
                        files.append(path)
        except PermissionError:
            continue
    return files
