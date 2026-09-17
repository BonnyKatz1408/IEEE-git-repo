from collections import defaultdict, deque


# These weights are intentionally small, explicit, and easy to tune.
HOTSPOT_WEIGHTS = {"loc": 0.4, "fan_in": 0.3, "fan_out": 0.3}
FILE_HOTSPOT_WEIGHTS = {
    "loc": 0.35,
    "number_of_defined_functions": 0.2,
    "incoming_dependencies": 0.2,
    "outgoing_dependencies": 0.15,
    "internal_edges": 0.1,
}
ONBOARDING_WEIGHTS = {
    "hotspot": 0.4,
    "entry_point": 0.25,
    "connectivity": 0.2,
    "chain": 0.15,
}


def qualified_name(symbol):
    return symbol.get("qualified_name") or f"{symbol['file']}::{symbol['name']}"


def build_graph(definitions, edges):
    """Build function-level adjacency and reverse-adjacency maps."""
    nodes = {qualified_name(symbol) for symbol in definitions}
    graph = {node: set() for node in nodes}
    reverse_graph = {node: set() for node in nodes}
    internal_edges = []
    seen_edges = set()

    for edge in edges:
        source = edge.get("from")
        target = edge.get("to")
        if source not in nodes or target not in nodes:
            continue
        edge_key = (source, target)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        graph[source].add(target)
        reverse_graph[target].add(source)
        internal_edges.append({"from": source, "to": target})

    return {
        "nodes": sorted(nodes),
        "graph": graph,
        "reverse_graph": reverse_graph,
        "edges": internal_edges,
    }


def _reachable(adjacency, start):
    if start not in adjacency:
        return []

    found = set()
    pending = deque(adjacency[start])
    while pending:
        node = pending.popleft()
        if node in found:
            continue
        found.add(node)
        pending.extend(adjacency[node])
    return sorted(found)


def reachable_dependencies(graph_data, node):
    return _reachable(graph_data["graph"], node)


def dependents_of(graph_data, node):
    return _reachable(graph_data["reverse_graph"], node)


def downstream_files(file_edges, file_name):
    """Return files reachable downstream from a file-level dependency graph."""
    graph = defaultdict(set)
    for edge in file_edges:
        graph[edge["from"]].add(edge["to"])
    return _reachable(graph, file_name)


def _cycles(graph):
    state = {}
    stack = []
    cycles = {}

    def visit(node):
        state[node] = "visiting"
        stack.append(node)

        for target in sorted(graph[node]):
            if state.get(target) == "visiting":
                start = stack.index(target)
                cycle = stack[start:]
                rotations = [
                    tuple(cycle[index:] + cycle[:index])
                    for index in range(len(cycle))
                ]
                cycles[min(rotations)] = cycle + [target]
            elif state.get(target) != "visited":
                visit(target)

        stack.pop()
        state[node] = "visited"

    for node in sorted(graph):
        if state.get(node) is None:
            visit(node)

    return [cycles[key] for key in sorted(cycles)]


def _structural_hints(symbol):
    name = symbol["name"].split(".")[-1].lower()
    hints = []
    if name == "main":
        hints.append("main")
    if name.startswith("onrequest") or name in {"handler", "handle", "serve", "start", "run"}:
        hints.append("common handler or startup name")
    return hints


def _is_test_file(file_name):
    parts = [part.lower() for part in file_name.replace("\\", "/").split("/")]
    basename = parts[-1]
    return any(
        part in {"test", "tests", "__tests__", "spec", "fixtures", "fixture"}
        for part in parts
    ) or basename.endswith(("_test.py", "_test.js", "_test.ts", ".test.js", ".test.ts", ".spec.js", ".spec.ts"))


def _normalise(items, key):
    maximum = max((item.get(key, 0) for item in items), default=0)
    if maximum == 0:
        return {id(item): 0.0 for item in items}
    return {id(item): item.get(key, 0) / maximum for item in items}


def _weighted_score(item, weights, normalised):
    return round(sum(weight * normalised[key].get(id(item), 0.0) for key, weight in weights.items()), 3)


