from collections import defaultdict
from pathlib import Path


MAX_FLOW_BRANCHES = 5
MAX_REPORT_ITEMS = 8
READING_ORDER_WEIGHTS = {
    "entry_point": 0.35,
    "flow_relevance": 0.25,
    "module_centrality": 0.2,
    "hotspot": 0.15,
    "import_relevance": 0.05,
}


def _strip_root_text(value, root):
    if not isinstance(value, str) or not value:
        return value
    text = value.replace('\\', '/')
    root_s = str(Path(root).resolve()).replace('\\', '/')
    if root_s in text:
        text = text.replace(root_s + '/', '').replace(root_s, '').lstrip('/')
    return text


def _relative(path, root):
    if not path:
        return path
    candidate = _strip_root_text(str(path), root)
    if candidate.startswith(('http://', 'https://')):
        return candidate
    posix = Path(candidate)
    if not posix.is_absolute():
        return candidate.lstrip('./')
    try:
        return posix.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return candidate.lstrip('/')


def _normalise_symbol_name(value, root):
    if not value:
        return value
    if '::' not in value:
        return _relative(value, root)
    file_part, _, symbol = value.rpartition('::')
    return f"{_relative(file_part, root)}::{symbol}"


import re

ROLE_TOKEN_TABLE = (
    (("test", "tests", "__tests__", "spec", "fixture", "fixtures"), "tests and fixtures"),
    (("ingest", "ingester", "fetch", "clone", "scan", "scanner"), "ingestion"),
    (("parse", "parser", "extract", "extractor"), "parsing"),
    (("layout", "place", "simulate"), "layout"),
    (("annot", "annotate", "annotation", "label", "highlight"), "annotation"),
    (("render", "draw", "canvas", "scene", "iso", "visual", "skyline", "map"), "visualization / rendering"),
    (("api", "handler", "handlers", "route", "routes", "controller", "controllers", "endpoint", "request"), "request handling"),
    (("component", "components", "view", "views", "ui", "frontend", "page", "pages"), "frontend / UI"),
    (("script", "scripts", "tool", "tools", "cli"), "tooling scripts"),
    (("type", "types", "model", "models", "schema"), "types / models"),
    (("server", "backend", "service", "services"), "backend / services"),
    (("lib", "core", "common", "shared", "util", "utils"), "shared library"),
)

FUNCTION_ROLE_TABLE = (
    (("test", "spec", "fixture"), "test helper"),
    (("ingest", "fetch", "clone", "load", "read"), "ingestion stage"),
    (("parse", "extract", "scan"), "parsing / extraction stage"),
    (("layout", "prioritize", "simulate"), "layout construction stage"),
    (("annot", "annotate", "label", "highlight"), "annotation stage"),
    (("render", "draw", "paint", "export", "download"), "output / rendering stage"),
    (("request", "handler", "serve"), "request handler"),
    (("main", "start", "boot", "init", "run"), "startup / orchestration"),
    (("cache"), "caching stage"),
)


def _name_tokens(*values):
    tokens = set()
    for value in values:
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or "").replace("\\", "/"))
        text = re.sub(r"[^A-Za-z0-9]+", " ", text)
        tokens.update(part.lower() for part in text.split() if len(part) > 1)
    return tokens


def _roles_from_tokens(tokens, table=ROLE_TOKEN_TABLE):
    roles = []
    for keys, label in table:
        if tokens & set(keys) and label not in roles:
            roles.append(label)
    return roles


def _module_hint(module, files=()):
    tokens = _name_tokens(module, *[Path(file_name).stem for file_name in files])
    roles = [role for role in _roles_from_tokens(tokens) if role != "tests and fixtures" or _is_test_module(module, files)]
    if not roles:
        return None
    return " / ".join(roles[:3])


def _is_test_module(module, files=()):
    tokens = _name_tokens(module, *files)
    return bool(tokens & {"test", "tests", "__tests__", "spec", "fixture", "fixtures"})


def _function_role(qualified_name, file_name=""):
    name = str(qualified_name or "").split("::")[-1]
    roles = _roles_from_tokens(_name_tokens(name, file_name), FUNCTION_ROLE_TABLE)
    if roles:
        return roles[0]
    return "downstream call in the entry-point chain"


def _function_name(metric):
    return metric["qualified_name"].split("::")[-1]


def _function_hint(name):
    lowered = name.lower()
    if lowered.startswith("onrequest"):
        return "request handler"
    if lowered in {"main", "start", "run", "serve"}:
        return "startup or orchestration function"
    return None


