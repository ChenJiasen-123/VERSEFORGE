import json
import unittest
from poetry_agent.aesthetics import compare


class Reply:
    def __init__(self, quote): self.quote = quote
    def complete(self, *args, **kwargs):
        return {'content': json.dumps({'choice': 'b', 'quote_a': '認取',
                                      'quote_b': self.quote, 'reason': '动作改变'})}


class ComparisonTests(unittest.TestCase):
    def test_exact_short_quote_works_across_punctuation_styles(self):
        a, b = {'lines': ['認取簷牙。']}, {'lines': ['起望簷牙']}
        self.assertEqual(compare(a, b, {}, Reply('起望'), 10)['assessment']['choice'], 'b')

    def test_added_punctuation_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            compare({'lines': ['認取簷牙。']}, {'lines': ['起望簷牙']}, {}, Reply('起望簷牙。'), 10)
