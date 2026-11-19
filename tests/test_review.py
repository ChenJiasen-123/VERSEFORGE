import json
import unittest
from poetry_agent.aesthetics import review


class Reply:
    def __init__(self, problem, reason='前文动作改变了灯的关系，熟悉不等于多余'):
        self.problem = problem
        self.reason = reason
    def complete(self, *args, **kwargs):
        return {'content': json.dumps(dict(decision='keep', preserve='动作', quote='灯',
                    problem=self.problem, suggestion='', tradeoff='', keep_reason=self.reason))}


class ReviewTests(unittest.TestCase):
    def test_unsupported_keep_is_not_accepted_as_completed_review(self):
        with self.assertRaises(ValueError):
            review({'lines': ['灯']}, {}, Reply('物件熟悉', ''), 10)

    def test_keep_without_countercheck_is_incomplete(self):
        with self.assertRaises(ValueError):
            review({'lines': ['灯']}, {}, Reply(''), 10)

    def test_keep_can_record_doubt_without_forcing_revision(self):
        result = review({'lines': ['灯']}, {}, Reply('物件熟悉，但在前文开关动作中承担关系，因此保留'), 10)
        self.assertEqual(result['assessment']['decision'], 'keep')