def _entry_strength(entry):
    name = entry["name"].split(".")[-1].lower()
    file_name = entry["file"].replace("\\", "/").lower()
    if name.startswith("onrequest"):
        return 1.0
    if name == "main":
        return 0.9
    if "/api/" in file_name:
        return 0.8
    if name in {"handler", "handle", "serve", "start", "run"}:
        return 0.4
    return 0.5


def _explanation(text, basis, confidence):
    return {"text": text, "basis": basis, "confidence": confidence}


def _module_description(module, files, functions, purpose_hint):
    names = sorted(Path(file_name).name for file_name in files)
    stems = []
    for name in names:
        stem = Path(name).stem.lower()
        if stem not in stems and any(token in stem for token in ("parse", "ingest", "layout", "annot", "iso", "component", "api", "type")):
            stems.append(stem)
    if stems:
        subject = ", ".join(stems[:4])
        text = f"Contains files associated with {subject} logic."
    elif purpose_hint:
        text = f"Contains files in the {purpose_hint.lower()} directory group."
    else:
        text = f"Contains {len(names)} files grouped under {module}."
    if functions:
        text += f" The files define {len(functions)} functions or methods."
    return text


def _enrich_modules(analysis, root):
    file_metrics = {metric["file"]: metric for metric in analysis["file_metrics"]}
    function_metrics = analysis["function_metrics"]
    functions_by_file = defaultdict(list)
    for metric in function_metrics:
        functions_by_file[metric["file"]].append(metric)

    module_by_file = {
        file_name: raw["module"]
        for raw in analysis["modules"]
        for file_name in raw["files"]
    }
    dependency_map = defaultdict(dict)
    for edge in analysis["architecture_edges"]:
        source_module = module_by_file.get(edge["from"])
        target_module = module_by_file.get(edge["to"])
        if not source_module or source_module == target_module:
            continue
        current = dependency_map[source_module].setdefault(target_module, {"import_count": 0, "call_count": 0})
        current["import_count"] += edge["import_count"]
        current["call_count"] += edge["call_count"]

    modules = []
    for raw in analysis["modules"]:
        metrics = [file_metrics[file_name] for file_name in raw["files"] if file_name in file_metrics]
        functions = [metric for file_name in raw["files"] for metric in functions_by_file[file_name]]
        hotspot = max((metric["hotspot_score"] for metric in metrics), default=0)
        evidence = [
            f"{len(raw['files'])} files",
            f"{sum(metric['loc'] for metric in metrics)} LOC",
            f"{sum(metric['number_of_defined_functions'] for metric in metrics)} definitions",
            f"{raw['incoming_dependencies']} incoming module dependencies",
            f"{raw['outgoing_dependencies']} outgoing module dependencies",
            f"{raw['internal_edges']} internal architecture edges",
        ]
        if functions:
            top_function = max(functions, key=lambda metric: (metric["hotspot_score"], metric["qualified_name"]))
            evidence.append(f"contains {top_function['name']} (hotspot {top_function['hotspot_score']})")
        item = dict(raw)
        key_functions = sorted(
            functions,
            key=lambda metric: (-metric["hotspot_score"], -metric["fan_out"], metric["qualified_name"]),
        )[:5]
        dependencies = [
            {
                "module": target,
                "import_count": values["import_count"],
                "call_count": values["call_count"],
                "types": [kind for kind, count in (("import", values["import_count"]), ("call", values["call_count"])) if count],
            }
            for target, values in sorted(dependency_map[raw["module"]].items())
        ]
        purpose_hint = _module_hint(raw["module"], raw["files"])
        description = _module_description(raw["module"], raw["files"], functions, purpose_hint)
        key_files = sorted(
            metrics,
            key=lambda metric: (-metric["hotspot_score"], -metric["loc"], metric["file"]),
        )[:4]
        item.update({
            "total_loc": sum(metric["loc"] for metric in metrics),
            "number_of_definitions": sum(metric["number_of_defined_functions"] for metric in metrics),
            "internal_calls": sum(metric.get("internal_edges", 0) for metric in metrics),
            "hotspot_score": hotspot,
            "is_test": bool(metrics) and all(metric["is_test"] for metric in metrics),
            "purpose_hint": purpose_hint,
            "role": purpose_hint,
            "description": description,
            "key_files": [
                {
                    "file": metric["file"],
                    "name": Path(metric["file"]).name,
                    "loc": metric["loc"],
                    "hotspot_score": metric["hotspot_score"],
                }
                for metric in key_files
            ],
            "key_functions": [
                {
                    "qualified_name": metric["qualified_name"],
                    "fan_in": metric["fan_in"],
                    "fan_out": metric["fan_out"],
                    "hotspot_score": metric["hotspot_score"],
                }
                for metric in key_functions
            ],
            "dependencies": dependencies,
            "evidence": evidence,
            "explanation": _explanation(
                description,
                evidence + [f"directory path {raw['module']}"],
                "fact",
            ),
        })
        modules.append(item)
    return modules


