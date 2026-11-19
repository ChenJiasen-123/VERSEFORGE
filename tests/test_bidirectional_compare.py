import json
import unittest
from unittest.mock import patch
from poetry_agent.aesthetics import compare_bidirectional


class Client:
    def __init__(self, choices): self.choices, self.calls = iter(choices), []
    def complete(self, system, user, **kwargs):
        data = json.loads(user)
        self.calls.append((system, data, kwargs))
        choice = next(self.choices)
        if choice == 'error': raise RuntimeError('service error')
        return {'content': json.dumps({'choice': choice, 'quote_a': data['a']['lines'][0],
            'quote_b': data['b']['lines'][0], 'reason': '测试协议，不作文学判断。'})}


class BidirectionalTests(unittest.TestCase):
    a, b = {'lines': ['甲']}, {'lines': ['乙']}

    def test_consistent_preference_maps_back_to_original_candidate(self):
        client = Client(['b', 'a'])
        result = compare_bidirectional(self.a, self.b, {}, client, 10)
        self.assertEqual(result['assessment']['choice'], 'b')
        self.assertEqual(result['selection_status'], 'consensus')
        self.assertEqual(client.calls[1][1]['a'], self.b)

    def test_first_position_bias_abstains_instead_of_replacing(self):
        result = compare_bidirectional(self.a, self.b, {}, Client(['a', 'a']), 10)
        self.assertEqual(result['assessment']['choice'], 'tie')
        self.assertEqual(result['selection_status'], 'disagreement')
        self.assertFalse(result['order_consistent'])

    def test_failure_and_real_tie_are_distinct(self):
        incomplete = compare_bidirectional(self.a, self.b, {}, Client(['b', 'error']), 10)
        tied = compare_bidirectional(self.a, self.b, {}, Client(['tie', 'tie']), 10)
        self.assertEqual(incomplete['selection_status'], 'incomplete')
        self.assertEqual(tied['selection_status'], 'consensus')
        self.assertIsNone(incomplete['order_consistent'])

    def test_reversing_revision_preserves_actual_chronology(self):
        client = Client(['b', 'a'])
        compare_bidirectional(self.a, self.b, {}, client, 10, relation='revision')
        self.assertEqual([c[1]['earlier_candidate'] for c in client.calls], ['a', 'b'])
        self.assertIn('本次B是较早稿，A是后续修订稿', client.calls[1][0])

    def test_expired_budget_does_not_start_second_call(self):
        client = Client(['b'])
        with patch('poetry_agent.aesthetics.time.monotonic', side_effect=[0, 0, 11, 11]):
            result = compare_bidirectional(self.a, self.b, {}, client, 10)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result['orders'][1]['failure_code'], 'comparison_budget_exhausted')
        self.assertEqual(result['assessment']['choice'], 'tie')
