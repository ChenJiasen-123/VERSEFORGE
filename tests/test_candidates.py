import unittest
from unittest.mock import patch
from poetry_agent.core import Task
from poetry_agent.client import MockClient
from poetry_agent.candidates import compose_candidates


class CandidateTests(unittest.TestCase):
    def test_inconsistent_real_comparison_does_not_replace_current_candidate(self):
        from tests.test_bidirectional_compare import Client
        results = [{'poem': {'lines': ['甲']}, 'issues': []}, {'poem': {'lines': ['乙']}, 'issues': []}]
        client = Client(['b', 'b'])
        client.mock = False
        with patch('poetry_agent.candidates.compose', side_effect=results):
            result = compose_candidates(Task('题'), client, count=2)
        self.assertEqual(result['selected_candidate'], 1)
        self.assertEqual(result['candidate_selection'][0]['selection_status'], 'disagreement')
        self.assertEqual(len(result['candidate_runs']), 2)

    def test_separate_compositions_are_not_labeled_as_revisions(self):
        results = [{'poem': {'lines': ['甲']}, 'issues': []}, {'poem': {'lines': ['乙']}, 'issues': []}]
        client = MockClient()
        client.mock = False
        with patch('poetry_agent.candidates.compose', side_effect=results), patch('poetry_agent.candidates.compare', return_value={'assessment': {'choice': 'tie'}}) as compare:
            compose_candidates(Task('题'), client, count=2)
        self.assertEqual(compare.call_args.kwargs['relation'], 'independent')
    def test_hard_constraints_take_priority_without_comparing_broken_candidate(self):
        results = [{'poem': {'lines': ['甲']}, 'issues': ['缺词']},
                   {'poem': {'lines': ['乙']}, 'issues': []}]
        client = MockClient()
        client.mock = False
        with patch('poetry_agent.candidates.compose', side_effect=results), patch('poetry_agent.candidates.compare') as compare:
            result = compose_candidates(Task('题'), client, count=2)
        self.assertEqual(result['selected_candidate'], 2)
        compare.assert_not_called()

    def test_comparison_failure_keeps_first_and_all_candidates(self):
        results = [{'poem': {'lines': ['甲']}, 'issues': []}, {'poem': {'lines': ['乙']}, 'issues': []}]
        client = MockClient()
        client.mock = False
        with patch('poetry_agent.candidates.compose', side_effect=results), patch('poetry_agent.candidates.compare', side_effect=ValueError('比较引用无效')):
            result = compose_candidates(Task('题'), client, count=2)
        self.assertEqual(result['selected_candidate'], 1)
        self.assertEqual(len(result['candidate_runs']), 2)
        self.assertEqual(result['candidate_selection'][0]['failure_code'], 'quote_not_found')

    def test_first_candidate_runtime_error_falls_through_to_second_candidate(self):
        second = {'poem': {'title': '乙', 'lines': ['乙']}, 'issues': []}
        client = MockClient()
        client.mock = False
        with patch('poetry_agent.candidates.compose', side_effect=[RuntimeError('模型输出未正常结束（length），本次输出未采用'), second]):
            result = compose_candidates(Task('题'), client, count=2)
        self.assertEqual(result['poem'], second['poem'])
        self.assertEqual(len(result['candidate_runs']), 1)
        self.assertEqual(result['candidate_selection'][0]['error'], 'generation_failed')
        self.assertIn('length', result['candidate_selection'][0]['detail'])