def _file_why(item):
    why = []
    loc = item.get("loc") or 0
    definitions = item.get("number_of_defined_functions") or 0
    incoming = (item.get("incoming_import_dependencies") or 0) + (item.get("incoming_call_dependencies") or 0)
    internal = item.get("internal_edges") or 0
    if loc >= 200:
        why.append("large implementation")
    elif loc >= 80:
        why.append("substantial implementation")
    if definitions >= 10:
        why.append(f"{definitions} definitions")
    if incoming >= 2:
        why.append("reused by other files")
    if internal >= 8:
        why.append("internally reused")
    if (item.get("hotspot_score") or 0) >= 0.5:
        why.append("high structural score")
    return why


def _hotspots(analysis):
    function_hotspots = sorted(
        [metric for metric in analysis["function_metrics"] if not metric["is_test"]],
        key=lambda item: (-item["hotspot_score"], item["qualified_name"]),
    )[:MAX_REPORT_ITEMS]
    file_hotspots = sorted(
        [metric for metric in analysis["file_metrics"] if not metric["is_test"]],
        key=lambda item: (-item["hotspot_score"], item["file"]),
    )[:MAX_REPORT_ITEMS]
    return {
        "functions": [
            {
                "qualified_name": item["qualified_name"],
                "file": item["file"],
                "line": item["line"],
                "hotspot_score": item["hotspot_score"],
                "loc": item["loc"],
                "fan_in": item["fan_in"],
                "fan_out": item["fan_out"],
                "evidence": [f"{item['loc']} LOC", f"fan-in {item['fan_in']}", f"fan-out {item['fan_out']}"],
                "why": _file_why({
                    "loc": item["loc"],
                    "incoming_call_dependencies": item["fan_in"],
                    "incoming_import_dependencies": 0,
                    "internal_edges": 0,
                    "number_of_defined_functions": 1,
                    "hotspot_score": item["hotspot_score"],
                }),
            }
            for item in function_hotspots
        ],
        "files": [
            {
                "file": item["file"],
                "hotspot_score": item["hotspot_score"],
                "loc": item["loc"],
                "number_of_defined_functions": item["number_of_defined_functions"],
                "incoming_import_dependencies": item.get("incoming_import_dependencies", 0),
                "outgoing_import_dependencies": item.get("outgoing_import_dependencies", 0),
                "incoming_call_dependencies": item.get("incoming_call_dependencies", 0),
                "outgoing_call_dependencies": item.get("outgoing_call_dependencies", 0),
                "internal_edges": item.get("internal_edges", 0),
                "evidence": [
                    f"{item['loc']} LOC",
                    f"{item['number_of_defined_functions']} definitions",
                    f"{item.get('incoming_import_dependencies', 0)} incoming imports",
                    f"{item.get('outgoing_import_dependencies', 0)} outgoing imports",
                ],
                "why": _file_why(item),
            }
            for item in file_hotspots
        ],
    }


def _function_report_item(metric, category, basis):
    return {
        "qualified_name": metric["qualified_name"],
        "file": metric["file"],
        "line": metric["line"],
        "loc": metric["loc"],
        "fan_in": metric["fan_in"],
        "fan_out": metric["fan_out"],
        "hotspot_score": metric["hotspot_score"],
        "category": category,
        "evidence": basis,
        "explanation": _explanation(
            f"{_function_name(metric)} is listed as {category}.",
            basis,
            "fact",
        ),
    }


