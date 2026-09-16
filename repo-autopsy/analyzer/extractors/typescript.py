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


def extract(tree, file_path):
    symbols = []
    calls = []
    file_str = str(file_path)

    def visit(node, caller):
        # function foo() {}
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _decode(name_node)
                qualified_name = f"{file_path}::{name}"
                symbols.append({
                    "name": name,
                    "qualified_name": qualified_name,
                    "type": "function",
                    "language": "typescript",
                    "file": file_str,
                    "line": node.start_point[0] + 1
                })
                caller = qualified_name

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
                    qualified_name = f"{file_path}::{name}"
                    symbols.append({
                        "name": name,
                        "qualified_name": qualified_name,
                        "type": "function",
                        "language": "typescript",
                        "file": file_str,
                        "line": child.start_point[0] + 1
                    })

        if node.type == "arrow_function":
            parent = node.parent
            if parent and parent.type == "variable_declarator":
                name_node = parent.child_by_field_name("name")
                if name_node:
                    caller = f"{file_path}::{_decode(name_node)}"

        if node.type in ("call_expression", "new_expression"):
            name = _callee_name(node)
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
