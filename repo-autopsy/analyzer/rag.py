import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path

from analyzer.scanner import scan_repo


DEFAULT_CHUNK_LIMIT = 6
DEFAULT_GEMINI_MODEL = 'gemini-3.6-flash'
RAG_INDEX_VERSION = 2
LOGGER = logging.getLogger(__name__)


def classify_question(question, metadata=None):
    text = str(question or '').lower()
    metadata = metadata or {}
    if any(term in text for term in ('depend', 'caller', 'callee', 'calls ', 'imports', 'imported by')):
        return 'dependency'
    if metadata.get('type') == 'function' or 'function' in text or 'symbol' in metadata:
        return 'function-explanation'
    if metadata.get('type') == 'file' or 'this file' in text or re.search(r'\b(file|\.py|\.js|\.ts|\.tsx|\.java)\b', text):
        return 'file-explanation'
    if any(term in text for term in ('entry point', 'entry points')):
        return 'entry-points'
    if 'hotspot' in text:
        return 'hotspots'
    if any(term in text for term in ('important module', 'major module', 'modules')):
        return 'modules'
    if any(term in text for term in ('file structure', 'function structure', 'class structure', 'structure of')):
        return 'file-structure'
    if any(term in text for term in ('affected', 'change this', 'blast radius', 'break if')):
        return 'impact'
    if any(term in text for term in ('start', 'begin', 'entry point', 'reading order')):
        return 'starting-point'
    if any(term in text for term in ('main flow', 'execution flow', 'how does', 'what happens')):
        return 'main-flow'
    if any(term in text for term in ('what is this repo', 'what is this repository', 'about this repo', 'repository overview')):
        return 'repository-overview'
    return 'lexical'


def _relative_repo_path(path, repo_root):
    if not path:
        return ""
    target = str(path).replace('\\', '/')
    root = str(Path(repo_root).resolve()).replace('\\', '/')
    if target.startswith(root + '/'):
        return target[len(root) + 1:]
    if target.startswith(root):
        return target[len(root):].lstrip('/')
    if target.startswith('./'):
        return target[2:]
    return target.lstrip('/')


def _read_text(path):
    try:
        return path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return ''


def _module_for_file(report, file_path):
    for module in report.get('modules', []) or []:
        files = module.get('files', []) or []
        if file_path in files:
            return module.get('module') or 'root'
    return 'root'


def _file_metric_for(report, file_path):
    for metric in report.get('file_metrics', []) or []:
        if metric.get('file') == file_path:
            return metric
    return {}


def _entry_files(report):
    return {item.get('file') for item in report.get('entry_points', []) or [] if item.get('file')}


def _hotspot_files(report):
    return {item.get('file') for item in (report.get('hotspots', {}) or {}).get('files', []) or [] if item.get('file')}


def _flow_files(report):
    files = set()
    for flow in report.get('flows', []) or []:
        nodes = []
        def collect(node):
            if not node:
                return
            nodes.append(node)
            for child in node.get('children', []) or []:
                collect(child)
        collect(flow.get('tree'))
        for node in nodes:
            value = node.get('file') or node.get('source_file')
            if value:
                files.add(value)
            qualified = node.get('qualified_name') or node.get('node')
            if qualified and '::' in qualified:
                files.add(qualified.split('::', 1)[0])
    return files


def _reading_files(report):
    return {item.get('file') for item in report.get('reading_order', []) or [] if item.get('file')}


def _module_files(report):
    files = set()
    for module in report.get('major_modules', []) or report.get('modules', []) or []:
        files.update(module.get('files', []) or [])
    return files


def _guess_language(path):
    suffix = Path(path).suffix.lower()
    mapping = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.c': 'c',
        '.h': 'c',
        '.hpp': 'cpp',
        '.cc': 'cpp',
        '.cpp': 'cpp',
        '.md': 'markdown',
        '.json': 'json',
        '.toml': 'toml',
        '.yml': 'yaml',
        '.yaml': 'yaml',
        '.txt': 'text',
    }
    return mapping.get(suffix, 'text')