def _important_functions(analysis):
    metrics = [metric for metric in analysis["function_metrics"] if not metric["is_test"]]
    likely_names = {entry["qualified_name"] for entry in analysis["likely_entry_points"]}
    fan_out_sorted = sorted(metrics, key=lambda metric: (-metric["fan_out"], metric["qualified_name"]))
    fan_in_sorted = sorted(metrics, key=lambda metric: (-metric["fan_in"], metric["qualified_name"]))
    loc_sorted = sorted(metrics, key=lambda metric: (-metric["loc"], metric["qualified_name"]))
    connectivity_sorted = sorted(
        [metric for metric in metrics if metric["fan_in"] and metric["fan_out"]],
        key=lambda metric: (-(metric["fan_in"] + metric["fan_out"]), metric["qualified_name"]),
    )

    orchestration = []
    for metric in fan_out_sorted:
        if metric["qualified_name"] in likely_names or len(orchestration) < 3:
            basis = [f"fan-out = {metric['fan_out']}", f"fan-in = {metric['fan_in']}"]
            if metric["qualified_name"] in likely_names:
                basis.append("classified as a likely entry point")
            orchestration.append(_function_report_item(metric, "entry / orchestration", basis))
        if len(orchestration) >= MAX_REPORT_ITEMS:
            break

    def top_items(items, category, basis_builder):
        return [_function_report_item(metric, category, basis_builder(metric)) for metric in items[:MAX_REPORT_ITEMS]]

    return {
        "entry_orchestration": orchestration,
        "highly_reused": top_items(
            [metric for metric in fan_in_sorted if metric["fan_in"]],
            "highly reused",
            lambda metric: [f"fan-in = {metric['fan_in']}", f"fan-out = {metric['fan_out']}"],
        ),
        "large_complex": top_items(
            loc_sorted,
            "large / complex by LOC",
            lambda metric: [f"LOC = {metric['loc']}", f"fan-out = {metric['fan_out']}"],
        ),
        "high_connectivity": top_items(
            connectivity_sorted,
            "high connectivity",
            lambda metric: [f"fan-in = {metric['fan_in']}", f"fan-out = {metric['fan_out']}"],
        ),
    }


def _reported_entry_points(analysis, root):
    entries = []
    for entry in analysis["likely_entry_points"]:
        item = dict(entry)
        item['file'] = _relative(entry.get('file'), root) if 'file' in entry else entry.get('file')
        item['qualified_name'] = _normalise_symbol_name(entry.get('qualified_name'), root)
        basis = [
            f"fan-in = {entry['fan_in']}",
            f"fan-out = {entry['fan_out']}",
        ]
        if entry["structural_hints"]:
            basis.extend(entry["structural_hints"])
        item["explanation"] = _explanation(
            f"{entry['name']} appears to be an application entry point.",
            basis,
            "heuristic",
        )
        entries.append(item)
    return entries


def _flow_tree(node, metrics_by_name, depth=0):
    metric = metrics_by_name.get(node["node"])
    children = sorted(
        node.get("children", []),
        key=lambda child: (
            -(metrics_by_name.get(child["node"], {}).get("fan_out", 0)),
            child["node"],
        ),
    )
    item = {
        "qualified_name": node["node"],
        "depth": depth,
        "evidence": [],
        "children": [],
    }
    if metric:
        item["evidence"] = [
            f"fan-in {metric['fan_in']}",
            f"fan-out {metric['fan_out']}",
            f"hotspot {metric['hotspot_score']}",
        ]
    for child in children[:MAX_FLOW_BRANCHES]:
        item["children"].append(_flow_tree(child, metrics_by_name, depth + 1))
    if len(children) > MAX_FLOW_BRANCHES:
        item["omitted_children"] = len(children) - MAX_FLOW_BRANCHES
    return item


def _flows(analysis):
    metrics_by_name = {metric["qualified_name"]: metric for metric in analysis["function_metrics"]}
    return [
        {
            "entry_point": chain["node"],
            "evidence": next(
                (
                    {
                        "fan_out": entry["fan_out"],
                        "hotspot_score": entry["hotspot_score"],
                        "structural_hints": entry["structural_hints"],
                    }
                    for entry in analysis["likely_entry_points"]
                    if entry["qualified_name"] == chain["node"]
                ),
                {},
            ),
            "tree": _flow_tree(chain, metrics_by_name),
        }
        for chain in analysis["dependency_chains"][:MAX_REPORT_ITEMS]
    ]


def _flow_spine(tree, limit=6):
    steps = []
    node = tree
    seen = set()
    while node and len(steps) < limit:
        qualified = node.get("qualified_name") or node.get("node")
        if not qualified or qualified in seen:
            break
        seen.add(qualified)
        steps.append(node)
        children = node.get("children") or []
        node = children[0] if children else None
    return steps


def _step_description(qualified_name, metric, entry=False):
    file_name = (metric or {}).get("file") or (qualified_name.split("::")[0] if "::" in (qualified_name or "") else "")
    role = _function_role(qualified_name, file_name)
    basis = []
    if entry:
        basis.append("classified as a likely entry point")
    if metric:
        if metric.get("fan_in") == 0:
            basis.append("zero internal fan-in")
        if metric.get("fan_out"):
            basis.append(f"fan-out {metric['fan_out']}")
        if file_name:
            basis.append(f"defined in {file_name}")
    if entry:
        text = f"{role} based on its name"
        if metric and metric.get("fan_in") == 0:
            text += " and zero internal fan-in"
        text += "."
    else:
        text = f"{role} from its name"
        if file_name:
            text += f"; defined in {file_name}"
        if metric and metric.get("fan_out"):
            text += f"; calls {metric['fan_out']} internal functions"
        text += "."
    return {"text": text, "basis": basis, "role": role}


