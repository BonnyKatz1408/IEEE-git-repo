def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def _decode(node):
    return node.text.decode() if node else None


def _callee_name(node):
    func = node.child_by_field_name("function")
    if func is None:
        func = node.child_by_field_name("constructor")
    if func is None:
        return None

    if func.type == "identifier":
        return _decode(func)

    if func.type in ("member_expression", "optional_chain"):
        prop = func.child_by_field_name("property")
        if prop:
            return _decode(prop)

    if func.type == "parenthesized_expression":
        for child in func.named_children:
            return _callee_name_from_expr(child)

    return _callee_name_from_expr(func)


def _callee_name_from_expr(node):
    if node is None:
        return None
    if node.type == "identifier":
        return _decode(node)
    if node.type in ("member_expression", "optional_chain"):
        prop = node.child_by_field_name("property")
        if prop:
            return _decode(prop)
    name = None
    for child in walk(node):
        if child.type in ("identifier", "property_identifier"):
            name = _decode(child)
    return name


def _callee_receiver(node):
    func = node.child_by_field_name("function")
    if func is None:
        func = node.child_by_field_name("constructor")
    if func and func.type in ("member_expression", "optional_chain"):
        receiver = func.child_by_field_name("object")
        return _decode(receiver)
    return None


def _enclosing_caller(node, file_path):
    current = node.parent
    while current:
        if current.type == "function_declaration":
            name_node = current.child_by_field_name("name")
            if name_node:
                return f"{file_path}::{_decode(name_node)}"

        if current.type == "arrow_function":
            parent = current.parent
            if parent and parent.type == "variable_declarator":
                name_node = parent.child_by_field_name("name")
                if name_node:
                    return f"{file_path}::{_decode(name_node)}"

        current = current.parent
    return None


def extract(tree, file_path):
    symbols = []
    calls = []
    file_str = str(file_path)

    for node in walk(tree.root_node):

        # function foo() {}
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")

            if name_node:
                name = _decode(name_node)

                symbols.append({
                    "name": name,
                    "qualified_name": f"{file_path}::{name}",
                    "type": "function",
                    "language": "typescript",
                    "file": file_str,
                        "line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1
                })

        # const foo = () => {}
        elif node.type == "lexical_declaration":
            for child in node.children:

                if child.type != "variable_declarator":
                    continue

                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")

                if not name_node or not value_node:
                    continue

                if value_node.type == "arrow_function":
                    name = _decode(name_node)

                    symbols.append({
                        "name": name,
                        "qualified_name": f"{file_path}::{name}",
                        "type": "function",
                        "language": "typescript",
                        "file": file_str,
                        "line": child.start_point[0] + 1,
                        "end_line": value_node.end_point[0] + 1
                    })

        if node.type in ("call_expression", "new_expression"):
            name = _callee_name(node)
            if name:
                calls.append({
                    "name": name,
                    "caller": _enclosing_caller(node, file_path),
                    "receiver": _callee_receiver(node),
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })

    return symbols, calls
