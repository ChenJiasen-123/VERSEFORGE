import json
from pathlib import Path
import unittest
from unittest.mock import patch

from poetry_agent.revision_scope import inspect_revision
from poetry_agent.core import compose, Task
from test_workflow import SequenceClient, output


class RevisionScopeTests(unittest.TestCase):
    def trial(self, number):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / f'runs/modern-workflow-trial-03/{number:02}.json').read_text(encoding='utf-8'))
        return [row['poem']['lines'] for row in data['history']]

    def test_actual_two_line_revision_with_two_extra_characters_is_eligible(self):
        before, after = self.trial(2)
        report = inspect_revision(before, after)
        self.assertEqual(report['changed_lines'], 2)
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(report['meaning_preservation_verified'])

    def test_actual_shortened_rewrite_is_outside_local_scope(self):
        before, after = self.trial(1)
        self.assertLess(sum(map(len, after)), sum(map(len, before)))
        self.assertEqual(inspect_revision(before, after)['status'], 'failed')

    def test_line_deletion_insertion_and_relineation_are_not_free(self):
        before = ['甲', '乙', '丙', '丁', '戊', '己']
        for after in (['甲', '己'], ['甲', '乙', '新', '丙', '丁', '戊', '己'], ['甲乙丙', '丁戊己']):
            self.assertEqual(inspect_revision(before, after)['status'], 'failed')
        self.assertEqual(inspect_revision(before, before)['changed_lines'], 0)

    def test_two_revisions_share_original_anchor_not_individual_allowances(self):
        before = [f'第{i}行文字' for i in range(12)]
        first = ['改' + row[1:] if i < 4 else row for i, row in enumerate(before)]
        second = ['变' + row[1:] if 4 <= i < 8 else row for i, row in enumerate(first)]
        client = SequenceClient([output(before), output(first), output(second)])
        client.mock = False
        with patch('poetry_agent.core.review', return_value={'assessment': {'decision': 'revise'}}), \
             patch('poetry_agent.core.compare', return_value={'assessment': {'choice': 'b'}}):
            result = compose(Task('修改范围'), client, max_revisions=2, aesthetic=True)
        self.assertEqual(result['history'][1]['revision_scope_check']['status'], 'passed')
        self.assertEqual(result['history'][2]['revision_scope_check']['changed_lines'], 8)
        self.assertEqual(result['poem']['lines'], first)

