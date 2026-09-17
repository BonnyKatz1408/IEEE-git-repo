def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def _decode(node):
    return node.text.decode() if node else None


def _callee_name(func):
    if func is None:
        return None

    if func.type == "identifier":
        return _decode(func)

    if func.type == "attribute":
        attr = func.child_by_field_name("attribute")
        if attr:
            return _decode(attr)

    name = None
    for child in walk(func):
        if child.type == "identifier":
            name = _decode(child)
    return name


def _callee_receiver(func):
    if func and func.type == "attribute":
        receiver = func.child_by_field_name("object")
        return _decode(receiver)
    return None


def _enclosing_caller(node, file_path):
    current = node.parent
    while current:
        if current.type == "function_definition":
            name_node = current.child_by_field_name("name")
            if name_node:
                return f"{file_path}::{_decode(name_node)}"
        current = current.parent
    return None


def extract(tree, file_path):
    symbols = []
    calls = []
    file_str = str(file_path)

    for node in walk(tree.root_node):

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")

            if not name_node:
                continue

            name = _decode(name_node)

            symbols.append({
                "name": name,
                "qualified_name": f"{file_path}::{name}",
                "type": "function",
                "language": "python",
                "file": file_str,
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1
            })

        elif node.type == "call":
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