def _function_metrics(definitions, graph_data):
    metrics = []
    fan_in = graph_data["reverse_graph"]
    fan_out = graph_data["graph"]

    for symbol in definitions:
        node = qualified_name(symbol)
        if node not in fan_out:
            continue
        item = dict(symbol)
        item["qualified_name"] = node
        item["loc"] = item.get("loc", 0)
        item["fan_in"] = len(fan_in[node])
        item["fan_out"] = len(fan_out[node])
        item["number_of_dependents"] = item["fan_in"]
        item["number_of_dependencies"] = item["fan_out"]
        item["dependents"] = sorted(fan_in[node])
        item["dependencies"] = sorted(fan_out[node])
        metrics.append(item)

    normalised = {key: _normalise(metrics, key) for key in HOTSPOT_WEIGHTS}
    for item in metrics:
        item["hotspot_score"] = _weighted_score(item, HOTSPOT_WEIGHTS, normalised)
        item["is_test"] = _is_test_file(item["file"])

    metrics.sort(key=lambda item: item["qualified_name"])
    return metrics


def _entry_points(metrics):
    potential_roots = []
    likely_entries = []
    for metric in metrics:
        if metric["fan_in"] != 0:
            continue
        hints = _structural_hints(metric)
        name = metric["name"].split(".")[-1].lower()
        likely_name = bool(hints) or name.startswith(("app", "bootstrap", "initialize", "init"))
        entry = {
            "qualified_name": metric["qualified_name"],
            "file": metric["file"],
            "line": metric["line"],
            "name": metric["name"],
            "fan_in": metric["fan_in"],
            "fan_out": metric["fan_out"],
            "hotspot_score": metric["hotspot_score"],
            "is_test": metric["is_test"],
            "classification": "raw zero-fan-in root",
            "structural_hints": hints,
        }
        potential_roots.append(entry)
        if not metric["is_test"] and likely_name:
            entry = dict(entry)
            entry["classification"] = "likely entry point"
            likely_entries.append(entry)
    likely_entries.sort(key=lambda item: (-item["hotspot_score"], item["qualified_name"]))
    return potential_roots, likely_entries


def _file_analysis(metrics, edges, source_files=None):
    definitions_by_node = {metric["qualified_name"]: metric for metric in metrics}
    file_functions = defaultdict(list)
    file_edges = defaultdict(set)
    file_edge_counts = defaultdict(int)
    file_call_counts = defaultdict(int)
    internal_edges = defaultdict(set)

    for metric in metrics:
        file_functions[metric["file"]].append(metric["qualified_name"])

    for edge in edges:
        source = definitions_by_node.get(edge["from"])
        target = definitions_by_node.get(edge["to"])
        if source is None or target is None:
            continue
        source_file = source["file"]
        target_file = target["file"]
        file_call_counts[source_file] += 1
        if source_file == target_file:
            internal_edges[source_file].add((edge["from"], edge["to"]))
            continue
        file_edges[source_file].add(target_file)
        file_edge_counts[(source_file, target_file)] += 1

    files = set(source_files or {}) | set(file_functions) | set(file_edges)
    incoming = defaultdict(set)
    for source_file, targets in file_edges.items():
        for target_file in targets:
            incoming[target_file].add(source_file)
    files.update(incoming)

    file_metrics = []
    for file in sorted(files):
        file_metrics.append({
            "file": file,
            "loc": (source_files or {}).get(file, 0),
            "defined_functions": sorted(file_functions[file]),
            "number_of_defined_functions": len(file_functions[file]),
            "incoming_dependencies": len(incoming[file]),
            "outgoing_dependencies": len(file_edges[file]),
            "incoming_call_dependencies": len(incoming[file]),
            "outgoing_call_dependencies": len(file_edges[file]),
            "number_of_calls": file_call_counts[file],
            "internal_edges": len(internal_edges[file]),
            "is_test": _is_test_file(file),
        })

    normalised = {
        key: _normalise(file_metrics, key)
        for key in FILE_HOTSPOT_WEIGHTS
    }
    for metric in file_metrics:
        metric["hotspot_score"] = _weighted_score(metric, FILE_HOTSPOT_WEIGHTS, normalised)

    aggregated_edges = [
        {"from": source, "to": target, "count": file_edge_counts[(source, target)]}
        for source in sorted(file_edges)
        for target in sorted(file_edges[source])
    ]
    return file_metrics, aggregated_edges


def dependency_chain(graph_data, node, direction="downstream", max_depth=3):
    """Return a bounded, non-repeating dependency tree for one graph node."""
    adjacency = graph_data["graph"] if direction == "downstream" else graph_data["reverse_graph"]

    def build(current, depth, seen):
        if depth >= max_depth:
            return []
        children = []
        for target in sorted(adjacency.get(current, ())):
            if target in seen:
                continue
            children.append({
                "node": target,
                "children": build(target, depth + 1, seen | {target}),
            })
        return children

    return {"node": node, "direction": direction, "depth": max_depth, "children": build(node, 0, {node})}


