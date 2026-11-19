import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluate import run
from poetry_agent.client import MockClient


class EvaluationTests(unittest.TestCase):
    def test_partial_pair_keeps_success_without_leaking_error(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'run'
            result = {'poem': {'title': '题', 'lines': ['灯']}}
            with patch('evaluate.compose', side_effect=[result, RuntimeError('secret-detail')]):
                run(MockClient(), folder)
            raw = (folder / 'raw.json').read_text(encoding='utf-8')
            self.assertNotIn('secret-detail', raw)
            self.assertEqual(len(json.loads(raw)), 2)
            self.assertEqual(json.loads((folder / 'blind.json').read_text()), [])

    def test_complete_packet_hides_arms_and_does_not_assign_ratings(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = run(MockClient(), Path(temp) / 'run', count=4)
            blind = json.loads((folder / 'blind.json').read_text(encoding='utf-8'))
            self.assertEqual(len(blind), 4)
            for pair in blind:
                self.assertIsNone(pair['judgment']['preference'])
                self.assertEqual(len(pair['samples']), 2)
                for sample in pair['samples']:
                    self.assertEqual(set(sample), {'sample_id', 'poem'})
