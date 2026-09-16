def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def _decode(node):
    return node.text.decode() if node else None


def _type_name(type_node):
    if type_node is None:
        return None
    if type_node.type in ("type_identifier", "identifier"):
        return _decode(type_node)
    name = None
    for child in walk(type_node):
        if child.type in ("type_identifier", "identifier"):
            name = _decode(child)
    return name


def extract(tree, file_path):
    symbols = []
    calls = []
    file_str = str(file_path)

    def visit(node, caller, class_name):
        if node.type == "class_declaration":
            class_name_node = node.child_by_field_name("name")
            if class_name_node:
                class_name = _decode(class_name_node)

        if node.type == "method_declaration" and class_name:
            method_name_node = node.child_by_field_name("name")
            if method_name_node:
                method_name = _decode(method_name_node)
                qualified_name = f"{file_path}::{class_name}.{method_name}"
                symbols.append({
                    "name": f"{class_name}.{method_name}",
                    "qualified_name": qualified_name,
                    "type": "method",
                    "language": "java",
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })
                caller = qualified_name

        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            if name_node:
                calls.append({
                    "name": _decode(name_node),
                    "caller": caller,
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })

        elif node.type == "object_creation_expression":
            name = _type_name(node.child_by_field_name("type"))
            if name:
                calls.append({
                    "name": name,
                    "caller": caller,
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })

        for child in node.children:
            visit(child, caller, class_name)

    visit(tree.root_node, None, None)
    return symbols, calls
