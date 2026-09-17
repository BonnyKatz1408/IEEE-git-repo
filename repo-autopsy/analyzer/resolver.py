from collections import defaultdict


def _short_name(symbol):
    return symbol["name"].split(".")[-1]


def _qualified(symbol):
    return symbol.get("qualified_name") or f"{symbol['file']}::{symbol['name']}"


def _caller_parts(caller):
    file_name, separator, function_name = caller.rpartition("::")
    if not separator:
        return None, caller
    return file_name, function_name


def _scope_name(name):
    if "." not in name:
        return None
    return name.rsplit(".", 1)[0]


def _issue(call, status, reason, candidates=()):
    issue = dict(call)
    issue["status"] = status
    issue["reason"] = reason
    if candidates:
        issue["candidates"] = sorted(_qualified(candidate) for candidate in candidates)
    return issue


def resolve_calls(definitions, calls):
    """Resolve calls conservatively and retain unresolved resolution issues."""
    by_name = defaultdict(list)
    by_qualified_name = {}
    for symbol in definitions:
        by_name[_short_name(symbol)].append(symbol)
        by_qualified_name[_qualified(symbol)] = symbol

    edges = []
    unresolved = []
    seen = set()

    for call in calls:
        caller = call.get("caller")
        name = call.get("name")
        if not caller or not name:
            unresolved.append(_issue(call, "unresolved", "missing caller or name"))
            continue

        exact_name = call.get("qualified_name") or call.get("target")
        if exact_name:
            exact = by_qualified_name.get(exact_name)
            candidates = [exact] if exact else []
        else:
            candidates = by_name.get(name, [])

        if not candidates:
            unresolved.append(_issue(call, "unresolved", "no repository definition"))
            continue

        _, caller_name = _caller_parts(caller)
        same_file = [symbol for symbol in candidates if symbol["file"] == call.get("file")]
        caller_scope = _scope_name(caller_name)
        same_scope = [
            symbol for symbol in candidates
            if caller_scope and _scope_name(symbol["name"]) == caller_scope
        ]

        receiver = call.get("receiver")
        if receiver and not exact_name and receiver not in {"this", "self"}:
            unresolved.append(_issue(call, "unresolved", "receiver-qualified call", candidates))
            continue

        if len(candidates) == 1 and exact_name:
            chosen = candidates
        elif len(same_file) == 1:
            chosen = same_file
        elif len(same_scope) == 1:
            chosen = same_scope
        elif len(candidates) == 1 and not call.get("receiver"):
            chosen = candidates
        else:
            status = "ambiguous" if len(candidates) > 1 else "unresolved"
            reason = "multiple repository definitions" if status == "ambiguous" else "receiver-qualified call"
            unresolved.append(_issue(call, status, reason, candidates))
            continue

        target = _qualified(chosen[0])
        if target == caller and receiver and receiver not in {"this", "self"}:
            unresolved.append(_issue(call, "unresolved", "receiver-qualified self match", chosen))
            continue

        key = (caller, target)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"from": caller, "to": target})

    return {"edges": edges, "unresolved": unresolved}


def resolve(definitions, calls):
    """Match calls to repository definitions and return internal edges.

    This compatibility wrapper keeps the original edge-only API. Use
    ``resolve_calls`` when unresolved and ambiguous calls are needed.
    """
    return resolve_calls(definitions, calls)["edges"]