def _chunk_symbol_lines(text):
    lines = text.splitlines()
    results = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        match = re.match(r'^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', stripped)
        if match:
            results.append({'name': match.group(1), 'type': 'function', 'start_line': index, 'end_line': min(index + 35, len(lines))})
        else:
            match = re.match(r'^class\s+([A-Za-z_][A-Za-z0-9_]*)', stripped)
            if match:
                results.append({'name': match.group(1), 'type': 'class', 'start_line': index, 'end_line': min(index + 60, len(lines))})
    return results


def _window_text(text, start, end):
    lines = text.splitlines()
    start_index = max(1, start) - 1
    end_index = min(len(lines), end)
    window = lines[start_index:end_index]
    return '\n'.join(window)


def _build_file_chunks(file_path, repo_root, report):
    rel_path = _relative_repo_path(file_path, repo_root)
    text = _read_text(file_path)
    if not text:
        return []
    lines = text.splitlines()
    chunks = []
    metric = _file_metric_for(report, rel_path)
    module_name = _module_for_file(report, rel_path)
    hotspot_score = float(metric.get('hotspot_score', 0) or 0)
    entry_point = rel_path in _entry_files(report)

    symbol_entries = _chunk_symbol_lines(text)
    if symbol_entries:
        for item in symbol_entries:
            chunk = {
                'id': f'{rel_path}::{item["name"]}',
                'text': _window_text(text, item['start_line'], item['end_line']),
                'file': rel_path,
                'start_line': item['start_line'],
                'end_line': item['end_line'],
                'language': _guess_language(rel_path),
                'symbol': item['name'],
                'type': item['type'],
                'module': module_name,
                'hotspot_score': hotspot_score,
                'is_entry_point': entry_point,
            }
            chunks.append(chunk)
    else:
        chunk_size = 80
        for start in range(1, len(lines) + 1, chunk_size):
            end = min(len(lines), start + chunk_size - 1)
            snippet = '\n'.join(lines[start - 1:end])
            if not snippet.strip():
                continue
            chunks.append({
                'id': f'{rel_path}:{start}-{end}',
                'text': snippet,
                'file': rel_path,
                'start_line': start,
                'end_line': end,
                'language': _guess_language(rel_path),
                'symbol': Path(rel_path).stem,
                'type': 'file',
                'module': module_name,
                'hotspot_score': hotspot_score,
                'is_entry_point': entry_point,
            })

    file_chunk = {
        'id': rel_path,
        'text': text[:12000],
        'file': rel_path,
        'start_line': 1,
        'end_line': len(lines),
        'language': _guess_language(rel_path),
        'symbol': Path(rel_path).stem,
        'type': 'file',
        'module': module_name,
        'hotspot_score': hotspot_score,
        'is_entry_point': entry_point,
    }
    if not chunks or rel_path.endswith('README.md') or file_chunk['language'] == 'markdown':
        chunks.insert(0, file_chunk)
    else:
        chunks.append(file_chunk)
    return chunks


def build_rag_index(report, repo_root):
    repo_root = Path(repo_root)
    included = []
    for file_path in scan_repo(repo_root):
        rel_path = _relative_repo_path(file_path, repo_root)
        if not rel_path or rel_path.startswith('.git/'):
            continue
        included.append(file_path)

    chunks = []
    for file_path in included:
        rel_path = _relative_repo_path(file_path, repo_root)
        if not rel_path:
            continue
        if rel_path.startswith('node_modules/') or rel_path.startswith('.venv/') or rel_path.endswith('.pyc'):
            continue
        chunks.extend(_build_file_chunks(file_path, repo_root, report))

    readme_candidates = sorted(repo_root.glob('README*'))
    for readme in readme_candidates:
        rel = _relative_repo_path(readme, repo_root)
        if any(chunk.get('file') == rel for chunk in chunks):
            continue
        readme_lines = _read_text(readme).splitlines()
        readme_chunk = {
            'id': f'{rel}:readme',
            'text': _read_text(readme)[:12000],
            'file': rel,
            'start_line': 1,
            'end_line': len(readme_lines),
            'language': 'markdown',
            'symbol': 'README',
            'type': 'documentation',
            'module': 'root',
            'hotspot_score': 0.0,
            'is_entry_point': False,
        }
        chunks.insert(0, readme_chunk)

    # keep repo-relative path canonical and avoid exposing machine paths
    for chunk in chunks:
        chunk['file'] = _relative_repo_path(chunk['file'], repo_root)

    return {
        'repo': repo_root.name,
        'version': RAG_INDEX_VERSION,
        'chunks': chunks,
        'count': len(chunks),
    }