def _how_it_works(flows, analysis):
    metrics = {metric["qualified_name"]: metric for metric in analysis["function_metrics"]}
    entries = {entry["qualified_name"]: entry for entry in analysis["likely_entry_points"]}
    explanations = []
    for flow in flows[:MAX_REPORT_ITEMS]:
        steps = []
        for index, node in enumerate(_flow_spine(flow.get("tree") or {})):
            qualified = node.get("qualified_name") or node.get("node")
            metric = metrics.get(qualified, {})
            detail = _step_description(qualified, metric, entry=index == 0 and qualified in entries)
            steps.append({
                "function": qualified,
                "file": metric.get("file") or (qualified.split("::")[0] if "::" in qualified else ""),
                "text": detail["text"],
                "role": detail["role"],
                "basis": (node.get("evidence") or []) + detail["basis"],
                "confidence": "heuristic" if index == 0 else "fact",
            })
        explanations.append({"entry_point": flow["entry_point"], "steps": steps})
    return explanations


def _repository_brief(modules, flows, overview, how_it_works):
    ranked = sorted(
        [module for module in modules if not module.get("is_test") and module.get("module") not in {None, ""}],
        key=lambda item: (-(item.get("total_loc") or 0), item.get("module") or ""),
    )
    structure = []
    seen = set()
    for module in ranked:
        role = module.get("role") or module.get("purpose_hint")
        if not role or role in seen or role == "tests and fixtures":
            continue
        if module.get("module") == ".":
            continue
        seen.add(role)
        structure.append({"role": role, "module": module["module"], "total_loc": module.get("total_loc") or 0})
        if len(structure) >= 5:
            break
    main_flow = []
    if how_it_works:
        main_flow = how_it_works[0].get("steps") or []
    elif flows:
        main_flow = [
            {"function": node.get("qualified_name") or node.get("node"), "text": "", "role": _function_role(node.get("qualified_name") or node.get("node"))}
            for node in _flow_spine((flows[0] or {}).get("tree") or {})
        ]
    names = [step["function"].split("::")[-1] for step in main_flow if step.get("function")]
    return {
        "structure": structure,
        "main_flow": main_flow,
        "main_flow_label": " → ".join(names),
        "languages": overview.get("languages") or [],
    }


def _reading_order(analysis, modules, root):
    module_by_file = {}
    for module in modules:
        for file_name in module["files"]:
            module_by_file[file_name] = module["module"]
    likely_files = {entry["file"] for entry in analysis["likely_entry_points"]}
    entry_strengths = {}
    for entry in analysis["likely_entry_points"]:
        entry_strengths[entry["file"]] = max(
            _entry_strength(entry),
            entry_strengths.get(entry["file"], 0),
        )
    flow_functions = set()

    def collect(node):
        flow_functions.add(node["node"])
        for child in node.get("children", []):
            collect(child)

    for chain in analysis["dependency_chains"]:
        collect(chain)
    flow_files = {
        metric["file"]
        for metric in analysis["function_metrics"]
        if metric["qualified_name"] in flow_functions
    }
    module_centrality = {
        module["module"]: module["incoming_dependencies"] + module["outgoing_dependencies"]
        for module in modules
    }
    max_centrality = max(1, max(module_centrality.values(), default=0))
    max_hotspot = max(1, max((metric["hotspot_score"] for metric in analysis["file_metrics"]), default=0))
    max_imports = max(1, max((metric.get("outgoing_import_dependencies", 0) for metric in analysis["file_metrics"]), default=0))
    candidates = []
    for metric in analysis["file_metrics"]:
        if metric["is_test"]:
            continue
        module = module_by_file.get(metric["file"])
        entry_score = entry_strengths.get(metric["file"], 0.0)
        flow_score = 1.0 if metric["file"] in flow_files else 0.0
        centrality = module_centrality.get(module, 0) / max_centrality
        hotspot = metric["hotspot_score"] / max_hotspot
        import_relevance = metric.get("outgoing_import_dependencies", 0) / max_imports
        score = round(
            READING_ORDER_WEIGHTS["entry_point"] * entry_score
            + READING_ORDER_WEIGHTS["flow_relevance"] * flow_score
            + READING_ORDER_WEIGHTS["module_centrality"] * centrality
            + READING_ORDER_WEIGHTS["hotspot"] * hotspot
            + READING_ORDER_WEIGHTS["import_relevance"] * import_relevance,
            3,
        )
        evidence = [f"{metric['loc']} LOC", f"hotspot {metric['hotspot_score']}"]
        if entry_score:
            evidence.append(f"contains a likely entry point (strength {entry_score})")
        if flow_score:
            evidence.append("appears in a likely-entry dependency flow")
        if module:
            evidence.append(f"module connectivity {module_centrality[module]}")
        candidates.append({
            "kind": "file",
            "name": metric["file"],
            "file": metric["file"],
            "module": module,
            "score": score,
            "display_name": _relative(metric["file"], root),
            "evidence": evidence,
            "explanation": _explanation(
                f"{_relative(metric['file'], root)} is a useful starting point.",
                evidence,
                "heuristic",
            ),
        })
    items = sorted(candidates, key=lambda item: (-item["score"], item["name"]))[:MAX_REPORT_ITEMS]
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
    return items


