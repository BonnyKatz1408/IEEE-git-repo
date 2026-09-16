def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def extract(tree, file_path):
    symbols = []

    for node in walk(tree.root_node):

        # function foo() {}
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")

            if name_node:
                name = name_node.text.decode()

                symbols.append({
                    "name": name,
                    "qualified_name": f"{file_path}::{name}"
                    "type": "function",
                    "language": "typescript",
                    "file": str(file_path),
                    "line": node.start_point[0] + 1
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
                    name = name_node.text.decode()

                    symbols.append({
                        "name": name,
                        "qualified_name": f"{file_path}::{name}"
                        "type": "function",
                        "language": "typescript",
                        "file": str(file_path),
                        "line": child.start_point[0] + 1
                    })

    return symbols




    