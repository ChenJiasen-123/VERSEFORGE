import json
import tempfile
import unittest
from pathlib import Path
from review_meter import review_files
from poetry_agent.context_review import body_hash


class MeterFileTests(unittest.TestCase):
    def test_reports_failure_without_certifying_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run, ledger, output = [root / n for n in ('run.json', 'ledger.json', 'output.json')]
            lines = ['東' * 7] * 4
            run.write_text(json.dumps({'task': {'genre': 'qijue', 'qijue_pattern': 'ping_rhyme'},
                                       'poem': {'lines': lines}}), encoding='utf-8')
            ledger.write_text(json.dumps({'body_sha256': body_hash(lines), 'reviewer_kind': 'assistant',
                                          'decisions': []}), encoding='utf-8')
            report = review_files(run, ledger, output)
            self.assertEqual(report['basic_target_check']['status'], 'failed')
            self.assertFalse(report['overall_literary_quality_verified'])
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                review_files(run, ledger, output)
            self.assertEqual(before, output.read_bytes())
