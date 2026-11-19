import json
import unittest
from probe_lineation import run


class Client:
    def __init__(self, choices): self.choices = iter(choices)
    def complete(self, system, user, **kwargs):
        payload = json.loads(user)
        return {'content': json.dumps({'choice': next(self.choices),
            'quote_a': payload['a']['lines'][0], 'quote_b': payload['b']['lines'][0],
            'reason': '机械协议测试，不是文学判断。'})}


class LineationProbeTests(unittest.TestCase):
    def probe(self):
        return [{'id': 'fixture', 'task': {'genre': 'modern'},
                 'a': {'title': '甲', 'lines': ['再等', '一次']},
                 'b': {'title': '乙', 'lines': ['再等一次']}}]

    def test_choice_is_mapped_to_original_after_swap(self):
        row = run(self.probe(), Client(['a', 'b']))['records'][0]
        self.assertTrue(row['order_consistent'])
        self.assertEqual([x['original_choice'] for x in row['orders']], ['a', 'a'])

    def test_first_position_bias_is_not_consistency(self):
        self.assertFalse(run(self.probe(), Client(['a', 'a']))['records'][0]['order_consistent'])

    def test_changed_wording_is_rejected_before_call(self):
        probes = self.probe()
        probes[0]['b']['lines'] = ['再多等一次']
        with self.assertRaises(ValueError): run(probes, Client([]))
