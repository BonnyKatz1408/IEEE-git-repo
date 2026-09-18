from tree_sitter_language_pack import get_parser

_PARSERS = {}


def parse_file(path, language):
    parser = _PARSERS.get(language)
    if parser is None:
        parser = get_parser(language)
        _PARSERS[language] = parser
    with open(path, "rb") as handle:
        source = handle.read()
    return parser.parse(source), source