def _keyword_terms(query):
    terms = []
    for term in re.findall(r'[A-Za-z0-9_./-]+', query.lower()):
        if len(term) > 2:
            terms.append(term)
    return terms


def retrieve_chunks(query, chunks, report=None, limit=DEFAULT_CHUNK_LIMIT, metadata=None):
    query_terms = _keyword_terms(query)
    intent = classify_question(query, metadata)

    entry_files = _entry_files(report or {})
    hotspot_files = _hotspot_files(report or {})
    flow_files = _flow_files(report or {})
    reading_files = _reading_files(report or {})
    module_files = _module_files(report or {})
    scored = []

    for chunk in chunks:
        file_name = str(chunk.get('file', '')).lower()
        symbol_name = str(chunk.get('symbol', '')).lower()
        text = str(chunk.get('text', '')).lower()
        score = 0
        normalized_file = str(chunk.get('file', ''))
        is_documentation = chunk.get('type') == 'documentation' or file_name.startswith(('readme', 'docs/')) or '/docs/' in file_name
        is_app_entry = Path(file_name).name in {'main.py', 'app.py', 'server.py', 'index.js', 'index.ts', 'index.tsx', 'package.json'}

        if intent == 'repository-overview':
            if file_name.startswith('readme'):
                score += 110
            elif file_name.startswith('docs/') or '/docs/' in file_name:
                score += 90
            if is_documentation:
                score += 70
            if chunk.get('type') == 'documentation':
                score += 25
            if is_app_entry:
                score += 24
            if normalized_file in entry_files:
                score += 22
            if normalized_file in module_files:
                score += 6
            score += min(float(chunk.get('hotspot_score', 0) or 0) * 10, 8)
        elif intent == 'starting-point':
            if normalized_file in entry_files:
                score += 70
            if normalized_file in reading_files:
                score += 48
            if normalized_file in module_files:
                score += 8
            if is_app_entry:
                score += 20
        elif intent == 'main-flow':
            if normalized_file in flow_files:
                score += 70
            if normalized_file in entry_files:
                score += 55
            if normalized_file in reading_files:
                score += 20
            if is_app_entry:
                score += 18
        elif intent in {'file-explanation', 'function-explanation'}:
            focus_file = str((metadata or {}).get('file', '')).lower()
            focus_symbol = str((metadata or {}).get('qualified_name') or (metadata or {}).get('symbol', '')).lower()
            if focus_file and focus_file == file_name:
                score += 90
            if focus_symbol and focus_symbol in symbol_name:
                score += 70
        elif intent == 'dependency':
            if normalized_file in entry_files or normalized_file in hotspot_files:
                score += 18
        elif intent == 'impact':
            if normalized_file in hotspot_files:
                score += 35
            if normalized_file in module_files:
                score += 20

        for term in query_terms:
            if term in file_name:
                score += 16
            if term in symbol_name:
                score += 18
            if term in text:
                score += 2

        if file_name in {item.lower() for item in entry_files}:
            score += 8
        if file_name in {item.lower() for item in hotspot_files}:
            score += 6
        if chunk.get('type') in {'file', 'documentation'}:
            score += 2
        if chunk.get('symbol') and chunk.get('symbol').lower() in query.lower():
            score += 10

        scored.append((score, chunk))

    best = sorted(scored, key=lambda item: (-item[0], item[1].get('file', ''), item[1].get('start_line', 0)))
    result = []
    seen_files = set()
    diversify = intent in {'repository-overview', 'starting-point', 'main-flow'}
    for _, chunk in best:
        file_name = chunk.get('file', '')
        if diversify and file_name in seen_files:
            continue
        result.append(chunk)
        seen_files.add(file_name)
        if len(result) >= limit:
            break
    return result


