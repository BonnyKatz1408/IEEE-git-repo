def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def extract(tree, file_path):
    symbols = []

    for node in walk(tree.root_node):

        if node.type != "function_definition":
            continue

        declarator = node.child_by_field_name("declarator")

        if not declarator:
            continue

        name_node = None

        for child in walk(declarator):
            if child.type == "identifier":
                name_node = child
                break

        if not name_node:
            continue

        name = name_node.text.decode()

        symbols.append({
            "name": name,
            "qualified_name": f"{file_path}::{name}",
            "type": "function",
            "language": "c",
            "file": str(file_path),
            "line": node.start_point[0] + 1
        })

    return symbols