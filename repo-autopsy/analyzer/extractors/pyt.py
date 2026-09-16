def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def extract(tree, file_path):
    symbols = []

    for node in walk(tree.root_node):

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")

            if not name_node:
                continue

            name = name_node.text.decode()

            symbols.append({
                "name": name,
                "qualified_name": f"{file_path}::{name}",
                "type": "function",
                "language": "python",
                "file": str(file_path),
                "line": node.start_point[0] + 1
            })

    return symbols