def build_context_packet(question, report, chunks, limit=DEFAULT_CHUNK_LIMIT, metadata=None, include_retrieval=True):
    intent = classify_question(question, metadata)
    relevant = retrieve_chunks(question, chunks, report, limit=limit, metadata=metadata) if include_retrieval else []
    overview = report.get('overview', {}) or {}
    ui_summary = report.get('ui_summary', {}) or {}
    graph_edges = report.get('function_edges', []) or []
    import_edges = report.get('import_edges', []) or []
    focus_file = str((metadata or {}).get('file', ''))
    related_function_edges = [
        edge for edge in graph_edges
        if focus_file and (str(edge.get('from', '')).split('::')[0] == focus_file or str(edge.get('to', '')).split('::')[0] == focus_file)
    ]
    related_import_edges = [
        edge for edge in import_edges
        if focus_file and (edge.get('from') == focus_file or edge.get('to') == focus_file)
    ]
    deterministic_context = {
        'intent': intent,
        'overview': {
            'repository': overview.get('repository'),
            'languages': overview.get('languages', []),
            'file_count': overview.get('file_count', 0),
            'function_count': overview.get('function_count', 0),
            'module_count': overview.get('module_count', 0),
        },
        'entry_points': (report.get('entry_points', []) or [])[:5],
        'hotspots': ((report.get('hotspots', {}) or {}).get('files', []) or [])[:5],
        'major_modules': (report.get('major_modules', []) or [])[:5],
        'reading_order': (report.get('reading_order', []) or [])[:5],
        'flows': (report.get('flows') or ui_summary.get('flows') or [])[:5],
        'how_it_works': (report.get('how_it_works') or ui_summary.get('how_it_works') or [])[:5],
        'important_functions': report.get('important_functions', {}),
        'graph_summary': {
            'function_edge_count': len(graph_edges),
            'import_edge_count': len(import_edges),
            'function_edges': graph_edges[:20],
            'import_edges': import_edges[:20],
            'focus_function_edges': related_function_edges[:30],
            'focus_import_edges': related_import_edges[:30],
        },
    }
    return {
        'question': question,
        'intent': intent,
        'focus': metadata or {},
        'repository': {
            'name': overview.get('repository') or 'repository',
            'languages': overview.get('languages', []),
            'files': overview.get('file_count', 0),
            'functions': overview.get('function_count', 0),
            'modules': overview.get('module_count', 0),
        },
        'deterministic_context': deterministic_context,
        'retrieved_chunks': relevant,
        'source_citations': _report_source_citations(report),
    }


def _citation(file_path, start=1, end=None):
    if not file_path:
        return None
    end = end or start
    return f'{str(file_path).replace("\\", "/")}:{start}-{end}'


def _file_metric(report, file_path):
    return next((item for item in report.get('file_metrics', []) or [] if item.get('file') == file_path), {})


def _file_for_focus(report, metadata, question):
    metadata = metadata or {}
    if metadata.get('file'):
        return metadata['file']
    candidates = [item.get('file') for item in report.get('file_metrics', []) or [] if item.get('file')]
    lowered = str(question).lower()
    matches = [path for path in candidates if str(path).lower() in lowered]
    return max(matches, key=len) if matches else None


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _function_lookup(report):
    return {item.get('qualified_name'): item for item in report.get('function_metrics', []) or [] if item.get('qualified_name')}


def _structured_sources(citations):
    return [{'reference': value} for value in _unique(citations) if value]


