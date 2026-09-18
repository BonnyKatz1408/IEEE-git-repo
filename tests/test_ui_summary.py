import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / 'repo-autopsy'))

from analyzer.report import build_report, build_ui_summary
from analyzer.map_layout import build_map_layout


class UiSummaryTests(unittest.TestCase):
    def test_build_ui_summary_exposes_repo_overview_and_guidance(self):
        report = {
            'overview': {
                'languages': ['python'],
                'file_count': 12,
                'function_count': 8,
                'module_count': 3,
            },
            'entry_points': [
                {'qualified_name': 'pkg.main::main', 'file': 'pkg/main.py', 'line': 10, 'name': 'main', 'hotspot_score': 0.7},
            ],
            'hotspots': {
                'files': [
                    {'file': 'pkg/main.py', 'hotspot_score': 0.9, 'loc': 120, 'number_of_defined_functions': 2},
                ],
                'functions': [
                    {'qualified_name': 'pkg.main::main', 'file': 'pkg/main.py', 'line': 10, 'hotspot_score': 0.8, 'loc': 80, 'fan_in': 1, 'fan_out': 2},
                ],
            },
            'major_modules': [
                {'module': 'pkg', 'total_loc': 200, 'hotspot_score': 0.9, 'description': 'Core package logic'},
            ],
            'reading_order': [
                {'file': 'pkg/main.py', 'score': 0.9, 'reason': ['likely entry point']},
            ],
            'flows': [
                {'entry_point': 'pkg.main::main', 'tree': {'node': 'pkg.main::main', 'children': []}},
            ],
        }

        summary = build_ui_summary(report)

        self.assertEqual(summary['overview']['file_count'], 12)
        self.assertEqual(summary['entry_points'][0]['qualified_name'], 'pkg.main::main')
        self.assertEqual(summary['top_hotspots'][0]['file'], 'pkg/main.py')
        self.assertEqual(summary['major_modules'][0]['module'], 'pkg')
        self.assertEqual(summary['reading_order'][0]['file'], 'pkg/main.py')
        self.assertEqual(summary['flows'][0]['entry_point'], 'pkg.main::main')

    def test_build_report_normalizes_paths_to_repo_relative_form(self):
        root = Path('/tmp/repo-root')
        repo_file = root / 'src' / 'api.py'
        repo_file.parent.mkdir(parents=True, exist_ok=True)
        repo_file.write_text('def run():\n    return 1\n', encoding='utf-8')

        analysis = {
            'functions': [{'file': str(repo_file), 'name': 'run', 'qualified_name': f'{repo_file}::run', 'line': 1, 'loc': 2, 'fan_in': 0, 'fan_out': 0, 'hotspot_score': 0.5, 'is_test': False}],
            'edges': [{'from': f'{repo_file}::run', 'to': f'{repo_file}::run'}],
            'function_metrics': [{'file': str(repo_file), 'qualified_name': f'{repo_file}::run', 'name': 'run', 'line': 1, 'loc': 2, 'fan_in': 0, 'fan_out': 0, 'hotspot_score': 0.5, 'is_test': False}],
            'file_metrics': [{'file': str(repo_file), 'loc': 2, 'number_of_defined_functions': 1, 'incoming_dependencies': 0, 'outgoing_dependencies': 0, 'incoming_call_dependencies': 0, 'outgoing_call_dependencies': 0, 'internal_edges': 0, 'hotspot_score': 0.5, 'is_test': False}],
            'import_edges': [],
            'architecture_edges': [],
            'modules': [{'module': 'src', 'files': [str(repo_file)], 'incoming_dependencies': 0, 'outgoing_dependencies': 0, 'internal_edges': 0, 'external_edges': 0, 'incoming_import_dependencies': 0, 'outgoing_import_dependencies': 0, 'incoming_call_dependencies': 0, 'outgoing_call_dependencies': 0}],
            'function_edges': [{'from': f'{repo_file}::run', 'to': f'{repo_file}::run'}],
            'likely_entry_points': [{'qualified_name': f'{repo_file}::run', 'file': str(repo_file), 'line': 1, 'name': 'run', 'fan_in': 0, 'fan_out': 0, 'hotspot_score': 0.5, 'is_test': False, 'structural_hints': ['main']}],
            'cycles': [],
            'potential_roots': [],
            'dependency_chains': [{'node': f'{repo_file}::run', 'children': []}],
            'onboarding_ranking': [{'name': 'run', 'file': str(repo_file), 'score': 0.4, 'reason': ['likely entry point']}],
            'imports': [],
            'unresolved_imports': [],
        }

        report = build_report(analysis, {str(repo_file): 2}, {'.py': 'python'}, root)

        self.assertEqual(report['file_metrics'][0]['file'], 'src/api.py')
        self.assertEqual(report['function_metrics'][0]['qualified_name'], 'src/api.py::run')
        self.assertEqual(report['entry_points'][0]['file'], 'src/api.py')
        self.assertEqual(report['ui_summary']['entry_points'][0]['file'], 'src/api.py')
        self.assertEqual(report['function_edges'][0]['from'], 'src/api.py::run')
        self.assertEqual(report['modules'][0]['files'], ['src/api.py'])
        self.assertNotIn('/tmp/repo-root', json.dumps(report))

        layout = build_map_layout(report)
        self.assertEqual(layout['buildings'][0]['path'], 'src/api.py')
        self.assertTrue(layout['modules'])


if __name__ == '__main__':
    unittest.main()
