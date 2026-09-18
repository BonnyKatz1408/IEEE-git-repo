import math


MODULE_COLORS = [
    0x1F7AB8, 0x1EAF9F, 0x8B5DC7, 0xD15A8B, 0x2E9CCF, 0x4D9D5E,
    0x4C6EDB, 0xE2913D, 0x3A9BB0, 0xC759A6, 0x3F9F89, 0x667AC9,
    0x1E79A8, 0xB56B3D, 0x2E7F6A, 0x9A4C72,
]


def _file_name(path):
    return str(path).rsplit("/", 1)[-1]


def _district_name(module_name):
    if not module_name or module_name == ".":
        return "root"
    return str(module_name).split("/")[0]


def build_map_layout(report):
    hotspot_files = {item["file"] for item in (report.get("hotspots") or {}).get("files") or []}
    entry_files = {item["file"] for item in report.get("entry_points") or []}
    modules = []
    for index, module in enumerate(report.get("modules") or []):
        name = module.get("module") or f"module-{index}"
        modules.append({
            "id": name,
            "name": name,
            "district": _district_name(name),
            "files": list(module.get("files") or []),
            "index": index,
            "color": MODULE_COLORS[index % len(MODULE_COLORS)],
            "total_loc": module.get("total_loc") or 0,
            "hotspot_score": module.get("hotspot_score") or 0,
        })
    module_by_file = {}
    for module in modules:
        for path in module["files"]:
            module_by_file[path] = module

    files = []
    for index, raw in enumerate(report.get("file_metrics") or []):
        path = raw.get("file") or f"file-{index}"
        module = module_by_file.get(path)
        loc = int(raw.get("loc") or 1)
        function_count = int(raw.get("number_of_defined_functions") or 0)
        fan_in = int(raw.get("incoming_import_dependencies") or 0) + int(raw.get("incoming_call_dependencies") or 0)
        fan_out = int(raw.get("outgoing_import_dependencies") or 0) + int(raw.get("outgoing_call_dependencies") or 0)
        hotspot_score = float(raw.get("hotspot_score") or 0)
        is_hotspot = path in hotspot_files or hotspot_score > 0.65
        files.append({
            "id": path,
            "path": path,
            "name": _file_name(path),
            "module": module["name"] if module else (path.split("/")[0] if "/" in path else "root"),
            "district": module["district"] if module else _district_name(path),
            "module_index": module["index"] if module else 0,
            "loc": loc,
            "functions": function_count,
            "hotspot": hotspot_score,
            "is_hotspot": is_hotspot,
            "fan_in": fan_in,
            "fan_out": fan_out,
            "entry": bool(raw.get("is_entry_point")) or path in entry_files,
        })
    file_by_id = {item["id"]: item for item in files}

    file_edges = []
    for edge in report.get("architecture_edges") or []:
        source = file_by_id.get(str(edge.get("from")))
        target = file_by_id.get(str(edge.get("to")))
        if not source or not target or source["id"] == target["id"]:
            continue
        weight = int(edge.get("import_count") or 0) + int(edge.get("call_count") or 0)
        file_edges.append({
            "from": source["id"],
            "to": target["id"],
            "weight": weight,
            "import_count": int(edge.get("import_count") or 0),
            "call_count": int(edge.get("call_count") or 0),
            "cross_module": source["module"] != target["module"],
        })

    columns = max(1, math.ceil(math.sqrt(max(len(modules), 1))))
    module_rows = max(1, math.ceil(len(modules) / columns))
    layouts = []
    for module in modules:
        file_count = sum(1 for item in files if item["module"] == module["name"])
        file_columns = max(1, math.ceil(math.sqrt(max(file_count, 1))))
        file_rows = max(1, math.ceil(file_count / file_columns))
        layouts.append({
            "file_columns": file_columns,
            "file_rows": file_rows,
            "width": max(80, file_columns * 24 + 34),
            "depth": max(80, file_rows * 24 + 34),
        })
    cell_size = max(190, max((max(item["width"], item["depth"]) + 70) for item in layouts) if layouts else 190)

    buildings = []
    module_nodes = []
    bounds = {"min_x": math.inf, "max_x": -math.inf, "min_z": math.inf, "max_z": -math.inf, "max_y": 0}
    for module_index, module in enumerate(modules):
        module_files = [item for item in files if item["module"] == module["name"]]
        if not module_files:
            continue
        module_column = module_index % columns
        module_row = module_index // columns
        base_x = (module_column - (columns - 1) / 2) * cell_size
        base_z = (module_row - (module_rows - 1) / 2) * cell_size
        layout = layouts[module_index]
        plate_width = layout["width"]
        plate_depth = layout["depth"]
        bounds["min_x"] = min(bounds["min_x"], base_x - plate_width / 2)
        bounds["max_x"] = max(bounds["max_x"], base_x + plate_width / 2)
        bounds["min_z"] = min(bounds["min_z"], base_z - plate_depth / 2)
        bounds["max_z"] = max(bounds["max_z"], base_z + plate_depth / 2)
        module_nodes.append({
            **module,
            "x": base_x,
            "z": base_z,
            "width": plate_width,
            "depth": plate_depth,
            "file_count": len(module_files),
        })
        file_columns = layout["file_columns"]
        for file_index, file in enumerate(module_files):
            column = file_index % file_columns
            row = file_index // file_columns
            x = base_x + (column - (file_columns - 1) / 2) * 24
            z = base_z + (row - (file_columns - 1) / 2) * 24
            height = max(8, min(155 if file["is_hotspot"] else 115, math.log1p(file["loc"]) * (18 if file["is_hotspot"] else 14)))
            width = max(15 if file["is_hotspot"] else 10, min(25 if file["is_hotspot"] else 18, (10 + file["functions"] * 0.25 + file["fan_out"] * 0.5) * (1.3 if file["is_hotspot"] else 1)))
            depth = max(15 if file["is_hotspot"] else 10, min(25 if file["is_hotspot"] else 18, (10 + file["fan_in"] * 0.45 + file["loc"] / 500) * (1.3 if file["is_hotspot"] else 1)))
            bounds["max_y"] = max(bounds["max_y"], height)
            buildings.append({
                **file,
                "x": x,
                "z": z,
                "height": round(height, 3),
                "width": round(width, 3),
                "depth": round(depth, 3),
            })

    if not math.isfinite(bounds["min_x"]):
        bounds = {"min_x": -50, "max_x": 50, "min_z": -50, "max_z": 50, "max_y": 20}

    district_nodes = {}
    for module in module_nodes:
        district = district_nodes.setdefault(module["district"], {
            "id": module["district"],
            "name": module["district"],
            "modules": [],
            "min_x": math.inf,
            "max_x": -math.inf,
            "min_z": math.inf,
            "max_z": -math.inf,
            "file_count": 0,
            "total_loc": 0,
            "color": module["color"],
        })
        district["modules"].append(module["id"])
        district["file_count"] += module["file_count"]
        district["total_loc"] += module.get("total_loc") or 0
        district["min_x"] = min(district["min_x"], module["x"] - module["width"] / 2)
        district["max_x"] = max(district["max_x"], module["x"] + module["width"] / 2)
        district["min_z"] = min(district["min_z"], module["z"] - module["depth"] / 2)
        district["max_z"] = max(district["max_z"], module["z"] + module["depth"] / 2)
    for district in district_nodes.values():
        district["x"] = (district["min_x"] + district["max_x"]) / 2
        district["z"] = (district["min_z"] + district["max_z"]) / 2
        district["width"] = max(90, district["max_x"] - district["min_x"] + 24)
        district["depth"] = max(90, district["max_z"] - district["min_z"] + 24)

    module_edges = {}
    district_edges = {}
    for edge in file_edges:
        source = file_by_id[edge["from"]]
        target = file_by_id[edge["to"]]
        if source["module"] != target["module"]:
            key = (source["module"], target["module"])
            current = module_edges.setdefault(key, {"from": source["module"], "to": target["module"], "weight": 0})
            current["weight"] += edge["weight"]
        if source["district"] != target["district"]:
            key = (source["district"], target["district"])
            current = district_edges.setdefault(key, {"from": source["district"], "to": target["district"], "weight": 0})
            current["weight"] += edge["weight"]

    important = sorted(
        buildings,
        key=lambda item: (not item["entry"], not item["is_hotspot"], -item["hotspot"], -item["loc"]),
    )
    return {
        "bounds": bounds,
        "modules": module_nodes,
        "districts": list(district_nodes.values()),
        "buildings": buildings,
        "file_edges": sorted(file_edges, key=lambda item: -item["weight"])[:400],
        "module_edges": sorted(module_edges.values(), key=lambda item: -item["weight"])[:80],
        "district_edges": sorted(district_edges.values(), key=lambda item: -item["weight"])[:40],
        "important_files": [item["id"] for item in important[:80]],
    }