def _report_source_citations(report):
    citations = []
    for item in (report.get('entry_points', []) or [])[:5]:
        citations.append(_citation(item.get('file'), item.get('line', 1), item.get('line', 1)))
    for item in (report.get('reading_order', []) or [])[:5]:
        metric = _file_metric(report, item.get('file'))
        citations.append(_citation(item.get('file'), 1, metric.get('loc', 1)))
    for item in (((report.get('hotspots', {}) or {}).get('files', []) or [])[:5]):
        metric = _file_metric(report, item.get('file'))
        citations.append(_citation(item.get('file'), 1, metric.get('loc', 1)))
    return _unique(citations)


def _deterministic_response(question, report, metadata=None):
    intent = classify_question(question, metadata)
    if intent not in {'dependency', 'impact', 'starting-point', 'entry-points', 'hotspots', 'modules', 'file-structure', 'file-explanation', 'function-explanation'}:
        return None

    citations = []
    file_path = _file_for_focus(report, metadata, question)
    if file_path:
        metric = _file_metric(report, file_path)
        citations.append(_citation(file_path, 1, metric.get('loc', 1)))

    if intent in {'starting-point', 'entry-points'}:
        entries = (report.get('entry_points', []) or [])[:5]
        reading = (report.get('reading_order', []) or [])[:5]
        lines = [f"{item.get('file')}::{item.get('name') or item.get('qualified_name', '').split('::')[-1]}" for item in entries]
        answer = (('Start with these deterministic entry points: ' if intent == 'starting-point' else 'The analyzer identified these entry points: ') + ', '.join(lines) + '.') if lines else 'The analyzer did not identify a likely entry point.'
        if reading and intent == 'starting-point':
            answer += ' Recommended reading order is provided below.'
        citations.extend(_citation(item.get('file'), item.get('line', 1), item.get('line', 1)) for item in entries)
        sections = [
            {'title': 'Entry points', 'items': [
                {'label': item.get('name') or item.get('qualified_name', '').split('::')[-1], 'path': item.get('file'), 'line': item.get('line', 1), 'type': 'entry'}
                for item in entries
            ]},
        ]
        if reading and intent == 'starting-point':
            sections.append({'title': 'Recommended reading order', 'items': [
                {'label': item.get('file'), 'path': item.get('file'), 'reason': (item.get('evidence') or ['ranked starting file'])[0]}
                for item in reading
            ]})
    elif intent == 'hotspots':
        items = ((report.get('hotspots', {}) or {}).get('files', []) or [])[:8]
        answer = 'The highest-ranked hotspot files are: ' + '; '.join(f"{item.get('file')} (score {item.get('hotspot_score', 0)})" for item in items) if items else 'The analyzer did not report hotspot files.'
        citations.extend(_citation(item.get('file'), 1, _file_metric(report, item.get('file')).get('loc', 1)) for item in items)
        sections = [{'title': 'Hotspot files', 'items': [{'label': item.get('file'), 'path': item.get('file'), 'meta': f"score {item.get('hotspot_score', 0)}"} for item in items]}]
    elif intent == 'modules':
        items = (report.get('major_modules', []) or report.get('modules', []) or [])[:8]
        answer = 'The important modules are: ' + '; '.join(f"{item.get('module', 'root')} ({item.get('file_count', len(item.get('files', []) or []))} files)" for item in items) if items else 'The analyzer did not report major modules.'
        citations.extend(_citation(item.get('files', [None])[0]) for item in items if item.get('files'))
        sections = [{'title': 'Important modules', 'items': [{'label': item.get('module') or 'root', 'path': (item.get('files') or [None])[0], 'meta': f"{len(item.get('files', []) or [])} files"} for item in items]}]
    elif intent == 'file-structure' and file_path:
        metric = _file_metric(report, file_path)
        definitions = metric.get('defined_functions', []) or []
        answer = f"{file_path} contains {len(definitions)} analyzed definitions across {metric.get('loc', 0)} lines: " + ', '.join(definitions[:12]) if definitions else f"{file_path} has {metric.get('loc', 0)} analyzed lines and no extracted function definitions."
        sections = [{'title': 'Definitions', 'items': [{'label': value.split('::')[-1], 'path': file_path} for value in definitions[:12]]}]
    elif intent in {'file-explanation', 'function-explanation'} and file_path:
        metric = _file_metric(report, file_path)
        functions = [item for item in report.get('function_metrics', []) or [] if item.get('file') == file_path]
        imports = [edge.get('to') for edge in report.get('import_edges', []) or [] if edge.get('from') == file_path]
        imported_by = [edge.get('from') for edge in report.get('import_edges', []) or [] if edge.get('to') == file_path]
        calls = [edge.get('to') for edge in report.get('function_edges', []) or [] if str(edge.get('from', '')).split('::')[0] == file_path]
        callers = [edge.get('from') for edge in report.get('function_edges', []) or [] if str(edge.get('to', '')).split('::')[0] == file_path]
        module = _module_for_file(report, file_path)
        answer = (
            f"{file_path} is a {metric.get('loc', 0)}-line {module} module with {len(functions)} defined functions. "
            f"It imports {_unique(imports)[:5] or ['no resolved local files']}, is imported by {_unique(imported_by)[:5] or ['no resolved local files']}, "
            f"and calls {_unique(calls)[:5] or ['no resolved functions']}. "
            f"Callers include {_unique(callers)[:5] or ['no resolved callers']} and its hotspot score is {metric.get('hotspot_score', 0)}."
        )
        for item in functions[:8]:
            citations.append(_citation(file_path, item.get('line', 1), item.get('end_line', item.get('line', 1))))
        sections = [
            {'title': 'File', 'items': [{'label': file_path, 'path': file_path, 'meta': f"{metric.get('loc', 0)} LOC"}]},
            {'title': 'Contains', 'items': [{'label': item.get('name'), 'path': file_path, 'line': item.get('line', 1), 'end_line': item.get('end_line', item.get('line', 1))} for item in functions[:8]]},
            {'title': 'Depends on', 'items': [{'label': value, 'path': value} for value in _unique(imports)[:8]]},
            {'title': 'Depended on by', 'items': [{'label': value, 'path': value} for value in _unique(imported_by)[:8]]},
            {'title': 'Why it matters', 'items': [{'label': f"Hotspot score {metric.get('hotspot_score', 0)}", 'meta': 'deterministic metric'}]},
        ]
    elif intent in {'dependency', 'impact'} and file_path:
        imported_by = [edge.get('from') for edge in report.get('import_edges', []) or [] if edge.get('to') == file_path]
        imports = [edge.get('to') for edge in report.get('import_edges', []) or [] if edge.get('from') == file_path]
        calls = [edge.get('from') for edge in report.get('function_edges', []) or [] if str(edge.get('to', '')).split('::')[0] == file_path]
        callees = [edge.get('to') for edge in report.get('function_edges', []) or [] if str(edge.get('from', '')).split('::')[0] == file_path]
        answer = (
            f"The deterministic graph reports {file_path} with incoming or outgoing file relationships: "
            f"imports {_unique(imports)[:10] or ['none']}; imported-by {_unique(imported_by)[:10] or ['none']}; callers {_unique(calls)[:10] or ['none']}; "
            f"callees {_unique(callees)[:10] or ['none']}."
        )
        sections = [
            {'title': 'Selected', 'items': [{'label': file_path, 'path': file_path}]},
            {'title': 'Direct dependents', 'items': [{'label': value, 'path': value} for value in _unique(imported_by)[:10]] or [{'label': 'No direct dependents found.'}]},
            {'title': 'Depends on', 'items': [{'label': value, 'path': value} for value in _unique(imports)[:10]] or [{'label': 'No direct dependencies found.'}]},
            {'title': 'Called / referenced by', 'items': [{'label': value} for value in _unique(calls)[:10]] or [{'label': 'No callers found.'}]},
            {'title': 'Callees', 'items': [{'label': value} for value in _unique(callees)[:10]] or [{'label': 'No callees found.'}]},
        ]
    else:
        return None

    return {
        'answer': answer,
        'sources': _unique(citations),
        'sections': sections,
        'structured_sources': _structured_sources(citations),
        'grounded': True,
        'mode': 'deterministic-analysis',
        'retrieval': {'count': 0, 'sources': []},
        'intent': intent,
    }


