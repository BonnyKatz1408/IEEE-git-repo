from tree_sitter_language_pack import get_parser

def parse_file(path,language):
    parser = get_parser(language)
    with open(path,"rb") as f:
        source = f.read()
    return parser.parse(source)