def _architectural_notes(analysis, modules):
    call_only = [edge for edge in analysis["architecture_edges"] if not edge["import_count"] and edge["call_count"]]
    import_only = [edge for edge in analysis["architecture_edges"] if edge["import_count"] and not edge["call_count"]]
    central_modules = sorted(
        [module for module in modules if not module["is_test"]],
        key=lambda item: (-item["incoming_dependencies"] - item["outgoing_dependencies"], item["module"]),
    )[:MAX_REPORT_ITEMS]
    observations = []
    if analysis["cycles"]:
        observations.append(_explanation(
            f"{len(analysis['cycles'])} dependency cycles were detected.",
            ["function dependency graph cycles"],
            "fact",
        ))
    else:
        observations.append(_explanation(
            "No dependency cycles were detected.",
            ["function dependency graph cycles = 0"],
            "fact",
        ))
    for item in central_modules[:5]:
        observations.append(_explanation(
            f"{item['module']} is among the most connected non-test modules.",
            item["evidence"],
            "heuristic",
        ))
    if call_only:
        observations.append(_explanation(
            f"{len(call_only)} architecture relationships are call-only.",
            ["architecture edges with imports = 0 and calls > 0"],
            "fact",
        ))
    if import_only:
        observations.append(_explanation(
            f"{len(import_only)} architecture relationships are import-only.",
            ["architecture edges with imports > 0 and calls = 0"],
            "fact",
        ))
    return {
        "cycles": analysis["cycles"],
        "central_modules": [
            {
                "module": item["module"],
                "connectivity": item["incoming_dependencies"] + item["outgoing_dependencies"],
                "evidence": item["evidence"],
            }
            for item in central_modules
        ],
        "call_only_edges": call_only,
        "import_only_edges": import_only,
        "observations": observations,
    }


def build_ui_summary(report):
    overview = report.get("overview", {}) or {}
    entry_points = report.get("entry_points", []) or []
    hotspots = report.get("hotspots", {}) or {}
    major_modules = report.get("major_modules") or report.get("modules", []) or []
    flows = report.get("flows", []) or []
    reading_order = report.get("reading_order", []) or []

    def _clip(items, count=4):
        return list(items)[:count]

    return {
        "overview": {
            "repository": overview.get("repository"),
            "languages": overview.get("languages", []),
            "file_count": overview.get("file_count", 0),
            "function_count": overview.get("function_count", 0),
            "module_count": overview.get("module_count", 0),
        },
        "entry_points": [
            {
                "qualified_name": item.get("qualified_name"),
                "file": item.get("file"),
                "line": item.get("line"),
                "name": item.get("name"),
                "hotspot_score": item.get("hotspot_score", 0),
                "classification": item.get("classification"),
                "structural_hints": item.get("structural_hints", []),
            }
            for item in _clip(entry_points)
        ],
        "top_hotspots": [
            {
                "file": item.get("file"),
                "hotspot_score": item.get("hotspot_score", 0),
                "loc": item.get("loc", 0),
                "number_of_defined_functions": item.get("number_of_defined_functions", 0),
                "evidence": item.get("evidence", []),
            }
            for item in _clip((hotspots.get("files") or []))
        ],
        "major_modules": [
            {
                "module": item.get("module"),
                "total_loc": item.get("total_loc"),
                "hotspot_score": item.get("hotspot_score", 0),
                "description": item.get("description"),
                "file_count": len(item.get("files", [])),
            }
            for item in _clip(major_modules)
        ],
        "flows": [
            {
                "entry_point": flow.get("entry_point"),
                "tree": flow.get("tree"),
            }
            for flow in _clip(flows, 3)
        ],
        "reading_order": [
            {
                "file": item.get("file"),
                "display_name": item.get("display_name"),
                "score": item.get("score", 0),
                "reason": item.get("reason", []),
                "evidence": item.get("evidence", []),
            }
            for item in _clip(reading_order)
        ],
        "how_it_works": report.get("how_it_works", []),
        "important_functions": report.get("important_functions", {}),
    }