def _format_sources(chunks):
    sources = []
    seen = set()
    for chunk in chunks:
        label = f"{chunk.get('file', '')}:{chunk.get('start_line', 1)}-{chunk.get('end_line', chunk.get('start_line', 1))}"
        if label not in seen:
            seen.add(label)
            sources.append(label)
    return sources


def _retrieval_details(chunks):
    return {
        'count': len(chunks),
        'sources': _format_sources(chunks),
    }


def _safe_sources(sources, fallback):
    valid = []
    for source in sources or []:
        value = str(source).strip()
        if re.match(r'^(?:[A-Za-z]:[\\/]|/|https?://)', value) or '..' in value:
            continue
        if re.match(r'^[^:]+:\d+(?:-\d+)?$', value):
            valid.append(value.replace('\\', '/'))
    return list(dict.fromkeys(valid)) or fallback


def _gemini_error_status(error):
    status = getattr(error, 'status_code', None) or getattr(error, 'code', None)
    text = str(error).lower()
    if status in {401, 403} or any(term in text for term in ('unauthorized', 'permission', 'api key', 'authentication')):
        return 'gemini-authentication-error'
    if status == 429 or any(term in text for term in ('quota', 'rate limit', 'resource exhausted')):
        return 'gemini-quota-error'
    if any(term in text for term in ('json', 'decode', 'schema', 'response was')):
        return 'gemini-malformed-response'
    return 'gemini-api-error'


