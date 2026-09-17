#iterator
def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def _decode(node):
    return node.text.decode() if node else None


def _callee_receiver(node):
    receiver = node.child_by_field_name("object")
    return _decode(receiver)


def _enclosing_caller(node, file_path):
    method_name = None
    class_name = None
    current = node.parent

    while current:
        if current.type == "method_declaration" and method_name is None:
            method_name = _decode(current.child_by_field_name("name"))
        elif current.type == "class_declaration" and class_name is None:
            class_name = _decode(current.child_by_field_name("name"))
        current = current.parent

    if method_name and class_name:
        return f"{file_path}::{class_name}.{method_name}"
    return None


# Extract relevant functions and calls from the Java syntax tree.
def extract(tree, file_path):
    symbols = []
    calls = []
    file_str = str(file_path)

    for node in walk(tree.root_node):
        if node.type == "class_declaration":
            class_name = _decode(node.child_by_field_name("name"))
            if not class_name:
                continue

            for child in walk(node):
                if child.type != "method_declaration":
                    continue
                method_name = _decode(child.child_by_field_name("name"))
                if not method_name:
                    continue

                symbols.append({
                    "name": f"{class_name}.{method_name}",
                    "type": "method",
                    "language": "java",
                    "file": file_str,
                    "line": child.start_point[0] + 1,
                    "end_line": child.end_point[0] + 1
                })

        elif node.type == "method_invocation":
            name = _decode(node.child_by_field_name("name"))
            if name:
                calls.append({
                    "name": name,
                    "caller": _enclosing_caller(node, file_path),
                    "receiver": _callee_receiver(node),
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })

    return symbols, calls