def build_report(analysis, source_files, languages, root):
    modules = _enrich_modules(analysis, root)
    major_modules = [module for module in modules if not module["is_test"]]
    hotspots = _hotspots(analysis)
    flows = _flows(analysis)
    reading_order = _reading_order(analysis, modules, root)
    important_functions = _important_functions(analysis)
    architectural_notes = _architectural_notes(analysis, modules)
    entry_points = _reported_entry_points(analysis, root)
    how_it_works = _how_it_works(flows, analysis)
    overview = {
        "languages": sorted({languages[Path(file_name).suffix] for file_name in source_files if Path(file_name).suffix in languages}),
        "file_count": len(source_files),
        "function_count": len(analysis["functions"]),
        "module_count": len(modules),
        "repository": Path(root).name,
    }
    result = dict(analysis)
    result.update({
        "overview": overview,
        "repository_summary": {
            "overview": overview,
            "likely_entry_points": entry_points,
            "major_modules": major_modules,
            "top_hotspots": hotspots,
            "important_execution_flows": flows,
            "recommended_reading_order": reading_order,
            "architectural_notes": architectural_notes,
        },
        "functions": analysis["functions"],
        "function_edges": analysis["edges"],
        "function_metrics": analysis["function_metrics"],
        "file_metrics": analysis["file_metrics"],
        "import_edges": analysis["import_edges"],
        "architecture_edges": analysis["architecture_edges"],
        "modules": modules,
        "major_modules": major_modules,
        "entry_points": entry_points,
        "potential_roots": analysis["potential_roots"],
        "hotspots": hotspots,
        "flows": flows,
        "execution_flows": flows,
        "how_it_works": how_it_works,
        "important_functions": important_functions,
        "reading_order": reading_order,
        "architectural_notes": architectural_notes,
        "architecture_notes": architectural_notes,
    })
    result = normalise_report_paths(result, root)
    result["ui_summary"] = build_ui_summary({
        "overview": result["overview"],
        "entry_points": result["entry_points"],
        "hotspots": result["hotspots"],
        "major_modules": result["major_modules"],
        "flows": result["flows"],
        "reading_order": result["reading_order"],
        "how_it_works": result["how_it_works"],
        "important_functions": result["important_functions"],
    })
    return result


PATH_KEYS = {"file", "from", "to", "display_name", "source", "resolved_file", "caller"}
SYMBOL_KEYS = {"qualified_name", "node", "entry_point", "function"}
PATH_LIST_KEYS = {"files"}
SYMBOL_LIST_KEYS = {"defined_functions", "dependents", "dependencies", "candidates"}
GRAPH_KEYS = {"graph", "reverse_graph", "file_graph"}


def _normalise_identity(value, root):
    if not isinstance(value, str):
        return value
    stripped = _strip_root_text(value, root)
    if "::" in stripped:
        return _normalise_symbol_name(stripped, root)
    if "/" in stripped or "\\" in stripped:
        return _relative(stripped, root)
    return stripped


def normalise_report_paths(obj, root, key=None):
    if isinstance(obj, dict):
        if key in GRAPH_KEYS:
            return {
                _normalise_identity(item_key, root): normalise_report_paths(item_value, root)
                for item_key, item_value in obj.items()
            }
        cleaned = {}
        for item_key, value in obj.items():
            if item_key in PATH_KEYS and isinstance(value, str):
                cleaned[item_key] = _relative(value, root)
            elif item_key in SYMBOL_KEYS and isinstance(value, str):
                cleaned[item_key] = _normalise_symbol_name(_strip_root_text(value, root), root)
            elif item_key == "name" and isinstance(value, str):
                cleaned[item_key] = _normalise_identity(value, root)
            elif item_key in PATH_LIST_KEYS and isinstance(value, list):
                cleaned[item_key] = [_relative(item, root) if isinstance(item, str) else normalise_report_paths(item, root) for item in value]
            elif item_key in SYMBOL_LIST_KEYS and isinstance(value, list):
                cleaned[item_key] = [_normalise_identity(item, root) if isinstance(item, str) else normalise_report_paths(item, root, item_key) for item in value]
            else:
                cleaned[item_key] = normalise_report_paths(value, root, item_key)
        return cleaned
    if isinstance(obj, list):
        return [
            _normalise_identity(item, root) if key == "cycles" and isinstance(item, str)
            else normalise_report_paths(item, root, key)
            for item in obj
        ]
    if isinstance(obj, str):
        return _strip_root_text(obj, root)
    return obj


