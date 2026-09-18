import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / 'repo-autopsy'))

from analyzer.report import build_ui_summary


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


if __name__ == '__main__':
    unittest.main()
