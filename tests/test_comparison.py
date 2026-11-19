import json
import unittest
from poetry_agent.aesthetics import compare


class Reply:
    def __init__(self, quote): self.quote = quote
    def complete(self, *args, **kwargs):
        return {'content': json.dumps({'choice': 'b', 'quote_a': '認取',
                                      'quote_b': self.quote, 'reason': '动作改变'})}


class ComparisonTests(unittest.TestCase):
    def test_candidate_relationship_is_explicit_in_request_and_result(self):
        class Capture(Reply):
            def complete(self, system, user, **kwargs):
                self.payload = json.loads(user)
                return super().complete(system, user, **kwargs)
        for relation in ('independent', 'revision'):
            client = Capture('起望')
            result = compare({'lines': ['認取']}, {'lines': ['起望']}, {}, client, 10, relation=relation)
            self.assertEqual(client.payload['comparison_relation'], relation)
            self.assertEqual(result['comparison_relation'], relation)

    def test_invalid_relationship_cannot_make_an_api_call(self):
        class NoCall:
            def complete(self, *args, **kwargs): raise AssertionError('unexpected API call')
        with self.assertRaises(ValueError):
            compare({'lines': ['甲']}, {'lines': ['乙']}, {}, NoCall(), 10, relation='unknown')
    def test_exact_short_quote_works_across_punctuation_styles(self):
        a, b = {'lines': ['認取簷牙。']}, {'lines': ['起望簷牙']}
        self.assertEqual(compare(a, b, {}, Reply('起望'), 10)['assessment']['choice'], 'b')

    def test_added_punctuation_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            compare({'lines': ['認取簷牙。']}, {'lines': ['起望簷牙']}, {}, Reply('起望簷牙。'), 10)