def _print_flow_tree(node, prefix=""):
    for index, child in enumerate(node.get("children", [])):
        branch = "└── " if index == len(node["children"]) - 1 else "├── "
        print(f"{prefix}{branch}{child['qualified_name'].split('::')[-1]}")
        next_prefix = prefix + ("    " if index == len(node["children"]) - 1 else "│   ")
        _print_flow_tree(child, next_prefix)


def print_report(report, root):
    overview = report["overview"]
    print("\n================ REPO AUTOPSY ================")
    print("\nOVERVIEW")
    print(f"languages: {', '.join(overview['languages'])}")
    print(f"files: {overview['file_count']} | functions: {overview['function_count']} | modules: {overview['module_count']}")

    print("\nWHAT IS THIS REPOSITORY?")
    summary_modules = [module["module"] for module in report["major_modules"] if not module["is_test"] and module["module"] != "."][:5]
    print(f"- Deterministic analysis found {', '.join(summary_modules)} as the largest non-test directory groups.")
    print(f"- The report is based on {len(report['function_edges'])} function edges and {len(report['import_edges'])} resolved import edges.")

    print("\nMAJOR MODULES")
    for module in sorted(report["modules"], key=lambda item: (item["is_test"], -item["hotspot_score"], item["module"]))[:MAX_REPORT_ITEMS]:
        hint = f"; {module['purpose_hint']}" if module["purpose_hint"] else ""
        print(f"- {module['module']} ({module['total_loc']} LOC, {module['number_of_definitions']} definitions, score {module['hotspot_score']}){hint}")
        print(f"  {module['description']}")
        print(f"  key files: {', '.join(Path(file_name).name for file_name in module['files'][:5])}")
        if module["dependencies"]:
            relationships = ", ".join(
                f"{dependency['module']} (imports {dependency['import_count']}, calls {dependency['call_count']})"
                for dependency in module["dependencies"][:4]
            )
            print(f"  depends on: {relationships}")
        print(f"  evidence: {', '.join(module['evidence'][-3:])}")

    print("\nLIKELY ENTRY POINTS")
    for entry in report["entry_points"][:MAX_REPORT_ITEMS]:
        print(f"- {entry['qualified_name']} ({', '.join(entry['structural_hints']) or 'heuristic entry-point match'})")
    print(f"potential roots retained: {len(report['potential_roots'])}")

    print("\nTOP HOTSPOTS")
    for item in report["hotspots"]["files"][:5]:
        print(f"- {_relative(item['file'], root)}: score {item['hotspot_score']} ({', '.join(item['evidence'])})")

    print("\nHOW IT WORKS")
    for explanation in _how_it_works(report["execution_flows"], report):
        print(f"- {explanation['entry_point'].split('::')[-1]}")
        for step in explanation["steps"][:MAX_FLOW_BRANCHES + 1]:
            print(f"  {step['function'].split('::')[-1]}: {step['text']}")

    print("\nMAIN EXECUTION FLOWS")
    for flow in report["flows"]:
        print(f"- {flow['entry_point'].split('::')[-1]}")
        _print_flow_tree(flow["tree"])

    print("\nIMPORTANT FUNCTIONS")
    for category, items in report["important_functions"].items():
        print(f"{category.replace('_', ' ').upper()}")
        for item in items[:5]:
            print(f"- {item['qualified_name'].split('::')[-1]} ({', '.join(item['evidence'])})")

    print("\nWHERE SHOULD I START?")
    for item in report["reading_order"]:
        print(f"{item['rank']}. {item['display_name']} ({item['module']})")
        print(f"   why: {', '.join(item['evidence']) or 'ranked by hotspot and dependency metrics'}")

    print("\nARCHITECTURAL NOTES")
    print(f"cycles: {len(report['architectural_notes']['cycles'])}")
    for item in report["architectural_notes"]["central_modules"][:5]:
        print(f"- central module {item['module']} ({item['connectivity']} cross-module relationships)")
    print(f"call-only architecture edges: {len(report['architectural_notes']['call_only_edges'])}")
    print(f"import-only architecture edges: {len(report['architectural_notes']['import_only_edges'])}")
