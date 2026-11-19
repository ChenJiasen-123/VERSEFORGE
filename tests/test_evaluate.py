import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluate import run
from poetry_agent.client import MockClient
from poetry_agent.core import Task


class EvaluationTests(unittest.TestCase):
    def test_custom_tasks_control_both_arms_without_leaking_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            tasks = [Task('嫉妒', max_lines=14)]
            result = {'poem': {'title': '题', 'lines': ['灯']}}
            with patch('evaluate.compose', return_value=result) as compose:
                folder = run(MockClient(), Path(temp)/'run', tasks=tasks, max_revisions=0,
                             generation_thinking='disabled')
            self.assertEqual(compose.call_count, 2)
            self.assertEqual({c.kwargs['aesthetic'] for c in compose.call_args_list}, {False, True})
            for call in compose.call_args_list:
                self.assertEqual(call.args[0], tasks[0])
                self.assertEqual(call.kwargs['max_revisions'], 0)
                self.assertEqual(call.kwargs['generation_thinking'], 'disabled')
            blind = (folder/'blind.json').read_text(encoding='utf-8')
            self.assertNotIn('generation_thinking', blind)
            self.assertNotIn('experiment_settings', blind)
            self.assertIn('prompts only', (folder/'README.txt').read_text(encoding='utf-8'))

    def test_invalid_custom_settings_fail_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            for kwargs in ({'tasks': []}, {'tasks': ['invalid']}, {'max_revisions': True},
                           {'generation_thinking': 'auto'}, {'budget': 0}):
                folder = Path(temp)/'run'
                with self.assertRaises(ValueError): run(MockClient(), folder, **kwargs)
                self.assertFalse(folder.exists())

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
