def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def extract(tree, file_path):
    symbols = []

    for node in walk(tree.root_node):

        if node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")

            if not declarator:
                continue

            name = None

            for child in walk(declarator):
                if child.type == "identifier":
                    name = child.text.decode()

                elif child.type == "field_identifier":
                    name = child.text.decode()

            if not name:
                continue

            symbols.append({
                "name": name,
                "qualified_name": f"{file_path}::{name}",
                "type": "function",
                "language": "cpp",
                "file": str(file_path),
                "line": node.start_point[0] + 1
            })

    return symbols