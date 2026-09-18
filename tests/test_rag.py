import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / 'repo-autopsy') not in sys.path:
    sys.path.insert(0, str(ROOT / 'repo-autopsy'))

from analyzer.rag import build_rag_index, retrieve_chunks, build_context_packet, generate_answer


class RagLayerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='rag-tests-')
        self.repo_root = Path(self.tmpdir) / 'sample-repo'
        self.repo_root.mkdir(parents=True, exist_ok=True)
        (self.repo_root / 'README.md').write_text('# Sample repo\n\nThis project parses files and describes architecture.\n', encoding='utf-8')
        (self.repo_root / 'src').mkdir(exist_ok=True)
        (self.repo_root / 'src' / 'parser.py').write_text(
            'def parse_structure():\n    return "parsing"\n\n'
            'class Parser:\n    def run(self):\n        return parse_structure()\n',
            encoding='utf-8',
        )
        (self.repo_root / 'src' / 'api.py').write_text(
            'def on_request_post():\n    return parse_structure()\n',
            encoding='utf-8',
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_build_rag_index_uses_repo_relative_paths(self):
        report = {
            'entry_points': [{'qualified_name': 'src/api.py::on_request_post', 'file': 'src/api.py'}],
            'hotspots': {'files': [{'file': 'src/parser.py', 'hotspot_score': 0.9}]},
            'modules': [{'module': 'src', 'files': ['src/parser.py', 'src/api.py']}],
            'file_metrics': [
                {'file': 'src/parser.py', 'loc': 40, 'number_of_defined_functions': 1, 'hotspot_score': 0.9},
                {'file': 'src/api.py', 'loc': 20, 'number_of_defined_functions': 1, 'hotspot_score': 0.4},
            ],
        }

        index = build_rag_index(report, self.repo_root)
        files = {chunk['file'] for chunk in index['chunks']}
        self.assertIn('src/parser.py', files)
        self.assertIn('src/api.py', files)
        self.assertNotIn(str(self.repo_root), json.dumps(index))

    def test_retrieve_priority_prefers_symbol_and_path_matches(self):
        report = {
            'entry_points': [{'qualified_name': 'src/api.py::on_request_post', 'file': 'src/api.py'}],
            'hotspots': {'files': [{'file': 'src/parser.py', 'hotspot_score': 0.9}]},
            'modules': [{'module': 'src', 'files': ['src/parser.py', 'src/api.py']}],
            'file_metrics': [
                {'file': 'src/parser.py', 'loc': 40, 'number_of_defined_functions': 1, 'hotspot_score': 0.9},
                {'file': 'src/api.py', 'loc': 20, 'number_of_defined_functions': 1, 'hotspot_score': 0.4},
            ],
        }

        index = build_rag_index(report, self.repo_root)
        matches = retrieve_chunks('parse_structure', index['chunks'], report)
        self.assertTrue(matches)
        self.assertIn('parse_structure', matches[0]['symbol'].lower())

    def test_repository_overview_prioritizes_readme_and_diverse_files(self):
        report = {
            'overview': {'repository': 'sample-repo', 'languages': ['python'], 'file_count': 3, 'function_count': 2, 'module_count': 1},
            'entry_points': [{'qualified_name': 'src/api.py::on_request_post', 'file': 'src/api.py'}],
            'hotspots': {'files': [{'file': 'src/parser.py', 'hotspot_score': 0.9}]},
            'modules': [{'module': 'src', 'files': ['src/parser.py', 'src/api.py']}],
            'file_metrics': [
                {'file': 'src/parser.py', 'loc': 40, 'number_of_defined_functions': 1, 'hotspot_score': 0.9},
                {'file': 'src/api.py', 'loc': 20, 'number_of_defined_functions': 1, 'hotspot_score': 0.4},
            ],
        }
        index = build_rag_index(report, self.repo_root)
        matches = retrieve_chunks('What is this repo?', index['chunks'], report)
        self.assertTrue(matches)
        self.assertEqual(matches[0]['file'], 'README.md')
        self.assertEqual(len({chunk['file'] for chunk in matches}), len(matches))

    def test_context_packet_contains_deterministic_overview_and_intent(self):
        report = {'overview': {'repository': 'sample-repo', 'languages': ['python'], 'file_count': 3, 'function_count': 2, 'module_count': 1}}
        packet = build_context_packet('What is this repo?', report, [])
        self.assertEqual(packet['intent'], 'repository-overview')
        self.assertEqual(packet['deterministic_context']['overview']['repository'], 'sample-repo')

    def test_generate_answer_uses_grounded_fallback(self):
        report = {
            'overview': {'repository': 'sample-repo', 'languages': ['python'], 'file_count': 3, 'function_count': 2, 'module_count': 1},
            'entry_points': [{'qualified_name': 'src/api.py::on_request_post', 'file': 'src/api.py'}],
            'hotspots': {'files': [{'file': 'src/parser.py', 'hotspot_score': 0.9}]},
            'modules': [{'module': 'src', 'files': ['src/parser.py', 'src/api.py']}],
            'file_metrics': [
                {'file': 'src/parser.py', 'loc': 40, 'number_of_defined_functions': 1, 'hotspot_score': 0.9},
                {'file': 'src/api.py', 'loc': 20, 'number_of_defined_functions': 1, 'hotspot_score': 0.4},
            ],
        }

        index = build_rag_index(report, self.repo_root)
        packet = build_context_packet('Where does request processing start?', report, index['chunks'])
        answer = generate_answer('Where does request processing start?', report, index['chunks'])
        self.assertIn('src/api.py', answer['answer'])
        self.assertTrue(answer['sources'])
        self.assertIn('deterministic', answer['answer'].lower())

    def test_structural_questions_use_deterministic_analysis_without_retrieval(self):
        report = {
            'overview': {'repository': 'sample-repo', 'languages': ['python'], 'file_count': 3, 'function_count': 2, 'module_count': 1},
            'entry_points': [{'qualified_name': 'src/api.py::on_request_post', 'file': 'src/api.py', 'line': 1, 'name': 'on_request_post'}],
            'reading_order': [{'file': 'src/api.py'}],
            'file_metrics': [{'file': 'src/api.py', 'loc': 20, 'defined_functions': ['src/api.py::on_request_post'], 'hotspot_score': 0.4}],
            'function_metrics': [],
            'import_edges': [{'from': 'src/api.py', 'to': 'src/parser.py'}],
            'function_edges': [],
            'modules': [{'module': 'src', 'files': ['src/api.py', 'src/parser.py']}],
        }
        answer = generate_answer('Where should I start?', report, [])
        self.assertEqual(answer['mode'], 'deterministic-analysis')
        self.assertEqual(answer['retrieval']['count'], 0)
        self.assertIn('src/api.py', answer['answer'])
        self.assertEqual(answer['sections'][0]['title'], 'Entry points')
        self.assertEqual(answer['sections'][0]['items'][0]['path'], 'src/api.py')

        answer = generate_answer('What does this file depend on?', report, [], {'type': 'file', 'file': 'src/api.py'})
        self.assertEqual(answer['mode'], 'deterministic-analysis')
        self.assertIn('src/parser.py', answer['answer'])
        self.assertTrue(answer['sections'])


if __name__ == '__main__':
    unittest.main()