def _onboarding_ranking(function_metrics, file_metrics, likely_entries, graph_data):
    likely_names = {entry["qualified_name"] for entry in likely_entries}
    file_by_name = {metric["file"]: metric for metric in file_metrics}
    function_norm = {key: _normalise(function_metrics, key) for key in ("fan_in", "fan_out")}
    candidates = []

    for metric in function_metrics:
        if metric["is_test"]:
            continue
        chain_size = len(reachable_dependencies(graph_data, metric["qualified_name"]))
        chain_norm = chain_size / max(1, len(graph_data["nodes"]))
        connectivity = (function_norm["fan_in"].get(id(metric), 0) + function_norm["fan_out"].get(id(metric), 0)) / 2
        entry_score = 1.0 if metric["qualified_name"] in likely_names else 0.0
        score = round(
            ONBOARDING_WEIGHTS["hotspot"] * metric["hotspot_score"]
            + ONBOARDING_WEIGHTS["entry_point"] * entry_score
            + ONBOARDING_WEIGHTS["connectivity"] * connectivity
            + ONBOARDING_WEIGHTS["chain"] * chain_norm,
            3,
        )
        reasons = []
        if entry_score:
            reasons.append("likely entry point")
        if metric["fan_out"]:
            reasons.append("high fan-out")
        if metric["fan_in"]:
            reasons.append("central dependency")
        if chain_size:
            reasons.append(f"connects to {chain_size} downstream functions")
        candidates.append({
            "kind": "function",
            "name": metric["qualified_name"],
            "file": metric["file"],
            "line": metric["line"],
            "score": score,
            "reason": reasons,
            "hotspot_score": metric["hotspot_score"],
            "fan_in": metric["fan_in"],
            "fan_out": metric["fan_out"],
            "loc": metric["loc"],
        })

    for metric in file_metrics:
        if metric["is_test"]:
            continue
        roots_in_file = sum(1 for entry in likely_entries if entry["file"] == metric["file"])
        score = round(metric["hotspot_score"] + min(0.2, roots_in_file * 0.1), 3)
        reasons = []
        if roots_in_file:
            reasons.append("contains a likely entry point")
        if metric["outgoing_dependencies"]:
            reasons.append("high file fan-out")
        if metric["incoming_dependencies"]:
            reasons.append("central file dependency")
        candidates.append({
            "kind": "file",
            "name": metric["file"],
            "file": metric["file"],
            "score": score,
            "reason": reasons,
            "hotspot_score": metric["hotspot_score"],
            "loc": metric["loc"],
            "incoming_dependencies": metric["incoming_dependencies"],
            "outgoing_dependencies": metric["outgoing_dependencies"],
            "number_of_defined_functions": metric["number_of_defined_functions"],
        })

    return sorted(candidates, key=lambda item: (-item["score"], item["name"]))


def analyze_graph(definitions, edges, source_files=None):
    graph_data = build_graph(definitions, edges)
    function_metrics = _function_metrics(definitions, graph_data)
    potential_roots, likely_entry_points = _entry_points(function_metrics)
    file_metrics, file_edges = _file_analysis(function_metrics, graph_data["edges"], source_files)

    most_depended_on = sorted(
        function_metrics,
        key=lambda item: (-item["fan_in"], item["qualified_name"]),
    )
    highest_fan_out = sorted(
        function_metrics,
        key=lambda item: (-item["fan_out"], item["qualified_name"]),
    )
    dependency_chains = [
        dependency_chain(graph_data, entry["qualified_name"], max_depth=3)
        for entry in likely_entry_points
    ]

    return {
        "functions": [dict(symbol, qualified_name=qualified_name(symbol)) for symbol in definitions],
        "edges": graph_data["edges"],
        "graph": {
            node: sorted(targets)
            for node, targets in graph_data["graph"].items()
        },
        "reverse_graph": {
            node: sorted(sources)
            for node, sources in graph_data["reverse_graph"].items()
        },
        "entry_points": likely_entry_points,
        "potential_roots": potential_roots,
        "likely_entry_points": likely_entry_points,
        "cycles": _cycles(graph_data["graph"]),
        "function_metrics": function_metrics,
        "most_depended_on": most_depended_on,
        "highest_fan_out": highest_fan_out,
        "dependency_chains": dependency_chains,
        "file_metrics": file_metrics,
        "file_edges": file_edges,
        "file_graph": {
            file: sorted(targets)
            for file in {edge["from"] for edge in file_edges}
            for targets in [{edge["to"] for edge in file_edges if edge["from"] == file}]
        },
        "onboarding_ranking": _onboarding_ranking(
            function_metrics, file_metrics, likely_entry_points, graph_data
        ),
    }