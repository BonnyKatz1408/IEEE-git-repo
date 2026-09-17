import re
from pathlib import Path


LANGUAGE_BY_SUFFIX = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
}


def _record(module, line, kind="import", local_candidate=True, imported_name=None):
    return {
        "module": module,
        "line": line,
        "kind": kind,
        "local_candidate": local_candidate,
        "imported_name": imported_name,
    }


def _extract_javascript(source):
    imports = []
    patterns = [
        (r"\bimport\s+(?:[\s\S]*?\s+from\s+)?['\"]([^'\"]+)['\"]", "import"),
        (r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", "require"),
    ]
    for pattern, kind in patterns:
        for match in re.finditer(pattern, source):
            line = source.count("\n", 0, match.start()) + 1
            imports.append(_record(match.group(1), line, kind))
    return imports


def _extract_python(source):
    imports = []
    for match in re.finditer(r"^\s*from\s+([.\w]+)\s+import\s+([^#\n]+)", source, re.MULTILINE):
        module = match.group(1)
        imports.append(_record(module, source.count("\n", 0, match.start()) + 1, imported_name=match.group(2).strip()))
    for match in re.finditer(r"^\s*import\s+([^#\n]+)", source, re.MULTILINE):
        line = source.count("\n", 0, match.start()) + 1
        for item in match.group(1).split(","):
            module = item.strip().split(" as ", 1)[0].strip()
            if module:
                imports.append(_record(module, line, imported_name=None))
    return imports


def _extract_java(source):
    imports = []
    for match in re.finditer(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;", source, re.MULTILINE):
        module = match.group(1)
        imports.append(_record(module, source.count("\n", 0, match.start()) + 1, imported_name=module.rsplit(".", 1)[-1]))
    return imports


def _extract_c(source):
    imports = []
    for match in re.finditer(r"^\s*#\s*include\s*([<\"])([^>\"\n]+)[>\"]", source, re.MULTILINE):
        delimiter, module = match.groups()
        imports.append(_record(module.strip(), source.count("\n", 0, match.start()) + 1, "include", delimiter == '"'))
    return imports


def extract_imports(file_path, source, language=None):
    language = language or LANGUAGE_BY_SUFFIX.get(Path(file_path).suffix)
    if language in {"javascript", "typescript"}:
        imports = _extract_javascript(source)
    elif language == "python":
        imports = _extract_python(source)
    elif language == "java":
        imports = _extract_java(source)
    elif language in {"c", "cpp"}:
        imports = _extract_c(source)
    else:
        imports = []
    for item in imports:
        item["source"] = str(file_path)
        item["language"] = language
    return imports


def _unique_candidates(candidates):
    unique = {str(path.resolve()) for path in candidates if path.is_file()}
    return sorted(unique)


def _extension_candidates(path, extensions):
    candidates = [path]
    if not path.suffix:
        candidates.extend(path.with_suffix(extension) for extension in extensions)
        candidates.extend(path / ("index" + extension) for extension in extensions)
        candidates.append(path / "__init__.py")
    return candidates


def _resolve_javascript(source, module, files, root):
    if not module.startswith("."):
        return None
    path = (Path(source).parent / module).resolve()
    candidates = _extension_candidates(path, (".ts", ".tsx", ".js", ".jsx"))
    return next((candidate for candidate in _unique_candidates(candidates) if str(candidate) in files), None)


def _resolve_python(source, module, files, root):
    if module.startswith("."):
        level = len(module) - len(module.lstrip("."))
        base = Path(source).parent
        for _ in range(max(0, level - 1)):
            base = base.parent
        path = base / module[level:].replace(".", "/")
    else:
        path = root / module.replace(".", "/")
    candidates = _extension_candidates(path, (".py",))
    return next((candidate for candidate in _unique_candidates(candidates) if str(candidate) in files), None)


def _resolve_java(source, module, files, root):
    if module.endswith(".*"):
        return None
    path = root / (module.replace(".", "/") + ".java")
    return str(path.resolve()) if str(path.resolve()) in files else None


def _resolve_c(source, module, files, root):
    local = (Path(source).parent / module).resolve()
    root_candidate = (root / module).resolve()
    matches = [path for path in (local, root_candidate) if str(path) in files]
    return matches[0] if len(set(matches)) == 1 else None


def resolve_import(source, item, files, root):
    if not item["local_candidate"]:
        return None
    language = item["language"]
    module = item["module"]
    if language in {"javascript", "typescript"}:
        return _resolve_javascript(source, module, files, root)
    if language == "python":
        return _resolve_python(source, module, files, root)
    if language == "java":
        return _resolve_java(source, module, files, root)
    if language in {"c", "cpp"}:
        return _resolve_c(source, module, files, root)
    return None


def analyze_imports(files, root):
    file_set = {str(Path(file).resolve()) for file in files}
    root = Path(root).resolve()
    imports = []
    edges = []
    unresolved = []
    for file in files:
        source = Path(file).read_text(encoding="utf-8", errors="ignore")
        for item in extract_imports(file, source):
            item = dict(item)
            target = resolve_import(file, item, file_set, root)
            item["resolved_file"] = target
            imports.append(item)
            if target is None:
                unresolved.append(item)
                continue
            edges.append({"from": str(Path(file).resolve()), "to": target, "type": "import"})
    return {"imports": imports, "import_edges": edges, "unresolved_imports": unresolved}