def _summary_fallback(question, report):
    intent = classify_question(question)
    entries = (report.get('entry_points', []) or [])[:5]
    flows = (report.get('flows', []) or [])[:3]
    citations = _report_source_citations(report)
    if intent == 'main-flow' and flows:
        names = []
        for flow in flows:
            root = flow.get('entry_point') or ''
            if root:
                names.append(root)
        answer = 'The deterministic execution flows begin at ' + '; '.join(names) + '. The flow data is available from the analyzer; Gemini synthesis was unavailable for this request.'
    else:
        overview = report.get('overview', {}) or {}
        answer = (
            f"The deterministic analysis describes {overview.get('repository') or 'this repository'} with "
            f"{overview.get('file_count', 0)} files, {overview.get('function_count', 0)} functions, and "
            f"{overview.get('module_count', 0)} modules. Gemini synthesis was unavailable for this request."
        )
    citations.extend(_citation(item.get('file'), item.get('line', 1), item.get('line', 1)) for item in entries)
    return {
        'answer': answer,
        'sources': _unique(citations),
        'grounded': True,
        'mode': 'deterministic-rag-fallback',
        'retrieval': {'count': 0, 'sources': []},
    }


def _fallback_answer(question, report, chunks, metadata=None, allow_retrieval=True):
    relevant = retrieve_chunks(question, chunks, report, limit=5, metadata=metadata) if allow_retrieval else []
    if not allow_retrieval:
        return _summary_fallback(question, report)
    if not relevant:
        overview = report.get('overview', {}) or {}
        repo_name = overview.get('repository') or 'this repository'
        answer = (
            f"The deterministic analysis shows {repo_name} has {overview.get('file_count', 0)} files and "
            f"{overview.get('function_count', 0)} functions. The available evidence is insufficient to answer the specific question beyond the static repo summary."
        )
        return {
            'answer': answer,
            'sources': [],
            'grounded': True,
            'mode': 'deterministic-rag-fallback',
            'retrieval': _retrieval_details(relevant),
        }

    first = relevant[0]
    file_ref = first.get('file', '')
    symbol = first.get('symbol') or file_ref
    answer = (
        f"The deterministic analysis points to {file_ref} as the strongest evidence for this question. "
        f"The relevant code is centered on {symbol}, and the surrounding static relationships support this as the main implementation path. "
        f"This answer is grounded in repo metrics and source evidence rather than inferred architecture alone."
    )

    if 'where' in question.lower() and 'start' in question.lower():
        entry_points = report.get('entry_points', []) or []
        if entry_points:
            main_entry = entry_points[0]
            file_value = main_entry.get('file') or file_ref
            name_value = main_entry.get('name') or main_entry.get('qualified_name', '').split('::')[-1]
            answer = (
                f"The deterministic analyzer identifies {file_value}::{name_value} as the likely entry point. "
                f"This is the strongest starting point because it is ranked as an entry point and is supported by the repository-level graph."
            )

    if 'what calls' in question.lower() or 'calls' in question.lower():
        symbol_name = question.split()[-1]
        if symbol_name:
            answer = (
                f"The static graph is the authoritative source for callers and callees. For {symbol_name}, the deterministic relationship data should be used first, then the retrieved source chunks provide the implementation context."
            )

    return {
        'answer': answer,
        'sources': _format_sources(relevant),
        'grounded': True,
        'mode': 'deterministic-rag-fallback',
        'retrieval': _retrieval_details(relevant),
    }


