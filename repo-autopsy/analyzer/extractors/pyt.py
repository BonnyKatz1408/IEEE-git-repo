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


def extract(tree, file_path):
    symbols = []
    calls = []
    file_str = str(file_path)

    def visit(node, caller):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")

            if name_node:
                name = _decode(name_node)
                qualified_name = f"{file_path}::{name}"
                symbols.append({
                    "name": name,
                    "qualified_name": qualified_name,
                    "type": "function",
                    "language": "python",
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })
                caller = qualified_name

        elif node.type == "call":
            name = _callee_name(node.child_by_field_name("function"))
            if name:
                calls.append({
                    "name": name,
                    "caller": caller,
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })

        for child in node.children:
            visit(child, caller)

    visit(tree.root_node, None)
    return symbols, calls
