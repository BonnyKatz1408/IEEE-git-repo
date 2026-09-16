#iterator
def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)

#extract relevant functions, store em in symbols and return dict
def extract(tree, file_path):
    symbols = []
    for node in walk(tree.root_node):
        if node.type != "class_declaration":
            continue
        class_name_node = node.child_by_field_name("name")
        if not class_name_node:
            continue
        class_name = class_name_node.text.decode()
        for child in walk(node):

            if child.type != "method_declaration":
                continue

            method_name_node = child.child_by_field_name("name")

            if not method_name_node:
                continue

            method_name = method_name_node.text.decode()

            symbols.append({
                "name": f"{class_name}.{method_name}",
                "type": "method",
                "language": "java",
                "file": str(file_path),
                "line": child.start_point[0] + 1
            })
    return symbols