def _maybe_call_google(question, report, chunks, metadata=None, include_retrieval=True):
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        return {'_gemini_status': 'gemini-key-missing'}
    try:
        from google import genai
        from google.genai import types
    except Exception:
        return {'_gemini_status': 'gemini-sdk-unavailable'}

    packet = build_context_packet(question, report, chunks, metadata=metadata, include_retrieval=include_retrieval)
    prompt = json.dumps(packet, indent=2)
    client = genai.Client(api_key=api_key)
    contents = (
        'You are Repo Autopsy. Use the deterministic analysis as the authority. Explain only using the provided context. '
        'Do not invent functions or dependencies. If evidence is insufficient, say so. '
        'Return a JSON object with keys answer and sources.\n\n' + prompt
    )
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=os.getenv('GEMINI_MODEL', DEFAULT_GEMINI_MODEL),
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type='application/json',
                ),
            )
            text = getattr(response, 'text', None) or ''
            if not text:
                raise ValueError('empty response')
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError('response was not a JSON object')
            answer_text = payload.get('answer') or payload.get('summary')
            if not answer_text:
                raise ValueError('response did not contain an answer')
            fallback_sources = _format_sources(packet.get('retrieved_chunks', [])) or packet.get('source_citations', [])
            sources = _safe_sources(payload.get('sources'), fallback_sources)
            return {
                'answer': answer_text,
                'sources': sources,
                'grounded': bool(sources or packet.get('retrieved_chunks') or packet.get('source_citations')),
                'mode': 'gemini-rag',
                'retrieval': _retrieval_details(packet.get('retrieved_chunks', [])),
            }
        except Exception as error:
            status_code = getattr(error, 'code', None) or getattr(error, 'status_code', None)
            if attempt == 0 and status_code in {429, 500, 503, 504}:
                time.sleep(1)
                continue
            status = _gemini_error_status(error)
            LOGGER.warning('%s; using deterministic RAG fallback', status)
            return {'_gemini_status': status}


def generate_answer(question, report, chunks, metadata=None):
    if not question or not str(question).strip():
        return {'answer': 'Please provide a question about this repository.', 'sources': [], 'grounded': False, 'mode': 'empty'}

    metadata = metadata or {}
    deterministic = _deterministic_response(question, report, metadata)
    if deterministic:
        return deterministic

    intent = classify_question(question, metadata)
    retrieval_hint = ' '.join(str(metadata.get(key, '')) for key in ('file', 'qualified_name', 'symbol')).strip()
    grounded_question = f'{question} {retrieval_hint}'.strip()

    direct = _maybe_call_google(
        grounded_question,
        report,
        chunks,
        metadata=metadata,
        include_retrieval=intent not in {'repository-overview', 'main-flow'},
    )
    if direct and 'answer' in direct:
        return direct

    fallback = _fallback_answer(
        grounded_question,
        report,
        chunks,
        metadata=metadata,
        allow_retrieval=intent not in {'repository-overview', 'main-flow'},
    )
    if direct and direct.get('_gemini_status'):
        fallback['gemini_status'] = direct['_gemini_status']
    return fallback
