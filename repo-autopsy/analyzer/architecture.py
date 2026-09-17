from collections import defaultdict
from pathlib import Path


def _module_for(file_name, root):
    relative = Path(file_name).resolve().relative_to(Path(root).resolve())
    return relative.parent.as_posix() or "."


def _edge_counts(import_edges, call_edges):
    counts = defaultdict(lambda: {"import_count": 0, "call_count": 0})
    for edge in import_edges:
        counts[(str(edge["from"]), str(edge["to"]))]["import_count"] += 1
    for edge in call_edges:
        counts[(str(edge["from"]), str(edge["to"]))]["call_count"] += edge.get("count", 1)
    return counts


def enrich_architecture(analysis, import_analysis, source_files, root):
    import_edges = import_analysis["import_edges"]
    call_edges = analysis.get("file_edges", [])
    counts = _edge_counts(import_edges, call_edges)

    file_metrics = {metric["file"]: metric for metric in analysis.get("file_metrics", [])}
    import_outgoing = defaultdict(set)
    import_incoming = defaultdict(set)
    import_counts = defaultdict(int)
    for edge in import_edges:
        import_outgoing[edge["from"]].add(edge["to"])
        import_incoming[edge["to"]].add(edge["from"])
        import_counts[edge["from"]] += 1

    for file_name, metric in file_metrics.items():
        metric["incoming_call_dependencies"] = metric.get("incoming_dependencies", 0)
        metric["outgoing_call_dependencies"] = metric.get("outgoing_dependencies", 0)
        metric["incoming_import_dependencies"] = len(import_incoming[file_name])
        metric["outgoing_import_dependencies"] = len(import_outgoing[file_name])
        metric["number_of_imports"] = import_counts[file_name]

    architecture_edges = []
    for (source, target), edge_counts in sorted(counts.items()):
        edge = {"from": source, "to": target, **edge_counts}
        edge["types"] = [
            edge_type for edge_type, count in (("import", edge["import_count"]), ("call", edge["call_count"]))
            if count
        ]
        architecture_edges.append(edge)

    module_files = defaultdict(list)
    for file_name in source_files:
        module_files[_module_for(file_name, root)].append(file_name)

    module_edges = defaultdict(lambda: {"import_count": 0, "call_count": 0})
    for edge in architecture_edges:
        source_module = _module_for(edge["from"], root)
        target_module = _module_for(edge["to"], root)
        if source_module != target_module:
            module_edges[(source_module, target_module)]["import_count"] += edge["import_count"]
            module_edges[(source_module, target_module)]["call_count"] += edge["call_count"]

    modules = []
    for module, files in sorted(module_files.items()):
        module_file_set = set(files)
        internal_edges = []
        outgoing_edges = []
        incoming_edges = []
        incoming = set()
        outgoing = set()
        for edge in architecture_edges:
            source_module = _module_for(edge["from"], root)
            target_module = _module_for(edge["to"], root)
            if source_module == module and target_module == module:
                internal_edges.append(edge)
            elif source_module == module:
                outgoing_edges.append(edge)
                outgoing.add(target_module)
            elif target_module == module:
                incoming_edges.append(edge)
                incoming.add(source_module)
        external_edges = outgoing_edges + incoming_edges
        modules.append({
            "module": module,
            "files": sorted(module_file_set),
            "incoming_dependencies": len(incoming),
            "outgoing_dependencies": len(outgoing),
            "internal_edges": len(internal_edges),
            "external_edges": len(external_edges),
            "incoming_import_dependencies": len({
                (edge["from"], edge["to"]) for edge in incoming_edges if edge["import_count"]
            }),
            "outgoing_import_dependencies": sum(
                edge["import_count"] for edge in outgoing_edges if edge["import_count"]
            ),
            "incoming_call_dependencies": len({
                (edge["from"], edge["to"]) for edge in incoming_edges if edge["call_count"]
            }),
            "outgoing_call_dependencies": sum(
                edge["call_count"] for edge in outgoing_edges if edge["call_count"]
            ),
        })

    module_by_file = {
        file_name: _module_for(file_name, root)
        for file_name in source_files
    }
    for item in analysis.get("onboarding_ranking", []):
        item["module"] = module_by_file.get(item["file"])
        metric = file_metrics.get(item["file"])
        if metric is None:
            continue
        if metric["outgoing_import_dependencies"]:
            item["reason"].append("high import fan-out")
            item["score"] = round(item["score"] + min(0.15, metric["outgoing_import_dependencies"] / 20), 3)
    analysis["onboarding_ranking"] = sorted(
        analysis.get("onboarding_ranking", []),
        key=lambda item: (-item["score"], item["name"]),
    )

    return {
        "imports": import_analysis["imports"],
        "import_edges": import_edges,
        "unresolved_imports": import_analysis["unresolved_imports"],
        "architecture_edges": architecture_edges,
        "modules": modules,
        "module_edges": [
            {"from": source, "to": target, **values}
            for (source, target), values in sorted(module_edges.items())
        ],
        "file_metrics": list(file_metrics.values()),
    }
