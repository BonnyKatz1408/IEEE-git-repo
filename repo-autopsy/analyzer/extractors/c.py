def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def _decode(node):
    return node.text.decode() if node else None


def _function_name(declarator):
    if not declarator:
        return None
    name_node = None
    for child in walk(declarator):
        if child.type == "identifier":
            name_node = child
            break
    return _decode(name_node) if name_node else None


def _callee_name(func):
    if func is None:
        return None
    if func.type == "identifier":
        return _decode(func)
    if func.type == "field_expression":
        field = func.child_by_field_name("field")
        if field:
            return _decode(field)
    name = None
    for child in walk(func):
        if child.type in ("identifier", "field_identifier"):
            name = _decode(child)
    return name


def _callee_receiver(func):
    if func and func.type == "field_expression":
        receiver = func.child_by_field_name("argument")
        return _decode(receiver)
    return None


def _enclosing_caller(node, file_path):
    current = node.parent
    while current:
        if current.type == "function_definition":
            name = _function_name(current.child_by_field_name("declarator"))
            if name:
                return f"{file_path}::{name}"
        current = current.parent
    return None


def extract(tree, file_path):
    symbols = []
    calls = []
    file_str = str(file_path)

    for node in walk(tree.root_node):

        if node.type == "function_definition":
            name = _function_name(node.child_by_field_name("declarator"))
            if not name:
                continue

            symbols.append({
                "name": name,
                "qualified_name": f"{file_path}::{name}",
                "type": "function",
                "language": "c",
                "file": file_str,
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1
            })

        elif node.type == "call_expression":
            name = _callee_name(node.child_by_field_name("function"))
            if name:
                calls.append({
                    "name": name,
                    "caller": _enclosing_caller(node, file_path),
                    "receiver": _callee_receiver(node.child_by_field_name("function")),
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })

    return symbols, calls
